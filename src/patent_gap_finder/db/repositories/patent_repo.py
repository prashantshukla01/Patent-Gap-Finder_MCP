"""Repository for Patent CRUD operations.

Uses bulk INSERT ... ON CONFLICT DO NOTHING for deduplication.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import insert, select, String, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from patent_gap_finder.db.models import PatentRecord, session_patents
from patent_gap_finder.models.patent import Patent

logger = logging.getLogger(__name__)


async def upsert_patents(
    db: AsyncSession,
    patents: list[Patent],
) -> tuple[int, int]:
    """Bulk upsert patents. Returns (inserted_count, skipped_count).

    Uses INSERT ... ON CONFLICT (patent_id) DO NOTHING to skip
    existing patents.
    """
    if not patents:
        return 0, 0

    inserted = 0
    skipped = 0

    for patent in patents:
        # Check if exists
        result = await db.execute(
            select(PatentRecord).where(PatentRecord.patent_id == patent.patent_id)
        )
        existing = result.scalars().first()

        if existing:
            skipped += 1
            continue

        record = PatentRecord(
            id=str(uuid.uuid4()),
            patent_id=patent.patent_id,
            title=patent.title,
            abstract=patent.abstract,
            filing_date=patent.filing_date,
            publication_date=patent.publication_date,
            grant_date=patent.grant_date,
            assignee=patent.assignee,
            inventors=patent.inventors,
            ipc_codes=patent.ipc_codes,
            cpc_codes=patent.cpc_codes,
            source=patent.source.value,
            source_url=patent.source_url,
            claims_text=patent.claims_text,
            created_at=datetime.now(timezone.utc),
        )
        db.add(record)
        inserted += 1

    await db.flush()
    return inserted, skipped


async def link_patents_to_session(
    db: AsyncSession,
    session_id: str,
    patent_db_ids: list[str],
) -> None:
    """Populate session_patents association table."""
    for patent_db_id in patent_db_ids:
        try:
            await db.execute(
                insert(session_patents).values(
                    session_id=session_id,
                    patent_id=patent_db_id,
                )
            )
        except Exception:
            pass  # Skip duplicates
    await db.flush()


async def get_patent_db_ids_by_patent_ids(
    db: AsyncSession,
    patent_ids: list[str],
) -> list[str]:
    """Get DB UUIDs for a list of normalized patent_id strings."""
    if not patent_ids:
        return []
    result = await db.execute(
        select(PatentRecord.id).where(PatentRecord.patent_id.in_(patent_ids))
    )
    return [row[0] for row in result.all()]


async def get_patents_for_session(
    db: AsyncSession,
    session_id: str,
) -> list[PatentRecord]:
    """Return all patents linked to a session."""
    result = await db.execute(
        select(PatentRecord)
        .join(session_patents)
        .where(session_patents.c.session_id == session_id)
    )
    return list(result.scalars().all())


async def get_patent_by_id(
    db: AsyncSession,
    patent_id: str,
) -> Optional[PatentRecord]:
    """Look up by normalized patent_id string."""
    result = await db.execute(
        select(PatentRecord).where(PatentRecord.patent_id == patent_id)
    )
    return result.scalars().first()


async def get_patent_count_for_session(
    db: AsyncSession,
    session_id: str,
) -> dict:
    """Count patents linked to a session, grouped by source."""
    patents = await get_patents_for_session(db, session_id)

    by_source: dict[str, int] = {}
    for p in patents:
        by_source[p.source] = by_source.get(p.source, 0) + 1

    return {
        "total": len(patents),
        "by_source": by_source,
    }


async def search_patents_by_ipc(
    db: AsyncSession,
    ipc_prefix: str,
) -> list[PatentRecord]:
    """Return patents whose ipc_codes contain the prefix."""
    # For JSON array search — cast to text and use LIKE
    result = await db.execute(
        select(PatentRecord).where(
            PatentRecord.ipc_codes.cast(String).contains(ipc_prefix)
        )
    )
    return list(result.scalars().all())


# ──────────────────────────────────────────────────────────────────────
# Phase 4: Embedding metadata updates
# ──────────────────────────────────────────────────────────────────────


async def update_patent_embedding_metadata(
    db: AsyncSession,
    patent_db_id: str,
    abstract_similarity: float,
    cluster_id: int,
    cluster_label: Optional[str] = None,
) -> None:
    """Update a patent with embedding metadata (Phase 4).

    Populates abstract_similarity (was NULL from Phase 3),
    cluster_id, and cluster_label.
    """
    await db.execute(
        update(PatentRecord)
        .where(PatentRecord.id == patent_db_id)
        .values(
            abstract_similarity=abstract_similarity,
            cluster_id=cluster_id,
            cluster_label=cluster_label,
        )
    )
    await db.flush()


async def get_unembedded_patents(
    db: AsyncSession,
    session_id: str,
) -> list[PatentRecord]:
    """Return patents where abstract_similarity IS NULL for a session.

    Used to avoid re-embedding on subsequent map_landscape calls.
    """
    result = await db.execute(
        select(PatentRecord)
        .join(session_patents)
        .where(
            session_patents.c.session_id == session_id,
            PatentRecord.abstract_similarity.is_(None),
        )
    )
    return list(result.scalars().all())
