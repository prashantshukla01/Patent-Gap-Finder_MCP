# Research Paper → Patent Gap Finder

> An MCP server that reads your research paper and tells you what's worth patenting — before someone else does.

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![FastMCP](https://img.shields.io/badge/FastMCP-2.14-purple.svg)](https://github.com/jlowin/fastmcp)
[![Langfuse Observability](https://img.shields.io/badge/Langfuse-Live%20Metrics%20%26%20Traces-blue.svg)](https://us.cloud.langfuse.com/project/cmt5wcj2n004pad0i3h8ovphb)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE.md)
[![Claude Desktop](https://img.shields.io/badge/Claude%20Desktop-MCP%20Ready-orange.svg)](https://claude.ai/download)
[![Version](https://img.shields.io/badge/version-1.1.0-brightgreen.svg)](https://github.com/prashantshukla01/Patent-Gap-Finder/releases)

---

## What It Does

Researchers and startup CTOs routinely build patentable innovations without realizing it — or file patents that already exist. Both outcomes cost months of wasted work.

**Patent Gap Finder** connects to **Claude Desktop** as an MCP server. You hand it a PDF or arXiv link. It extracts your paper's technical contributions, searches 200+ patents across EPO, Lens.org, and Google Patents, maps the existing patent landscape using embeddings and clustering, and identifies the white-space regions where your work is genuinely novel. Then Claude drafts preliminary patent claims in USPTO format — ready for an attorney to refine.

**No AI API key required on the server.** Claude Desktop handles all reasoning. The server is a pure data and compute engine.

**The complete pipeline, triggered from a single Claude Desktop conversation.**

---

## Table of Contents

- [Architecture Overview](#architecture-overview)
- [Features](#features)
- [Observability & Live Metrics](#observability--live-metrics)
- [MCP Tools](#mcp-tools)
- [Tech Stack](#tech-stack)
- [Prerequisites](#prerequisites)
- [Installation](#installation)
- [Configuration](#configuration)
- [Running the Server](#running-the-server)
- [Connecting to Claude Desktop](#connecting-to-claude-desktop)
- [Usage Examples](#usage-examples)
- [Implementation Phases](#implementation-phases)
- [Project Structure](#project-structure)
- [API Keys](#api-keys)
- [Development](#development)
- [Testing](#testing)
- [Deployment](#deployment)
- [Free Tier Limits](#free-tier-limits)
- [Contributing](#contributing)
- [License](#license)

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                         MCP Clients                                 │
│         Claude Desktop (stdio)  ·  Web UI (streamable-http)         │
└────────────────────────────┬────────────────────────────────────────┘
                             │  MCP Protocol (stdio / HTTP)
┌────────────────────────────▼────────────────────────────────────────┐
│                   FastMCP 2.14 Server (Python 3.11)                  │
│                                                                     │
│   parse_paper · classify_ipc · search_prior_art · get_search_status │
│   map_landscape · find_whitespace · draft_claims · export_report    │
│   save_claims · save_classification · save_whitespace · get_session │
│                                                                     │
│   Instruct-then-Save: tools return ai_instructions for Claude       │
│   Claude does reasoning · save_* tools persist Claude's output      │
└──────┬──────────────┬───────────────┬──────────────────┬────────────┘
       │              │               │                  │
┌──────▼──────┐ ┌─────▼──────┐ ┌──────▼──────┐  ┌────────▼───────┐
│  Embeddings │ │  External  │ │   Storage   │  │   Async Jobs   │
│  & Cluster  │ │  Patent    │ │             │  │                │
│             │ │    APIs    │ │  PostgreSQL │  │  Celery +      │
│ sentence-   │ │            │ │   Qdrant    │  │  Redis Broker  │
│ transformers│ │   Lens.org │ │   Redis     │  │                │
│  HDBSCAN    │ │   EPO OPS  │ │   Cache     │  │                │
│             │ │  SerpAPI   │ │             │  │                │
└─────────────┘ └────────────┘ └─────────────┘  └────────────────┘
```

**Key design principle:** Claude Desktop is the AI. The server never calls any AI API. This means zero AI cost on the server, users leverage their existing Claude subscription, and the architecture stays simple.

---

## Features

### Phase 1 — Ingestion
- Parse research PDFs with multi-column layout detection (IEEE, ACM, Nature formats)
- Fetch papers directly from arXiv by URL or ID
- Extract candidate technical claims using heuristic scoring (no AI cost)
- Detect section boundaries: abstract, introduction, methodology, results, conclusion
- SHA-256 deduplication — same paper never analyzed twice

### Phase 2 — AI Understanding (via Claude Desktop)
- Returns structured `ai_instructions` from `parse_paper` for Claude to extract patent claims
- Claude maps each claim to IPC/CPC international patent classification codes
- Claude generates 10–15 USPTO-optimized search terms per paper
- `save_claims` and `save_classification` persist Claude's output to PostgreSQL
- Every analysis saved and retrievable by session ID

### Phase 3 — Patent Search
- Parallel search across EPO OPS + Lens.org (USPTO replacement) simultaneously via `asyncio.gather`
- SerpAPI fallback — Google Patents consulted when combined results < 50
- Redis caching — patent API results cached 7 days (TTL) to preserve free tier quotas
- Cross-source deduplication — same patent across sources de-duplicated by normalized ID and title similarity
- Result normalization — all sources converted to a unified `Patent` schema

### Phase 4 — Landscape Analysis
- Sentence-transformer embeddings for all retrieved patents (`all-MiniLM-L6-v2`)
- HDBSCAN clustering of the patent landscape stored in Qdrant vector database
- Cosine-distance white-space detection with configurable novelty threshold
- `find_whitespace` returns opportunities with instructions for Claude to assess novelty

### Phase 5 — Drafting and Deployment
- `draft_claims` returns opportunities with USPTO drafting rules for Claude to draft claims
- ReportLab PDF report generation (attorney-ready output with cover page and methodology)
- API key authentication middleware + per-IP rate limiting (HTTP transport)
- Health endpoint (`/health`) for container orchestration
- Full Web UI (Next.js 15) with D3.js patent landscape visualization
- Railway production deployment via Docker

---

## Observability & Live Metrics

Patent Gap Finder includes complete observability, tracing, and automated pipeline evaluation powered by **[Langfuse](https://langfuse.com)**. Every tool execution, model embedding generation, HDBSCAN clustering step, and drafted patent claim is profiled and scored in real time.

### 🔗 Live Dashboards & Model Metrics

You can inspect the live execution traces, model latency, and evaluation scores directly on the Langfuse platform:

* 📊 **[Project Overview Dashboard](https://us.cloud.langfuse.com/project/cmt5wcj2n004pad0i3h8ovphb)**
* ⏱️ **[Live Tool Traces & Execution Latency](https://us.cloud.langfuse.com/project/cmt5wcj2n004pad0i3h8ovphb/traces)**
* 📈 **[Model Evaluation & Quality Scores](https://us.cloud.langfuse.com/project/cmt5wcj2n004pad0i3h8ovphb/scores)**

### 📐 Tracked Mathematical & Quality Metrics

| Metric | Range | Description |
| :--- | :--- | :--- |
| **`silhouette_score`** | `-1.0` to `+1.0` | Mathematical cluster cohesion and separation quality calculated across patent embedding space. |
| **`noise_ratio`** | `0.0` to `1.0` | Percentage of retrieved prior art patents identified as outlier noise by HDBSCAN. |
| **`cluster_count`** | `0+` | Number of distinct patent technological landscape clusters formed. |
| **`whitespace_opportunity_count`** | `0+` | Number of identified white-space innovation gap regions. |
| **`avg_claim_novelty_score`** | `0.0` to `1.0` | Average cosine distance between research paper claims and nearest prior art patents. |
| **`claim_structural_compliance`** | `0.0` to `1.0` | Automated USPTO 35 U.S.C. 112 structural validator (preamble, transition word `comprising`, body technical limitations). |
| **`SentenceTransformer.encode_texts`** | `ms` | Dense vector embedding latency and item throughput profiling. |
| **FastMCP Tool Traces** | `ms` | Input payloads, session IDs, execution durations, and output responses across all 13 FastMCP tools. |

---

## MCP Tools

All 13 tools are callable from Claude Desktop or any MCP client.

| Tool | Description | Input | Output |
|------|-------------|-------|--------|
| `parse_paper` | Parse PDF or arXiv paper | `source: str`, `content: str`, `title: str` | Structured paper + session ID + ai_instructions |
| `save_claims` | Persist Claude's extracted claims | `session_id`, `claims`, `paper_summary`, `primary_domain` | Confirmation + next step |
| `classify_ipc` | Get claims with IPC classification instructions | `session_id: str` | Claims + classification ai_instructions |
| `save_classification` | Persist Claude's IPC mappings | `session_id`, `mappings`, `top_ipc_codes`, `search_keywords` | Confirmation + next step |
| `search_prior_art` | Search EPO + Lens.org + SerpAPI | `session_id: str` | Job ID (async) |
| `get_search_status` | Poll patent search job | `job_id: str` | Status + patent counts |
| `map_landscape` | Embed + cluster patents | `session_id: str` | Cluster map |
| `find_whitespace` | Detect patentable gaps | `session_id: str`, `min_novelty_score: float` | Opportunities + assessment ai_instructions |
| `save_whitespace` | Persist Claude's novelty assessments | `session_id`, `assessments` | Confirmation + next step |
| `draft_claims` | Get opportunities with USPTO drafting instructions | `session_id: str` | Opportunities + drafting ai_instructions |
| `save_drafted_claims` | Persist Claude's drafted claims | `session_id`, `claim_sets` | Confirmation + next step |
| `export_report` | Generate PDF analysis report | `session_id: str` | Base64-encoded PDF |
| `get_session` | Retrieve past analysis | `session_id: str` | Full session data |

### Resources

| URI | Description |
|-----|-------------|
| `patent://health` | Server health check with dependency verification |
| `patent://usage` | Server architecture info (no AI API usage to track) |
| `patent://quota-status` | Patent API rate limit status (EPO, SerpAPI) |
| `patent://cache-stats` | Redis cache statistics |
| `patent://qdrant-stats` | Qdrant vector store statistics |

---

## Tech Stack

| Layer | Technology | Purpose |
|-------|-----------|---------| 
| MCP Framework | FastMCP 2.14 | Tool registration, stdio + streamable-HTTP transport |
| **Primary Client** | **Claude Desktop** | **All AI reasoning — claim extraction, IPC classification, novelty assessment, claim drafting** |
| Embeddings | sentence-transformers `all-MiniLM-L6-v2` | Patent vector embeddings (174 MB, cached) |
| Clustering | HDBSCAN | Patent landscape clustering |
| PDF Parsing | PyMuPDF + pdfplumber | Multi-column PDF ingestion |
| HTTP | httpx (async) | Patent API calls, arXiv fetch |
| Database | PostgreSQL + SQLAlchemy 2.0 + asyncpg | Session and patent persistence |
| Vector DB | Qdrant | Patent embedding storage and ANN search |
| Cache | Redis (redis-py async) | Patent API result caching (7-day TTL) |
| Task Queue | Celery + Redis | Async patent search jobs |
| Report | ReportLab | Attorney-ready PDF generation |
| Web UI | Next.js 15 + D3.js | Patent landscape visualization |
| Package Manager | uv (cpython 3.11.15 managed) | Dependency management and venv |
| Infrastructure | Docker Compose | Local dev: Postgres, Redis, Qdrant |

---

## Prerequisites

- **Python 3.11+** (uv will manage the exact version automatically)
- **uv** — [install here](https://docs.astral.sh/uv/getting-started/installation/)
- **Docker + Docker Compose** — for PostgreSQL, Redis, and Qdrant
- **Claude Desktop** — [download here](https://claude.ai/download) — the primary interface and AI engine
- **EPO OPS credentials** — free registration ([register here](https://developers.epo.org))
- **SerpAPI key** — optional, 100 free searches/month ([get one here](https://serpapi.com))
- **Lens.org API key** — optional, free registration for higher patent search volume ([get one here](https://www.lens.org/lens/user/apikey))

> **Important:** This project requires uv's **managed Python 3.11** (not the system `/Library/Frameworks` Python on macOS). uv handles this automatically when you run `uv sync`.

> **No AI API key needed.** Claude Desktop (the user's own account) handles all reasoning. The server is a zero-cost data engine.

---

## Installation

### 1. Clone the repository

```bash
git clone https://github.com/prashantshukla01/Patent-Gap-Finder.git
cd Patent-Gap-Finder
```

### 2. Install dependencies (uv manages Python version automatically)

```bash
uv sync
```

> This downloads uv's managed CPython 3.11.15 if needed and installs all packages into `.venv`.

### 3. Copy environment config

```bash
cp .env.example .env
```

Edit `.env` and fill in your API keys (see [Configuration](#configuration)).

### 4. Start infrastructure services

```bash
docker compose up -d postgres redis qdrant
```

This starts PostgreSQL on `5432`, Redis on `6379`, and Qdrant on `6333`.

### 5. Run database migrations

```bash
PYTHONPATH=src uv run alembic upgrade head
```

### 6. Pre-download the embedding model (one-time, ~30s)

```bash
PYTHONPATH=src uv run python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"
```

This caches the 174 MB model so Claude Desktop doesn't wait on first launch.

---

## Configuration

Copy `.env.example` to `.env` and set the following variables:

```bash
# ── PostgreSQL (required) ──────────────────────────────────────────
# Use URL-encoded password for special characters (@ → %40)
DATABASE_URL=postgresql+asyncpg://postgres:password@localhost:5432/patent_gap_finder

# ── Redis (required) ───────────────────────────────────────────────
REDIS_URL=redis://localhost:6379/0

# ── Qdrant (required for Phase 4+) ────────────────────────────────
QDRANT_URL=http://localhost:6333

# ── EPO Open Patent Services (recommended) ─────────────────────────
# Free registration: https://developers.epo.org
EPO_CONSUMER_KEY=your_epo_consumer_key
EPO_CONSUMER_SECRET=your_epo_consumer_secret

# ── SerpAPI / Google Patents (optional) ───────────────────────────
# 100 free searches/month: https://serpapi.com
SERPAPI_KEY=your_serpapi_key_here

# ── Lens.org / USPTO replacement (optional) ───────────────────────
# Free registration: https://www.lens.org/lens/user/apikey
# Without this key, EPO + SerpAPI cover the search gap automatically.
LENS_API_KEY=your_lens_api_key_here

# ── Server transport ───────────────────────────────────────────────
# Claude Desktop uses "stdio" (default). Web UI uses "streamable-http".
MCP_TRANSPORT=stdio

# ── HTTP transport security (streamable-http mode only) ────────────
MCP_API_KEY=your_secret_api_key_here
RATE_LIMIT_PER_MINUTE=30
```

> No Gemini or Anthropic API key required. Claude Desktop uses the user's own Claude account for all AI reasoning.

---

## Running the Server

### For Claude Desktop (stdio mode — recommended)

Claude Desktop launches the server automatically via the config below.
You do **not** need to run it manually.

### For Web UI / API (HTTP mode)

```bash
PYTHONPATH=src MCP_TRANSPORT=streamable-http uv run python -m patent_gap_finder.server
```

Server starts at `http://localhost:8000`. Health check: `curl http://localhost:8000/health`

### Every-session startup (run once per machine restart)

```bash
# 1. Start infrastructure
docker compose up -d postgres redis qdrant

# 2. (Optional) Start HTTP server for Web UI
PYTHONPATH=src MCP_TRANSPORT=streamable-http uv run python -m patent_gap_finder.server
```

---

## Connecting to Claude Desktop

Add the following to your Claude Desktop config file:

**macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`  
**Windows:** `%APPDATA%\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "patent-gap-finder": {
      "command": "/Users/YOUR_USERNAME/.local/bin/uv",
      "args": [
        "--directory",
        "/absolute/path/to/Patent-Gap-Finder",
        "run",
        "python",
        "-m",
        "patent_gap_finder.server"
      ],
      "env": {
        "PYTHONPATH": "/absolute/path/to/Patent-Gap-Finder/src",
        "DATABASE_URL": "postgresql+asyncpg://postgres:password@localhost:5432/patent_gap_finder",
        "REDIS_URL": "redis://localhost:6379/0",
        "QDRANT_URL": "http://localhost:6333",
        "EPO_CONSUMER_KEY": "your_epo_key",
        "EPO_CONSUMER_SECRET": "your_epo_secret",
        "SERPAPI_KEY": "your_serpapi_key",
        "LENS_API_KEY": "your_lens_key",
        "MCP_TRANSPORT": "stdio"
      }
    }
  }
}
```

> **macOS note:** Use the **absolute path** to `uv` (e.g. `/Users/yourname/.local/bin/uv`). Claude Desktop does not inherit your shell's `$PATH`. Find yours with `which uv`.

**After saving:** Quit Claude Desktop completely (`Cmd+Q`) and reopen it. You should see the hammer icon in the chat input — click it to confirm the patent tools are listed.

---

## Usage Examples

### Full pipeline from arXiv

```
User: Analyze this paper and find patentable opportunities:
      https://arxiv.org/abs/1706.03762

Claude: [calls parse_paper]          → Extracts "Attention Is All You Need"
        [extracts claims from paper] → Identifies novel technical contributions
        [calls save_claims]          → Persists extracted claims
        [calls classify_ipc]         → Gets classification instructions
        [classifies into IPC codes]  → Maps to G06N 3/04, G06F 40/30...
        [calls save_classification]  → Persists IPC mappings
        [calls search_prior_art]     → Returns job_id, search dispatched
        [calls get_search_status]    → 187 patents found across 3 sources
        [calls map_landscape]        → 6 clusters identified
        [calls find_whitespace]      → 2 high-novelty opportunities found
        [assesses novelty]           → Reviews each opportunity
        [calls save_whitespace]      → Persists novelty assessments
        [calls draft_claims]         → Gets USPTO drafting instructions
        [drafts patent claims]       → Writes independent + dependent claims
        [calls save_drafted_claims]  → Persists drafted claims
        [calls export_report]        → PDF report ready

Found 2 white-space opportunities:

1. G06N 3/04 — Multi-head self-attention with learned positional sparsity
   Novelty score: 0.82 | No direct prior art coverage

2. G06F 40/30 — Cross-attention alignment for sequence-to-sequence tasks
   Novelty score: 0.71 | Only 3 tangential patents found
```

### From a local PDF

```
User: Find patent gaps in /Users/me/papers/my_paper.pdf

Claude: [calls parse_paper with source="/Users/me/papers/my_paper.pdf"]
        ...
```

### Retrieve a previous analysis

```
User: Show me session 3f8a2b1c-...

Claude: [calls get_session]   → Full session with all results
```

---

## Implementation Phases

| Phase | Status | What Was Built |
|-------|--------|----------------|
| **Phase 1** | Complete | PDF + arXiv ingestion, heuristic claim extraction, FastMCP scaffold |
| **Phase 2** | Complete | Instruct-then-save AI workflow, IPC/CPC classification via Claude, PostgreSQL persistence |
| **Phase 3** | Complete | EPO + Lens.org + SerpAPI search, Redis cache, async jobs |
| **Phase 4** | Complete | Qdrant embeddings, HDBSCAN clustering, white-space detection |
| **Phase 5** | Complete | USPTO claim drafting via Claude, PDF export, auth middleware, Web UI, Railway deploy |

---

## Project Structure

```
Patent-Gap-Finder/
├── pyproject.toml                  # Dependencies (managed by uv)
├── uv.lock                         # Locked dependency graph
├── .env.example                    # Environment variable template
├── docker-compose.yml              # Local dev: Postgres, Redis, Qdrant
├── docker-compose.prod.yml         # Production compose override
├── Dockerfile                      # MCP server container
├── Dockerfile.worker               # Celery worker container
├── railway.toml                    # Railway deployment config
├── alembic.ini                     # DB migration config
├── README.md
│
├── src/
│   └── patent_gap_finder/
│       ├── server.py               # FastMCP entrypoint — 13 tools, 5 resources
│       │
│       ├── tools/                  # MCP tool handlers (one file per tool)
│       │   ├── parse_paper.py      # Parse PDF/arXiv, return ai_instructions
│       │   ├── save_claims.py      # Persist Claude's extracted claims
│       │   ├── classify_ipc.py     # Return claims + IPC instructions for Claude
│       │   ├── save_classification.py
│       │   ├── search_prior_art.py
│       │   ├── get_search_status.py
│       │   ├── map_landscape.py
│       │   ├── find_whitespace.py  # Return gaps + novelty instructions for Claude
│       │   ├── save_whitespace.py
│       │   ├── draft_claims.py     # Return opportunities + USPTO rules for Claude
│       │   ├── save_drafted_claims.py
│       │   ├── export_report.py
│       │   └── get_session.py
│       │
│       ├── parsers/                # Input ingestion
│       │   ├── pdf_parser.py       # PyMuPDF + pdfplumber multi-column
│       │   └── arxiv_parser.py     # arXiv API + PDF download
│       │
│       ├── ai/                     # Architecture documentation only
│       │   └── __init__.py         # Instruct-then-save pattern description
│       │
│       ├── search/                 # Patent API clients
│       │   ├── uspto_client.py     # Lens.org (USPTO replacement, post-2026 migration)
│       │   ├── epo_client.py       # EPO OPS + OAuth2
│       │   ├── serpapi_client.py
│       │   ├── search_coordinator.py
│       │   └── normalizer.py       # Unified Patent schema + dedup
│       │
│       ├── embeddings/             # Vector storage
│       │   ├── embedding_engine.py # sentence-transformers singleton
│       │   └── qdrant_store.py     # Qdrant upsert + ANN search
│       │
│       ├── clustering/             # Phase 4 landscape analysis
│       │   ├── landscape_builder.py  # HDBSCAN clustering
│       │   └── whitespace_detector.py # Gap detection + novelty scoring
│       │
│       ├── drafting/               # Phase 5 formatting
│       │   └── claim_formatter.py  # USPTO format validation
│       │
│       ├── reporting/              # Phase 5 PDF output
│       │   └── pdf_report.py       # ReportLab PDF generation
│       │
│       ├── middleware/             # HTTP transport security
│       │   ├── auth.py             # API key authentication
│       │   └── rate_limiter.py     # Per-IP Redis rate limiting
│       │
│       ├── cache/
│       │   └── redis_client.py     # Async Redis wrapper, TTL management
│       │
│       ├── db/                     # Database layer
│       │   ├── connection.py       # Async engine, init_db()
│       │   ├── models.py           # SQLAlchemy ORM
│       │   ├── migrations/         # Alembic migrations
│       │   └── repositories/       # Repository pattern
│       │
│       └── models/                 # Pydantic schemas
│           ├── paper.py
│           ├── ipc.py
│           └── patent.py
│
├── web/                            # Next.js 15 Web UI
│   ├── src/app/                    # App router pages
│   ├── src/components/             # React components
│   ├── src/hooks/                  # usePipeline, useSession
│   └── src/lib/api.ts              # MCP HTTP client
│
└── tests/
    ├── test_pdf_parser.py
    ├── test_arxiv_parser.py
    ├── test_normalizer.py
    ├── test_embedding_engine.py
    ├── test_qdrant_store.py
    └── ...
```

---

## API Keys

No credit card required for any of these. The server itself needs no AI API key.

| API | Required | Free Tier | How to Get |
|-----|----------|-----------|------------|
| **EPO OPS** | Recommended | 4 GB/week, ~2,000 req/day | [developers.epo.org](https://developers.epo.org) |
| **SerpAPI** | Optional | 100 searches/month | [serpapi.com](https://serpapi.com) |
| **Lens.org** | Optional | Free with registration | [lens.org/lens/user/apikey](https://www.lens.org/lens/user/apikey) |

> **USPTO note:** The original PatentsView API (`search.patentsview.org`) was permanently shut down in March 2026. Patent Gap Finder uses Lens.org as a drop-in replacement with equivalent US + global patent coverage. When `LENS_API_KEY` is not set, EPO + SerpAPI handle the search automatically.

---

## Development

```bash
# Run all unit tests (no network, all APIs mocked)
PYTHONPATH=src uv run pytest tests/ -m "not integration" -v

# Run with coverage
PYTHONPATH=src uv run pytest --cov=patent_gap_finder --cov-report=html

# Run linter
uv run ruff check src/

# Check Qdrant
curl http://localhost:6333/collections

# Monitor Redis cache
redis-cli KEYS "patents:*"
```

---

## Testing

Tests use `pytest-asyncio` and `aiosqlite` for in-memory database tests — no real PostgreSQL or external APIs needed.

```bash
# Full suite
PYTHONPATH=src uv run pytest

# Unit tests only (fast)
PYTHONPATH=src uv run pytest tests/ -m "not integration"

# Specific file
PYTHONPATH=src uv run pytest tests/test_pdf_parser.py -v
```

---

## Deployment

### Local (Docker Compose)

```bash
docker compose up -d postgres redis qdrant
PYTHONPATH=src MCP_TRANSPORT=streamable-http uv run python -m server
```

### Railway (Production)

1. Push to GitHub
2. Create a Railway project, add PostgreSQL + Redis plugins
3. Deploy repo — Railway uses `Dockerfile` automatically
4. Add Qdrant as a separate service using `qdrant/qdrant` image
5. Set environment variables in Railway dashboard (see [Configuration](#configuration))

Railway will run `alembic upgrade head` before starting the server (configured in `railway.toml`).

---

## Free Tier Limits

| Service | Free Limit | Usage Per Analysis | Analyses/Day |
|---------|-----------|-------------------|--------------| 
| EPO OPS | ~2,000 req/day | ~5 requests | ~400 |
| SerpAPI | 100 req/month | 0–1 (fallback) | ~3/day |
| Lens.org | 10,000 req/month | ~3 requests | ~100/day |
| Redis Cache | — | 7-day TTL on results | Reduces repeat API calls |

---

## License

MIT License — see [LICENSE](LICENSE.md) for details.

---

## Contributing

1. Fork the repository
2. Create a feature branch: `git checkout -b feat/my-feature`
3. Add tests for your changes
4. Run `PYTHONPATH=src uv run pytest tests/ -m "not integration"`
5. Commit using conventional commits (`feat:`, `fix:`, `docs:`, `chore:`)
6. Open a pull request

---

## Acknowledgements

- [FastMCP](https://github.com/jlowin/fastmcp) — MCP server framework
- [Claude Desktop](https://claude.ai/download) — Primary conversational MCP client and AI engine
- [EPO Open Patent Services](https://developers.epo.org) — European patent API
- [Lens.org](https://www.lens.org) — Global patent search (USPTO replacement)
- [Qdrant](https://qdrant.tech) — Open-source vector database

---

*Built as a demonstration of full-stack MCP server architecture for real-world IP research automation.*  
*All 5 phases complete — production-ready on Railway + Claude Desktop.*
