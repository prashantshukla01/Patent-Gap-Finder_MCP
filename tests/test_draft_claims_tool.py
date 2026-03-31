import pytest
from unittest.mock import AsyncMock, patch

from patent_gap_finder.tools.draft_claims import draft_claims


@pytest.fixture
def mock_session():
    mock = AsyncMock()
    mock.whitespace_analysis_complete = True
    return mock


@pytest.fixture
def sample_opportunities():
    return [
        AsyncMock(is_whitespace=True, novelty_score=0.9, nearest_patent_ids=["US-1", "US-2"]),
        AsyncMock(is_whitespace=True, novelty_score=0.6, nearest_patent_ids=["US-3"]),
        AsyncMock(is_whitespace=False, novelty_score=0.9, nearest_patent_ids=["US-4"])
    ]


@pytest.mark.asyncio
async def test_draft_claims_success(mock_session, sample_opportunities):
    with patch("patent_gap_finder.tools.draft_claims.get_session", new_callable=AsyncMock) as mock_get_session, \
         patch("patent_gap_finder.tools.draft_claims.get_whitespace_opportunities", new_callable=AsyncMock) as mock_get_opps, \
         patch("patent_gap_finder.tools.draft_claims.get_patents_by_ids", new_callable=AsyncMock) as mock_get_patents, \
         patch("patent_gap_finder.drafting.claim_drafter.draft_all_claim_sets", new_callable=AsyncMock) as mock_draft_all, \
         patch("patent_gap_finder.db.repositories.drafts_repo.save_claim_sets", new_callable=AsyncMock) as mock_save, \
         patch("patent_gap_finder.tools.draft_claims.AsyncSessionLocal"):
         
        mock_get_session.return_value = mock_session
        mock_get_opps.return_value = sample_opportunities
        mock_draft_all.return_value = [AsyncMock(opportunity_id=f"opp-{i}") for i in range(2)]

        result = await draft_claims("session-123", min_novelty_score=0.5)

        assert result["session_id"] == "session-123"
        assert result["total_claim_sets"] == 2
        
        # Verify save was called
        mock_save.assert_called_once()
        # Verify Session was marked as having claims drafted
        assert mock_session.claims_drafted is True


@pytest.mark.asyncio
async def test_draft_claims_phase4_incomplete(mock_session):
    mock_session.whitespace_analysis_complete = False
    
    with patch("patent_gap_finder.tools.draft_claims.get_session", new_callable=AsyncMock) as mock_get_session, \
         patch("patent_gap_finder.tools.draft_claims.AsyncSessionLocal"):
         
        mock_get_session.return_value = mock_session

        result = await draft_claims("session-123", min_novelty_score=0.5)

        assert "error" in result
        assert result["code"] == "PHASE4_INCOMPLETE"


@pytest.mark.asyncio
async def test_draft_claims_no_opportunities(mock_session, sample_opportunities):
    # Filter using min_novelty_score = 0.95 (none qualify)
    with patch("patent_gap_finder.tools.draft_claims.get_session", new_callable=AsyncMock) as mock_get_session, \
         patch("patent_gap_finder.tools.draft_claims.get_whitespace_opportunities", new_callable=AsyncMock) as mock_get_opps, \
         patch("patent_gap_finder.tools.draft_claims.AsyncSessionLocal"):
         
        mock_get_session.return_value = mock_session
        mock_get_opps.return_value = sample_opportunities

        result = await draft_claims("session-123", min_novelty_score=0.95)

        assert "error" in result
        assert result["code"] == "NO_OPPORTUNITIES"
