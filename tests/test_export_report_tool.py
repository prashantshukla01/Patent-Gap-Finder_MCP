import pytest
import base64
from unittest.mock import AsyncMock, patch

from patent_gap_finder.tools.export_report import export_report

@pytest.fixture
def mock_session():
    mock = AsyncMock()
    mock.claims_drafted = True
    return mock


@pytest.mark.asyncio
async def test_export_report_success(mock_session):
    pdf_bytes = b"%PDF-test-bytes"
    
    with patch("patent_gap_finder.tools.export_report.get_session", new_callable=AsyncMock) as mock_get_session, \
         patch("patent_gap_finder.reporting.pdf_report.generate_report", new_callable=AsyncMock) as mock_generate:
        
        mock_get_session.return_value = mock_session
        mock_generate.return_value = pdf_bytes
        
        result = await export_report("session-123")
        
        assert result["session_id"] == "session-123"
        assert result["filename"] == "patent_gap_report_session-.pdf"
        assert base64.b64decode(result["pdf_base64"]) == pdf_bytes
        assert result["size_bytes"] == len(pdf_bytes)
        assert result["pages_estimated"] >= 4
        

@pytest.mark.asyncio
async def test_export_report_claims_not_drafted(mock_session):
    mock_session.claims_drafted = False
    
    with patch("patent_gap_finder.tools.export_report.get_session", new_callable=AsyncMock) as mock_get_session, \
         patch("patent_gap_finder.reporting.pdf_report.generate_report", new_callable=AsyncMock) as mock_generate:
        
        mock_get_session.return_value = mock_session
        mock_generate.return_value = b"%PDF-mock"
        
        result = await export_report("session-123")
        
        assert "warning" in result
        assert result["code"] == "CLAIMS_NOT_DRAFTED"
        assert base64.b64decode(result["pdf_base64"]) == b"%PDF-mock"


@pytest.mark.asyncio
async def test_export_report_session_not_found():
    with patch("patent_gap_finder.tools.export_report.get_session", new_callable=AsyncMock) as mock_get_session:
        # Simulate session not found behavior
        mock_get_session.return_value = None
        
        result = await export_report("invalid-session")
        assert "error" in result
        assert result["code"] == "SESSION_NOT_FOUND"
