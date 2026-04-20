"""MCP tool: save_classification — persist LLM IPC/CPC classifications.

Accepts patent classifications produced by the host LLM (e.g. Claude)
and saves them to the session's claims.  Replaces the old Gemini-powered
IPC classification path.
"""

from __future__ import annotations

import logging
import re
from uuid import UUID

from patent_gap_finder.db.connection import get_db_session
from patent_gap_finder.db.repositories import claim_repo, session_repo

logger = logging.getLogger(__name__)

_IPC_REGEX = re.compile(r"^[A-H]\d{2}[A-Z] \d+/\d+$")


def _is_valid_uuid(value: str) -> bool:
    try:
        UUID(value)
        return True
    except (ValueError, AttributeError):
        return False


async def save_classification(
    session_id: str,
    mappings: list[dict],
    top_ipc_codes: list[str] | None = None,
    search_keywords: list[str] | None = None,
) -> dict:
    """Save LLM-produced IPC/CPC classifications to the database.

    Each mapping dict should contain:
      - claim_text (str, required): The claim text that was classified
      - primary_ipc (str, required): Primary IPC code, e.g. "G06N 3/08"
      - secondary_ipc (list[str]): Additional IPC codes
      - cpc_code (str): CPC code if different from IPC
      - confidence (float): 0.0–1.0 classification confidence
      - rationale (str): Why this code was assigned

    Args:
        session_id: UUID of the analysis session.
        mappings: List of claim-to-IPC mapping dicts.
        top_ipc_codes: Deduplicated IPC codes ranked by frequency.
        search_keywords: 10–15 terms for patent search.

    Returns:
        Confirmation dict with classification count and next step.
    """
    session_id = session_id.strip()
    top_ipc_codes = top_ipc_codes or []
    search_keywords = search_keywords or []

    if not _is_valid_uuid(session_id):
        return {
            "error": "INVALID_SESSION_ID",
            "message": f"'{session_id}' is not a valid UUID.",
        }

    if not mappings:
        return {
            "error": "NO_MAPPINGS",
            "message": "No classification mappings provided.",
        }

    try:
        async with get_db_session() as db:
            # Verify session
            session = await session_repo.get_session(db, session_id)
            if session is None:
                return {
                    "error": "SESSION_NOT_FOUND",
                    "message": f"Session {session_id} not found.",
                }

            # Load AI claims to match by claim_text
            ai_claims = await claim_repo.get_claims_by_source(db, session_id, "ai")
            claim_text_to_id = {c.claim_text: c.id for c in ai_claims}

            matched = 0
            valid_ipc = 0

            for mapping in mappings:
                claim_text = mapping.get("claim_text", "")
                claim_id = claim_text_to_id.get(claim_text)
                if not claim_id:
                    continue

                primary_ipc = mapping.get("primary_ipc", "")
                is_valid = bool(_IPC_REGEX.match(primary_ipc.strip())) if primary_ipc else False
                if is_valid:
                    valid_ipc += 1

                await claim_repo.update_claim_ipc(db, claim_id, {
                    "primary_ipc": primary_ipc,
                    "secondary_ipc": mapping.get("secondary_ipc", []),
                    "cpc_code": mapping.get("cpc_code", ""),
                    "confidence": min(max(float(mapping.get("confidence", 0.7)), 0.0), 1.0),
                    "is_valid_ipc": is_valid,
                })
                matched += 1

            # Update session
            await session_repo.update_session_results(db, session_id, {
                "top_ipc_codes": top_ipc_codes,
                "search_keywords": search_keywords,
            })
            await session_repo.update_session_status(db, session_id, "complete")

        logger.info(
            "Saved IPC classification: %d/%d matched, %d valid codes",
            matched, len(mappings), valid_ipc,
        )

        return {
            "session_id": session_id,
            "claims_classified": matched,
            "valid_ipc_codes": valid_ipc,
            "top_ipc_codes": top_ipc_codes,
            "search_keywords": search_keywords,
            "next_step": f"Call search_prior_art with session_id='{session_id}' to search patents",
        }

    except Exception as e:
        logger.exception("Failed to save classification")
        return {
            "error": "INTERNAL_ERROR",
            "message": f"Failed to save classification: {e}",
            "session_id": session_id,
        }
