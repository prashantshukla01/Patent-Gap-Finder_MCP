"""Landscape builder — orchestrates embed → cluster → label pipeline.

Full flow:
1. Load patents from DB
2. Prepare texts and embed via sentence-transformers
3. Upsert to Qdrant
4. Run HDBSCAN clustering
5. Label clusters via Gemini (capped at 20)
6. Persist results
7. Return LandscapeMap
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

import numpy as np
from sqlalchemy.ext.asyncio import AsyncSession

from patent_gap_finder.clustering.hdbscan_clusterer import (
    compute_centroids,
    compute_intra_cluster_similarity,
    find_centroid_patents,
    run_clustering,
)
from patent_gap_finder.embeddings import qdrant_store
from patent_gap_finder.embeddings.embedding_engine import encode_texts
from patent_gap_finder.embeddings.text_preparer import batch_prepare_patents
from patent_gap_finder.models.landscape import ClusterInfo, LandscapeMap

logger = logging.getLogger(__name__)


class InsufficientPatentsError(Exception):
    """Not enough patents to build a landscape."""


class ClusteringFailedError(Exception):
    """HDBSCAN clustering failed after retries."""


async def build_landscape(
    session_id: str,
    db: AsyncSession,
) -> LandscapeMap:
    """Orchestrate the full embedding → clustering → labeling pipeline.

    Args:
        session_id: UUID of the analysis session.
        db: Async database session.

    Returns:
        Complete LandscapeMap with clusters and metadata.
    """
    from patent_gap_finder.db.repositories import patent_repo

    # Step 1 — Load patents
    patents = await patent_repo.get_patents_for_session(db, session_id)

    if len(patents) < 5:
        raise InsufficientPatentsError(
            f"Need at least 5 patents to build landscape. "
            f"Found {len(patents)}. Run search_prior_art first."
        )

    logger.info("Building landscape for session %s (%d patents)",
                session_id, len(patents))

    # Step 2 — Prepare texts and embed
    texts = batch_prepare_patents(patents)
    embeddings = await encode_texts(texts)

    # Step 3 — Upsert to Qdrant
    patent_db_ids = [str(p.id) for p in patents]
    payloads = [
        {
            "patent_id": p.patent_id,
            "title": (p.title or "")[:200],
            "abstract": (p.abstract or "")[:512],
            "ipc_codes": p.ipc_codes or [],
            "source": p.source or "",
            "session_ids": [str(session_id)],
        }
        for p in patents
    ]
    await qdrant_store.upsert_patent_embeddings(patent_db_ids, embeddings, payloads)

    # Step 4 — Retrieve all embeddings from Qdrant for clustering
    all_ids, all_embeddings = await qdrant_store.get_all_session_embeddings(
        session_id
    )

    if len(all_ids) < 5:
        raise InsufficientPatentsError(
            f"Only {len(all_ids)} embeddings in Qdrant. Need at least 5."
        )

    # Step 5 — Run HDBSCAN
    labels, probabilities, params_used = run_clustering(all_embeddings)
    centroids = compute_centroids(all_embeddings, labels)

    n_clusters = len(set(labels)) - (1 if -1 in labels else 0)
    noise_count = int((labels == -1).sum())

    # Step 6 — Label clusters via Gemini (cap at 20)
    clusters: list[ClusterInfo] = []
    cluster_ids_to_label = sorted(
        [cid for cid in set(labels) if cid != -1],
        key=lambda cid: int((labels == cid).sum()),
        reverse=True,
    )

    # Build a map from DB UUID → patent record for title lookups
    id_to_patent = {}
    for p in patents:
        id_to_patent[str(p.id)] = p

    for idx, cluster_id in enumerate(cluster_ids_to_label):
        mask = labels == cluster_id
        patent_count = int(mask.sum())

        # Find centroid patents
        centroid_ids = find_centroid_patents(
            all_embeddings, labels, all_ids, cluster_id, n=3
        )
        centroid_titles = []
        centroid_patent_ids = []
        for db_id in centroid_ids:
            patent = id_to_patent.get(db_id)
            if patent:
                centroid_titles.append(patent.title or "")
                centroid_patent_ids.append(patent.patent_id)

        # Compute intra-cluster similarity
        avg_sim = compute_intra_cluster_similarity(
            all_embeddings, labels, cluster_id
        )

        # Label via Gemini (only top 20 clusters to save quota)
        label = f"cluster {cluster_id}"
        tech_domain = ""
        if idx < 20 and centroid_titles:
            try:
                from patent_gap_finder.ai.novelty_reasoner import label_cluster
                label_result = await label_cluster(centroid_titles, patent_count)
                label = label_result.get("label", label)
                tech_domain = label_result.get("technical_domain", "")
            except Exception as e:
                logger.warning("Gemini cluster labeling failed for %d: %s",
                               cluster_id, e)
                label = f"uncategorized domain {cluster_id}"

        clusters.append(ClusterInfo(
            cluster_id=int(cluster_id),
            label=label,
            technical_domain=tech_domain,
            patent_count=patent_count,
            centroid_patent_ids=centroid_patent_ids,
            avg_internal_similarity=round(avg_sim, 4),
            representative_titles=centroid_titles[:3],
        ))

    # Step 7 — Update patent records with cluster assignments
    for i, db_id in enumerate(all_ids):
        cluster_id_val = int(labels[i])
        cluster_label = None
        if cluster_id_val != -1:
            for c in clusters:
                if c.cluster_id == cluster_id_val:
                    cluster_label = c.label
                    break

        try:
            await patent_repo.update_patent_embedding_metadata(
                db, db_id,
                abstract_similarity=1.0,
                cluster_id=cluster_id_val,
                cluster_label=cluster_label,
            )
        except Exception as e:
            logger.warning("Failed to update patent %s metadata: %s", db_id, e)

    # Step 8 — Build and return LandscapeMap
    landscape = LandscapeMap(
        session_id=session_id,
        total_patents_embedded=len(all_ids),
        n_clusters=n_clusters,
        noise_patent_count=noise_count,
        clusters=clusters,
        embedding_model="all-MiniLM-L6-v2",
        hdbscan_params=params_used,
        created_at=datetime.now(timezone.utc),
    )

    logger.info(
        "Landscape built: %d patents, %d clusters, %d noise",
        landscape.total_patents_embedded,
        landscape.n_clusters,
        landscape.noise_patent_count,
    )

    return landscape
