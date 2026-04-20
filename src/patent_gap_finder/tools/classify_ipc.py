"""MCP tool for IPC/CPC classification of extracted claims.

Loads AI-extracted claims from a session and returns them with
classification instructions for the host LLM.  The LLM classifies
the claims and calls save_classification to persist the results.
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


async def classify_ipc(session_id: str) -> dict:
    """Return AI-extracted claims with IPC classification instructions.

    Loads claims from the database and returns them along with structured
    instructions for the host LLM to classify them into IPC/CPC codes.
    The LLM should then call save_classification with the results.

    Args:
        session_id: UUID string of the analysis session.

    Returns:
        Dict with claims data and classification instructions, or
        structured error dict on failure.
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
            # Load session
            session = await session_repo.get_session(db, session_id)
            if session is None:
                return {
                    "error": "SESSION_NOT_FOUND",
                    "message": f"Session {session_id} not found. Run parse_paper first.",
                    "session_id": session_id,
                }

            # Load AI claims
            ai_claims = await claim_repo.get_claims_by_source(
                db, session_id, "ai"
            )
            if not ai_claims:
                return {
                    "error": "NO_AI_CLAIMS",
                    "message": (
                        f"No AI-extracted claims found for session {session_id}. "
                        "Run parse_paper first, then call save_claims with extracted claims."
                    ),
                    "session_id": session_id,
                }

            primary_domain = session.primary_domain or "general technology"

            # Build claims list for the LLM
            claims_data = [
                {
                    "claim_text": c.claim_text,
                    "claim_type": c.claim_type,
                    "technical_domain": c.technical_domain or "",
                    "novelty_basis": c.novelty_basis or "",
                    "source_section": c.source_section,
                    "confidence": c.confidence,
                }
                for c in ai_claims
            ]

        return {
            "session_id": session_id,
            "primary_domain": primary_domain,
            "claims_to_classify": claims_data,
            "total_claims": len(claims_data),
            "ai_instructions": {
                "task": "classify_ipc_codes",
                "description": (
                    "Classify each claim below into IPC (International Patent "
                    "Classification) and CPC codes. Then call the save_classification "
                    "tool with the results."
                ),
                "save_tool": "save_classification",
                "save_args": {
                    "session_id": session_id,
                    "mappings": "list of mapping dicts (see schema below)",
                    "top_ipc_codes": "deduplicated IPC codes ranked by frequency",
                    "search_keywords": "10-15 terms for USPTO patent search",
                },
                "mapping_schema": {
                    "claim_text": "The claim text that was classified (must match exactly)",
                    "primary_ipc": "Primary IPC code, e.g. 'G06N 3/08' (format: [A-H][0-9][0-9][A-Z] [digits]/[digits])",
                    "secondary_ipc": "list of additional IPC codes",
                    "cpc_code": "CPC code if different from IPC",
                    "confidence": "0.0-1.0 classification confidence",
                    "rationale": "One-sentence explanation of why this code was assigned",
                },
                "ipc_reference": {
                    "A": "Human Necessities",
                    "B": "Performing Operations; Transporting",
                    "C": "Chemistry; Metallurgy",
                    "D": "Textiles; Paper",
                    "E": "Fixed Constructions",
                    "F": "Mechanical Engineering; Lighting; Heating; Weapons",
                    "G": "Physics (G06 = computing, G06N = ML/AI)",
                    "H": "Electricity (H04 = communications)",
                },
                "key_subclasses": {
                    "G06F": "Electric digital data processing",
                    "G06N": "Neural networks, ML, AI",
                    "G06V": "Image or video recognition",
                    "G06T": "Image data processing",
                    "H04L": "Transmission of digital information",
                },
                "rules": [
                    "IPC code format: [A-H][0-9]{2}[A-Z] [0-9]+/[0-9]+ (e.g. 'G06N 3/08')",
                    "Be conservative — low confidence if uncertain",
                    "Generate 10-15 search_keywords for USPTO PatentsView search",
                    "Deduplicate top_ipc_codes across all claims",
                ],
            },
            "next_step": (
                "Classify each claim into IPC codes using the instructions above, "
                f"then call save_classification with session_id='{session_id}'"
            ),
        }

    except Exception as e:
        logger.exception("Unexpected error in classify_ipc")
        return {
            "error": "INTERNAL_ERROR",
            "message": f"Unexpected error: {e}",
            "session_id": session_id,
        }
