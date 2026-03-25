"""Tests for the session repository using in-memory SQLite.

No real PostgreSQL needed — uses aiosqlite.
"""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from patent_gap_finder.db.connection import get_db_session, init_db, reset_db
from patent_gap_finder.db.models import AnalysisSession


# ── Fixtures ─────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
async def setup_test_db():
    """Set up an in-memory SQLite database for each test."""
    reset_db()
    with patch.dict(os.environ, {"DATABASE_URL": "sqlite+aiosqlite:///:memory:"}):
        await init_db()
        yield
    reset_db()


# ──────────────────────────────────────────────────────────────────────
# Tests
# ──────────────────────────────────────────────────────────────────────


class TestCreateSession:
    """Tests for session creation."""

    @pytest.mark.asyncio
    async def test_creates_session_with_uuid(self) -> None:
        """Created session should have an auto-generated UUID."""
        from patent_gap_finder.db.repositories import session_repo

        async with get_db_session() as db:
            session = await session_repo.create_session(db, {
                "paper_title": "Test Paper",
                "paper_authors": ["Author One"],
                "source_url": "https://arxiv.org/abs/1234.56789",
                "file_hash": "abc123def456",
            })

        assert session.id is not None
        assert len(session.id) == 36  # UUID format
        assert session.paper_title == "Test Paper"
        assert session.status == "parsing"

    @pytest.mark.asyncio
    async def test_default_status_is_parsing(self) -> None:
        """New sessions should default to 'parsing' status."""
        from patent_gap_finder.db.repositories import session_repo

        async with get_db_session() as db:
            session = await session_repo.create_session(db, {
                "paper_title": "Status Test",
            })

        assert session.status == "parsing"
        assert session.total_requests_used == 0


class TestGetSession:
    """Tests for session retrieval."""

    @pytest.mark.asyncio
    async def test_returns_none_for_unknown_id(self) -> None:
        """Should return None for a non-existent session ID."""
        from patent_gap_finder.db.repositories import session_repo

        async with get_db_session() as db:
            result = await session_repo.get_session(
                db, "00000000-0000-0000-0000-000000000000"
            )

        assert result is None

    @pytest.mark.asyncio
    async def test_retrieves_created_session(self) -> None:
        """Should retrieve a previously created session."""
        from patent_gap_finder.db.repositories import session_repo

        async with get_db_session() as db:
            created = await session_repo.create_session(db, {
                "paper_title": "Retrieve Test",
            })
            session_id = created.id

        async with get_db_session() as db:
            retrieved = await session_repo.get_session(db, session_id)

        assert retrieved is not None
        assert retrieved.paper_title == "Retrieve Test"


class TestGetSessionByFileHash:
    """Tests for deduplication by file hash."""

    @pytest.mark.asyncio
    async def test_finds_existing_session(self) -> None:
        """Should find a session by its file hash."""
        from patent_gap_finder.db.repositories import session_repo

        async with get_db_session() as db:
            await session_repo.create_session(db, {
                "paper_title": "Hash Test",
                "file_hash": "deadbeef" * 8,
            })

        async with get_db_session() as db:
            found = await session_repo.get_session_by_file_hash(
                db, "deadbeef" * 8
            )

        assert found is not None
        assert found.paper_title == "Hash Test"

    @pytest.mark.asyncio
    async def test_returns_none_for_unknown_hash(self) -> None:
        """Should return None for an unknown file hash."""
        from patent_gap_finder.db.repositories import session_repo

        async with get_db_session() as db:
            result = await session_repo.get_session_by_file_hash(
                db, "nonexistent_hash"
            )

        assert result is None


class TestUpdateSessionStatus:
    """Tests for status updates."""

    @pytest.mark.asyncio
    async def test_changes_status(self) -> None:
        """Should update the session status field."""
        from patent_gap_finder.db.repositories import session_repo

        async with get_db_session() as db:
            session = await session_repo.create_session(db, {
                "paper_title": "Status Update",
            })
            session_id = session.id

        async with get_db_session() as db:
            await session_repo.update_session_status(
                db, session_id, "extracting"
            )

        async with get_db_session() as db:
            updated = await session_repo.get_session(db, session_id)

        assert updated is not None
        assert updated.status == "extracting"


class TestIncrementRequestCounter:
    """Tests for Gemini request counter."""

    @pytest.mark.asyncio
    async def test_increments_correctly(self) -> None:
        """Counter should accumulate across multiple increments."""
        from patent_gap_finder.db.repositories import session_repo

        async with get_db_session() as db:
            session = await session_repo.create_session(db, {
                "paper_title": "Counter Test",
            })
            session_id = session.id

        async with get_db_session() as db:
            await session_repo.increment_request_counter(db, session_id, 2)

        async with get_db_session() as db:
            await session_repo.increment_request_counter(db, session_id, 3)

        async with get_db_session() as db:
            session = await session_repo.get_session(db, session_id)

        assert session is not None
        assert session.total_requests_used == 5
