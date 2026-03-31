import pytest
from unittest.mock import AsyncMock, patch

from patent_gap_finder.models.landscape import WhitespaceOpportunity
from patent_gap_finder.models.drafts import ClaimSet, DraftedClaim, ClaimDraftReport
from patent_gap_finder.reporting.pdf_report import generate_report


@pytest.fixture
def mock_db_session():
    mock = AsyncMock()
    # Mocking standard SQL queries or repository functions isn't ideal without the full DB setup
    # Need to patch the methods inside generate_report that hit DB
    return mock


@pytest.fixture
def sample_report_data():
    return ClaimDraftReport(
        session_id="session-123",
        paper_title="A Novel Approach to AI Resiliency",
        total_opportunities=1,
        drafting_summary="Summary of strategy",
        recommended_filing_order=["opp-1"],
        claim_sets=[
            ClaimSet(
                opportunity_id="opp-1",
                claim_text_original="Something novel",
                novelty_score=0.9,
                recommended_scope="broad",
                claims=[
                    DraftedClaim(
                        claim_number=1,
                        claim_text="A method comprising X.",
                        claim_type="independent",
                        patent_claim_category="method"
                    )
                ],
                drafting_rationale="Rationale here",
                distinguishing_features=["Feature A"],
                ipc_codes=["G06N"]
            )
        ]
    )


@pytest.mark.asyncio
async def test_generate_report_valid(mock_db_session, sample_report_data):
    # Depending on how pdf_report is written, we may need to mock repository methods.
    # Assuming pdf_report retrieves session, landscape, and sets correctly.
    with patch("patent_gap_finder.reporting.pdf_report.get_report_data", new_callable=AsyncMock) as mock_get_data:
        mock_get_data.return_value = (
            # session
            AsyncMock(paper_abstract="Abstract here", top_ipc_codes=["G06N"], total_patents_found=187),
            # clusters
            [AsyncMock(label="Cluster 1", patent_count=10, technical_domain="AI")],
            # opportunities
            [AsyncMock(novelty_score=0.9, nearest_patent_titles=[], claim_text="text")],
            sample_report_data
        )

        pdf_bytes = await generate_report("session-123", mock_db_session)

        # PDF signatures always start with %PDF
        assert pdf_bytes.startswith(b"%PDF")
        assert len(pdf_bytes) > 10240  # Must be larger than 10KB


@pytest.mark.asyncio
async def test_generate_report_no_opportunities(mock_db_session):
    report_empty = ClaimDraftReport(
        session_id="session-123",
        paper_title="Empty Paper",
        total_opportunities=0,
    )
    
    with patch("patent_gap_finder.reporting.pdf_report.get_report_data", new_callable=AsyncMock) as mock_get_data:
        mock_get_data.return_value = (
            AsyncMock(paper_abstract="Empty", top_ipc_codes=[], total_patents_found=0),
            [],
            [],
            report_empty
        )

        pdf_bytes = await generate_report("session-123", mock_db_session)
        assert pdf_bytes.startswith(b"%PDF")
        # Should generate correctly, no claim section


@pytest.mark.asyncio
async def test_generate_report_long_title(mock_db_session, sample_report_data):
    sample_report_data.paper_title = "VERY LONG TITLE " * 100

    with patch("patent_gap_finder.reporting.pdf_report.get_report_data", new_callable=AsyncMock) as mock_get_data:
        mock_get_data.return_value = (
            AsyncMock(paper_abstract="Abstract here", top_ipc_codes=["G06N"], total_patents_found=187),
            [],
            [],
            sample_report_data
        )

        pdf_bytes = await generate_report("session-123", mock_db_session)
        assert pdf_bytes.startswith(b"%PDF")
        # Ensure it didn't throw a ReportLab width error
