"""Tests for embedding engine — singleton, async encode, dimensions."""

from __future__ import annotations

from unittest.mock import MagicMock, patch, AsyncMock
import asyncio

import numpy as np
import pytest


class TestGetEmbeddingModel:
    @patch("patent_gap_finder.embeddings.embedding_engine.SentenceTransformer",
           create=True)
    def test_singleton_returns_same_instance(self, mock_st_class):
        from patent_gap_finder.embeddings.embedding_engine import (
            get_embedding_model, reset_embedding_model,
        )

        reset_embedding_model()
        mock_model = MagicMock()
        mock_st_class.return_value = mock_model

        import patent_gap_finder.embeddings.embedding_engine as mod
        mod._model_instance = None

        m1 = mod.get_embedding_model()
        m2 = mod.get_embedding_model()
        assert m1 is m2

        reset_embedding_model()

    def test_get_embedding_dim(self):
        from patent_gap_finder.embeddings.embedding_engine import get_embedding_dim
        assert get_embedding_dim() == 384


class TestEncodeTexts:
    async def test_returns_correct_shape(self):
        from patent_gap_finder.embeddings.embedding_engine import (
            encode_texts, reset_embedding_model, EMBEDDING_DIM,
        )

        mock_model = MagicMock()
        fake_embeddings = np.random.rand(3, EMBEDDING_DIM).astype(np.float32)
        mock_model.encode.return_value = fake_embeddings

        import patent_gap_finder.embeddings.embedding_engine as mod
        old = mod._model_instance
        mod._model_instance = mock_model

        try:
            result = await encode_texts(["a", "b", "c"])
            assert result.shape == (3, EMBEDDING_DIM)
            mock_model.encode.assert_called_once()
        finally:
            mod._model_instance = old

    async def test_empty_list_returns_empty_array(self):
        from patent_gap_finder.embeddings.embedding_engine import (
            encode_texts, EMBEDDING_DIM,
        )

        result = await encode_texts([])
        assert result.shape == (0, EMBEDDING_DIM)

    async def test_encode_calls_model_encode(self):
        """Verify model.encode is called (runs via executor internally)."""
        from patent_gap_finder.embeddings.embedding_engine import (
            encode_texts, EMBEDDING_DIM,
        )

        mock_model = MagicMock()
        fake_embeddings = np.random.rand(2, EMBEDDING_DIM).astype(np.float32)
        mock_model.encode.return_value = fake_embeddings

        import patent_gap_finder.embeddings.embedding_engine as mod
        old = mod._model_instance
        mod._model_instance = mock_model

        try:
            result = await encode_texts(["hello", "world"])
            assert result.shape == (2, EMBEDDING_DIM)
            # model.encode was called — proving run_in_executor delegated to it
            mock_model.encode.assert_called_once()
            call_args = mock_model.encode.call_args
            assert call_args[0][0] == ["hello", "world"]
        finally:
            mod._model_instance = old


class TestEncodeSingle:
    async def test_returns_1d(self):
        from patent_gap_finder.embeddings.embedding_engine import (
            encode_single, EMBEDDING_DIM,
        )

        mock_model = MagicMock()
        fake = np.random.rand(1, EMBEDDING_DIM).astype(np.float32)
        mock_model.encode.return_value = fake

        import patent_gap_finder.embeddings.embedding_engine as mod
        old = mod._model_instance
        mod._model_instance = mock_model

        try:
            result = await encode_single("test text")
            assert result.shape == (EMBEDDING_DIM,)
        finally:
            mod._model_instance = old
