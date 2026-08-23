"""Langfuse tracing and span profilers for FastMCP tools and machine learning pipelines."""

from __future__ import annotations

import contextvars
import functools
import inspect
import logging
import os
import time
import uuid
from contextlib import contextmanager, asynccontextmanager
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger("observability.tracer")

# Context variables to track active trace/span in async call stacks
_active_trace_id: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar("_active_trace_id", default=None)
_active_session_id: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar("_active_session_id", default=None)

_langfuse_client = None
_client_initialized = False


def is_langfuse_enabled() -> bool:
    """Check if Langfuse credentials are configured in the environment."""
    public_key = os.getenv("LANGFUSE_PUBLIC_KEY")
    secret_key = os.getenv("LANGFUSE_SECRET_KEY")
    return bool(public_key and secret_key)


def get_langfuse_client():
    """Get or lazily initialize the Langfuse singleton client."""
    global _langfuse_client, _client_initialized

    if _client_initialized:
        return _langfuse_client

    if is_langfuse_enabled():
        try:
            from langfuse import Langfuse

            public_key = os.getenv("LANGFUSE_PUBLIC_KEY")
            secret_key = os.getenv("LANGFUSE_SECRET_KEY")
            host = os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com")

            _langfuse_client = Langfuse(
                public_key=public_key,
                secret_key=secret_key,
                host=host,
            )
            logger.info("Langfuse observability initialized successfully (host=%s)", host)
        except Exception as e:
            logger.warning("Failed to initialize Langfuse client: %s — tracing disabled", e)
            _langfuse_client = None
    else:
        logger.debug("Langfuse keys not found — observability running in no-op mode")
        _langfuse_client = None

    _client_initialized = True
    return _langfuse_client


def log_score(name: str, value: float, comment: Optional[str] = None, trace_id: Optional[str] = None) -> None:
    """Record a numerical evaluation metric/score to the active Langfuse trace."""
    current_trace_id = trace_id or _active_trace_id.get()
    client = get_langfuse_client()

    if client and current_trace_id:
        try:
            client.score(
                trace_id=current_trace_id,
                name=name,
                value=float(value),
                comment=comment,
            )
            logger.debug("Logged Langfuse score: %s = %s (trace=%s)", name, value, current_trace_id)
        except Exception as e:
            logger.warning("Failed to log score %s to Langfuse: %s", name, e)
    else:
        logger.debug("Score recorded (local): %s = %s", name, value)


@contextmanager
def trace_span(name: str, metadata: Optional[Dict[str, Any]] = None):
    """Sync context manager for profiling inner execution spans."""
    client = get_langfuse_client()
    trace_id = _active_trace_id.get()
    start_time = time.perf_counter()
    span = None

    if client and trace_id:
        try:
            span = client.span(
                trace_id=trace_id,
                name=name,
                metadata=metadata or {},
            )
        except Exception as e:
            logger.debug("Failed to create Langfuse span %s: %s", name, e)

    try:
        yield span
    except Exception as exc:
        if span:
            try:
                span.end(level="ERROR", status_message=str(exc))
            except Exception:
                pass
        raise
    finally:
        elapsed_ms = (time.perf_counter() - start_time) * 1000.0
        if span:
            try:
                span.end(metadata={"latency_ms": elapsed_ms, **(metadata or {})})
            except Exception:
                pass
        logger.debug("Span [%s] completed in %.2fms", name, elapsed_ms)


def trace_tool(tool_name: Optional[str] = None):
    """Decorator to trace FastMCP tool calls, latency, payloads, and errors."""

    def decorator(fn: Callable) -> Callable:
        name = tool_name or fn.__name__

        @functools.wraps(fn)
        async def async_wrapper(*args, **kwargs):
            client = get_langfuse_client()

            # Extract session_id if present in args or kwargs
            session_id = kwargs.get("session_id")
            if not session_id and args:
                # Check if first positional argument is session_id string
                if isinstance(args[0], str) and len(args[0]) >= 32:
                    session_id = args[0]

            trace = None
            trace_id = str(uuid.uuid4())
            token_trace = _active_trace_id.set(trace_id)
            token_session = _active_session_id.set(session_id)

            # Sanitize inputs for telemetry
            input_summary = {
                k: (v if not isinstance(v, (bytes, bytearray)) else f"<binary {len(v)} bytes>")
                for k, v in kwargs.items()
            }

            if client:
                try:
                    trace = client.trace(
                        id=trace_id,
                        name=name,
                        session_id=session_id,
                        input=input_summary,
                        metadata={"framework": "fastmcp", "tool": name},
                    )
                except Exception as e:
                    logger.debug("Failed to create Langfuse tool trace for %s: %s", name, e)

            start_time = time.perf_counter()
            try:
                result = await fn(*args, **kwargs)

                elapsed_ms = (time.perf_counter() - start_time) * 1000.0
                if trace:
                    try:
                        trace.update(
                            output=_sanitize_output(result),
                            metadata={"latency_ms": elapsed_ms},
                        )
                    except Exception:
                        pass

                return result

            except Exception as exc:
                elapsed_ms = (time.perf_counter() - start_time) * 1000.0
                if trace:
                    try:
                        trace.update(
                            status_message=str(exc),
                            metadata={"latency_ms": elapsed_ms, "error": str(exc)},
                        )
                    except Exception:
                        pass
                raise

            finally:
                _active_trace_id.reset(token_trace)
                _active_session_id.reset(token_session)

        @functools.wraps(fn)
        def sync_wrapper(*args, **kwargs):
            client = get_langfuse_client()
            session_id = kwargs.get("session_id")

            trace = None
            trace_id = str(uuid.uuid4())
            token_trace = _active_trace_id.set(trace_id)
            token_session = _active_session_id.set(session_id)

            if client:
                try:
                    trace = client.trace(
                        id=trace_id,
                        name=name,
                        session_id=session_id,
                        input=kwargs,
                        metadata={"framework": "fastmcp", "tool": name},
                    )
                except Exception as e:
                    logger.debug("Failed to create Langfuse trace for %s: %s", name, e)

            start_time = time.perf_counter()
            try:
                result = fn(*args, **kwargs)
                elapsed_ms = (time.perf_counter() - start_time) * 1000.0
                if trace:
                    try:
                        trace.update(
                            output=_sanitize_output(result),
                            metadata={"latency_ms": elapsed_ms},
                        )
                    except Exception:
                        pass
                return result
            except Exception as exc:
                elapsed_ms = (time.perf_counter() - start_time) * 1000.0
                if trace:
                    try:
                        trace.update(
                            status_message=str(exc),
                            metadata={"latency_ms": elapsed_ms, "error": str(exc)},
                        )
                    except Exception:
                        pass
                raise
            finally:
                _active_trace_id.reset(token_trace)
                _active_session_id.reset(token_session)

        return async_wrapper if inspect.iscoroutinefunction(fn) else sync_wrapper

    return decorator


def _sanitize_output(output: Any) -> Any:
    """Format outputs safely for Langfuse JSON serialization."""
    if isinstance(output, (dict, list, str, int, float, bool)) or output is None:
        return output
    try:
        if hasattr(output, "model_dump"):
            return output.model_dump()
        if hasattr(output, "to_dict"):
            return output.to_dict()
        return str(output)
    except Exception:
        return "<non-serializable output>"
