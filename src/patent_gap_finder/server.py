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
# Lifespan — DB init / shutdown
# ──────────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(server):
    """Server lifespan handler — initializes and tears down the database."""
    try:
        from patent_gap_finder.db.connection import init_db, close_db
        await init_db()
        logger.info("Database initialized")
    except Exception as e:
        logger.warning("Database init skipped (not configured): %s", e)
    yield
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
        "3. get_session(session_id) — retrieve full analysis results"
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

    Supported input formats:
      - Local PDF: "/path/to/paper.pdf"
      - arXiv ID: "2301.07041"
      - arXiv URL: "https://arxiv.org/abs/2301.07041"

    Args:
        source: Path to a PDF file or an arXiv ID/URL.
        extract_with_ai: If True, use Gemini AI for claim extraction
            (requires GEMINI_API_KEY). Default: False.

    Returns:
        Parsed paper data with session_id if persisted.
        On error: structured error dict.
    """
    return await _parse_paper_impl(source, extract_with_ai=extract_with_ai)


@mcp.tool()
async def classify_ipc(session_id: str) -> dict:
    """Classify extracted claims into IPC/CPC patent codes using Gemini AI.

    Requires a session with AI-extracted claims (run parse_paper with
    extract_with_ai=true first).

    Returns IPC/CPC mappings for each claim, top codes across all claims,
    and search keywords for patent database queries.

    Args:
        session_id: UUID of an analysis session from parse_paper.

    Returns:
        IPC classification results with mappings, top codes, and keywords.
        On error: structured error dict.
    """
    return await _classify_ipc_impl(session_id)


@mcp.tool()
async def get_session(session_id: str) -> dict:
    """Retrieve a past analysis session with all results.

    Returns the full session data including paper metadata, extracted
    claims (both heuristic and AI), IPC classifications, and processing
    status.

    Args:
        session_id: UUID of the analysis session.

    Returns:
        Complete session data with claims and status.
        On error: structured error dict.
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
        "version": "0.2.0",
        "server": "patent-gap-finder",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "tools_available": [
            "parse_paper",
            "classify_ipc",
            "get_session",
        ],
        "phase": 2,
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
    """Estimated remaining daily Gemini free-tier quota.

    The free tier allows 1,500 requests per day. This resource tracks
    usage from the current server session (resets on restart).
    """
    daily_limit = 1500
    try:
        from patent_gap_finder.ai.gemini_client import get_gemini_client
        client = get_gemini_client()
        used = client.total_requests
        return {
            "daily_limit": daily_limit,
            "used_this_session": used,
            "estimated_remaining": max(0, daily_limit - used),
            "note": (
                "This tracks the current server session only. "
                "Actual quota resets daily at Google's discretion."
            ),
        }
    except Exception:
        return {
            "daily_limit": daily_limit,
            "used_this_session": 0,
            "estimated_remaining": daily_limit,
            "note": "Gemini client not initialized.",
        }


# ──────────────────────────────────────────────────────────────────────
# Entrypoint
# ──────────────────────────────────────────────────────────────────────

def main() -> None:
    """Run the MCP server.

    Transport is determined by the ``MCP_TRANSPORT`` environment variable:
      - ``stdio`` (default): for Claude Desktop integration
      - ``streamable-http``: for web client integration
    """
    transport = os.getenv("MCP_TRANSPORT", "stdio").lower()
    host = os.getenv("MCP_HOST", "0.0.0.0")
    port = int(os.getenv("MCP_PORT", "8000"))

    logger.info(
        "Starting Patent Gap Finder MCP server v0.2.0 (transport=%s)", transport
    )

    if transport == "streamable-http":
        mcp.run(transport="streamable-http", host=host, port=port)
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
