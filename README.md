# Research Paper → Patent Gap Finder

> An MCP server that reads your research paper and tells you what's worth patenting — before someone else does.

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![FastMCP](https://img.shields.io/badge/FastMCP-2.14-purple.svg)](https://github.com/jlowin/fastmcp)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE.md)
[![Claude Desktop](https://img.shields.io/badge/Claude%20Desktop-MCP%20Ready-orange.svg)](https://claude.ai/download)
[![Version](https://img.shields.io/badge/version-1.1.0-brightgreen.svg)](https://github.com/prashantshukla01/Patent-Gap-Finder/releases)

---

## What It Does

Researchers and startup CTOs routinely build patentable innovations without realizing it — or file patents that already exist. Both outcomes cost months of wasted work.

**Patent Gap Finder** connects to **Claude Desktop** as an MCP server. You hand it a PDF or arXiv link. It extracts your paper's technical contributions, searches 200+ patents across USPTO, EPO, and Google Patents, maps the existing patent landscape using embeddings and clustering, and identifies the white-space regions where your work is genuinely novel. Then it drafts preliminary patent claims in USPTO format — ready for an attorney to refine.

**The complete pipeline, triggered from a single Claude Desktop conversation.**

---

## Table of Contents

- [Architecture Overview](#architecture-overview)
- [Features](#features)
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
│  parse_paper · classify_ipc · search_prior_art · get_search_status  │
│   map_landscape · find_whitespace · draft_claims · export_report    │
│                          get_session                                │
└──────┬──────────────┬───────────────┬──────────────────┬────────────┘
       │              │               │                  │
┌──────▼──────┐ ┌─────▼──────┐ ┌──────▼──────┐  ┌────────▼───────┐
│  AI / NLP   │ │  External  │ │   Storage   │  │   Async Jobs   │
│             │ │  Patent    │ │             │  │                │
│ Gemini 1.5  │ │    APIs    │ │  PostgreSQL │  │  FastMCP +     │
│    Flash    │ │            │ │   Qdrant    │  │  Docket Queue  │
│ sentence-   │ │   USPTO    │ │   Redis     │  │                │
│ transformers│ │   EPO OPS  │ │   Cache     │  │                │
│  HDBSCAN    │ │  SerpAPI   │ │             │  │                │
└─────────────┘ └────────────┘ └─────────────┘  └────────────────┘
```

---

## Features

### Phase 1 — Ingestion ✅
- Parse research PDFs with multi-column layout detection (IEEE, ACM, Nature formats)
- Fetch papers directly from arXiv by URL or ID
- Extract candidate technical claims using heuristic scoring (no AI cost)
- Detect section boundaries: abstract, introduction, methodology, results, conclusion
- SHA-256 deduplication — same paper never analyzed twice

### Phase 2 — AI Understanding ✅
- **Gemini-powered claim extraction** — turns research contributions into patent-style claim statements with few-shot prompt engineering
- **IPC/CPC classification** — maps each claim to international patent classification codes (e.g. G06N 3/08 for neural networks)
- **Search keyword generation** — produces 10–15 USPTO-optimized search terms per paper
- **Session persistence** — every analysis saved to PostgreSQL, retrievable by session ID
- All AI calls go through a rate-limited Gemini client (free tier: 15 RPM, 1500 RPD)

### Phase 3 — Patent Search ✅
- **Parallel search** across USPTO PatentsView + EPO OPS simultaneously via `asyncio.gather`
- **SerpAPI fallback** — Google Patents consulted when combined results < 30
- **Redis caching** — patent API results cached 7 days (TTL) to preserve free tier quotas
- **Cross-source deduplication** — same patent appearing in USPTO + EPO de-duplicated by normalized ID and title similarity
- **Result normalization** — all sources converted to a unified `Patent` schema

### Phase 4 — Landscape Analysis ✅
- Sentence-transformer embeddings for all retrieved patents (`all-MiniLM-L6-v2`)
- HDBSCAN clustering of the patent landscape stored in Qdrant vector database
- Cosine-distance white-space detection with configurable novelty threshold
- Gemini-assisted novelty reasoning per candidate opportunity

### Phase 5 — Drafting & Deployment ✅
- USPTO-format independent and dependent claim drafting via Gemini
- ReportLab PDF report generation (attorney-ready output with cover page and methodology)
- API key authentication middleware + per-IP rate limiting (HTTP transport)
- Health endpoint (`/health`) for container orchestration
- Full Web UI (Next.js 15) with D3.js patent landscape visualization
- Railway production deployment via Docker Compose

---

## MCP Tools

All 9 tools are callable from Claude Desktop or any MCP client.

| Tool | Description | Input | Output |
|------|-------------|-------|--------|
| `parse_paper` | Parse PDF or arXiv paper | `source: str`, `extract_with_ai: bool` | Structured paper + session ID |
| `classify_ipc` | Map claims to IPC/CPC codes | `session_id: str` | IPC codes + search keywords |
| `search_prior_art` | Search USPTO + EPO + SerpAPI | `session_id: str` | Job ID (async) |
| `get_search_status` | Poll patent search job | `job_id: str` | Status + patent counts |
| `map_landscape` | Embed + cluster patents | `session_id: str` | Cluster map |
| `find_whitespace` | Detect patentable gaps | `session_id: str`, `min_novelty_score: float` | Ranked opportunities |
| `draft_claims` | Generate USPTO-format claims | `session_id: str` | Draft independent + dependent claims |
| `export_report` | Generate PDF analysis report | `session_id: str` | Base64-encoded PDF |
| `get_session` | Retrieve past analysis | `session_id: str` | Full session data |

### Resources

| URI | Description |
|-----|-------------|
| `patent://health` | Server health check with dependency verification |
| `patent://usage` | Gemini API request counters |
| `patent://quota-status` | Estimated remaining daily API calls |
| `patent://cache-stats` | Redis cache statistics |
| `patent://qdrant-stats` | Qdrant vector store statistics |

---

## Tech Stack

| Layer | Technology | Purpose |
|-------|-----------|---------| 
| MCP Framework | FastMCP 2.14 | Tool registration, stdio + streamable-HTTP transport |
| **Primary Client** | **Claude Desktop** | **Conversational MCP interface** |
| AI / NLP | Gemini 1.5 Flash (free) | Claim extraction, IPC classification, claim drafting |
| Embeddings | sentence-transformers `all-MiniLM-L6-v2` | Patent vector embeddings (174 MB, cached) |
| Clustering | HDBSCAN | Patent landscape clustering |
| PDF Parsing | PyMuPDF + pdfplumber | Multi-column PDF ingestion |
| HTTP | httpx (async) | Patent API calls, arXiv fetch |
| Database | PostgreSQL + SQLAlchemy 2.0 + asyncpg | Session and patent persistence |
| Vector DB | Qdrant | Patent embedding storage and ANN search |
| Cache | Redis (redis-py async) | Patent API result caching (7-day TTL) |
| Task Queue | FastMCP Docket (in-memory / Redis) | Async patent search jobs |
| Report | ReportLab | Attorney-ready PDF generation |
| Web UI | Next.js 15 + D3.js | Patent landscape visualization |
| Package Manager | uv (cpython 3.11.15 managed) | Dependency management & venv |
| Infrastructure | Docker Compose | Local dev: Postgres, Redis, Qdrant |

---

## Prerequisites

- **Python 3.11+** (uv will manage the exact version automatically)
- **uv** — [install here](https://docs.astral.sh/uv/getting-started/installation/)
- **Docker + Docker Compose** — for PostgreSQL, Redis, and Qdrant
- **Claude Desktop** — [download here](https://claude.ai/download) — the primary interface
- **Gemini API key** — free, no billing required ([get one here](https://aistudio.google.com/app/apikey))
- **EPO OPS credentials** — free registration ([register here](https://developers.epo.org))
- **SerpAPI key** — optional, 100 free searches/month ([get one here](https://serpapi.com))

> **Important:** This project requires uv's **managed Python 3.11** (not the system `/Library/Frameworks` Python on macOS). uv handles this automatically when you run `uv sync`.

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

> This downloads uv's managed CPython 3.11.15 if needed and installs all 177 packages into `.venv`.

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
PYTHONPATH=src uv run python -m alembic upgrade head
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
# ── Gemini (required for AI features) ─────────────────────────────
# Free tier: 15 RPM, 1500 RPD, no billing needed
# Get key: https://aistudio.google.com/app/apikey
GEMINI_API_KEY=your_gemini_api_key_here

# ── PostgreSQL (required) ──────────────────────────────────────────
# Use URL-encoded password for special characters (@ → %40)
DATABASE_URL=postgresql+asyncpg://postgres:password@localhost:5432/patent_gap_finder

# ── Redis (required) ───────────────────────────────────────────────
REDIS_URL=redis://localhost:6379/0

# ── Qdrant (required for Phase 4+) ────────────────────────────────
QDRANT_URL=http://localhost:6333

# ── EPO Open Patent Services (recommended) ─────────────────────────
EPO_CONSUMER_KEY=your_epo_consumer_key
EPO_CONSUMER_SECRET=your_epo_consumer_secret

# ── SerpAPI / Google Patents (optional) ───────────────────────────
SERPAPI_KEY=your_serpapi_key_here

# ── Server transport ───────────────────────────────────────────────
# Claude Desktop uses "stdio" (default). Web UI uses "streamable-http".
MCP_TRANSPORT=stdio

# ── HTTP transport security (streamable-http mode only) ────────────
MCP_API_KEY=your_secret_api_key_here
RATE_LIMIT_PER_MINUTE=30
```

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
        "GEMINI_API_KEY": "your_gemini_key",
        "DATABASE_URL": "postgresql+asyncpg://postgres:password@localhost:5432/patent_gap_finder",
        "REDIS_URL": "redis://localhost:6379/0",
        "QDRANT_URL": "http://localhost:6333",
        "EPO_CONSUMER_KEY": "your_epo_key",
        "EPO_CONSUMER_SECRET": "your_epo_secret",
        "SERPAPI_KEY": "your_serpapi_key",
        "MCP_TRANSPORT": "stdio"
      }
    }
  }
}
```

> **macOS note:** Use the **absolute path** to `uv` (e.g. `/Users/yourname/.local/bin/uv`). Claude Desktop does not inherit your shell's `$PATH`. Find yours with `which uv`.

**After saving:** Quit Claude Desktop completely (`Cmd+Q`) and reopen it. You should see the 🔨 hammer icon in the chat input — click it to confirm 9 patent tools are listed.

---

## Usage Examples

### Full pipeline from arXiv

```
User: Analyze this paper and find patentable opportunities:
      https://arxiv.org/abs/1706.03762

Claude: [calls parse_paper]          → Extracts "Attention Is All You Need"
        [calls classify_ipc]         → Maps to G06N 3/04, G06F 40/30...
        [calls search_prior_art]     → Returns job_id, search dispatched
        [calls get_search_status]    → 187 patents found across 3 sources
        [calls map_landscape]        → 6 clusters identified
        [calls find_whitespace]      → 2 high-novelty opportunities found
        [calls draft_claims]         → USPTO-format claims generated
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
| **Phase 1** | ✅ Complete | PDF + arXiv ingestion, heuristic claim extraction, FastMCP scaffold |
| **Phase 2** | ✅ Complete | Gemini AI extraction, IPC/CPC classification, PostgreSQL persistence |
| **Phase 3** | ✅ Complete | USPTO + EPO + SerpAPI search, Redis cache, async jobs via Docket |
| **Phase 4** | ✅ Complete | Qdrant embeddings, HDBSCAN clustering, white-space detection |
| **Phase 5** | ✅ Complete | USPTO claim drafting, PDF export, auth middleware, Web UI, Railway deploy |

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
│       ├── server.py               # FastMCP entrypoint — 9 tools, 5 resources
│       │
│       ├── tools/                  # MCP tool handlers (one file per tool)
│       │   ├── parse_paper.py
│       │   ├── classify_ipc.py
│       │   ├── search_prior_art.py
│       │   ├── get_search_status.py
│       │   ├── map_landscape.py
│       │   ├── find_whitespace.py
│       │   ├── draft_claims.py
│       │   ├── export_report.py
│       │   └── get_session.py
│       │
│       ├── parsers/                # Input ingestion
│       │   ├── pdf_parser.py       # PyMuPDF + pdfplumber multi-column
│       │   └── arxiv_parser.py     # arXiv API + PDF download
│       │
│       ├── ai/                     # Gemini AI integration
│       │   ├── gemini_client.py    # Singleton client, rate limiting
│       │   ├── claim_extractor.py  # Patent claim extraction prompts
│       │   └── ipc_classifier.py   # IPC/CPC classification prompts
│       │
│       ├── search/                 # Patent API clients
│       │   ├── uspto_client.py
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
│       ├── drafting/               # Phase 5 claim generation
│       │   ├── claim_drafter.py    # USPTO claim drafting via Gemini
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
└── tests/                          # 271 tests (240 passing unit tests)
    ├── test_pdf_parser.py
    ├── test_arxiv_parser.py
    ├── test_claim_extractor.py
    ├── test_normalizer.py
    ├── test_embedding_engine.py
    ├── test_qdrant_store.py
    ├── test_novelty_reasoner.py
    └── ...
```

---

## API Keys

All required APIs have free tiers. No credit card needed to get started.

| API | Required | Free Tier | How to Get |
|-----|----------|-----------|------------|
| **Gemini 1.5 Flash** | Yes | 15 RPM, 1,500 req/day | [aistudio.google.com/app/apikey](https://aistudio.google.com/app/apikey) |
| **USPTO PatentsView** | No (keyless) | 45 req/min | Optional: [patentsview.org/apis/apikey](https://patentsview.org/apis/apikey) |
| **EPO OPS** | Recommended | 4 GB/week, ~2,000 req/day | [developers.epo.org](https://developers.epo.org) |
| **SerpAPI** | Optional | 100 searches/month | [serpapi.com](https://serpapi.com) |

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
# Full suite (271 tests)
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
PYTHONPATH=src MCP_TRANSPORT=streamable-http uv run python -m patent_gap_finder.server
```

### Railway (Production)

1. Push to GitHub
2. Create a Railway project, add PostgreSQL + Redis plugins
3. Deploy repo — Railway uses `Dockerfile` automatically
4. Add Qdrant as a separate service using `qdrant/qdrant` image
5. Set all environment variables in Railway dashboard

---

## Free Tier Limits

| Service | Free Limit | Usage Per Analysis | Analyses/Day |
|---------|-----------|-------------------|--------------| 
| Gemini 1.5 Flash | 1,500 req/day | ~4–5 requests | ~350 |
| USPTO PatentsView | Unlimited | ~3 requests | Unlimited |
| EPO OPS | ~2,000 req/day | ~5 requests | ~400 |
| SerpAPI | 100 req/month | 0–1 (fallback) | ~3/day |

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
- [Claude Desktop](https://claude.ai/download) — Primary conversational MCP client
- [USPTO PatentsView](https://patentsview.org) — Free US patent data API
- [EPO Open Patent Services](https://developers.epo.org) — European patent API
- [Google Gemini](https://aistudio.google.com) — Free AI inference
- [Qdrant](https://qdrant.tech) — Open-source vector database

---

*Built as a demonstration of full-stack MCP server architecture for real-world IP research automation.*  
*All 5 phases complete — production-ready on Railway + Claude Desktop.*
