"""MCP tool: export_report — generate and return a PDF analysis report.

Produces a structured, attorney-ready PDF covering the full patent gap
analysis pipeline. Returns the PDF as base64-encoded string(s).
"""

from __future__ import annotations

import base64
import logging
import re
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

UUID_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I
)

# Max chunk size for base64 PDF data (500KB to stay within context limits)
MAX_CHUNK_SIZE = 500_000


async def export_report(session_id: str) -> dict:
    """Generate and return a PDF patent gap analysis report.

    Args:
        session_id: UUID of the analysis session.

    Returns:
        Report metadata with base64-encoded PDF, or structured error.
    """
    # Validate UUID
    if not UUID_PATTERN.match(session_id):
        return {"error": "INVALID_SESSION_ID", "message": "Not a valid UUID"}

    from patent_gap_finder.db.connection import get_db_session
    from patent_gap_finder.db.models import AnalysisSession
    from sqlalchemy import select

    async with get_db_session() as db:
        result = await db.execute(
            select(AnalysisSession).where(AnalysisSession.id == session_id)
        )
        session = result.scalars().first()

        if not session:
            return {"error": "SESSION_NOT_FOUND", "message": "No session with this ID"}

    # Check if claims have been drafted
    claims_note = ""
    if not session.claims_drafted:
        claims_note = (
            "Note: Patent claims have not been drafted yet. The claims section "
            "of the report will be empty. Run draft_claims first for a complete "
            "report."
        )
        logger.info("Generating report without drafted claims for session %s", session_id)

    # Generate PDF
    try:
        from patent_gap_finder.reporting.pdf_report import generate_report

        pdf_bytes = await generate_report(session_id)
    except Exception as e:
        logger.error("PDF generation failed for session %s: %s", session_id, e)
        return {
            "error": "PDF_GENERATION_FAILED",
            "message": f"Report generation failed: {str(e)}",
        }

    if not pdf_bytes:
        return {
            "error": "PDF_GENERATION_FAILED",
            "message": "Report generation produced empty output",
        }

    # Encode to base64
    pdf_b64 = base64.b64encode(pdf_bytes).decode("ascii")

    # Estimate page count
    opp_count = session.top_opportunity_count or 0
    pages_estimated = 4 + (2 * opp_count)

    filename = f"patent_gap_report_{session_id[:8]}.pdf"

    # Build sections preview
    sections = [
        "Cover Page",
        "Executive Summary",
        "Patent Landscape Overview",
    ]
    if opp_count > 0:
        sections.append(f"Whitespace Opportunities ({opp_count})")
    if session.claims_drafted:
        sections.append("Drafted Patent Claims")
    sections.append("Methodology & Disclaimer")

    # If PDF is very large, chunk the base64 data
    if len(pdf_b64) > MAX_CHUNK_SIZE * 2:
        chunks = {}
        for i in range(0, len(pdf_b64), MAX_CHUNK_SIZE):
            chunk_num = i // MAX_CHUNK_SIZE + 1
            chunks[f"pdf_base64_chunk_{chunk_num}"] = pdf_b64[i:i + MAX_CHUNK_SIZE]

        response = {
            "session_id": session_id,
            "filename": filename,
            "total_chunks": len(chunks),
            "assembly_instruction": (
                "Concatenate all pdf_base64_chunk_N values in order, "
                "then base64 decode to get the PDF file."
            ),
            "size_bytes": len(pdf_bytes),
            "pages_estimated": pages_estimated,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "sections": sections,
        }
        response.update(chunks)
        if claims_note:
            response["claims_note"] = claims_note
        return response

    # Normal (non-chunked) response
    response = {
        "session_id": session_id,
        "filename": filename,
        "pdf_base64": pdf_b64,
        "size_bytes": len(pdf_bytes),
        "pages_estimated": pages_estimated,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sections": sections,
    }
    if claims_note:
        response["claims_note"] = claims_note

    return response
