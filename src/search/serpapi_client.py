"""SerpAPI Google Patents client — fallback only.

Used when USPTO + EPO combined return fewer than 30 results.
Free tier: 100 searches/month — used sparingly.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

BASE_URL = "https://serpapi.com/search.json"

# Rate limit: 1 req/sec (conservative for free tier)
_semaphore = asyncio.Semaphore(1)


def is_available() -> bool:
    """Check whether SerpAPI key is configured."""
    return bool(os.environ.get("SERPAPI_KEY", ""))


async def search(
    keywords: list[str],
    max_results: int = 20,
) -> list[dict]:
    """Search Google Patents via SerpAPI.

    Args:
        keywords: Search terms (limited to first 8).
        max_results: Maximum results (capped at 20 for free tier).

    Returns:
        List of raw patent dicts from SerpAPI.
    """
    api_key = os.environ.get("SERPAPI_KEY", "")
    if not api_key:
        logger.warning("SERPAPI_KEY not set — skipping Google Patents search")
        return []

    query = " ".join(keywords[:8])
    all_patents: list[dict] = []
    max_results = min(max_results, 20)
    num_per_page = 10

    async with httpx.AsyncClient(timeout=30.0) as client:
        pages = (max_results + num_per_page - 1) // num_per_page

        for page_num in range(pages):
            if len(all_patents) >= max_results:
                break

            params = {
                "engine": "google_patents",
                "q": query,
                "api_key": api_key,
                "num": num_per_page,
            }

            if page_num > 0:
                params["start"] = page_num * num_per_page

            async with _semaphore:
                try:
                    response = await client.get(BASE_URL, params=params)
                    response.raise_for_status()
                except httpx.HTTPStatusError as e:
                    if e.response.status_code == 429:
                        logger.warning("SerpAPI rate limited")
                        break
                    logger.error("SerpAPI error: %s", e)
                    break
                except httpx.TimeoutException:
                    logger.warning("SerpAPI timeout")
                    break

                await asyncio.sleep(1.0)

            data = response.json()
            results = data.get("organic_results", [])

            if not results:
                break

            for result in results:
                patent = {
                    "patent_id": result.get("patent_id", ""),
                    "title": result.get("title", ""),
                    "abstract": result.get("snippet", ""),
                    "inventors": result.get("inventor", ""),
                    "assignee": result.get("assignee", ""),
                    "publication_date": result.get("publication_date", ""),
                    "filing_date": result.get("filing_date", ""),
                    "pdf_url": result.get("pdf", ""),
                    "thumbnail": result.get("thumbnail", ""),
                }
                all_patents.append(patent)

            logger.info("SerpAPI page %d: %d results", page_num + 1, len(results))

    return all_patents[:max_results]
