"""Unified patent schema for cross-source normalization.

These Pydantic models represent the in-memory representation of patent
data.  They are used by the normalizer and search coordinator — NOT
directly as ORM models.
"""

from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class PatentSource(str, Enum):
    """Source of a patent record."""

    USPTO = "uspto"
    EPO = "epo"
    GOOGLE_PATENTS = "google_patents"


class Patent(BaseModel):
    """Unified patent record across all sources."""

    patent_id: str = Field(
        ..., description='Normalized ID e.g. "US-10234567", "EP-3456789"'
    )
    title: str = ""
    abstract: str = ""
    filing_date: Optional[date] = None
    publication_date: Optional[date] = None
    grant_date: Optional[date] = None
    assignee: Optional[str] = None
    inventors: list[str] = Field(default_factory=list)
    ipc_codes: list[str] = Field(default_factory=list)
    cpc_codes: list[str] = Field(default_factory=list)
    source: PatentSource = PatentSource.USPTO
    source_url: Optional[str] = None
    claims_text: Optional[str] = None
    abstract_similarity: Optional[float] = None  # Populated in Phase 4


class PatentSearchResult(BaseModel):
    """Aggregated result from a multi-source patent search."""

    patents: list[Patent] = Field(default_factory=list)
    total_found: int = 0
    source_counts: dict[str, int] = Field(default_factory=dict)
    search_duration_seconds: float = 0.0
    cache_hits: dict[str, bool] = Field(default_factory=dict)
    keywords_used: list[str] = Field(default_factory=list)
    ipc_codes_searched: list[str] = Field(default_factory=list)
    deduplication_removed: int = 0
