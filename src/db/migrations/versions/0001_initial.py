"""Initial migration — all tables for Phases 1–5.

Revision ID: 0001
Revises: None
Create Date: 2026-04-01

Covers all 9 tables + 1 association table:
- analysis_sessions (Phase 1-5)
- extracted_claims (Phase 1-2)
- patents (Phase 1-4)
- session_patents (Phase 3)
- search_jobs (Phase 3)
- landscape_jobs (Phase 4)
- cluster_records (Phase 4)
- whitespace_opportunities (Phase 4)
- drafted_claims (Phase 5)
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers
revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── analysis_sessions ─────────────────────────────────────────────
    op.create_table(
        "analysis_sessions",
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("paper_title", sa.String(500), nullable=False),
        sa.Column("paper_authors", sa.JSON, nullable=True),
        sa.Column("source_url", sa.String(1000), nullable=True),
        sa.Column("file_hash", sa.String(64), nullable=True, index=True),
        sa.Column("primary_domain", sa.String(200), nullable=True),
        sa.Column("paper_summary", sa.String(2000), nullable=True),
        sa.Column("top_ipc_codes", sa.JSON, nullable=True),
        sa.Column("search_keywords", sa.JSON, nullable=True),
        sa.Column("status", sa.String(30), nullable=False, server_default="parsing"),
        sa.Column("total_requests_used", sa.Integer, nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("patent_search_complete", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("total_patents_found", sa.Integer, nullable=True),
        sa.Column("landscape_complete", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("whitespace_analysis_complete", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("top_opportunity_count", sa.Integer, nullable=True),
        sa.Column("claims_drafted", sa.Boolean, nullable=False, server_default="false"),
    )

    # ── extracted_claims ──────────────────────────────────────────────
    op.create_table(
        "extracted_claims",
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "session_id",
            UUID(as_uuid=False),
            sa.ForeignKey("analysis_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("claim_text", sa.Text, nullable=False),
        sa.Column("claim_type", sa.String(20), nullable=False),
        sa.Column("technical_domain", sa.String(200), nullable=True),
        sa.Column("novelty_basis", sa.Text, nullable=True),
        sa.Column("source_section", sa.String(200), nullable=False),
        sa.Column("confidence", sa.Float, nullable=False),
        sa.Column("primary_ipc", sa.String(20), nullable=True),
        sa.Column("secondary_ipc", sa.JSON, nullable=True),
        sa.Column("cpc_code", sa.String(30), nullable=True),
        sa.Column("ipc_confidence", sa.Float, nullable=True),
        sa.Column("is_valid_ipc", sa.Boolean, nullable=True),
        sa.Column("extraction_source", sa.String(20), nullable=False),
    )

    # ── patents ───────────────────────────────────────────────────────
    op.create_table(
        "patents",
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column("patent_id", sa.String(50), nullable=False, unique=True, index=True),
        sa.Column("title", sa.Text, nullable=False, server_default=""),
        sa.Column("abstract", sa.Text, nullable=False, server_default=""),
        sa.Column("filing_date", sa.DateTime, nullable=True),
        sa.Column("publication_date", sa.DateTime, nullable=True),
        sa.Column("grant_date", sa.DateTime, nullable=True),
        sa.Column("assignee", sa.String(500), nullable=True),
        sa.Column("inventors", sa.JSON, nullable=True),
        sa.Column("ipc_codes", sa.JSON, nullable=True),
        sa.Column("cpc_codes", sa.JSON, nullable=True),
        sa.Column("source", sa.String(20), nullable=False),
        sa.Column("source_url", sa.String(1000), nullable=True),
        sa.Column("claims_text", sa.Text, nullable=True),
        sa.Column("abstract_similarity", sa.Float, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cluster_id", sa.Integer, nullable=True),
        sa.Column("cluster_label", sa.String(200), nullable=True),
    )

    # ── session_patents (association table) ───────────────────────────
    op.create_table(
        "session_patents",
        sa.Column(
            "session_id",
            UUID(as_uuid=False),
            sa.ForeignKey("analysis_sessions.id"),
            primary_key=True,
        ),
        sa.Column(
            "patent_id",
            UUID(as_uuid=False),
            sa.ForeignKey("patents.id"),
            primary_key=True,
        ),
    )

    # ── search_jobs ───────────────────────────────────────────────────
    op.create_table(
        "search_jobs",
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "session_id",
            UUID(as_uuid=False),
            sa.ForeignKey("analysis_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("celery_task_id", sa.String(200), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("keywords_used", sa.JSON, nullable=True),
        sa.Column("ipc_codes_searched", sa.JSON, nullable=True),
        sa.Column("result_count", sa.Integer, nullable=True),
        sa.Column("uspto_count", sa.Integer, nullable=True),
        sa.Column("epo_count", sa.Integer, nullable=True),
        sa.Column("serpapi_count", sa.Integer, nullable=True),
        sa.Column("dedup_removed", sa.Integer, nullable=True),
        sa.Column("cache_hit_uspto", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("cache_hit_epo", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("duration_seconds", sa.Float, nullable=True),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )

    # ── landscape_jobs ────────────────────────────────────────────────
    op.create_table(
        "landscape_jobs",
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "session_id",
            UUID(as_uuid=False),
            sa.ForeignKey("analysis_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("n_patents_embedded", sa.Integer, nullable=True),
        sa.Column("n_clusters", sa.Integer, nullable=True),
        sa.Column("noise_patent_count", sa.Integer, nullable=True),
        sa.Column("hdbscan_params", sa.JSON, nullable=True),
        sa.Column("embedding_model", sa.String(100), nullable=True),
        sa.Column("whitespace_opportunities_found", sa.Integer, nullable=True),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )

    # ── cluster_records ───────────────────────────────────────────────
    op.create_table(
        "cluster_records",
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "landscape_job_id",
            UUID(as_uuid=False),
            sa.ForeignKey("landscape_jobs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("cluster_id", sa.Integer, nullable=False),
        sa.Column("label", sa.String(200), nullable=True),
        sa.Column("technical_domain", sa.String(200), nullable=True),
        sa.Column("patent_count", sa.Integer, nullable=False),
        sa.Column("centroid_patent_ids", sa.JSON, nullable=True),
        sa.Column("avg_internal_similarity", sa.Float, nullable=True),
        sa.Column("is_noise_cluster", sa.Boolean, nullable=False, server_default="false"),
    )

    # ── whitespace_opportunities ──────────────────────────────────────
    op.create_table(
        "whitespace_opportunities",
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "session_id",
            UUID(as_uuid=False),
            sa.ForeignKey("analysis_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "landscape_job_id",
            UUID(as_uuid=False),
            sa.ForeignKey("landscape_jobs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "claim_id",
            UUID(as_uuid=False),
            sa.ForeignKey("extracted_claims.id"),
            nullable=True,
        ),
        sa.Column("claim_text", sa.Text, nullable=False),
        sa.Column("claim_type", sa.String(20), nullable=False),
        sa.Column("novelty_score", sa.Float, nullable=False),
        sa.Column("avg_neighbor_similarity", sa.Float, nullable=False),
        sa.Column("nearest_cluster_label", sa.String(200), nullable=True),
        sa.Column("nearest_cluster_distance", sa.Float, nullable=True),
        sa.Column("nearest_patent_ids", sa.JSON, nullable=True),
        sa.Column("nearest_patent_titles", sa.JSON, nullable=True),
        sa.Column("gemini_assessment", sa.Text, nullable=True),
        sa.Column("gemini_confidence", sa.Float, nullable=True),
        sa.Column("recommended_claim_scope", sa.String(10), nullable=True),
        sa.Column("ipc_whitespace_codes", sa.JSON, nullable=True),
        sa.Column("is_whitespace", sa.Boolean, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    # ── drafted_claims (Phase 5) ──────────────────────────────────────
    op.create_table(
        "drafted_claims",
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column(
            "session_id",
            UUID(as_uuid=False),
            sa.ForeignKey("analysis_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "opportunity_id",
            UUID(as_uuid=False),
            sa.ForeignKey("whitespace_opportunities.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("claim_number", sa.Integer, nullable=False),
        sa.Column("claim_text", sa.Text, nullable=False),
        sa.Column("claim_type", sa.String(20), nullable=False),
        sa.Column("depends_on", sa.Integer, nullable=True),
        sa.Column("patent_claim_category", sa.String(20), nullable=False, server_default="method"),
        sa.Column("drafting_rationale", sa.Text, nullable=True),
        sa.Column("distinguishing_features", sa.JSON, nullable=True),
        sa.Column("ipc_codes", sa.JSON, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    # Drop tables in reverse dependency order
    op.drop_table("drafted_claims")
    op.drop_table("whitespace_opportunities")
    op.drop_table("cluster_records")
    op.drop_table("landscape_jobs")
    op.drop_table("search_jobs")
    op.drop_table("session_patents")
    op.drop_table("patents")
    op.drop_table("extracted_claims")
    op.drop_table("analysis_sessions")
