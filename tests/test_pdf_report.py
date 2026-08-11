import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from patent_gap_finder.reporting.pdf_report import generate_report

SESS_ID = "00000000-0000-0000-0000-000000000001"


@pytest.fixture
def mock_session_data():
    data = {
        "id": SESS_ID,
        "paper_title": "A Novel Approach to AI Resiliency",
        "paper_authors": ["Author One"],
        "paper_abstract": "Abstract here",
        "top_ipc_codes": ["G06N 3/08"],
        "created_at": None,
    }
    ns = SimpleNamespace(**data)
    ns.to_dict = lambda: data
    return ns


@pytest.fixture
def mock_opp():
    return SimpleNamespace(
        id="opp-1",
        claim_text="A method comprising X",
        claim_type="method",
        novelty_score=0.9,
        nearest_cluster_label="neural networks",
        nearest_patent_ids=["US-1"],
        nearest_patent_titles=["Patent Title 1"],
        gemini_assessment="Novel opportunity",
        gemini_confidence=0.85,
        recommended_claim_scope="broad",
        ipc_whitespace_codes=["G06N 3/08"],
        is_whitespace=True,
    )


@pytest.mark.asyncio
async def test_generate_report_valid(mock_session_data, mock_opp):
    with patch("patent_gap_finder.db.repositories.patent_repo.get_patents_for_session", new_callable=AsyncMock) as mock_patents, \
         patch("patent_gap_finder.db.repositories.landscape_repo.get_latest_landscape_job", new_callable=AsyncMock) as mock_job, \
         patch("patent_gap_finder.db.repositories.landscape_repo.get_whitespace_opportunities", new_callable=AsyncMock) as mock_opps, \
         patch("patent_gap_finder.db.repositories.drafts_repo.get_claim_sets_for_session", new_callable=AsyncMock) as mock_claims, \
         patch("patent_gap_finder.db.connection.get_db_session") as mock_db:

        db_cm = AsyncMock()
        mock_db.return_value.__aenter__.return_value = db_cm
        mock_result = MagicMock()
        mock_result.scalars().first.return_value = mock_session_data
        db_cm.execute.return_value = mock_result

        mock_patents.return_value = []
        mock_job.return_value = SimpleNamespace(id="job-1", cluster_records=[])
        mock_opps.return_value = [mock_opp]
        mock_claims.return_value = []

        pdf_bytes = await generate_report(SESS_ID)

        assert pdf_bytes.startswith(b"%PDF")
        assert len(pdf_bytes) > 1000


@pytest.mark.asyncio
async def test_generate_report_no_opportunities(mock_session_data):
    with patch("patent_gap_finder.db.repositories.patent_repo.get_patents_for_session", new_callable=AsyncMock) as mock_patents, \
         patch("patent_gap_finder.db.repositories.landscape_repo.get_latest_landscape_job", new_callable=AsyncMock) as mock_job, \
         patch("patent_gap_finder.db.repositories.landscape_repo.get_whitespace_opportunities", new_callable=AsyncMock) as mock_opps, \
         patch("patent_gap_finder.db.repositories.drafts_repo.get_claim_sets_for_session", new_callable=AsyncMock) as mock_claims, \
         patch("patent_gap_finder.db.connection.get_db_session") as mock_db:

        db_cm = AsyncMock()
        mock_db.return_value.__aenter__.return_value = db_cm
        mock_result = MagicMock()
        mock_result.scalars().first.return_value = mock_session_data
        db_cm.execute.return_value = mock_result

        mock_patents.return_value = []
        mock_job.return_value = None
        mock_opps.return_value = []
        mock_claims.return_value = []

        pdf_bytes = await generate_report(SESS_ID)
        assert pdf_bytes.startswith(b"%PDF")


@pytest.mark.asyncio
async def test_generate_report_long_title(mock_session_data, mock_opp):
    mock_session_data.paper_title = "VERY LONG TITLE " * 50

    with patch("patent_gap_finder.db.repositories.patent_repo.get_patents_for_session", new_callable=AsyncMock) as mock_patents, \
         patch("patent_gap_finder.db.repositories.landscape_repo.get_latest_landscape_job", new_callable=AsyncMock) as mock_job, \
         patch("patent_gap_finder.db.repositories.landscape_repo.get_whitespace_opportunities", new_callable=AsyncMock) as mock_opps, \
         patch("patent_gap_finder.db.repositories.drafts_repo.get_claim_sets_for_session", new_callable=AsyncMock) as mock_claims, \
         patch("patent_gap_finder.db.connection.get_db_session") as mock_db:

        db_cm = AsyncMock()
        mock_db.return_value.__aenter__.return_value = db_cm
        mock_result = MagicMock()
        mock_result.scalars().first.return_value = mock_session_data
        db_cm.execute.return_value = mock_result

        mock_patents.return_value = []
        mock_job.return_value = None
        mock_opps.return_value = [mock_opp]
        mock_claims.return_value = []

        pdf_bytes = await generate_report(SESS_ID)
        assert pdf_bytes.startswith(b"%PDF")
