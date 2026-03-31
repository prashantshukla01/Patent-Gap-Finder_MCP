"""Repository for LandscapeJob, ClusterRecord, and WhitespaceOpportunity CRUD."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from patent_gap_finder.db.models import (
    ClusterRecord,
    LandscapeJob,
    WhitespaceOpportunityRecord,
)
from patent_gap_finder.models.landscape import ClusterInfo, WhitespaceOpportunity

logger = logging.getLogger(__name__)


async def create_landscape_job(
    db: AsyncSession,
    session_id: str,
) -> LandscapeJob:
    """Create a new landscape job."""
    job = LandscapeJob(
        id=str(uuid.uuid4()),
        session_id=session_id,
        status="pending",
        created_at=datetime.now(timezone.utc),
    )
    db.add(job)
    await db.flush()
    return job


async def update_landscape_job_status(
    db: AsyncSession,
    job_id: str,
    status: str,
    error: Optional[str] = None,
) -> None:
    """Update the status of a landscape job."""
    values = {"status": status}
    if error:
        values["error_message"] = error
    if status in ("complete", "failed"):
        values["completed_at"] = datetime.now(timezone.utc)

    await db.execute(
        update(LandscapeJob)
        .where(LandscapeJob.id == job_id)
        .values(**values)
    )
    await db.flush()


async def update_landscape_job_results(
    db: AsyncSession,
    job_id: str,
    results: dict,
) -> None:
    """Update landscape job with completion results."""
    await db.execute(
        update(LandscapeJob)
        .where(LandscapeJob.id == job_id)
        .values(
            status="complete",
            n_patents_embedded=results.get("n_patents_embedded"),
            n_clusters=results.get("n_clusters"),
            noise_patent_count=results.get("noise_patent_count"),
            hdbscan_params=results.get("hdbscan_params"),
            embedding_model=results.get("embedding_model"),
            whitespace_opportunities_found=results.get("whitespace_opportunities_found"),
            completed_at=datetime.now(timezone.utc),
        )
    )
    await db.flush()


async def get_landscape_job(
    db: AsyncSession,
    job_id: str,
) -> Optional[LandscapeJob]:
    """Get a landscape job by ID."""
    result = await db.execute(
        select(LandscapeJob).where(LandscapeJob.id == job_id)
    )
    return result.scalars().first()


async def get_latest_landscape_job(
    db: AsyncSession,
    session_id: str,
) -> Optional[LandscapeJob]:
    """Get the most recent landscape job for a session."""
    result = await db.execute(
        select(LandscapeJob)
        .where(LandscapeJob.session_id == session_id)
        .order_by(LandscapeJob.created_at.desc())
        .limit(1)
    )
    return result.scalars().first()


async def create_cluster_records(
    db: AsyncSession,
    job_id: str,
    clusters: list[ClusterInfo],
) -> None:
    """Persist cluster metadata to the database."""
    for cluster in clusters:
        record = ClusterRecord(
            id=str(uuid.uuid4()),
            landscape_job_id=job_id,
            cluster_id=cluster.cluster_id,
            label=cluster.label,
            technical_domain=cluster.technical_domain,
            patent_count=cluster.patent_count,
            centroid_patent_ids=cluster.centroid_patent_ids,
            avg_internal_similarity=cluster.avg_internal_similarity,
            is_noise_cluster=(cluster.cluster_id == -1),
        )
        db.add(record)
    await db.flush()


async def create_whitespace_opportunities(
    db: AsyncSession,
    session_id: str,
    job_id: str,
    opportunities: list[WhitespaceOpportunity],
) -> None:
    """Persist white-space opportunities to the database."""
    for opp in opportunities:
        record = WhitespaceOpportunityRecord(
            id=opp.opportunity_id,
            session_id=session_id,
            landscape_job_id=job_id,
            claim_text=opp.claim_text,
            claim_type=opp.claim_type,
            novelty_score=opp.novelty_score,
            avg_neighbor_similarity=opp.avg_neighbor_similarity,
            nearest_cluster_label=opp.nearest_cluster_label,
            nearest_cluster_distance=opp.nearest_cluster_distance,
            nearest_patent_ids=opp.nearest_patents,
            nearest_patent_titles=opp.nearest_patent_titles,
            gemini_assessment=opp.gemini_novelty_assessment,
            gemini_confidence=opp.gemini_confidence,
            recommended_claim_scope=opp.recommended_claim_scope,
            ipc_whitespace_codes=opp.ipc_whitespace_codes,
            is_whitespace=opp.is_whitespace,
            created_at=datetime.now(timezone.utc),
        )
        db.add(record)
    await db.flush()


async def get_whitespace_opportunities(
    db: AsyncSession,
    session_id: str,
    min_novelty_score: float = 0.0,
) -> list[WhitespaceOpportunityRecord]:
    """Retrieve white-space opportunities for a session."""
    result = await db.execute(
        select(WhitespaceOpportunityRecord)
        .where(
            WhitespaceOpportunityRecord.session_id == session_id,
            WhitespaceOpportunityRecord.novelty_score >= min_novelty_score,
        )
        .order_by(WhitespaceOpportunityRecord.novelty_score.desc())
    )
    return list(result.scalars().all())
