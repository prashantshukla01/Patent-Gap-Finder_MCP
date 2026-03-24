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
from datetime import datetime, timezone

from dotenv import load_dotenv
from fastmcp import FastMCP

from patent_gap_finder.tools.parse_paper import parse_paper as _parse_paper_impl

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
# FastMCP application
# ──────────────────────────────────────────────────────────────────────

mcp = FastMCP(
    "patent-gap-finder",
    instructions=(
        "Patent Gap Finder helps researchers discover patentable white-space "
        "opportunities from their research papers. Start by using the "
        "parse_paper tool to extract structured content from a PDF or arXiv paper."
    ),
)


# ──────────────────────────────────────────────────────────────────────
# Tools
# ──────────────────────────────────────────────────────────────────────

@mcp.tool()
async def parse_paper(source: str) -> dict:
    """Parse a research paper and extract structured content.

    Accepts a local PDF file path or an arXiv identifier (bare ID or URL).
    Returns structured data including title, authors, abstract, sections,
    and candidate patentable claims identified via heuristic analysis.

    Supported input formats:
      - Local PDF: "/path/to/paper.pdf"
      - arXiv ID: "2301.07041"
      - arXiv URL: "https://arxiv.org/abs/2301.07041"

    The candidate_claims field contains sentences scored for patent
    potential using signal phrase detection, technical verb analysis,
    and structural heuristics. These are preliminary candidates —
    use classify_ipc and search_prior_art for deeper analysis.

    Args:
        source: Path to a PDF file or an arXiv ID/URL.

    Returns:
        A dict with keys: title, authors, abstract, sections,
        candidate_claims, source_url, file_hash, parsed_at.
        On error: {"error": True, "message": str, "type": str}.
    """
    return await _parse_paper_impl(source)


# ──────────────────────────────────────────────────────────────────────
# Resources
# ──────────────────────────────────────────────────────────────────────

@mcp.resource("patent://health")
def health_check() -> dict:
    """Server health check — returns status and version information.

    Returns:
        Dict with server status, version, and available tools.
    """
    return {
        "status": "healthy",
        "version": "0.1.0",
        "server": "patent-gap-finder",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "tools_available": [
            "parse_paper",
            # Future Phase 2+ tools:
            # "classify_ipc",
            # "search_prior_art",
            # "map_landscape",
            # "find_whitespace",
            # "draft_claims",
        ],
        "phase": 1,
    }


# ──────────────────────────────────────────────────────────────────────
# Entrypoint
# ──────────────────────────────────────────────────────────────────────

def main() -> None:
    """Run the MCP server.

    Transport is determined by the ``MCP_TRANSPORT`` environment variable:
      - ``stdio`` (default): for Claude Desktop integration
      - ``streamable-http``: for web client integration

    For streamable-http, ``MCP_HOST`` and ``MCP_PORT`` control the
    bind address (defaults: ``0.0.0.0:8000``).
    """
    transport = os.getenv("MCP_TRANSPORT", "stdio").lower()
    host = os.getenv("MCP_HOST", "0.0.0.0")
    port = int(os.getenv("MCP_PORT", "8000"))

    logger.info(
        "Starting Patent Gap Finder MCP server (transport=%s)", transport
    )

    if transport == "streamable-http":
        mcp.run(transport="streamable-http", host=host, port=port)
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
