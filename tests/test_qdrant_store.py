"""Tests for qdrant_store — mock AsyncQdrantClient."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from types import SimpleNamespace

import numpy as np
import pytest


def _mock_qdrant_client():
    """Create a mock AsyncQdrantClient."""
    client = AsyncMock()
    # get_collections returns an object with .collections list
    collections_result = MagicMock()
    collections_result.collections = []
    client.get_collections.return_value = collections_result
    return client


class TestEnsureCollectionExists:
    async def test_creates_collection_when_missing(self):
        import patent_gap_finder.embeddings.qdrant_store as mod
        old = mod._client_instance
        mock_client = _mock_qdrant_client()
        mod._client_instance = mock_client

        try:
            await mod.ensure_collection_exists()
            mock_client.create_collection.assert_called_once()
        finally:
            mod._client_instance = old

    async def test_idempotent_when_exists(self):
        import patent_gap_finder.embeddings.qdrant_store as mod
        old = mod._client_instance
        mock_client = _mock_qdrant_client()

        # Simulate collection already exists
        existing = MagicMock()
        existing.name = "patents"
        mock_client.get_collections.return_value.collections = [existing]
        mod._client_instance = mock_client

        try:
            await mod.ensure_collection_exists()
            mock_client.create_collection.assert_not_called()
        finally:
            mod._client_instance = old


class TestUpsertPatentEmbeddings:
    async def test_upserts_correct_count(self):
        import patent_gap_finder.embeddings.qdrant_store as mod
        old = mod._client_instance
        mock_client = _mock_qdrant_client()
        mod._client_instance = mock_client

        try:
            ids = ["id-1", "id-2", "id-3"]
            embeddings = np.random.rand(3, 384).astype(np.float32)
            payloads = [{"patent_id": f"US-{i}"} for i in range(3)]

            count = await mod.upsert_patent_embeddings(ids, embeddings, payloads)
            assert count == 3
            mock_client.upsert.assert_called_once()
        finally:
            mod._client_instance = old

    async def test_batches_at_500(self):
        import patent_gap_finder.embeddings.qdrant_store as mod
        old = mod._client_instance
        mock_client = _mock_qdrant_client()
        mod._client_instance = mock_client

        try:
            n = 600
            ids = [f"id-{i}" for i in range(n)]
            embeddings = np.random.rand(n, 384).astype(np.float32)
            payloads = [{"patent_id": f"US-{i}"} for i in range(n)]

            count = await mod.upsert_patent_embeddings(ids, embeddings, payloads)
            assert count == 600
            assert mock_client.upsert.call_count == 2  # 500 + 100
        finally:
            mod._client_instance = old


class TestSearchSimilar:
    async def test_passes_session_filter(self):
        import patent_gap_finder.embeddings.qdrant_store as mod
        old = mod._client_instance
        mock_client = _mock_qdrant_client()
        mock_client.search.return_value = []
        mod._client_instance = mock_client

        try:
            query = np.random.rand(384).astype(np.float32)
            await mod.search_similar(query, session_id="sess-123", k=5)
            mock_client.search.assert_called_once()

            call_kwargs = mock_client.search.call_args[1]
            assert call_kwargs["limit"] == 5
        finally:
            mod._client_instance = old

    async def test_connection_failure_returns_empty(self):
        import patent_gap_finder.embeddings.qdrant_store as mod
        old = mod._client_instance
        mock_client = _mock_qdrant_client()
        mock_client.search.side_effect = ConnectionError("down")
        mod._client_instance = mock_client

        try:
            query = np.random.rand(384).astype(np.float32)
            result = await mod.search_similar(query, session_id="s1")
            assert result == []
        finally:
            mod._client_instance = old


class TestGetAllSessionEmbeddings:
    async def test_paginates_correctly(self):
        import patent_gap_finder.embeddings.qdrant_store as mod
        old = mod._client_instance
        mock_client = _mock_qdrant_client()

        # Two pages of results
        page1_points = [
            MagicMock(id="id-1", vector=[0.1] * 384, payload={}),
            MagicMock(id="id-2", vector=[0.2] * 384, payload={}),
        ]
        page2_points = [
            MagicMock(id="id-3", vector=[0.3] * 384, payload={}),
        ]

        mock_client.scroll.side_effect = [
            (page1_points, "offset-2"),  # First page, has more
            (page2_points, None),         # Last page
        ]
        mod._client_instance = mock_client

        try:
            ids, embeddings = await mod.get_all_session_embeddings("sess-1")
            assert len(ids) == 3
            assert embeddings.shape == (3, 384)
            assert mock_client.scroll.call_count == 2
        finally:
            mod._client_instance = old

    async def test_empty_result(self):
        import patent_gap_finder.embeddings.qdrant_store as mod
        old = mod._client_instance
        mock_client = _mock_qdrant_client()
        mock_client.scroll.return_value = ([], None)
        mod._client_instance = mock_client

        try:
            ids, embeddings = await mod.get_all_session_embeddings("sess-1")
            assert len(ids) == 0
            assert embeddings.shape == (0, 384)
        finally:
            mod._client_instance = old
