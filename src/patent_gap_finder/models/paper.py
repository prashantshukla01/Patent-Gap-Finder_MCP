"""Pydantic schemas for parsed research papers.

These models define the structured output of the paper parsing pipeline.
They are designed to be serializable (for MCP tool responses) and to
carry enough metadata for downstream patent analysis in later phases.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal, Optional

from pydantic import BaseModel, Field


class ParsedSection(BaseModel):
    """A single logical section extracted from a research paper."""

    title: str = Field(
        description="Section heading text (e.g. 'Introduction', '3.1 Model Architecture')."
    )
    content: str = Field(
        description="Full text content of the section, with whitespace normalized."
    )
    section_type: Literal[
        "abstract",
        "introduction",
        "methodology",
        "results",
        "conclusion",
        "references",
        "other",
    ] = Field(
        default="other",
        description="Semantic category of the section, inferred from heading text.",
    )


class CandidateClaim(BaseModel):
    """A sentence identified as a potential patentable claim via heuristic scoring."""

    text: str = Field(
        description="The verbatim sentence from the paper."
    )
    source_section: str = Field(
        description="Title of the section this sentence was extracted from."
    )
    claim_type: Literal["method", "system", "composition", "unknown"] = Field(
        default="unknown",
        description="Patent claim category inferred from sentence patterns.",
    )
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="Heuristic confidence score (0–1) indicating claim-likeness.",
    )


class ParsedPaper(BaseModel):
    """Complete structured representation of a parsed research paper.

    This is the primary return type of the ``parse_paper`` MCP tool.
    """

    title: str = Field(
        description="Paper title extracted from PDF metadata or first-page heuristics."
    )
    authors: list[str] = Field(
        default_factory=list,
        description="List of author names, in document order.",
    )
    abstract: str = Field(
        default="",
        description="Paper abstract text.",
    )
    sections: list[ParsedSection] = Field(
        default_factory=list,
        description="Ordered list of parsed sections.",
    )
    candidate_claims: list[CandidateClaim] = Field(
        default_factory=list,
        description="Top candidate patentable claims extracted via heuristics.",
    )
    source_url: Optional[str] = Field(
        default=None,
        description="Original URL if the paper was fetched from arXiv or another source.",
    )
    file_hash: Optional[str] = Field(
        default=None,
        description="SHA-256 hex digest of the source PDF for deduplication.",
    )
    session_id: Optional[str] = Field(
        default=None,
        description="Database session ID, set when the paper is persisted.",
    )
    parsed_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC timestamp of when the paper was parsed.",
    )
