# Multi-stage Dockerfile for Patent Gap Finder MCP Server
# Stage 1: Build dependencies with uv
# Stage 2: Minimal runtime image

# ── Stage 1: Builder ──────────────────────────────────────────────────
FROM python:3.11-slim AS builder
WORKDIR /app

RUN apt-get update && apt-get install -y \
    build-essential \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*
# Install uv for fast dependency resolution
RUN pip install --no-cache-dir uv

# Copy dependency files first for layer caching
COPY pyproject.toml uv.lock* ./
COPY README.md ./

# Install production dependencies only
RUN uv sync --frozen --no-dev 2>/dev/null || uv sync --no-dev

# ── Stage 2: Runtime ─────────────────────────────────────────────────
FROM python:3.11-slim AS runtime
WORKDIR /app

# System dependencies for PyMuPDF + asyncpg + ReportLab
RUN apt-get update && apt-get install -y --no-install-recommends \
    libglib2.0-0 \
    libgl1 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Non-root user for security
RUN adduser --disabled-password --gecos "" appuser

# Copy virtual environment from builder
COPY --from=builder /app/.venv /app/.venv

# Copy application source
COPY src/ src/
COPY scripts/ scripts/
COPY alembic.ini .

# Set ownership and permissions
RUN chmod +x /app/scripts/*.sh && chown -R appuser:appuser /app
USER appuser

# Environment
ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONPATH="/app/src"
ENV PYTHONUNBUFFERED=1
ENV MCP_TRANSPORT=streamable-http

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -sf http://localhost:${PORT:-8000}/health || exit 1

CMD ["python", "-m", "patent_gap_finder.server"]
