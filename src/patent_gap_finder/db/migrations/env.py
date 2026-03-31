"""Alembic env.py — migration environment configuration.

Imports all SQLAlchemy models so Alembic can detect them for autogenerate.
Guards against running autogenerate against SQLite to prevent JSON column
corruption in migrations.
"""

from __future__ import annotations

import os
import sys
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# Add src to path so models can be imported
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))

# Import all models so Base.metadata has them registered
from patent_gap_finder.db.models import Base  # noqa: E402

# Alembic Config object
config = context.config

# Set up loggers
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Set target metadata for autogenerate
target_metadata = Base.metadata

# Allow DATABASE_URL env var to override alembic.ini
db_url = os.environ.get("DATABASE_URL")
if db_url:
    # Convert asyncpg URL to psycopg2 for Alembic (sync migrations)
    sync_url = db_url.replace("+asyncpg", "+psycopg2").replace("+aiosqlite", "")
    config.set_main_option("sqlalchemy.url", sync_url)


def _guard_sqlite(url: str) -> None:
    """Raise an error if running against SQLite.

    Alembic autogenerate against SQLite replaces JSON columns with TEXT,
    producing migrations that corrupt the schema on PostgreSQL. Always
    run autogenerate against a real PostgreSQL instance.
    """
    if "sqlite" in url.lower():
        raise RuntimeError(
            "Alembic migrations must be generated against PostgreSQL, not SQLite. "
            "SQLite does not support JSON columns properly and autogenerate will "
            "produce incorrect migrations. Set DATABASE_URL to a PostgreSQL URL."
        )


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (generate SQL without connecting)."""
    url = config.get_main_option("sqlalchemy.url")
    _guard_sqlite(url)

    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode (connect and apply)."""
    url = config.get_main_option("sqlalchemy.url")
    _guard_sqlite(url)

    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
