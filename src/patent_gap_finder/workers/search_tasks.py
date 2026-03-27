"""Celery task that wraps the async search coordinator.

Celery workers run synchronously — this module bridges the sync/async
boundary by creating a fresh event loop for each task invocation.
Uses sync SQLAlchemy (psycopg2) for DB updates inside the worker.
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone

from sqlalchemy import create_engine, update
from sqlalchemy.orm import sessionmaker

from patent_gap_finder.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


def _get_sync_session():
    """Create a sync SQLAlchemy session for Celery worker DB access."""
    db_url = os.environ.get("DATABASE_URL", "")
    # Convert async URL to sync
    sync_url = db_url.replace("+asyncpg", "+psycopg2")
    if not sync_url:
        sync_url = "sqlite:///patent_gap_finder.db"
    engine = create_engine(sync_url)
    Session = sessionmaker(bind=engine)
    return Session()


def _update_job_status_sync(job_id: str, status: str, error: str = None) -> None:
    """Update SearchJob status using sync DB session."""
    try:
        from patent_gap_finder.db.models import SearchJob
        session = _get_sync_session()
        try:
            values = {
                "status": status,
            }
            if error:
                values["error_message"] = error
            if status in ("complete", "failed"):
                values["completed_at"] = datetime.now(timezone.utc)

            session.execute(
                update(SearchJob)
                .where(SearchJob.id == job_id)
                .values(**values)
            )
            session.commit()
        finally:
            session.close()
    except Exception as e:
        logger.error("Failed to update job %s status to %s: %s", job_id, status, e)


@celery_app.task(
    bind=True,
    name="search_prior_art_task",
    max_retries=2,
    default_retry_delay=30,
)
def run_patent_search(
    self,
    session_id: str,
    job_id: str,
    keywords: list,
    ipc_codes: list,
) -> dict:
    """Execute patent search across all sources.

    This Celery task bridges the sync Celery worker to the async search
    coordinator by creating a dedicated event loop.

    Args:
        session_id: UUID of the analysis session.
        job_id: UUID of the search job.
        keywords: Search terms from Phase 2.
        ipc_codes: IPC codes from Phase 2.

    Returns:
        Dict with job_id, session_id, patent_count, and status.
    """
    logger.info(
        "Starting patent search task job=%s session=%s keywords=%d ipc=%d",
        job_id, session_id, len(keywords), len(ipc_codes),
    )

    # Mark job as running
    _update_job_status_sync(job_id, "running")

    try:
        # Create a fresh event loop for the async coordinator
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        try:
            from patent_gap_finder.search.search_coordinator import coordinate_search

            result = loop.run_until_complete(
                coordinate_search(
                    keywords=keywords,
                    ipc_codes=ipc_codes,
                    session_id=session_id,
                    job_id=job_id,
                )
            )
        finally:
            loop.close()

        # Mark job as complete
        _update_job_status_sync(job_id, "complete")

        return {
            "job_id": job_id,
            "session_id": session_id,
            "patent_count": result.total_found,
            "status": "complete",
        }

    except Exception as exc:
        logger.exception("Patent search task failed: %s", exc)
        _update_job_status_sync(job_id, "failed", str(exc))

        # Retry on certain recoverable errors
        from patent_gap_finder.search.epo_client import EPOQuotaError
        from patent_gap_finder.search.uspto_client import USPTOTimeoutError

        if isinstance(exc, (USPTOTimeoutError, EPOQuotaError)):
            raise self.retry(exc=exc, countdown=30)

        return {
            "job_id": job_id,
            "session_id": session_id,
            "patent_count": 0,
            "status": "failed",
            "error": str(exc),
        }
