import pytest
import asyncio
from unittest.mock import patch, AsyncMock

from patent_gap_finder.server import mcp

# In a real environment with live services, we'd actually call the real functions.
# However, integration tests running in CI usually rely on either spun-up docker
# containers or mocked external API calls to avoid flaky third-party endpoints.
# The pipeline now uses a two-phase approach: the MCP server returns data and
# instructions, and the host LLM (Claude) does the AI reasoning and saves results
# back via save_* tools.

@pytest.mark.asyncio
@pytest.mark.integration
async def test_full_pipeline_arxiv_paper():
    """
    Full end-to-end pipeline test using a real arXiv paper.
    Requires: all services running (Postgres, Redis, Qdrant, Celery).
    The LLM reasoning steps (claim extraction, IPC classification, etc.)
    are simulated with mock data since no LLM is available in tests.
    """
    try:
        from patent_gap_finder.tools.parse_paper import parse_paper
        from patent_gap_finder.tools.save_claims import save_claims
        from patent_gap_finder.tools.classify_ipc import classify_ipc
        from patent_gap_finder.tools.save_classification import save_classification
        from patent_gap_finder.tools.search_prior_art import search_prior_art
        from patent_gap_finder.tools.get_search_status import get_search_status
        from patent_gap_finder.tools.map_landscape import map_landscape
        from patent_gap_finder.tools.find_whitespace import find_whitespace
        from patent_gap_finder.tools.save_whitespace import save_whitespace
        from patent_gap_finder.tools.draft_claims import draft_claims
        from patent_gap_finder.tools.save_drafted_claims import save_drafted_claims
        from patent_gap_finder.tools.export_report import export_report
    except ImportError:
        pytest.skip("Project not fully initialized or import error")

    # Step 1: parse_paper
    # We use arXiv:2005.14165 (GPT-3 paper)
    try:
        parsed = await parse_paper("https://arxiv.org/abs/2005.14165")
        session_id = parsed.get("session_id")
        assert session_id is not None
        assert "ai_instructions" in parsed
    except Exception as e:
        pytest.skip(f"parse_paper failed (possibly missing services): {e}")

    # Step 2: save_claims (simulating LLM extraction)
    mock_claims = [
        {
            "claim_text": "A method for training language models comprising: scaling model parameters to 175 billion; using in-context learning without fine-tuning.",
            "claim_type": "method",
            "technical_domain": "natural language processing",
            "novelty_basis": "First demonstration of in-context few-shot learning at scale",
            "source_section": "Introduction",
            "confidence": 0.85,
        }
    ]
    save_result = await save_claims(
        session_id, mock_claims,
        paper_summary="GPT-3 demonstrates that scaling language models improves few-shot learning.",
        primary_domain="natural language processing",
    )
    assert save_result["claims_saved"] == 1

    # Step 3: classify_ipc — get instructions
    ipc_data = await classify_ipc(session_id)
    assert ipc_data["total_claims"] >= 1

    # Step 4: save_classification (simulating LLM classification)
    mock_mappings = [
        {
            "claim_text": mock_claims[0]["claim_text"],
            "primary_ipc": "G06N 3/08",
            "secondary_ipc": ["G06N 3/04"],
            "cpc_code": "G06N 3/08",
            "confidence": 0.9,
            "rationale": "Neural network training methods",
        }
    ]
    class_result = await save_classification(
        session_id, mock_mappings,
        top_ipc_codes=["G06N 3/08"],
        search_keywords=["language model", "few-shot learning", "GPT"],
    )
    assert class_result["claims_classified"] == 1

    # Step 5: search_prior_art
    search_res = await search_prior_art(session_id)
    job_id = search_res["job_id"]
    assert job_id is not None

    # Step 6: poll get_search_status
    status = None
    for _ in range(24):  # timeout 120s
        status = await get_search_status(job_id)
        if status["status"] == "complete":
            break
        await asyncio.sleep(5)

    assert status["status"] == "complete", dict(status)
    assert status["result_count"] > 0

    # Step 7: map_landscape
    landscape = await map_landscape(session_id)
    assert landscape["n_clusters"] >= 3

    # Step 8: find_whitespace
    whitespace = await find_whitespace(session_id, min_novelty_score=0.5)
    assert len(whitespace["whitespace_opportunities"]) >= 1
    assert "ai_instructions" in whitespace

    # Step 9: save_whitespace (simulating LLM assessment)
    ws_opps = whitespace["whitespace_opportunities"]
    mock_assessments = [
        {
            "opportunity_id": opp["opportunity_id"],
            "novelty_assessment": "This claim is novel because...",
            "confidence": 0.8,
            "recommended_scope": "medium",
            "ipc_codes": ["G06N 3/08"],
        }
        for opp in ws_opps if opp.get("is_whitespace")
    ]
    if mock_assessments:
        ws_result = await save_whitespace(session_id, mock_assessments)
        assert ws_result["assessments_saved"] >= 1

    # Step 10: draft_claims — get instructions
    drafts_data = await draft_claims(session_id, min_novelty_score=0.5)
    assert drafts_data["total_opportunities"] >= 1
    assert "ai_instructions" in drafts_data

    # Step 11: save_drafted_claims (simulating LLM drafting)
    mock_claim_sets = [
        {
            "opportunity_id": drafts_data["opportunities"][0]["opportunity_id"],
            "claim_text_original": drafts_data["opportunities"][0]["claim_text"],
            "novelty_score": drafts_data["opportunities"][0]["novelty_score"],
            "recommended_scope": "medium",
            "claims": [
                {
                    "claim_number": 1,
                    "claim_text": "A method for training a language model comprising: providing a corpus of text data...",
                    "claim_type": "independent",
                    "depends_on": None,
                    "patent_claim_category": "method",
                },
            ],
            "drafting_rationale": "Broad scope to cover the core NLP method.",
            "distinguishing_features": ["in-context learning", "175B parameters"],
        }
    ]
    draft_result = await save_drafted_claims(session_id, mock_claim_sets)
    assert draft_result["claim_sets_saved"] == 1

    # Step 12: export_report
    report = await export_report(session_id)
    assert report["pdf_base64"] is not None
    import base64
    pdf_bytes = base64.b64decode(report["pdf_base64"])
    assert pdf_bytes.startswith(b"%PDF")

    # Step 13: get_session
    from patent_gap_finder.tools.get_session import get_session
    final_session = await get_session(session_id)
    assert final_session["status"] == "complete"
    assert final_session["claims_drafted"] is True
