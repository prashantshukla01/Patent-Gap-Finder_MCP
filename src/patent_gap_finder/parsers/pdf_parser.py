"""PDF parser using PyMuPDF (fitz) with pdfplumber fallback.

Handles multi-column academic paper layouts (IEEE, ACM) by analyzing text
block positions to reconstruct correct reading order.  Detects section
headings via font size, boldness, and numbering heuristics.
"""

from __future__ import annotations

import hashlib
import logging
import re
import statistics
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import fitz  # PyMuPDF

from patent_gap_finder.models.paper import CandidateClaim, ParsedPaper, ParsedSection
from patent_gap_finder.utils.text_utils import (
    classify_section_type,
    clean_text,
    extract_candidate_claims,
)

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────
# Internal data structures
# ──────────────────────────────────────────────────────────────────────

@dataclass
class TextBlock:
    """A text block extracted from a PDF page with layout metadata."""

    text: str
    x0: float
    y0: float
    x1: float
    y1: float
    font_size: float
    is_bold: bool
    page_num: int
    span_fonts: list[dict] = field(default_factory=list)

    @property
    def width(self) -> float:
        return self.x1 - self.x0

    @property
    def height(self) -> float:
        return self.y1 - self.y0

    @property
    def midpoint_x(self) -> float:
        return (self.x0 + self.x1) / 2.0


@dataclass
class RawSection:
    """Accumulates text blocks belonging to a single section."""

    title: str
    blocks: list[TextBlock] = field(default_factory=list)

    @property
    def content(self) -> str:
        return " ".join(b.text for b in self.blocks if b.text.strip())


# ──────────────────────────────────────────────────────────────────────
# PDF → TextBlock extraction
# ──────────────────────────────────────────────────────────────────────

def _extract_blocks_from_page(page: fitz.Page, page_num: int) -> list[TextBlock]:
    """Extract text blocks with font metadata from a single PDF page.

    Args:
        page: A PyMuPDF page object.
        page_num: Zero-indexed page number.

    Returns:
        List of :class:`TextBlock` objects.
    """
    blocks: list[TextBlock] = []
    page_dict = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)

    for block in page_dict.get("blocks", []):
        if block.get("type") != 0:  # only text blocks
            continue

        block_text_parts: list[str] = []
        font_sizes: list[float] = []
        bold_flags: list[bool] = []
        span_fonts: list[dict] = []

        for line in block.get("lines", []):
            line_text_parts: list[str] = []
            for span in line.get("spans", []):
                text = span.get("text", "")
                if not text.strip():
                    continue
                line_text_parts.append(text)

                size = span.get("size", 10.0)
                font_sizes.append(size)

                font_name = span.get("font", "").lower()
                flags = span.get("flags", 0)
                is_bold = bool(flags & 2**4) or "bold" in font_name
                bold_flags.append(is_bold)

                span_fonts.append({
                    "font": span.get("font", ""),
                    "size": size,
                    "bold": is_bold,
                })

            if line_text_parts:
                block_text_parts.append(" ".join(line_text_parts))

        if not block_text_parts:
            continue

        full_text = " ".join(block_text_parts)
        avg_font_size = statistics.mean(font_sizes) if font_sizes else 10.0
        majority_bold = sum(bold_flags) > len(bold_flags) / 2 if bold_flags else False

        bbox = block.get("bbox", (0, 0, 0, 0))
        blocks.append(TextBlock(
            text=full_text,
            x0=bbox[0],
            y0=bbox[1],
            x1=bbox[2],
            y1=bbox[3],
            font_size=avg_font_size,
            is_bold=majority_bold,
            page_num=page_num,
            span_fonts=span_fonts,
        ))

    return blocks


# ──────────────────────────────────────────────────────────────────────
# Multi-column layout detection and reading-order reconstruction
# ──────────────────────────────────────────────────────────────────────

def _detect_columns(blocks: list[TextBlock], page_width: float) -> int:
    """Detect whether a page uses 1-column or 2-column layout.

    Uses a histogram of block x-midpoints to identify two distinct
    clusters.

    Args:
        blocks: Text blocks from a single page.
        page_width: Page width in points.

    Returns:
        1 or 2 (number of columns detected).
    """
    if len(blocks) < 4:
        return 1

    midpoints = [b.midpoint_x for b in blocks if b.width < page_width * 0.7]
    if len(midpoints) < 4:
        return 1

    # Check if midpoints cluster into two groups (left half vs right half)
    center = page_width / 2.0
    left_count = sum(1 for m in midpoints if m < center - page_width * 0.05)
    right_count = sum(1 for m in midpoints if m > center + page_width * 0.05)

    if left_count >= 2 and right_count >= 2:
        return 2
    return 1


def _sort_blocks_reading_order(
    blocks: list[TextBlock],
    page_width: float,
) -> list[TextBlock]:
    """Sort text blocks into correct reading order, handling multi-column layouts.

    For 2-column layouts, blocks are first separated into left/right columns
    based on their x-midpoint, then sorted top-to-bottom within each column,
    with left column read first.

    Args:
        blocks: Text blocks from a single page.
        page_width: Page width in points.

    Returns:
        Blocks in reading order.
    """
    num_cols = _detect_columns(blocks, page_width)

    if num_cols == 1:
        # Single column: sort top-to-bottom
        return sorted(blocks, key=lambda b: (b.y0, b.x0))

    # Two-column: split at page center
    center = page_width / 2.0
    left: list[TextBlock] = []
    right: list[TextBlock] = []
    full_width: list[TextBlock] = []

    for b in blocks:
        # Full-width blocks (titles, abstracts) span most of the page
        if b.width > page_width * 0.65:
            full_width.append(b)
        elif b.midpoint_x < center:
            left.append(b)
        else:
            right.append(b)

    # Sort each group top-to-bottom
    full_width.sort(key=lambda b: b.y0)
    left.sort(key=lambda b: (b.y0, b.x0))
    right.sort(key=lambda b: (b.y0, b.x0))

    # Interleave: full-width blocks at their y-positions, then left col, then right col
    # For simplicity, put full-width first (usually title/abstract at top),
    # then left column, then right column
    result: list[TextBlock] = []

    # Separate full-width blocks that are above the column content
    if left or right:
        col_top = min(
            (b.y0 for b in left + right),
            default=float("inf"),
        )
        top_full = [b for b in full_width if b.y0 < col_top]
        bottom_full = [b for b in full_width if b.y0 >= col_top]

        result.extend(top_full)
        result.extend(left)
        result.extend(right)
        result.extend(bottom_full)
    else:
        result.extend(full_width)

    return result


# ──────────────────────────────────────────────────────────────────────
# Heading detection
# ──────────────────────────────────────────────────────────────────────

# Common section heading patterns
_NUMBERED_HEADING = re.compile(
    r"^\s*(\d+(\.\d+)*\.?\s+|[IVXivx]+\.?\s+|[A-Z]\.?\s+)"
)

_KNOWN_HEADINGS = {
    "abstract", "introduction", "background", "related work",
    "methodology", "method", "methods", "approach", "model",
    "framework", "architecture", "design", "implementation",
    "system", "proposed", "experiment", "experiments",
    "evaluation", "results", "discussion", "analysis",
    "ablation", "conclusion", "conclusions", "summary",
    "future work", "references", "bibliography",
    "acknowledgment", "acknowledgments", "acknowledgement",
    "appendix",
}


def _is_heading(
    block: TextBlock,
    median_font_size: float,
    page_num: int,
) -> bool:
    """Determine whether a text block is likely a section heading.

    Uses multiple heuristics:
    - Font size significantly larger than the median body text
    - Bold font style
    - Numbered heading pattern (e.g., "1.", "1.1", "II.")
    - ALL CAPS text
    - Known heading keywords
    - Short text length (headings are typically brief)

    Args:
        block: The text block to evaluate.
        median_font_size: Median font size of all body text on the page.
        page_num: Page number (first page has special handling).

    Returns:
        True if the block is likely a heading.
    """
    text = block.text.strip()

    # Skip very short or very long "headings"
    if len(text) < 2 or len(text) > 200:
        return False

    word_count = len(text.split())
    if word_count > 15:
        return False

    score = 0

    # Font size larger than median body text
    if block.font_size > median_font_size * 1.15:
        score += 2

    # Bold text
    if block.is_bold:
        score += 2

    # Numbered heading pattern
    if _NUMBERED_HEADING.match(text):
        score += 2

    # ALL CAPS (and at least 3 chars to avoid "I" or "A")
    text_alpha = re.sub(r"[^A-Za-z\s]", "", text)
    if len(text_alpha) > 3 and text_alpha == text_alpha.upper():
        score += 1

    # Known heading keyword
    normalized = re.sub(r"^\s*[\d.IVXivx]+\.?\s*", "", text).strip().lower()
    if normalized in _KNOWN_HEADINGS:
        score += 2

    # Short text is more likely a heading
    if word_count <= 6:
        score += 1

    return score >= 3


# ──────────────────────────────────────────────────────────────────────
# Metadata extraction (title, authors)
# ──────────────────────────────────────────────────────────────────────

def _extract_metadata_from_pdf(doc: fitz.Document) -> dict:
    """Extract title and authors from PDF metadata fields.

    Args:
        doc: An open PyMuPDF document.

    Returns:
        Dict with ``title`` and ``authors`` keys.
    """
    meta = doc.metadata or {}
    title = meta.get("title", "").strip()
    author_str = meta.get("author", "").strip()

    authors: list[str] = []
    if author_str:
        # Authors may be separated by commas, semicolons, or "and"
        parts = re.split(r"[;,]|\band\b", author_str)
        authors = [a.strip() for a in parts if a.strip()]

    return {"title": title, "authors": authors}


def _extract_metadata_from_first_page(
    blocks: list[TextBlock],
) -> dict:
    """Extract title and authors from first-page visual heuristics.

    Assumes the largest text on the first page is the title, and the
    next block(s) below it (with smaller font) contain author names.

    Args:
        blocks: Text blocks from the first page, in reading order.

    Returns:
        Dict with ``title`` and ``authors`` keys.
    """
    if not blocks:
        return {"title": "", "authors": []}

    # Find the block with the largest font size (likely title)
    title_block = max(blocks[:10], key=lambda b: b.font_size)
    title = title_block.text.strip()

    # Look for author block: just below the title, smaller font
    authors: list[str] = []
    for b in blocks:
        if b.y0 > title_block.y1 and b.font_size < title_block.font_size:
            # Heuristic: author names are typically comma-separated
            candidate = b.text.strip()
            if len(candidate) < 500 and ("," in candidate or "and" in candidate.lower()):
                parts = re.split(r"[;,]|\band\b", candidate)
                authors = [a.strip() for a in parts if a.strip() and len(a.strip()) > 1]
                break

    return {"title": title, "authors": authors}


# ──────────────────────────────────────────────────────────────────────
# Table extraction via pdfplumber (fallback)
# ──────────────────────────────────────────────────────────────────────

def _extract_tables_pdfplumber(pdf_path: str) -> list[dict]:
    """Extract tables from a PDF using pdfplumber.

    This is a fallback for pages with complex table layouts that
    PyMuPDF's text extraction may mangle.

    Args:
        pdf_path: Path to the PDF file.

    Returns:
        List of dicts, each with ``page``, ``table_index``, and ``content`` keys.
    """
    tables: list[dict] = []
    try:
        import pdfplumber

        with pdfplumber.open(pdf_path) as pdf:
            for page_num, page in enumerate(pdf.pages):
                page_tables = page.extract_tables() or []
                for idx, table in enumerate(page_tables):
                    if not table:
                        continue
                    # Convert table rows to text
                    rows = []
                    for row in table:
                        cells = [str(cell).strip() if cell else "" for cell in row]
                        rows.append(" | ".join(cells))
                    content = "\n".join(rows)
                    if content.strip():
                        tables.append({
                            "page": page_num,
                            "table_index": idx,
                            "content": content,
                        })
    except Exception as e:
        logger.warning("pdfplumber table extraction failed: %s", e)

    return tables


# ──────────────────────────────────────────────────────────────────────
# Main parsing pipeline
# ──────────────────────────────────────────────────────────────────────

def _compute_file_hash(data: bytes) -> str:
    """Compute SHA-256 hex digest of PDF bytes.

    Args:
        data: Raw PDF file bytes.

    Returns:
        Hex digest string.
    """
    return hashlib.sha256(data).hexdigest()


def parse_pdf(
    source: str | Path | bytes,
    *,
    extract_tables: bool = True,
    top_n_claims: int = 10,
) -> ParsedPaper:
    """Parse a research paper PDF into a structured :class:`ParsedPaper`.

    Handles multi-column layouts, detects section headings via font
    heuristics, extracts metadata, and identifies candidate patentable
    claims.

    Args:
        source: File path (str or Path), or raw PDF bytes.
        extract_tables: Whether to run the pdfplumber fallback for tables.
        top_n_claims: Number of top candidate claims to return.

    Returns:
        A fully populated :class:`ParsedPaper` object.

    Raises:
        FileNotFoundError: If *source* is a path and the file doesn't exist.
        ValueError: If *source* is empty or the PDF is corrupt/unreadable.
    """
    # ── Load PDF bytes ──
    pdf_bytes: bytes
    pdf_path: Optional[str] = None

    if isinstance(source, bytes):
        if not source:
            raise ValueError("Empty PDF bytes provided.")
        pdf_bytes = source
    else:
        path = Path(source)
        if not path.exists():
            raise FileNotFoundError(f"PDF file not found: {path}")
        if not path.is_file():
            raise ValueError(f"Path is not a file: {path}")
        pdf_bytes = path.read_bytes()
        pdf_path = str(path.resolve())

    if len(pdf_bytes) < 100:
        raise ValueError("PDF data is too small to be a valid document.")

    file_hash = _compute_file_hash(pdf_bytes)

    # ── Open with PyMuPDF ──
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    except Exception as e:
        raise ValueError(f"Failed to open PDF: {e}") from e

    if doc.page_count == 0:
        doc.close()
        raise ValueError("PDF has no pages.")

    # ── Extract metadata ──
    pdf_meta = _extract_metadata_from_pdf(doc)

    # ── Extract all blocks from all pages ──
    all_blocks: list[TextBlock] = []
    first_page_blocks: list[TextBlock] = []

    for page_num in range(doc.page_count):
        page = doc.load_page(page_num)
        page_width = page.rect.width
        page_blocks = _extract_blocks_from_page(page, page_num)
        ordered_blocks = _sort_blocks_reading_order(page_blocks, page_width)

        if page_num == 0:
            first_page_blocks = ordered_blocks

        all_blocks.extend(ordered_blocks)

    doc.close()

    # ── First-page heuristics for metadata ──
    fp_meta = _extract_metadata_from_first_page(first_page_blocks)

    # Merge: prefer non-empty values
    title = pdf_meta["title"] or fp_meta["title"] or "Untitled"
    authors = pdf_meta["authors"] or fp_meta["authors"]

    # Clean title
    title = clean_text(title)

    # ── Compute median font size for heading detection ──
    font_sizes = [b.font_size for b in all_blocks if len(b.text.strip()) > 10]
    median_fs = statistics.median(font_sizes) if font_sizes else 10.0

    # ── Segment into sections ──
    raw_sections: list[RawSection] = []
    current_section = RawSection(title="Preamble")

    for block in all_blocks:
        if _is_heading(block, median_fs, block.page_num):
            # Save the current section if it has content
            if current_section.blocks:
                raw_sections.append(current_section)
            current_section = RawSection(title=block.text.strip())
        else:
            current_section.blocks.append(block)

    # Don't forget the last section
    if current_section.blocks:
        raw_sections.append(current_section)

    # ── Build ParsedSection objects ──
    abstract_text = ""
    sections: list[ParsedSection] = []

    for raw in raw_sections:
        content = clean_text(raw.content)
        if not content:
            continue

        section_type = classify_section_type(raw.title)

        # Capture abstract
        if section_type == "abstract":
            abstract_text = content

        sections.append(ParsedSection(
            title=raw.title,
            content=content,
            section_type=section_type,
        ))

    # If no explicit abstract section was found, check PDF metadata
    if not abstract_text and sections:
        # Sometimes the first non-preamble section is effectively the abstract
        for s in sections:
            if s.section_type == "abstract":
                abstract_text = s.content
                break

    # ── Extract candidate claims ──
    candidate_claims: list[CandidateClaim] = extract_candidate_claims(
        sections, top_n=top_n_claims
    )

    # ── Optionally extract tables via pdfplumber ──
    if extract_tables and pdf_path:
        tables = _extract_tables_pdfplumber(pdf_path)
        if tables:
            logger.info("Extracted %d tables via pdfplumber", len(tables))
            # Append tables as an extra section
            table_content = "\n\n".join(
                f"[Table {t['table_index'] + 1} on page {t['page'] + 1}]\n{t['content']}"
                for t in tables
            )
            sections.append(ParsedSection(
                title="Extracted Tables",
                content=table_content,
                section_type="other",
            ))

    return ParsedPaper(
        title=title,
        authors=authors,
        abstract=abstract_text,
        sections=sections,
        candidate_claims=candidate_claims,
        file_hash=file_hash,
        parsed_at=datetime.now(timezone.utc),
    )
