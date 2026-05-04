"""Tests for Lens.org patent search client (USPTO replacement).

The original USPTO PatentsView API was shut down March 2026.
This client now targets https://api.lens.org/patent/search
"""

from __future__ import annotations

import asyncio
import os
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from patent_gap_finder.search import uspto_client
from patent_gap_finder.search.uspto_client import (
    USPTOAPIError,
    USPTOTimeoutError,
    _build_query,
    _map_to_patentsview_shape,
    search,
)


# ── Query builder ────────────────────────────────────────────────────


class TestBuildQuery:
    def test_keywords_only(self):
        q = _build_query(["neural", "network"], [])
        assert "query_string" in q
        assert "neural network" in q["query_string"]["query"]

    def test_ipc_only(self):
        q = _build_query([], ["G06N 3/08"])
        assert "term" in q
        assert q["term"]["classifications_ipcr.symbol"] == "G06N"

    def test_keywords_and_ipc(self):
        q = _build_query(["attention"], ["G06N 3/08", "H04L 9/30"])
        assert "bool" in q
        assert "must" in q["bool"]
        assert len(q["bool"]["must"]) == 2

    def test_multiple_ipc_codes_use_should(self):
        q = _build_query([], ["G06N 3/08", "H04L 9/30"])
        assert "bool" in q
        assert "should" in q["bool"]

    def test_single_ipc_uses_term(self):
        q = _build_query([], ["G06N 3/08"])
        assert "term" in q

    def test_empty_raises(self):
        with pytest.raises(ValueError):
            _build_query([], [])

    def test_ipc_prefix_extracted(self):
        q = _build_query([], ["G06N 3/08"])
        # "G06N 3/08" → prefix "G06N"
        assert q["term"]["classifications_ipcr.symbol"] == "G06N"


# ── Shape mapper ─────────────────────────────────────────────────────


class TestMapToPatentsviewShape:
    def _make_hit(self, **kwargs):
        base = {
            "lens_id": "001-234-567",
            "title": "Test Patent Title",
            "abstract": "A test abstract.",
            "date_published": "2023-06-15",
            "inventors": [{"name": "Jane Doe"}],
            "assignees": [{"name": "Acme Corp"}],
            "classifications_ipcr": [{"symbol": "G06N"}],
            "classifications_cpc": [{"symbol": "G06N3/04"}],
            "publication_references": [],
        }
        base.update(kwargs)
        return base

    def test_basic_fields_mapped(self):
        hit = self._make_hit()
        out = _map_to_patentsview_shape(hit)
        assert out["patent_title"] == "Test Patent Title"
        assert out["patent_abstract"] == "A test abstract."
        assert out["patent_date"] == "2023-06-15"
        assert out["assignee_organization"] == "Acme Corp"

    def test_ipc_codes_extracted(self):
        hit = self._make_hit()
        out = _map_to_patentsview_shape(hit)
        assert "G06N" in out["ipc_code"]

    def test_cpc_codes_extracted(self):
        hit = self._make_hit()
        out = _map_to_patentsview_shape(hit)
        assert "G06N3/04" in out["cpc_code"]

    def test_inventor_name_split(self):
        hit = self._make_hit(inventors=[{"name": "John Smith"}])
        out = _map_to_patentsview_shape(hit)
        assert "John" in out["inventor_first_name"]
        assert "Smith" in out["inventor_last_name"]

    def test_us_patent_number_preferred(self):
        hit = self._make_hit(publication_references=[
            {"jurisdiction": "US", "doc_number": "10123456"},
            {"jurisdiction": "EP", "doc_number": "3456789"},
        ])
        out = _map_to_patentsview_shape(hit)
        assert out["patent_number"] == "10123456"

    def test_fallback_to_lens_id_when_no_us(self):
        hit = self._make_hit(publication_references=[
            {"jurisdiction": "EP", "doc_number": "3456789"},
        ])
        out = _map_to_patentsview_shape(hit)
        assert out["patent_number"] == "001-234-567"

    def test_empty_assignee(self):
        hit = self._make_hit(assignees=[])
        out = _map_to_patentsview_shape(hit)
        assert out["assignee_organization"] == ""

    def test_date_truncated_to_10_chars(self):
        hit = self._make_hit(date_published="2023-06-15T00:00:00Z")
        out = _map_to_patentsview_shape(hit)
        assert out["patent_date"] == "2023-06-15"


# ── Search (no LENS_API_KEY → graceful skip) ─────────────────────────


class TestSearchNoKey:
    async def test_returns_empty_when_no_key(self):
        with patch.dict(os.environ, {}, clear=True):
            # Ensure neither key is set
            os.environ.pop("LENS_API_KEY", None)
            os.environ.pop("USPTO_API_KEY", None)
            result = await search(["neural"], ["G06N"], max_results=5)
            assert result == []


# ── Search (with key → Lens.org API) ─────────────────────────────────


def _mock_lens_response(hits, total=None, status=200):
    """Create a mock httpx.Response for Lens.org format."""
    if total is None:
        total = len(hits)
    response = MagicMock()
    response.status_code = status
    response.json.return_value = {
        "data": hits,
        "total": {"value": total},
    }
    response.text = "mock"
    return response


def _sample_hit(patent_id="001"):
    return {
        "lens_id": patent_id,
        "title": f"Patent {patent_id}",
        "abstract": "Abstract text.",
        "date_published": "2023-01-01",
        "inventors": [{"name": "Alice Bob"}],
        "assignees": [{"name": "Corp"}],
        "classifications_ipcr": [{"symbol": "G06N"}],
        "classifications_cpc": [],
        "publication_references": [],
    }


class TestSearchWithKey:
    @pytest.fixture(autouse=True)
    def set_key(self, monkeypatch):
        monkeypatch.setenv("LENS_API_KEY", "test-key-abc")
        uspto_client._semaphore = asyncio.Semaphore(2)

    @patch("patent_gap_finder.search.uspto_client._make_request")
    async def test_returns_mapped_patents(self, mock_req):
        mock_req.return_value = _mock_lens_response([_sample_hit("1"), _sample_hit("2")], total=2)

        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await search(["neural"], ["G06N"], max_results=10)

        assert len(result) == 2
        assert result[0]["patent_title"] == "Patent 1"

    @patch("patent_gap_finder.search.uspto_client._make_request")
    async def test_respects_max_results(self, mock_req):
        hits = [_sample_hit(str(i)) for i in range(50)]
        mock_req.return_value = _mock_lens_response(hits, total=200)

        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await search(["neural"], ["G06N"], max_results=30)

        assert len(result) == 30

    @patch("patent_gap_finder.search.uspto_client._make_request")
    async def test_empty_result(self, mock_req):
        mock_req.return_value = _mock_lens_response([], total=0)

        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await search(["obscure"], ["Z99"], max_results=10)

        assert result == []


# ── _make_request retry logic ─────────────────────────────────────────


class TestMakeRequest:
    @patch("httpx.AsyncClient.post")
    async def test_429_retry(self, mock_post):
        ok_resp = MagicMock()
        ok_resp.status_code = 200
        ok_resp.json.return_value = {"data": [], "total": {"value": 0}}

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

    @patch("httpx.AsyncClient.post")
    async def test_401_raises_api_error(self, mock_post):
        resp = MagicMock()
        resp.status_code = 401
        resp.text = "Unauthorized"
        mock_post.return_value = resp

        async with httpx.AsyncClient() as client:
            with pytest.raises(USPTOAPIError, match="authentication"):
                await uspto_client._make_request(client, {}, {}, retries=0)

    @patch("httpx.AsyncClient.post")
    async def test_500_retries_then_raises(self, mock_post):
        resp = MagicMock()
        resp.status_code = 500
        resp.text = "Server Error"
        mock_post.return_value = resp

        async with httpx.AsyncClient() as client:
            with patch("asyncio.sleep", new_callable=AsyncMock):
                with pytest.raises(USPTOAPIError):
                    await uspto_client._make_request(client, {}, {}, retries=1)
