"""Tests for EPO OPS client."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from patent_gap_finder.search.epo_client import (
    EPOAuthError,
    EPOClient,
    EPOQuotaError,
)


def _make_epo_client(key="test_key", secret="test_secret"):
    """Create an EPOClient with test credentials."""
    with patch.dict("os.environ", {
        "EPO_CONSUMER_KEY": key,
        "EPO_CONSUMER_SECRET": secret,
    }):
        return EPOClient()


class TestAvailability:
    def test_available_with_credentials(self):
        client = _make_epo_client()
        assert client.is_available()

    def test_unavailable_without_credentials(self):
        client = _make_epo_client(key="", secret="")
        assert not client.is_available()


class TestTokenManagement:
    @patch("httpx.AsyncClient.post")
    async def test_token_fetched_on_first_call(self, mock_post):
        token_response = MagicMock()
        token_response.status_code = 200
        token_response.json.return_value = {
            "access_token": "test_token_123",
            "expires_in": 1200,
        }
        token_response.raise_for_status = MagicMock()
        mock_post.return_value = token_response

        client = _make_epo_client()
        async with httpx.AsyncClient() as http_client:
            token = await client._ensure_token(http_client)
            assert token == "test_token_123"
            assert mock_post.call_count == 1

    @patch("httpx.AsyncClient.post")
    async def test_token_reused_on_second_call(self, mock_post):
        token_response = MagicMock()
        token_response.status_code = 200
        token_response.json.return_value = {
            "access_token": "test_token_123",
            "expires_in": 1200,
        }
        token_response.raise_for_status = MagicMock()
        mock_post.return_value = token_response

        client = _make_epo_client()
        async with httpx.AsyncClient() as http_client:
            await client._ensure_token(http_client)
            await client._ensure_token(http_client)
            # Only fetched once
            assert mock_post.call_count == 1


class TestCQLBuilder:
    def test_keywords_only(self):
        client = _make_epo_client()
        cql = client._build_cql(["neural", "network", "attention"], [])
        assert "txt=" in cql
        assert "neural AND network AND attention" in cql

    def test_ipc_only(self):
        client = _make_epo_client()
        cql = client._build_cql([], ["G06N 3/08"])
        assert "ic=G06N" in cql

    def test_combined(self):
        client = _make_epo_client()
        cql = client._build_cql(["neural"], ["G06N 3/08"])
        assert "txt=" in cql
        assert "ic=G06N" in cql
        assert " AND " in cql

    def test_limits_to_5_keywords(self):
        client = _make_epo_client()
        many_kw = [f"term{i}" for i in range(10)]
        cql = client._build_cql(many_kw, [])
        # Only 5 terms should be in the query
        assert cql.count(" AND ") == 4  # 5 terms = 4 ANDs

    def test_empty_raises(self):
        client = _make_epo_client()
        with pytest.raises(ValueError):
            client._build_cql([], [])


class TestSearch:
    async def test_missing_credentials_returns_empty(self):
        client = _make_epo_client(key="", secret="")
        result = await client.search(["neural"], ["G06N"])
        assert result == []

    @patch("httpx.AsyncClient.post")
    @patch("httpx.AsyncClient.get")
    async def test_quota_error(self, mock_get, mock_post):
        # Token response
        token_response = MagicMock()
        token_response.status_code = 200
        token_response.json.return_value = {
            "access_token": "token",
            "expires_in": 1200,
        }
        token_response.raise_for_status = MagicMock()
        mock_post.return_value = token_response

        # Search returns 403
        quota_resp = MagicMock()
        quota_resp.status_code = 403
        mock_get.return_value = quota_resp

        client = _make_epo_client()
        with pytest.raises(EPOQuotaError):
            with patch("asyncio.sleep", new_callable=AsyncMock):
                await client.search(["neural"], ["G06N"], max_results=10)
