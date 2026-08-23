"""FastMCP server entrypoint for the Patent Gap Finder.

Registers all MCP tools and resources.  Supports both stdio transport
(for Claude Desktop) and streamable-http transport (for web clients).

Phase 5 additions:
- draft_claims and export_report tools (9 total)
- Structured JSON logging
- Health check with dependency verification
- API key authentication middleware (HTTP transport)
- Per-IP rate limiting via Redis (HTTP transport)

Usage:
    # stdio transport (Claude Desktop)
    uv run python -m server

    # streamable-http transport
    MCP_TRANSPORT=streamable-http uv run python -m server
"""

from __future__ import annotations

import json
import logging
import os
import sys
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from dotenv import load_dotenv
from fastmcp import FastMCP
from starlette.middleware import Middleware as StarletteMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse as StarletteJSONResponse

from observability.tracer import trace_tool
from tools.parse_paper import parse_paper as _parse_paper_impl
from tools.classify_ipc import classify_ipc as _classify_ipc_impl
from tools.get_session import get_session as _get_session_impl
from tools.search_prior_art import search_prior_art as _search_prior_art_impl
from tools.get_search_status import get_search_status as _get_search_status_impl
from tools.map_landscape import map_landscape as _map_landscape_impl
from tools.find_whitespace import find_whitespace as _find_whitespace_impl
from tools.draft_claims import draft_claims as _draft_claims_impl
from tools.export_report import export_report as _export_report_impl
from tools.save_claims import save_claims as _save_claims_impl
from tools.save_classification import save_classification as _save_classification_impl
from tools.save_whitespace import save_whitespace as _save_whitespace_impl
from tools.save_drafted_claims import save_drafted_claims as _save_drafted_claims_impl

# Load environment variables from .env if present
load_dotenv()

# ──────────────────────────────────────────────────────────────────────
# Structured JSON logging
# ──────────────────────────────────────────────────────────────────────


class JSONFormatter(logging.Formatter):
    """Structured JSON log formatter for production deployments."""

    def format(self, record: logging.LogRecord) -> str:
        return json.dumps({
            "timestamp": self.formatTime(record),
            "level": record.levelname,
            "module": record.module,
            "message": record.getMessage(),
            "session_id": getattr(record, "session_id", None),
        })


def _configure_logging() -> None:
    """Set up logging based on environment configuration."""
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    transport = os.getenv("MCP_TRANSPORT", "stdio").lower()

    if transport == "streamable-http":
        # Use structured JSON logging for HTTP transport (production)
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(JSONFormatter())
    else:
        # Use human-readable logging for stdio transport (development)
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(
            logging.Formatter("%(asctime)s [%(name)s] %(levelname)s: %(message)s")
        )

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(getattr(logging, log_level, logging.INFO))


_configure_logging()
logger = logging.getLogger("patent_gap_finder")


# ──────────────────────────────────────────────────────────────────────
# Lifespan — DB + Redis + Qdrant + Embedding model init / shutdown
# ──────────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(server):
    """Server lifespan handler — initializes and tears down services."""
    import asyncio

    # Database
    try:
        from db.connection import init_db
        await asyncio.wait_for(init_db(), timeout=2.0)
        logger.info("Database initialized")
    except Exception as e:
        logger.warning("Database init skipped (not configured or offline): %s", e)

    # Redis
    try:
        from cache.redis_client import get_redis_client
        redis = get_redis_client()
        stats = await asyncio.wait_for(redis.get_cache_stats(), timeout=1.0)
        logger.info("Redis connected: %s", stats)
    except Exception as e:
        logger.warning("Redis init skipped: %s", e)

    # Qdrant
    try:
        from embeddings.qdrant_store import ensure_collection_exists
        await asyncio.wait_for(ensure_collection_exists(), timeout=1.0)
        logger.info("Qdrant collection ready")
    except Exception as e:
        logger.warning("Qdrant init skipped: %s", e)

    # Embedding model warmup
    try:
        from embeddings.embedding_engine import get_embedding_model
        get_embedding_model()
        logger.info("Embedding model loaded")
    except Exception as e:
        logger.warning("Embedding model warmup skipped: %s", e)

    # Observability
    try:
        from observability.tracer import get_langfuse_client, is_langfuse_enabled
        if is_langfuse_enabled():
            get_langfuse_client()
            logger.info("Langfuse observability initialized")
        else:
            logger.info("Langfuse observability running in no-op mode")
    except Exception as e:
        logger.warning("Observability initialization skipped: %s", e)

    yield

    # Shutdown
    try:
        from cache.redis_client import get_redis_client
        redis = get_redis_client()
        await redis.close()
    except Exception:
        pass
    try:
        from db.connection import close_db
        await close_db()
    except Exception:
        pass


# ──────────────────────────────────────────────────────────────────────
# FastMCP application
# ──────────────────────────────────────────────────────────────────────

mcp = FastMCP(
    "patent-gap-finder",
    instructions=(
        "Patent Gap Finder helps researchers discover patentable white-space "
        "opportunities from their research papers.\n\n"
        "YOU (the LLM) do the AI reasoning. The server does parsing, DB, "
        "embeddings, and clustering. Follow this workflow:\n\n"
        "1. parse_paper(source/content) — parse paper, get ai_instructions\n"
        "2. [YOU] Extract patent claims from the paper content\n"
        "3. save_claims(session_id, claims) — save your extracted claims\n"
        "4. classify_ipc(session_id) — get claims + IPC instructions\n"
        "5. [YOU] Classify claims into IPC/CPC codes\n"
        "6. save_classification(session_id, mappings) — save classifications\n"
        "7. search_prior_art(session_id) — search for prior art\n"
        "8. get_search_status(job_id) — poll search progress\n"
        "9. map_landscape(session_id) — cluster patents\n"
        "10. find_whitespace(session_id) — detect gaps + get assessment instructions\n"
        "11. [YOU] Assess novelty of each whitespace opportunity\n"
        "12. save_whitespace(session_id, assessments) — save assessments\n"
        "13. draft_claims(session_id) — get opportunities + drafting instructions\n"
        "14. [YOU] Draft USPTO patent claims\n"
        "15. save_drafted_claims(session_id, claim_sets) — save claims\n"
        "16. export_report(session_id) — download PDF report\n"
        "17. get_session(session_id) — retrieve full results"
    ),
    lifespan=lifespan,
)


# ──────────────────────────────────────────────────────────────────────
# Tools
# ──────────────────────────────────────────────────────────────────────

@mcp.tool()
@trace_tool("parse_paper")
async def parse_paper(
    source: str = "",
    content: str = "",
    title: str = "",
) -> dict:
    """Parse a research paper and extract structured content + patent claims.

    Accepts a local PDF file path, an arXiv identifier, or raw text content.
    Returns structured data with heuristic claims and AI extraction instructions.

    After calling this tool, read the ai_instructions in the response,
    extract patent claims from the paper content, then call save_claims.

    Args:
        source: Path to a PDF file or an arXiv ID/URL. May be empty if
            content is provided.
        content: Raw text content of the paper (e.g. pasted from an
            uploaded PDF in Claude Desktop). When provided, source is
            ignored and no file-system access is needed.
        title: Optional paper title to use when providing raw content.

    Returns:
        Parsed paper data with session_id and ai_instructions.
    """
    return await _parse_paper_impl(
        source, content=content, title=title
    )


@mcp.tool()
@trace_tool("classify_ipc")
async def classify_ipc(session_id: str) -> dict:
    """Get claims with IPC/CPC classification instructions.

    Returns AI-extracted claims from the session with instructions for
    you to classify them into IPC codes. After classifying, call
    save_classification with the results.

    Args:
        session_id: UUID of an analysis session with saved claims.

    Returns:
        Claims data with IPC classification instructions.
    """
    return await _classify_ipc_impl(session_id)


@mcp.tool()
@trace_tool("save_claims")
async def save_claims(
    session_id: str,
    claims: list[dict],
    paper_summary: str = "",
    primary_domain: str = "",
) -> dict:
    """Save your extracted patent claims to the database.

    Call this after parse_paper returns ai_instructions. Pass the claims
    you extracted from the paper content.

    Args:
        session_id: UUID from parse_paper response.
        claims: List of claim dicts, each with: claim_text, claim_type,
            technical_domain, novelty_basis, source_section, confidence.
        paper_summary: 2-3 sentence technical summary of the paper.
        primary_domain: Main technical field (e.g. 'machine learning').

    Returns:
        Confirmation with claim count and next step.
    """
    return await _save_claims_impl(
        session_id, claims, paper_summary=paper_summary,
        primary_domain=primary_domain,
    )


@mcp.tool()
@trace_tool("save_classification")
async def save_classification(
    session_id: str,
    mappings: list[dict],
    top_ipc_codes: list[str] | None = None,
    search_keywords: list[str] | None = None,
) -> dict:
    """Save your IPC/CPC classifications to the database.

    Call this after classify_ipc returns classification instructions.

    Args:
        session_id: UUID of the analysis session.
        mappings: List of mapping dicts, each with: claim_text, primary_ipc,
            secondary_ipc, cpc_code, confidence, rationale.
        top_ipc_codes: Deduplicated IPC codes ranked by frequency.
        search_keywords: 10-15 terms for USPTO patent search.

    Returns:
        Confirmation with classification count and next step.
    """
    return await _save_classification_impl(
        session_id, mappings,
        top_ipc_codes=top_ipc_codes,
        search_keywords=search_keywords,
    )


@mcp.tool()
@trace_tool("search_prior_art")
async def search_prior_art(session_id: str) -> dict:
    """Search USPTO, EPO, and Google Patents for prior art.

    Requires Phase 2 completion (classify_ipc). Dispatches an async search
    job and returns immediately with a job_id for polling.

    Args:
        session_id: UUID of the analysis session.

    Returns:
        Job dispatch confirmation with job_id for polling.
    """
    return await _search_prior_art_impl(session_id)


@mcp.tool()
@trace_tool("get_search_status")
async def get_search_status(job_id: str) -> dict:
    """Poll the status of a patent search job.

    Args:
        job_id: UUID of the search job from search_prior_art.

    Returns:
        Structured status with progress and completion info.
    """
    return await _get_search_status_impl(job_id)


@mcp.tool()
@trace_tool("map_landscape")
async def map_landscape(session_id: str) -> dict:
    """Build a patent landscape map from search results.

    Embeds all patents using sentence-transformers, clusters with HDBSCAN,
    and auto-labels clusters from patent titles. Requires search completion.

    Args:
        session_id: UUID of the analysis session.

    Returns:
        Landscape map with clusters, patent counts, and cluster labels.
    """
    return await _map_landscape_impl(session_id)


@mcp.tool()
@trace_tool("find_whitespace")
async def find_whitespace(
    session_id: str,
    min_novelty_score: float = 0.5,
) -> dict:
    """Detect patentable white-space opportunities.

    Compares AI-extracted paper claims against the patent landscape.
    Returns gap candidates with instructions for you to assess novelty.
    After assessing, call save_whitespace with the results.

    Args:
        session_id: UUID of the analysis session.
        min_novelty_score: Minimum novelty score threshold (0.0-1.0).

    Returns:
        White-space report with opportunities and assessment instructions.
    """
    return await _find_whitespace_impl(session_id, min_novelty_score=min_novelty_score)


@mcp.tool()
@trace_tool("save_whitespace")
async def save_whitespace(
    session_id: str,
    assessments: list[dict],
) -> dict:
    """Save your novelty assessments for whitespace opportunities.

    Call this after find_whitespace returns assessment instructions.

    Args:
        session_id: UUID of the analysis session.
        assessments: List of assessment dicts, each with: opportunity_id,
            novelty_assessment, confidence, recommended_scope, ipc_codes.

    Returns:
        Confirmation with update count and next step.
    """
    return await _save_whitespace_impl(session_id, assessments)


@mcp.tool()
@trace_tool("draft_claims")
async def draft_claims(
    session_id: str,
    min_novelty_score: float = 0.5,
) -> dict:
    """Get whitespace opportunities with USPTO claim drafting instructions.

    Returns opportunities with nearest patent context and drafting rules.
    After drafting claims, call save_drafted_claims with the results.

    Args:
        session_id: UUID of the analysis session.
        min_novelty_score: Minimum novelty score for claim drafting (0.0-1.0).

    Returns:
        Opportunities with drafting instructions and USPTO rules.
    """
    return await _draft_claims_impl(session_id, min_novelty_score=min_novelty_score)


@mcp.tool()
@trace_tool("save_drafted_claims")
async def save_drafted_claims(
    session_id: str,
    claim_sets: list[dict],
) -> dict:
    """Save your drafted USPTO patent claims to the database.

    Call this after draft_claims returns drafting instructions.

    Args:
        session_id: UUID of the analysis session.
        claim_sets: List of claim set dicts, each with: opportunity_id,
            claims (list of {claim_number, claim_text, claim_type, depends_on,
            patent_claim_category}), drafting_rationale, distinguishing_features.

    Returns:
        Confirmation with claim count and next step.
    """
    return await _save_drafted_claims_impl(session_id, claim_sets)


@mcp.tool()
@trace_tool("export_report")
async def export_report(session_id: str) -> dict:
    """Generate and download a PDF patent gap analysis report.

    Produces a structured, attorney-ready PDF with cover page, executive
    summary, patent landscape overview, whitespace opportunities, drafted
    claims, and methodology sections.

    Args:
        session_id: UUID of the analysis session.

    Returns:
        Report metadata with base64-encoded PDF content.
    """
    return await _export_report_impl(session_id)


@mcp.tool()
@trace_tool("get_session")
async def get_session(session_id: str) -> dict:
    """Retrieve a past analysis session with all results.

    Returns the full session data including paper metadata, extracted
    claims, IPC classifications, patent search results, and status.

    Args:
        session_id: UUID of the analysis session.

    Returns:
        Complete session data with claims and status.
    """
    return await _get_session_impl(session_id)


# ──────────────────────────────────────────────────────────────────────
# Resources
# ──────────────────────────────────────────────────────────────────────

async def _run_health_checks() -> dict:
    """Shared health check logic used by both MCP resource and HTTP route."""
    checks: dict[str, str] = {}

    # PostgreSQL
    try:
        from db.connection import get_db_session
        from sqlalchemy import text

        async with get_db_session() as db:
            await db.execute(text("SELECT 1"))
        checks["postgres"] = "ok"
    except Exception as e:
        checks["postgres"] = f"error: {str(e)}"

    # Redis
    try:
        from cache.redis_client import get_redis_client
        redis = get_redis_client()
        conn = await redis._get_connection()
        if conn:
            await conn.ping()
            checks["redis"] = "ok"
        else:
            checks["redis"] = "unavailable"
    except Exception as e:
        checks["redis"] = f"error: {str(e)}"

    # Qdrant
    try:
        from embeddings.qdrant_store import get_collection_stats
        await get_collection_stats()
        checks["qdrant"] = "ok"
    except Exception as e:
        checks["qdrant"] = f"error: {str(e)}"

    # Embedding model
    try:
        from embeddings.embedding_engine import get_embedding_model
        get_embedding_model()
        checks["embedding_model"] = "ok"
    except Exception as e:
        checks["embedding_model"] = f"error: {str(e)}"

    all_ok = all(v == "ok" for v in checks.values())
    return {
        "status": "healthy" if all_ok else "degraded",
        "checks": checks,
        "version": "1.0.0",
        "tools_available": [
            "parse_paper", "classify_ipc", "search_prior_art",
            "get_search_status", "map_landscape", "find_whitespace",
            "draft_claims", "export_report", "get_session",
        ],
        "phase": 5,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@mcp.resource("patent://health")
async def health_check() -> dict:
    """Server health check with dependency verification (MCP resource)."""
    return await _run_health_checks()


@mcp.custom_route("/health", methods=["GET"])
async def health_http_endpoint(request: Request) -> StarletteJSONResponse:
    """Standalone HTTP health endpoint for Docker/Railway health checks."""
    result = await _run_health_checks()
    status_code = 200 if result["status"] == "healthy" else 503
    return StarletteJSONResponse(result, status_code=status_code)


@mcp.resource("patent://usage")
def usage_stats() -> dict:
    """Server info — no AI API keys required.

    This server uses the host LLM (Claude Desktop) for all reasoning.
    No API keys are needed on the server side.
    """
    return {
        "architecture": "instruct-then-save",
        "ai_model": "host LLM (Claude Desktop)",
        "server_role": "data + compute engine (parsing, DB, embeddings, clustering)",
        "note": "All AI reasoning is performed by the host LLM. No API key required.",
        "tools": [
            "parse_paper", "save_claims", "classify_ipc", "save_classification",
            "search_prior_art", "get_search_status", "map_landscape",
            "find_whitespace", "save_whitespace", "draft_claims",
            "save_drafted_claims", "export_report", "get_session",
        ],
    }


@mcp.resource("patent://quota-status")
def quota_status() -> dict:
    """API quota status — no quota limits apply.

    This server does not make any AI API calls.
    Rate limits only apply to EPO (2000 req/day) and SerpAPI (100/month free).
    """
    return {
        "ai_api": "none — host LLM handles all reasoning",
        "epo_daily_limit": 2000,
        "serpapi_monthly_limit": 100,
        "lens_org": "unlimited with LENS_API_KEY, skipped without it",
    }


@mcp.resource("patent://cache-stats")
async def cache_stats() -> dict:
    """Redis cache statistics."""
    try:
        from cache.redis_client import get_redis_client
        redis = get_redis_client()
        return await redis.get_cache_stats()
    except Exception:
        return {"status": "unavailable"}


@mcp.resource("patent://qdrant-stats")
async def qdrant_stats() -> dict:
    """Qdrant vector store statistics."""
    try:
        from embeddings.qdrant_store import get_collection_stats
        return await get_collection_stats()
    except Exception:
        return {"status": "unavailable"}


# ──────────────────────────────────────────────────────────────────────
# Middleware wiring (HTTP transport only)
# ──────────────────────────────────────────────────────────────────────

def _get_middleware() -> list[StarletteMiddleware]:
    """Build the middleware stack for HTTP transport."""
    from starlette.middleware.cors import CORSMiddleware
    from middleware.auth import APIKeyMiddleware
    from middleware.rate_limiter import RateLimitMiddleware

    middlewares: list[StarletteMiddleware] = []

    # CORS middleware (outermost — allows cross-origin requests from web clients)
    middlewares.append(
        StarletteMiddleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_methods=["*"],
            allow_headers=["*"],
            expose_headers=["*"],
        )
    )

    # Rate limiting (runs before auth)
    middlewares.append(StarletteMiddleware(RateLimitMiddleware))

    # API key authentication
    api_key = os.getenv("MCP_API_KEY")
    if api_key:
        middlewares.append(StarletteMiddleware(APIKeyMiddleware, api_key=api_key))
        logger.info("API key authentication enabled")
    else:
        logger.warning(
            "MCP_API_KEY not set — HTTP transport has NO authentication. "
            "Set MCP_API_KEY for production deployments."
        )

    return middlewares


from starlette.responses import JSONResponse


@mcp.custom_route("/health", methods=["GET"])
async def health_endpoint(request):
    """Health check endpoint for Docker / Oracle Cloud / load balancer."""
    return JSONResponse({"status": "healthy", "service": "patent-gap-finder"})


# ──────────────────────────────────────────────────────────────────────
# Entrypoint
# ──────────────────────────────────────────────────────────────────────

def main() -> None:
    """Run the MCP server."""
    transport = os.getenv("MCP_TRANSPORT", "stdio").lower()
    host = os.getenv("MCP_HOST", "0.0.0.0")
    port = int(os.getenv("PORT") or os.getenv("MCP_PORT") or "8000")

    logger.info(
        "Starting Patent Gap Finder MCP server v1.0.0 (transport=%s)", transport
    )

    if transport == "streamable-http":
        import uvicorn

        middlewares = _get_middleware()
        app = mcp.streamable_http_app()
        for mw in middlewares:
            app.add_middleware(mw.cls, **mw.kwargs)

        logger.info(
            "HTTP server starting on %s:%d with %d middleware(s)",
            host, port, len(middlewares),
        )
        uvicorn.run(app, host=host, port=port, log_level="info")
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
