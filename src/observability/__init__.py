"""Observability and telemetry package for Patent Gap Finder.

Provides Langfuse tracing, span profilers, and automated evaluation metrics
for embeddings, clustering, whitespace discovery, and patent claim quality.
"""

from observability.tracer import (
    get_langfuse_client,
    is_langfuse_enabled,
    log_score,
    trace_span,
    trace_tool,
)
from observability.metrics import (
    compute_clustering_metrics,
    compute_whitespace_metrics,
    evaluate_claim_structure,
)

__all__ = [
    "get_langfuse_client",
    "is_langfuse_enabled",
    "log_score",
    "trace_span",
    "trace_tool",
    "compute_clustering_metrics",
    "compute_whitespace_metrics",
    "evaluate_claim_structure",
]
