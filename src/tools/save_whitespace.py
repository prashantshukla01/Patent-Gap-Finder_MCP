"""MCP tool: save_whitespace — persist LLM novelty assessments.

Accepts novelty assessments from the host LLM for whitespace
opportunities and updates the database records.
"""

from __future__ import annotations

import logging
import re
from uuid import UUID

from db.connection import get_db_session
from db.repositories import landscape_repo

logger = logging.getLogger(__name__)

UUID_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I
)


async def save_whitespace(
    session_id: str,
    assessments: list[dict],
) -> dict:
    """Save LLM novelty assessments for whitespace opportunities.

    Each assessment dict should contain:
      - opportunity_id (str, required): UUID of the opportunity
      - novelty_assessment (str): Detailed novelty analysis text
      - confidence (float): 0.0–1.0 assessment confidence
      - recommended_scope (str): "broad" | "medium" | "narrow"
      - ipc_codes (list[str]): Suggested IPC codes for this gap

    Args:
        session_id: UUID of the analysis session.
        assessments: List of assessment dicts from the host LLM.

    Returns:
        Confirmation dict with update count and next step.
    """
    session_id = session_id.strip()

    if not UUID_PATTERN.match(session_id):
        return {"error": "INVALID_SESSION_ID", "message": "Not a valid UUID"}

    if not assessments:
        return {
            "error": "NO_ASSESSMENTS",
            "message": "No assessments provided.",
        }

    try:
        async with get_db_session() as db:
            updated = 0
            for a in assessments:
                opp_id = a.get("opportunity_id", "")
                if not opp_id:
                    continue

                try:
                    await landscape_repo.update_whitespace_assessment(
                        db, opp_id, {
                            "gemini_assessment": a.get("novelty_assessment", ""),
                            "gemini_confidence": min(
                                max(float(a.get("confidence", 0.5)), 0.0), 1.0
                            ),
                            "recommended_claim_scope": a.get("recommended_scope", "medium"),
                            "ipc_whitespace_codes": a.get("ipc_codes", []),
                        }
                    )
                    updated += 1
                except Exception as e:
                    logger.warning("Failed to update opportunity %s: %s", opp_id, e)

            await db.commit()

        logger.info("Saved %d/%d whitespace assessments", updated, len(assessments))

        return {
            "session_id": session_id,
            "assessments_saved": updated,
            "total_provided": len(assessments),
            "next_step": f"Call draft_claims with session_id='{session_id}' to generate patent claims",
        }

    except Exception as e:
        logger.exception("Failed to save whitespace assessments")
        return {
            "error": "INTERNAL_ERROR",
            "message": f"Failed to save assessments: {e}",
            "session_id": session_id,
        }
