"""Tests for whitespace_detector — scoring, thresholds, centroids."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest

from patent_gap_finder.clustering.whitespace_detector import (
    CLUSTER_DISTANCE_THRESHOLD,
    WHITESPACE_THRESHOLD,
    find_nearest_centroid,
)
from patent_gap_finder.models.landscape import ClusterInfo, LandscapeMap


def _make_claim(text="test claim", confidence=0.8, claim_type="method"):
    return SimpleNamespace(
        id="claim-1",
        claim_text=text,
        claim_type=claim_type,
        confidence=confidence,
        primary_ipc="G06N",
    )


def _make_scored_point(patent_id, title, score, abstract=""):
    sp = MagicMock()
    sp.score = score
    sp.payload = {"patent_id": patent_id, "title": title, "abstract": abstract}
    return sp


def _make_landscape():
    return LandscapeMap(
        session_id="sess-1",
        total_patents_embedded=50,
        n_clusters=2,
        noise_patent_count=5,
        clusters=[
            ClusterInfo(cluster_id=0, label="attention mechanisms", patent_count=25),
            ClusterInfo(cluster_id=1, label="image recognition", patent_count=20),
        ],
    )


class TestFindNearestCentroid:
    def test_returns_nearest(self):
        claim_emb = np.array([1.0, 0.0] + [0.0] * 382, dtype=np.float32)
        centroids = {
            0: np.array([2.0, 0.0] + [0.0] * 382, dtype=np.float32),
            1: np.array([10.0, 0.0] + [0.0] * 382, dtype=np.float32),
        }
        cid, dist = find_nearest_centroid(claim_emb, centroids)
        assert cid == 0
        assert abs(dist - 1.0) < 1e-5

    def test_empty_centroids(self):
        claim_emb = np.array([1.0] + [0.0] * 383, dtype=np.float32)
        cid, dist = find_nearest_centroid(claim_emb, {})
        assert cid == -1
        assert dist == 999.0


class TestDetectWhitespace:
    @patch("patent_gap_finder.clustering.whitespace_detector.qdrant_store")
    @patch("patent_gap_finder.clustering.whitespace_detector.encode_single")
    async def test_whitespace_detected(self, mock_encode, mock_qdrant):
        """Claim with low similarity and high distance → is_whitespace=True."""
        from patent_gap_finder.clustering.whitespace_detector import detect_whitespace

        claim_emb = np.array([1.0] + [0.0] * 383, dtype=np.float32)
        mock_encode.return_value = claim_emb

        # Low similarity neighbors
        mock_qdrant.search_similar = AsyncMock(return_value=[
            _make_scored_point("US-1", "Patent 1", 0.3),
            _make_scored_point("US-2", "Patent 2", 0.4),
        ])

        landscape = _make_landscape()
        claims = [_make_claim(confidence=0.8)]

        # Centroid far away → high distance
        centroids = {
            0: np.array([10.0] + [0.0] * 383, dtype=np.float32),
            1: np.array([20.0] + [0.0] * 383, dtype=np.float32),
        }

        db = AsyncMock()
        # Patch assess_novelty at its SOURCE module
        with patch("patent_gap_finder.ai.gemini_client.get_gemini_client") as mock_gc:
            mock_client = AsyncMock()
            mock_client.complete.return_value = (
                '{"gemini_novelty_assessment": "Novel", '
                '"gemini_confidence": 0.9, '
                '"recommended_claim_scope": "broad", '
                '"ipc_whitespace_codes": ["G06N"], '
                '"key_differentiators": []}'
            )
            mock_gc.return_value = mock_client

            result = await detect_whitespace(
                "sess-1", landscape, claims, centroids, db
            )

        assert len(result) == 1
        assert result[0].is_whitespace is True
        assert result[0].avg_neighbor_similarity == 0.35  # (0.3+0.4)/2

    @patch("patent_gap_finder.clustering.whitespace_detector.qdrant_store")
    @patch("patent_gap_finder.clustering.whitespace_detector.encode_single")
    async def test_high_similarity_not_whitespace(self, mock_encode, mock_qdrant):
        """Claim with high similarity → is_whitespace=False."""
        from patent_gap_finder.clustering.whitespace_detector import detect_whitespace

        claim_emb = np.array([1.0] + [0.0] * 383, dtype=np.float32)
        mock_encode.return_value = claim_emb

        mock_qdrant.search_similar = AsyncMock(return_value=[
            _make_scored_point("US-1", "Patent 1", 0.85),
            _make_scored_point("US-2", "Patent 2", 0.9),
        ])

        landscape = _make_landscape()
        claims = [_make_claim()]
        centroids = {0: np.array([1.1] + [0.0] * 383, dtype=np.float32)}

        db = AsyncMock()
        result = await detect_whitespace("sess-1", landscape, claims, centroids, db)

        assert len(result) == 1
        assert result[0].is_whitespace is False

    @patch("patent_gap_finder.clustering.whitespace_detector.qdrant_store")
    @patch("patent_gap_finder.clustering.whitespace_detector.encode_single")
    async def test_close_to_cluster_not_whitespace(self, mock_encode, mock_qdrant):
        """Claim close to cluster centroid → not whitespace even if low similarity."""
        from patent_gap_finder.clustering.whitespace_detector import detect_whitespace

        claim_emb = np.array([1.0] + [0.0] * 383, dtype=np.float32)
        mock_encode.return_value = claim_emb

        mock_qdrant.search_similar = AsyncMock(return_value=[
            _make_scored_point("US-1", "P1", 0.4),
        ])

        landscape = _make_landscape()
        claims = [_make_claim()]
        centroids = {0: np.array([1.01] + [0.0] * 383, dtype=np.float32)}

        db = AsyncMock()
        result = await detect_whitespace("sess-1", landscape, claims, centroids, db)

        assert result[0].is_whitespace is False

    @patch("patent_gap_finder.clustering.whitespace_detector.qdrant_store")
    @patch("patent_gap_finder.clustering.whitespace_detector.encode_single")
    async def test_novelty_score_clamped(self, mock_encode, mock_qdrant):
        """Novelty score = (1 - avg_sim) * confidence, clamped to [0, 1]."""
        from patent_gap_finder.clustering.whitespace_detector import detect_whitespace

        claim_emb = np.zeros(384, dtype=np.float32)
        mock_encode.return_value = claim_emb
        mock_qdrant.search_similar = AsyncMock(return_value=[
            _make_scored_point("US-1", "P", 0.2),
        ])

        landscape = _make_landscape()
        claims = [_make_claim(confidence=0.9)]
        centroids = {0: np.array([10.0] + [0.0] * 383, dtype=np.float32)}

        db = AsyncMock()
        with patch("patent_gap_finder.ai.gemini_client.get_gemini_client") as mock_gc:
            mock_client = AsyncMock()
            mock_client.complete.return_value = (
                '{"gemini_novelty_assessment": "Novel", '
                '"gemini_confidence": 0.8, '
                '"recommended_claim_scope": "broad", '
                '"ipc_whitespace_codes": [], '
                '"key_differentiators": []}'
            )
            mock_gc.return_value = mock_client

            result = await detect_whitespace("sess-1", landscape, claims, centroids, db)

        expected = round((1.0 - 0.2) * 0.9, 4)
        assert result[0].novelty_score == expected
        assert 0.0 <= result[0].novelty_score <= 1.0

    @patch("patent_gap_finder.clustering.whitespace_detector.qdrant_store")
    @patch("patent_gap_finder.clustering.whitespace_detector.encode_single")
    async def test_gemini_only_called_for_whitespace(self, mock_encode, mock_qdrant):
        """Gemini NOT called when is_whitespace=False."""
        from patent_gap_finder.clustering.whitespace_detector import detect_whitespace

        claim_emb = np.zeros(384, dtype=np.float32)
        mock_encode.return_value = claim_emb
        mock_qdrant.search_similar = AsyncMock(return_value=[
            _make_scored_point("US-1", "P", 0.9),
        ])

        landscape = _make_landscape()
        claims = [_make_claim()]
        centroids = {0: np.array([0.01] + [0.0] * 383, dtype=np.float32)}

        db = AsyncMock()
        with patch("patent_gap_finder.ai.gemini_client.get_gemini_client") as mock_gc:
            result = await detect_whitespace("sess-1", landscape, claims, centroids, db)
            # Non-whitespace → assess_novelty never called → get_gemini_client never called
            mock_gc.assert_not_called()
