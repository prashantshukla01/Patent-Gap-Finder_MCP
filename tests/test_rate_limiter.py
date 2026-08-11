import pytest
from unittest.mock import AsyncMock, patch

from patent_gap_finder.middleware.rate_limiter import check_rate_limit, RATE_LIMIT_PER_MINUTE


@pytest.fixture
def mock_redis():
    mock = AsyncMock()
    # Provide necessary mock methods returning scalar data values
    mock.zremrangebyscore = AsyncMock()
    mock.zcard = AsyncMock()
    mock.zadd = AsyncMock()
    mock.expire = AsyncMock()
    mock.zrange = AsyncMock()
    return mock


@pytest.mark.asyncio
async def test_rate_limiter_allow_under_limit(mock_redis):
    with patch("patent_gap_finder.cache.redis_client.get_redis_client") as mock_get_redis:
        mock_client = AsyncMock()
        mock_client._get_connection = AsyncMock(return_value=mock_redis)
        mock_get_redis.return_value = mock_client
        
        # Simulate currently 10 requests in the window
        mock_redis.zcard.return_value = 10
        
        allowed, retry_after = await check_rate_limit("192.168.1.1")
        
        assert allowed is True
        assert retry_after == 0
        mock_redis.zadd.assert_called_once()
        mock_redis.expire.assert_called_once()


@pytest.mark.asyncio
async def test_rate_limiter_deny_over_limit(mock_redis):
    with patch("patent_gap_finder.cache.redis_client.get_redis_client") as mock_get_redis:
        mock_client = AsyncMock()
        mock_client._get_connection = AsyncMock(return_value=mock_redis)
        mock_get_redis.return_value = mock_client
        
        # Simulate reaching the limit
        mock_redis.zcard.return_value = RATE_LIMIT_PER_MINUTE
        
        # Mock zrange returning the timestamp of the oldest request
        import time
        now = time.time()
        mock_redis.zrange.return_value = [("score", now - 50)]
        
        allowed, retry_after = await check_rate_limit("192.168.1.1")
        
        assert allowed is False
        assert retry_after > 0
        assert retry_after <= 11 # 60 - 50 + 1 = 11
        mock_redis.zadd.assert_not_called()


@pytest.mark.asyncio
async def test_rate_limiter_whitelist_localhost():
    # Localhost should bypass without hitting redis
    from patent_gap_finder.middleware.rate_limiter import RateLimitMiddleware
    app_mock = AsyncMock()
    middleware = RateLimitMiddleware(app_mock)
    scope = {"type": "http", "client": ("127.0.0.1", 12345), "path": "/mcp"}
    receive = AsyncMock()
    send = AsyncMock()

    with patch("patent_gap_finder.cache.redis_client.get_redis_client") as mock_get_redis:
        await middleware(scope, receive, send)
        app_mock.assert_called_once_with(scope, receive, send)
        mock_get_redis.assert_not_called()
