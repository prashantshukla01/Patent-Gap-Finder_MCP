"""FastMCP server entrypoint for the Patent Gap Finder.

Registers all MCP tools and resources.  Supports both stdio transport
(for Claude Desktop) and streamable-http transport (for web clients).

Usage:
    # stdio transport (Claude Desktop)
    uv run python -m patent_gap_finder.server

    # streamable-http transport
    MCP_TRANSPORT=streamable-http uv run python -m patent_gap_finder.server
"""

from __future__ import annotations

import logging
import os
import sys
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from dotenv import load_dotenv
from fastmcp import FastMCP

from patent_gap_finder.tools.parse_paper import parse_paper as _parse_paper_impl
from patent_gap_finder.tools.classify_ipc import classify_ipc as _classify_ipc_impl
from patent_gap_finder.tools.get_session import get_session as _get_session_impl
from patent_gap_finder.tools.search_prior_art import search_prior_art as _search_prior_art_impl
from patent_gap_finder.tools.get_search_status import get_search_status as _get_search_status_impl
from patent_gap_finder.tools.map_landscape import map_landscape as _map_landscape_impl
from patent_gap_finder.tools.find_whitespace import find_whitespace as _find_whitespace_impl

# Load environment variables from .env if present
load_dotenv()

# ──────────────────────────────────────────────────────────────────────
# Logging configuration
# ──────────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    stream=sys.stderr,  # MCP uses stdout for protocol messages
)
logger = logging.getLogger("patent_gap_finder")


# ──────────────────────────────────────────────────────────────────────
# Lifespan — DB + Redis + Qdrant + Embedding model init / shutdown
# ──────────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(server):
    """Server lifespan handler — initializes and tears down services."""
    # Database
    try:
        from patent_gap_finder.db.connection import init_db
        await init_db()
        logger.info("Database initialized")
    except Exception as e:
        logger.warning("Database init skipped (not configured): %s", e)

    # Redis
    try:
        from patent_gap_finder.cache.redis_client import get_redis_client
        redis = get_redis_client()
        stats = await redis.get_cache_stats()
        logger.info("Redis connected: %s", stats)
    except Exception as e:
        logger.warning("Redis init skipped: %s", e)

    # Qdrant
    try:
        from patent_gap_finder.embeddings.qdrant_store import ensure_collection_exists
        await ensure_collection_exists()
        logger.info("Qdrant collection ready")
    except Exception as e:
        logger.warning("Qdrant init skipped: %s", e)

    # Embedding model warmup
    try:
        from patent_gap_finder.embeddings.embedding_engine import get_embedding_model
        get_embedding_model()
        logger.info("Embedding model loaded")
    except Exception as e:
        logger.warning("Embedding model warmup skipped: %s", e)

    yield

    # Shutdown
    try:
        from patent_gap_finder.cache.redis_client import get_redis_client
        redis = get_redis_client()
        await redis.close()
    except Exception:
        pass
    try:
        from patent_gap_finder.db.connection import close_db
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
        "Workflow:\n"
        "1. parse_paper(source, extract_with_ai=true) — parse and extract claims\n"
        "2. classify_ipc(session_id) — classify claims into IPC/CPC codes\n"
        "3. search_prior_art(session_id) — search USPTO + EPO for prior art\n"
        "4. get_search_status(job_id) — poll search progress\n"
        "5. map_landscape(session_id) — embed patents and cluster landscape\n"
        "6. find_whitespace(session_id) — detect patentable gaps\n"
        "7. get_session(session_id) — retrieve full analysis results"
    ),
    lifespan=lifespan,
)


# ──────────────────────────────────────────────────────────────────────
# Tools
# ──────────────────────────────────────────────────────────────────────

@mcp.tool()
async def parse_paper(source: str, extract_with_ai: bool = False) -> dict:
    """Parse a research paper and extract structured content + patent claims.

    Accepts a local PDF file path or an arXiv identifier (bare ID or URL).
    Returns structured data including title, authors, abstract, sections,
    and candidate patentable claims.

    When extract_with_ai=True, uses Google Gemini to extract high-quality
    patent-style claims and creates a database session for tracking.

    Args:
        source: Path to a PDF file or an arXiv ID/URL.
        extract_with_ai: If True, use Gemini AI for claim extraction.

    Returns:
        Parsed paper data with session_id if persisted.
    """
    return await _parse_paper_impl(source, extract_with_ai=extract_with_ai)


@mcp.tool()
async def classify_ipc(session_id: str) -> dict:
    """Classify extracted claims into IPC/CPC patent codes using Gemini AI.

    Requires a session with AI-extracted claims (run parse_paper with
    extract_with_ai=true first).

    Args:
        session_id: UUID of an analysis session from parse_paper.

    Returns:
        IPC classification results with mappings, top codes, and keywords.
    """
    return await _classify_ipc_impl(session_id)


@mcp.tool()
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
async def get_search_status(job_id: str) -> dict:
    """Poll the status of a patent search job.

    Args:
        job_id: UUID of the search job from search_prior_art.

    Returns:
        Structured status with progress and completion info.
    """
    return await _get_search_status_impl(job_id)


@mcp.tool()
async def map_landscape(session_id: str) -> dict:
    """Build a patent landscape map from search results.

    Embeds all patents using sentence-transformers, clusters with HDBSCAN,
    and labels clusters with Gemini AI. Requires Phase 3 completion.

    Args:
        session_id: UUID of the analysis session.

    Returns:
        Landscape map with clusters, patent counts, and cluster labels.
    """
    return await _map_landscape_impl(session_id)


@mcp.tool()
async def find_whitespace(
    session_id: str,
    min_novelty_score: float = 0.5,
) -> dict:
    """Detect patentable white-space opportunities.

    Compares AI-extracted paper claims against the patent landscape to
    find regions with no dense prior art coverage. Uses Gemini for
    novelty assessment of genuine candidates.

    Args:
        session_id: UUID of the analysis session.
        min_novelty_score: Minimum novelty score threshold (0.0-1.0).

    Returns:
        White-space report with ranked opportunities and Gemini assessments.
    """
    return await _find_whitespace_impl(session_id, min_novelty_score=min_novelty_score)


@mcp.tool()
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

@mcp.resource("patent://health")
def health_check() -> dict:
    """Server health check — returns status and version information."""
    return {
        "status": "healthy",
        "version": "0.4.0",
        "server": "patent-gap-finder",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "tools_available": [
            "parse_paper",
            "classify_ipc",
            "search_prior_art",
            "get_search_status",
            "map_landscape",
            "find_whitespace",
            "get_session",
        ],
        "phase": 4,
    }


@mcp.resource("patent://usage")
def usage_stats() -> dict:
    """Gemini API usage statistics for the current server session."""
    try:
        from patent_gap_finder.ai.gemini_client import get_gemini_client
        client = get_gemini_client()
        return {
            "total_requests": client.total_requests,
            "total_prompt_chars": client.total_prompt_chars,
            "total_response_chars": client.total_response_chars,
            "model": "gemini-1.5-flash",
        }
    except Exception:
        return {
            "total_requests": 0,
            "total_prompt_chars": 0,
            "total_response_chars": 0,
            "note": "Gemini client not initialized (GEMINI_API_KEY may not be set)",
        }


@mcp.resource("patent://quota-status")
def quota_status() -> dict:
    """Estimated remaining daily Gemini free-tier quota."""
    daily_limit = 1500
    try:
        from patent_gap_finder.ai.gemini_client import get_gemini_client
        client = get_gemini_client()
        used = client.total_requests
        return {
            "daily_limit": daily_limit,
            "used_this_session": used,
            "estimated_remaining": max(0, daily_limit - used),
        }
    except Exception:
        return {
            "daily_limit": daily_limit,
            "used_this_session": 0,
            "estimated_remaining": daily_limit,
            "note": "Gemini client not initialized.",
        }


@mcp.resource("patent://cache-stats")
async def cache_stats() -> dict:
    """Redis cache statistics."""
    try:
        from patent_gap_finder.cache.redis_client import get_redis_client
        redis = get_redis_client()
        return await redis.get_cache_stats()
    except Exception:
        return {"status": "unavailable"}


@mcp.resource("patent://qdrant-stats")
async def qdrant_stats() -> dict:
    """Qdrant vector store statistics."""
    try:
        from patent_gap_finder.embeddings.qdrant_store import get_collection_stats
        return await get_collection_stats()
    except Exception:
        return {"status": "unavailable"}


# ──────────────────────────────────────────────────────────────────────
# Entrypoint
# ──────────────────────────────────────────────────────────────────────

def main() -> None:
    """Run the MCP server."""
    transport = os.getenv("MCP_TRANSPORT", "stdio").lower()
    host = os.getenv("MCP_HOST", "0.0.0.0")
    port = int(os.getenv("MCP_PORT", "8000"))

    logger.info(
        "Starting Patent Gap Finder MCP server v0.4.0 (transport=%s)", transport
    )

    if transport == "streamable-http":
        mcp.run(transport="streamable-http", host=host, port=port)
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
