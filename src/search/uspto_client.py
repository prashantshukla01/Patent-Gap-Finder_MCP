"""Async Lens.org patent search client (replaces defunct PatentsView API).

The original USPTO PatentsView API (search.patentsview.org) was permanently
shut down on March 20, 2026 and migrated to data.uspto.gov, which does not
yet provide a stable programmatic search endpoint.

Lens.org provides equivalent global patent coverage (USPTO + EPO + PCT) with:
  - Free tier: 10,000 requests/month (no key required for basic search)
  - Authenticated tier: higher limits via LENS_API_KEY in .env
  - IPC/CPC classification filtering
  - Full-text search on title + abstract

Output dicts are shaped to match the existing normalize_uspto() expectations:
  patent_number, patent_title, patent_abstract, patent_date,
  inventor_first_name, inventor_last_name, assignee_organization,
  ipc_code, cpc_code
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

# ── Custom exceptions ────────────────────────────────────────────────


class USPTOTimeoutError(Exception):
    """Lens.org API timed out after retries."""


class USPTOAPIError(Exception):
    """Non-retryable Lens.org API error."""


# ── Client ───────────────────────────────────────────────────────────

BASE_URL = "https://api.lens.org/patent/search"

# Lens.org rate limit: 10 req/s authenticated, ~2 req/s anonymous
_semaphore = asyncio.Semaphore(2)


def _build_query(keywords: list[str], ipc_codes: list[str]) -> dict:
    """Build a Lens.org patent search query.

    Args:
        keywords: Search terms for title/abstract text search.
        ipc_codes: IPC classification codes (e.g. 'G06N', 'G06N 3/08').

    Returns:
        Lens.org query dict (Elasticsearch query DSL).
    """
    must_clauses = []

    if keywords:
        keyword_text = " ".join(keywords[:10])
        must_clauses.append({
            "query_string": {
                "query": keyword_text,
                "fields": ["title", "abstract"],
                "default_operator": "OR",
            }
        })

    if ipc_codes:
        # Extract section+class prefix (e.g. "G06N 3/08" → "G06N")
        ipc_prefixes = list({code.split()[0] for code in ipc_codes if code.strip()})
        if len(ipc_prefixes) == 1:
            must_clauses.append({
                "term": {"classifications_ipcr.symbol": ipc_prefixes[0]}
            })
        elif ipc_prefixes:
            must_clauses.append({
                "bool": {
                    "should": [
                        {"prefix": {"classifications_ipcr.symbol": p}}
                        for p in ipc_prefixes
                    ],
                    "minimum_should_match": 1,
                }
            })

    if not must_clauses:
        raise ValueError("At least one of keywords or ipc_codes must be provided")

    if len(must_clauses) == 1:
        return must_clauses[0]
    return {"bool": {"must": must_clauses}}


def _map_to_patentsview_shape(hit: dict) -> dict:
    """Map a Lens.org patent record to the shape normalize_uspto() expects.

    normalize_uspto() reads these fields:
      patent_number, patent_title, patent_abstract, patent_date,
      inventor_first_name (list), inventor_last_name (list),
      assignee_organization, ipc_code (list), cpc_code (list)
    """
    # Patent number: prefer US number, fall back to lens_id
    lens_id = hit.get("lens_id", "")
    pub_refs = hit.get("publication_references", [])
    patent_number = lens_id  # fallback
    for ref in pub_refs:
        if ref.get("jurisdiction") == "US":
            patent_number = ref.get("doc_number", lens_id)
            break

    # Inventors
    inventor_first: list[str] = []
    inventor_last: list[str] = []
    for inv in hit.get("inventors", []):
        name = inv.get("name", "")
        parts = name.rsplit(" ", 1)
        if len(parts) == 2:
            inventor_first.append(parts[0])
            inventor_last.append(parts[1])
        elif parts:
            inventor_first.append("")
            inventor_last.append(parts[0])

    # Assignees
    assignees = hit.get("assignees", [])
    assignee_org = assignees[0].get("name", "") if assignees else ""

    # IPC codes
    ipc_codes = []
    for cls in hit.get("classifications_ipcr", []):
        sym = cls.get("symbol", "").strip()
        if sym:
            ipc_codes.append(sym)

    # CPC codes
    cpc_codes = []
    for cls in hit.get("classifications_cpc", []):
        sym = cls.get("symbol", "").strip()
        if sym:
            cpc_codes.append(sym)

    # Publication date: prefer granted date, fall back to published date
    pub_date = (
        hit.get("date_published")
        or hit.get("publication_type", {}).get("date_published")
        or ""
    )

    return {
        "patent_number": patent_number,
        "patent_title": hit.get("title", ""),
        "patent_abstract": hit.get("abstract", ""),
        "patent_date": pub_date[:10] if pub_date else "",  # YYYY-MM-DD
        "inventor_first_name": inventor_first,
        "inventor_last_name": inventor_last,
        "assignee_organization": assignee_org,
        "ipc_code": ipc_codes,
        "cpc_code": cpc_codes,
    }


async def search(
    keywords: list[str],
    ipc_codes: list[str],
    max_results: int = 100,
) -> list[dict]:
    """Search Lens.org for patents matching keywords + IPC codes.

    Requires a free Lens.org API key:
      1. Register at https://www.lens.org/lens/user/apikey
      2. Add LENS_API_KEY=<your-key> to .env

    Automatically paginates up to *max_results* patents.

    Args:
        keywords: Search terms for title/abstract text search.
        ipc_codes: IPC classification codes.
        max_results: Maximum number of patents to return.

    Returns:
        List of raw patent dicts (shaped like PatentsView output).
        Returns empty list when no API key is configured.

    Raises:
        USPTOTimeoutError: On connection timeout after retries.
        USPTOAPIError: On non-retryable server errors.
    """
    api_key = os.environ.get("LENS_API_KEY") or os.environ.get("USPTO_API_KEY", "")
    if not api_key:
        logger.warning(
            "LENS_API_KEY not set — skipping Lens.org (USPTO) search. "
            "Register free at https://www.lens.org/lens/user/apikey and add "
            "LENS_API_KEY to .env. EPO + SerpAPI will cover this gap."
        )
        return []

    query = _build_query(keywords, ipc_codes)

    all_patents: list[dict] = []
    page_size = min(50, max_results)
    from_offset = 0

    headers: dict[str, str] = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    async with httpx.AsyncClient(
        timeout=httpx.Timeout(60.0, connect=10.0)
    ) as client:
        while len(all_patents) < max_results:
            body = {
                "query": query,
                "size": page_size,
                "from": from_offset,
                "sort": [{"date_published": "desc"}],
                "include": [
                    "lens_id",
                    "title",
                    "abstract",
                    "date_published",
                    "inventors",
                    "assignees",
                    "classifications_ipcr",
                    "classifications_cpc",
                    "publication_references",
                ],
            }

            async with _semaphore:
                try:
                    response = await _make_request(client, body, headers)
                except USPTOTimeoutError:
                    if from_offset == 0:
                        raise
                    logger.warning(
                        "Lens.org timeout at offset %d, returning partial results",
                        from_offset,
                    )
                    break

                # Rate-limit gap (anonymous: ~0.5 req/s)
                await asyncio.sleep(0.5 if api_key else 1.5)

            data = response.json()
            hits = data.get("data", [])
            total = data.get("total", {})
            total_count = total.get("value", 0) if isinstance(total, dict) else int(total or 0)

            if not hits:
                break

            mapped = [_map_to_patentsview_shape(h) for h in hits]
            all_patents.extend(mapped)

            logger.info(
                "Lens.org offset %d: %d patents (total available: %d)",
                from_offset,
                len(hits),
                total_count,
            )

            if len(all_patents) >= max_results:
                break
            if from_offset + page_size >= total_count:
                break

            from_offset += page_size

    return all_patents[:max_results]


async def _make_request(
    client: httpx.AsyncClient,
    body: dict,
    headers: dict,
    retries: int = 2,
) -> httpx.Response:
    """Make a single Lens.org request with retry logic.

    Retries on 429 (rate limit) with 60s wait and on 5xx with backoff.

    Raises:
        USPTOTimeoutError: On connection/read timeout.
        USPTOAPIError: On non-retryable errors.
    """
    for attempt in range(retries + 1):
        try:
            response = await client.post(BASE_URL, json=body, headers=headers)

            if response.status_code == 200:
                return response

            if response.status_code == 429:
                if attempt < retries:
                    logger.warning(
                        "Lens.org 429 rate limited, waiting 60s (attempt %d/%d)",
                        attempt + 1, retries + 1,
                    )
                    await asyncio.sleep(60)
                    continue
                raise USPTOAPIError(
                    f"Lens.org rate limited after {retries + 1} attempts"
                )

            if response.status_code == 401:
                # Anonymous access may be restricted — log and raise
                raise USPTOAPIError(
                    "Lens.org requires authentication. "
                    "Set LENS_API_KEY from https://www.lens.org/lens/user/apikey"
                )

            if response.status_code >= 500:
                if attempt < retries:
                    wait = 5 * (attempt + 1)
                    logger.warning(
                        "Lens.org %d error, retrying in %ds",
                        response.status_code, wait,
                    )
                    await asyncio.sleep(wait)
                    continue
                raise USPTOAPIError(
                    f"Lens.org server error {response.status_code}: {response.text[:200]}"
                )

            raise USPTOAPIError(
                f"Lens.org error {response.status_code}: {response.text[:200]}"
            )

        except httpx.TimeoutException as e:
            if attempt < retries:
                logger.warning(
                    "Lens.org timeout, retrying (attempt %d/%d)",
                    attempt + 1, retries + 1,
                )
                await asyncio.sleep(5)
                continue
            raise USPTOTimeoutError(
                f"Lens.org timed out after {retries + 1} attempts"
            ) from e
