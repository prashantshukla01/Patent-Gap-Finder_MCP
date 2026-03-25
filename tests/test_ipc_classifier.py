"""Tests for the IPC classifier module.

Mocks the GeminiClient to test IPC code validation and response handling.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from patent_gap_finder.ai.ipc_classifier import classify_ipc, validate_ipc_code
from patent_gap_finder.models.ipc import (
    AIExtractedClaim,
    ClaimIPCMapping,
    IPCClassificationResponse,
)


# ── Fixtures ─────────────────────────────────────────────────────────

@pytest.fixture
def sample_claims() -> list[AIExtractedClaim]:
    """Create sample AI-extracted claims for testing."""
    return [
        AIExtractedClaim(
            claim_text="A method for training a neural network...",
            claim_type="method",
            technical_domain="machine learning",
            novelty_basis="Novel sparse attention mechanism",
            source_section="Methodology",
            confidence=0.85,
        ),
        AIExtractedClaim(
            claim_text="A system for real-time image recognition...",
            claim_type="system",
            technical_domain="computer vision",
            novelty_basis="Multi-scale feature extraction pipeline",
            source_section="Architecture",
            confidence=0.78,
        ),
    ]


@pytest.fixture
def mock_classification() -> IPCClassificationResponse:
    """Create a sample classification response."""
    return IPCClassificationResponse(
        mappings=[
            ClaimIPCMapping(
                claim_text="A method for training a neural network...",
                primary_ipc="G06N 3/08",
                secondary_ipc=["G06N 3/04"],
                cpc_code="G06N 3/08",
                confidence=0.9,
                rationale="Neural network training falls under G06N 3/08.",
                is_valid_ipc=True,
            ),
            ClaimIPCMapping(
                claim_text="A system for real-time image recognition...",
                primary_ipc="G06V 10/40",
                secondary_ipc=["G06N 3/08"],
                cpc_code="G06V 10/40",
                confidence=0.85,
                rationale="Image recognition is classified under G06V.",
                is_valid_ipc=True,
            ),
        ],
        top_ipc_codes=["G06N 3/08", "G06V 10/40", "G06N 3/04"],
        search_keywords=[
            "neural network", "attention mechanism", "image recognition",
            "deep learning", "convolutional", "feature extraction",
            "training method", "sparse attention", "multi-scale",
            "real-time processing", "object detection",
        ],
        classification_summary="The claims span neural network training and computer vision.",
    )


# ──────────────────────────────────────────────────────────────────────
# IPC Validation Tests
# ──────────────────────────────────────────────────────────────────────


class TestIPCValidation:
    """Tests for the validate_ipc_code function."""

    @pytest.mark.parametrize("code,expected", [
        ("G06N 3/08", True),
        ("H04L 9/30", True),
        ("A61K 9/51", True),
        ("B82Y 5/00", True),
        ("G06F 17/30", True),
        ("G16B 30/00", True),
        # Invalid codes
        ("G06N3/08", False),       # missing space
        ("X06N 3/08", False),      # invalid section letter
        ("G06N", False),           # incomplete
        ("", False),               # empty
        ("random text", False),    # not a code
        ("G6N 3/08", False),       # only one digit after section
    ])
    def test_ipc_validation(self, code: str, expected: bool) -> None:
        """IPC codes should be validated against the standard pattern."""
        assert validate_ipc_code(code) == expected


# ──────────────────────────────────────────────────────────────────────
# Classification Tests
# ──────────────────────────────────────────────────────────────────────


class TestClassifyIPC:
    """Tests for the classify_ipc function."""

    @pytest.mark.asyncio
    async def test_returns_mappings(
        self,
        sample_claims: list[AIExtractedClaim],
        mock_classification: IPCClassificationResponse,
    ) -> None:
        """Should return mappings for each claim."""
        mock_client = MagicMock()
        mock_client.complete_json = AsyncMock(return_value=mock_classification)

        result = await classify_ipc(
            sample_claims, "machine learning", client=mock_client
        )

        assert len(result.mappings) == 2
        mock_client.complete_json.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_top_ipc_codes_deduplicated(
        self,
        sample_claims: list[AIExtractedClaim],
        mock_classification: IPCClassificationResponse,
    ) -> None:
        """top_ipc_codes should be deduplicated."""
        mock_client = MagicMock()
        mock_client.complete_json = AsyncMock(return_value=mock_classification)

        result = await classify_ipc(
            sample_claims, "machine learning", client=mock_client
        )

        # Should have unique codes
        assert len(result.top_ipc_codes) == len(set(result.top_ipc_codes))

    @pytest.mark.asyncio
    async def test_search_keywords_count(
        self,
        sample_claims: list[AIExtractedClaim],
        mock_classification: IPCClassificationResponse,
    ) -> None:
        """Should return 10-15 search keywords."""
        mock_client = MagicMock()
        mock_client.complete_json = AsyncMock(return_value=mock_classification)

        result = await classify_ipc(
            sample_claims, "machine learning", client=mock_client
        )

        assert len(result.search_keywords) >= 10

    @pytest.mark.asyncio
    async def test_invalid_ipc_flagged(
        self,
        sample_claims: list[AIExtractedClaim],
    ) -> None:
        """Invalid IPC codes should be flagged with is_valid_ipc=False."""
        bad_classification = IPCClassificationResponse(
            mappings=[
                ClaimIPCMapping(
                    claim_text="A method...",
                    primary_ipc="INVALID",  # bad code
                    secondary_ipc=[],
                    cpc_code="",
                    confidence=0.5,
                    rationale="test",
                    is_valid_ipc=True,  # Will be corrected by post-processing
                ),
            ],
            top_ipc_codes=["INVALID"],
            search_keywords=["test"] * 10,
            classification_summary="test",
        )

        mock_client = MagicMock()
        mock_client.complete_json = AsyncMock(return_value=bad_classification)

        result = await classify_ipc(
            sample_claims, "test", client=mock_client
        )

        assert result.mappings[0].is_valid_ipc is False
