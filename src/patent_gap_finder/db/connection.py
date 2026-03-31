"""Async SQLAlchemy engine and session factory.

Supports PostgreSQL (asyncpg) for production and SQLite (aiosqlite)
for testing.  The ``init_db()`` function runs Alembic migrations for
PostgreSQL and falls back to ``create_all`` for SQLite test databases.
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────
# Engine and session factory
# ──────────────────────────────────────────────────────────────────────

_engine = None
_session_factory = None


def _get_engine():
    """Create or return the async engine (lazy singleton)."""
    global _engine
    if _engine is None:
        url = os.environ.get(
            "DATABASE_URL",
            "sqlite+aiosqlite:///patent_gap_finder.db",
        )
        logger.info("Creating database engine: %s", url.split("@")[-1] if "@" in url else url)

        # Different kwargs for different backends
        kwargs = {}
        if url.startswith("postgresql"):
            kwargs = {
                "pool_size": 5,
                "max_overflow": 10,
                "pool_pre_ping": True,
            }

        _engine = create_async_engine(url, echo=False, **kwargs)
    return _engine


def _get_session_factory():
    """Create or return the session factory (lazy singleton)."""
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            bind=_get_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
        )
    return _session_factory


@asynccontextmanager
async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Provide a transactional async database session.

    Usage::

        async with get_db_session() as db:
            result = await session_repo.get_session(db, session_id)

    Yields:
        An :class:`AsyncSession` instance.  Commits on success,
        rolls back on exception.
    """
    factory = _get_session_factory()
    session = factory()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


async def init_db() -> None:
    """Initialize the database schema.

    For PostgreSQL: runs Alembic migrations (``alembic upgrade head``).
    For SQLite (tests): falls back to ``create_all`` since Alembic
    does not support SQLite JSON columns correctly.

    Called during FastMCP server startup via the lifespan handler.
    Safe to call multiple times.
    """
    import os

    url = os.environ.get("DATABASE_URL", "")

    if "postgresql" in url:
        # Use Alembic migrations for production PostgreSQL
        try:
            import asyncio
            from alembic.config import Config
            from alembic import command

            alembic_cfg = Config("alembic.ini")
            # Override URL from environment
            alembic_cfg.set_main_option(
                "sqlalchemy.url",
                url.replace("+asyncpg", "+psycopg2"),
            )
            await asyncio.to_thread(command.upgrade, alembic_cfg, "head")
            logger.info("Alembic migrations applied successfully")
        except Exception as e:
            logger.warning("Alembic migration failed, falling back to create_all: %s", e)
            from patent_gap_finder.db.models import Base
            engine = _get_engine()
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            logger.info("Database tables created via create_all fallback")
    else:
        # SQLite or other — use create_all directly
        from patent_gap_finder.db.models import Base
        engine = _get_engine()
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("Database tables created/verified (non-PostgreSQL)")


async def close_db() -> None:
    """Dispose of the engine connection pool.

    Called during server shutdown.
    """
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _session_factory = None
        logger.info("Database engine disposed")


def reset_db() -> None:
    """Reset engine and factory singletons (used in tests)."""
    global _engine, _session_factory
    _engine = None
    _session_factory = None
