"""Async Redis wrapper for patent search result caching.

Uses ``redis.asyncio`` for non-blocking access with 7-day TTL default.
Gracefully degrades when Redis is unavailable — all operations return
None/empty on connection failure so the search pipeline continues
without caching.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from typing import Optional

import redis.asyncio as aioredis

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────
# Singleton
# ──────────────────────────────────────────────────────────────────────

_client: Optional[RedisClient] = None


class RedisClient:
    """Thin async wrapper around ``redis.asyncio``."""

    def __init__(self, url: Optional[str] = None) -> None:
        self._url = url or os.environ.get("REDIS_URL", "redis://localhost:6379/0")
        self._redis: Optional[aioredis.Redis] = None

    async def _get_connection(self) -> Optional[aioredis.Redis]:
        """Lazily establish Redis connection."""
        if self._redis is None:
            try:
                self._redis = aioredis.from_url(
                    self._url, decode_responses=True
                )
                await self._redis.ping()
                logger.info("Redis connected: %s", self._url.split("@")[-1])
            except Exception as e:
                logger.warning("Redis unavailable (%s) — caching disabled", e)
                self._redis = None
        return self._redis

    # ── Core operations ──────────────────────────────────────────────

    async def get_cached(self, key: str) -> Optional[dict]:
        """Return parsed JSON for *key*, or None on miss/error."""
        try:
            conn = await self._get_connection()
            if conn is None:
                return None
            raw = await conn.get(key)
            if raw is None:
                return None
            return json.loads(raw)
        except Exception as e:
            logger.warning("Redis get failed for %s: %s", key, e)
            return None

    async def set_cached(
        self,
        key: str,
        data: dict,
        ttl_seconds: int = 604_800,  # 7 days
    ) -> None:
        """Serialize *data* to JSON and store with SETEX."""
        try:
            conn = await self._get_connection()
            if conn is None:
                return
            await conn.setex(key, ttl_seconds, json.dumps(data, default=str))
        except Exception as e:
            logger.warning("Redis set failed for %s: %s", key, e)

    # ── Key building ─────────────────────────────────────────────────

    @staticmethod
    def build_patent_cache_key(
        source: str,
        keywords: list[str],
        ipc_codes: list[str],
        page: int = 1,
    ) -> str:
        """Build a deterministic, stable cache key.

        Uses SHA-256 on sorted inputs so key is identical across process
        restarts (unlike Python's built-in ``hash()``).
        """
        kw_hash = hashlib.sha256(
            "|".join(sorted(keywords)).encode()
        ).hexdigest()[:16]
        ipc_hash = hashlib.sha256(
            "|".join(sorted(ipc_codes)).encode()
        ).hexdigest()[:16]
        return f"patents:{source}:{kw_hash}:{ipc_hash}:p{page}"

    # ── Diagnostics ──────────────────────────────────────────────────

    async def get_cache_stats(self) -> dict:
        """Return keyspace info for patent cache keys."""
        try:
            conn = await self._get_connection()
            if conn is None:
                return {"keys": 0, "status": "disconnected"}
            keys = await conn.keys("patents:*")
            return {"keys": len(keys), "status": "connected"}
        except Exception:
            return {"keys": 0, "status": "error"}

    async def invalidate_session_cache(self, session_id: str) -> int:
        """Delete all patent cache keys. Returns count deleted."""
        try:
            conn = await self._get_connection()
            if conn is None:
                return 0
            keys = await conn.keys("patents:*")
            if keys:
                return await conn.delete(*keys)
            return 0
        except Exception:
            return 0

    async def close(self) -> None:
        """Close the Redis connection pool."""
        if self._redis is not None:
            await self._redis.close()
            self._redis = None


def get_redis_client() -> RedisClient:
    """Return the Redis client singleton."""
    global _client
    if _client is None:
        _client = RedisClient()
    return _client


def reset_redis_client() -> None:
    """Reset the singleton (for tests)."""
    global _client
    _client = None
