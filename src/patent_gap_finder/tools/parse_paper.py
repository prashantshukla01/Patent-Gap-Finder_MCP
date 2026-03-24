"""MCP tool wrapper for the parse_paper capability.

Routes input to the appropriate parser (local PDF or arXiv) and returns
a structured ParsedPaper dict.  All exceptions are caught and returned
as structured error dicts — the MCP layer never sees unhandled exceptions.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from patent_gap_finder.parsers.arxiv_parser import is_arxiv_source, parse_arxiv
from patent_gap_finder.parsers.pdf_parser import parse_pdf

logger = logging.getLogger(__name__)


async def parse_paper(source: str) -> dict:
    """Parse a research paper from a file path or arXiv reference.

    This is the core MCP tool implementation.  It detects whether *source*
    is a local PDF file or an arXiv reference, delegates to the appropriate
    parser, and returns the parsed paper as a serializable dict.

    Args:
        source: Either a local file path to a PDF, or an arXiv identifier.
            Supported arXiv formats:
            - Bare ID: ``"2301.07041"``
            - Abs URL: ``"https://arxiv.org/abs/2301.07041"``
            - PDF URL: ``"https://arxiv.org/pdf/2301.07041"``

    Returns:
        A dict serialization of :class:`ParsedPaper` on success, or an
        error dict with keys ``{"error": True, "message": str, "type": str}``
        on failure.
    """
    source = source.strip()

    if not source:
        return {
            "error": True,
            "message": "Empty source provided. Please supply a PDF file path or arXiv ID/URL.",
            "type": "validation_error",
        }

    try:
        if is_arxiv_source(source):
            logger.info("Detected arXiv source: %s", source)
            parsed = await parse_arxiv(source)
        else:
            # Treat as local file path
            path = Path(source).expanduser().resolve()
            if not path.exists():
                return {
                    "error": True,
                    "message": f"File not found: {path}",
                    "type": "file_not_found",
                }
            if not path.suffix.lower() == ".pdf":
                return {
                    "error": True,
                    "message": f"Expected a PDF file, got: {path.suffix}",
                    "type": "validation_error",
                }
            logger.info("Parsing local PDF: %s", path)
            parsed = parse_pdf(str(path))

        return parsed.model_dump(mode="json")

    except FileNotFoundError as e:
        logger.error("File not found: %s", e)
        return {
            "error": True,
            "message": str(e),
            "type": "file_not_found",
        }
    except ValueError as e:
        logger.error("Validation error: %s", e)
        return {
            "error": True,
            "message": str(e),
            "type": "validation_error",
        }
    except Exception as e:
        logger.exception("Unexpected error parsing paper")
        return {
            "error": True,
            "message": f"Unexpected error: {e}",
            "type": "internal_error",
        }
