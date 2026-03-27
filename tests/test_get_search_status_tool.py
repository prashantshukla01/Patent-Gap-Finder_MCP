"""Tests for get_search_status MCP tool."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _fake_db_session(mock_session=None):
    if mock_session is None:
        mock_session = AsyncMock()

    @asynccontextmanager
    async def fake_db():
        yield mock_session

    return fake_db


class TestGetSearchStatusTool:
    async def test_invalid_job_id(self):
        from patent_gap_finder.tools.get_search_status import get_search_status

        result = await get_search_status("not-a-uuid")
        assert result["error"] == "INVALID_JOB_ID"

    @patch("patent_gap_finder.tools.get_search_status.get_db_session")
    @patch("patent_gap_finder.tools.get_search_status.job_repo")
    async def test_job_not_found(self, mock_jrepo, mock_db):
        from patent_gap_finder.tools.get_search_status import get_search_status

        mock_db.side_effect = _fake_db_session()
        mock_jrepo.get_job = AsyncMock(return_value=None)

        result = await get_search_status("12345678-1234-1234-1234-123456789abc")
        assert result["error"] == "JOB_NOT_FOUND"

    @patch("patent_gap_finder.tools.get_search_status.get_db_session")
    @patch("patent_gap_finder.tools.get_search_status.job_repo")
    async def test_pending_job(self, mock_jrepo, mock_db):
        from patent_gap_finder.tools.get_search_status import get_search_status

        job = MagicMock()
        job.id = "job-1"
        job.session_id = "sess-1"
        job.status = "pending"
        job.celery_task_id = None
        job.result_count = None
        job.uspto_count = None
        job.epo_count = None
        job.serpapi_count = None
        job.dedup_removed = None
        job.cache_hit_uspto = False
        job.cache_hit_epo = False
        job.duration_seconds = None
        job.error_message = None
        job.completed_at = None

        mock_db.side_effect = _fake_db_session()
        mock_jrepo.get_job = AsyncMock(return_value=job)

        result = await get_search_status("12345678-1234-1234-1234-123456789abc")
        assert result["status"] == "pending"
        assert "Poll again" in result["next_step"]

    @patch("patent_gap_finder.tools.get_search_status.get_db_session")
    @patch("patent_gap_finder.tools.get_search_status.job_repo")
    async def test_complete_job(self, mock_jrepo, mock_db):
        from patent_gap_finder.tools.get_search_status import get_search_status

        job = MagicMock()
        job.id = "job-1"
        job.session_id = "sess-1"
        job.status = "complete"
        job.celery_task_id = "celery-1"
        job.result_count = 50
        job.uspto_count = 30
        job.epo_count = 20
        job.serpapi_count = 0
        job.dedup_removed = 5
        job.cache_hit_uspto = True
        job.cache_hit_epo = False
        job.duration_seconds = 12.5
        job.error_message = None
        job.completed_at = datetime.now(timezone.utc)

        mock_db.side_effect = _fake_db_session()
        mock_jrepo.get_job = AsyncMock(return_value=job)

        # Patch the celery imports that happen inside the function
        with patch.dict("sys.modules", {
            "patent_gap_finder.workers.celery_app": MagicMock(),
            "celery.result": MagicMock(),
        }):
            result = await get_search_status("12345678-1234-1234-1234-123456789abc")

        assert result["status"] == "complete"
        assert result["progress"]["patents_found"] == 50
        assert "get_session" in result["next_step"]

    @patch("patent_gap_finder.tools.get_search_status.get_db_session")
    @patch("patent_gap_finder.tools.get_search_status.job_repo")
    async def test_failed_job(self, mock_jrepo, mock_db):
        from patent_gap_finder.tools.get_search_status import get_search_status

        job = MagicMock()
        job.id = "job-1"
        job.session_id = "sess-1"
        job.status = "failed"
        job.celery_task_id = "celery-1"
        job.result_count = 0
        job.uspto_count = None
        job.epo_count = None
        job.serpapi_count = None
        job.dedup_removed = None
        job.cache_hit_uspto = False
        job.cache_hit_epo = False
        job.duration_seconds = None
        job.error_message = "All sources timed out"
        job.completed_at = None

        mock_db.side_effect = _fake_db_session()
        mock_jrepo.get_job = AsyncMock(return_value=job)

        result = await get_search_status("12345678-1234-1234-1234-123456789abc")
        assert result["status"] == "failed"
        assert result["error"] == "All sources timed out"
        assert "retry" in result["next_step"]
