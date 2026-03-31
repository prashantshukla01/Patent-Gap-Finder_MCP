"""Tests for novelty_reasoner — Gemini cluster labeling and novelty assessment."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestLabelCluster:
    @patch("patent_gap_finder.ai.gemini_client.get_gemini_client")
    async def test_returns_label_and_domain(self, mock_get_client):
        from patent_gap_finder.ai.novelty_reasoner import label_cluster

        mock_client = AsyncMock()
        mock_client.complete.return_value = '{"label": "sparse attention methods", "technical_domain": "NLP"}'
        mock_get_client.return_value = mock_client

        result = await label_cluster(
            ["Sparse attention for transformers", "Efficient self-attention"],
            patent_count=10,
        )

        assert result["label"] == "sparse attention methods"
        assert result["technical_domain"] == "NLP"

    @patch("patent_gap_finder.ai.gemini_client.get_gemini_client")
    async def test_prompt_contains_titles(self, mock_get_client):
        from patent_gap_finder.ai.novelty_reasoner import label_cluster

        mock_client = AsyncMock()
        mock_client.complete.return_value = '{"label": "test", "technical_domain": "test"}'
        mock_get_client.return_value = mock_client

        await label_cluster(
            ["Title A", "Title B", "Title C"],
            patent_count=5,
        )

        call_args = mock_client.complete.call_args
        user_prompt = call_args[1]["user"]
        assert "Title A" in user_prompt
        assert "Title B" in user_prompt
        assert "Title C" in user_prompt

    @patch("patent_gap_finder.ai.gemini_client.get_gemini_client")
    async def test_handles_invalid_json(self, mock_get_client):
        from patent_gap_finder.ai.novelty_reasoner import label_cluster

        mock_client = AsyncMock()
        mock_client.complete.return_value = "not json"
        mock_get_client.return_value = mock_client

        result = await label_cluster(["Title"], patent_count=3)
        assert result["label"] == "unknown cluster"


class TestAssessNovelty:
    @patch("patent_gap_finder.ai.gemini_client.get_gemini_client")
    async def test_returns_assessment(self, mock_get_client):
        from patent_gap_finder.ai.novelty_reasoner import assess_novelty

        mock_client = AsyncMock()
        mock_client.complete.return_value = (
            '{"gemini_novelty_assessment": "This claim is novel because...", '
            '"gemini_confidence": 0.85, '
            '"recommended_claim_scope": "broad", '
            '"ipc_whitespace_codes": ["G06N 3/08"], '
            '"key_differentiators": ["sparse attention", "efficiency"]}'
        )
        mock_get_client.return_value = mock_client

        claim = SimpleNamespace(
            claim_text="A method for sparse attention",
            claim_type="method",
            primary_ipc="G06N",
        )

        result = await assess_novelty(
            claim=claim,
            nearest_patents=[
                {"title": "Patent A", "abstract": "Abstract A"},
                {"title": "Patent B", "abstract": "Abstract B"},
            ],
            avg_similarity=0.35,
            nearest_cluster_label="attention mechanisms",
        )

        assert result["gemini_confidence"] == 0.85
        assert result["recommended_claim_scope"] == "broad"
        assert "G06N 3/08" in result["ipc_whitespace_codes"]

    @patch("patent_gap_finder.ai.gemini_client.get_gemini_client")
    async def test_prompt_contains_claim_and_similarity(self, mock_get_client):
        from patent_gap_finder.ai.novelty_reasoner import assess_novelty

        mock_client = AsyncMock()
        mock_client.complete.return_value = (
            '{"gemini_novelty_assessment": "test", "gemini_confidence": 0.5, '
            '"recommended_claim_scope": "medium", "ipc_whitespace_codes": [], '
            '"key_differentiators": []}'
        )
        mock_get_client.return_value = mock_client

        claim = SimpleNamespace(
            claim_text="Novel method XYZ",
            claim_type="method",
            primary_ipc=None,
        )

        await assess_novelty(
            claim=claim,
            nearest_patents=[{"title": "P1", "abstract": "A1"}],
            avg_similarity=0.42,
            nearest_cluster_label="cluster A",
        )

        call_args = mock_client.complete.call_args
        user_prompt = call_args[1]["user"]
        assert "Novel method XYZ" in user_prompt
        assert "0.42" in user_prompt

    @patch("patent_gap_finder.ai.gemini_client.get_gemini_client")
    async def test_interprets_similarity_correctly(self, mock_get_client):
        from patent_gap_finder.ai.novelty_reasoner import assess_novelty

        mock_client = AsyncMock()
        mock_client.complete.return_value = (
            '{"gemini_novelty_assessment": "test", "gemini_confidence": 0.5, '
            '"recommended_claim_scope": "medium", "ipc_whitespace_codes": [], '
            '"key_differentiators": []}'
        )
        mock_get_client.return_value = mock_client

        claim = SimpleNamespace(
            claim_text="test", claim_type="method", primary_ipc=None,
        )

        await assess_novelty(claim, [], avg_similarity=0.2, nearest_cluster_label="x")
        user_prompt = mock_client.complete.call_args[1]["user"]
        assert "very different" in user_prompt

    @patch("patent_gap_finder.ai.gemini_client.get_gemini_client")
    async def test_handles_parse_error(self, mock_get_client):
        from patent_gap_finder.ai.novelty_reasoner import assess_novelty

        mock_client = AsyncMock()
        mock_client.complete.return_value = "invalid json response"
        mock_get_client.return_value = mock_client

        claim = SimpleNamespace(
            claim_text="test", claim_type="method", primary_ipc="G06N",
        )

        result = await assess_novelty(claim, [], avg_similarity=0.3, nearest_cluster_label="x")
        assert result["gemini_confidence"] == 0.5
        assert result["recommended_claim_scope"] == "medium"
