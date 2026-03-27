"""Tests for search_prior_art MCP tool."""

from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _fake_db_session(mock_session=None):
    """Create a fake get_db_session context manager."""
    if mock_session is None:
        mock_session = AsyncMock()

    @asynccontextmanager
    async def fake_db():
        yield mock_session

    return fake_db


class TestSearchPriorArtTool:
    async def test_invalid_session_id(self):
        from patent_gap_finder.tools.search_prior_art import search_prior_art

        result = await search_prior_art("not-a-uuid")
        assert result["error"] == "INVALID_SESSION_ID"

    @patch("patent_gap_finder.tools.search_prior_art.get_db_session")
    @patch("patent_gap_finder.tools.search_prior_art.session_repo")
    async def test_session_not_found(self, mock_srepo, mock_db):
        from patent_gap_finder.tools.search_prior_art import search_prior_art

        mock_db.side_effect = _fake_db_session()
        mock_srepo.get_session = AsyncMock(return_value=None)

        result = await search_prior_art("12345678-1234-1234-1234-123456789abc")
        assert result["error"] == "SESSION_NOT_FOUND"

    @patch("patent_gap_finder.tools.search_prior_art.get_db_session")
    @patch("patent_gap_finder.tools.search_prior_art.job_repo")
    @patch("patent_gap_finder.tools.search_prior_art.session_repo")
    async def test_phase2_incomplete(self, mock_srepo, mock_jrepo, mock_db):
        from patent_gap_finder.tools.search_prior_art import search_prior_art

        session = MagicMock()
        session.top_ipc_codes = None
        session.search_keywords = None

        mock_db.side_effect = _fake_db_session()
        mock_srepo.get_session = AsyncMock(return_value=session)

        result = await search_prior_art("12345678-1234-1234-1234-123456789abc")
        assert result["error"] == "PHASE2_INCOMPLETE"

    @patch("patent_gap_finder.tools.search_prior_art.get_db_session")
    @patch("patent_gap_finder.tools.search_prior_art.job_repo")
    @patch("patent_gap_finder.tools.search_prior_art.session_repo")
    async def test_existing_complete_job(self, mock_srepo, mock_jrepo, mock_db):
        from patent_gap_finder.tools.search_prior_art import search_prior_art

        session = MagicMock()
        session.top_ipc_codes = ["G06N 3/08"]
        session.search_keywords = ["neural", "network"]

        existing_job = MagicMock()
        existing_job.status = "complete"
        existing_job.id = "job-123"
        existing_job.result_count = 50

        mock_db.side_effect = _fake_db_session()
        mock_srepo.get_session = AsyncMock(return_value=session)
        mock_jrepo.get_latest_job_for_session = AsyncMock(return_value=existing_job)

        result = await search_prior_art("12345678-1234-1234-1234-123456789abc")
        assert result["error"] == "JOB_ALREADY_EXISTS"

    @patch("patent_gap_finder.workers.search_tasks.run_patent_search")
    @patch("patent_gap_finder.tools.search_prior_art.get_db_session")
    @patch("patent_gap_finder.tools.search_prior_art.job_repo")
    @patch("patent_gap_finder.tools.search_prior_art.session_repo")
    async def test_happy_path(self, mock_srepo, mock_jrepo, mock_db, mock_task):
        from patent_gap_finder.tools.search_prior_art import search_prior_art

        session = MagicMock()
        session.top_ipc_codes = ["G06N 3/08"]
        session.search_keywords = ["neural", "network"]

        job = MagicMock()
        job.id = "job-456"

        mock_db.side_effect = _fake_db_session()
        mock_srepo.get_session = AsyncMock(return_value=session)
        mock_jrepo.get_latest_job_for_session = AsyncMock(return_value=None)
        mock_jrepo.create_job = AsyncMock(return_value=job)
        mock_jrepo.update_job_celery_id = AsyncMock()

        mock_celery_result = MagicMock()
        mock_celery_result.id = "celery-task-789"
        mock_task.delay.return_value = mock_celery_result

        result = await search_prior_art("12345678-1234-1234-1234-123456789abc")
        assert result["status"] == "pending"
        assert result["job_id"] == "job-456"
        mock_task.delay.assert_called_once()

    @patch("patent_gap_finder.workers.search_tasks.run_patent_search")
    @patch("patent_gap_finder.tools.search_prior_art.get_db_session")
    @patch("patent_gap_finder.tools.search_prior_art.job_repo")
    @patch("patent_gap_finder.tools.search_prior_art.session_repo")
    async def test_celery_unavailable(self, mock_srepo, mock_jrepo, mock_db, mock_task):
        from patent_gap_finder.tools.search_prior_art import search_prior_art

        session = MagicMock()
        session.top_ipc_codes = ["G06N"]
        session.search_keywords = ["neural"]

        job = MagicMock()
        job.id = "job-err"

        mock_db.side_effect = _fake_db_session()
        mock_srepo.get_session = AsyncMock(return_value=session)
        mock_jrepo.get_latest_job_for_session = AsyncMock(return_value=None)
        mock_jrepo.create_job = AsyncMock(return_value=job)
        mock_jrepo.update_job_status = AsyncMock()

        mock_task.delay.side_effect = ConnectionError("Redis down")
        result = await search_prior_art("12345678-1234-1234-1234-123456789abc")

        assert result["error"] == "CELERY_UNAVAILABLE"
