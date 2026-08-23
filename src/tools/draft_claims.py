"""MCP tool: draft_claims — return whitespace data for LLM claim drafting.

Returns whitespace opportunities with nearest patent context and
USPTO drafting instructions.  The host LLM drafts the claims and
calls save_drafted_claims to persist them.
"""

from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

UUID_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I
)


async def draft_claims(
    session_id: str,
    min_novelty_score: float = 0.5,
) -> dict:
    """Return whitespace opportunities with USPTO claim drafting instructions.

    The host LLM should draft patent claims for each opportunity
    and call save_drafted_claims to persist them.

    Args:
        session_id: UUID of the analysis session.
        min_novelty_score: Minimum novelty score to draft claims for (0.0-1.0).

    Returns:
        Whitespace data with drafting instructions, or structured error.
    """
    # Validate UUID
    if not UUID_PATTERN.match(session_id):
        return {"error": "INVALID_SESSION_ID", "message": "Not a valid UUID"}

    from db.connection import get_db_session
    from db.models import AnalysisSession
    from db.repositories import (
        landscape_repo,
        patent_repo,
    )

    async with get_db_session() as db:
        # Load session
        from sqlalchemy import select

        result = await db.execute(
            select(AnalysisSession).where(AnalysisSession.id == session_id)
        )
        session = result.scalars().first()

        if not session:
            return {"error": "SESSION_NOT_FOUND", "message": "No session with this ID"}

        # Check Phase 4 completion
        if not session.whitespace_analysis_complete:
            return {
                "error": "PHASE4_INCOMPLETE",
                "message": (
                    "White-space analysis not complete. Run the full pipeline first: "
                    "parse_paper → save_claims → classify_ipc → save_classification → "
                    "search_prior_art → map_landscape → find_whitespace → save_whitespace, "
                    "then call draft_claims."
                ),
            }

        # Load whitespace opportunities
        opps = await landscape_repo.get_whitespace_opportunities(
            db, session_id, min_novelty_score=min_novelty_score
        )

        # Filter to actual whitespace opportunities
        whitespace_opps = [o for o in opps if o.is_whitespace]

        if not whitespace_opps:
            return {
                "error": "NO_OPPORTUNITIES",
                "message": (
                    f"No whitespace opportunities found with novelty score ≥ {min_novelty_score}. "
                    "Try lowering the min_novelty_score parameter."
                ),
                "suggestion": "Try min_novelty_score=0.3 for a broader analysis",
            }

        # Load patent details for context
        all_patent_ids: set[str] = set()
        for opp in whitespace_opps:
            if opp.nearest_patent_ids:
                for pid in opp.nearest_patent_ids:
                    all_patent_ids.add(pid)

        patent_details: dict[str, dict] = {}
        patents = await patent_repo.get_patents_for_session(db, session_id)
        for p in patents:
            if p.patent_id in all_patent_ids:
                patent_details[p.patent_id] = {
                    "title": p.title,
                    "abstract": (p.abstract or "")[:300],
                    "patent_id": p.patent_id,
                    "assignee": p.assignee,
                }

        # Build opportunity data with patent context
        opp_data = []
        for opp in whitespace_opps:
            nearest_patents = []
            for pid in (opp.nearest_patent_ids or [])[:3]:
                details = patent_details.get(pid, {})
                if details:
                    nearest_patents.append(details)

            opp_data.append({
                "opportunity_id": opp.id,
                "claim_text": opp.claim_text,
                "claim_type": opp.claim_type,
                "novelty_score": opp.novelty_score,
                "novelty_assessment": opp.gemini_assessment or "",
                "recommended_claim_scope": opp.recommended_claim_scope or "medium",
                "ipc_codes": opp.ipc_whitespace_codes or [],
                "nearest_patents": nearest_patents,
            })

    return {
        "session_id": session_id,
        "total_opportunities": len(opp_data),
        "opportunities": opp_data,
        "ai_instructions": {
            "task": "draft_patent_claims",
            "description": (
                "Draft USPTO-format patent claims for each whitespace "
                "opportunity below. Then call save_drafted_claims with the results."
            ),
            "save_tool": "save_drafted_claims",
            "save_args": {
                "session_id": session_id,
                "claim_sets": "list of claim set dicts (see schema below)",
            },
            "claim_set_schema": {
                "opportunity_id": "UUID from the opportunities above",
                "claim_text_original": "The original claim text from the paper",
                "novelty_score": "The novelty score from the opportunity",
                "recommended_scope": "broad | medium | narrow",
                "claims": [
                    {
                        "claim_number": "integer starting at 1",
                        "claim_text": "Full formatted claim text with proper USPTO structure",
                        "claim_type": "independent | dependent",
                        "depends_on": "claim number this depends on, null for independent",
                        "patent_claim_category": "method | system | composition",
                    }
                ],
                "drafting_rationale": "2-3 sentences explaining scope decisions",
                "distinguishing_features": ["feature 1 not in prior art", "feature 2"],
                "ipc_codes": "relevant IPC codes",
            },
            "uspto_rules": {
                "independent_claim": {
                    "preamble": "A method for [X] / A system comprising / An apparatus for [X]",
                    "transition": "comprising (always open-ended)",
                    "body": "each element on its own line; ended with semicolon except last (period)",
                },
                "dependent_claim": "The [category] of claim [N], wherein [LIMITATION].",
                "antecedent_basis": "First mention: 'a processor', subsequent: 'the processor'",
                "scope_guidelines": {
                    "broad": "1 independent + 2 dependent claims",
                    "medium": "1 independent + 3 dependent claims",
                    "narrow": "1 independent + 4 dependent claims",
                },
            },
            "rules": [
                "Independent claim must NOT read on any cited prior art",
                "Add distinguishing elements from nearest patents",
                "Use functional language: 'configured to', 'adapted to', 'operable to'",
                "Each body element on its own line ending with semicolon (last ends with period)",
                "Use 'comprising' as transition word for all independent claims",
            ],
            "output_format_template": {
                "section_1": "1. Overall Patentability Verdict & Success Probability (%) — High/Moderate/Low verdict, XX% success probability, and Executive Summary",
                "section_2": "2. What claims make it unpatentable — Specific claims with 35 U.S.C. §101/102/103 abstract idea or obviousness risks and prior art overlaps",
                "section_3": "3. How can someone make it patentable — Strategic reframing, algorithmic/mathematical pivots, and structural limitations",
            },
        },
        "disclaimer": (
            "DISCLAIMER: Claims drafted by AI have not been reviewed by a "
            "licensed patent attorney. Consult a registered patent practitioner "
            "before filing any patent application."
        ),
        "next_step": (
            "Draft USPTO patent claims for each opportunity using the instructions, "
            f"then call save_drafted_claims with session_id='{session_id}'"
        ),
    }
