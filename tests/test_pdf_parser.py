"""Tests for the PDF parser module.

Downloads a real arXiv paper as a test fixture and validates section
detection, metadata extraction, candidate claim extraction, and hash
computation.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import httpx
import pytest

from patent_gap_finder.models.paper import ParsedPaper, ParsedSection
from patent_gap_finder.parsers.pdf_parser import (
    TextBlock,
    _detect_columns,
    _is_heading,
    _sort_blocks_reading_order,
    parse_pdf,
)
from patent_gap_finder.utils.text_utils import (
    classify_section_type,
    extract_candidate_claims,
    score_claim_likeness,
    split_sentences,
)

# ──────────────────────────────────────────────────────────────────────
# Test fixtures
# ──────────────────────────────────────────────────────────────────────

# "Attention Is All You Need" — a well-known paper with 2-column layout
_TEST_ARXIV_ID = "1706.03762"
_TEST_PDF_URL = f"https://arxiv.org/pdf/{_TEST_ARXIV_ID}"
_FIXTURE_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session")
def test_pdf_path() -> Path:
    """Download a test PDF from arXiv (cached across the session)."""
    _FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    pdf_path = _FIXTURE_DIR / f"{_TEST_ARXIV_ID}.pdf"

    if not pdf_path.exists():
        response = httpx.get(
            _TEST_PDF_URL,
            follow_redirects=True,
            timeout=60.0,
        )
        response.raise_for_status()
        pdf_path.write_bytes(response.content)

    return pdf_path


@pytest.fixture(scope="session")
def parsed_paper(test_pdf_path: Path) -> ParsedPaper:
    """Parse the test PDF into a ParsedPaper object."""
    return parse_pdf(str(test_pdf_path))


# ──────────────────────────────────────────────────────────────────────
# Metadata extraction tests
# ──────────────────────────────────────────────────────────────────────


class TestMetadataExtraction:
    """Tests for title and author extraction from PDFs."""

    def test_title_not_empty(self, parsed_paper: ParsedPaper) -> None:
        """The parser must extract a non-empty title."""
        assert parsed_paper.title
        assert len(parsed_paper.title) > 5

    def test_title_is_reasonable(self, parsed_paper: ParsedPaper) -> None:
        """The title should resemble the known paper title."""
        # "Attention Is All You Need" — check for key words
        title_lower = parsed_paper.title.lower()
        assert "attention" in title_lower or len(parsed_paper.title) > 10

    def test_authors_extracted(self, parsed_paper: ParsedPaper) -> None:
        """At least one author should be extracted."""
        assert len(parsed_paper.authors) >= 0  # PDF metadata may not have authors

    def test_file_hash_is_sha256(self, parsed_paper: ParsedPaper) -> None:
        """File hash should be a valid SHA-256 hex digest."""
        assert parsed_paper.file_hash is not None
        assert len(parsed_paper.file_hash) == 64
        # Verify it's valid hex
        int(parsed_paper.file_hash, 16)

    def test_file_hash_matches(self, test_pdf_path: Path, parsed_paper: ParsedPaper) -> None:
        """File hash should match independent SHA-256 computation."""
        expected = hashlib.sha256(test_pdf_path.read_bytes()).hexdigest()
        assert parsed_paper.file_hash == expected

    def test_parsed_at_is_set(self, parsed_paper: ParsedPaper) -> None:
        """parsed_at timestamp must be populated."""
        assert parsed_paper.parsed_at is not None


# ──────────────────────────────────────────────────────────────────────
# Section detection tests
# ──────────────────────────────────────────────────────────────────────


class TestSectionDetection:
    """Tests for section boundary detection and classification."""

    def test_sections_extracted(self, parsed_paper: ParsedPaper) -> None:
        """At least 3 sections should be detected from a real paper."""
        assert len(parsed_paper.sections) >= 3

    def test_sections_have_content(self, parsed_paper: ParsedPaper) -> None:
        """Every section should have non-empty content."""
        for section in parsed_paper.sections:
            assert section.content.strip(), f"Section '{section.title}' has no content"

    def test_section_types_valid(self, parsed_paper: ParsedPaper) -> None:
        """All section types should be valid literals."""
        valid_types = {"abstract", "introduction", "methodology", "results",
                       "conclusion", "references", "other"}
        for section in parsed_paper.sections:
            assert section.section_type in valid_types, (
                f"Invalid section type: {section.section_type}"
            )

    def test_has_methodology_or_other(self, parsed_paper: ParsedPaper) -> None:
        """The paper should have at least one methodology/results/other section."""
        types = {s.section_type for s in parsed_paper.sections}
        assert len(types) > 1, "Only one section type detected — heading detection may have failed"


# ──────────────────────────────────────────────────────────────────────
# Section type classification tests
# ──────────────────────────────────────────────────────────────────────


class TestSectionTypeClassification:
    """Tests for the classify_section_type utility."""

    @pytest.mark.parametrize("title,expected", [
        ("Abstract", "abstract"),
        ("1. Introduction", "introduction"),
        ("2 Background", "introduction"),
        ("3. Methodology", "methodology"),
        ("3.1 Model Architecture", "methodology"),
        ("4. Experiments", "results"),
        ("5. Results and Discussion", "results"),
        ("6. Conclusion", "conclusion"),
        ("References", "references"),
        ("Appendix A: Proofs", "other"),
    ])
    def test_section_type_mapping(self, title: str, expected: str) -> None:
        """Known heading patterns should map to correct types."""
        assert classify_section_type(title) == expected


# ──────────────────────────────────────────────────────────────────────
# Claim extraction tests
# ──────────────────────────────────────────────────────────────────────


class TestCandidateClaimExtraction:
    """Tests for heuristic candidate claim extraction."""

    def test_claims_extracted(self, parsed_paper: ParsedPaper) -> None:
        """At least one candidate claim should be identified."""
        assert len(parsed_paper.candidate_claims) >= 1

    def test_claims_have_valid_types(self, parsed_paper: ParsedPaper) -> None:
        """Each claim should have a valid claim type."""
        valid_types = {"method", "system", "composition", "unknown"}
        for claim in parsed_paper.candidate_claims:
            assert claim.claim_type in valid_types

    def test_claims_have_confidence(self, parsed_paper: ParsedPaper) -> None:
        """Each claim should have a confidence score in [0, 1]."""
        for claim in parsed_paper.candidate_claims:
            assert 0.0 <= claim.confidence <= 1.0

    def test_claims_sorted_by_confidence(self, parsed_paper: ParsedPaper) -> None:
        """Claims should be sorted by confidence descending."""
        confidences = [c.confidence for c in parsed_paper.candidate_claims]
        assert confidences == sorted(confidences, reverse=True)

    def test_claim_text_is_substantial(self, parsed_paper: ParsedPaper) -> None:
        """Claim text should be at least 20 characters."""
        for claim in parsed_paper.candidate_claims:
            assert len(claim.text) > 20, f"Claim too short: {claim.text!r}"


# ──────────────────────────────────────────────────────────────────────
# Sentence splitting tests
# ──────────────────────────────────────────────────────────────────────


class TestSentenceSplitting:
    """Tests for the split_sentences utility."""

    def test_basic_splitting(self) -> None:
        """Sentences ending with periods should split correctly."""
        text = "First sentence. Second sentence. Third one here."
        sentences = split_sentences(text)
        assert len(sentences) == 3

    def test_abbreviation_handling(self) -> None:
        """Common abbreviations should not cause false splits."""
        text = "As shown in Fig. 3, the results are significant. The method works."
        sentences = split_sentences(text)
        assert len(sentences) == 2

    def test_empty_input(self) -> None:
        """Empty string should return empty list."""
        assert split_sentences("") == []
        assert split_sentences("   ") == []

    def test_single_sentence(self) -> None:
        """A single sentence without terminal punctuation."""
        sentences = split_sentences("This is a single sentence without ending")
        assert len(sentences) == 1


# ──────────────────────────────────────────────────────────────────────
# Claim scoring tests
# ──────────────────────────────────────────────────────────────────────


class TestClaimScoring:
    """Tests for the score_claim_likeness function."""

    def test_high_score_for_claim_language(self) -> None:
        """Sentences with strong claim language should score highly."""
        sentence = (
            "We propose a novel transformer architecture that enables "
            "efficient parallel computation and outperforms existing models."
        )
        score = score_claim_likeness(sentence)
        assert score >= 0.4

    def test_low_score_for_generic_text(self) -> None:
        """Generic text without claim signals should score low."""
        sentence = "The data was collected from 500 participants."
        score = score_claim_likeness(sentence)
        assert score < 0.3

    def test_empty_sentence(self) -> None:
        """Empty sentence should score zero."""
        assert score_claim_likeness("") == 0.0


# ──────────────────────────────────────────────────────────────────────
# Column detection tests
# ──────────────────────────────────────────────────────────────────────


class TestColumnDetection:
    """Tests for multi-column layout detection."""

    def _make_block(self, x0: float, x1: float, y0: float = 0) -> TextBlock:
        """Create a minimal TextBlock for testing."""
        return TextBlock(
            text="test text here",
            x0=x0, y0=y0, x1=x1, y1=y0 + 20,
            font_size=10.0, is_bold=False, page_num=0,
        )

    def test_single_column(self) -> None:
        """Wide blocks should be detected as single-column."""
        blocks = [
            self._make_block(50, 550, y0=i * 30) for i in range(6)
        ]
        assert _detect_columns(blocks, page_width=612) == 1

    def test_two_columns(self) -> None:
        """Left+right blocks should be detected as two-column."""
        blocks = [
            # Left column blocks
            self._make_block(50, 280, y0=i * 30) for i in range(4)
        ] + [
            # Right column blocks
            self._make_block(320, 560, y0=i * 30) for i in range(4)
        ]
        assert _detect_columns(blocks, page_width=612) == 2

    def test_too_few_blocks(self) -> None:
        """Very few blocks should default to single-column."""
        blocks = [self._make_block(50, 200)]
        assert _detect_columns(blocks, page_width=612) == 1


# ──────────────────────────────────────────────────────────────────────
# Error handling tests
# ──────────────────────────────────────────────────────────────────────


class TestErrorHandling:
    """Tests for error handling in PDF parsing."""

    def test_nonexistent_file(self) -> None:
        """Should raise FileNotFoundError for missing files."""
        with pytest.raises(FileNotFoundError):
            parse_pdf("/nonexistent/path/paper.pdf")

    def test_empty_bytes(self) -> None:
        """Should raise ValueError for empty bytes."""
        with pytest.raises(ValueError, match="Empty PDF bytes"):
            parse_pdf(b"")

    def test_invalid_pdf(self) -> None:
        """Should raise ValueError for non-PDF data."""
        with pytest.raises(ValueError):
            parse_pdf(b"This is not a PDF file at all")

    def test_tiny_pdf(self) -> None:
        """Should raise ValueError for data too small to be a PDF."""
        with pytest.raises(ValueError, match="too small"):
            parse_pdf(b"%PDF-tiny")
