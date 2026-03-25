"""Tests for the Gemini client wrapper.

All Gemini SDK calls are mocked — no real API key needed.
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import BaseModel

from patent_gap_finder.ai.gemini_client import (
    GeminiClient,
    GeminiDailyQuotaError,
    GeminiRateLimitError,
    GeminiResponseValidationError,
    reset_gemini_client,
)


# ── Test schema ──────────────────────────────────────────────────────

class _TestSchema(BaseModel):
    name: str
    value: int


# ── Fixtures ─────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def reset_singleton():
    """Reset the Gemini client singleton between tests."""
    reset_gemini_client()
    yield
    reset_gemini_client()


def _make_client() -> GeminiClient:
    """Create a client with mocked genai.configure and model."""
    with patch("patent_gap_finder.ai.gemini_client.genai") as mock_genai:
        mock_genai.GenerativeModel.return_value = MagicMock()
        mock_genai.GenerationConfig = MagicMock()
        client = GeminiClient(api_key="test-key")
    return client


def _mock_response(text: str) -> MagicMock:
    """Create a mock Gemini response object."""
    resp = MagicMock()
    resp.text = text
    return resp


# ──────────────────────────────────────────────────────────────────────
# Tests
# ──────────────────────────────────────────────────────────────────────


class TestComplete:
    """Tests for GeminiClient.complete()."""

    @pytest.mark.asyncio
    async def test_returns_response_text(self) -> None:
        """Normal call should return the response text."""
        client = _make_client()
        client._model.generate_content = MagicMock(
            return_value=_mock_response("Hello world")
        )

        with patch("patent_gap_finder.ai.gemini_client.asyncio.sleep", new_callable=AsyncMock):
            result = await client.complete("system", "user")

        assert result == "Hello world"
        assert client.total_requests == 1

    @pytest.mark.asyncio
    async def test_rate_limiting_sleep(self) -> None:
        """A 4-second sleep should be called after each request."""
        client = _make_client()
        client._model.generate_content = MagicMock(
            return_value=_mock_response("ok")
        )

        with patch("patent_gap_finder.ai.gemini_client.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            await client.complete("sys", "usr")
            mock_sleep.assert_awaited_once_with(4.0)

    @pytest.mark.asyncio
    async def test_retry_on_429(self) -> None:
        """Should retry on ResourceExhausted and succeed on third attempt."""
        from google.api_core.exceptions import ResourceExhausted

        client = _make_client()
        client._model.generate_content = MagicMock(
            side_effect=[
                ResourceExhausted("rate limit"),
                ResourceExhausted("rate limit"),
                _mock_response("success"),
            ]
        )

        with patch("patent_gap_finder.ai.gemini_client.asyncio.sleep", new_callable=AsyncMock):
            result = await client.complete("sys", "usr")

        assert result == "success"
        assert client.total_requests == 1

    @pytest.mark.asyncio
    async def test_daily_quota_exhausted(self) -> None:
        """Should raise GeminiDailyQuotaError when quota message detected."""
        from google.api_core.exceptions import ResourceExhausted

        client = _make_client()
        client._model.generate_content = MagicMock(
            side_effect=ResourceExhausted("daily quota exceeded")
        )

        with patch("patent_gap_finder.ai.gemini_client.asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(GeminiDailyQuotaError):
                await client.complete("sys", "usr")

    @pytest.mark.asyncio
    async def test_rate_limit_exhausted_after_retries(self) -> None:
        """Should raise GeminiRateLimitError after max retries."""
        from google.api_core.exceptions import ResourceExhausted

        client = _make_client()
        client._model.generate_content = MagicMock(
            side_effect=ResourceExhausted("rate limit")
        )

        with patch("patent_gap_finder.ai.gemini_client.asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises((GeminiRateLimitError, GeminiDailyQuotaError)):
                await client.complete("sys", "usr")

    @pytest.mark.asyncio
    async def test_usage_counters(self) -> None:
        """Counters should track prompt and response sizes."""
        client = _make_client()
        client._model.generate_content = MagicMock(
            return_value=_mock_response("response text")
        )

        with patch("patent_gap_finder.ai.gemini_client.asyncio.sleep", new_callable=AsyncMock):
            await client.complete("system prompt", "user prompt")

        assert client.total_requests == 1
        assert client.total_prompt_chars > 0
        assert client.total_response_chars > 0


class TestCompleteJson:
    """Tests for GeminiClient.complete_json()."""

    @pytest.mark.asyncio
    async def test_returns_validated_pydantic_object(self) -> None:
        """Should return a validated Pydantic instance."""
        client = _make_client()
        client._model.generate_content = MagicMock(
            return_value=_mock_response(json.dumps({"name": "test", "value": 42}))
        )

        with patch("patent_gap_finder.ai.gemini_client.asyncio.sleep", new_callable=AsyncMock):
            result = await client.complete_json("sys", "usr", _TestSchema)

        assert isinstance(result, _TestSchema)
        assert result.name == "test"
        assert result.value == 42

    @pytest.mark.asyncio
    async def test_strips_markdown_fences(self) -> None:
        """Should handle responses wrapped in ```json ... ```."""
        client = _make_client()
        wrapped = '```json\n{"name": "fenced", "value": 99}\n```'
        client._model.generate_content = MagicMock(
            return_value=_mock_response(wrapped)
        )

        with patch("patent_gap_finder.ai.gemini_client.asyncio.sleep", new_callable=AsyncMock):
            result = await client.complete_json("sys", "usr", _TestSchema)

        assert result.name == "fenced"
        assert result.value == 99

    @pytest.mark.asyncio
    async def test_retry_on_validation_failure(self) -> None:
        """Should retry once with corrective prompt on validation error."""
        client = _make_client()
        bad_response = _mock_response(json.dumps({"wrong_key": "bad"}))
        good_response = _mock_response(json.dumps({"name": "fixed", "value": 1}))
        client._model.generate_content = MagicMock(
            side_effect=[bad_response, good_response]
        )

        with patch("patent_gap_finder.ai.gemini_client.asyncio.sleep", new_callable=AsyncMock):
            result = await client.complete_json("sys", "usr", _TestSchema)

        assert result.name == "fixed"

    @pytest.mark.asyncio
    async def test_validation_error_after_retry(self) -> None:
        """Should raise GeminiResponseValidationError if both attempts fail."""
        client = _make_client()
        client._model.generate_content = MagicMock(
            return_value=_mock_response(json.dumps({"wrong": "data"}))
        )

        with patch("patent_gap_finder.ai.gemini_client.asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(GeminiResponseValidationError):
                await client.complete_json("sys", "usr", _TestSchema)


class TestApiKeyMissing:
    """Test that missing API key raises ValueError."""

    def test_no_api_key(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            with patch("patent_gap_finder.ai.gemini_client.genai"):
                with pytest.raises(ValueError, match="GEMINI_API_KEY"):
                    GeminiClient()
