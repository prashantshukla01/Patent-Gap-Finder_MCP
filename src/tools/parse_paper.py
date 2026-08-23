"""MCP tool wrapper for the parse_paper capability.

Routes input to the appropriate parser (local PDF, arXiv, or raw text
content) and returns a structured ParsedPaper dict with AI extraction
instructions for the host LLM.

The ``content`` parameter allows Claude Desktop to pass extracted text
from an uploaded PDF directly — bypassing file-system access.

All exceptions are caught and returned as structured error dicts — the
MCP layer never sees unhandled exceptions.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from models.paper import (
    CandidateClaim,
    ParsedPaper,
    ParsedSection,
)
from parsers.arxiv_parser import is_arxiv_source, parse_arxiv
from parsers.pdf_parser import parse_pdf
from utils.text_utils import (
    classify_section_type,
    clean_text,
    extract_candidate_claims,
)

logger = logging.getLogger(__name__)


async def parse_paper(
    source: str = "",
    content: str = "",
    title: str = "",
) -> dict:
    """Parse a research paper from a file path, arXiv reference, or raw text.

    Returns structured paper data with heuristic claims and instructions
    for the host LLM to extract patent-quality claims.  The LLM should
    then call ``save_claims`` with the extracted claims.

    Args:
        source: Either a local file path to a PDF, or an arXiv identifier.
            May be empty if *content* is provided.
        content: Raw text content of the paper (e.g., pasted from an
            uploaded PDF).  When provided, *source* is ignored.
        title: Optional paper title.  Used when *content* is provided
            and a title cannot be inferred from the text.

    Returns:
        A dict with parsed paper data, session_id, and ai_instructions.
    """
    source = source.strip()
    content = content.strip()

    if not source and not content:
        return {
            "error": "VALIDATION_ERROR",
            "message": (
                "No input provided. Either supply a file path / arXiv ID "
                "via 'source', or paste the paper text via 'content'."
            ),
        }

    try:
        # ── Route: raw text content ──
        if content:
            logger.info("Building ParsedPaper from raw text content (%d chars)", len(content))
            parsed = _parse_from_text(content, title=title)
        # ── Route: arXiv ──
        elif is_arxiv_source(source):
            logger.info("Detected arXiv source: %s", source)
            parsed = await parse_arxiv(source)
        # ── Route: local PDF ──
        else:
            path = Path(source).expanduser().resolve()
            if not path.exists():
                return {
                    "error": "FILE_NOT_FOUND",
                    "message": f"File not found: {path}",
                }
            if not path.suffix.lower() == ".pdf":
                return {
                    "error": "VALIDATION_ERROR",
                    "message": f"Expected a PDF file, got: {path.suffix}",
                }
            logger.info("Parsing local PDF: %s", path)
            parsed = parse_pdf(str(path))

        return await _persist_and_instruct(parsed)

    except FileNotFoundError as e:
        logger.error("File not found: %s", e)
        return {"error": "FILE_NOT_FOUND", "message": str(e)}
    except ValueError as e:
        logger.error("Validation error: %s", e)
        return {"error": "VALIDATION_ERROR", "message": str(e)}
    except Exception as e:
        logger.exception("Unexpected error parsing paper")
        return {"error": "INTERNAL_ERROR", "message": f"Unexpected error: {e}"}


# ──────────────────────────────────────────────────────────────────────
# Raw-text → ParsedPaper builder
# ──────────────────────────────────────────────────────────────────────

# Heading patterns used when parsing raw (non-PDF) text
_TEXT_HEADING_RE = re.compile(
    r"^(?:"
    r"(?:\d+(?:\.\d+)*\.?\s+)"   # "1.", "1.1", "2.3.1 "
    r"|(?:[IVXivx]+\.?\s+)"      # "II.", "IV "
    r"|(?:[A-Z]\.?\s+)"          # "A.", "B "
    r")"
    r"[A-Z]",                    # followed by uppercase letter
    re.MULTILINE,
)

_KNOWN_HEADING_WORDS = {
    "abstract", "introduction", "background", "related work",
    "methodology", "method", "methods", "approach", "model",
    "framework", "architecture", "design", "implementation",
    "system", "proposed", "experiment", "experiments",
    "evaluation", "results", "discussion", "analysis",
    "ablation", "conclusion", "conclusions", "summary",
    "future work", "references", "bibliography",
    "acknowledgment", "acknowledgments", "acknowledgement",
    "appendix", "claims", "description",
}


def _parse_from_text(
    text: str,
    *,
    title: str = "",
    top_n_claims: int = 10,
) -> ParsedPaper:
    """Build a :class:`ParsedPaper` from raw text content.

    Uses lightweight heuristics to split the text into sections,
    detect a title (if not supplied), and extract candidate claims.

    Args:
        text: Full paper text (e.g. pasted from a PDF upload).
        title: Optional explicit title.
        top_n_claims: Number of top candidate claims to return.

    Returns:
        A :class:`ParsedPaper` instance.
    """
    lines = text.split("\n")
    file_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()

    # ── Infer title from first non-blank line if not provided ──
    if not title:
        for line in lines:
            stripped = line.strip()
            if stripped and len(stripped) > 5:
                title = clean_text(stripped)
                break
        if not title:
            title = "Untitled"

    # ── Split into sections by heading heuristics ──
    sections: list[ParsedSection] = []
    current_heading = "Preamble"
    current_content: list[str] = []

    def _flush():
        nonlocal current_heading, current_content
        body = clean_text("\n".join(current_content))
        if body:
            sections.append(ParsedSection(
                title=current_heading,
                content=body,
                section_type=classify_section_type(current_heading),
            ))
        current_content = []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            current_content.append("")
            continue

        is_heading = False

        # Check numbered heading pattern (e.g. "1. Introduction")
        if _TEXT_HEADING_RE.match(stripped):
            is_heading = True

        # Check all-caps short line (e.g. "ABSTRACT")
        elif (
            stripped == stripped.upper()
            and len(stripped) < 80
            and len(stripped.split()) <= 6
            and any(w.lower() in _KNOWN_HEADING_WORDS for w in stripped.split())
        ):
            is_heading = True

        # Check known heading word as standalone line
        elif (
            stripped.lower().rstrip(":") in _KNOWN_HEADING_WORDS
            and len(stripped) < 60
        ):
            is_heading = True

        if is_heading:
            _flush()
            current_heading = stripped
        else:
            current_content.append(stripped)

    _flush()  # last section

    # ── Extract abstract ──
    abstract = ""
    for s in sections:
        if s.section_type == "abstract":
            abstract = s.content
            break

    # ── Extract candidate claims ──
    candidate_claims: list[CandidateClaim] = extract_candidate_claims(
        sections, top_n=top_n_claims
    )

    return ParsedPaper(
        title=title,
        authors=[],
        abstract=abstract,
        sections=sections,
        candidate_claims=candidate_claims,
        file_hash=file_hash,
        parsed_at=datetime.now(timezone.utc),
    )


async def _persist_and_instruct(parsed) -> dict:
    """Persist heuristic results and return AI extraction instructions.

    Creates a session, saves heuristic claims, and returns the parsed
    paper data along with instructions for the host LLM to extract
    patent-quality claims.
    """
    result = parsed.model_dump(mode="json")

    try:
        from db.connection import get_db_session
        from db.repositories import claim_repo, session_repo

        async with get_db_session() as db:
            # Check for duplicate
            if parsed.file_hash:
                existing = await session_repo.get_session_by_file_hash(
                    db, parsed.file_hash
                )
                if existing:
                    result["session_id"] = existing.id
                    result["duplicate"] = True
                    result["existing_session_id"] = existing.id
                    result["note"] = (
                        "This paper was previously analyzed. "
                        "Use get_session to retrieve past results."
                    )
                    return result

            # Create session
            session = await session_repo.create_session(db, {
                "paper_title": parsed.title,
                "paper_authors": parsed.authors,
                "source_url": parsed.source_url,
                "file_hash": parsed.file_hash,
            })

            # Save heuristic claims
            heuristic_claims = [
                {
                    "claim_text": c.text,
                    "claim_type": c.claim_type,
                    "source_section": c.source_section,
                    "confidence": c.confidence,
                    "extraction_source": "heuristic",
                }
                for c in parsed.candidate_claims
            ]
            if heuristic_claims:
                await claim_repo.create_claims(db, session.id, heuristic_claims)

            result["session_id"] = session.id

    except Exception as e:
        logger.warning("Database not available, returning without persistence: %s", e)
        result["note"] = (
            "Results not persisted (database unavailable). "
            "Set DATABASE_URL to enable persistence."
        )

    # ── AI Extraction Instructions ──
    # Always included — the host LLM reads these, extracts claims,
    # and calls save_claims (if DB is available).
    result["ai_instructions"] = {
        "task": "extract_patent_claims",
        "description": (
            "Analyze the paper content above and extract 5-10 independent "
            "patent-style claims. Then call the save_claims tool with the results."
        ),
        "save_tool": "save_claims",
        "save_args": {
            "session_id": result.get("session_id", ""),
            "claims": "list of claim dicts (see schema below)",
            "paper_summary": "2-3 sentence technical summary",
            "primary_domain": "main technical field",
        },
        "claim_schema": {
            "claim_text": "Full patent-style claim (e.g. 'A method for X comprising: step A; step B; step C.')",
            "claim_type": "method | system | composition",
            "technical_domain": "e.g. 'natural language processing'",
            "novelty_basis": "Why this might be patentable — what is novel",
            "source_section": "Paper section title this claim was derived from",
            "confidence": "0.0-1.0 confidence score",
        },
        "rules": [
            "Extract 5-10 claims, not more",
            "Each claim must identify a specific novel technical contribution",
            "Use patent claim structure: preamble + 'comprising' + body elements",
            "Ignore incremental improvements with no structural novelty",
            "If confidence is below 0.5, omit the claim",
            "Classify each as 'method', 'system', or 'composition'",
        ],
    }
    result["next_step"] = (
        "Read the paper content, extract patent claims using the ai_instructions, "
        f"then call save_claims with session_id='{result.get('session_id', '')}'"
    )

    return result
