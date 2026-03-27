"""Async USPTO PatentsView API client.

Base URL: https://search.patentsview.org/api/v1/patent/
Free tier: 45 req/min (no key).  With optional USPTO_API_KEY: higher limits.
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
    """USPTO API timed out after retries."""


class USPTOAPIError(Exception):
    """Non-retryable USPTO API error."""


# ── Client ───────────────────────────────────────────────────────────

BASE_URL = "https://search.patentsview.org/api/v1/patent/"

# Rate limit: 45 req/min → 1 concurrent + 1.4s gap
_semaphore = asyncio.Semaphore(1)

FIELDS = [
    "patent_id",
    "patent_title",
    "patent_abstract",
    "patent_date",
    "patent_number",
    "assignee_organization",
    "ipc_code",
    "cpc_code",
    "inventor_last_name",
    "inventor_first_name",
]


def _build_query(keywords: list[str], ipc_codes: list[str]) -> dict:
    """Build a PatentsView query combining keyword + IPC filters.

    Args:
        keywords: Search terms for abstract text search.
        ipc_codes: IPC codes to filter (prefix match).

    Returns:
        PatentsView query dict.
    """
    conditions = []

    if keywords:
        keyword_text = " ".join(keywords[:10])
        conditions.append(
            {"_text_any": {"patent_abstract": keyword_text}}
        )

    if ipc_codes:
        # Extract section+class prefix (e.g. "G06N 3/08" → "G06N")
        ipc_prefixes = list({code.split()[0] for code in ipc_codes if code.strip()})
        if len(ipc_prefixes) == 1:
            conditions.append({"_eq": {"ipc_code": ipc_prefixes[0]}})
        elif ipc_prefixes:
            conditions.append(
                {"_or": [{"_eq": {"ipc_code": p}} for p in ipc_prefixes]}
            )

    if not conditions:
        raise ValueError("At least one of keywords or ipc_codes must be provided")

    if len(conditions) == 1:
        return conditions[0]
    return {"_and": conditions}


async def search(
    keywords: list[str],
    ipc_codes: list[str],
    max_results: int = 100,
) -> list[dict]:
    """Search USPTO PatentsView for patents matching keywords + IPC codes.

    Automatically paginates up to *max_results* patents.  Respects the
    45 req/min rate limit via a semaphore + sleep.

    Args:
        keywords: Search terms for abstract text search.
        ipc_codes: IPC classification codes.
        max_results: Maximum number of patents to return.

    Returns:
        List of raw patent dicts from the API.

    Raises:
        USPTOTimeoutError: On connection timeout after retries.
        USPTOAPIError: On non-retryable server errors.
    """
    query = _build_query(keywords, ipc_codes)
    api_key = os.environ.get("USPTO_API_KEY")

    all_patents: list[dict] = []
    page = 1
    per_page = min(50, max_results)

    headers = {}
    if api_key:
        headers["X-Api-Key"] = api_key

    async with httpx.AsyncClient(timeout=30.0) as client:
        while len(all_patents) < max_results:
            body = {
                "q": query,
                "f": FIELDS,
                "o": {"per_page": per_page, "page": page},
                "s": [{"patent_date": "desc"}],
            }

            async with _semaphore:
                try:
                    response = await _make_request(client, body, headers)
                except USPTOTimeoutError:
                    if page == 1:
                        raise
                    logger.warning("USPTO timeout on page %d, returning partial results", page)
                    break

                # Enforce rate limit gap
                await asyncio.sleep(1.4)

            data = response.json()

            patents = data.get("patents", [])
            total_count = data.get("total_patent_count", 0)

            if not patents:
                break

            all_patents.extend(patents)
            logger.info(
                "USPTO page %d: %d patents (total available: %d)",
                page, len(patents), total_count,
            )

            # Stop conditions
            if len(all_patents) >= max_results:
                break
            if page * per_page >= total_count:
                break

            page += 1

    return all_patents[:max_results]


async def _make_request(
    client: httpx.AsyncClient,
    body: dict,
    headers: dict,
    retries: int = 2,
) -> httpx.Response:
    """Make a single USPTO request with retry logic.

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
                        "USPTO 429 rate limited, waiting 60s (attempt %d/%d)",
                        attempt + 1, retries + 1,
                    )
                    await asyncio.sleep(60)
                    continue
                raise USPTOAPIError(f"USPTO rate limited after {retries + 1} attempts")

            if response.status_code >= 500:
                if attempt < retries:
                    wait = 5 * (attempt + 1)
                    logger.warning(
                        "USPTO %d error, retrying in %ds",
                        response.status_code, wait,
                    )
                    await asyncio.sleep(wait)
                    continue
                raise USPTOAPIError(
                    f"USPTO server error {response.status_code}: {response.text[:200]}"
                )

            raise USPTOAPIError(
                f"USPTO error {response.status_code}: {response.text[:200]}"
            )

        except httpx.TimeoutException as e:
            if attempt < retries:
                logger.warning("USPTO timeout, retrying (attempt %d/%d)", attempt + 1, retries + 1)
                await asyncio.sleep(5)
                continue
            raise USPTOTimeoutError(f"USPTO timed out after {retries + 1} attempts") from e
