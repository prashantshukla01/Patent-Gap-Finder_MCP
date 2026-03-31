"""HDBSCAN wrapper with adaptive parameter selection and centroid computation.

Handles the quirks of clustering small patent datasets:
- Adaptive min_cluster_size based on dataset size
- Fallback chain when clustering degenerates (all noise / one cluster)
- Guard against 1D arrays and wrong embedding dimensions
"""

from __future__ import annotations

import logging
from typing import Optional

import numpy as np

from patent_gap_finder.embeddings.embedding_engine import EMBEDDING_DIM

logger = logging.getLogger(__name__)


def select_hdbscan_params(n_patents: int) -> dict:
    """Select HDBSCAN parameters based on dataset size.

    Returns:
        Dict with min_cluster_size and min_samples.
    """
    if n_patents < 80:
        return {"min_cluster_size": 3, "min_samples": 2}
    elif n_patents < 150:
        return {"min_cluster_size": 4, "min_samples": 2}
    else:
        return {"min_cluster_size": 5, "min_samples": 3}


def run_clustering(
    embeddings: np.ndarray,
    params: Optional[dict] = None,
) -> tuple[np.ndarray, np.ndarray, dict]:
    """Run HDBSCAN clustering with adaptive fallback.

    Args:
        embeddings: 2D numpy array of shape (n_patents, EMBEDDING_DIM).
        params: Optional HDBSCAN params. Auto-selected if None.

    Returns:
        (labels, probabilities, params_used) where:
        - labels: array of cluster IDs (-1 = noise)
        - probabilities: cluster membership confidence
        - params_used: the HDBSCAN parameters that were used

    Raises:
        ValueError: If embeddings array has wrong shape/dimension.
    """
    import hdbscan

    assert embeddings.ndim == 2, (
        f"Expected 2D array (n_patents, {EMBEDDING_DIM}), "
        f"got shape {embeddings.shape}"
    )
    assert embeddings.shape[1] == EMBEDDING_DIM, (
        f"Wrong embedding dimension: {embeddings.shape[1]} != {EMBEDDING_DIM}"
    )

    n_patents = embeddings.shape[0]

    if params is None:
        params = select_hdbscan_params(n_patents)

    current_params = dict(params)
    max_retries = 2

    for attempt in range(max_retries + 1):
        clusterer = hdbscan.HDBSCAN(
            min_cluster_size=current_params["min_cluster_size"],
            min_samples=current_params["min_samples"],
            metric="euclidean",
            cluster_selection_method="eom",
            prediction_data=True,
        )
        labels = clusterer.fit_predict(embeddings)
        probabilities = clusterer.probabilities_

        n_clusters = len(set(labels)) - (1 if -1 in labels else 0)
        noise_count = int((labels == -1).sum())

        logger.info(
            "HDBSCAN attempt %d: n_clusters=%d noise=%d params=%s",
            attempt + 1, n_clusters, noise_count, current_params,
        )

        if n_clusters == 0 and attempt < max_retries:
            # All noise — reduce min_cluster_size
            current_params["min_cluster_size"] = max(
                2, current_params["min_cluster_size"] - 1
            )
            logger.warning("All noise — reducing min_cluster_size to %d",
                           current_params["min_cluster_size"])
            continue

        if n_clusters == 1 and attempt < max_retries:
            # One cluster — increase min_cluster_size
            current_params["min_cluster_size"] += 2
            logger.warning("Single cluster — increasing min_cluster_size to %d",
                           current_params["min_cluster_size"])
            continue

        break

    return labels, probabilities, current_params


def compute_centroids(
    embeddings: np.ndarray,
    labels: np.ndarray,
) -> dict[int, np.ndarray]:
    """Compute cluster centroids (mean embedding per cluster).

    Excludes noise points (label == -1).

    Returns:
        {cluster_id: centroid_embedding} dict.
    """
    centroids = {}
    for cluster_id in set(labels):
        if cluster_id == -1:
            continue
        mask = labels == cluster_id
        cluster_embeddings = embeddings[mask]
        centroids[int(cluster_id)] = cluster_embeddings.mean(axis=0)
    return centroids


def find_centroid_patents(
    embeddings: np.ndarray,
    labels: np.ndarray,
    patent_ids: list[str],
    cluster_id: int,
    n: int = 3,
) -> list[str]:
    """Find the N patents closest to the centroid of a cluster.

    Args:
        embeddings: All patent embeddings.
        labels: Cluster labels for each patent.
        patent_ids: DB UUIDs corresponding to each embedding.
        cluster_id: Cluster to find central patents for.
        n: Number of central patents to return.

    Returns:
        List of patent_id strings closest to the centroid.
    """
    mask = labels == cluster_id
    cluster_embeddings = embeddings[mask]
    cluster_ids = [patent_ids[i] for i, m in enumerate(mask) if m]

    if len(cluster_ids) == 0:
        return []

    centroid = cluster_embeddings.mean(axis=0)
    distances = np.linalg.norm(cluster_embeddings - centroid, axis=1)
    sorted_indices = np.argsort(distances)[:n]

    return [cluster_ids[i] for i in sorted_indices]


def compute_intra_cluster_similarity(
    embeddings: np.ndarray,
    labels: np.ndarray,
    cluster_id: int,
) -> float:
    """Compute average cosine similarity between all pairs in a cluster.

    For large clusters (> 50), samples 50 random pairs.

    Returns:
        Average cosine similarity [0, 1].
    """
    mask = labels == cluster_id
    cluster_embeddings = embeddings[mask]
    n = len(cluster_embeddings)

    if n < 2:
        return 1.0

    # Normalize for cosine similarity
    norms = np.linalg.norm(cluster_embeddings, axis=1, keepdims=True)
    norms = np.where(norms == 0, 1, norms)
    normalized = cluster_embeddings / norms

    if n <= 50:
        # All pairs
        sim_matrix = normalized @ normalized.T
        # Extract upper triangle (excluding diagonal)
        upper_indices = np.triu_indices(n, k=1)
        similarities = sim_matrix[upper_indices]
    else:
        # Sample 50 random pairs
        rng = np.random.default_rng(42)
        idx1 = rng.integers(0, n, size=50)
        idx2 = rng.integers(0, n, size=50)
        # Avoid same-index pairs
        idx2 = np.where(idx1 == idx2, (idx2 + 1) % n, idx2)
        similarities = np.sum(normalized[idx1] * normalized[idx2], axis=1)

    return float(np.mean(similarities))
