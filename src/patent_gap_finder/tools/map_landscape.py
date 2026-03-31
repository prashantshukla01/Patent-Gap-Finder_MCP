"""MCP tool: map_landscape — embed patents and cluster the landscape.

Orchestrates the full Phase 4 pipeline:
1. Validate session
2. Check Phase 3 completion
3. Check for existing landscape
4. Build landscape (embed → cluster → label)
5. Persist results
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

UUID_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I
)


async def map_landscape(session_id: str) -> dict:
    """Build a patent landscape map from Phase 3 search results.

    Embeds all patents, clusters with HDBSCAN, labels with Gemini.

    Args:
        session_id: UUID of the analysis session.

    Returns:
        Landscape map with clusters, or structured error.
    """
    # Validate UUID
    if not UUID_PATTERN.match(session_id):
        return {"error": "INVALID_SESSION_ID", "message": "Not a valid UUID"}

    from patent_gap_finder.db.connection import get_db_session
    from patent_gap_finder.db.repositories import patent_repo
    from patent_gap_finder.db.repositories import landscape_repo
    from patent_gap_finder.db.models import AnalysisSession

    try:
        from patent_gap_finder.embeddings import qdrant_store
        await qdrant_store.ensure_collection_exists()
    except Exception as e:
        return {
            "error": "QDRANT_UNAVAILABLE",
            "message": f"Cannot connect to Qdrant: {e}",
        }

    async with get_db_session() as db:
        # Load session
        from sqlalchemy import select
        result = await db.execute(
            select(AnalysisSession).where(AnalysisSession.id == session_id)
        )
        session = result.scalars().first()

        if not session:
            return {"error": "SESSION_NOT_FOUND", "message": "No session with this ID"}

        # Check Phase 3 completion
        if not session.patent_search_complete:
            return {
                "error": "PHASE3_INCOMPLETE",
                "message": "Patent search not complete. Run search_prior_art first.",
            }

        # Check for existing complete landscape
        existing = await landscape_repo.get_latest_landscape_job(db, session_id)
        if existing and existing.status == "complete":
            # Return cached result
            clusters_data = []
            for cr in existing.cluster_records:
                if not cr.is_noise_cluster:
                    clusters_data.append({
                        "cluster_id": cr.cluster_id,
                        "label": cr.label,
                        "technical_domain": cr.technical_domain,
                        "patent_count": cr.patent_count,
                        "representative_titles": [],
                    })
            return {
                "landscape_job_id": existing.id,
                "session_id": session_id,
                "status": "complete",
                "n_patents_embedded": existing.n_patents_embedded or 0,
                "n_clusters": existing.n_clusters or 0,
                "noise_patent_count": existing.noise_patent_count or 0,
                "clusters": clusters_data,
                "embedding_model": existing.embedding_model or "all-MiniLM-L6-v2",
                "note": "Landscape already built. Call find_whitespace to detect gaps.",
                "next_step": "Call find_whitespace to identify patentable gaps",
            }

        # Create job
        job = await landscape_repo.create_landscape_job(db, session_id)
        await landscape_repo.update_landscape_job_status(db, job.id, "running")
        await db.commit()

        # Build landscape
        try:
            from patent_gap_finder.clustering.landscape_builder import (
                build_landscape,
                InsufficientPatentsError,
            )

            landscape = await build_landscape(session_id, db)

            # Persist cluster records
            await landscape_repo.create_cluster_records(
                db, job.id, landscape.clusters
            )

            # Update job results
            await landscape_repo.update_landscape_job_results(db, job.id, {
                "n_patents_embedded": landscape.total_patents_embedded,
                "n_clusters": landscape.n_clusters,
                "noise_patent_count": landscape.noise_patent_count,
                "hdbscan_params": landscape.hdbscan_params,
                "embedding_model": landscape.embedding_model,
            })

            # Update session
            session.landscape_complete = True
            await db.commit()

            return {
                "landscape_job_id": job.id,
                "session_id": session_id,
                "status": "complete",
                "n_patents_embedded": landscape.total_patents_embedded,
                "n_clusters": landscape.n_clusters,
                "noise_patent_count": landscape.noise_patent_count,
                "clusters": [
                    {
                        "cluster_id": c.cluster_id,
                        "label": c.label,
                        "technical_domain": c.technical_domain,
                        "patent_count": c.patent_count,
                        "representative_titles": c.representative_titles,
                    }
                    for c in landscape.clusters
                ],
                "embedding_model": landscape.embedding_model,
                "next_step": "Call find_whitespace to identify patentable gaps",
            }

        except InsufficientPatentsError as e:
            await landscape_repo.update_landscape_job_status(
                db, job.id, "failed", str(e)
            )
            await db.commit()
            return {
                "error": "INSUFFICIENT_PATENTS",
                "message": str(e),
            }

        except Exception as e:
            logger.exception("Landscape building failed")
            await landscape_repo.update_landscape_job_status(
                db, job.id, "failed", str(e)
            )
            await db.commit()
            return {
                "error": "CLUSTERING_FAILED",
                "message": f"Landscape building failed: {e}",
            }
