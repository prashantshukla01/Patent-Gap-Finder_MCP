"""MCP tool for polling search job status.

Returns structured progress data from both the DB and Celery task state.
"""

from __future__ import annotations

import logging
from uuid import UUID

from patent_gap_finder.db.connection import get_db_session
from patent_gap_finder.db.repositories import job_repo

logger = logging.getLogger(__name__)


def _is_valid_uuid(value: str) -> bool:
    try:
        UUID(value)
        return True
    except (ValueError, AttributeError):
        return False


async def get_search_status(job_id: str) -> dict:
    """Retrieve the status of a patent search job.

    Args:
        job_id: UUID of the search job from search_prior_art.

    Returns:
        Structured status dict with progress and next step guidance.
    """
    job_id = job_id.strip()

    if not _is_valid_uuid(job_id):
        return {
            "error": "INVALID_JOB_ID",
            "message": f"'{job_id}' is not a valid UUID.",
            "job_id": job_id,
        }

    try:
        async with get_db_session() as db:
            job = await job_repo.get_job(db, job_id)
            if job is None:
                return {
                    "error": "JOB_NOT_FOUND",
                    "message": f"Search job {job_id} not found.",
                    "job_id": job_id,
                }

            # Try to get Celery task state
            celery_status = "UNKNOWN"
            if job.celery_task_id:
                try:
                    from patent_gap_finder.workers.celery_app import celery_app
                    from celery.result import AsyncResult
                    result = AsyncResult(job.celery_task_id, app=celery_app)
                    celery_status = result.state
                except Exception:
                    celery_status = "UNAVAILABLE"

            # Build next step guidance
            if job.status == "complete":
                next_step = (
                    "Search complete. Call get_session to see full results, "
                    "or proceed to Phase 4 (map_landscape) for gap analysis."
                )
            elif job.status == "failed":
                next_step = (
                    "Search failed. Check error message and retry with "
                    "search_prior_art if the issue is transient."
                )
            else:
                next_step = (
                    "Search in progress. Poll again in 10-15 seconds."
                )

            return {
                "job_id": job.id,
                "session_id": job.session_id,
                "status": job.status,
                "celery_status": celery_status,
                "progress": {
                    "patents_found": job.result_count,
                    "uspto_count": job.uspto_count,
                    "epo_count": job.epo_count,
                    "serpapi_count": job.serpapi_count,
                    "duplicates_removed": job.dedup_removed,
                    "cache_hits": {
                        "uspto": job.cache_hit_uspto,
                        "epo": job.cache_hit_epo,
                    },
                    "duration_seconds": job.duration_seconds,
                },
                "error": job.error_message,
                "completed_at": (
                    job.completed_at.isoformat()
                    if job.completed_at else None
                ),
                "next_step": next_step,
            }

    except Exception as e:
        logger.exception("Error retrieving search status")
        return {
            "error": "INTERNAL_ERROR",
            "message": f"Failed to retrieve status: {e}",
            "job_id": job_id,
        }
