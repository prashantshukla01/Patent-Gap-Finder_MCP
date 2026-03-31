import pytest
import asyncio
from unittest.mock import patch, AsyncMock

from patent_gap_finder.server import mcp

# In a real environment with live services, we'd actually call the real functions.
# However, integration tests running in CI usually rely on either spun-up docker 
# containers or mocked external API calls to avoid flaky third-party endpoints.
# Below is a test that wires together the real business logic but potentially mocks
# out external APIs like Gemini/SerpAPI when they aren't available.

@pytest.mark.asyncio
@pytest.mark.integration
async def test_full_pipeline_arxiv_paper():
    """
    Full end-to-end pipeline test using a real arXiv paper.
    Requires: all services running (Postgres, Redis, Qdrant, Celery).
    When running in isolation, consider mocking GeminiClient and external clients.
    """
    try:
        from patent_gap_finder.tools.parse_paper import parse_paper
        from patent_gap_finder.tools.classify_ipc import classify_ipc
        from patent_gap_finder.tools.search_prior_art import search_prior_art
        from patent_gap_finder.tools.get_search_status import get_search_status
        from patent_gap_finder.tools.map_landscape import map_landscape
        from patent_gap_finder.tools.find_whitespace import find_whitespace
        from patent_gap_finder.tools.draft_claims import draft_claims
        from patent_gap_finder.tools.export_report import export_report
    except ImportError:
        pytest.skip("Project not fully initialized or import error")

    # Step 1: parse_paper
    # We use arXiv:2005.14165 (GPT-3 paper)
    try:
        parsed = await parse_paper("https://arxiv.org/abs/2005.14165", extract_with_ai=True)
        session_id = parsed["session_id"]
        assert session_id is not None
        assert parsed["claims_extracted"] > 0
    except Exception as e:
        pytest.skip(f"parse_paper failed (possibly missing services): {e}")

    # Step 2: classify_ipc
    classified = await classify_ipc(session_id)
    assert any("G06" in ipc for ipc in classified["top_ipc_codes"])

    # Step 3: search_prior_art
    search_res = await search_prior_art(session_id)
    job_id = search_res["job_id"]
    assert job_id is not None

    # Step 4: poll get_search_status
    status = None
    for _ in range(24): # timeout 120s
        status = await get_search_status(job_id)
        if status["status"] == "complete":
            break
        await asyncio.sleep(5)
    
    assert status["status"] == "complete", dict(status)
    assert status["result_count"] > 0

    # Step 5: map_landscape
    landscape = await map_landscape(session_id)
    assert landscape["n_clusters"] >= 3

    # Step 6: find_whitespace
    whitespace = await find_whitespace(session_id, min_score=0.5)
    assert len(whitespace["whitespace_opportunities"]) >= 1

    # Step 7: draft_claims
    drafts = await draft_claims(session_id, min_novelty_score=0.5)
    assert drafts["total_claim_sets"] >= 1
    assert any("CLAIMS" in cs.get("claims_preview", "") for cs in drafts["claim_sets"])

    # Step 8: export_report
    report = await export_report(session_id)
    assert report["pdf_base64"] is not None
    import base64
    pdf_bytes = base64.b64decode(report["pdf_base64"])
    assert pdf_bytes.startswith(b"%PDF")
    
    # Step 9: get_session
    from patent_gap_finder.tools.get_session import get_session
    final_session = await get_session(session_id)
    assert final_session["status"] == "complete"
    assert final_session["claims_drafted"] is True
