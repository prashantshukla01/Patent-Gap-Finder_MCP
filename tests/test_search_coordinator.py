"""Tests for search coordinator."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from patent_gap_finder.models.patent import Patent, PatentSource


@pytest.fixture
def mock_redis():
    """Mock Redis client."""
    with patch("patent_gap_finder.search.search_coordinator.get_redis_client") as m:
        client = AsyncMock()
        client.get_cached.return_value = None
        client.set_cached = AsyncMock()
        m.return_value = client
        yield client


@pytest.fixture
def mock_persist():
    """Mock _persist_results."""
    with patch(
        "patent_gap_finder.search.search_coordinator._persist_results",
        new_callable=AsyncMock,
    ) as m:
        yield m


def _make_patent(id: str, source: PatentSource = PatentSource.USPTO) -> dict:
    return {
        "patent_number": id,
        "patent_title": f"Patent {id}",
        "patent_abstract": "Abstract",
        "patent_date": "2023-01-01",
        "assignee_organization": "Corp",
        "inventor_first_name": ["John"],
        "inventor_last_name": ["Doe"],
        "ipc_code": ["G06N 3/08"],
        "cpc_code": [],
    }


class TestCoordinateSearch:
    @patch("patent_gap_finder.search.search_coordinator.serpapi_mod")
    @patch("patent_gap_finder.search.search_coordinator.epo_mod")
    @patch("patent_gap_finder.search.search_coordinator.uspto_mod")
    async def test_both_cached_no_api_calls(
        self, mock_uspto, mock_epo, mock_serpapi, mock_redis, mock_persist
    ):
        """When both sources are cached, no API calls should be made."""
        from patent_gap_finder.search.search_coordinator import coordinate_search

        # Set up cache hits
        mock_redis.get_cached.side_effect = [
            {"patents": [{"patent_id": "US-123", "title": "Cached", "source": "uspto"}]},
            {"patents": [{"patent_id": "EP-456", "title": "Cached EPO", "source": "epo"}]},
        ]
        mock_serpapi.is_available.return_value = False

        result = await coordinate_search(
            keywords=["neural"], ipc_codes=["G06N"],
            session_id="sess-1", job_id="job-1",
        )

        # No API calls should have been made
        mock_uspto.search.assert_not_called()
        mock_epo.get_epo_client.assert_not_called()

    @patch("patent_gap_finder.search.search_coordinator.serpapi_mod")
    @patch("patent_gap_finder.search.search_coordinator.epo_mod")
    @patch("patent_gap_finder.search.search_coordinator.uspto_mod")
    async def test_uspto_cached_epo_missed(
        self, mock_uspto, mock_epo, mock_serpapi, mock_redis, mock_persist
    ):
        """When USPTO cached but EPO missed, only EPO client called."""
        from patent_gap_finder.search.search_coordinator import coordinate_search

        patents_cached = [
            {"patent_id": f"US-{i}", "title": f"P{i}", "source": "uspto"}
            for i in range(20)
        ]
        mock_redis.get_cached.side_effect = [
            {"patents": patents_cached},  # USPTO cached
            None,  # EPO cache miss
        ]

        epo_client = AsyncMock()
        epo_client.search.return_value = [
            {"country": "EP", "doc_number": str(i), "kind": "A1"}
            for i in range(15)
        ]
        mock_epo.get_epo_client.return_value = epo_client
        mock_serpapi.is_available.return_value = False

        result = await coordinate_search(
            keywords=["neural"], ipc_codes=["G06N"],
            session_id="sess-1", job_id="job-1",
        )

        # Only EPO called, not USPTO
        mock_uspto.search.assert_not_called()
        epo_client.search.assert_called_once()

    @patch("patent_gap_finder.search.search_coordinator.serpapi_mod")
    @patch("patent_gap_finder.search.search_coordinator.epo_mod")
    @patch("patent_gap_finder.search.search_coordinator.uspto_mod")
    async def test_uspto_fails_epo_still_returns(
        self, mock_uspto, mock_epo, mock_serpapi, mock_redis, mock_persist
    ):
        """If USPTO fails, EPO results should still be returned."""
        from patent_gap_finder.search.search_coordinator import coordinate_search

        mock_redis.get_cached.return_value = None

        mock_uspto.search.side_effect = Exception("USPTO down")

        epo_client = AsyncMock()
        epo_client.search.return_value = [
            {"country": "EP", "doc_number": "111", "kind": "A1"}
        ]
        mock_epo.get_epo_client.return_value = epo_client
        mock_serpapi.is_available.return_value = False

        result = await coordinate_search(
            keywords=["neural"], ipc_codes=["G06N"],
            session_id="sess-1", job_id="job-1",
        )

        assert result.total_found >= 1

    @patch("patent_gap_finder.search.search_coordinator.serpapi_mod")
    @patch("patent_gap_finder.search.search_coordinator.epo_mod")
    @patch("patent_gap_finder.search.search_coordinator.uspto_mod")
    async def test_serpapi_called_when_under_30(
        self, mock_uspto, mock_epo, mock_serpapi, mock_redis, mock_persist
    ):
        """SerpAPI should be called when total < 30."""
        from patent_gap_finder.search.search_coordinator import coordinate_search

        mock_redis.get_cached.return_value = None

        # USPTO returns 10
        mock_uspto.search.return_value = [_make_patent(str(i)) for i in range(10)]

        # EPO returns 5
        epo_client = AsyncMock()
        epo_client.search.return_value = [
            {"country": "EP", "doc_number": str(100 + i), "kind": "A1"}
            for i in range(5)
        ]
        mock_epo.get_epo_client.return_value = epo_client

        # SerpAPI available
        mock_serpapi.is_available.return_value = True
        mock_serpapi.search = AsyncMock(return_value=[
            {"patent_id": "US999", "title": "Serp Patent", "snippet": "test"}
        ])

        result = await coordinate_search(
            keywords=["neural"], ipc_codes=["G06N"],
            session_id="sess-1", job_id="job-1",
        )

        mock_serpapi.search.assert_called_once()

    @patch("patent_gap_finder.search.search_coordinator.serpapi_mod")
    @patch("patent_gap_finder.search.search_coordinator.epo_mod")
    @patch("patent_gap_finder.search.search_coordinator.uspto_mod")
    async def test_serpapi_not_called_when_over_30(
        self, mock_uspto, mock_epo, mock_serpapi, mock_redis, mock_persist
    ):
        """SerpAPI should NOT be called when total >= 30."""
        from patent_gap_finder.search.search_coordinator import coordinate_search

        mock_redis.get_cached.return_value = None

        mock_uspto.search = AsyncMock(
            return_value=[_make_patent(str(i)) for i in range(25)]
        )
        epo_client = AsyncMock()
        epo_client.search.return_value = [
            {"country": "EP", "doc_number": str(100 + i), "kind": "A1"}
            for i in range(10)
        ]
        mock_epo.get_epo_client.return_value = epo_client
        mock_serpapi.is_available.return_value = True

        result = await coordinate_search(
            keywords=["neural"], ipc_codes=["G06N"],
            session_id="sess-1", job_id="job-1",
        )

        mock_serpapi.search.assert_not_called()
