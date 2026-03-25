"""Tests for the AI claim extractor module.

Mocks the GeminiClient to test prompt assembly and response handling.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from patent_gap_finder.ai.claim_extractor import extract_claims, _build_user_prompt
from patent_gap_finder.models.ipc import AIExtractedClaim, AIExtractedClaimsResponse
from patent_gap_finder.models.paper import ParsedPaper, ParsedSection


# ── Fixtures ─────────────────────────────────────────────────────────

@pytest.fixture
def sample_paper() -> ParsedPaper:
    """Create a sample ParsedPaper for testing."""
    return ParsedPaper(
        title="A Novel Approach to Widget Optimization",
        authors=["Alice Smith", "Bob Jones"],
        abstract="We present a novel method for optimizing widgets using deep learning.",
        sections=[
            ParsedSection(
                title="Abstract",
                content="We present a novel method for optimizing widgets.",
                section_type="abstract",
            ),
            ParsedSection(
                title="Introduction",
                content="Widget optimization is a key challenge in modern manufacturing.",
                section_type="introduction",
            ),
            ParsedSection(
                title="Methodology",
                content="Our approach uses a hierarchical attention mechanism that attends to both local and global features. " * 20,
                section_type="methodology",
            ),
            ParsedSection(
                title="Results",
                content="We achieve state-of-the-art results on the WidgetBench benchmark.",
                section_type="results",
            ),
            ParsedSection(
                title="Conclusion",
                content="We have demonstrated that our approach significantly outperforms prior work.",
                section_type="conclusion",
            ),
        ],
    )


@pytest.fixture
def mock_response() -> AIExtractedClaimsResponse:
    """Create a sample AI response."""
    return AIExtractedClaimsResponse(
        claims=[
            AIExtractedClaim(
                claim_text="A method for optimizing widgets comprising: applying hierarchical attention...",
                claim_type="method",
                technical_domain="manufacturing optimization",
                novelty_basis="Novel hierarchical attention mechanism for widget features",
                source_section="Methodology",
                confidence=0.85,
            ),
            AIExtractedClaim(
                claim_text="A system for real-time widget quality assessment comprising: a sensor array...",
                claim_type="system",
                technical_domain="quality control",
                novelty_basis="Real-time quality assessment using multi-scale feature extraction",
                source_section="Methodology",
                confidence=0.72,
            ),
        ],
        paper_summary="This paper presents a novel widget optimization method using hierarchical attention.",
        primary_domain="manufacturing optimization",
    )


# ──────────────────────────────────────────────────────────────────────
# Tests
# ──────────────────────────────────────────────────────────────────────


class TestPromptAssembly:
    """Tests for user prompt construction."""

    def test_prompt_contains_title(self, sample_paper: ParsedPaper) -> None:
        """Prompt should include the paper title."""
        prompt = _build_user_prompt(sample_paper)
        assert "Novel Approach to Widget Optimization" in prompt

    def test_prompt_contains_abstract(self, sample_paper: ParsedPaper) -> None:
        """Prompt should include the abstract text."""
        prompt = _build_user_prompt(sample_paper)
        assert "novel method for optimizing widgets" in prompt

    def test_prompt_contains_introduction(self, sample_paper: ParsedPaper) -> None:
        """Prompt should include the intro section."""
        prompt = _build_user_prompt(sample_paper)
        assert "key challenge" in prompt

    def test_prompt_contains_conclusion(self, sample_paper: ParsedPaper) -> None:
        """Prompt should include the conclusion."""
        prompt = _build_user_prompt(sample_paper)
        assert "outperforms prior work" in prompt

    def test_methodology_truncated(self, sample_paper: ParsedPaper) -> None:
        """Long methodology section should be truncated to 800 chars."""
        prompt = _build_user_prompt(sample_paper)
        # The methodology section content is ~1600 chars, should be truncated
        assert "[truncated]" in prompt

    def test_empty_sections_handled(self) -> None:
        """Paper with no sections should produce a minimal prompt."""
        paper = ParsedPaper(title="Empty Paper", authors=[])
        prompt = _build_user_prompt(paper)
        assert "Empty Paper" in prompt


class TestExtractClaims:
    """Tests for the extract_claims function."""

    @pytest.mark.asyncio
    async def test_returns_correct_claim_count(
        self,
        sample_paper: ParsedPaper,
        mock_response: AIExtractedClaimsResponse,
    ) -> None:
        """Should return the correct number of claims from Gemini."""
        mock_client = MagicMock()
        mock_client.complete_json = AsyncMock(return_value=mock_response)

        result = await extract_claims(sample_paper, client=mock_client)

        assert len(result.claims) == 2
        assert result.primary_domain == "manufacturing optimization"
        mock_client.complete_json.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_claims_have_correct_types(
        self,
        sample_paper: ParsedPaper,
        mock_response: AIExtractedClaimsResponse,
    ) -> None:
        """Each claim should have a valid claim_type."""
        mock_client = MagicMock()
        mock_client.complete_json = AsyncMock(return_value=mock_response)

        result = await extract_claims(sample_paper, client=mock_client)

        for claim in result.claims:
            assert claim.claim_type in {"method", "system", "composition"}
            assert 0.0 <= claim.confidence <= 1.0

    @pytest.mark.asyncio
    async def test_paper_summary_present(
        self,
        sample_paper: ParsedPaper,
        mock_response: AIExtractedClaimsResponse,
    ) -> None:
        """Response should include a paper summary."""
        mock_client = MagicMock()
        mock_client.complete_json = AsyncMock(return_value=mock_response)

        result = await extract_claims(sample_paper, client=mock_client)

        assert result.paper_summary
        assert len(result.paper_summary) > 10
