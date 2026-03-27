"""Tests for USPTO PatentsView client."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from patent_gap_finder.search import uspto_client
from patent_gap_finder.search.uspto_client import (
    USPTOAPIError,
    USPTOTimeoutError,
    _build_query,
    search,
)


# ── Query builder ────────────────────────────────────────────────────


class TestBuildQuery:
    def test_keywords_only(self):
        q = _build_query(["neural", "network"], [])
        assert "_text_any" in q
        assert "neural network" in q["_text_any"]["patent_abstract"]

    def test_ipc_only(self):
        q = _build_query([], ["G06N 3/08"])
        assert "_eq" in q
        assert q["_eq"]["ipc_code"] == "G06N"

    def test_keywords_and_ipc(self):
        q = _build_query(["attention"], ["G06N 3/08", "H04L 9/30"])
        assert "_and" in q
        conditions = q["_and"]
        assert len(conditions) == 2

    def test_multiple_ipc_codes_use_or(self):
        q = _build_query([], ["G06N 3/08", "H04L 9/30"])
        assert "_or" in q

    def test_single_ipc_uses_eq(self):
        q = _build_query([], ["G06N 3/08"])
        assert "_eq" in q

    def test_empty_raises(self):
        with pytest.raises(ValueError):
            _build_query([], [])


# ── Search ───────────────────────────────────────────────────────────


def _mock_response(patents, total=None, status=200):
    """Create a mock httpx.Response."""
    if total is None:
        total = len(patents)
    response = MagicMock()
    response.status_code = status
    response.json.return_value = {
        "patents": patents,
        "total_patent_count": total,
    }
    response.text = "mock"
    return response


class TestSearch:
    @pytest.fixture(autouse=True)
    def reset_semaphore(self):
        """Reset the module-level semaphore for each test."""
        uspto_client._semaphore = asyncio.Semaphore(1)

    @patch("patent_gap_finder.search.uspto_client._make_request")
    async def test_returns_patents(self, mock_req):
        patents_data = [
            {"patent_id": "1", "patent_title": "Test Patent"},
            {"patent_id": "2", "patent_title": "Test Patent 2"},
        ]
        mock_req.return_value = _mock_response(patents_data, total=2)

        result = await search(["neural"], ["G06N 3/08"], max_results=10)
        assert len(result) == 2
        assert result[0]["patent_title"] == "Test Patent"

    @patch("patent_gap_finder.search.uspto_client._make_request")
    async def test_pagination(self, mock_req):
        page1 = [{"patent_id": str(i)} for i in range(50)]
        page2 = [{"patent_id": str(i)} for i in range(50, 80)]

        mock_req.side_effect = [
            _mock_response(page1, total=80),
            _mock_response(page2, total=80),
        ]

        result = await search(["neural"], ["G06N"], max_results=100)
        assert len(result) == 80
        assert mock_req.call_count == 2

    @patch("patent_gap_finder.search.uspto_client._make_request")
    async def test_respects_max_results(self, mock_req):
        page1 = [{"patent_id": str(i)} for i in range(50)]
        mock_req.return_value = _mock_response(page1, total=200)

        result = await search(["neural"], ["G06N"], max_results=30)
        assert len(result) == 30

    @patch("patent_gap_finder.search.uspto_client._make_request")
    async def test_empty_result(self, mock_req):
        mock_req.return_value = _mock_response([], total=0)

        result = await search(["obscure query"], ["Z99"], max_results=10)
        assert result == []


class TestMakeRequest:
    @patch("httpx.AsyncClient.post")
    async def test_429_retry(self, mock_post):
        """429 → wait → retry → success."""
        ok_resp = MagicMock()
        ok_resp.status_code = 200
        ok_resp.json.return_value = {"patents": [], "total_patent_count": 0}

        rate_resp = MagicMock()
        rate_resp.status_code = 429

        mock_post.side_effect = [rate_resp, ok_resp]

        async with httpx.AsyncClient() as client:
            with patch("asyncio.sleep", new_callable=AsyncMock):
                result = await uspto_client._make_request(client, {}, {}, retries=1)
                assert result.status_code == 200

    @patch("httpx.AsyncClient.post")
    async def test_timeout_raises(self, mock_post):
        mock_post.side_effect = httpx.TimeoutException("timeout")

        async with httpx.AsyncClient() as client:
            with patch("asyncio.sleep", new_callable=AsyncMock):
                with pytest.raises(USPTOTimeoutError):
                    await uspto_client._make_request(client, {}, {}, retries=1)
