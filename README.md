# Research Paper → Patent Gap Finder

> An MCP server that reads your research paper and tells you what's worth patenting — before someone else does.

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![FastMCP](https://img.shields.io/badge/FastMCP-2.0-purple.svg)](https://github.com/jlowin/fastmcp)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE.md%20)
[![Free APIs](https://img.shields.io/badge/APIs-Free%20Tier-orange.svg)](#api-keys)

---

## What It Does

Researchers and startup CTOs routinely build patentable innovations without realizing it — or file patents that already exist. Both outcomes cost months of wasted work.

**Patent Gap Finder** connects to Claude Desktop as an MCP server. You hand it a PDF or arXiv link. It extracts your paper's technical contributions, searches 200+ patents across USPTO, EPO, and Google Patents, maps the existing patent landscape using embeddings and clustering, and identifies the white-space regions where your work is genuinely novel. Then it drafts preliminary patent claims in USPTO format — ready for an attorney to refine.

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
│              Claude Desktop (SSE)  ·  Web UI (HTTP)                 │
└────────────────────────────┬────────────────────────────────────────┘
                             │  MCP Protocol
┌────────────────────────────▼────────────────────────────────────────┐
│                      FastMCP Server (Python)                        │
│   parse_paper · classify_ipc · search_prior_art · map_landscape     │
│             find_whitespace · draft_claims · get_session            │
└──────┬──────────────┬───────────────┬──────────────────┬────────────┘
       │              │               │                  │
┌──────▼──────┐ ┌─────▼──────┐ ┌──────▼──────┐  ┌────────▼───────┐
│  AI / NLP   │ │  External  │ │   Storage   │  │   Async Jobs   │
│             │ │  Patent    │ │             │  │                │
│ Gemini 1.5  │ │    APIs    │ │  PostgreSQL │  │ Celery + Redis │
│    Flash    │ │            │ │   Qdrant    │  │    Workers     │
│ sentence-   │ │   USPTO    │ │   Redis     │  │                │
│ transformers│ │   EPO OPS  │ │   Cache     │  │                │
│  HDBSCAN    │ │  SerpAPI   │ │             │  │                │
└─────────────┘ └────────────┘ └─────────────┘  └────────────────┘
```

---

## Features

### Phase 1 — Ingestion
- Parse research PDFs with multi-column layout detection (IEEE, ACM, Nature formats)
- Fetch papers directly from arXiv by URL or ID
- Extract candidate technical claims using heuristic scoring (no AI cost)
- Detect section boundaries: abstract, introduction, methodology, results, conclusion
- SHA-256 deduplication — same paper never analyzed twice

### Phase 2 — AI Understanding
- **Gemini-powered claim extraction** — turns research contributions into patent-style claim statements with few-shot prompt engineering
- **IPC/CPC classification** — maps each claim to international patent classification codes (e.g. G06N 3/08 for neural networks)
- **Search keyword generation** — produces 10–15 USPTO-optimized search terms per paper
- **Session persistence** — every analysis saved to PostgreSQL, retrievable by session ID
- All AI calls go through a rate-limited Gemini client (free tier: 15 RPM, 1500 RPD)

### Phase 3 — Patent Search
- **Parallel search** across USPTO PatentsView + EPO OPS simultaneously via `asyncio.gather`
- **SerpAPI fallback** — Google Patents consulted when combined results < 30
- **Redis caching** — patent API results cached 7 days (TTL) to preserve free tier quotas
- **Async job queue** — Celery dispatches long-running searches; tools return job IDs immediately
- **Cross-source deduplication** — same patent appearing in USPTO + EPO de-duplicated by normalized ID and title similarity
- **Result normalization** — all sources converted to a unified `Patent` schema

### Phase 4 — Gap Detection *(coming)*
- Sentence-transformer embeddings for all retrieved patents
- HDBSCAN clustering of the patent landscape
- Cosine-distance white-space detection
- Gemini-assisted novelty reasoning

### Phase 5 — Output & Deploy *(coming)*
- USPTO-format independent claim drafting
- PDF report generation
- Railway deployment with Docker Compose
- Web UI with D3.js patent landscape visualization

---

## MCP Tools

All tools are callable from Claude Desktop or any MCP client.

| Tool | Description | Input | Output |
|------|-------------|-------|--------|
| `parse_paper` | Parse PDF or arXiv paper | `source: str`, `extract_with_ai: bool` | Structured paper + session ID |
| `classify_ipc` | Map claims to IPC/CPC codes | `session_id: str` | IPC codes + search keywords |
| `search_prior_art` | Search USPTO + EPO + SerpAPI | `session_id: str` | Job ID (async) |
| `get_search_status` | Poll patent search job | `job_id: str` | Status + patent counts |
| `map_landscape` | Embed + cluster patents | `session_id: str` | Cluster map |
| `find_whitespace` | Detect patentable gaps | `session_id: str` | Ranked opportunities |
| `draft_claims` | Generate USPTO claims | `session_id: str` | Draft independent claims |
| `get_session` | Retrieve past analysis | `session_id: str` | Full session data |

### Resources

| URI | Description |
|-----|-------------|
| `patent://health` | Server health check |
| `patent://usage` | Gemini API request counters |
| `patent://quota-status` | Estimated remaining daily API calls |

---

## Tech Stack

| Layer | Technology | Purpose |
|-------|-----------|---------|
| MCP Framework | FastMCP 2.0 | Tool registration, SSE + HTTP transport |
| AI / NLP | Gemini 1.5 Flash (free) | Claim extraction, IPC classification, claim drafting |
| Embeddings | sentence-transformers (all-MiniLM-L6-v2) | Patent vector embeddings |
| Clustering | HDBSCAN | Patent landscape clustering |
| PDF Parsing | PyMuPDF + pdfplumber | Multi-column PDF ingestion |
| HTTP | httpx (async) | Patent API calls, arXiv fetch |
| Database | PostgreSQL + SQLAlchemy 2.0 + asyncpg | Session and patent persistence |
| Vector DB | Qdrant | Patent embedding storage and search |
| Cache | Redis (redis-py async) | Patent API result caching (7-day TTL) |
| Job Queue | Celery + Redis broker | Async patent search jobs |
| Validation | Pydantic v2 | All schemas and API responses |
| Package Manager | uv | Dependency management |

---

## Prerequisites

- **Python 3.11+**
- **uv** — [install here](https://docs.astral.sh/uv/getting-started/installation/)
- **Docker + Docker Compose** — for PostgreSQL, Redis, Qdrant, and Celery worker
- **Gemini API key** — free, no billing required ([get one here](https://aistudio.google.com/app/apikey))
- **EPO OPS credentials** — free registration ([register here](https://developers.epo.org)) — takes ~10 minutes
- **SerpAPI key** — optional, 100 free searches/month ([get one here](https://serpapi.com))

---

## Installation

### 1. Clone the repository

```bash
git clone https://github.com/your-username/patent-gap-finder.git
cd patent-gap-finder
```

### 2. Install dependencies

```bash
uv sync
```

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

### 5. Initialize the database

```bash
uv run python -m patent_gap_finder.db.init
```

### 6. Start the Celery worker

```bash
uv run celery -A patent_gap_finder.workers.celery_app worker --loglevel=info
```

Open a second terminal for this — keep it running alongside the MCP server.

---

## Configuration

Copy `.env.example` to `.env` and set the following variables:

```bash
# ── Gemini (required) ──────────────────────────────────────────────
# Free tier: 15 RPM, 1500 RPD, no billing needed
# Get key: https://aistudio.google.com/app/apikey
GEMINI_API_KEY=your_gemini_api_key_here

# ── PostgreSQL (required) ──────────────────────────────────────────
# Docker default (change for production)
DATABASE_URL=postgresql+asyncpg://postgres:password@localhost:5432/patent_gap_finder

# ── Redis (required) ───────────────────────────────────────────────
# Used for caching + Celery broker
REDIS_URL=redis://localhost:6379/0

# ── Qdrant (required for Phase 4+) ────────────────────────────────
QDRANT_URL=http://localhost:6333

# ── EPO Open Patent Services (recommended) ─────────────────────────
# Free registration at https://developers.epo.org
# Provides European + PCT patent coverage
EPO_CONSUMER_KEY=your_epo_consumer_key
EPO_CONSUMER_SECRET=your_epo_consumer_secret

# ── SerpAPI / Google Patents (optional) ───────────────────────────
# Only used when USPTO + EPO return < 30 results
# 100 free searches/month
SERPAPI_KEY=your_serpapi_key_here

# ── USPTO (optional) ───────────────────────────────────────────────
# No key needed. Key gives higher rate limits.
# Register free: https://patentsview.org/apis/apikey
USPTO_API_KEY=your_uspto_key_here
```

---

## Running the Server

### Development (stdio — for Claude Desktop)

```bash
uv run python -m patent_gap_finder.server
```

### Production (HTTP — for web clients)

```bash
uv run python -m patent_gap_finder.server --transport streamable-http --port 8000
```

### Docker Compose (all services)

```bash
docker compose up
```

This starts the MCP server, Celery worker, PostgreSQL, Redis, and Qdrant together.

---

## Connecting to Claude Desktop

Add the following to your Claude Desktop config file:

**macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`  
**Windows:** `%APPDATA%\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "patent-gap-finder": {
      "command": "uv",
      "args": [
        "--directory",
        "/absolute/path/to/patent-gap-finder",
        "run",
        "python",
        "-m",
        "patent_gap_finder.server"
      ],
      "env": {
        "GEMINI_API_KEY": "your_key_here",
        "DATABASE_URL": "postgresql+asyncpg://postgres:password@localhost:5432/patent_gap_finder",
        "REDIS_URL": "redis://localhost:6379/0"
      }
    }
  }
}
```

Restart Claude Desktop. You should see "patent-gap-finder" appear in the tools panel.

---

## Usage Examples

### Basic analysis from arXiv

```
User: Analyze this paper and find patentable white-space:
      https://arxiv.org/abs/2301.07041

Claude: [calls parse_paper with extract_with_ai=true]
        [calls classify_ipc]
        [calls search_prior_art]
        [polls get_search_status]
        ...

        Found 3 white-space opportunities in your paper:

        1. G06N 3/08 — Novel sparse attention mask architecture
           No existing patents cover the O(n log n) reduction method
           combined with the proposed positional encoding variant.

        2. G06F 17/30 — Cross-modal embedding alignment technique
           Only 2 prior patents in this specific combination...
```

### From a local PDF

```
User: Check /Users/me/papers/my_cv_paper.pdf for patent opportunities

Claude: [calls parse_paper with source="/Users/me/papers/my_cv_paper.pdf"]
        ...
```

### Retrieve a previous analysis

```
User: Show me the session from last week — session 3f8a2b1c-...

Claude: [calls get_session with the session ID]
        ...
```

### Check search progress

```
User: Is the patent search done yet?

Claude: [calls get_search_status]

        Search complete. Found 187 patents across 3 sources:
        - USPTO: 124 patents
        - EPO: 58 patents
        - Google Patents: 12 patents (SerpAPI fallback)
        - Duplicates removed: 7
        - Cache used: USPTO (saved 1 API call)
```

---

## Implementation Phases

| Phase | Status | What Was Built |
|-------|--------|----------------|
| **Phase 1** | Complete | PDF + arXiv ingestion, heuristic claim extraction, FastMCP scaffold |
| **Phase 2** | Complete | Gemini AI extraction, IPC/CPC classification, PostgreSQL persistence |
| **Phase 3** | Complete | USPTO + EPO + SerpAPI search, Redis cache, Celery async jobs |
| **Phase 4** | In Progress | Qdrant embeddings, HDBSCAN clustering, white-space detection |
| **Phase 5** | Planned | USPTO claim drafting, PDF report output, Railway deployment |

---

## Project Structure

```
patent_gap_finder/
├── pyproject.toml                  # Dependencies (managed by uv)
├── .env.example                    # Environment variable template
├── docker-compose.yml              # Full local dev stack
├── README.md
│
├── src/
│   └── patent_gap_finder/
│       ├── server.py               # FastMCP entrypoint, tool registration
│       │
│       ├── tools/                  # MCP tool handlers (one file per tool)
│       │   ├── parse_paper.py
│       │   ├── classify_ipc.py
│       │   ├── search_prior_art.py
│       │   ├── get_search_status.py
│       │   ├── get_session.py
│       │   ├── map_landscape.py    # Phase 4
│       │   ├── find_whitespace.py  # Phase 4
│       │   └── draft_claims.py     # Phase 5
│       │
│       ├── parsers/                # Input ingestion
│       │   ├── pdf_parser.py       # PyMuPDF + pdfplumber
│       │   └── arxiv_parser.py     # arXiv API + PDF download
│       │
│       ├── ai/                     # Gemini AI integration
│       │   ├── gemini_client.py    # Singleton client, rate limiting
│       │   ├── claim_extractor.py  # Patent claim extraction prompts
│       │   └── ipc_classifier.py   # IPC/CPC classification prompts
│       │
│       ├── search/                 # Patent API clients
│       │   ├── uspto_client.py     # USPTO PatentsView API
│       │   ├── epo_client.py       # EPO OPS + OAuth2
│       │   ├── serpapi_client.py   # Google Patents fallback
│       │   ├── search_coordinator.py  # Parallel orchestration
│       │   └── normalizer.py       # Unified Patent schema + dedup
│       │
│       ├── cache/
│       │   └── redis_client.py     # Async Redis wrapper, TTL management
│       │
│       ├── workers/                # Celery async job processing
│       │   ├── celery_app.py       # Celery configuration
│       │   └── search_tasks.py     # run_patent_search task
│       │
│       ├── db/                     # Database layer
│       │   ├── connection.py       # AsyncSessionLocal, init_db()
│       │   ├── models.py           # SQLAlchemy ORM: Session, Claim, Patent, Job
│       │   └── repositories/       # Repository pattern (one per table)
│       │       ├── session_repo.py
│       │       ├── claim_repo.py
│       │       ├── patent_repo.py
│       │       └── job_repo.py
│       │
│       ├── models/                 # Pydantic schemas (not ORM)
│       │   ├── paper.py            # ParsedPaper, CandidateClaim, ParsedSection
│       │   ├── ipc.py              # AIExtractedClaim, IPCClassificationResponse
│       │   └── patent.py           # Patent, PatentSearchResult, PatentSource
│       │
│       └── utils/
│           └── text_utils.py       # Sentence splitting, heuristic scoring
│
└── tests/
    ├── test_pdf_parser.py
    ├── test_arxiv_parser.py
    ├── test_gemini_client.py
    ├── test_claim_extractor.py
    ├── test_ipc_classifier.py
    ├── test_session_repo.py
    ├── test_classify_ipc_tool.py
    ├── test_uspto_client.py
    ├── test_epo_client.py
    ├── test_normalizer.py
    ├── test_redis_client.py
    ├── test_search_coordinator.py
    ├── test_search_prior_art_tool.py
    └── test_get_search_status_tool.py
```

---

## API Keys

All required APIs have free tiers. No credit card needed to get started.

| API | Required | Free Tier | How to Get |
|-----|----------|-----------|------------|
| **Gemini** | Yes | 15 RPM, 1,500 req/day | [aistudio.google.com/app/apikey](https://aistudio.google.com/app/apikey) |
| **USPTO PatentsView** | No (keyless) | 45 req/min | Optional: [patentsview.org/apis/apikey](https://patentsview.org/apis/apikey) |
| **EPO OPS** | Recommended | 4 GB/week, ~2,000 req/day | [developers.epo.org](https://developers.epo.org) |
| **SerpAPI** | Optional | 100 searches/month | [serpapi.com](https://serpapi.com) |

### Getting your Gemini API key (2 minutes)

1. Go to [aistudio.google.com/app/apikey](https://aistudio.google.com/app/apikey)
2. Click **Create API key**
3. Copy the key into your `.env` as `GEMINI_API_KEY`

No billing setup required. The free tier covers ~1,500 paper analyses per day.

### Registering for EPO OPS (10 minutes)

1. Go to [developers.epo.org](https://developers.epo.org)
2. Register for a free account
3. Create a new application to get `Consumer Key` and `Consumer Secret`
4. Add both to `.env` as `EPO_CONSUMER_KEY` and `EPO_CONSUMER_SECRET`

EPO covers European and PCT (international) patents — important for non-US prior art.

---

## Development

### Run tests

```bash
uv run pytest
```

### Run tests with coverage

```bash
uv run pytest --cov=patent_gap_finder --cov-report=html
open htmlcov/index.html
```

### Run a specific test file

```bash
uv run pytest tests/test_uspto_client.py -v
```

### Monitor Celery tasks (Flower)

```bash
uv run celery -A patent_gap_finder.workers.celery_app flower --port=5555
```

Open [http://localhost:5555](http://localhost:5555) to see task queue, worker status, and task history.

### Verify Redis caching

```bash
redis-cli KEYS "patents:*"           # List all cached patent results
redis-cli TTL "patents:uspto:abc123:p1"  # Check TTL on a specific key
redis-cli INFO memory                # Cache memory usage
```

### Check Qdrant collections (Phase 4+)

```bash
curl http://localhost:6333/collections
```

---

## Testing

Tests use `pytest-asyncio` for async tests and `aiosqlite` for in-memory database tests (no real PostgreSQL needed for the test suite).

```bash
# Full suite
uv run pytest

# Unit tests only (fast, no network calls — all APIs mocked)
uv run pytest tests/ -m "not integration"

# With verbose output
uv run pytest -v --tb=short
```

External API calls (USPTO, EPO, SerpAPI, Gemini) are all mocked in tests using `unittest.mock` and `respx`. No API keys needed to run the test suite.

---

## Deployment

### Local (Docker Compose)

```bash
# Start everything
docker compose up

# View logs
docker compose logs -f mcp_server
docker compose logs -f worker

# Stop everything
docker compose down
```

### Railway (Production)

1. Push your code to GitHub
2. Create a new Railway project
3. Add the following services from Railway's marketplace:
   - **PostgreSQL** plugin
   - **Redis** plugin
4. Deploy the repo — Railway auto-detects the Dockerfile
5. Add a second service for the Celery worker:
   - Same repo, override start command: `celery -A patent_gap_finder.workers.celery_app worker`
6. Add a third service for Qdrant:
   - Use the `qdrant/qdrant` Docker image
7. Set all environment variables in Railway's dashboard

### Environment variables for production

```bash
DATABASE_URL=postgresql+asyncpg://{Railway Postgres connection string}
REDIS_URL=redis://{Railway Redis connection string}
QDRANT_URL=http://{Qdrant service internal URL}:6333
GEMINI_API_KEY=...
EPO_CONSUMER_KEY=...
EPO_CONSUMER_SECRET=...
```

---

## Free Tier Limits

Designed to run entirely on free tiers. Here is the daily budget at scale:

| Service | Free Limit | Usage Per Analysis | Analyses/Day |
|---------|-----------|-------------------|--------------|
| Gemini 1.5 Flash | 1,500 req/day | ~2 requests | ~750 |
| USPTO PatentsView | Unlimited (no key) | ~3 requests | Unlimited |
| EPO OPS | ~2,000 req/day | ~5 requests | ~400 |
| SerpAPI | 100 req/month | 0–1 (fallback only) | ~3/day |
| Redis Cache | Local / Railway free | Reduces API calls by ~60% after warmup | — |

**Practical throughput:** ~400 full analyses per day on the free tier, limited by EPO. USPTO alone supports unlimited analyses. SerpAPI is reserved for edge cases.

---
## License

MIT License — see [LICENSE](LICENSE.md%20) for details.

---

## Contributing

1. Fork the repository
2. Create a feature branch: `git checkout -b feat/my-feature`
3. Make your changes with tests
4. Run the test suite: `uv run pytest`
5. Commit using conventional commits:
   ```
   feat(search): add Lens.org as additional patent source
   fix(epo): handle single-result response as dict not list
   ```
6. Open a pull request

### Commit convention

```
feat:     new feature
fix:      bug fix
refactor: code change (no feature or fix)
test:     test additions or changes
chore:    build, tooling, dependencies
docs:     documentation only
```

---

## Acknowledgements

- [FastMCP](https://github.com/jlowin/fastmcp) — MCP server framework
- [USPTO PatentsView](https://patentsview.org) — Free US patent data API
- [EPO Open Patent Services](https://developers.epo.org) — European patent API
- [Google Gemini](https://aistudio.google.com) — Free AI inference
- [Qdrant](https://qdrant.tech) — Open-source vector database

---

*Built as a demonstration of MCP server architecture for real-world IP research automation.*
