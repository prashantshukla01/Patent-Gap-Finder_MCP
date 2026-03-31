"""Text preparation for embedding — cleaning, truncation, field prefixing.

Prepares patent abstracts and research claims for sentence-transformers
encoding with field-specific prefixes for better semantic disambiguation.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from patent_gap_finder.db.models import ExtractedClaim, PatentRecord

MAX_TEXT_LENGTH = 512


def clean_text(text: str) -> str:
    """Clean text for embedding.

    - Strip HTML tags
    - Replace LaTeX math notation with plain text
    - Normalize whitespace
    - Remove non-ASCII control characters
    """
    if not text:
        return ""

    # Strip HTML tags
    text = re.sub(r"<[^>]+>", "", text)

    # Replace common LaTeX patterns
    text = re.sub(r"\$([^$]+)\$", r"\1", text)  # inline math
    text = re.sub(r"\\frac\{([^}]*)\}\{([^}]*)\}", r"\1/\2", text)
    text = re.sub(r"\\(?:text|mathrm|mathbf)\{([^}]*)\}", r"\1", text)
    text = re.sub(r"\\[a-zA-Z]+", " ", text)  # remaining LaTeX commands
    text = re.sub(r"[{}^_]", " ", text)  # LaTeX special chars

    # Remove non-ASCII control characters (keep printable + common unicode)
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]", "", text)

    # Normalize whitespace
    text = re.sub(r"\s+", " ", text).strip()

    return text


def prepare_patent_text(patent) -> str:
    """Prepare a patent for embedding.

    Combines title + abstract with 'patent abstract:' prefix.
    Truncates to MAX_TEXT_LENGTH characters.
    """
    title = getattr(patent, "title", "") or ""
    abstract = getattr(patent, "abstract", "") or ""

    combined = f"{title}. {abstract}".strip()
    cleaned = clean_text(combined)
    truncated = cleaned[:MAX_TEXT_LENGTH]

    return f"patent abstract: {truncated}"


def prepare_claim_text(claim) -> str:
    """Prepare a claim for embedding.

    Prefixes with 'research claim:' for semantic disambiguation.
    Claims are already concise — no truncation needed.
    """
    text = getattr(claim, "claim_text", "") or ""
    cleaned = clean_text(text)
    return f"research claim: {cleaned}"


def batch_prepare_patents(patents: list) -> list[str]:
    """Prepare a batch of patents for embedding."""
    return [prepare_patent_text(p) for p in patents]


def batch_prepare_claims(claims: list) -> list[str]:
    """Prepare a batch of claims for embedding."""
    return [prepare_claim_text(c) for c in claims]
