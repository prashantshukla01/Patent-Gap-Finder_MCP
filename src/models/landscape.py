"""Pydantic schemas for patent landscape mapping and white-space detection."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class ClusterInfo(BaseModel):
    """Information about a single patent cluster."""

    cluster_id: int
    label: str = ""
    technical_domain: str = ""
    patent_count: int = 0
    centroid_patent_ids: list[str] = Field(default_factory=list)
    avg_internal_similarity: float = 0.0
    representative_titles: list[str] = Field(default_factory=list)


class LandscapeMap(BaseModel):
    """Full landscape map from HDBSCAN clustering."""

    session_id: str
    total_patents_embedded: int = 0
    n_clusters: int = 0
    noise_patent_count: int = 0
    clusters: list[ClusterInfo] = Field(default_factory=list)
    embedding_model: str = "all-MiniLM-L6-v2"
    hdbscan_params: dict = Field(default_factory=dict)
    created_at: Optional[datetime] = None


class WhitespaceOpportunity(BaseModel):
    """A single white-space patent opportunity."""

    opportunity_id: str
    claim_text: str
    claim_type: str = "method"
    novelty_score: float = 0.0
    avg_neighbor_similarity: float = 0.0
    nearest_cluster_label: str = ""
    nearest_cluster_distance: float = 0.0
    nearest_patents: list[str] = Field(default_factory=list)
    nearest_patent_titles: list[str] = Field(default_factory=list)
    gemini_novelty_assessment: str = ""
    gemini_confidence: float = 0.0
    ipc_whitespace_codes: list[str] = Field(default_factory=list)
    recommended_claim_scope: str = "medium"
    is_whitespace: bool = False


class WhitespaceReport(BaseModel):
    """Aggregated white-space analysis report."""

    session_id: str
    landscape_job_id: str
    total_claims_analyzed: int = 0
    whitespace_opportunities: list[WhitespaceOpportunity] = Field(default_factory=list)
    non_whitespace_claims: int = 0
    analysis_summary: str = ""
    top_opportunity_count: int = 0
    created_at: Optional[datetime] = None


class NoveltyAssessment(BaseModel):
    """Gemini-generated novelty assessment for a claim."""

    gemini_novelty_assessment: str = ""
    gemini_confidence: float = 0.0
    recommended_claim_scope: str = "medium"
    ipc_whitespace_codes: list[str] = Field(default_factory=list)
    key_differentiators: list[str] = Field(default_factory=list)
