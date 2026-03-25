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
        """Full happy path: session found, AI claims exist, classification runs."""
        session_id = await _create_session_with_ai_claims()

        mock_response = IPCClassificationResponse(
            mappings=[
                ClaimIPCMapping(
                    claim_text="A method for training neural networks...",
                    primary_ipc="G06N 3/08",
                    secondary_ipc=["G06N 3/04"],
                    cpc_code="G06N 3/08",
                    confidence=0.9,
                    rationale="Neural network training",
                    is_valid_ipc=True,
                ),
            ],
            top_ipc_codes=["G06N 3/08"],
            search_keywords=["neural network"] * 10,
            classification_summary="ML classification.",
        )

        with patch(
            "patent_gap_finder.tools.classify_ipc.get_gemini_client"
        ) as mock_get_client, patch(
            "patent_gap_finder.tools.classify_ipc._classify",
            new_callable=AsyncMock,
            return_value=mock_response,
        ):
            mock_client = MagicMock()
            mock_get_client.return_value = mock_client

            result = await classify_ipc(session_id)

        assert "error" not in result
        assert result["session_id"] == session_id
        assert len(result["mappings"]) == 1
        assert result["top_ipc_codes"] == ["G06N 3/08"]

    @pytest.mark.asyncio
    async def test_gemini_quota_exhausted(self) -> None:
        """Should return GEMINI_QUOTA_EXHAUSTED on quota error."""
        from patent_gap_finder.ai.gemini_client import GeminiDailyQuotaError

        session_id = await _create_session_with_ai_claims()

        with patch(
            "patent_gap_finder.tools.classify_ipc.get_gemini_client"
        ) as mock_get_client, patch(
            "patent_gap_finder.tools.classify_ipc._classify",
            new_callable=AsyncMock,
            side_effect=GeminiDailyQuotaError("quota exhausted"),
        ):
            mock_get_client.return_value = MagicMock()
            result = await classify_ipc(session_id)

        assert result["error"] == "GEMINI_QUOTA_EXHAUSTED"
        assert result["session_id"] == session_id

    @pytest.mark.asyncio
    async def test_result_contains_session_id(self) -> None:
        """Result should always include the session_id."""
        session_id = await _create_session_with_ai_claims()

        mock_response = IPCClassificationResponse(
            mappings=[],
            top_ipc_codes=[],
            search_keywords=["test"] * 10,
            classification_summary="Empty test.",
        )

        with patch(
            "patent_gap_finder.tools.classify_ipc.get_gemini_client"
        ), patch(
            "patent_gap_finder.tools.classify_ipc._classify",
            new_callable=AsyncMock,
            return_value=mock_response,
        ):
            result = await classify_ipc(session_id)

        assert result["session_id"] == session_id
