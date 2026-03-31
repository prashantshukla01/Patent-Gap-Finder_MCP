"""Async Qdrant client wrapper for patent vector storage.

Handles collection creation, batch upsert, similarity search,
and scroll-based pagination for HDBSCAN input retrieval.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

COLLECTION_NAME = "patents"
QDRANT_URL_DEFAULT = "http://localhost:6333"

_client_instance = None


class QdrantUnavailableError(Exception):
    """Cannot connect to Qdrant."""


def get_qdrant_client():
    """Return the shared AsyncQdrantClient singleton."""
    global _client_instance
    if _client_instance is None:
        try:
            from qdrant_client import AsyncQdrantClient
            url = os.environ.get("QDRANT_URL", QDRANT_URL_DEFAULT)
            _client_instance = AsyncQdrantClient(url=url)
            logger.info("Qdrant client created: %s", url)
        except Exception as e:
            raise QdrantUnavailableError(
                f"Cannot connect to Qdrant at "
                f"{os.environ.get('QDRANT_URL', QDRANT_URL_DEFAULT)}: {e}"
            ) from e
    return _client_instance


def reset_qdrant_client() -> None:
    """Reset the singleton (for tests)."""
    global _client_instance
    _client_instance = None


async def ensure_collection_exists() -> None:
    """Create the patents collection if it doesn't exist.

    Idempotent — safe to call on every startup.
    Uses cosine distance with on_disk_payload for RAM efficiency.
    """
    from qdrant_client.models import Distance, VectorParams

    client = get_qdrant_client()
    try:
        collections = await client.get_collections()
        exists = any(c.name == COLLECTION_NAME for c in collections.collections)

        if not exists:
            await client.create_collection(
                collection_name=COLLECTION_NAME,
                vectors_config=VectorParams(
                    size=384,
                    distance=Distance.COSINE,
                ),
                on_disk_payload=True,
            )
            logger.info("Created Qdrant collection: %s", COLLECTION_NAME)
        else:
            logger.info("Qdrant collection already exists: %s", COLLECTION_NAME)
    except Exception as e:
        logger.warning("Qdrant collection setup failed: %s", e)
        raise QdrantUnavailableError(f"Qdrant setup failed: {e}") from e


async def upsert_patent_embeddings(
    patent_ids: list[str],
    embeddings: np.ndarray,
    payloads: list[dict],
) -> int:
    """Batch upsert patent embeddings into Qdrant.

    Chunks into batches of 500 for stability.

    Args:
        patent_ids: List of patent DB UUID strings (used as point IDs).
        embeddings: numpy array of shape (n, 384).
        payloads: List of metadata dicts for each patent.

    Returns:
        Count of upserted points.
    """
    from qdrant_client.models import PointStruct

    client = get_qdrant_client()
    total = len(patent_ids)
    batch_size = 500
    upserted = 0

    for start in range(0, total, batch_size):
        end = min(start + batch_size, total)
        points = [
            PointStruct(
                id=str(patent_ids[i]),
                vector=embeddings[i].tolist(),
                payload=payloads[i],
            )
            for i in range(start, end)
        ]
        await client.upsert(
            collection_name=COLLECTION_NAME,
            points=points,
            wait=True,
        )
        upserted += len(points)

    logger.info("Upserted %d patent embeddings to Qdrant", upserted)
    return upserted


async def search_similar(
    query_vector: np.ndarray,
    session_id: str,
    k: int = 10,
    score_threshold: float = 0.3,
):
    """Search for similar patents in Qdrant.

    Args:
        query_vector: Embedding vector of shape (384,).
        session_id: Filter to patents from this session.
        k: Number of nearest neighbors.
        score_threshold: Minimum similarity score.

    Returns:
        List of ScoredPoint results.
    """
    from qdrant_client.models import (
        FieldCondition,
        Filter,
        MatchValue,
    )

    client = get_qdrant_client()
    try:
        results = await client.search(
            collection_name=COLLECTION_NAME,
            query_vector=query_vector.tolist(),
            limit=k,
            score_threshold=score_threshold,
            with_payload=True,
            query_filter=Filter(
                must=[
                    FieldCondition(
                        key="session_ids",
                        match=MatchValue(value=str(session_id)),
                    )
                ]
            ),
        )
        return results
    except Exception as e:
        logger.warning("Qdrant search failed: %s", e)
        return []


async def get_all_session_embeddings(
    session_id: str,
) -> tuple[list[str], np.ndarray]:
    """Retrieve all embeddings for a session via scroll pagination.

    Handles the scroll pagination correctly — the last batch where
    next_offset is None still contains data.

    Returns:
        (patent_db_ids, embeddings) where embeddings has shape (n, 384).
    """
    from qdrant_client.models import FieldCondition, Filter, MatchValue

    client = get_qdrant_client()
    all_ids: list[str] = []
    all_vectors: list[list[float]] = []

    offset = None
    while True:
        points, next_offset = await client.scroll(
            collection_name=COLLECTION_NAME,
            scroll_filter=Filter(
                must=[
                    FieldCondition(
                        key="session_ids",
                        match=MatchValue(value=str(session_id)),
                    )
                ]
            ),
            limit=500,
            with_vectors=True,
            with_payload=True,
            offset=offset,
        )

        for point in points:
            all_ids.append(str(point.id))
            all_vectors.append(point.vector)

        if next_offset is None:
            break
        offset = next_offset

    if not all_vectors:
        return [], np.empty((0, 384), dtype=np.float32)

    return all_ids, np.array(all_vectors, dtype=np.float32)


async def get_collection_stats() -> dict:
    """Return collection statistics."""
    try:
        client = get_qdrant_client()
        info = await client.get_collection(COLLECTION_NAME)
        return {
            "collection_name": COLLECTION_NAME,
            "points_count": info.points_count,
            "indexed_count": info.indexed_vectors_count,
        }
    except Exception:
        return {"collection_name": COLLECTION_NAME, "status": "unavailable"}


async def patent_already_embedded(patent_db_id: str) -> bool:
    """Check if a patent has already been embedded in Qdrant."""
    try:
        client = get_qdrant_client()
        points = await client.retrieve(
            collection_name=COLLECTION_NAME,
            ids=[str(patent_db_id)],
        )
        return len(points) > 0
    except Exception:
        return False
