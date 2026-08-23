import base64
import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from tools.export_report import export_report

SESS_ID = "00000000-0000-0000-0000-000000000001"


@pytest.fixture
def mock_session():
    return SimpleNamespace(
        id=SESS_ID,
        claims_drafted=True,
        top_opportunity_count=2,
    )


@pytest.mark.asyncio
async def test_export_report_success(mock_session):
    pdf_bytes = b"%PDF-test-bytes"
    
    with patch("reporting.pdf_report.generate_report", new_callable=AsyncMock) as mock_generate, \
         patch("db.connection.get_db_session") as mock_db:
        
        db_cm = AsyncMock()
        mock_db.return_value.__aenter__.return_value = db_cm
        mock_result = MagicMock()
        mock_result.scalars().first.return_value = mock_session
        db_cm.execute.return_value = mock_result
        mock_generate.return_value = pdf_bytes
        
        result = await export_report(SESS_ID)
        
        assert result["session_id"] == SESS_ID
        assert result["filename"] == f"patent_gap_report_{SESS_ID[:8]}.pdf"
        assert base64.b64decode(result["pdf_base64"]) == pdf_bytes
        assert result["size_bytes"] == len(pdf_bytes)
        assert result["pages_estimated"] >= 4


@pytest.mark.asyncio
async def test_export_report_claims_not_drafted(mock_session):
    mock_session.claims_drafted = False
    
    with patch("reporting.pdf_report.generate_report", new_callable=AsyncMock) as mock_generate, \
         patch("db.connection.get_db_session") as mock_db:
        
        db_cm = AsyncMock()
        mock_db.return_value.__aenter__.return_value = db_cm
        mock_result = MagicMock()
        mock_result.scalars().first.return_value = mock_session
        db_cm.execute.return_value = mock_result
        mock_generate.return_value = b"%PDF-mock"
        
        result = await export_report(SESS_ID)
        
        assert "claims_note" in result
        assert base64.b64decode(result["pdf_base64"]) == b"%PDF-mock"


@pytest.mark.asyncio
async def test_export_report_session_not_found():
    with patch("db.connection.get_db_session") as mock_db:
        db_cm = AsyncMock()
        mock_db.return_value.__aenter__.return_value = db_cm
        mock_result = MagicMock()
        mock_result.scalars().first.return_value = None
        db_cm.execute.return_value = mock_result
        
        result = await export_report(SESS_ID)
        assert "error" in result
        assert result["error"] == "SESSION_NOT_FOUND"
