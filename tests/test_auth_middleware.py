import pytest
from unittest.mock import AsyncMock

from starlette.responses import Response

from patent_gap_finder.middleware.auth import APIKeyMiddleware


@pytest.fixture
def mock_app():
    async def app(scope, receive, send):
        response = Response("success", 200)
        await response(scope, receive, send)
    return app


@pytest.mark.asyncio
async def test_auth_valid_token(mock_app):
    middleware = APIKeyMiddleware(mock_app, "secret-key")
    
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/mcp",
        "headers": [(b"authorization", b"Bearer secret-key")]
    }
    
    receive = AsyncMock()
    send = AsyncMock()
    
    await middleware(scope, receive, send)
    
    # Send should be called twice (start, body)
    assert send.await_count == 2
    assert send.call_args_list[0][0][0]["status"] == 200


@pytest.mark.asyncio
async def test_auth_missing_header(mock_app):
    middleware = APIKeyMiddleware(mock_app, "secret-key")
    
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/mcp",
        "headers": []
    }
    
    receive = AsyncMock()
    send = AsyncMock()
    
    await middleware(scope, receive, send)
    
    assert send.await_count == 2
    assert send.call_args_list[0][0][0]["status"] == 401


@pytest.mark.asyncio
async def test_auth_invalid_token(mock_app):
    middleware = APIKeyMiddleware(mock_app, "secret-key")
    
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/mcp",
        "headers": [(b"authorization", b"Bearer wrong-key")]
    }
    
    receive = AsyncMock()
    send = AsyncMock()
    
    await middleware(scope, receive, send)
    
    assert send.await_count == 2
    assert send.call_args_list[0][0][0]["status"] == 401


@pytest.mark.asyncio
async def test_auth_disabled_when_none(mock_app):
    middleware = APIKeyMiddleware(mock_app, None)
    
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/mcp",
        "headers": []
    }
    
    receive = AsyncMock()
    send = AsyncMock()
    
    await middleware(scope, receive, send)
    
    assert send.await_count == 2
    assert send.call_args_list[0][0][0]["status"] == 200


@pytest.mark.asyncio
async def test_auth_bypass_health(mock_app):
    middleware = APIKeyMiddleware(mock_app, "secret-key")
    
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/health",
        "headers": []
    }
    
    receive = AsyncMock()
    send = AsyncMock()
    
    await middleware(scope, receive, send)
    
    assert send.await_count == 2
    assert send.call_args_list[0][0][0]["status"] == 200
