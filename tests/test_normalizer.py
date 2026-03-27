"""Tests for patent normalizer."""

from __future__ import annotations

import pytest

from patent_gap_finder.models.patent import Patent, PatentSource
from patent_gap_finder.search.normalizer import (
    _normalize_patent_number,
    _title_similarity,
    build_search_result,
    deduplicate,
    normalize_epo,
    normalize_serpapi,
    normalize_uspto,
)


# ── Patent number normalization ──────────────────────────────────────


class TestNormalizePatentNumber:
    def test_us_number(self):
        assert _normalize_patent_number("10234567", "US") == "US-10234567"

    def test_strips_kind_code(self):
        assert _normalize_patent_number("10234567B2", "US") == "US-10234567"

    def test_strips_country_prefix(self):
        assert _normalize_patent_number("US10234567B2") == "US-10234567"

    def test_ep_number(self):
        assert _normalize_patent_number("3456789A1", "EP") == "EP-3456789"

    def test_wo_number(self):
        assert _normalize_patent_number("2019123456A1", "WO") == "WO-2019123456"


# ── Source normalizers ───────────────────────────────────────────────


class TestNormalizeUSPTO:
    def test_maps_all_fields(self):
        raw = {
            "patent_number": "10234567",
            "patent_title": "Test Patent",
            "patent_abstract": "A test abstract",
            "patent_date": "2023-01-15",
            "assignee_organization": "TestCorp",
            "inventor_first_name": ["John"],
            "inventor_last_name": ["Doe"],
            "ipc_code": ["G06N 3/08"],
            "cpc_code": [],
        }
        patent = normalize_uspto(raw)
        assert patent.patent_id == "US-10234567"
        assert patent.title == "Test Patent"
        assert patent.source == PatentSource.USPTO
        assert patent.inventors == ["John Doe"]
        assert patent.ipc_codes == ["G06N 3/08"]

    def test_missing_abstract(self):
        raw = {"patent_number": "123", "patent_title": "Test"}
        patent = normalize_uspto(raw)
        assert patent.abstract == ""


class TestNormalizeEPO:
    def test_maps_fields(self):
        raw = {
            "country": "EP",
            "doc_number": "3456789",
            "kind": "A1",
            "publication_number": "EP3456789A1",
            "title": "EPO Test Patent",
        }
        patent = normalize_epo(raw)
        assert patent.patent_id == "EP-3456789"
        assert patent.source == PatentSource.EPO

    def test_missing_abstract_is_none(self):
        raw = {"country": "EP", "doc_number": "999"}
        patent = normalize_epo(raw)
        assert patent.abstract == ""


class TestNormalizeSerpAPI:
    def test_maps_fields(self):
        raw = {
            "patent_id": "US10234567B2",
            "title": "Google Patent",
            "snippet": "A snippet",
            "inventors": "John Doe, Jane Smith",
        }
        patent = normalize_serpapi(raw)
        assert patent.source == PatentSource.GOOGLE_PATENTS
        assert patent.inventors == ["John Doe", "Jane Smith"]


# ── Deduplication ────────────────────────────────────────────────────


class TestDeduplicate:
    def test_removes_exact_id_duplicates(self):
        patents = [
            Patent(patent_id="US-123", title="A", source=PatentSource.USPTO),
            Patent(patent_id="US-123", title="A copy", source=PatentSource.EPO),
        ]
        result, removed = deduplicate(patents)
        assert len(result) == 1
        assert removed == 1
        assert result[0].source == PatentSource.USPTO  # Keeps priority source

    def test_removes_high_similarity_titles(self):
        # 12 shared words, 13 total unique → Jaccard = 12/13 = 0.923 > 0.92
        patents = [
            Patent(
                patent_id="US-111",
                title="deep neural network attention mechanism method for natural language text classification in large scale systems",
                source=PatentSource.USPTO,
            ),
            Patent(
                patent_id="EP-222",
                title="deep neural network attention mechanism method for natural language text classification in large scale distributed systems",
                source=PatentSource.EPO,
            ),
        ]
        result, removed = deduplicate(patents)
        assert len(result) == 1
        assert removed == 1
        assert result[0].source == PatentSource.USPTO

    def test_keeps_different_patents(self):
        patents = [
            Patent(patent_id="US-111", title="quantum computing method", source=PatentSource.USPTO),
            Patent(patent_id="EP-222", title="enzyme purification process", source=PatentSource.EPO),
        ]
        result, removed = deduplicate(patents)
        assert len(result) == 2
        assert removed == 0

    def test_dedup_count_accurate(self):
        patents = [
            Patent(patent_id="US-1", title="A", source=PatentSource.USPTO),
            Patent(patent_id="US-1", title="A dup", source=PatentSource.EPO),
            Patent(patent_id="US-2", title="B", source=PatentSource.USPTO),
            Patent(patent_id="US-2", title="B dup", source=PatentSource.GOOGLE_PATENTS),
        ]
        result, removed = deduplicate(patents)
        assert removed == 2


# ── Title similarity ─────────────────────────────────────────────────


class TestTitleSimilarity:
    def test_identical_titles(self):
        assert _title_similarity("hello world", "hello world") == 1.0

    def test_completely_different(self):
        sim = _title_similarity("cat dog", "sun moon")
        assert sim == 0.0

    def test_partial_overlap(self):
        sim = _title_similarity("neural network method", "neural network approach")
        assert 0.0 < sim < 1.0

    def test_empty_string(self):
        assert _title_similarity("", "hello") == 0.0


# ── Build search result ─────────────────────────────────────────────


class TestBuildSearchResult:
    def test_computes_source_counts(self):
        result = build_search_result(
            uspto_patents=[
                Patent(patent_id="US-1", source=PatentSource.USPTO),
                Patent(patent_id="US-2", source=PatentSource.USPTO),
            ],
            epo_patents=[
                Patent(patent_id="EP-1", source=PatentSource.EPO),
            ],
            serpapi_patents=[],
            duration=1.5,
            cache_hits={"uspto": True, "epo": False},
            keywords=["neural"],
            ipc_codes=["G06N"],
        )
        assert result.source_counts["uspto"] == 2
        assert result.source_counts["epo"] == 1
        assert result.source_counts["google_patents"] == 0
        assert result.total_found == 3
