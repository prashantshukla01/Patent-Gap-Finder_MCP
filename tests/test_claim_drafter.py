import pytest
from unittest.mock import AsyncMock, patch

from patent_gap_finder.models.landscape import WhitespaceOpportunity
from patent_gap_finder.models.drafts import ClaimSet, DraftedClaim
from patent_gap_finder.drafting.claim_drafter import draft_claim_set, draft_all_claim_sets


@pytest.fixture
def sample_opportunity():
    return WhitespaceOpportunity(
        opportunity_id="opp-123",
        claim_text="A method for X comprising Y.",
        novelty_score=0.85,
        nearest_cluster_label="Test Cluster",
        nearest_patents=["US-1", "US-2", "US-3"],
        nearest_patent_titles=["Patent 1", "Patent 2", "Patent 3"],
        gemini_novelty_assessment="Highly novel because...",
        ipc_whitespace_codes=["G06N 3/08"],
        recommended_claim_scope="broad",
        is_whitespace=True,
    )


@pytest.fixture
def sample_gemini_response():
    return {
        "opportunity_id": "opp-123",
        "claim_text_original": "A method for X comprising Y.",
        "novelty_score": 0.85,
        "recommended_scope": "broad",
        "drafting_rationale": "Broad scope due to high novelty.",
        "distinguishing_features": ["Uses Y"],
        "ipc_codes": ["G06N 3/08"],
        "claims": [
            {
                "claim_number": 1,
                "claim_text": "A method comprising:\nX;\nand Y.",
                "claim_type": "independent",
                "depends_on": None,
                "patent_claim_category": "method"
            },
            {
                "claim_number": 2,
                "claim_text": "The method of claim 1, further comprising Z.",
                "claim_type": "dependent",
                "depends_on": 1,
                "patent_claim_category": "method"
            },
            {
                "claim_number": 3,
                "claim_text": "The method of claim 1, wherein X is Q.",
                "claim_type": "dependent",
                "depends_on": 1,
                "patent_claim_category": "method"
            }
        ]
    }


@pytest.mark.asyncio
async def test_draft_claim_set(sample_opportunity, sample_gemini_response):
    patent_details = {
        "US-1": {"title": "Patent 1", "abstract": "Abstract 1"},
        "US-2": {"title": "Patent 2", "abstract": "Abstract 2"},
        "US-3": {"title": "Patent 3", "abstract": "Abstract 3"},
    }
    
    with patch("patent_gap_finder.ai.gemini_client.GeminiClient.complete_json", new_callable=AsyncMock) as mock_complete:
        mock_complete.return_value = sample_gemini_response
        
        result = await draft_claim_set(sample_opportunity, patent_details)
        
        assert isinstance(result, ClaimSet)
        assert len(result.claims) == 3
        # Independent claim matches scope
        assert len([c for c in result.claims if c.claim_type == "independent"]) == 1
        assert "DISCLAIMER" in result.gemini_disclaimer
        
        # Verify prompt contained claim text and nearest patent titles
        call_args = mock_complete.call_args[1]
        assert "A method for X comprising Y." in call_args["prompt"]
        assert "Patent 1" in call_args["prompt"]
        assert "Patent 2" in call_args["prompt"]


@pytest.mark.asyncio
async def test_draft_all_claim_sets(sample_opportunity, sample_gemini_response):
    patent_details = {}
    
    # Create a non-whitespace opportunity to test filtering
    opp_reject = sample_opportunity.model_copy()
    opp_reject.is_whitespace = False
    
    opp_low_novelty = sample_opportunity.model_copy()
    opp_low_novelty.novelty_score = 0.4
    
    opportunities = [sample_opportunity, opp_reject, opp_low_novelty]
    
    with patch("patent_gap_finder.drafting.claim_drafter.draft_claim_set", new_callable=AsyncMock) as mock_draft:
        mock_draft.return_value = ClaimSet(**sample_gemini_response)
        
        results = await draft_all_claim_sets(opportunities, patent_details, min_novelty_score=0.5)
        
        assert len(results) == 1
        mock_draft.assert_called_once()
        assert mock_draft.call_args[0][0].opportunity_id == "opp-123"
