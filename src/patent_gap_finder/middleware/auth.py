"""API key authentication middleware for HTTP transport.

If MCP_API_KEY is set, all HTTP requests must include:
    Authorization: Bearer <key>

If MCP_API_KEY is NOT set, auth is disabled (zero-config local dev).
The /health endpoint always bypasses authentication.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp, Receive, Scope, Send

logger = logging.getLogger(__name__)

# Paths that bypass authentication
AUTH_EXEMPT_PATHS = {"/health", "/docs", "/openapi.json"}


class APIKeyMiddleware:
    """ASGI middleware that validates Bearer token API keys.

    When ``api_key`` is None (MCP_API_KEY not set), all requests pass
    through without authentication — this enables zero-config local
    development.
    """

    def __init__(self, app: ASGIApp, api_key: Optional[str] = None) -> None:
        self.app = app
        self.api_key = api_key or os.environ.get("MCP_API_KEY")
        if not self.api_key:
            logger.warning(
                "MCP_API_KEY not set — HTTP transport has NO authentication. "
                "Set MCP_API_KEY for production deployments."
            )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Check if path is exempt from auth
        path = scope.get("path", "")
        if path in AUTH_EXEMPT_PATHS:
            await self.app(scope, receive, send)
            return

        # If no API key configured, skip auth
        if not self.api_key:
            await self.app(scope, receive, send)
            return

        # Validate Authorization header
        headers = dict(scope.get("headers", []))
        auth_header = headers.get(b"authorization", b"").decode("utf-8", errors="ignore")

        if not auth_header.startswith("Bearer "):
            response = JSONResponse(
                {"error": "UNAUTHORIZED", "message": "Missing or invalid Authorization header"},
                status_code=401,
            )
            await response(scope, receive, send)
            return

        token = auth_header[7:]
        if token != self.api_key:
            response = JSONResponse(
                {"error": "UNAUTHORIZED", "message": "Invalid API key"},
                status_code=401,
            )
            await response(scope, receive, send)
            return

        # Log authenticated request
        logger.info("Authenticated request: path=%s", path)
        await self.app(scope, receive, send)


def validate_api_key(request: Request) -> bool:
    """Standalone validation function for use outside middleware.

    Args:
        request: Starlette Request object.

    Returns:
        True if the API key is valid or auth is disabled.
    """
    api_key = os.environ.get("MCP_API_KEY")
    if not api_key:
        return True

    auth = request.headers.get("authorization", "")
    if not auth.startswith("Bearer "):
        return False

    return auth[7:] == api_key
