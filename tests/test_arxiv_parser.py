"""Tests for the arXiv parser module.

Tests arXiv ID normalization, metadata fetching, and the full
parse pipeline.  Network tests require internet access and are
marked accordingly.
"""

from __future__ import annotations

import pytest

from patent_gap_finder.parsers.arxiv_parser import (
    extract_arxiv_id,
    fetch_arxiv_metadata,
    is_arxiv_source,
    parse_arxiv,
)


# ──────────────────────────────────────────────────────────────────────
# arXiv ID extraction / normalization tests
# ──────────────────────────────────────────────────────────────────────


class TestArxivIdExtraction:
    """Tests for extract_arxiv_id and is_arxiv_source."""

    @pytest.mark.parametrize("input_str,expected", [
        # Bare new-style IDs
        ("2301.07041", "2301.07041"),
        ("2301.07041v2", "2301.07041v2"),
        ("1706.03762", "1706.03762"),
        # Abs URLs
        ("https://arxiv.org/abs/2301.07041", "2301.07041"),
        ("http://arxiv.org/abs/2301.07041v1", "2301.07041v1"),
        # PDF URLs
        ("https://arxiv.org/pdf/2301.07041", "2301.07041"),
        ("https://arxiv.org/pdf/2301.07041v2.pdf", "2301.07041v2"),
        ("https://arxiv.org/pdf/2301.07041.pdf", "2301.07041"),
        # Old-style IDs
        ("hep-ph/9905221", "hep-ph/9905221"),
        ("math.AG/0601001v1", "math.AG/0601001v1"),
    ])
    def test_valid_ids(self, input_str: str, expected: str) -> None:
        """Valid arXiv references should parse correctly."""
        assert extract_arxiv_id(input_str) == expected

    def test_invalid_id_raises(self) -> None:
        """Non-arXiv strings should raise ValueError."""
        with pytest.raises(ValueError, match="Could not extract arXiv ID"):
            extract_arxiv_id("not-an-arxiv-id")

    def test_empty_string_raises(self) -> None:
        """Empty string should raise ValueError."""
        with pytest.raises(ValueError):
            extract_arxiv_id("")

    @pytest.mark.parametrize("input_str,expected", [
        ("2301.07041", True),
        ("https://arxiv.org/abs/2301.07041", True),
        ("https://arxiv.org/pdf/2301.07041", True),
        ("/path/to/paper.pdf", False),
        ("some random text", False),
    ])
    def test_is_arxiv_source(self, input_str: str, expected: bool) -> None:
        """is_arxiv_source should correctly identify arXiv references."""
        assert is_arxiv_source(input_str) == expected


# ──────────────────────────────────────────────────────────────────────
# Metadata fetching tests (require network)
# ──────────────────────────────────────────────────────────────────────


class TestArxivMetadataFetch:
    """Tests for arXiv API metadata fetching.  Requires network access."""

    @pytest.mark.asyncio
    async def test_fetch_known_paper(self) -> None:
        """Fetching metadata for a known paper should return valid data."""
        # "Attention Is All You Need"
        metadata = await fetch_arxiv_metadata("1706.03762")

        assert metadata["title"]
        assert "attention" in metadata["title"].lower()
        assert len(metadata["authors"]) > 0
        assert metadata["abstract"]
        assert len(metadata["abstract"]) > 50

    @pytest.mark.asyncio
    async def test_fetch_returns_categories(self) -> None:
        """Categories should be present in the metadata."""
        metadata = await fetch_arxiv_metadata("1706.03762")
        assert isinstance(metadata["categories"], list)

    @pytest.mark.asyncio
    async def test_fetch_nonexistent_paper(self) -> None:
        """Fetching a nonexistent paper should raise ValueError."""
        with pytest.raises(ValueError):
            await fetch_arxiv_metadata("9999.99999")


# ──────────────────────────────────────────────────────────────────────
# Full pipeline tests (require network)
# ──────────────────────────────────────────────────────────────────────


class TestArxivFullPipeline:
    """End-to-end tests for parse_arxiv.  Requires network access."""

    @pytest.mark.asyncio
    async def test_parse_by_id(self) -> None:
        """Parsing by bare arXiv ID should produce a valid ParsedPaper."""
        paper = await parse_arxiv("1706.03762")

        assert paper.title
        assert "attention" in paper.title.lower()
        assert len(paper.authors) > 0
        assert paper.abstract
        assert len(paper.sections) >= 3
        assert paper.source_url == "https://arxiv.org/abs/1706.03762"
        assert paper.file_hash is not None

    @pytest.mark.asyncio
    async def test_parse_by_abs_url(self) -> None:
        """Parsing by abs URL should work identically to bare ID."""
        paper = await parse_arxiv("https://arxiv.org/abs/1706.03762")
        assert paper.title
        assert paper.source_url == "https://arxiv.org/abs/1706.03762"

    @pytest.mark.asyncio
    async def test_candidate_claims_present(self) -> None:
        """The full pipeline should extract candidate claims."""
        paper = await parse_arxiv("1706.03762")
        assert len(paper.candidate_claims) >= 1

        # Claims should have valid structure
        for claim in paper.candidate_claims:
            assert claim.text
            assert 0.0 <= claim.confidence <= 1.0
            assert claim.claim_type in {"method", "system", "composition", "unknown"}
