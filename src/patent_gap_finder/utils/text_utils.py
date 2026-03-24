"""Text processing utilities for candidate claim extraction.

This module provides heuristic-based extraction of patentable claims from
research paper text *without* any AI/LLM calls. It uses weighted scoring
across multiple signal dimensions to surface sentences most likely to
describe novel technical contributions.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from patent_gap_finder.models.paper import CandidateClaim, ParsedSection


# ──────────────────────────────────────────────────────────────────────
# Signal phrase lexicons (lowercased for matching)
# ──────────────────────────────────────────────────────────────────────

CLAIM_SIGNAL_PHRASES: list[str] = [
    "we propose",
    "we present",
    "we introduce",
    "we describe",
    "we develop",
    "we design",
    "our method",
    "our approach",
    "our system",
    "our framework",
    "our model",
    "our technique",
    "our algorithm",
    "the proposed",
    "the system",
    "this paper presents",
    "this work introduces",
    "this work proposes",
    "in this paper, we",
    "in this work, we",
    "novel",
    "a new method",
    "a new approach",
    "a new framework",
    "a new technique",
    "a new algorithm",
    "method for",
    "approach to",
    "technique for",
    "framework for",
    "system for",
    "apparatus for",
    "comprising",
    "consists of",
    "characterized by",
    "configured to",
    "adapted to",
    "operable to",
    "key contribution",
    "main contribution",
    "primary contribution",
    "contribution of this",
]

TECHNICAL_VERBS: list[str] = [
    "classifies",
    "detects",
    "generates",
    "optimizes",
    "enables",
    "computes",
    "transforms",
    "encodes",
    "decodes",
    "predicts",
    "estimates",
    "extracts",
    "identifies",
    "segments",
    "clusters",
    "aggregates",
    "maps",
    "reduces",
    "accelerates",
    "improves",
    "outperforms",
    "achieves",
    "leverages",
    "utilizes",
    "employs",
    "integrates",
    "combines",
    "automates",
    "enhances",
    "mitigates",
    "minimizes",
    "maximizes",
    "synthesizes",
    "reconstructs",
    "processes",
    "classify",
    "detect",
    "generate",
    "optimize",
    "enable",
    "compute",
    "transform",
    "encode",
    "decode",
    "predict",
    "estimate",
    "extract",
    "identify",
    "segment",
    "cluster",
    "aggregate",
    "reduce",
    "accelerate",
    "improve",
    "outperform",
    "achieve",
    "leverage",
    "utilize",
    "employ",
    "integrate",
    "combine",
    "automate",
    "enhance",
    "mitigate",
    "minimize",
    "maximize",
    "synthesize",
    "reconstruct",
    "process",
]

# Patterns for claim-type classification
_METHOD_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\b(method|approach|technique|algorithm|procedure|process|pipeline|workflow)\b", re.I),
    re.compile(r"\b(step|steps|stage|stages)\b", re.I),
    re.compile(r"\bwe (propose|present|introduce|develop|design)\b", re.I),
]

_SYSTEM_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\b(system|framework|platform|architecture|infrastructure|module|device|apparatus|tool)\b", re.I),
    re.compile(r"\b(compris(es|ing)|consist(s|ing) of|configured to|coupled to)\b", re.I),
]

_COMPOSITION_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\b(composition|compound|formulation|mixture|material|alloy|polymer|substance)\b", re.I),
    re.compile(r"\b(comprising .* and .*)\b", re.I),
]

# ──────────────────────────────────────────────────────────────────────
# Sentence splitting
# ──────────────────────────────────────────────────────────────────────

# Abbreviations that should NOT trigger sentence boundaries
_ABBREVIATIONS = {
    "dr", "mr", "mrs", "ms", "prof", "sr", "jr",
    "inc", "ltd", "co", "corp", "dept", "univ",
    "vol", "no", "fig", "figs", "eq", "eqs",
    "ref", "refs", "sec", "secs", "ch", "chs",
    "ed", "eds", "et", "al", "vs", "approx",
    "i.e", "e.g", "viz", "cf", "etc",
}

# Regex: split on period/question/exclamation followed by whitespace + uppercase,
# but avoid splitting on known abbreviations or decimal numbers.
_SENTENCE_BOUNDARY = re.compile(
    r'(?<=[.!?])\s+(?=[A-Z])'
)


def split_sentences(text: str) -> list[str]:
    """Split *text* into sentences using robust regex heuristics.

    Handles common academic abbreviations (e.g., ``et al.``, ``Fig.``,
    ``i.e.``) and avoids splitting on decimal numbers or initials.

    Args:
        text: Raw text to split.

    Returns:
        List of sentence strings with whitespace normalized.
    """
    if not text or not text.strip():
        return []

    # Normalize whitespace (collapse newlines, tabs, multiple spaces)
    text = re.sub(r"\s+", " ", text).strip()

    # Use one-dot-leader (U+2024) as a safe placeholder for periods we want to protect
    _DOT_PLACEHOLDER = "\u2024"  # ․

    # Protect known abbreviations by temporarily replacing their periods
    protected = text
    for abbr in _ABBREVIATIONS:
        # Match abbreviation followed by period and space
        pattern = re.compile(rf"\b{re.escape(abbr)}\.", re.I)
        protected = pattern.sub(abbr.replace(".", "") + _DOT_PLACEHOLDER, protected)

    # Protect decimal numbers (e.g., 3.14)
    protected = re.sub(r"(\d)\.(\d)", rf"\1{_DOT_PLACEHOLDER}\2", protected)

    # Split on sentence boundaries
    raw_sentences = _SENTENCE_BOUNDARY.split(protected)

    # Restore protected periods and clean up
    sentences: list[str] = []
    for s in raw_sentences:
        s = s.replace("\u2024", ".").strip()
        if len(s) > 5:  # skip tiny fragments
            sentences.append(s)

    return sentences


# ──────────────────────────────────────────────────────────────────────
# Claim scoring
# ──────────────────────────────────────────────────────────────────────

def _count_signal_phrases(sentence_lower: str) -> int:
    """Count how many claim signal phrases appear in the lowercased sentence."""
    return sum(1 for phrase in CLAIM_SIGNAL_PHRASES if phrase in sentence_lower)


def _count_technical_verbs(sentence_lower: str) -> int:
    """Count distinct technical verbs present in the lowercased sentence."""
    count = 0
    for verb in TECHNICAL_VERBS:
        # Use word-boundary matching to avoid partial matches
        if re.search(rf"\b{verb}\b", sentence_lower):
            count += 1
    return count


def score_claim_likeness(sentence: str) -> float:
    """Compute a 0.0–1.0 score indicating how likely *sentence* is a patentable claim.

    The scoring function combines four weighted dimensions:

    1. **Signal phrase density** (weight 0.40) — presence of canonical claim
       language like "we propose", "method for", "comprising".
    2. **Technical verb density** (weight 0.25) — presence of action verbs
       common in patent claims (detects, optimizes, generates).
    3. **Sentence length fit** (weight 0.20) — optimal length is 20–60 words;
       too short or too long sentences are penalized.
    4. **Structural indicators** (weight 0.15) — numbered/bulleted items,
       semicolons (common in patent claims), specific quantitative results.

    Args:
        sentence: A single sentence to score.

    Returns:
        Float in [0.0, 1.0].
    """
    if not sentence or not sentence.strip():
        return 0.0

    lower = sentence.lower().strip()
    words = sentence.split()
    word_count = len(words)

    # ── Dimension 1: Signal phrase density (0–1) ──
    signal_count = _count_signal_phrases(lower)
    signal_score = min(signal_count / 3.0, 1.0)  # cap at 3 matches

    # ── Dimension 2: Technical verb density (0–1) ──
    verb_count = _count_technical_verbs(lower)
    verb_score = min(verb_count / 3.0, 1.0)

    # ── Dimension 3: Sentence length fitness (0–1) ──
    if word_count < 10:
        length_score = 0.1
    elif word_count < 15:
        length_score = 0.4
    elif 15 <= word_count <= 80:
        # Peak at 20–60 words
        if 20 <= word_count <= 60:
            length_score = 1.0
        elif word_count < 20:
            length_score = 0.7
        else:  # 60–80
            length_score = 0.8
    else:
        length_score = 0.3  # very long sentences

    # ── Dimension 4: Structural indicators (0–1) ──
    struct_score = 0.0
    # Semicolons (common in patent claim sub-clauses)
    if ";" in sentence:
        struct_score += 0.3
    # Contains quantitative results (numbers + %)
    if re.search(r"\d+\.?\d*\s*%", sentence):
        struct_score += 0.2
    # Starts with a gerund (e.g., "A method comprising …")
    if re.match(r"^(a|an|the)\s+\w+\s+(comprising|including|consisting)", lower):
        struct_score += 0.5
    # Contains comparison language
    if re.search(r"\b(compared to|outperform|surpass|exceed|better than|superior)\b", lower):
        struct_score += 0.2
    # Contains "wherein" (very patent-specific)
    if "wherein" in lower:
        struct_score += 0.3
    struct_score = min(struct_score, 1.0)

    # ── Weighted combination ──
    raw_score = (
        0.40 * signal_score
        + 0.25 * verb_score
        + 0.20 * length_score
        + 0.15 * struct_score
    )

    return round(min(raw_score, 1.0), 3)


# ──────────────────────────────────────────────────────────────────────
# Claim-type classification
# ──────────────────────────────────────────────────────────────────────

def classify_claim_type(sentence: str) -> str:
    """Classify a sentence into a patent claim category.

    Uses regex pattern matching against known patterns for three claim
    types.  Falls back to ``"unknown"`` if no patterns match.

    Args:
        sentence: The sentence to classify.

    Returns:
        One of ``"method"``, ``"system"``, ``"composition"``, or ``"unknown"``.
    """
    method_hits = sum(1 for p in _METHOD_PATTERNS if p.search(sentence))
    system_hits = sum(1 for p in _SYSTEM_PATTERNS if p.search(sentence))
    composition_hits = sum(1 for p in _COMPOSITION_PATTERNS if p.search(sentence))

    scores = {
        "method": method_hits,
        "system": system_hits,
        "composition": composition_hits,
    }

    best_type = max(scores, key=scores.get)  # type: ignore[arg-type]
    if scores[best_type] == 0:
        return "unknown"
    return best_type


# ──────────────────────────────────────────────────────────────────────
# Top-level candidate extraction
# ──────────────────────────────────────────────────────────────────────

def extract_candidate_claims(
    sections: list[ParsedSection],
    top_n: int = 10,
) -> list[CandidateClaim]:
    """Extract the top-N candidate patentable claims from parsed sections.

    Processes every sentence in every section, scores it for claim-likeness,
    classifies its type, and returns the highest-scoring candidates.  Sections
    with type ``"references"`` are skipped.

    Args:
        sections: List of :class:`ParsedSection` objects.
        top_n: Maximum number of claims to return.

    Returns:
        List of :class:`CandidateClaim` sorted by confidence descending.
    """
    from patent_gap_finder.models.paper import CandidateClaim as ClaimModel

    scored: list[tuple[float, str, str, str]] = []  # (score, text, section, type)

    for section in sections:
        # Skip references — they don't contain novel claims
        if section.section_type == "references":
            continue

        sentences = split_sentences(section.content)
        for sent in sentences:
            score = score_claim_likeness(sent)
            if score < 0.10:
                continue  # skip obvious noise
            claim_type = classify_claim_type(sent)
            scored.append((score, sent, section.title, claim_type))

    # Sort by score descending, take top-N
    scored.sort(key=lambda x: x[0], reverse=True)
    top = scored[:top_n]

    return [
        ClaimModel(
            text=text,
            source_section=section_title,
            claim_type=ctype,  # type: ignore[arg-type]
            confidence=score,
        )
        for score, text, section_title, ctype in top
    ]


# ──────────────────────────────────────────────────────────────────────
# Text cleaning helpers
# ──────────────────────────────────────────────────────────────────────

def clean_text(text: str) -> str:
    """Normalize whitespace and remove common PDF extraction artifacts.

    Args:
        text: Raw extracted text.

    Returns:
        Cleaned text string.
    """
    if not text:
        return ""

    # Remove common ligature artifacts
    replacements = {
        "\ufb01": "fi",
        "\ufb02": "fl",
        "\ufb03": "ffi",
        "\ufb04": "ffl",
        "\u2019": "'",
        "\u2018": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u2013": "-",
        "\u2014": "-",
        "\u00ad": "",  # soft hyphen
    }
    for old, new in replacements.items():
        text = text.replace(old, new)

    # Remove hyphenation at line breaks (e.g., "compu-\nter" → "computer")
    text = re.sub(r"(\w)-\s*\n\s*(\w)", r"\1\2", text)

    # Collapse whitespace
    text = re.sub(r"\s+", " ", text).strip()

    return text


def normalize_section_title(title: str) -> str:
    """Normalize a section heading for consistent comparison.

    Strips numbering prefixes (``1.``, ``1.1``, ``A.``) and extra whitespace.

    Args:
        title: Raw section heading text.

    Returns:
        Normalized heading string.
    """
    # Strip common numbering patterns
    title = re.sub(r"^\s*[\dIVXivx]+(\.\d+)*\.?\s*", "", title)
    title = re.sub(r"^\s*[A-Z](\.\d+)*\.?\s+", "", title)
    return title.strip()


def classify_section_type(
    title: str,
) -> str:
    """Infer a section's semantic type from its heading text.

    Args:
        title: The section heading.

    Returns:
        One of the ``ParsedSection.section_type`` literal values.
    """
    normalized = normalize_section_title(title).lower()

    mapping: dict[str, list[str]] = {
        "abstract": ["abstract"],
        "introduction": ["introduction", "background", "motivation", "overview"],
        "methodology": [
            "method", "methodology", "approach", "model", "framework",
            "architecture", "design", "implementation", "system",
            "proposed", "technique", "algorithm",
        ],
        "results": [
            "result", "experiment", "evaluation", "performance",
            "analysis", "comparison", "ablation", "benchmark",
            "finding", "discussion",
        ],
        "conclusion": ["conclusion", "summary", "future work", "concluding"],
        "references": ["reference", "bibliography"],
    }

    for section_type, keywords in mapping.items():
        for kw in keywords:
            if kw in normalized:
                return section_type

    return "other"
