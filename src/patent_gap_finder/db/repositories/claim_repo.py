"""Repository for ExtractedClaim CRUD operations.

Uses bulk ``insert`` for performance when creating multiple claims
from a single extraction pass.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from patent_gap_finder.db.models import ExtractedClaim

logger = logging.getLogger(__name__)


async def create_claims(
    db: AsyncSession,
    session_id: str,
    claims: list[dict],
) -> list[ExtractedClaim]:
    """Bulk-insert extracted claims for a session.

    Args:
        db: Async database session.
        session_id: UUID string of the parent session.
        claims: List of dicts, each with keys matching ExtractedClaim columns:
            claim_text, claim_type, source_section, confidence,
            extraction_source, and optionally technical_domain, novelty_basis.

    Returns:
        List of created :class:`ExtractedClaim` instances.
    """
    if not claims:
        return []

    rows = []
    for claim in claims:
        rows.append({
            "id": str(uuid.uuid4()),
            "session_id": session_id,
            "claim_text": claim["claim_text"],
            "claim_type": claim.get("claim_type", "unknown"),
            "technical_domain": claim.get("technical_domain"),
            "novelty_basis": claim.get("novelty_basis"),
            "source_section": claim.get("source_section", ""),
            "confidence": claim.get("confidence", 0.0),
            "extraction_source": claim.get("extraction_source", "heuristic"),
            "created_at": datetime.now(timezone.utc),
        })

    await db.execute(insert(ExtractedClaim), rows)
    logger.info(
        "Inserted %d claims for session %s",
        len(rows),
        session_id,
    )

    # Return the created claims via query (to get fully hydrated objects)
    result = await db.execute(
        select(ExtractedClaim).where(ExtractedClaim.session_id == session_id)
    )
    return list(result.scalars().all())


async def get_claims_for_session(
    db: AsyncSession,
    session_id: str,
) -> list[ExtractedClaim]:
    """Fetch all claims for a given session.

    Args:
        db: Async database session.
        session_id: UUID string of the session.

    Returns:
        List of :class:`ExtractedClaim` instances.
    """
    result = await db.execute(
        select(ExtractedClaim)
        .where(ExtractedClaim.session_id == session_id)
        .order_by(ExtractedClaim.confidence.desc())
    )
    return list(result.scalars().all())


async def get_claims_by_type(
    db: AsyncSession,
    session_id: str,
    claim_type: str,
) -> list[ExtractedClaim]:
    """Fetch claims filtered by type for a session.

    Args:
        db: Async database session.
        session_id: UUID string of the session.
        claim_type: Claim type filter (method/system/composition/unknown).

    Returns:
        Filtered list of :class:`ExtractedClaim` instances.
    """
    result = await db.execute(
        select(ExtractedClaim)
        .where(
            ExtractedClaim.session_id == session_id,
            ExtractedClaim.claim_type == claim_type,
        )
        .order_by(ExtractedClaim.confidence.desc())
    )
    return list(result.scalars().all())


async def get_claims_by_source(
    db: AsyncSession,
    session_id: str,
    extraction_source: str,
) -> list[ExtractedClaim]:
    """Fetch claims filtered by extraction source.

    Args:
        db: Async database session.
        session_id: UUID string of the session.
        extraction_source: Either 'heuristic' or 'ai'.

    Returns:
        Filtered list of :class:`ExtractedClaim`.
    """
    result = await db.execute(
        select(ExtractedClaim)
        .where(
            ExtractedClaim.session_id == session_id,
            ExtractedClaim.extraction_source == extraction_source,
        )
        .order_by(ExtractedClaim.confidence.desc())
    )
    return list(result.scalars().all())


async def update_claim_ipc(
    db: AsyncSession,
    claim_id: str,
    ipc_data: dict,
) -> None:
    """Update IPC classification data on a claim.

    Args:
        db: Async database session.
        claim_id: UUID string of the claim.
        ipc_data: Dict with keys: primary_ipc, secondary_ipc, cpc_code,
            ipc_confidence (as 'confidence'), is_valid_ipc.
    """
    values = {}
    if "primary_ipc" in ipc_data:
        values["primary_ipc"] = ipc_data["primary_ipc"]
    if "secondary_ipc" in ipc_data:
        values["secondary_ipc"] = ipc_data["secondary_ipc"]
    if "cpc_code" in ipc_data:
        values["cpc_code"] = ipc_data["cpc_code"]
    if "confidence" in ipc_data:
        values["ipc_confidence"] = ipc_data["confidence"]
    if "is_valid_ipc" in ipc_data:
        values["is_valid_ipc"] = ipc_data["is_valid_ipc"]

    if values:
        await db.execute(
            update(ExtractedClaim)
            .where(ExtractedClaim.id == claim_id)
            .values(**values)
        )
