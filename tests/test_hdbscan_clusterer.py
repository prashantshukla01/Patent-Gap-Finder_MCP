"""Tests for hdbscan_clusterer — params, clustering, centroids."""

from __future__ import annotations

import numpy as np
import pytest
from unittest.mock import patch, MagicMock

from clustering.hdbscan_clusterer import (
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
        mock_hdbscan = MagicMock()
        mock_instance = MagicMock()
        mock_instance.fit_predict.return_value = np.array([0] * 20 + [1] * 20 + [2] * 20)
        mock_instance.probabilities_ = np.ones(60)
        mock_hdbscan.HDBSCAN.return_value = mock_instance

        with patch.dict("sys.modules", {"hdbscan": mock_hdbscan}):
            embeddings = np.random.rand(60, 384).astype(np.float32)
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
        mock_hdbscan = MagicMock()
        mock_instance_0 = MagicMock()
        mock_instance_0.fit_predict.return_value = np.full(15, -1)
        mock_instance_0.probabilities_ = np.zeros(15)

        mock_instance_1 = MagicMock()
        mock_instance_1.fit_predict.return_value = np.array([0] * 5 + [1] * 5 + [-1] * 5)
        mock_instance_1.probabilities_ = np.ones(15)

        mock_hdbscan.HDBSCAN.side_effect = [mock_instance_0, mock_instance_1]

        with patch.dict("sys.modules", {"hdbscan": mock_hdbscan}):
            embeddings = np.random.rand(15, 384).astype(np.float32)
            labels, probs, params = run_clustering(embeddings)

            assert mock_hdbscan.HDBSCAN.call_count == 2
            assert labels.shape == (15,)
            assert params["min_cluster_size"] == 2


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
