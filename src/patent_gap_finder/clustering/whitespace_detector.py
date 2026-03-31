"""White-space detector — finds patentable gaps in the landscape.

Compares paper claims against the patent landscape to find regions
where claims have no dense prior art coverage.
"""

from __future__ import annotations

import logging
import os
import uuid
from typing import Optional

import numpy as np
from sqlalchemy.ext.asyncio import AsyncSession

from patent_gap_finder.embeddings import qdrant_store
from patent_gap_finder.embeddings.embedding_engine import encode_single
from patent_gap_finder.embeddings.text_preparer import prepare_claim_text
from patent_gap_finder.models.landscape import (
    ClusterInfo,
    LandscapeMap,
    WhitespaceOpportunity,
)

logger = logging.getLogger(__name__)

WHITESPACE_THRESHOLD = float(os.environ.get("WHITESPACE_THRESHOLD", "0.65"))
CLUSTER_DISTANCE_THRESHOLD = 0.40
K_NEAREST = int(os.environ.get("K_NEAREST_PATENTS", "10"))


def find_nearest_centroid(
    claim_embedding: np.ndarray,
    centroids: dict[int, np.ndarray],
) -> tuple[int, float]:
    """Find the nearest cluster centroid to a claim embedding.

    Args:
        claim_embedding: Embedding vector of shape (384,).
        centroids: {cluster_id: centroid_embedding} dict.

    Returns:
        (cluster_id, euclidean_distance). (-1, 999.0) if no centroids.
    """
    if not centroids:
        return -1, 999.0

    best_id = -1
    best_dist = 999.0

    for cid, centroid in centroids.items():
        dist = float(np.linalg.norm(claim_embedding - centroid))
        if dist < best_dist:
            best_dist = dist
            best_id = cid

    return best_id, best_dist


async def detect_whitespace(
    session_id: str,
    landscape: LandscapeMap,
    claims: list,
    centroids: dict[int, np.ndarray],
    db: AsyncSession,
) -> list[WhitespaceOpportunity]:
    """Detect white-space opportunities by comparing claims vs landscape.

    For each claim:
    1. Embed the claim
    2. Search Qdrant for K nearest patent neighbors
    3. Compute average similarity
    4. Find nearest cluster centroid
    5. Determine if white-space (below both thresholds)
    6. Compute novelty score
    7. Call Gemini for assessment (only for white-space claims)

    Args:
        session_id: UUID of the session.
        landscape: The built LandscapeMap.
        claims: List of ExtractedClaim ORM objects.
        centroids: Cluster centroids from HDBSCAN.
        db: Async DB session.

    Returns:
        List of WhitespaceOpportunity sorted by novelty_score desc.
    """
    cluster_label_map = {c.cluster_id: c.label for c in landscape.clusters}
    opportunities: list[WhitespaceOpportunity] = []

    for claim in claims:
        claim_text = getattr(claim, "claim_text", "")
        claim_type = getattr(claim, "claim_type", "method")
        confidence = getattr(claim, "confidence", 0.5)
        claim_id = getattr(claim, "id", None)

        # Step 1 — Embed
        prepared = prepare_claim_text(claim)
        claim_embedding = await encode_single(prepared)

        # Step 2 — Search neighbors
        neighbors = await qdrant_store.search_similar(
            claim_embedding, session_id=session_id,
            k=K_NEAREST, score_threshold=0.2,
        )

        # Step 3 — Average similarity
        if not neighbors:
            avg_similarity = 0.0
        else:
            avg_similarity = sum(n.score for n in neighbors) / len(neighbors)

        # Step 4 — Nearest centroid
        nearest_cid, nearest_dist = find_nearest_centroid(
            claim_embedding, centroids
        )
        nearest_label = cluster_label_map.get(nearest_cid, "unknown")

        # Step 5 — White-space check
        is_whitespace = (
            avg_similarity < WHITESPACE_THRESHOLD
            and nearest_dist > CLUSTER_DISTANCE_THRESHOLD
        )

        # Step 6 — Novelty score
        novelty_score = (1.0 - avg_similarity) * confidence
        novelty_score = min(max(novelty_score, 0.0), 1.0)

        # Step 7 — Nearest patents
        nearest_patent_ids = [
            n.payload.get("patent_id", "") for n in neighbors[:3]
        ]
        nearest_patent_titles = [
            n.payload.get("title", "") for n in neighbors[:3]
        ]

        # Step 8 — Gemini assessment (only for white-space claims)
        gemini_assessment = ""
        gemini_confidence = 0.0
        recommended_scope = "medium"
        ipc_codes = []

        if is_whitespace:
            try:
                from patent_gap_finder.ai.novelty_reasoner import assess_novelty
                assessment = await assess_novelty(
                    claim=claim,
                    nearest_patents=[
                        {"title": n.payload.get("title", ""),
                         "abstract": n.payload.get("abstract", "")}
                        for n in neighbors[:3]
                    ],
                    avg_similarity=avg_similarity,
                    nearest_cluster_label=nearest_label,
                )
                gemini_assessment = assessment.get("gemini_novelty_assessment", "")
                gemini_confidence = assessment.get("gemini_confidence", 0.0)
                recommended_scope = assessment.get("recommended_claim_scope", "medium")
                ipc_codes = assessment.get("ipc_whitespace_codes", [])
            except Exception as e:
                logger.warning("Gemini novelty assessment failed: %s", e)
                gemini_assessment = "Assessment unavailable"

        opportunity = WhitespaceOpportunity(
            opportunity_id=str(uuid.uuid4()),
            claim_text=claim_text,
            claim_type=claim_type,
            novelty_score=round(novelty_score, 4),
            avg_neighbor_similarity=round(avg_similarity, 4),
            nearest_cluster_label=nearest_label,
            nearest_cluster_distance=round(nearest_dist, 4),
            nearest_patents=nearest_patent_ids,
            nearest_patent_titles=nearest_patent_titles,
            gemini_novelty_assessment=gemini_assessment,
            gemini_confidence=gemini_confidence,
            ipc_whitespace_codes=ipc_codes,
            recommended_claim_scope=recommended_scope,
            is_whitespace=is_whitespace,
        )
        opportunities.append(opportunity)

    # Sort by novelty score descending
    opportunities.sort(key=lambda o: o.novelty_score, reverse=True)

    logger.info(
        "White-space detection: %d claims analyzed, %d opportunities found",
        len(claims),
        sum(1 for o in opportunities if o.is_whitespace),
    )

    return opportunities
