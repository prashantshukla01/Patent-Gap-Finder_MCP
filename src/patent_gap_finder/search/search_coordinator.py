"""Search coordinator — orchestrates parallel search across all sources.

Checks Redis cache first, fires async searches for cache misses,
normalizes and deduplicates, then persists results.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Optional

from patent_gap_finder.cache.redis_client import get_redis_client, RedisClient
from patent_gap_finder.models.patent import Patent, PatentSearchResult
from patent_gap_finder.search import (
    epo_client as epo_mod,
    serpapi_client as serpapi_mod,
    uspto_client as uspto_mod,
)
from patent_gap_finder.search.normalizer import (
    build_search_result,
    normalize_epo,
    normalize_serpapi,
    normalize_uspto,
)

logger = logging.getLogger(__name__)


async def coordinate_search(
    keywords: list[str],
    ipc_codes: list[str],
    session_id: str,
    job_id: str,
) -> PatentSearchResult:
    """Run parallel patent search with caching, normalization, and persistence.

    Steps:
    1. Check Redis cache for each source
    2. Fire async searches for cache misses
    3. Handle per-source exceptions (never let one abort all)
    4. Cache successful results
    5. Conditionally call SerpAPI if total < 30
    6. Normalize + deduplicate
    7. Persist to DB

    Args:
        keywords: Search terms from Phase 2 classification.
        ipc_codes: IPC codes from Phase 2 classification.
        session_id: UUID of the parent analysis session.
        job_id: UUID of the search job.

    Returns:
        Aggregated PatentSearchResult.
    """
    start_time = time.monotonic()
    redis = get_redis_client()

    cache_hits: dict[str, bool] = {"uspto": False, "epo": False, "google_patents": False}

    # ── Step 1: Check caches ─────────────────────────────────────────

    uspto_key = RedisClient.build_patent_cache_key("uspto", keywords, ipc_codes)
    epo_key = RedisClient.build_patent_cache_key("epo", keywords, ipc_codes)

    uspto_cached = await redis.get_cached(uspto_key)
    epo_cached = await redis.get_cached(epo_key)

    # ── Step 2: Fire searches for cache misses ───────────────────────

    tasks: dict[str, asyncio.Task] = {}

    if uspto_cached:
        cache_hits["uspto"] = True
        logger.info("USPTO cache hit")
    else:
        tasks["uspto"] = asyncio.create_task(
            _safe_search("uspto", _search_uspto, keywords, ipc_codes)
        )

    if epo_cached:
        cache_hits["epo"] = True
        logger.info("EPO cache hit")
    else:
        tasks["epo"] = asyncio.create_task(
            _safe_search("epo", _search_epo, keywords, ipc_codes)
        )

    # Wait for all tasks
    if tasks:
        await asyncio.gather(*tasks.values())

    # ── Step 3: Collect results ──────────────────────────────────────

    # USPTO
    if uspto_cached:
        uspto_patents = [
            Patent(**p) for p in uspto_cached.get("patents", [])
        ]
    elif "uspto" in tasks:
        raw_result = tasks["uspto"].result()
        if raw_result is not None:
            uspto_patents = [normalize_uspto(p) for p in raw_result]
            # Cache successful results
            await redis.set_cached(
                uspto_key,
                {"patents": [p.model_dump(mode="json") for p in uspto_patents]},
            )
        else:
            uspto_patents = []
    else:
        uspto_patents = []

    # EPO
    if epo_cached:
        epo_patents = [
            Patent(**p) for p in epo_cached.get("patents", [])
        ]
    elif "epo" in tasks:
        raw_result = tasks["epo"].result()
        if raw_result is not None:
            epo_patents = [normalize_epo(p) for p in raw_result]
            await redis.set_cached(
                epo_key,
                {"patents": [p.model_dump(mode="json") for p in epo_patents]},
            )
        else:
            epo_patents = []
    else:
        epo_patents = []

    # ── Step 5: Conditional SerpAPI ──────────────────────────────────

    serpapi_patents: list[Patent] = []
    total_so_far = len(uspto_patents) + len(epo_patents)

    if total_so_far < 30 and serpapi_mod.is_available():
        logger.info(
            "Total so far: %d (< 30) — triggering SerpAPI fallback",
            total_so_far,
        )
        try:
            raw_serpapi = await serpapi_mod.search(keywords, max_results=20)
            serpapi_patents = [normalize_serpapi(p) for p in raw_serpapi]
            cache_hits["google_patents"] = False
        except Exception as e:
            logger.warning("SerpAPI search failed: %s", e)

    # ── Step 6: Build final result ───────────────────────────────────

    duration = time.monotonic() - start_time

    result = build_search_result(
        uspto_patents=uspto_patents,
        epo_patents=epo_patents,
        serpapi_patents=serpapi_patents,
        duration=duration,
        cache_hits=cache_hits,
        keywords=keywords,
        ipc_codes=ipc_codes,
    )

    # ── Step 7: Persist to DB ────────────────────────────────────────

    try:
        await _persist_results(session_id, job_id, result)
    except Exception as e:
        logger.error("Failed to persist search results: %s", e)

    logger.info(
        "Search complete: %d patents found (%d deduped) in %.1fs",
        result.total_found,
        result.deduplication_removed,
        result.search_duration_seconds,
    )

    return result


async def _safe_search(source: str, func, keywords, ipc_codes) -> Optional[list]:
    """Wrap a search function to catch and log exceptions."""
    try:
        return await func(keywords, ipc_codes)
    except Exception as e:
        logger.error("%s search failed: %s", source.upper(), e)
        return None


async def _search_uspto(keywords: list[str], ipc_codes: list[str]) -> list[dict]:
    """Run USPTO search."""
    return await uspto_mod.search(keywords, ipc_codes, max_results=100)


async def _search_epo(keywords: list[str], ipc_codes: list[str]) -> list[dict]:
    """Run EPO search."""
    client = epo_mod.get_epo_client()
    return await client.search(keywords, ipc_codes, max_results=100)


async def _persist_results(
    session_id: str, job_id: str, result: PatentSearchResult
) -> None:
    """Persist patents and update job/session in DB."""
    from patent_gap_finder.db.connection import get_db_session
    from patent_gap_finder.db.repositories import job_repo, patent_repo, session_repo

    async with get_db_session() as db:
        # Upsert patents
        inserted, skipped = await patent_repo.upsert_patents(db, result.patents)
        logger.info("Patents persisted: %d inserted, %d skipped", inserted, skipped)

        # Link patents to session
        patent_ids = await patent_repo.get_patent_db_ids_by_patent_ids(
            db, [p.patent_id for p in result.patents]
        )
        if patent_ids:
            await patent_repo.link_patents_to_session(db, session_id, patent_ids)

        # Update job
        await job_repo.update_job_results(db, job_id, {
            "result_count": result.total_found,
            "uspto_count": result.source_counts.get("uspto", 0),
            "epo_count": result.source_counts.get("epo", 0),
            "serpapi_count": result.source_counts.get("google_patents", 0),
            "dedup_removed": result.deduplication_removed,
            "cache_hit_uspto": result.cache_hits.get("uspto", False),
            "cache_hit_epo": result.cache_hits.get("epo", False),
            "duration_seconds": result.search_duration_seconds,
        })

        # Update session
        await session_repo.update_session_status(db, session_id, "search_complete")
