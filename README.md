# Patent Gap Finder — MCP Server

An **MCP (Model Context Protocol) server** that analyzes research papers to discover patentable white-space opportunities. Submit a PDF or arXiv URL, and the system extracts structured content, identifies candidate technical claims, and (in future phases) maps them against the existing patent landscape to find novel, patentable gaps.

**Phase 1** provides the foundation: paper parsing, section detection, metadata extraction, and heuristic-based candidate claim identification — all exposed as MCP tools that Claude Desktop or any MCP client can call directly.

---

## Prerequisites

- **Python 3.11+**
- **[uv](https://docs.astral.sh/uv/)** — fast Python package manager

```bash
# Install uv if you don't have it
curl -LsSf https://astral.sh/uv/install.sh | sh
```

## Installation

```bash
# Clone the repository
git clone <repo-url> patent-gap-finder
cd patent-gap-finder

# Install dependencies
uv sync --all-extras
```

## Running the MCP Server

### stdio transport (Claude Desktop)

```bash
uv run python -m patent_gap_finder.server
```

### streamable-http transport (web clients)

```bash
MCP_TRANSPORT=streamable-http MCP_PORT=8000 uv run python -m patent_gap_finder.server
```

## Connecting to Claude Desktop

Add this to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "patent-gap-finder": {
      "command": "uv",
      "args": [
        "run",
        "--directory", "/absolute/path/to/patent-gap-finder",
        "python", "-m", "patent_gap_finder.server"
      ]
    }
  }
}
```

> **Note:** Replace `/absolute/path/to/patent-gap-finder` with the actual path to this project.

## Available Tools

### `parse_paper`

Parse a research paper from a local PDF file or arXiv reference.

**Input:** `source` (string) — a file path or arXiv ID/URL

**Supported formats:**
- Local PDF: `/path/to/paper.pdf`
- arXiv ID: `2301.07041`
- arXiv URL: `https://arxiv.org/abs/2301.07041`

### Example Usage

In Claude Desktop, after connecting the server:

```
Please parse this paper and identify potential patent claims:

parse_paper("2301.07041")
```

**Sample output (truncated):**

```json
{
  "title": "Attention Is All You Need",
  "authors": ["Ashish Vaswani", "Noam Shazeer", "..."],
  "abstract": "The dominant sequence transduction models...",
  "sections": [
    {
      "title": "Introduction",
      "content": "Recurrent neural networks...",
      "section_type": "introduction"
    }
  ],
  "candidate_claims": [
    {
      "text": "We propose a new simple network architecture, the Transformer, based solely on attention mechanisms.",
      "source_section": "Introduction",
      "claim_type": "system",
      "confidence": 0.78
    }
  ],
  "source_url": "https://arxiv.org/abs/1706.03762",
  "file_hash": "a1b2c3d4...",
  "parsed_at": "2025-01-15T10:30:00Z"
}
```

## Running Tests

```bash
# Run all tests
uv run pytest tests/ -v

# Run only PDF parser tests (no network needed after first run)
uv run pytest tests/test_pdf_parser.py -v

# Run arXiv tests (requires network)
uv run pytest tests/test_arxiv_parser.py -v
```

## Project Structure

```
patent_gap_finder/
├── pyproject.toml
├── .env.example
├── README.md
├── src/
│   └── patent_gap_finder/
│       ├── server.py           # FastMCP server entrypoint
│       ├── tools/
│       │   └── parse_paper.py  # parse_paper MCP tool
│       ├── parsers/
│       │   ├── pdf_parser.py   # PyMuPDF + pdfplumber parser
│       │   └── arxiv_parser.py # arXiv API fetcher
│       ├── models/
│       │   └── paper.py        # Pydantic schemas
│       └── utils/
│           └── text_utils.py   # Sentence splitting, claim scoring
└── tests/
    ├── test_pdf_parser.py
    └── test_arxiv_parser.py
```

## Roadmap

| Phase | Scope | Status |
|-------|-------|--------|
| **1** | Project scaffold, PDF parsing, arXiv integration | ✅ Complete |
| **2** | AI claim extraction (Claude), IPC classification | 🔜 Planned |
| **3** | USPTO/EPO/Google Patents search, Redis caching | 🔜 Planned |
| **4** | Embedding, HDBSCAN clustering, gap detection | 🔜 Planned |
| **5** | Claim drafting, PDF reports, deployment | 🔜 Planned |

## License

MIT
