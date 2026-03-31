"""Tests for find_whitespace MCP tool."""

from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest


def _fake_db_session(mock_session=None):
    if mock_session is None:
        mock_session = AsyncMock()

    @asynccontextmanager
    async def fake_db():
        yield mock_session

    return fake_db


class TestFindWhitespaceTool:
    async def test_invalid_session_id(self):
        from patent_gap_finder.tools.find_whitespace import find_whitespace
        result = await find_whitespace("not-a-uuid")
        assert result["error"] == "INVALID_SESSION_ID"

    @patch("patent_gap_finder.db.connection.get_db_session")
    async def test_session_not_found(self, mock_db):
        from patent_gap_finder.tools.find_whitespace import find_whitespace

        mock_session_db = AsyncMock()
        mock_db.side_effect = _fake_db_session(mock_session_db)

        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = None
        mock_session_db.execute.return_value = mock_result

        result = await find_whitespace("12345678-1234-1234-1234-123456789abc")
        assert result["error"] == "SESSION_NOT_FOUND"

    @patch("patent_gap_finder.db.connection.get_db_session")
    async def test_landscape_incomplete(self, mock_db):
        from patent_gap_finder.tools.find_whitespace import find_whitespace

        mock_session_db = AsyncMock()
        mock_db.side_effect = _fake_db_session(mock_session_db)

        session = MagicMock()
        session.landscape_complete = False

        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = session
        mock_session_db.execute.return_value = mock_result

        result = await find_whitespace("12345678-1234-1234-1234-123456789abc")
        assert result["error"] == "PHASE4_LANDSCAPE_INCOMPLETE"

    @patch("patent_gap_finder.db.repositories.landscape_repo.get_latest_landscape_job", new_callable=AsyncMock)
    @patch("patent_gap_finder.db.connection.get_db_session")
    async def test_no_ai_claims(self, mock_db, mock_latest_job):
        from patent_gap_finder.tools.find_whitespace import find_whitespace

        mock_session_db = AsyncMock()
        mock_db.side_effect = _fake_db_session(mock_session_db)

        session = MagicMock()
        session.landscape_complete = True

        job = MagicMock()
        job.status = "complete"
        job.n_patents_embedded = 50
        job.n_clusters = 3
        job.noise_patent_count = 2
        job.embedding_model = "all-MiniLM-L6-v2"
        job.hdbscan_params = {}
        job.cluster_records = []
        job.id = "job-1"
        mock_latest_job.return_value = job

        call_count = [0]
        def side_effect(*args, **kwargs):
            call_count[0] += 1
            result = MagicMock()
            if call_count[0] == 1:
                result.scalars.return_value.first.return_value = session
            else:
                result.scalars.return_value.all.return_value = []
            return result

        mock_session_db.execute.side_effect = side_effect

        result = await find_whitespace("12345678-1234-1234-1234-123456789abc")
        assert result["error"] == "NO_AI_CLAIMS"

    @patch("patent_gap_finder.clustering.whitespace_detector.detect_whitespace", new_callable=AsyncMock)
    @patch("patent_gap_finder.clustering.hdbscan_clusterer.compute_centroids")
    @patch("patent_gap_finder.embeddings.qdrant_store.get_all_session_embeddings", new_callable=AsyncMock)
    @patch("patent_gap_finder.db.repositories.patent_repo.get_patents_for_session", new_callable=AsyncMock)
    @patch("patent_gap_finder.db.repositories.landscape_repo.create_whitespace_opportunities", new_callable=AsyncMock)
    @patch("patent_gap_finder.db.repositories.landscape_repo.get_latest_landscape_job", new_callable=AsyncMock)
    @patch("patent_gap_finder.db.connection.get_db_session")
    async def test_top_opportunity_count(
        self, mock_db, mock_latest_job, mock_create_opp,
        mock_get_patents, mock_get_emb, mock_centroids, mock_detect
    ):
        from patent_gap_finder.tools.find_whitespace import find_whitespace
        from patent_gap_finder.models.landscape import WhitespaceOpportunity

        mock_session_db = AsyncMock()
        mock_db.side_effect = _fake_db_session(mock_session_db)

        session = MagicMock()
        session.landscape_complete = True
        session.whitespace_analysis_complete = False
        session.top_opportunity_count = None

        job = MagicMock()
        job.status = "complete"
        job.n_patents_embedded = 50
        job.n_clusters = 3
        job.noise_patent_count = 2
        job.embedding_model = "all-MiniLM-L6-v2"
        job.hdbscan_params = {}
        job.cluster_records = []
        job.id = "job-1"
        mock_latest_job.return_value = job

        claim1 = MagicMock()
        claim1.id = "c1"
        claim1.claim_text = "Novel method"
        claim1.confidence = 0.9

        call_count = [0]
        def side_effect(*args, **kwargs):
            call_count[0] += 1
            result = MagicMock()
            if call_count[0] == 1:
                result.scalars.return_value.first.return_value = session
            else:
                result.scalars.return_value.all.return_value = [claim1]
            return result

        mock_session_db.execute.side_effect = side_effect

        mock_get_emb.return_value = (
            ["id-1"], np.random.rand(1, 384).astype(np.float32)
        )
        mock_get_patents.return_value = [MagicMock(id="id-1", cluster_id=0)]
        mock_centroids.return_value = {0: np.zeros(384, dtype=np.float32)}

        mock_detect.return_value = [
            WhitespaceOpportunity(
                opportunity_id="opp-1",
                claim_text="Novel method",
                novelty_score=0.85,
                avg_neighbor_similarity=0.3,
                is_whitespace=True,
            ),
        ]

        result = await find_whitespace(
            "12345678-1234-1234-1234-123456789abc",
            min_novelty_score=0.5,
        )

        assert result["top_opportunities"] == 1
        assert len(result["whitespace_opportunities"]) == 1
        mock_create_opp.assert_called_once()
