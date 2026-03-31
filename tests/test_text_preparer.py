"""Tests for text_preparer — cleaning, prefixing, truncation."""

from __future__ import annotations

from types import SimpleNamespace

from patent_gap_finder.embeddings.text_preparer import (
    batch_prepare_claims,
    batch_prepare_patents,
    clean_text,
    prepare_claim_text,
    prepare_patent_text,
    MAX_TEXT_LENGTH,
)


class TestCleanText:
    def test_strips_html_tags(self):
        assert clean_text("H<sub>2</sub>O") == "H2O"

    def test_strips_latex_inline_math(self):
        result = clean_text("The equation $x^2 + y$ is used")
        assert "$" not in result
        assert "x" in result

    def test_normalizes_whitespace(self):
        assert clean_text("hello   world\n\nfoo") == "hello world foo"

    def test_removes_control_characters(self):
        result = clean_text("hello\x00world\x1f")
        assert result == "helloworld"

    def test_empty_string(self):
        assert clean_text("") == ""

    def test_none_returns_empty(self):
        assert clean_text(None) == ""


class TestPreparePatentText:
    def test_prepends_prefix(self):
        patent = SimpleNamespace(title="My Patent", abstract="Describes a method")
        result = prepare_patent_text(patent)
        assert result.startswith("patent abstract:")

    def test_combines_title_and_abstract(self):
        patent = SimpleNamespace(title="Title", abstract="Abstract text")
        result = prepare_patent_text(patent)
        assert "Title" in result
        assert "Abstract text" in result

    def test_truncates_long_text(self):
        patent = SimpleNamespace(title="T", abstract="A" * 1000)
        result = prepare_patent_text(patent)
        # Prefix + space + truncated text
        content_after_prefix = result[len("patent abstract: "):]
        assert len(content_after_prefix) <= MAX_TEXT_LENGTH

    def test_handles_missing_abstract(self):
        patent = SimpleNamespace(title="Title Only", abstract=None)
        result = prepare_patent_text(patent)
        assert "Title Only" in result


class TestPrepareClaimText:
    def test_prepends_prefix(self):
        claim = SimpleNamespace(claim_text="A novel method for training")
        result = prepare_claim_text(claim)
        assert result.startswith("research claim:")

    def test_includes_claim_text(self):
        claim = SimpleNamespace(claim_text="Method for neural network optimization")
        result = prepare_claim_text(claim)
        assert "neural network optimization" in result


class TestBatch:
    def test_batch_prepare_patents(self):
        patents = [
            SimpleNamespace(title="P1", abstract="A1"),
            SimpleNamespace(title="P2", abstract="A2"),
        ]
        results = batch_prepare_patents(patents)
        assert len(results) == 2
        assert all(r.startswith("patent abstract:") for r in results)

    def test_batch_prepare_claims(self):
        claims = [
            SimpleNamespace(claim_text="Claim 1"),
            SimpleNamespace(claim_text="Claim 2"),
        ]
        results = batch_prepare_claims(claims)
        assert len(results) == 2
        assert all(r.startswith("research claim:") for r in results)
