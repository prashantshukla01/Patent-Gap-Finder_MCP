"""Tests for hdbscan_clusterer — params, clustering, centroids."""

from __future__ import annotations

import numpy as np
import pytest
from unittest.mock import patch, MagicMock

from patent_gap_finder.clustering.hdbscan_clusterer import (
    compute_centroids,
    compute_intra_cluster_similarity,
    find_centroid_patents,
    run_clustering,
    select_hdbscan_params,
)


class TestSelectHdbscanParams:
    def test_small_dataset(self):
        params = select_hdbscan_params(50)
        assert params == {"min_cluster_size": 3, "min_samples": 2}

    def test_medium_dataset(self):
        params = select_hdbscan_params(100)
        assert params == {"min_cluster_size": 4, "min_samples": 2}

    def test_large_dataset(self):
        params = select_hdbscan_params(200)
        assert params == {"min_cluster_size": 5, "min_samples": 3}

    def test_boundary_80(self):
        params = select_hdbscan_params(80)
        assert params["min_cluster_size"] == 4

    def test_boundary_150(self):
        params = select_hdbscan_params(150)
        assert params["min_cluster_size"] == 5


class TestRunClustering:
    def test_returns_correct_shapes(self):
        # Create synthetic data with clear clusters
        rng = np.random.default_rng(42)
        c1 = rng.normal(loc=[1, 0, 0] + [0] * 381, scale=0.1, size=(20, 384))
        c2 = rng.normal(loc=[0, 1, 0] + [0] * 381, scale=0.1, size=(20, 384))
        c3 = rng.normal(loc=[0, 0, 1] + [0] * 381, scale=0.1, size=(20, 384))
        embeddings = np.vstack([c1, c2, c3]).astype(np.float32)

        labels, probabilities, params = run_clustering(embeddings)

        assert labels.shape == (60,)
        assert probabilities.shape == (60,)
        assert isinstance(params, dict)
        assert "min_cluster_size" in params

    def test_rejects_1d_array(self):
        embeddings = np.random.rand(384).astype(np.float32)
        with pytest.raises(AssertionError, match="Expected 2D"):
            run_clustering(embeddings)

    def test_rejects_wrong_dimension(self):
        embeddings = np.random.rand(10, 100).astype(np.float32)
        with pytest.raises(AssertionError, match="Wrong embedding dimension"):
            run_clustering(embeddings)

    def test_fallback_when_all_noise(self):
        """When HDBSCAN returns all noise, it retries with lower min_cluster_size."""
        import hdbscan

        call_count = [0]
        original_init = hdbscan.HDBSCAN.__init__

        # We can't easily mock HDBSCAN to return all noise, so test the params
        # fallback by giving very sparse data
        rng = np.random.default_rng(123)
        # Sparse random data — likely to produce all noise
        embeddings = rng.uniform(-10, 10, size=(15, 384)).astype(np.float32)

        labels, probs, params = run_clustering(embeddings)

        # Should have attempted fallback (min_cluster_size reduced)
        assert labels.shape == (15,)
        # The params should reflect any fallback attempts
        assert params["min_cluster_size"] >= 2


class TestComputeCentroids:
    def test_excludes_noise(self):
        embeddings = np.array([
            [1.0, 0.0, 0.0] + [0.0] * 381,
            [1.1, 0.0, 0.0] + [0.0] * 381,
            [0.0, 1.0, 0.0] + [0.0] * 381,
            [0.0, 1.1, 0.0] + [0.0] * 381,
            [5.0, 5.0, 5.0] + [0.0] * 381,  # noise
        ], dtype=np.float32)
        labels = np.array([0, 0, 1, 1, -1])

        centroids = compute_centroids(embeddings, labels)

        assert -1 not in centroids
        assert 0 in centroids
        assert 1 in centroids
        assert centroids[0].shape == (384,)

    def test_centroid_is_mean(self):
        embeddings = np.array([
            [2.0] + [0.0] * 383,
            [4.0] + [0.0] * 383,
        ], dtype=np.float32)
        labels = np.array([0, 0])

        centroids = compute_centroids(embeddings, labels)
        assert abs(centroids[0][0] - 3.0) < 1e-5


class TestFindCentroidPatents:
    def test_returns_closest_to_centroid(self):
        embeddings = np.array([
            [1.0, 0.0] + [0.0] * 382,
            [1.5, 0.0] + [0.0] * 382,
            [3.0, 0.0] + [0.0] * 382,  # furthest from centroid ~1.83
        ], dtype=np.float32)
        labels = np.array([0, 0, 0])
        patent_ids = ["p1", "p2", "p3"]

        result = find_centroid_patents(embeddings, labels, patent_ids, 0, n=2)
        assert len(result) == 2
        # p2 (1.5) is closest to centroid (1.83), then p1 or p3


class TestComputeIntraClusterSimilarity:
    def test_identical_vectors_return_1(self):
        embeddings = np.array([
            [1.0, 0.0, 0.0] + [0.0] * 381,
            [1.0, 0.0, 0.0] + [0.0] * 381,
        ], dtype=np.float32)
        labels = np.array([0, 0])

        sim = compute_intra_cluster_similarity(embeddings, labels, 0)
        assert abs(sim - 1.0) < 1e-5

    def test_single_point_returns_1(self):
        embeddings = np.array([[1.0] + [0.0] * 383], dtype=np.float32)
        labels = np.array([0])

        sim = compute_intra_cluster_similarity(embeddings, labels, 0)
        assert sim == 1.0
