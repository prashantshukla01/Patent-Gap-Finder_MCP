"""Tests for the classify_ipc MCP tool.

Mocks both GeminiClient and DB repositories.
"""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from patent_gap_finder.db.connection import get_db_session, init_db, reset_db
from patent_gap_finder.db.repositories import claim_repo, session_repo
from patent_gap_finder.models.ipc import (
    ClaimIPCMapping,
    IPCClassificationResponse,
)
from patent_gap_finder.tools.classify_ipc import classify_ipc


# ── Fixtures ─────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
async def setup_test_db():
    """In-memory SQLite DB for each test."""
    reset_db()
    with patch.dict(os.environ, {"DATABASE_URL": "sqlite+aiosqlite:///:memory:"}):
        await init_db()
        yield
    reset_db()


async def _create_session_with_ai_claims() -> str:
    """Helper: create a session with AI claims in the DB."""
    async with get_db_session() as db:
        session = await session_repo.create_session(db, {
            "paper_title": "IPC Test Paper",
            "paper_authors": ["Test Author"],
        })
        session_id = session.id

        await session_repo.update_session_results(db, session_id, {
            "primary_domain": "machine learning",
        })

        await claim_repo.create_claims(db, session_id, [
            {
                "claim_text": "A method for training neural networks...",
                "claim_type": "method",
                "technical_domain": "machine learning",
                "novelty_basis": "Novel training approach",
                "source_section": "Methodology",
                "confidence": 0.85,
                "extraction_source": "ai",
            },
        ])
    return session_id


# ──────────────────────────────────────────────────────────────────────
# Tests
# ──────────────────────────────────────────────────────────────────────


class TestClassifyIPCTool:
    """Tests for the classify_ipc MCP tool."""

    @pytest.mark.asyncio
    async def test_invalid_session_id(self) -> None:
        """Should return INVALID_SESSION_ID for bad UUID."""
        result = await classify_ipc("not-a-uuid")
        assert result["error"] == "INVALID_SESSION_ID"

    @pytest.mark.asyncio
    async def test_session_not_found(self) -> None:
        """Should return SESSION_NOT_FOUND for unknown UUID."""
        result = await classify_ipc("00000000-0000-0000-0000-000000000000")
        assert result["error"] == "SESSION_NOT_FOUND"

    @pytest.mark.asyncio
    async def test_no_ai_claims(self) -> None:
        """Should return NO_AI_CLAIMS when no AI extraction was done."""
        # Create session with heuristic claims only
        async with get_db_session() as db:
            session = await session_repo.create_session(db, {
                "paper_title": "No AI Claims Paper",
            })
            session_id = session.id

            await claim_repo.create_claims(db, session_id, [
                {
                    "claim_text": "A heuristic claim...",
                    "claim_type": "method",
                    "source_section": "Intro",
                    "confidence": 0.5,
                    "extraction_source": "heuristic",
                },
            ])

        result = await classify_ipc(session_id)
        assert result["error"] == "NO_AI_CLAIMS"

    @pytest.mark.asyncio
    async def test_happy_path(self) -> None:
        """Full happy path: session found, AI claims exist, returns ai_instructions."""
        session_id = await _create_session_with_ai_claims()
        result = await classify_ipc(session_id)

        assert "error" not in result
        assert result["session_id"] == session_id
        assert len(result["claims_to_classify"]) == 1
        assert "ai_instructions" in result
        assert result["ai_instructions"]["task"] == "classify_ipc_codes"

    @pytest.mark.asyncio
    async def test_result_contains_session_id(self) -> None:
        """Result should always include the session_id."""
        session_id = await _create_session_with_ai_claims()
        result = await classify_ipc(session_id)

        assert result["session_id"] == session_id
