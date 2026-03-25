"""MCP tool wrapper for the parse_paper capability.

Routes input to the appropriate parser (local PDF or arXiv) and returns
a structured ParsedPaper dict.  When ``extract_with_ai=True``, triggers
Gemini-powered claim extraction and persists results to the database.

All exceptions are caught and returned as structured error dicts — the
MCP layer never sees unhandled exceptions.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from patent_gap_finder.parsers.arxiv_parser import is_arxiv_source, parse_arxiv
from patent_gap_finder.parsers.pdf_parser import parse_pdf

logger = logging.getLogger(__name__)


async def parse_paper(source: str, extract_with_ai: bool = False) -> dict:
    """Parse a research paper from a file path or arXiv reference.

    This is the core MCP tool implementation.  It detects whether *source*
    is a local PDF file or an arXiv reference, delegates to the appropriate
    parser, and returns the parsed paper as a serializable dict.

    When *extract_with_ai* is True:
    1. Checks for duplicate papers (by file hash)
    2. Creates a database analysis session
    3. Runs Gemini-powered claim extraction
    4. Persists both heuristic and AI claims

    Args:
        source: Either a local file path to a PDF, or an arXiv identifier.
        extract_with_ai: If True, run Gemini AI claim extraction and
            persist results to the database.

    Returns:
        A dict serialization of :class:`ParsedPaper` on success, or an
        error dict on failure.
    """
    source = source.strip()

    if not source:
        return {
            "error": "VALIDATION_ERROR",
            "message": "Empty source provided. Please supply a PDF file path or arXiv ID/URL.",
        }

    try:
        # ── Phase 1: Parse the paper ──
        if is_arxiv_source(source):
            logger.info("Detected arXiv source: %s", source)
            parsed = await parse_arxiv(source)
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

        # ── Phase 1 only: return heuristic results ──
        if not extract_with_ai:
            return await _persist_heuristic_only(parsed)

        # ── Phase 2: AI extraction with DB persistence ──
        return await _extract_with_ai(parsed)

    except FileNotFoundError as e:
        logger.error("File not found: %s", e)
        return {"error": "FILE_NOT_FOUND", "message": str(e)}
    except ValueError as e:
        logger.error("Validation error: %s", e)
        return {"error": "VALIDATION_ERROR", "message": str(e)}
    except Exception as e:
        logger.exception("Unexpected error parsing paper")
        return {"error": "INTERNAL_ERROR", "message": f"Unexpected error: {e}"}


async def _persist_heuristic_only(parsed) -> dict:
    """Persist heuristic results to DB and return response.

    Creates a session and saves heuristic claims. If the database is not
    available, returns results without persistence.
    """
    result = parsed.model_dump(mode="json")

    try:
        from patent_gap_finder.db.connection import get_db_session
        from patent_gap_finder.db.repositories import claim_repo, session_repo

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
            result["note"] = (
                "Heuristic extraction only. "
                "Use extract_with_ai=true for AI-powered claims."
            )

    except Exception as e:
        logger.warning("Database not available, returning without persistence: %s", e)
        result["note"] = (
            "Results not persisted (database unavailable). "
            "Set DATABASE_URL to enable persistence."
        )

    return result


async def _extract_with_ai(parsed) -> dict:
    """Run AI extraction and persist everything to DB."""
    from patent_gap_finder.ai.claim_extractor import extract_claims
    from patent_gap_finder.ai.gemini_client import (
        GeminiDailyQuotaError,
        GeminiRateLimitError,
        GeminiResponseValidationError,
        get_gemini_client,
    )
    from patent_gap_finder.db.connection import get_db_session
    from patent_gap_finder.db.repositories import claim_repo, session_repo

    result = parsed.model_dump(mode="json")

    # Check for Gemini API key
    if not os.environ.get("GEMINI_API_KEY"):
        return {
            "error": "GEMINI_API_KEY_MISSING",
            "message": (
                "GEMINI_API_KEY not set. Get a free key at "
                "https://aistudio.google.com/app/apikey"
            ),
        }

    try:
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
            session_id = session.id

    except Exception as e:
        return {
            "error": "DATABASE_ERROR",
            "message": f"Failed to create session: {e}",
        }

    try:
        # Run AI extraction
        client = get_gemini_client()
        ai_response = await extract_claims(parsed, client=client)

        async with get_db_session() as db:
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

            # Save AI claims
            ai_claims = [
                {
                    "claim_text": c.claim_text,
                    "claim_type": c.claim_type,
                    "technical_domain": c.technical_domain,
                    "novelty_basis": c.novelty_basis,
                    "source_section": c.source_section,
                    "confidence": c.confidence,
                    "extraction_source": "ai",
                }
                for c in ai_response.claims
            ]

            all_claims = heuristic_claims + ai_claims
            if all_claims:
                await claim_repo.create_claims(db, session_id, all_claims)

            # Update session
            await session_repo.update_session_results(db, session_id, {
                "primary_domain": ai_response.primary_domain,
                "paper_summary": ai_response.paper_summary,
            })
            await session_repo.update_session_status(
                db, session_id, "extracting"
            )
            await session_repo.increment_request_counter(
                db, session_id, count=1
            )

        result["session_id"] = session_id
        result["ai_claims_extracted"] = len(ai_response.claims)
        result["heuristic_claims_found"] = len(heuristic_claims)
        result["paper_summary"] = ai_response.paper_summary
        result["primary_domain"] = ai_response.primary_domain
        result["ai_claims"] = [c.model_dump() for c in ai_response.claims]
        result["next_step"] = (
            f"Call classify_ipc with session_id='{session_id}' to get IPC codes"
        )
        return result

    except GeminiDailyQuotaError:
        async with get_db_session() as db:
            await session_repo.update_session_status(
                db, session_id, "failed",
                error_message="Gemini daily quota exhausted",
            )
        return {
            "error": "GEMINI_QUOTA_EXHAUSTED",
            "message": "Daily Gemini free-tier quota exhausted. Try again tomorrow.",
            "session_id": session_id,
        }
    except GeminiRateLimitError:
        async with get_db_session() as db:
            await session_repo.update_session_status(
                db, session_id, "failed",
                error_message="Gemini rate limit exceeded",
            )
        return {
            "error": "GEMINI_RATE_LIMITED",
            "message": "Gemini rate limit exceeded after retries.",
            "session_id": session_id,
            "retry_after_seconds": 60,
        }
    except GeminiResponseValidationError as e:
        async with get_db_session() as db:
            await session_repo.update_session_status(
                db, session_id, "failed",
                error_message=str(e),
            )
        return {
            "error": "GEMINI_VALIDATION_ERROR",
            "message": str(e),
            "session_id": session_id,
        }
    except Exception as e:
        logger.exception("Unexpected error in AI extraction")
        try:
            async with get_db_session() as db:
                await session_repo.update_session_status(
                    db, session_id, "failed",
                    error_message=str(e),
                )
        except Exception:
            pass
        return {
            "error": "INTERNAL_ERROR",
            "message": f"Unexpected error during AI extraction: {e}",
            "session_id": session_id,
        }
