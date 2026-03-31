"""MCP tool: find_whitespace — detect patentable gaps in the landscape.

Requires map_landscape to have completed first.
Compares AI-extracted claims against the patent landscape.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

UUID_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I
)


async def find_whitespace(
    session_id: str,
    min_novelty_score: float = 0.5,
) -> dict:
    """Detect white-space opportunities in the patent landscape.

    Args:
        session_id: UUID of the analysis session.
        min_novelty_score: Minimum novelty score to include (0.0-1.0).

    Returns:
        White-space report with opportunities, or structured error.
    """
    # Validate UUID
    if not UUID_PATTERN.match(session_id):
        return {"error": "INVALID_SESSION_ID", "message": "Not a valid UUID"}

    from patent_gap_finder.db.connection import get_db_session
    from patent_gap_finder.db.models import AnalysisSession, ExtractedClaim
    from patent_gap_finder.db.repositories import landscape_repo

    async with get_db_session() as db:
        # Load session
        from sqlalchemy import select
        result = await db.execute(
            select(AnalysisSession).where(AnalysisSession.id == session_id)
        )
        session = result.scalars().first()

        if not session:
            return {"error": "SESSION_NOT_FOUND", "message": "No session with this ID"}

        # Check landscape completion
        if not session.landscape_complete:
            return {
                "error": "PHASE4_LANDSCAPE_INCOMPLETE",
                "message": "Landscape not built. Run map_landscape first.",
            }

        # Load landscape job
        landscape_job = await landscape_repo.get_latest_landscape_job(db, session_id)
        if not landscape_job or landscape_job.status != "complete":
            return {
                "error": "PHASE4_LANDSCAPE_INCOMPLETE",
                "message": "No complete landscape job found.",
            }

        # Load AI-extracted claims with confidence > 0.4
        claims_result = await db.execute(
            select(ExtractedClaim).where(
                ExtractedClaim.session_id == session_id,
                ExtractedClaim.extraction_source == "ai",
                ExtractedClaim.confidence > 0.4,
            )
        )
        claims = list(claims_result.scalars().all())

        if not claims:
            return {
                "error": "NO_AI_CLAIMS",
                "message": (
                    "No AI-extracted claims found with confidence > 0.4. "
                    "Run parse_paper with extract_with_ai=true first."
                ),
            }

        # Build LandscapeMap from DB records
        from patent_gap_finder.models.landscape import ClusterInfo, LandscapeMap

        landscape = LandscapeMap(
            session_id=session_id,
            total_patents_embedded=landscape_job.n_patents_embedded or 0,
            n_clusters=landscape_job.n_clusters or 0,
            noise_patent_count=landscape_job.noise_patent_count or 0,
            clusters=[
                ClusterInfo(
                    cluster_id=cr.cluster_id,
                    label=cr.label or "",
                    technical_domain=cr.technical_domain or "",
                    patent_count=cr.patent_count,
                    centroid_patent_ids=cr.centroid_patent_ids or [],
                    avg_internal_similarity=cr.avg_internal_similarity or 0.0,
                )
                for cr in landscape_job.cluster_records
                if not cr.is_noise_cluster
            ],
            embedding_model=landscape_job.embedding_model or "all-MiniLM-L6-v2",
            hdbscan_params=landscape_job.hdbscan_params or {},
        )

        # Reconstruct centroids from Qdrant
        from patent_gap_finder.embeddings import qdrant_store
        from patent_gap_finder.clustering.hdbscan_clusterer import compute_centroids

        try:
            all_ids, all_embeddings = await qdrant_store.get_all_session_embeddings(
                session_id
            )
        except Exception as e:
            return {
                "error": "QDRANT_UNAVAILABLE",
                "message": f"Cannot retrieve embeddings: {e}",
            }

        # Rebuild labels from Qdrant data for centroid computation
        import numpy as np
        from patent_gap_finder.db.repositories import patent_repo

        # Get cluster assignments from DB
        patents = await patent_repo.get_patents_for_session(db, session_id)
        id_to_cluster = {str(p.id): (p.cluster_id if p.cluster_id is not None else -1)
                         for p in patents}

        # Build labels array matching Qdrant order
        labels = np.array([id_to_cluster.get(pid, -1) for pid in all_ids])
        centroids = compute_centroids(all_embeddings, labels)

        # Detect whitespace
        from patent_gap_finder.clustering.whitespace_detector import detect_whitespace

        opportunities = await detect_whitespace(
            session_id=session_id,
            landscape=landscape,
            claims=claims,
            centroids=centroids,
            db=db,
        )

        # Filter by min_novelty_score
        filtered = [o for o in opportunities if o.novelty_score >= min_novelty_score]

        # Save to DB
        await landscape_repo.create_whitespace_opportunities(
            db, session_id, landscape_job.id, opportunities
        )

        # Update session
        top_count = sum(1 for o in filtered if o.novelty_score >= 0.75)
        session.whitespace_analysis_complete = True
        session.top_opportunity_count = top_count
        await db.commit()

        # Generate summary
        ws_count = sum(1 for o in opportunities if o.is_whitespace)
        summary = (
            f"Analyzed {len(claims)} AI-extracted claims against "
            f"{landscape.total_patents_embedded} patents in "
            f"{landscape.n_clusters} clusters. Found {ws_count} "
            f"white-space opportunities, {top_count} with high novelty "
            f"(score >= 0.75)."
        )

        return {
            "session_id": session_id,
            "total_claims_analyzed": len(claims),
            "whitespace_opportunities": [
                {
                    "opportunity_id": o.opportunity_id,
                    "claim_text": o.claim_text,
                    "claim_type": o.claim_type,
                    "novelty_score": o.novelty_score,
                    "avg_neighbor_similarity": o.avg_neighbor_similarity,
                    "nearest_cluster_label": o.nearest_cluster_label,
                    "nearest_patents": o.nearest_patents,
                    "nearest_patent_titles": o.nearest_patent_titles,
                    "gemini_assessment": o.gemini_novelty_assessment,
                    "gemini_confidence": o.gemini_confidence,
                    "recommended_claim_scope": o.recommended_claim_scope,
                    "ipc_whitespace_codes": o.ipc_whitespace_codes,
                }
                for o in filtered
            ],
            "non_whitespace_claims": len(claims) - ws_count,
            "top_opportunities": top_count,
            "analysis_summary": summary,
            "next_step": "Call draft_claims to generate USPTO patent claims",
        }
