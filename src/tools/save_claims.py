"""MCP tool: save_claims — persist LLM-extracted claims to the database.

Accepts patent claims extracted by the host LLM (e.g. Claude Desktop)
and saves them to the analysis session.  Replaces the old Gemini-powered
claim extraction path.
"""

from __future__ import annotations

import logging
from uuid import UUID

from db.connection import get_db_session
from db.repositories import claim_repo, session_repo

logger = logging.getLogger(__name__)


def _is_valid_uuid(value: str) -> bool:
    try:
        UUID(value)
        return True
    except (ValueError, AttributeError):
        return False


async def save_claims(
    session_id: str,
    claims: list[dict],
    paper_summary: str = "",
    primary_domain: str = "",
) -> dict:
    """Save LLM-extracted patent claims to the database.

    Each claim dict should contain:
      - claim_text (str, required): Full patent-style claim statement
      - claim_type (str): "method" | "system" | "composition" (default: "method")
      - technical_domain (str): e.g. "natural language processing"
      - novelty_basis (str): Why this claim might be patentable
      - source_section (str): Paper section the claim was derived from
      - confidence (float): 0.0–1.0 confidence score

    Args:
        session_id: UUID of the analysis session from parse_paper.
        claims: List of claim dicts extracted by the host LLM.
        paper_summary: 2–3 sentence technical summary of the paper.
        primary_domain: Main technical field of the paper.

    Returns:
        Confirmation dict with claim count and next step.
    """
    session_id = session_id.strip()

    if not _is_valid_uuid(session_id):
        return {
            "error": "INVALID_SESSION_ID",
            "message": f"'{session_id}' is not a valid UUID.",
        }

    if not claims:
        return {
            "error": "NO_CLAIMS",
            "message": "No claims provided. Please extract claims from the paper first.",
        }

    try:
        async with get_db_session() as db:
            # Verify session exists
            session = await session_repo.get_session(db, session_id)
            if session is None:
                return {
                    "error": "SESSION_NOT_FOUND",
                    "message": f"Session {session_id} not found. Run parse_paper first.",
                }

            # Build claim records
            ai_claims = []
            for c in claims:
                claim_text = c.get("claim_text", "").strip()
                if not claim_text:
                    continue
                ai_claims.append({
                    "claim_text": claim_text,
                    "claim_type": c.get("claim_type", "method"),
                    "technical_domain": c.get("technical_domain", ""),
                    "novelty_basis": c.get("novelty_basis", ""),
                    "source_section": c.get("source_section", ""),
                    "confidence": min(max(float(c.get("confidence", 0.7)), 0.0), 1.0),
                    "extraction_source": "ai",
                })

            if not ai_claims:
                return {
                    "error": "NO_VALID_CLAIMS",
                    "message": "None of the provided claims had valid claim_text.",
                }

            # Save claims
            await claim_repo.create_claims(db, session_id, ai_claims)

            # Update session metadata
            update_data = {}
            if paper_summary:
                update_data["paper_summary"] = paper_summary
            if primary_domain:
                update_data["primary_domain"] = primary_domain
            if update_data:
                await session_repo.update_session_results(db, session_id, update_data)

            await session_repo.update_session_status(db, session_id, "extracting")

        logger.info(
            "Saved %d AI claims for session %s (domain=%s)",
            len(ai_claims), session_id, primary_domain,
        )

        return {
            "session_id": session_id,
            "claims_saved": len(ai_claims),
            "paper_summary": paper_summary,
            "primary_domain": primary_domain,
            "next_step": f"Call classify_ipc with session_id='{session_id}' to get IPC codes",
        }

    except Exception as e:
        logger.exception("Failed to save claims")
        return {
            "error": "INTERNAL_ERROR",
            "message": f"Failed to save claims: {e}",
            "session_id": session_id,
        }
