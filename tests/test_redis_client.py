"""Tests for Redis cache client."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from patent_gap_finder.cache.redis_client import RedisClient


class TestBuildCacheKey:
    def test_deterministic(self):
        key1 = RedisClient.build_patent_cache_key("uspto", ["b", "a"], ["G06N"])
        key2 = RedisClient.build_patent_cache_key("uspto", ["a", "b"], ["G06N"])
        assert key1 == key2  # Sorted, so order doesn't matter

    def test_different_sources(self):
        key1 = RedisClient.build_patent_cache_key("uspto", ["a"], ["G06N"])
        key2 = RedisClient.build_patent_cache_key("epo", ["a"], ["G06N"])
        assert key1 != key2

    def test_includes_page(self):
        key1 = RedisClient.build_patent_cache_key("uspto", ["a"], ["G06N"], page=1)
        key2 = RedisClient.build_patent_cache_key("uspto", ["a"], ["G06N"], page=2)
        assert key1 != key2

    def test_format(self):
        key = RedisClient.build_patent_cache_key("uspto", ["neural"], ["G06N"])
        assert key.startswith("patents:uspto:")
        assert ":p1" in key


class TestGetCached:
    async def test_returns_none_on_miss(self):
        client = RedisClient()
        mock_redis = AsyncMock()
        mock_redis.get.return_value = None
        mock_redis.ping.return_value = True
        client._redis = mock_redis

        result = await client.get_cached("patents:test:key")
        assert result is None

    async def test_returns_parsed_dict_on_hit(self):
        client = RedisClient()
        mock_redis = AsyncMock()
        mock_redis.get.return_value = '{"patents": [{"id": "1"}]}'
        mock_redis.ping.return_value = True
        client._redis = mock_redis

        result = await client.get_cached("patents:test:key")
        assert result == {"patents": [{"id": "1"}]}

    async def test_returns_none_on_connection_failure(self):
        client = RedisClient("redis://nonexistent:9999")
        # Force _redis to None so _get_connection attempts to connect
        client._redis = None

        result = await client.get_cached("patents:test:key")
        assert result is None


class TestSetCached:
    async def test_setex_called_with_ttl(self):
        client = RedisClient()
        mock_redis = AsyncMock()
        client._redis = mock_redis

        await client.set_cached("test_key", {"data": "value"}, ttl_seconds=3600)
        mock_redis.setex.assert_called_once()
        args = mock_redis.setex.call_args
        assert args[0][0] == "test_key"
        assert args[0][1] == 3600

    async def test_default_ttl_is_7_days(self):
        client = RedisClient()
        mock_redis = AsyncMock()
        client._redis = mock_redis

        await client.set_cached("test_key", {"data": "value"})
        args = mock_redis.setex.call_args
        assert args[0][1] == 604_800


class TestCacheStats:
    async def test_returns_key_count(self):
        client = RedisClient()
        mock_redis = AsyncMock()
        mock_redis.keys.return_value = ["patents:a", "patents:b"]
        mock_redis.ping.return_value = True
        client._redis = mock_redis

        stats = await client.get_cache_stats()
        assert stats["keys"] == 2
        assert stats["status"] == "connected"
