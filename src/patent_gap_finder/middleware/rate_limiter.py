"""Per-IP rate limiting middleware using Redis sorted sets.

Implements a sliding window rate limiter:
- Each IP's requests are tracked in a Redis ZSET (key: ratelimit:<ip>)
- Window: 60 seconds
- Default limit: 30 requests/minute (configurable via RATE_LIMIT_PER_MINUTE)
- Localhost (127.0.0.1) is exempt in development

Returns 429 Too Many Requests with Retry-After header when limit exceeded.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Optional

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

logger = logging.getLogger(__name__)

RATE_LIMIT_PER_MINUTE = int(os.environ.get("RATE_LIMIT_PER_MINUTE", "30"))
WINDOW_SECONDS = 60

# IPs exempt from rate limiting (local development)
EXEMPT_IPS = {"127.0.0.1", "::1", "localhost"}


async def check_rate_limit(client_ip: str) -> tuple[bool, int]:
    """Check if a request from client_ip is within rate limits.

    Uses Redis ZSET sliding window algorithm.

    Args:
        client_ip: The client's IP address.

    Returns:
        Tuple of (is_allowed, retry_after_seconds).
        If is_allowed is False, retry_after_seconds > 0.
    """
    try:
        from patent_gap_finder.cache.redis_client import get_redis_client

        redis_client = get_redis_client()
        conn = await redis_client._get_connection()
        if conn is None:
            # Redis unavailable — allow request (fail open)
            return True, 0
    except Exception:
        return True, 0

    key = f"ratelimit:{client_ip}"
    now = time.time()
    window_start = now - WINDOW_SECONDS

    try:
        # Remove old entries outside the window
        await conn.zremrangebyscore(key, 0, window_start)

        # Count requests in current window
        count = await conn.zcard(key)

        if count >= RATE_LIMIT_PER_MINUTE:
            # Rate limited — calculate retry after
            oldest = await conn.zrange(key, 0, 0, withscores=True)
            if oldest:
                retry_after = int(WINDOW_SECONDS - (now - oldest[0][1])) + 1
                retry_after = max(retry_after, 1)
            else:
                retry_after = 1
            return False, retry_after

        # Add this request
        await conn.zadd(key, {str(now): now})
        await conn.expire(key, WINDOW_SECONDS + 10)

        return True, 0
    except Exception as e:
        logger.warning("Rate limit check failed (allowing request): %s", e)
        return True, 0


def _get_client_ip(scope: Scope) -> str:
    """Extract client IP from ASGI scope."""
    client = scope.get("client")
    if client:
        return client[0]
    # Fallback: check headers for proxy
    headers = dict(scope.get("headers", []))
    forwarded = headers.get(b"x-forwarded-for", b"").decode()
    if forwarded:
        return forwarded.split(",")[0].strip()
    return "unknown"


class RateLimitMiddleware:
    """ASGI middleware for per-IP rate limiting via Redis.

    Rate limits are enforced using a sliding window algorithm with
    Redis sorted sets. Localhost IPs are exempt in development.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        client_ip = _get_client_ip(scope)

        # Exempt localhost
        if client_ip in EXEMPT_IPS:
            await self.app(scope, receive, send)
            return

        # Skip rate limiting for health checks
        path = scope.get("path", "")
        if path == "/health":
            await self.app(scope, receive, send)
            return

        is_allowed, retry_after = await check_rate_limit(client_ip)

        if not is_allowed:
            logger.warning(
                "Rate limit exceeded for %s (retry_after=%ds)",
                client_ip,
                retry_after,
            )
            response = JSONResponse(
                {
                    "error": "RATE_LIMITED",
                    "message": f"Too many requests. Retry after {retry_after} seconds.",
                    "retry_after": retry_after,
                },
                status_code=429,
                headers={"Retry-After": str(retry_after)},
            )
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)
