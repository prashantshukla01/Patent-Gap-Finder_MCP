"""MCP tool: draft_claims — generate USPTO-format patent claims.

Requires find_whitespace to have completed first (Phase 4).
Uses Gemini AI to draft independent and dependent claims for each
whitespace opportunity.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

UUID_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I
)


async def draft_claims(
    session_id: str,
    min_novelty_score: float = 0.5,
) -> dict:
    """Draft USPTO-format patent claims for whitespace opportunities.

    Args:
        session_id: UUID of the analysis session.
        min_novelty_score: Minimum novelty score to draft claims for (0.0-1.0).

    Returns:
        Claim drafting results with claim sets, or structured error.
    """
    # Validate UUID
    if not UUID_PATTERN.match(session_id):
        return {"error": "INVALID_SESSION_ID", "message": "Not a valid UUID"}

    from patent_gap_finder.db.connection import get_db_session
    from patent_gap_finder.db.models import AnalysisSession, WhitespaceOpportunityRecord
    from patent_gap_finder.db.repositories import (
        landscape_repo,
        patent_repo,
        drafts_repo,
        session_repo,
    )
    from patent_gap_finder.drafting.claim_drafter import draft_all_claim_sets

    async with get_db_session() as db:
        # Load session
        from sqlalchemy import select, update

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
                    "parse_paper → classify_ipc → search_prior_art → map_landscape → "
                    "find_whitespace, then call draft_claims."
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
                    "Try lowering the min_novelty_score parameter, or the paper may not "
                    "have sufficiently novel claims compared to existing prior art."
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
                    "abstract": p.abstract,
                    "patent_id": p.patent_id,
                    "assignee": p.assignee,
                }

        # Convert ORM objects to dicts for the drafter
        opp_dicts = []
        for opp in whitespace_opps:
            opp_dicts.append({
                "id": opp.id,
                "claim_text": opp.claim_text,
                "claim_type": opp.claim_type,
                "novelty_score": opp.novelty_score,
                "recommended_claim_scope": opp.recommended_claim_scope or "medium",
                "gemini_assessment": opp.gemini_assessment or "",
                "ipc_whitespace_codes": opp.ipc_whitespace_codes or [],
                "nearest_patent_ids": opp.nearest_patent_ids or [],
                "is_whitespace": opp.is_whitespace,
            })

        # Draft claims
        logger.info(
            "Drafting claims for %d opportunities (session=%s)",
            len(opp_dicts),
            session_id,
        )

        claim_sets = await draft_all_claim_sets(
            opportunities=opp_dicts,
            patent_details=patent_details,
            min_novelty_score=min_novelty_score,
        )

        if not claim_sets:
            return {
                "error": "DRAFTING_FAILED",
                "message": "AI claim drafting produced no results. Please retry.",
            }

        # Save to database
        await drafts_repo.save_claim_sets(db, session_id, claim_sets)

        # Update session status
        await db.execute(
            update(AnalysisSession)
            .where(AnalysisSession.id == session_id)
            .values(
                claims_drafted=True,
                updated_at=datetime.now(timezone.utc),
            )
        )
        await db.commit()

        # Build drafting summary
        total_claims = sum(len(cs.claims) for cs in claim_sets)
        ind_claims = sum(
            1 for cs in claim_sets
            for c in cs.claims if c.claim_type == "independent"
        )
        dep_claims = total_claims - ind_claims

        drafting_summary = (
            f"Generated {len(claim_sets)} claim sets covering {total_claims} "
            f"total claims ({ind_claims} independent, {dep_claims} dependent). "
            f"Claims are drafted in USPTO format with proper preamble, transition, "
            f"and body element structure."
        )

        # Build recommended filing order (sorted by novelty score descending)
        filing_order = sorted(
            claim_sets,
            key=lambda cs: cs.novelty_score,
            reverse=True,
        )

        return {
            "session_id": session_id,
            "total_claim_sets": len(claim_sets),
            "total_claims": total_claims,
            "claim_sets": [
                {
                    "opportunity_id": cs.opportunity_id,
                    "claim_text_original": cs.claim_text_original[:150],
                    "novelty_score": cs.novelty_score,
                    "recommended_scope": cs.recommended_scope,
                    "claim_count": len(cs.claims),
                    "claims_preview": cs.claims[0].claim_text if cs.claims else "",
                    "ipc_codes": cs.ipc_codes,
                    "distinguishing_features": cs.distinguishing_features,
                }
                for cs in claim_sets
            ],
            "drafting_summary": drafting_summary,
            "recommended_filing_order": [
                cs.opportunity_id for cs in filing_order
            ],
            "disclaimer": (
                "DISCLAIMER: These claims were generated by an AI system and have not "
                "been reviewed by a licensed patent attorney. They are provided for "
                "informational purposes only and do not constitute legal advice."
            ),
            "next_step": "Call export_report to download the full PDF analysis",
        }
