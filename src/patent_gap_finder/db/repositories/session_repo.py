"""Repository for AnalysisSession CRUD operations.

All methods accept an ``AsyncSession`` as the first parameter —
they never create their own sessions.  Session lifecycle is managed
by the caller (typically the MCP tool via ``get_db_session``).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from patent_gap_finder.db.models import AnalysisSession

logger = logging.getLogger(__name__)


async def create_session(
    db: AsyncSession,
    paper_data: dict,
) -> AnalysisSession:
    """Create a new analysis session for a paper.

    Args:
        db: Async database session.
        paper_data: Dict with keys: paper_title, paper_authors,
            source_url, file_hash.

    Returns:
        The created :class:`AnalysisSession` instance.
    """
    session = AnalysisSession(
        paper_title=paper_data.get("paper_title", "Untitled"),
        paper_authors=paper_data.get("paper_authors"),
        source_url=paper_data.get("source_url"),
        file_hash=paper_data.get("file_hash"),
        status="parsing",
    )
    db.add(session)
    await db.flush()
    logger.info("Created analysis session %s for '%s'", session.id, session.paper_title)
    return session


async def get_session(
    db: AsyncSession,
    session_id: str,
) -> Optional[AnalysisSession]:
    """Retrieve a session by ID.

    Args:
        db: Async database session.
        session_id: UUID string of the session.

    Returns:
        The :class:`AnalysisSession` or None if not found.
    """
    result = await db.execute(
        select(AnalysisSession).where(AnalysisSession.id == session_id)
    )
    return result.scalars().first()


async def update_session_status(
    db: AsyncSession,
    session_id: str,
    status: str,
    *,
    error_message: Optional[str] = None,
) -> None:
    """Update the processing status of a session.

    Args:
        db: Async database session.
        session_id: UUID string of the session.
        status: New status value (parsing/extracting/classifying/complete/failed).
        error_message: Optional error message (set when status is 'failed').
    """
    values = {
        "status": status,
        "updated_at": datetime.now(timezone.utc),
    }
    if error_message is not None:
        values["error_message"] = error_message

    await db.execute(
        update(AnalysisSession)
        .where(AnalysisSession.id == session_id)
        .values(**values)
    )
    logger.info("Session %s status → %s", session_id, status)


async def update_session_results(
    db: AsyncSession,
    session_id: str,
    results: dict,
) -> None:
    """Update AI-derived results on a session.

    Args:
        db: Async database session.
        session_id: UUID string of the session.
        results: Dict with optional keys: primary_domain, paper_summary,
            top_ipc_codes, search_keywords.
    """
    values: dict = {"updated_at": datetime.now(timezone.utc)}

    for key in ("primary_domain", "paper_summary", "top_ipc_codes", "search_keywords"):
        if key in results:
            values[key] = results[key]

    await db.execute(
        update(AnalysisSession)
        .where(AnalysisSession.id == session_id)
        .values(**values)
    )
    logger.info("Session %s results updated", session_id)


async def get_session_by_file_hash(
    db: AsyncSession,
    file_hash: str,
) -> Optional[AnalysisSession]:
    """Find an existing session by PDF file hash (deduplication).

    Args:
        db: Async database session.
        file_hash: SHA-256 hex digest of the PDF file.

    Returns:
        The existing :class:`AnalysisSession` or None.
    """
    result = await db.execute(
        select(AnalysisSession).where(AnalysisSession.file_hash == file_hash)
    )
    return result.scalars().first()


async def increment_request_counter(
    db: AsyncSession,
    session_id: str,
    count: int = 1,
) -> None:
    """Increment the Gemini request counter for a session.

    Args:
        db: Async database session.
        session_id: UUID string of the session.
        count: Number of requests to add.
    """
    session = await get_session(db, session_id)
    if session is not None:
        await db.execute(
            update(AnalysisSession)
            .where(AnalysisSession.id == session_id)
            .values(
                total_requests_used=AnalysisSession.total_requests_used + count,
                updated_at=datetime.now(timezone.utc),
            )
        )
