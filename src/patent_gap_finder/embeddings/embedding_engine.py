"""Singleton sentence-transformers wrapper with async support.

model.encode() is CPU-bound — always runs via run_in_executor to
avoid blocking the FastMCP event loop.
"""

from __future__ import annotations

import asyncio
import logging
from functools import partial
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

MODEL_NAME = "all-MiniLM-L6-v2"
EMBEDDING_DIM = 384


class EmbeddingModelLoadError(Exception):
    """Failed to load the sentence-transformers model."""


class EmbeddingDimensionMismatchError(Exception):
    """Embedding dimension does not match expected value."""


_model_instance = None


def get_embedding_model():
    """Return the shared SentenceTransformer singleton.

    Loads the model on first call (~2s). Subsequent calls return
    the cached instance.

    Raises:
        EmbeddingModelLoadError: If the model fails to load.
    """
    global _model_instance
    if _model_instance is None:
        try:
            from sentence_transformers import SentenceTransformer
            _model_instance = SentenceTransformer(MODEL_NAME)
            logger.info("Loaded embedding model: %s", MODEL_NAME)
        except Exception as e:
            raise EmbeddingModelLoadError(
                f"Failed to load {MODEL_NAME}. Ensure sentence-transformers "
                f"is installed and the model is downloaded. "
                f"Pre-download with: python -c \"from sentence_transformers "
                f"import SentenceTransformer; SentenceTransformer('{MODEL_NAME}')\". "
                f"Error: {e}"
            ) from e
    return _model_instance


def reset_embedding_model() -> None:
    """Reset the singleton (for tests)."""
    global _model_instance
    _model_instance = None


def get_embedding_dim() -> int:
    """Return the expected embedding dimension."""
    return EMBEDDING_DIM


async def encode_texts(texts: list[str]) -> np.ndarray:
    """Encode a list of texts into embedding vectors.

    Uses asyncio.get_event_loop().run_in_executor to avoid blocking
    the event loop with CPU-bound computation.

    Args:
        texts: List of texts to encode.

    Returns:
        numpy array of shape (len(texts), EMBEDDING_DIM).
        If texts is empty, returns shape (0, EMBEDDING_DIM).
    """
    if not texts:
        return np.empty((0, EMBEDDING_DIM), dtype=np.float32)

    model = get_embedding_model()
    loop = asyncio.get_event_loop()
    encode_fn = partial(
        model.encode,
        texts,
        batch_size=64,
        show_progress_bar=False,
        normalize_embeddings=False,
    )
    embeddings = await loop.run_in_executor(None, encode_fn)

    if embeddings.shape[1] != EMBEDDING_DIM:
        raise EmbeddingDimensionMismatchError(
            f"Expected dim {EMBEDDING_DIM}, got {embeddings.shape[1]}"
        )

    return embeddings


async def encode_single(text: str) -> np.ndarray:
    """Encode a single text into an embedding vector.

    Args:
        text: Text to encode.

    Returns:
        numpy array of shape (EMBEDDING_DIM,).
    """
    embeddings = await encode_texts([text])
    return embeddings[0]
