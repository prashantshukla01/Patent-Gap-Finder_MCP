"""Normalizer — converts raw API responses into unified Patent objects.

Handles patent ID normalization across sources and deduplication using
both exact ID match and title similarity.
"""

from __future__ import annotations

import logging
import re
from collections import Counter
from datetime import date
from typing import Optional

from patent_gap_finder.models.patent import Patent, PatentSearchResult, PatentSource

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────
# Patent ID normalization
# ──────────────────────────────────────────────────────────────────────


def _normalize_patent_number(raw: str, country: str = "US") -> str:
    """Normalize a patent number to a canonical form.

    US patents → "US-{number}" (strip kind codes B1/B2/A1)
    EP patents → "EP-{number}"
    WO patents → "WO-{year}{number}"
    """
    raw = raw.strip()

    # Strip leading country code if present
    for prefix in ("US", "EP", "WO"):
        if raw.upper().startswith(prefix):
            country = prefix
            raw = raw[len(prefix):]
            break

    # Strip kind codes (B1, B2, A1, A2, etc.)
    raw = re.sub(r"[A-Z]\d*$", "", raw)
    # Strip leading zeros, hyphens, spaces
    raw = raw.lstrip("0").strip("-").strip()

    if not raw:
        return f"{country}-UNKNOWN"

    return f"{country}-{raw}"


# ──────────────────────────────────────────────────────────────────────
# Source normalizers
# ──────────────────────────────────────────────────────────────────────


def normalize_uspto(raw: dict) -> Patent:
    """Convert a raw USPTO PatentsView dict to a unified Patent."""
    patent_number = raw.get("patent_number", raw.get("patent_id", ""))
    patent_id = _normalize_patent_number(str(patent_number), "US")

    # Combine inventor names
    first_names = raw.get("inventor_first_name", [])
    last_names = raw.get("inventor_last_name", [])
    if isinstance(first_names, str):
        first_names = [first_names]
    if isinstance(last_names, str):
        last_names = [last_names]

    inventors = []
    for fn, ln in zip(first_names or [], last_names or []):
        name = f"{fn} {ln}".strip()
        if name:
            inventors.append(name)

    # Extract IPC/CPC codes from nested lists
    ipc_codes = _extract_code_list(raw.get("ipc_code", []))
    cpc_codes = _extract_code_list(raw.get("cpc_code", []))

    # Parse date
    pub_date = _parse_date(raw.get("patent_date"))

    assignee_raw = raw.get("assignee_organization", "")
    if isinstance(assignee_raw, list):
        assignee_raw = assignee_raw[0] if assignee_raw else ""

    return Patent(
        patent_id=patent_id,
        title=raw.get("patent_title", ""),
        abstract=raw.get("patent_abstract", ""),
        publication_date=pub_date,
        assignee=assignee_raw or None,
        inventors=inventors,
        ipc_codes=ipc_codes,
        cpc_codes=cpc_codes,
        source=PatentSource.USPTO,
        source_url=f"https://patents.google.com/patent/US{patent_number}",
    )


def normalize_epo(raw: dict) -> Patent:
    """Convert a raw EPO publication reference dict to a unified Patent."""
    country = raw.get("country", "EP")
    doc_number = raw.get("doc_number", "")
    kind = raw.get("kind", "")

    patent_id = _normalize_patent_number(doc_number, country)

    pub_number = raw.get("publication_number", f"{country}{doc_number}{kind}")

    return Patent(
        patent_id=patent_id,
        title=raw.get("title", ""),
        abstract=raw.get("abstract", ""),
        publication_date=_parse_date(raw.get("publication_date")),
        assignee=raw.get("applicant"),
        inventors=raw.get("inventors", []),
        ipc_codes=raw.get("ipc_codes", []),
        cpc_codes=[],
        source=PatentSource.EPO,
        source_url=f"https://worldwide.espacenet.com/patent/search?q=pn%3D{pub_number}",
    )


def normalize_serpapi(raw: dict) -> Patent:
    """Convert a raw SerpAPI Google Patents dict to a unified Patent."""
    raw_id = raw.get("patent_id", "")
    if raw_id:
        patent_id = _normalize_patent_number(raw_id)
    else:
        patent_id = f"GP-{hash(raw.get('title', '')) & 0xFFFFFFFF}"

    inventors_raw = raw.get("inventors", "")
    if isinstance(inventors_raw, str):
        inventors = [n.strip() for n in inventors_raw.split(",") if n.strip()]
    elif isinstance(inventors_raw, list):
        inventors = inventors_raw
    else:
        inventors = []

    return Patent(
        patent_id=patent_id,
        title=raw.get("title", ""),
        abstract=raw.get("abstract", raw.get("snippet", "")),
        publication_date=_parse_date(raw.get("publication_date")),
        filing_date=_parse_date(raw.get("filing_date")),
        assignee=raw.get("assignee"),
        inventors=inventors,
        ipc_codes=[],
        cpc_codes=[],
        source=PatentSource.GOOGLE_PATENTS,
        source_url=raw.get("pdf_url"),
    )


# ──────────────────────────────────────────────────────────────────────
# Deduplication
# ──────────────────────────────────────────────────────────────────────


def _tokenize(text: str) -> set[str]:
    """Tokenize text into lowercase word set for similarity."""
    return set(re.findall(r"\w+", text.lower()))


def _title_similarity(a: str, b: str) -> float:
    """Token overlap ratio between two titles."""
    tokens_a = _tokenize(a)
    tokens_b = _tokenize(b)
    if not tokens_a or not tokens_b:
        return 0.0
    intersection = tokens_a & tokens_b
    union = tokens_a | tokens_b
    return len(intersection) / len(union) if union else 0.0


def deduplicate(patents: list[Patent]) -> tuple[list[Patent], int]:
    """Remove duplicate patents by ID and title similarity.

    Priority: USPTO > EPO > Google Patents (keep higher-priority source).

    Returns:
        (deduplicated_list, count_removed)
    """
    SOURCE_PRIORITY = {
        PatentSource.USPTO: 0,
        PatentSource.EPO: 1,
        PatentSource.GOOGLE_PATENTS: 2,
    }

    # Sort by source priority (best first)
    sorted_patents = sorted(patents, key=lambda p: SOURCE_PRIORITY.get(p.source, 9))

    seen_ids: dict[str, int] = {}  # patent_id → index in result
    result: list[Patent] = []
    removed = 0

    for patent in sorted_patents:
        # 1. Exact ID dedup
        if patent.patent_id in seen_ids:
            removed += 1
            continue

        # 2. Title similarity dedup
        is_dup = False
        for idx, existing in enumerate(result):
            if _title_similarity(patent.title, existing.title) > 0.92:
                is_dup = True
                removed += 1
                break

        if not is_dup:
            seen_ids[patent.patent_id] = len(result)
            result.append(patent)

    return result, removed


# ──────────────────────────────────────────────────────────────────────
# Build final result
# ──────────────────────────────────────────────────────────────────────


def build_search_result(
    uspto_patents: list[Patent],
    epo_patents: list[Patent],
    serpapi_patents: list[Patent],
    duration: float,
    cache_hits: dict[str, bool],
    keywords: list[str],
    ipc_codes: list[str],
) -> PatentSearchResult:
    """Combine, deduplicate, and build the final search result."""
    all_patents = uspto_patents + epo_patents + serpapi_patents
    deduplicated, removed = deduplicate(all_patents)

    return PatentSearchResult(
        patents=deduplicated,
        total_found=len(deduplicated),
        source_counts={
            "uspto": len(uspto_patents),
            "epo": len(epo_patents),
            "google_patents": len(serpapi_patents),
        },
        search_duration_seconds=round(duration, 2),
        cache_hits=cache_hits,
        keywords_used=keywords,
        ipc_codes_searched=ipc_codes,
        deduplication_removed=removed,
    )


# ──────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────


def _extract_code_list(raw) -> list[str]:
    """Extract a flat list of code strings from various API formats."""
    if isinstance(raw, str):
        return [raw] if raw.strip() else []
    if isinstance(raw, list):
        codes = []
        for item in raw:
            if isinstance(item, str) and item.strip():
                codes.append(item.strip())
            elif isinstance(item, dict):
                for val in item.values():
                    if isinstance(val, str) and val.strip():
                        codes.append(val.strip())
        return codes
    return []


def _parse_date(raw) -> Optional[date]:
    """Parse a date string in various formats."""
    if raw is None or raw == "":
        return None
    if isinstance(raw, date):
        return raw

    raw_str = str(raw).strip()
    for fmt in ("%Y-%m-%d", "%Y%m%d", "%Y-%m", "%Y"):
        try:
            return __import__("datetime").datetime.strptime(raw_str, fmt).date()
        except ValueError:
            continue
    return None
