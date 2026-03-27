"""Repository for SearchJob CRUD operations."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from patent_gap_finder.db.models import SearchJob

logger = logging.getLogger(__name__)


async def create_job(
    db: AsyncSession,
    session_id: str,
    keywords: list,
    ipc_codes: list,
) -> SearchJob:
    """Create a pending search job."""
    job = SearchJob(
        session_id=session_id,
        status="pending",
        keywords_used=keywords,
        ipc_codes_searched=ipc_codes,
    )
    db.add(job)
    await db.flush()
    logger.info("Created search job %s for session %s", job.id, session_id)
    return job


async def update_job_celery_id(
    db: AsyncSession,
    job_id: str,
    celery_task_id: str,
) -> None:
    """Set the Celery task ID on a job."""
    await db.execute(
        update(SearchJob)
        .where(SearchJob.id == job_id)
        .values(celery_task_id=celery_task_id)
    )


async def update_job_status(
    db: AsyncSession,
    job_id: str,
    status: str,
    error: Optional[str] = None,
) -> None:
    """Update job status."""
    values = {"status": status}
    if error is not None:
        values["error_message"] = error
    if status in ("complete", "failed"):
        values["completed_at"] = datetime.now(timezone.utc)

    await db.execute(
        update(SearchJob).where(SearchJob.id == job_id).values(**values)
    )


async def update_job_results(
    db: AsyncSession,
    job_id: str,
    results: dict,
) -> None:
    """Update job with search result metrics."""
    values = {"completed_at": datetime.now(timezone.utc), "status": "complete"}

    for key in (
        "result_count", "uspto_count", "epo_count", "serpapi_count",
        "dedup_removed", "cache_hit_uspto", "cache_hit_epo", "duration_seconds",
    ):
        if key in results:
            values[key] = results[key]

    await db.execute(
        update(SearchJob).where(SearchJob.id == job_id).values(**values)
    )


async def get_job(
    db: AsyncSession,
    job_id: str,
) -> Optional[SearchJob]:
    """Retrieve a job by ID."""
    result = await db.execute(
        select(SearchJob).where(SearchJob.id == job_id)
    )
    return result.scalars().first()


async def get_latest_job_for_session(
    db: AsyncSession,
    session_id: str,
) -> Optional[SearchJob]:
    """Get the most recent search job for a session."""
    result = await db.execute(
        select(SearchJob)
        .where(SearchJob.session_id == session_id)
        .order_by(SearchJob.created_at.desc())
        .limit(1)
    )
    return result.scalars().first()
