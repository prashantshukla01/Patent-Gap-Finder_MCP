"""Automated evaluation metrics for embeddings, HDBSCAN clustering, whitespace, and patent claims."""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

import numpy as np

logger = logging.getLogger("observability.metrics")


try:
    from sklearn.metrics import silhouette_score as _silhouette_score
except Exception:
    _silhouette_score = None


def compute_clustering_metrics(embeddings: np.ndarray, labels: np.ndarray) -> Dict[str, float]:
    """Compute mathematical quality metrics for HDBSCAN clustering.

    Returns:
        Dict containing:
            - cluster_count: Number of valid thematic clusters formed
            - noise_count: Number of outlier points (label == -1)
            - noise_ratio: Percentage of points marked as noise (0.0 - 1.0)
            - silhouette_score: Metric of cluster separation and compactness (-1.0 to 1.0)
    """
    if len(embeddings) == 0 or len(labels) == 0:
        return {
            "cluster_count": 0.0,
            "noise_count": 0.0,
            "noise_ratio": 0.0,
            "silhouette_score": 0.0,
        }

    n_samples = len(labels)
    unique_labels = set(labels)
    non_noise_labels = [lbl for lbl in unique_labels if lbl != -1]
    n_clusters = len(non_noise_labels)
    noise_count = int((labels == -1).sum())
    noise_ratio = float(noise_count / n_samples) if n_samples > 0 else 0.0

    metrics: Dict[str, float] = {
        "cluster_count": float(n_clusters),
        "noise_count": float(noise_count),
        "noise_ratio": round(noise_ratio, 4),
        "silhouette_score": 0.0,
    }

    # Silhouette score requires at least 2 distinct clusters and >= 2 non-noise points
    if n_clusters >= 2 and _silhouette_score is not None:
        try:
            # Filter out noise points for assessing cluster separation quality
            non_noise_mask = labels != -1
            if non_noise_mask.sum() >= n_clusters + 1:
                filtered_emb = embeddings[non_noise_mask]
                filtered_lbl = labels[non_noise_mask]
                score = float(_silhouette_score(filtered_emb, filtered_lbl, metric="cosine"))
                metrics["silhouette_score"] = round(score, 4)
        except Exception as e:
            logger.debug("Failed to calculate silhouette score: %s", e)

    return metrics


def compute_whitespace_metrics(
    whitespace_opportunities: List[Dict[str, Any]],
    patent_embeddings: Optional[np.ndarray] = None,
) -> Dict[str, float]:
    """Compute opportunity density and distance metrics for detected whitespace gaps."""
    if not whitespace_opportunities:
        return {
            "opportunity_count": 0.0,
            "avg_confidence": 0.0,
            "min_distance": 0.0,
        }

    count = len(whitespace_opportunities)
    confidences = [
        float(op.get("confidence") or op.get("gap_score") or 0.8)
        for op in whitespace_opportunities
    ]
    avg_confidence = sum(confidences) / count if count > 0 else 0.0

    distances = [
        float(op.get("distance_to_nearest") or 0.5)
        for op in whitespace_opportunities
        if "distance_to_nearest" in op
    ]
    min_dist = min(distances) if distances else 0.0

    return {
        "opportunity_count": float(count),
        "avg_confidence": round(avg_confidence, 4),
        "min_distance": round(min_dist, 4),
    }


def evaluate_claim_structure(claim_text: str) -> Dict[str, Any]:
    """Evaluate structural patent drafting compliance (MPEP 2111 standard).

    Checks:
    1. Preamble (e.g. '1. A method for...', '1. An apparatus comprising...')
    2. Transitional phrase ('comprising', 'consisting of', 'consisting essentially of')
    3. Body elements count (semicolon/colon delimited clauses)
    4. Compliance score (0.0 to 1.0)
    """
    if not claim_text or not claim_text.strip():
        return {
            "is_valid": False,
            "has_preamble": False,
            "has_transition": False,
            "element_count": 0,
            "structural_score": 0.0,
        }

    text = claim_text.strip()

    # 1. Preamble check: starts with claim number and subject matter
    has_preamble = bool(re.match(r"^\s*(?:claim\s*)?\d+[\.:]\s*(?:A|An|The)\s+\w+", text, re.IGNORECASE))

    # 2. Transitional phrase check
    transition_patterns = [
        r"\bcomprising\b",
        r"\bcomprises\b",
        r"\bconsisting of\b",
        r"\bconsisting essentially of\b",
        r"\bcharacterized in that\b",
    ]
    has_transition = any(re.search(pat, text, re.IGNORECASE) for pat in transition_patterns)

    # 3. Body elements count: count clauses ending with semicolons or numbered items
    clauses = re.split(r";|\n\s*[-–•\(\d\)]+|\n\s*[a-z]\)", text)
    element_count = max(1, len([c for c in clauses if len(c.strip()) > 10]))

    # 4. Calculate score
    score = 0.0
    if has_preamble:
        score += 0.35
    if has_transition:
        score += 0.35
    if element_count >= 2:
        score += 0.30
    elif element_count == 1:
        score += 0.15

    return {
        "is_valid": score >= 0.70,
        "has_preamble": has_preamble,
        "has_transition": has_transition,
        "element_count": element_count,
        "structural_score": round(score, 2),
    }
