"""arXiv paper parser — fetches metadata and PDF from arXiv.

Enforces a 3-second delay between requests to comply with arXiv's
rate-limiting policy. Supports bare arXiv IDs, abs URLs, and pdf URLs.
"""

from __future__ import annotations

import asyncio
import logging
import re
import xml.etree.ElementTree as ET
from typing import Optional

import httpx

from patent_gap_finder.models.paper import ParsedPaper
from patent_gap_finder.parsers.pdf_parser import parse_pdf

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────
# Constants
# ──────────────────────────────────────────────────────────────────────

_ARXIV_API_BASE = "https://export.arxiv.org/api/query"
_ARXIV_PDF_BASE = "https://arxiv.org/pdf"
_ARXIV_ABS_BASE = "https://arxiv.org/abs"

# Rate-limit: wait at least 3 seconds between arXiv requests
_REQUEST_DELAY_SECONDS = 3.0

# Atom XML namespace
_ATOM_NS = "http://www.w3.org/2005/Atom"

# Regex patterns for arXiv ID extraction
_ARXIV_ID_PATTERNS: list[re.Pattern[str]] = [
    # New-style: 2301.07041 or 2301.07041v2
    re.compile(r"(?:^|/)(\d{4}\.\d{4,5}(?:v\d+)?)(?:\.pdf)?$"),
    # Old-style: hep-ph/9905221 or math.AG/0601001v1
    re.compile(r"(?:^|/)([a-z-]+(?:\.[A-Z]{2})?/\d{7}(?:v\d+)?)(?:\.pdf)?$"),
]

# Timeout for HTTP requests (seconds)
_HTTP_TIMEOUT = 30.0

# Track the last request time for rate limiting
_last_request_time: float = 0.0
_rate_limit_lock = asyncio.Lock()


# ──────────────────────────────────────────────────────────────────────
# arXiv ID normalization
# ──────────────────────────────────────────────────────────────────────

def extract_arxiv_id(source: str) -> str:
    """Extract a normalized arXiv ID from a URL, path, or bare ID.

    Handles these formats:
      - ``2301.07041``
      - ``2301.07041v2``
      - ``https://arxiv.org/abs/2301.07041``
      - ``https://arxiv.org/pdf/2301.07041``
      - ``https://arxiv.org/pdf/2301.07041v2.pdf``
      - ``hep-ph/9905221``

    Args:
        source: The input string.

    Returns:
        Normalized arXiv ID (e.g. ``"2301.07041"``).

    Raises:
        ValueError: If no valid arXiv ID can be extracted.
    """
    source = source.strip()

    for pattern in _ARXIV_ID_PATTERNS:
        match = pattern.search(source)
        if match:
            return match.group(1)

    raise ValueError(
        f"Could not extract arXiv ID from: {source!r}. "
        "Expected formats: '2301.07041', 'https://arxiv.org/abs/2301.07041', etc."
    )


def is_arxiv_source(source: str) -> bool:
    """Check whether *source* looks like an arXiv reference.

    Returns True for arXiv URLs, arXiv IDs, or strings containing 'arxiv'.

    Args:
        source: The input string.

    Returns:
        True if *source* is likely an arXiv reference.
    """
    source_lower = source.lower().strip()

    if "arxiv.org" in source_lower or "arxiv" in source_lower:
        return True

    # Check if it matches the arXiv ID pattern directly
    for pattern in _ARXIV_ID_PATTERNS:
        if pattern.search(source):
            return True

    return False


# ──────────────────────────────────────────────────────────────────────
# Rate-limited HTTP helper
# ──────────────────────────────────────────────────────────────────────

async def _rate_limited_request(
    client: httpx.AsyncClient,
    url: str,
    **kwargs,
) -> httpx.Response:
    """Make an HTTP GET request with arXiv rate limiting.

    Ensures at least 3 seconds have elapsed since the last request
    to comply with arXiv's API policy.

    Args:
        client: An httpx async client.
        url: The URL to request.
        **kwargs: Additional arguments passed to ``client.get()``.

    Returns:
        The HTTP response.

    Raises:
        httpx.HTTPStatusError: On non-2xx responses.
        httpx.TimeoutException: On timeout.
    """
    global _last_request_time

    async with _rate_limit_lock:
        loop = asyncio.get_event_loop()
        now = loop.time()
        elapsed = now - _last_request_time
        if elapsed < _REQUEST_DELAY_SECONDS:
            await asyncio.sleep(_REQUEST_DELAY_SECONDS - elapsed)
        _last_request_time = asyncio.get_event_loop().time()

    response = await client.get(url, **kwargs)
    response.raise_for_status()
    return response


# ──────────────────────────────────────────────────────────────────────
# arXiv API metadata fetching
# ──────────────────────────────────────────────────────────────────────

def _parse_atom_entry(xml_text: str) -> dict:
    """Parse an Atom XML response from the arXiv API.

    Args:
        xml_text: Raw XML response body.

    Returns:
        Dict with ``title``, ``authors``, ``abstract``, ``categories``,
        and ``arxiv_id`` keys.

    Raises:
        ValueError: If the response contains no entries or is malformed.
    """
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        raise ValueError(f"Failed to parse arXiv API response: {e}") from e

    entries = root.findall(f"{{{_ATOM_NS}}}entry")
    if not entries:
        raise ValueError("arXiv API returned no entries. The paper may not exist.")

    entry = entries[0]

    # Title
    title_elem = entry.find(f"{{{_ATOM_NS}}}title")
    title = title_elem.text.strip() if title_elem is not None and title_elem.text else ""
    # Normalize whitespace in title
    title = re.sub(r"\s+", " ", title)

    # Check for "Error" in title (arXiv returns errors as entries)
    if title.lower().startswith("error"):
        summary_elem = entry.find(f"{{{_ATOM_NS}}}summary")
        error_msg = summary_elem.text.strip() if summary_elem is not None and summary_elem.text else "Unknown error"
        raise ValueError(f"arXiv API error: {error_msg}")

    # Authors
    authors: list[str] = []
    for author_elem in entry.findall(f"{{{_ATOM_NS}}}author"):
        name_elem = author_elem.find(f"{{{_ATOM_NS}}}name")
        if name_elem is not None and name_elem.text:
            authors.append(name_elem.text.strip())

    # Summary (abstract)
    summary_elem = entry.find(f"{{{_ATOM_NS}}}summary")
    abstract = summary_elem.text.strip() if summary_elem is not None and summary_elem.text else ""
    abstract = re.sub(r"\s+", " ", abstract)

    # Categories
    categories: list[str] = []
    for cat in entry.findall("{http://arxiv.org/schemas/atom}primary_category"):
        term = cat.get("term")
        if term:
            categories.append(term)
    for cat in entry.findall(f"{{{_ATOM_NS}}}category"):
        term = cat.get("term")
        if term and term not in categories:
            categories.append(term)

    # Extract arXiv ID from the entry ID URL
    id_elem = entry.find(f"{{{_ATOM_NS}}}id")
    arxiv_url = id_elem.text.strip() if id_elem is not None and id_elem.text else ""
    try:
        arxiv_id = extract_arxiv_id(arxiv_url)
    except ValueError:
        arxiv_id = ""

    return {
        "title": title,
        "authors": authors,
        "abstract": abstract,
        "categories": categories,
        "arxiv_id": arxiv_id,
    }


async def fetch_arxiv_metadata(arxiv_id: str) -> dict:
    """Fetch metadata for a paper from the arXiv API.

    Args:
        arxiv_id: A normalized arXiv ID (e.g. ``"2301.07041"``).

    Returns:
        Dict with ``title``, ``authors``, ``abstract``, ``categories``,
        and ``arxiv_id`` keys.

    Raises:
        ValueError: If the API returns an error or no results.
        httpx.HTTPStatusError: On non-2xx responses.
    """
    # Strip version suffix for API query (API returns latest by default)
    base_id = re.sub(r"v\d+$", "", arxiv_id)
    url = f"{_ARXIV_API_BASE}?id_list={base_id}"

    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
        response = await _rate_limited_request(client, url)
        return _parse_atom_entry(response.text)


# ──────────────────────────────────────────────────────────────────────
# PDF download
# ──────────────────────────────────────────────────────────────────────

async def download_arxiv_pdf(arxiv_id: str) -> bytes:
    """Download the PDF of an arXiv paper.

    Uses streaming download with rate limiting.

    Args:
        arxiv_id: A normalized arXiv ID.

    Returns:
        Raw PDF bytes.

    Raises:
        httpx.HTTPStatusError: On non-2xx responses.
        ValueError: If the downloaded content is too small or not a PDF.
    """
    # Strip version suffix — arXiv serves the latest version by default
    url = f"{_ARXIV_PDF_BASE}/{arxiv_id}"

    async with httpx.AsyncClient(
        timeout=_HTTP_TIMEOUT,
        follow_redirects=True,
    ) as client:
        response = await _rate_limited_request(client, url)

    pdf_bytes = response.content

    # Sanity check
    if len(pdf_bytes) < 1000:
        raise ValueError(
            f"Downloaded PDF is suspiciously small ({len(pdf_bytes)} bytes). "
            f"arXiv ID '{arxiv_id}' may not exist or may not have a PDF."
        )

    if not pdf_bytes[:5] == b"%PDF-":
        raise ValueError(
            "Downloaded content does not appear to be a valid PDF file."
        )

    return pdf_bytes


# ──────────────────────────────────────────────────────────────────────
# Full pipeline
# ──────────────────────────────────────────────────────────────────────

async def parse_arxiv(
    source: str,
    *,
    top_n_claims: int = 10,
) -> ParsedPaper:
    """Parse an arXiv paper into a structured :class:`ParsedPaper`.

    Fetches metadata from the arXiv API, downloads the PDF, parses it
    with the PDF parser, and merges the metadata. Respects arXiv's
    3-second rate limit between requests.

    Args:
        source: An arXiv ID, abs URL, or pdf URL.
        top_n_claims: Number of top candidate claims to return.

    Returns:
        A fully populated :class:`ParsedPaper` object.

    Raises:
        ValueError: On invalid arXiv IDs or download failures.
    """
    arxiv_id = extract_arxiv_id(source)
    source_url = f"{_ARXIV_ABS_BASE}/{arxiv_id}"

    logger.info("Fetching arXiv metadata for %s", arxiv_id)
    metadata = await fetch_arxiv_metadata(arxiv_id)

    logger.info("Downloading PDF for %s", arxiv_id)
    pdf_bytes = await download_arxiv_pdf(arxiv_id)

    logger.info("Parsing PDF for %s (%d bytes)", arxiv_id, len(pdf_bytes))
    parsed = parse_pdf(pdf_bytes, extract_tables=False, top_n_claims=top_n_claims)

    # Merge arXiv metadata (it's usually more reliable than PDF extraction)
    if metadata["title"]:
        parsed.title = metadata["title"]
    if metadata["authors"]:
        parsed.authors = metadata["authors"]
    if metadata["abstract"]:
        parsed.abstract = metadata["abstract"]

    parsed.source_url = source_url

    return parsed
