"""SQLAlchemy 2.0 ORM models for the Patent Gap Finder.

Uses ``Mapped`` / ``mapped_column`` declarative style.  UUIDs are
generated server-side (or in Python for SQLite compatibility).

Models:
- AnalysisSession: paper analysis tracking
- ExtractedClaim: patent claims from papers
- Patent: prior art patents from search
- SearchJob: async search job tracking
- session_patents: many-to-many association
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Table,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
    relationship,
)
from sqlalchemy.types import JSON, TypeDecorator


# ──────────────────────────────────────────────────────────────────────
# UUID type that works with both Postgres and SQLite
# ──────────────────────────────────────────────────────────────────────


class UUIDType(TypeDecorator):
    """Platform-agnostic UUID type.

    Uses PostgreSQL's native UUID when available, falls back to
    CHAR(36) for SQLite.
    """

    impl = String(36)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is not None:
            return str(value)
        return value

    def process_result_value(self, value, dialect):
        if value is not None:
            return str(value)
        return value

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(PG_UUID(as_uuid=False))
        return dialect.type_descriptor(String(36))


# ──────────────────────────────────────────────────────────────────────
# Base
# ──────────────────────────────────────────────────────────────────────


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""
    pass


# ──────────────────────────────────────────────────────────────────────
# Association table: session ↔ patent (many-to-many)
# ──────────────────────────────────────────────────────────────────────

session_patents = Table(
    "session_patents",
    Base.metadata,
    Column("session_id", UUIDType, ForeignKey("analysis_sessions.id"), primary_key=True),
    Column("patent_id", UUIDType, ForeignKey("patents.id"), primary_key=True),
)


# ──────────────────────────────────────────────────────────────────────
# AnalysisSession
# ──────────────────────────────────────────────────────────────────────


class AnalysisSession(Base):
    """Represents a single paper analysis session.

    Tracks the paper metadata, current processing status, Gemini usage,
    classification results, and patent search state.
    """

    __tablename__ = "analysis_sessions"

    id: Mapped[str] = mapped_column(
        UUIDType,
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    # Paper metadata
    paper_title: Mapped[str] = mapped_column(String(500))
    paper_authors: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    source_url: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    file_hash: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True, index=True
    )

    # AI results
    primary_domain: Mapped[Optional[str]] = mapped_column(
        String(200), nullable=True
    )
    paper_summary: Mapped[Optional[str]] = mapped_column(
        String(2000), nullable=True
    )
    top_ipc_codes: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    search_keywords: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)

    # Processing status
    status: Mapped[str] = mapped_column(String(30), default="parsing")
    total_requests_used: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Phase 3: patent search tracking
    patent_search_complete: Mapped[bool] = mapped_column(
        Boolean, default=False
    )
    total_patents_found: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True
    )

    # Relationships
    claims: Mapped[List["ExtractedClaim"]] = relationship(
        back_populates="session",
        lazy="selectin",
        cascade="all, delete-orphan",
    )
    search_jobs: Mapped[List["SearchJob"]] = relationship(
        back_populates="session",
        lazy="selectin",
        cascade="all, delete-orphan",
    )
    patents: Mapped[List["PatentRecord"]] = relationship(
        secondary=session_patents,
        lazy="selectin",
    )

    def to_dict(self) -> dict:
        """Serialize to a plain dict for MCP responses."""
        return {
            "id": self.id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "paper_title": self.paper_title,
            "paper_authors": self.paper_authors,
            "source_url": self.source_url,
            "file_hash": self.file_hash,
            "primary_domain": self.primary_domain,
            "paper_summary": self.paper_summary,
            "top_ipc_codes": self.top_ipc_codes,
            "search_keywords": self.search_keywords,
            "status": self.status,
            "total_requests_used": self.total_requests_used,
            "error_message": self.error_message,
            "patent_search_complete": self.patent_search_complete,
            "total_patents_found": self.total_patents_found,
        }


# ──────────────────────────────────────────────────────────────────────
# ExtractedClaim
# ──────────────────────────────────────────────────────────────────────


class ExtractedClaim(Base):
    """A patent claim extracted from a paper, either by heuristic or AI."""

    __tablename__ = "extracted_claims"

    id: Mapped[str] = mapped_column(
        UUIDType,
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    session_id: Mapped[str] = mapped_column(
        UUIDType,
        ForeignKey("analysis_sessions.id", ondelete="CASCADE"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )

    # Claim content
    claim_text: Mapped[str] = mapped_column(Text)
    claim_type: Mapped[str] = mapped_column(String(20))
    technical_domain: Mapped[Optional[str]] = mapped_column(
        String(200), nullable=True
    )
    novelty_basis: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    source_section: Mapped[str] = mapped_column(String(200))
    confidence: Mapped[float] = mapped_column(Float)

    # IPC classification (populated by classify_ipc tool)
    primary_ipc: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    secondary_ipc: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    cpc_code: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    ipc_confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    is_valid_ipc: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)

    # Source tracking
    extraction_source: Mapped[str] = mapped_column(String(20))  # "heuristic" or "ai"

    # Relationships
    session: Mapped["AnalysisSession"] = relationship(back_populates="claims")

    def to_dict(self) -> dict:
        """Serialize to a plain dict for MCP responses."""
        return {
            "id": self.id,
            "claim_text": self.claim_text,
            "claim_type": self.claim_type,
            "technical_domain": self.technical_domain,
            "novelty_basis": self.novelty_basis,
            "source_section": self.source_section,
            "confidence": self.confidence,
            "primary_ipc": self.primary_ipc,
            "secondary_ipc": self.secondary_ipc,
            "cpc_code": self.cpc_code,
            "ipc_confidence": self.ipc_confidence,
            "is_valid_ipc": self.is_valid_ipc,
            "extraction_source": self.extraction_source,
        }


# ──────────────────────────────────────────────────────────────────────
# PatentRecord (prior art from search)
# ──────────────────────────────────────────────────────────────────────


class PatentRecord(Base):
    """A patent retrieved from USPTO, EPO, or Google Patents."""

    __tablename__ = "patents"

    id: Mapped[str] = mapped_column(
        UUIDType,
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    patent_id: Mapped[str] = mapped_column(
        String(50), unique=True, index=True
    )
    title: Mapped[str] = mapped_column(Text, default="")
    abstract: Mapped[str] = mapped_column(Text, default="")
    filing_date: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True
    )
    publication_date: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True
    )
    grant_date: Mapped[Optional[datetime]] = mapped_column(
        DateTime, nullable=True
    )
    assignee: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    inventors: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    ipc_codes: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    cpc_codes: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    source: Mapped[str] = mapped_column(String(20))
    source_url: Mapped[Optional[str]] = mapped_column(
        String(1000), nullable=True
    )
    claims_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    abstract_similarity: Mapped[Optional[float]] = mapped_column(
        Float, nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )


# ──────────────────────────────────────────────────────────────────────
# SearchJob
# ──────────────────────────────────────────────────────────────────────


class SearchJob(Base):
    """Tracks an async patent search job dispatched to Celery."""

    __tablename__ = "search_jobs"

    id: Mapped[str] = mapped_column(
        UUIDType,
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    session_id: Mapped[str] = mapped_column(
        UUIDType,
        ForeignKey("analysis_sessions.id", ondelete="CASCADE"),
    )
    celery_task_id: Mapped[Optional[str]] = mapped_column(
        String(200), nullable=True
    )

    # Status
    status: Mapped[str] = mapped_column(String(20), default="pending")

    # Search parameters
    keywords_used: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    ipc_codes_searched: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)

    # Results
    result_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    uspto_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    epo_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    serpapi_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    dedup_removed: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    cache_hit_uspto: Mapped[bool] = mapped_column(Boolean, default=False)
    cache_hit_epo: Mapped[bool] = mapped_column(Boolean, default=False)
    duration_seconds: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Relationships
    session: Mapped["AnalysisSession"] = relationship(back_populates="search_jobs")
