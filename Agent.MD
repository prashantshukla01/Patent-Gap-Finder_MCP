# AGENT.md — Patent Gap Finder

> Complete agent specification for AI assistants, contributors, and automated
> systems working on this codebase.

---

## What This Project Is

**Research Paper → Patent Gap Finder** is an MCP (Model Context Protocol) server
that identifies patentable white-space opportunities from research papers.

A user connects this server to **Claude Desktop**. Claude Desktop acts as the
reasoning engine — no external AI API is called, no API key is needed, no cost
is incurred. The MCP server provides tools. Claude Desktop provides intelligence.
Together they form a zero-cost patent analysis pipeline.

```
User
 │
 ▼
Claude Desktop (reasoning — free, no API key)
 │  MCP Protocol (stdio)
 ▼
Patent Gap Finder MCP Server
 │
 ├── PostgreSQL  (session + patent storage)
 ├── Redis       (caching + Celery broker)
 ├── Qdrant      (vector embeddings)
 └── Celery      (async patent search jobs)
      │
      ├── USPTO PatentsView API  (free, no key)
      ├── EPO OPS API            (free registration)
      └── SerpAPI                (optional fallback)
```

---

## Critical Architecture Decision — No External AI API

**There is no AI API key in this project.**

All reasoning, claim extraction, IPC classification, cluster labeling, novelty
assessment, and patent claim drafting is performed by **Claude Desktop itself**
via the MCP protocol. The server exposes tools. Claude calls those tools,
processes the results, and reasons about them natively.

This means:
- No `ANTHROPIC_API_KEY` required
- No `GEMINI_API_KEY` required
- No `OPENAI_API_KEY` required
- Zero AI inference cost to the project owner
- Claude Desktop's built-in intelligence handles everything

**If you see any file importing `anthropic`, `google.generativeai`, or `openai`
as a client for inference — that is a bug. Remove it.**

The only AI-adjacent library allowed is `sentence-transformers` for generating
vector embeddings locally on CPU. This is not an API call — it runs entirely
on the user's machine.

---

## Project Structure

```
Patent-MCP/
├── AGENT.md                          # This file
├── README.md
├── LICENSE.md
├── SECURITY.md
├── CODE_OF_CONDUCT.md
├── pyproject.toml                    # uv-managed dependencies
├── .env.example                      # Template — copy to .env
├── .env                              # Local secrets — git-ignored
├── .gitignore
├── alembic.ini                       # DB migration config
├── docker-compose.yml                # Local dev (Postgres, Redis, Qdrant)
├── docker-compose.prod.yml           # Production
├── Dockerfile                        # MCP server image
├── Dockerfile.worker                 # Celery worker image
├── railway.toml                      # Railway deployment config
│
├── src/
│   └── patent_gap_finder/
│       ├── __init__.py
│       ├── server.py                 # FastMCP entrypoint — register all tools here
│       │
│       ├── tools/                    # One file per MCP tool
│       │   ├── parse_paper.py        # Tool 1: parse PDF or arXiv
│       │   ├── classify_ipc.py       # Tool 2: IPC/CPC classification
│       │   ├── search_prior_art.py   # Tool 3: dispatch patent search job
│       │   ├── get_search_status.py  # Tool 4: poll Celery job
│       │   ├── map_landscape.py      # Tool 5: embed + cluster patents
│       │   ├── find_whitespace.py    # Tool 6: detect novelty gaps
│       │   ├── draft_claims.py       # Tool 7: USPTO claim drafting
│       │   ├── export_report.py      # Tool 8: generate PDF report
│       │   └── get_session.py        # Tool 9: retrieve past analysis
│       │
│       ├── parsers/
│       │   ├── pdf_parser.py         # PyMuPDF + pdfplumber
│       │   └── arxiv_parser.py       # arXiv API + async PDF download
│       │
│       ├── search/                   # Patent API clients
│       │   ├── uspto_client.py       # USPTO PatentsView (free, no key)
│       │   ├── epo_client.py         # EPO OPS + OAuth2 token management
│       │   ├── serpapi_client.py     # Google Patents fallback (optional)
│       │   ├── search_coordinator.py # asyncio.gather parallel search
│       │   └── normalizer.py         # Unified Patent schema + deduplication
│       │
│       ├── embeddings/               # Local vector operations (no API)
│       │   ├── embedding_engine.py   # sentence-transformers singleton
│       │   ├── qdrant_store.py       # Qdrant async CRUD
│       │   └── text_preparer.py      # Text cleaning + field prefixing
│       │
│       ├── clustering/
│       │   ├── hdbscan_clusterer.py  # HDBSCAN + adaptive params
│       │   ├── landscape_builder.py  # embed → cluster → store
│       │   └── whitespace_detector.py # cosine distance gap detection
│       │
│       ├── reporting/
│       │   └── pdf_report.py         # ReportLab PDF generator
│       │
│       ├── drafting/
│       │   ├── claim_drafter.py      # USPTO claim format builder
│       │   └── claim_formatter.py    # Numbered claim section formatter
│       │
│       ├── cache/
│       │   └── redis_client.py       # Async Redis, 7-day TTL
│       │
│       ├── workers/
│       │   ├── celery_app.py         # Celery + Redis broker config
│       │   └── search_tasks.py       # run_patent_search Celery task
│       │
│       ├── middleware/
│       │   ├── auth.py               # Bearer token validation
│       │   └── rate_limiter.py       # Redis sliding window rate limit
│       │
│       ├── db/
│       │   ├── connection.py         # AsyncSessionLocal, init_db()
│       │   ├── models.py             # All SQLAlchemy ORM models
│       │   ├── migrations/           # Alembic versions — always commit these
│       │   └── repositories/
│       │       ├── session_repo.py
│       │       ├── claim_repo.py
│       │       ├── patent_repo.py
│       │       ├── job_repo.py
│       │       ├── landscape_repo.py
│       │       └── drafts_repo.py
│       │
│       └── models/                   # Pydantic schemas (not ORM)
│           ├── paper.py
│           ├── ipc.py
│           ├── patent.py
│           ├── landscape.py
│           └── drafts.py
│
├── web/                              # Next.js 14 frontend (optional)
│   ├── src/
│   │   ├── app/
│   │   ├── components/
│   │   ├── hooks/
│   │   └── lib/
│   └── package.json
│
└── tests/                            # pytest test suite
    ├── test_pdf_parser.py
    ├── test_arxiv_parser.py
    ├── test_session_repo.py
    ├── test_uspto_client.py
    ├── test_epo_client.py
    ├── test_normalizer.py
    ├── test_redis_client.py
    ├── test_search_coordinator.py
    ├── test_hdbscan_clusterer.py
    ├── test_whitespace_detector.py
    ├── test_embedding_engine.py
    ├── test_qdrant_store.py
    ├── test_claim_formatter.py
    ├── test_pdf_report.py
    └── test_e2e_pipeline.py
```

---

## MCP Tools — Complete Reference

All tools are registered in `server.py` and callable from Claude Desktop.
Claude Desktop handles ALL reasoning about tool outputs — the tools only
fetch, store, and compute.

| # | Tool | Signature | What it does |
|---|------|-----------|--------------|
| 1 | `parse_paper` | `(source: str, extract_with_ai: bool = False)` | Parse PDF or arXiv URL. Returns structured paper + session ID |
| 2 | `classify_ipc` | `(session_id: str)` | Heuristic IPC/CPC code mapping from claim keywords |
| 3 | `search_prior_art` | `(session_id: str)` | Dispatch Celery patent search. Returns job_id immediately |
| 4 | `get_search_status` | `(job_id: str)` | Poll patent search job completion and results |
| 5 | `map_landscape` | `(session_id: str)` | Embed patents → HDBSCAN cluster → store in Qdrant |
| 6 | `find_whitespace` | `(session_id: str, min_novelty_score: float = 0.5)` | Cosine distance gap detection against patent clusters |
| 7 | `draft_claims` | `(session_id: str, min_novelty_score: float = 0.5)` | Build USPTO-format independent + dependent claims |
| 8 | `export_report` | `(session_id: str)` | Generate ReportLab PDF. Returns base64-encoded bytes |
| 9 | `get_session` | `(session_id: str)` | Retrieve full session data, claims, patents, opportunities |

### MCP Resources

| URI | Returns |
|-----|---------|
| `patent://health` | Status of all dependencies |
| `patent://usage` | Embedding model stats, request counts |
| `patent://quota-status` | Remaining free API quota estimates |
| `patent://qdrant-stats` | Vector collection point count |

### How Claude Desktop Uses These Tools

Claude Desktop calls tools in this sequence for a full analysis:

```
1. parse_paper(source, extract_with_ai=false)
   → Gets session_id + heuristic candidate claims

2. classify_ipc(session_id)
   → Gets IPC codes + search keywords (keyword-based, no AI needed)

3. search_prior_art(session_id)
   → Gets job_id

4. [loop] get_search_status(job_id)
   → Polls every ~10s until status="complete"

5. map_landscape(session_id)
   → Embeds patents locally, clusters with HDBSCAN

6. find_whitespace(session_id)
   → Returns ranked novelty opportunities

7. draft_claims(session_id)
   → Returns USPTO-format claim sets

8. export_report(session_id)
   → Returns downloadable PDF

9. [optional] get_session(session_id)
   → Full data for any past analysis
```

Claude Desktop reads each tool response and reasons about it — deciding what
to call next, what to tell the user, and how to interpret the results.
The server is stateless between tool calls. All state lives in PostgreSQL.

---

## Data Models — Database Tables

```
analysis_sessions        — one row per paper analyzed
extracted_claims         — AI or heuristic claims per session
patents                  — normalized patents from all sources
session_patents          — many-to-many: session ↔ patent
search_jobs              — Celery job tracking per session
landscape_jobs           — embedding/clustering job per session
cluster_records          — HDBSCAN cluster metadata
whitespace_opportunities — detected gaps with novelty scores
drafted_claims           — USPTO-format claim text
```

Full schema is in `db/models.py`. Migrations are in `db/migrations/versions/`.

**Always run migrations before starting the server:**
```bash
uv run alembic upgrade head
```

---

## Environment Variables

Copy `.env.example` to `.env` and fill in values.

### Required (project will not start without these)

```bash
DATABASE_URL=postgresql+asyncpg://postgres:password@localhost:5432/patent_gap_finder
REDIS_URL=redis://localhost:6379/0
QDRANT_URL=http://localhost:6333
```

### Required for patent search

```bash
# EPO Open Patent Services — free at https://developers.epo.org
EPO_CONSUMER_KEY=your_epo_key
EPO_CONSUMER_SECRET=your_epo_secret
```

### Optional

```bash
# Google Patents fallback — 100 free/month at https://serpapi.com
SERPAPI_KEY=your_serpapi_key

# USPTO higher rate limits — free at https://patentsview.org/apis/apikey
USPTO_API_KEY=your_uspto_key

# HTTP transport security (generate with: openssl rand -hex 32)
MCP_API_KEY=random_secret_string

# Tuning
RATE_LIMIT_PER_MINUTE=30
LOG_LEVEL=INFO
WHITESPACE_THRESHOLD=0.65
K_NEAREST_PATENTS=10
```

### What is NOT needed

```bash
# These are NOT used — no external AI API
# ANTHROPIC_API_KEY  ← not needed
# GEMINI_API_KEY     ← not needed
# OPENAI_API_KEY     ← not needed
```

---

## How to Run Locally

### Prerequisites
- Python 3.11+
- uv (`curl -LsSf https://astral.sh/uv/install.sh | sh`)
- Docker Desktop

### Start infrastructure
```bash
docker compose up -d postgres redis qdrant
```

### Install dependencies
```bash
uv sync
```

### Run migrations
```bash
uv run alembic upgrade head
```

### Pre-download embedding model (one-time, ~90MB)
```bash
uv run python -c "
from sentence_transformers import SentenceTransformer
SentenceTransformer('all-MiniLM-L6-v2')
print('Model ready')
"
```

### Start Celery worker (Terminal 1)
```bash
uv run celery -A patent_gap_finder.workers.celery_app worker --loglevel=info
```

### Start MCP server (Terminal 2)
```bash
uv run python -m patent_gap_finder.server
```

### Connect to Claude Desktop

Add to `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "patent-gap-finder": {
      "command": "/absolute/path/to/.local/bin/uv",
      "args": [
        "--directory",
        "/absolute/path/to/Patent-MCP",
        "run",
        "python",
        "-m",
        "patent_gap_finder.server"
      ],
      "env": {
        "DATABASE_URL": "postgresql+asyncpg://postgres:password@localhost:5432/patent_gap_finder",
        "REDIS_URL": "redis://localhost:6379/0",
        "QDRANT_URL": "http://localhost:6333",
        "EPO_CONSUMER_KEY": "your_key",
        "EPO_CONSUMER_SECRET": "your_secret"
      }
    }
  }
}
```

**Important notes:**
- Use the full absolute path to `uv` (run `which uv` to find it)
- Use full absolute path to the project directory
- Do NOT use `~` in paths — Claude Desktop does not expand it
- Restart Claude Desktop (Cmd+Q, then reopen) after editing the config
- All env vars must be in the config `env` block — `.env` file is NOT
  read by Claude Desktop's subprocess

### Verify connection
In Claude Desktop, type:
```
Use the get_session tool with session_id "test" to verify the server is connected
```
You should see the tool being called (even if it returns SESSION_NOT_FOUND —
that confirms the server is running and tools are registered).

---

## How to Run Tests

```bash
# Unit tests only (fast, no network, no Docker needed)
uv run pytest tests/ -m "not integration" -v

# With coverage
uv run pytest tests/ -m "not integration" --cov=patent_gap_finder --cov-report=term

# Single file
uv run pytest tests/test_uspto_client.py -v

# Full integration test (requires all Docker services + real API keys)
uv run pytest tests/test_e2e_pipeline.py -m integration -v
```

All external APIs (USPTO, EPO, SerpAPI) are mocked in unit tests.
No API keys needed to run the unit test suite.

---

## Patent API Reference

### USPTO PatentsView
- **URL**: `https://search.patentsview.org/api/v1/patent/`
- **Auth**: None required (optional key for higher limits)
- **Rate limit**: 45 req/min (no key), higher with key
- **Free tier**: Unlimited data
- **Query format**: POST with JSON body, `_text_any` for full-text search

### EPO Open Patent Services
- **URL**: `https://ops.epo.org/3.2/rest-services/`
- **Auth**: OAuth2 client credentials
  - Token URL: `https://ops.epo.org/3.2/auth/accesstoken`
  - Token expires: every 20 minutes (auto-refreshed in `epo_client.py`)
- **Rate limit**: 10 req/sec
- **Free tier**: 4GB/week, ~2000 req/day
- **Query language**: CQL (e.g. `txt=neural AND network AND ic=G06N`)

### SerpAPI (Google Patents)
- **URL**: `https://serpapi.com/search.json?engine=google_patents`
- **Auth**: `api_key` query parameter
- **Free tier**: 100 searches/month
- **Used only as fallback**: when USPTO + EPO return < 30 results

### USPTO Query Patterns (common issues)
```python
# CORRECT — use _begins for IPC prefix match
{"_begins": {"ipc_code": "G06N"}}

# WRONG — _eq requires exact match, not prefix
{"_eq": {"ipc_code": "G06N"}}

# CORRECT — text search field name
{"_text_any": {"patent_abstract": "neural network attention"}}

# CORRECT — combine text + IPC
{"_and": [
    {"_text_any": {"patent_abstract": "keyword1 keyword2"}},
    {"_or": [{"_begins": {"ipc_code": "G06N"}}]}
]}
```

---

## Embedding & Clustering

### Embedding model
- **Model**: `all-MiniLM-L6-v2` (sentence-transformers)
- **Dimension**: 384
- **Runs**: locally on CPU — no API call, no cost
- **Speed**: ~14,000 sentences/sec on CPU
- **Size**: ~90MB (cached in `~/.cache/huggingface/` after first download)

### Text preparation
- Patents: `"patent abstract: {title}. {abstract[:512]}"`
- Claims: `"research claim: {claim_text}"`

### HDBSCAN parameters
| Patent count | min_cluster_size | min_samples |
|---|---|---|
| < 80 | 3 | 2 |
| 80–150 | 4 | 2 |
| ≥ 150 | 5 | 3 |

Noise points (label = -1) are stored but excluded from white-space analysis.

### White-space detection thresholds
```python
WHITESPACE_THRESHOLD = 0.65      # avg cosine similarity to K nearest patents
CLUSTER_DISTANCE_THRESHOLD = 0.40 # euclidean distance to nearest centroid
K_NEAREST = 10                   # neighbors considered per claim
```

A claim is flagged as white-space when BOTH:
- `avg_neighbor_similarity < WHITESPACE_THRESHOLD`
- `nearest_centroid_distance > CLUSTER_DISTANCE_THRESHOLD`

---

## Coding Standards

### Async
- All tool handlers, repository methods, and client methods must be `async`
- Use `asyncio.to_thread()` for CPU-bound work (embedding, HDBSCAN, PDF parsing)
- Never call blocking functions directly in async code

### Database sessions
```python
# CORRECT — one session per request, closed after use
async with AsyncSessionLocal() as db:
    result = await session_repo.get_session(db, session_id)

# WRONG — never store sessions on a global or share across requests
self.db = AsyncSessionLocal()  # bug
```

### Error returns from MCP tools
```python
# Always return structured error dicts — never raise from a tool handler
return {
    "error": "SESSION_NOT_FOUND",
    "message": f"Session {session_id} not found. Run parse_paper first.",
    "session_id": session_id
}
```

### Cache keys
```python
# Use hashlib.sha256 — never Python's hash() (randomized per process)
import hashlib
key = hashlib.sha256("|".join(sorted(keywords)).encode()).hexdigest()[:16]
cache_key = f"patents:uspto:{key}:p{page}"
```

### No AI API calls in tools
Tools compute, fetch, store, and return structured data.
Claude Desktop reads the data and does the reasoning.

```python
# CORRECT — tool returns structured data for Claude to reason about
return {
    "whitespace_opportunities": [...],
    "clusters": [...],
    "total_patents": 187
}

# WRONG — tool should not call an AI API
response = anthropic_client.messages.create(...)  # never do this
```

---

## Deployment (Railway)

### Services required in Railway
1. **MCP server** — main app, runs FastMCP in HTTP mode
2. **Celery worker** — separate service, same repo, different start command
3. **PostgreSQL** — Railway plugin
4. **Redis** — Railway plugin
5. **Qdrant** — Docker image `qdrant/qdrant`, port 6333

### Start commands
```bash
# MCP server
python -m patent_gap_finder.server --transport streamable-http --port $PORT

# Celery worker
celery -A patent_gap_finder.workers.celery_app worker --loglevel=info --concurrency=2
```

### Required Railway environment variables
```
DATABASE_URL=postgresql+asyncpg://<railway-postgres-url>
REDIS_URL=redis://<railway-redis-url>
QDRANT_URL=http://<qdrant-service-name>:6333
EPO_CONSUMER_KEY=...
EPO_CONSUMER_SECRET=...
MCP_API_KEY=<openssl rand -hex 32>
PYTHONPATH=/app/src
LOG_LEVEL=INFO
```

### Claude Desktop config for deployed server
```json
{
  "mcpServers": {
    "patent-gap-finder": {
      "type": "http",
      "url": "https://your-app.railway.app",
      "headers": {
        "Authorization": "Bearer your_mcp_api_key"
      }
    }
  }
}
```

---

## Common Errors & Fixes

| Error | Cause | Fix |
|-------|-------|-----|
| `spawn uv ENOENT` | uv not in PATH for Claude Desktop | Use full path: `which uv` |
| `ModuleNotFoundError: patent_gap_finder` | Wrong PYTHONPATH | Set `PYTHONPATH=/app/src` or reinstall with `uv sync --reinstall` |
| `Connection refused (Postgres)` | Docker not running | `docker compose up -d postgres redis qdrant` |
| Tools don't appear in Claude Desktop | Config cached | Quit Claude Desktop fully (Cmd+Q), reopen |
| `MISSING` for env vars | .env not read by subprocess | Add all vars to `claude_desktop_config.json` env block |
| EPO returns 401 | Token expired or wrong credentials | Check EPO_CONSUMER_KEY/SECRET in .env |
| USPTO returns empty | Wrong query operator | Use `_begins` not `_eq` for IPC prefix |
| `alembic.util.exc.CommandError` | Migrations not run | `uv run alembic upgrade head` |
| Qdrant `+0 -0` on upsert | Points already exist (idempotent) | Normal behavior — not an error |

---

## Free Tier Limits

| Service | Limit | Usage per analysis | Daily capacity |
|---------|-------|--------------------|----------------|
| Claude Desktop | User's own plan | All reasoning | Unlimited for user |
| USPTO PatentsView | Unlimited | ~3 requests | Unlimited |
| EPO OPS | ~2,000 req/day | ~5 requests | ~400 analyses |
| SerpAPI | 100/month | 0–1 (fallback) | ~3/day |
| sentence-transformers | Local CPU | ~200 patents | Unlimited |
| HDBSCAN | Local CPU | 1 cluster run | Unlimited |

**Total cost to project owner: $0**

---

## Contribution Guide

### Branch naming
```
feat/tool-name        — new MCP tool
fix/component-name    — bug fix
refactor/module-name  — code improvement
docs/section-name     — documentation
test/module-name      — test additions
```

### Commit format
```
feat(tools): add export_report tool with base64 PDF output
fix(epo): handle single-result response as dict not list
refactor(embeddings): extract text_preparer into separate module
```

### Adding a new MCP tool
1. Create `src/patent_gap_finder/tools/your_tool.py`
2. Define an async function with typed parameters and docstring
3. Register it in `server.py`:
   ```python
   from patent_gap_finder.tools.your_tool import your_tool_handler
   mcp.tool()(your_tool_handler)
   ```
4. Add error codes to the error handling section in the tool
5. Write tests in `tests/test_your_tool.py`
6. Add to the MCP Tools table in this file and in README.md

### Never commit
- `.env` file
- API keys anywhere in source
- Model weights (`~/.cache/huggingface/`)
- Generated PDF reports
- `__pycache__` directories
- `.venv` directory

---

## Author

**Prashant Shukla**
Project: Research Paper → Patent Gap Finder
License: MIT
Repository: github.com/prashantshukla/Patent-MCP

---

*This file is the single source of truth for agents, contributors, and automated
systems working on this project. Keep it updated when architecture changes.*