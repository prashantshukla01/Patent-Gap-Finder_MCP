"""MCP tool for retrieving past analysis sessions.

Returns structured session data including claims, phases completed,
and claim count breakdowns.
"""

from __future__ import annotations

import logging
from uuid import UUID

from patent_gap_finder.db.connection import get_db_session
from patent_gap_finder.db.repositories import claim_repo, session_repo

logger = logging.getLogger(__name__)


def _is_valid_uuid(value: str) -> bool:
    """Check if a string is a valid UUID."""
    try:
        UUID(value)
        return True
    except (ValueError, AttributeError):
        return False


async def get_session(session_id: str) -> dict:
    """Retrieve a past analysis session with all details.

    Args:
        session_id: UUID string of the analysis session.

    Returns:
        Structured dict with session data, claims, phases completed,
        and claim counts.  Returns error dict on failure.
    """
    session_id = session_id.strip()

    if not _is_valid_uuid(session_id):
        return {
            "error": "INVALID_SESSION_ID",
            "message": f"'{session_id}' is not a valid UUID.",
            "session_id": session_id,
        }

    try:
        async with get_db_session() as db:
            session = await session_repo.get_session(db, session_id)
            if session is None:
                return {
                    "error": "SESSION_NOT_FOUND",
                    "message": f"Session {session_id} not found.",
                    "session_id": session_id,
                }

            claims = await claim_repo.get_claims_for_session(db, session_id)

            # Compute phases completed
            phases_completed = ["parsing"]

            ai_claims = [c for c in claims if c.extraction_source == "ai"]
            heuristic_claims = [c for c in claims if c.extraction_source == "heuristic"]

            if ai_claims:
                phases_completed.append("ai_extraction")

            if session.top_ipc_codes:
                phases_completed.append("ipc_classification")

            # Build claim summaries
            claim_dicts = [
                {
                    "claim_text": c.claim_text,
                    "claim_type": c.claim_type,
                    "confidence": c.confidence,
                    "primary_ipc": c.primary_ipc,
                    "extraction_source": c.extraction_source,
                }
                for c in claims
            ]

            return {
                "session_id": session.id,
                "status": session.status,
                "paper_title": session.paper_title,
                "paper_authors": session.paper_authors or [],
                "primary_domain": session.primary_domain,
                "paper_summary": session.paper_summary,
                "created_at": (
                    session.created_at.isoformat()
                    if session.created_at else None
                ),
                "top_ipc_codes": session.top_ipc_codes or [],
                "search_keywords": session.search_keywords or [],
                "gemini_requests_used": session.total_requests_used,
                "phases_completed": phases_completed,
                "claims": claim_dicts,
                "claim_count": {
                    "total": len(claims),
                    "ai": len(ai_claims),
                    "heuristic": len(heuristic_claims),
                },
            }

    except Exception as e:
        logger.exception("Error retrieving session %s", session_id)
        return {
            "error": "DATABASE_ERROR",
            "message": f"Failed to retrieve session: {e}",
            "session_id": session_id,
        }
