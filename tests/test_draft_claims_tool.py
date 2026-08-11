import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from patent_gap_finder.tools.draft_claims import draft_claims


@pytest.fixture
def mock_session():
    return SimpleNamespace(
        id="00000000-0000-0000-0000-000000000001",
        whitespace_analysis_complete=True,
    )


@pytest.fixture
def sample_opportunities():
    return [
        SimpleNamespace(
            id="opp-1",
            claim_text="Claim 1",
            claim_type="method",
            novelty_score=0.9,
            gemini_assessment="Novel",
            recommended_claim_scope="broad",
            ipc_whitespace_codes=["G06N"],
            is_whitespace=True,
            nearest_patent_ids=["US-1", "US-2"],
        ),
    ]


@pytest.mark.asyncio
async def test_draft_claims_success(mock_session, sample_opportunities):
    sess_id = "00000000-0000-0000-0000-000000000001"
    with patch("patent_gap_finder.db.repositories.landscape_repo.get_whitespace_opportunities", new_callable=AsyncMock) as mock_get_opps, \
         patch("patent_gap_finder.db.repositories.patent_repo.get_patents_for_session", new_callable=AsyncMock) as mock_get_patents, \
         patch("patent_gap_finder.db.connection.get_db_session") as mock_db:
        
        db_cm = AsyncMock()
        mock_db.return_value.__aenter__.return_value = db_cm
        mock_result = MagicMock()
        mock_result.scalars().first.return_value = mock_session
        db_cm.execute.return_value = mock_result
        
        mock_get_opps.return_value = sample_opportunities
        mock_get_patents.return_value = []

        result = await draft_claims(sess_id, min_novelty_score=0.5)

        assert result["session_id"] == sess_id
        assert result["total_opportunities"] == 1
        assert "ai_instructions" in result
        assert result["ai_instructions"]["task"] == "draft_patent_claims"


@pytest.mark.asyncio
async def test_draft_claims_phase4_incomplete(mock_session):
    sess_id = "00000000-0000-0000-0000-000000000001"
    mock_session.whitespace_analysis_complete = False
    
    with patch("patent_gap_finder.db.connection.get_db_session") as mock_db:
        db_cm = AsyncMock()
        mock_db.return_value.__aenter__.return_value = db_cm
        mock_result = MagicMock()
        mock_result.scalars().first.return_value = mock_session
        db_cm.execute.return_value = mock_result

        result = await draft_claims(sess_id, min_novelty_score=0.5)

        assert "error" in result
        assert result["error"] == "PHASE4_INCOMPLETE"


@pytest.mark.asyncio
async def test_draft_claims_no_opportunities(mock_session):
    sess_id = "00000000-0000-0000-0000-000000000001"
    with patch("patent_gap_finder.db.repositories.landscape_repo.get_whitespace_opportunities", new_callable=AsyncMock) as mock_get_opps, \
         patch("patent_gap_finder.db.connection.get_db_session") as mock_db:
        
        db_cm = AsyncMock()
        mock_db.return_value.__aenter__.return_value = db_cm
        mock_result = MagicMock()
        mock_result.scalars().first.return_value = mock_session
        db_cm.execute.return_value = mock_result
        mock_get_opps.return_value = []

        result = await draft_claims(sess_id, min_novelty_score=0.95)

        assert "error" in result
        assert result["error"] == "NO_OPPORTUNITIES"
