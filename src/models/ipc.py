"""Pydantic schemas for AI-extracted claims and IPC classification.

These models serve as both the Gemini JSON-mode response schemas and
the data contracts between the AI layer and the MCP tools.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


# ──────────────────────────────────────────────────────────────────────
# AI Claim Extraction
# ──────────────────────────────────────────────────────────────────────


class AIExtractedClaim(BaseModel):
    """A single patent-style claim extracted by Gemini."""

    claim_text: str = Field(
        description="Full patent-style independent claim statement."
    )
    claim_type: Literal["method", "system", "composition"] = Field(
        description="Patent claim category."
    )
    technical_domain: str = Field(
        description="Technical domain, e.g. 'natural language processing'."
    )
    novelty_basis: str = Field(
        description="Why this claim might be patentable — what is novel."
    )
    source_section: str = Field(
        description="Title of the paper section this claim was derived from."
    )
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="Gemini's confidence that this is a valid patentable claim.",
    )


class AIExtractedClaimsResponse(BaseModel):
    """Complete response from the AI claim extraction prompt."""

    claims: list[AIExtractedClaim] = Field(
        description="Extracted patent-style claims (5–10)."
    )
    paper_summary: str = Field(
        description="2–3 sentence technical summary of the paper."
    )
    primary_domain: str = Field(
        description="Main technical field of the paper."
    )


# ──────────────────────────────────────────────────────────────────────
# IPC / CPC Classification
# ──────────────────────────────────────────────────────────────────────


class ClaimIPCMapping(BaseModel):
    """IPC/CPC classification for a single claim."""

    claim_text: str = Field(description="The claim text that was classified.")
    primary_ipc: str = Field(description="Primary IPC code, e.g. 'G06N 3/08'.")
    secondary_ipc: list[str] = Field(
        default_factory=list,
        description="Additional relevant IPC codes.",
    )
    cpc_code: str = Field(
        default="",
        description="CPC code if different from IPC.",
    )
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="Classification confidence.",
    )
    rationale: str = Field(
        description="One-sentence explanation of why this code was assigned.",
    )
    is_valid_ipc: bool = Field(
        default=True,
        description="True if primary_ipc passes IPC regex validation.",
    )


class IPCClassificationResponse(BaseModel):
    """Complete response from the IPC classification prompt."""

    mappings: list[ClaimIPCMapping] = Field(
        description="IPC mapping for each claim."
    )
    top_ipc_codes: list[str] = Field(
        default_factory=list,
        description="Deduplicated IPC codes ranked by frequency across all claims.",
    )
    search_keywords: list[str] = Field(
        default_factory=list,
        description="10–15 terms for USPTO PatentsView full-text search.",
    )
    classification_summary: str = Field(
        default="",
        description="One-paragraph summary of the classification results.",
    )
