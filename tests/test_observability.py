"""Unit tests for Langfuse observability, telemetry, and evaluation metrics."""

from __future__ import annotations

from unittest.mock import MagicMock, patch
import numpy as np
import pytest

from observability.tracer import (
    is_langfuse_enabled,
    get_langfuse_client,
    trace_tool,
    trace_span,
    log_score,
)
from observability.metrics import (
    compute_clustering_metrics,
    compute_whitespace_metrics,
    evaluate_claim_structure,
)


class TestObservabilityFallback:
    """Test safe graceful degradation when Langfuse credentials are not provided."""

    def test_disabled_by_default(self, monkeypatch):
        monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
        monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
        assert is_langfuse_enabled() is False

    @pytest.mark.asyncio
    async def test_trace_tool_async_noop(self, monkeypatch):
        monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
        monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)

        @trace_tool("test_async_tool")
        async def dummy_async(x: int, session_id: str = "sess_123"):
            return {"result": x * 2}

        res = await dummy_async(5, session_id="sess_123")
        assert res == {"result": 10}

    def test_trace_tool_sync_noop(self, monkeypatch):
        monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
        monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)

        @trace_tool("test_sync_tool")
        def dummy_sync(x: int):
            return x + 5

        res = dummy_sync(10)
        assert res == 15

    def test_trace_span_noop(self):
        with trace_span("dummy_span", metadata={"foo": "bar"}) as span:
            assert span is None

    def test_log_score_noop(self):
        # Should execute safely without raising any exceptions
        log_score("silhouette_score", 0.85, comment="test score")


class TestClusteringMetrics:
    """Test clustering metrics and silhouette score computation."""

    def test_empty_clustering(self):
        metrics = compute_clustering_metrics(np.empty((0, 384)), np.empty((0,)))
        assert metrics["cluster_count"] == 0.0
        assert metrics["silhouette_score"] == 0.0
        assert metrics["noise_ratio"] == 0.0

    def test_synthetic_clusters_silhouette(self):
        # Create 2 clear synthetic clusters in 384-D space
        c1 = np.ones((10, 384), dtype=np.float32)
        c2 = -np.ones((10, 384), dtype=np.float32)
        noise = np.zeros((2, 384), dtype=np.float32)

        embeddings = np.vstack([c1, c2, noise])
        labels = np.array([0] * 10 + [1] * 10 + [-1] * 2)

        metrics = compute_clustering_metrics(embeddings, labels)
        assert metrics["cluster_count"] == 2.0
        assert metrics["noise_count"] == 2.0
        assert metrics["noise_ratio"] == round(2 / 22, 4)
        assert metrics["silhouette_score"] > 0.5  # High separation


class TestWhitespaceMetrics:
    """Test whitespace opportunity metrics."""

    def test_empty_whitespace(self):
        metrics = compute_whitespace_metrics([])
        assert metrics["opportunity_count"] == 0.0

    def test_whitespace_metrics_calculation(self):
        opportunities = [
            {"gap_score": 0.85, "distance_to_nearest": 0.65},
            {"gap_score": 0.75, "distance_to_nearest": 0.45},
        ]
        metrics = compute_whitespace_metrics(opportunities)
        assert metrics["opportunity_count"] == 2.0
        assert metrics["avg_confidence"] == 0.8
        assert metrics["min_distance"] == 0.45


class TestClaimStructureEvaluator:
    """Test USPTO patent claim drafting structural evaluation."""

    def test_valid_independent_claim(self):
        claim = """
        1. A method for training a neural network model, comprising:
           receiving a training dataset comprising input tensors;
           applying a sparse attention mask across intermediate activation layers; and
           updating weight parameters using stochastic gradient descent.
        """
        eval_res = evaluate_claim_structure(claim)
        assert eval_res["is_valid"] is True
        assert eval_res["has_preamble"] is True
        assert eval_res["has_transition"] is True
        assert eval_res["element_count"] >= 2
        assert eval_res["structural_score"] >= 0.8

    def test_invalid_claim_missing_transition(self):
        claim = "A machine learning system that processes data."
        eval_res = evaluate_claim_structure(claim)
        assert eval_res["is_valid"] is False
        assert eval_res["has_transition"] is False


class TestMockedLangfuseDispatch:
    """Test trace and span dispatch when Langfuse client is active."""

    @patch("observability.tracer.get_langfuse_client")
    @pytest.mark.asyncio
    async def test_trace_tool_dispatch(self, mock_get_client):
        mock_client = MagicMock()
        mock_trace = MagicMock()
        mock_client.start_observation.return_value = mock_trace
        mock_get_client.return_value = mock_client

        @trace_tool("test_dispatched_tool")
        async def dummy(val: str, session_id: str = "sess-xyz"):
            return {"output": val}

        result = await dummy("hello", session_id="sess-xyz")
        assert result == {"output": "hello"}
        mock_client.start_observation.assert_called_once()
        mock_trace.update.assert_called_once()
