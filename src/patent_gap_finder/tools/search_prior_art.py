"""MCP tool for initiating prior art patent search.

Dispatches a Celery task to search USPTO + EPO + SerpAPI in parallel,
returns immediately with a job_id for polling.
"""

from __future__ import annotations

import logging
from uuid import UUID

from patent_gap_finder.db.connection import get_db_session
from patent_gap_finder.db.repositories import job_repo, session_repo

logger = logging.getLogger(__name__)


def _is_valid_uuid(value: str) -> bool:
    try:
        UUID(value)
        return True
    except (ValueError, AttributeError):
        return False


async def search_prior_art(session_id: str) -> dict:
    """Search for prior art patents related to a session's classified claims.

    Requires Phase 2 completion (classify_ipc) so that IPC codes and
    search keywords are available.  Dispatches an async Celery task
    and returns immediately with a job_id for polling.

    Args:
        session_id: UUID of the analysis session.

    Returns:
        Job dispatch confirmation with job_id, or error dict.
    """
    session_id = session_id.strip()

    if not _is_valid_uuid(session_id):
        return {
            "error": "INVALID_SESSION_ID",
            "message": f"'{session_id}' is not a valid UUID.",
            "session_id": session_id,
        }

    try:
        async with get_db_session() as db:
            # Load session
            session = await session_repo.get_session(db, session_id)
            if session is None:
                return {
                    "error": "SESSION_NOT_FOUND",
                    "message": f"Session {session_id} not found.",
                    "session_id": session_id,
                }

            # Verify Phase 2 is done
            if not session.top_ipc_codes or not session.search_keywords:
                return {
                    "error": "PHASE2_INCOMPLETE",
                    "message": (
                        "Run classify_ipc first before searching patents. "
                        "Session needs top_ipc_codes and search_keywords."
                    ),
                    "session_id": session_id,
                }

            # Check for existing complete job
            existing_job = await job_repo.get_latest_job_for_session(
                db, session_id
            )
            if existing_job and existing_job.status == "complete":
                if not session.patent_search_complete:
                    session.patent_search_complete = True
                    session.total_patents_found = existing_job.result_count or 0
                    await db.flush()
                return {
                    "status": "complete",
                    "message": (
                        "Search already completed for this session. "
                        "Proceed to map_landscape to cluster the patent landscape."
                    ),
                    "session_id": session_id,
                    "job_id": existing_job.id,
                    "result_count": existing_job.result_count,
                    "next_step": "Call map_landscape to cluster the patent landscape",
                }

            if existing_job and existing_job.status in ("pending", "running"):
                return {
                    "error": "JOB_ALREADY_EXISTS",
                    "message": (
                        "Search already in progress. "
                        "Use get_search_status to poll progress."
                    ),
                    "session_id": session_id,
                    "job_id": existing_job.id,
                    "status": existing_job.status,
                }

            # Create job
            job = await job_repo.create_job(
                db,
                session_id=session_id,
                keywords=session.search_keywords,
                ipc_codes=session.top_ipc_codes,
            )
            job_id = job.id
            keywords = session.search_keywords
            ipc_codes = session.top_ipc_codes

        # Dispatch Celery task (sync call, safe from async context)
        try:
            from patent_gap_finder.workers.celery_app import celery_app
            from patent_gap_finder.workers.search_tasks import run_patent_search

            inspector = celery_app.control.inspect(timeout=1.0)
            ping_resp = inspector.ping() if inspector else None
            if not ping_resp:
                raise RuntimeError("No active Celery worker listening")

            task = run_patent_search.delay(
                session_id=session_id,
                job_id=job_id,
                keywords=keywords,
                ipc_codes=ipc_codes,
            )

            # Update job with celery task ID
            async with get_db_session() as db:
                await job_repo.update_job_celery_id(db, job_id, task.id)

        except Exception as e:
            logger.info("Celery/Redis unavailable (%s) — launching in-process search task fallback", e)
            import asyncio
            from patent_gap_finder.search.search_coordinator import coordinate_search

            async def _run_search_fallback():
                try:
                    async with get_db_session() as db_inner:
                        await job_repo.update_job_status(db_inner, job_id, "running")
                    await coordinate_search(
                        keywords=keywords,
                        ipc_codes=ipc_codes,
                        session_id=session_id,
                        job_id=job_id,
                    )
                except Exception as ex:
                    logger.error("Fallback search failed for job %s: %s", job_id, ex)
                    async with get_db_session() as db_inner:
                        await job_repo.update_job_status(
                            db_inner, job_id, "failed", error=str(ex)
                        )

            asyncio.create_task(_run_search_fallback())

        return {
            "job_id": job_id,
            "session_id": session_id,
            "status": "pending",
            "message": "Patent search started. Poll get_search_status for updates.",
            "keywords_queued": keywords,
            "ipc_codes_queued": ipc_codes,
            "estimated_duration_seconds": 45,
        }

    except Exception as e:
        logger.exception("Unexpected error in search_prior_art")
        return {
            "error": "INTERNAL_ERROR",
            "message": f"Unexpected error: {e}",
            "session_id": session_id,
        }
