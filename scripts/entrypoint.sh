#!/bin/bash
set -e

if [ -n "$DATABASE_URL" ]; then
    echo "Running database migrations..."
    alembic upgrade head || echo "Migration warning: alembic upgrade head failed or DB not ready"
fi

echo "Starting MCP server..."
exec python -m server
