"""Tests for map_landscape MCP tool."""

from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from patent_gap_finder.models.landscape import ClusterInfo, LandscapeMap


def _fake_db_session(mock_session=None):
    if mock_session is None:
        mock_session = AsyncMock()

    @asynccontextmanager
    async def fake_db():
        yield mock_session

    return fake_db


class TestMapLandscapeTool:
    async def test_invalid_session_id(self):
        from patent_gap_finder.tools.map_landscape import map_landscape
        result = await map_landscape("not-a-uuid")
        assert result["error"] == "INVALID_SESSION_ID"

    async def test_qdrant_unavailable(self):
        """Qdrant connection failure returns structured error."""
        from patent_gap_finder.tools.map_landscape import map_landscape

        with patch.dict("sys.modules", {}):
            with patch(
                "patent_gap_finder.embeddings.qdrant_store.ensure_collection_exists",
                new_callable=AsyncMock,
                side_effect=Exception("Connection refused"),
            ):
                result = await map_landscape("12345678-1234-1234-1234-123456789abc")
                assert result["error"] == "QDRANT_UNAVAILABLE"

    @patch("patent_gap_finder.embeddings.qdrant_store.ensure_collection_exists", new_callable=AsyncMock)
    @patch("patent_gap_finder.db.connection.get_db_session")
    async def test_session_not_found(self, mock_db, mock_qdrant):
        from patent_gap_finder.tools.map_landscape import map_landscape

        mock_session_db = AsyncMock()
        mock_db.side_effect = _fake_db_session(mock_session_db)

        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = None
        mock_session_db.execute.return_value = mock_result

        result = await map_landscape("12345678-1234-1234-1234-123456789abc")
        assert result["error"] == "SESSION_NOT_FOUND"

    @patch("patent_gap_finder.embeddings.qdrant_store.ensure_collection_exists", new_callable=AsyncMock)
    @patch("patent_gap_finder.db.connection.get_db_session")
    async def test_phase3_incomplete(self, mock_db, mock_qdrant):
        from patent_gap_finder.tools.map_landscape import map_landscape

        mock_session_db = AsyncMock()
        mock_db.side_effect = _fake_db_session(mock_session_db)

        session = MagicMock()
        session.patent_search_complete = False

        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = session
        mock_session_db.execute.return_value = mock_result

        result = await map_landscape("12345678-1234-1234-1234-123456789abc")
        assert result["error"] == "PHASE3_INCOMPLETE"

    @patch("patent_gap_finder.db.repositories.landscape_repo.get_latest_landscape_job", new_callable=AsyncMock)
    @patch("patent_gap_finder.embeddings.qdrant_store.ensure_collection_exists", new_callable=AsyncMock)
    @patch("patent_gap_finder.db.connection.get_db_session")
    async def test_existing_landscape_returns_cached(self, mock_db, mock_qdrant, mock_latest_job):
        from patent_gap_finder.tools.map_landscape import map_landscape

        mock_session_db = AsyncMock()
        mock_db.side_effect = _fake_db_session(mock_session_db)

        session = MagicMock()
        session.patent_search_complete = True

        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = session
        mock_session_db.execute.return_value = mock_result

        existing_job = MagicMock()
        existing_job.id = "job-123"
        existing_job.status = "complete"
        existing_job.n_patents_embedded = 50
        existing_job.n_clusters = 5
        existing_job.noise_patent_count = 3
        existing_job.embedding_model = "all-MiniLM-L6-v2"
        existing_job.cluster_records = []
        mock_latest_job.return_value = existing_job

        result = await map_landscape("12345678-1234-1234-1234-123456789abc")
        assert result["status"] == "complete"
        assert "already built" in result.get("note", "")

    @patch("patent_gap_finder.clustering.landscape_builder.build_landscape", new_callable=AsyncMock)
    @patch("patent_gap_finder.db.repositories.landscape_repo.update_landscape_job_status", new_callable=AsyncMock)
    @patch("patent_gap_finder.db.repositories.landscape_repo.create_landscape_job", new_callable=AsyncMock)
    @patch("patent_gap_finder.db.repositories.landscape_repo.get_latest_landscape_job", new_callable=AsyncMock)
    @patch("patent_gap_finder.embeddings.qdrant_store.ensure_collection_exists", new_callable=AsyncMock)
    @patch("patent_gap_finder.db.connection.get_db_session")
    async def test_insufficient_patents(
        self, mock_db, mock_qdrant, mock_latest_job,
        mock_create_job, mock_update_status, mock_build
    ):
        from patent_gap_finder.tools.map_landscape import map_landscape
        from patent_gap_finder.clustering.landscape_builder import InsufficientPatentsError

        mock_session_db = AsyncMock()
        mock_db.side_effect = _fake_db_session(mock_session_db)

        session = MagicMock()
        session.patent_search_complete = True

        mock_result = MagicMock()
        mock_result.scalars.return_value.first.return_value = session
        mock_session_db.execute.return_value = mock_result

        mock_latest_job.return_value = None
        job = MagicMock()
        job.id = "job-new"
        mock_create_job.return_value = job

        mock_build.side_effect = InsufficientPatentsError("Need 5, found 2")

        result = await map_landscape("12345678-1234-1234-1234-123456789abc")
        assert result["error"] == "INSUFFICIENT_PATENTS"
