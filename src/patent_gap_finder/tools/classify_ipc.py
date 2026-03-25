"""MCP tool for IPC/CPC classification of extracted claims.

Loads AI-extracted claims from a session, classifies them via Gemini,
persists the results, and returns the full classification response.
"""

from __future__ import annotations

import logging
from uuid import UUID

from patent_gap_finder.ai.gemini_client import (
    GeminiDailyQuotaError,
    GeminiRateLimitError,
    GeminiResponseValidationError,
    get_gemini_client,
)
from patent_gap_finder.ai.ipc_classifier import classify_ipc as _classify
from patent_gap_finder.db.connection import get_db_session
from patent_gap_finder.db.repositories import claim_repo, session_repo
from patent_gap_finder.models.ipc import AIExtractedClaim

logger = logging.getLogger(__name__)


def _is_valid_uuid(value: str) -> bool:
    """Check if a string is a valid UUID."""
    try:
        UUID(value)
        return True
    except (ValueError, AttributeError):
        return False


async def classify_ipc(session_id: str) -> dict:
    """Classify extracted claims into IPC/CPC codes.

    Full pipeline:
    1. Validate session_id format
    2. Load session from DB
    3. Load AI-extracted claims
    4. Call Gemini IPC classifier
    5. Persist IPC results to each claim
    6. Update session with top_ipc_codes and search_keywords
    7. Return classification response

    Args:
        session_id: UUID string of the analysis session.

    Returns:
        Dict with classification results and session_id, or
        structured error dict on failure.
    """
    session_id = session_id.strip()

    # 1. Validate UUID
    if not _is_valid_uuid(session_id):
        return {
            "error": "INVALID_SESSION_ID",
            "message": f"'{session_id}' is not a valid UUID.",
            "session_id": session_id,
        }

    try:
        async with get_db_session() as db:
            # 2. Load session
            session = await session_repo.get_session(db, session_id)
            if session is None:
                return {
                    "error": "SESSION_NOT_FOUND",
                    "message": f"Session {session_id} not found. Run parse_paper first.",
                    "session_id": session_id,
                }

            # 3. Load AI claims
            ai_claims = await claim_repo.get_claims_by_source(
                db, session_id, "ai"
            )
            if not ai_claims:
                return {
                    "error": "NO_AI_CLAIMS",
                    "message": (
                        f"No AI-extracted claims found for session {session_id}. "
                        "Run parse_paper with extract_with_ai=true first."
                    ),
                    "session_id": session_id,
                }

            # 4. Convert to Pydantic models for the classifier
            claim_models = [
                AIExtractedClaim(
                    claim_text=c.claim_text,
                    claim_type=c.claim_type,
                    technical_domain=c.technical_domain or "",
                    novelty_basis=c.novelty_basis or "",
                    source_section=c.source_section,
                    confidence=c.confidence,
                )
                for c in ai_claims
            ]

            primary_domain = session.primary_domain or "general technology"

            # Update status
            await session_repo.update_session_status(
                db, session_id, "classifying"
            )

        # 5. Call Gemini (outside DB session to avoid long-held connections)
        client = get_gemini_client()
        classification = await _classify(
            claim_models,
            primary_domain,
            client=client,
        )

        # 6. Persist results
        async with get_db_session() as db:
            # Match classifications to claims by claim_text
            claim_text_to_id = {c.claim_text: c.id for c in ai_claims}

            for mapping in classification.mappings:
                claim_id = claim_text_to_id.get(mapping.claim_text)
                if claim_id:
                    await claim_repo.update_claim_ipc(db, claim_id, {
                        "primary_ipc": mapping.primary_ipc,
                        "secondary_ipc": mapping.secondary_ipc,
                        "cpc_code": mapping.cpc_code,
                        "confidence": mapping.confidence,
                        "is_valid_ipc": mapping.is_valid_ipc,
                    })

            # 7. Update session
            await session_repo.update_session_results(db, session_id, {
                "top_ipc_codes": classification.top_ipc_codes,
                "search_keywords": classification.search_keywords,
            })
            await session_repo.update_session_status(
                db, session_id, "complete"
            )
            await session_repo.increment_request_counter(
                db, session_id, count=1
            )

        result = classification.model_dump()
        result["session_id"] = session_id
        return result

    except GeminiDailyQuotaError:
        logger.error("Gemini daily quota exhausted during IPC classification")
        return {
            "error": "GEMINI_QUOTA_EXHAUSTED",
            "message": "Daily Gemini free-tier quota exhausted. Try again tomorrow.",
            "session_id": session_id,
        }
    except GeminiRateLimitError:
        logger.error("Gemini rate limit exceeded during IPC classification")
        return {
            "error": "GEMINI_RATE_LIMITED",
            "message": "Gemini rate limit exceeded after retries.",
            "session_id": session_id,
            "retry_after_seconds": 60,
        }
    except GeminiResponseValidationError as e:
        logger.error("Gemini response validation failed: %s", e)
        return {
            "error": "GEMINI_VALIDATION_ERROR",
            "message": str(e),
            "session_id": session_id,
        }
    except Exception as e:
        logger.exception("Unexpected error in classify_ipc")
        # Try to mark session as failed
        try:
            async with get_db_session() as db:
                await session_repo.update_session_status(
                    db, session_id, "failed", error_message=str(e)
                )
        except Exception:
            pass
        return {
            "error": "INTERNAL_ERROR",
            "message": f"Unexpected error: {e}",
            "session_id": session_id,
        }
