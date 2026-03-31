"""ReportLab PDF report generator for patent gap analysis.

Generates a structured, attorney-ready PDF report including:
- Cover page with paper metadata
- Executive summary with analysis statistics
- Patent landscape overview
- Whitespace opportunities (one section per opportunity)
- Drafted patent claims
- Methodology and legal disclaimer

Key technical notes:
- Uses wordWrap="CJK" on claim styles to handle long run-on claim text
- Truncates tokens > 50 chars to prevent silent overflow
- All content loaded from PostgreSQL via repositories
"""

from __future__ import annotations

import io
import logging
import re
from datetime import datetime, timezone
from typing import Optional

from reportlab.lib.colors import HexColor
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    HRFlowable,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from patent_gap_finder.drafting.claim_formatter import format_claim_set, validate_claim_set
from patent_gap_finder.models.drafts import DraftedClaim

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────
# Color palette
# ──────────────────────────────────────────────────────────────────────

PRIMARY = HexColor("#4a9eed")
ACCENT_GREEN = HexColor("#22c55e")
ACCENT_AMBER = HexColor("#f59e0b")
DARK_TEXT = HexColor("#1a1a2e")
LIGHT_GRAY = HexColor("#f8f9fa")
BORDER_GRAY = HexColor("#cccccc")
MUTED_TEXT = HexColor("#888888")
WHITE = HexColor("#ffffff")
HEADER_BG = HexColor("#4a9eed")

# ──────────────────────────────────────────────────────────────────────
# Custom styles
# ──────────────────────────────────────────────────────────────────────


def _build_styles():
    """Build custom ParagraphStyles for the report."""
    base = getSampleStyleSheet()

    return {
        "ReportTitle": ParagraphStyle(
            name="ReportTitle",
            parent=base["Title"],
            fontSize=26,
            textColor=DARK_TEXT,
            spaceAfter=16,
            alignment=TA_CENTER,
        ),
        "SubTitle": ParagraphStyle(
            name="SubTitle",
            parent=base["Title"],
            fontSize=14,
            textColor=PRIMARY,
            spaceAfter=8,
            alignment=TA_CENTER,
        ),
        "SectionHeading": ParagraphStyle(
            name="SectionHeading",
            parent=base["Heading1"],
            fontSize=14,
            textColor=PRIMARY,
            spaceBefore=16,
            spaceAfter=8,
            borderPadding=4,
        ),
        "SubSectionHeading": ParagraphStyle(
            name="SubSectionHeading",
            parent=base["Heading2"],
            fontSize=12,
            textColor=DARK_TEXT,
            spaceBefore=12,
            spaceAfter=6,
        ),
        "BodyText": ParagraphStyle(
            name="ReportBody",
            parent=base["Normal"],
            fontSize=10,
            leading=14,
            alignment=TA_JUSTIFY,
            spaceAfter=8,
        ),
        "CenterText": ParagraphStyle(
            name="CenterText",
            parent=base["Normal"],
            fontSize=10,
            leading=14,
            alignment=TA_CENTER,
            spaceAfter=8,
        ),
        "ClaimText": ParagraphStyle(
            name="ClaimText",
            parent=base["Normal"],
            fontSize=9,
            fontName="Courier",
            leftIndent=20,
            spaceAfter=6,
            leading=14,
            wordWrap="CJK",  # Force aggressive wrapping for long claim text
        ),
        "SmallText": ParagraphStyle(
            name="SmallText",
            parent=base["Normal"],
            fontSize=8,
            leading=10,
            textColor=MUTED_TEXT,
        ),
        "Disclaimer": ParagraphStyle(
            name="Disclaimer",
            parent=base["Normal"],
            fontSize=8,
            leading=11,
            textColor=MUTED_TEXT,
            alignment=TA_JUSTIFY,
            spaceBefore=8,
            spaceAfter=4,
        ),
        "Badge": ParagraphStyle(
            name="Badge",
            parent=base["Normal"],
            fontSize=10,
            textColor=WHITE,
            alignment=TA_CENTER,
        ),
    }


# ──────────────────────────────────────────────────────────────────────
# Helper utilities
# ──────────────────────────────────────────────────────────────────────


def _safe_text(text: str, max_token_len: int = 50) -> str:
    """Guard against ReportLab silent overflow on extremely long tokens.

    Splits any token longer than max_token_len with a soft hyphen so
    Paragraph can wrap it properly.
    """
    if not text:
        return ""
    words = text.split()
    safe_words = []
    for w in words:
        if len(w) > max_token_len:
            # Insert soft hyphens every max_token_len chars
            parts = [w[i:i + max_token_len] for i in range(0, len(w), max_token_len)]
            safe_words.append("\u00ad".join(parts))
        else:
            safe_words.append(w)
    return " ".join(safe_words)


def _xml_escape(text: str) -> str:
    """Escape XML special characters for ReportLab Paragraph."""
    if not text:
        return ""
    text = text.replace("&", "&amp;")
    text = text.replace("<", "&lt;")
    text = text.replace(">", "&gt;")
    return text


def _novelty_bar(score: float) -> str:
    """Build a text-based novelty score visualization."""
    filled = int(score * 10)
    empty = 10 - filled
    bar = "█" * filled + "░" * empty
    return f"{bar} {score:.2f}/1.0"


def _add_page_number(canvas, doc):
    """Draw page number footer on each page."""
    canvas.saveState()
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(MUTED_TEXT)
    page_num = canvas.getPageNumber()
    canvas.drawRightString(
        letter[0] - 0.75 * inch,
        0.5 * inch,
        f"Patent Gap Finder  ·  Page {page_num}",
    )
    canvas.restoreState()


def _make_table(data: list[list[str]], col_widths: Optional[list] = None) -> Table:
    """Build a styled data table."""
    table = Table(data, colWidths=col_widths)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), HEADER_BG),
        ("TEXTCOLOR", (0, 0), (-1, 0), WHITE),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("ALIGN", (0, 0), (-1, -1), "LEFT"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [LIGHT_GRAY, WHITE]),
        ("GRID", (0, 0), (-1, -1), 0.25, BORDER_GRAY),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ]))
    return table


# ──────────────────────────────────────────────────────────────────────
# Report section builders
# ──────────────────────────────────────────────────────────────────────


def _build_cover_page(
    story: list,
    styles: dict,
    session: dict,
) -> None:
    """Add cover page to the report."""
    story.append(Spacer(1, 2 * inch))
    story.append(Paragraph("Patent Gap Analysis Report", styles["ReportTitle"]))
    story.append(Spacer(1, 0.3 * inch))
    story.append(HRFlowable(
        width="60%", thickness=2, color=PRIMARY, spaceAfter=16,
    ))

    title = _xml_escape(_safe_text(session.get("paper_title", "Untitled Paper")))
    story.append(Paragraph(title, styles["SubTitle"]))
    story.append(Spacer(1, 0.5 * inch))

    # Authors
    authors = session.get("paper_authors")
    if authors:
        if isinstance(authors, list):
            authors_text = ", ".join(str(a) for a in authors)
        else:
            authors_text = str(authors)
        story.append(Paragraph(
            f"Authors: {_xml_escape(_safe_text(authors_text))}",
            styles["CenterText"],
        ))

    # Analysis metadata
    analyzed_at = session.get("created_at", datetime.now(timezone.utc).isoformat())
    session_id = session.get("id", "unknown")
    story.append(Paragraph(f"Analyzed: {str(analyzed_at)[:19]}", styles["CenterText"]))
    story.append(Paragraph(f"Session: {session_id[:8]}...", styles["CenterText"]))
    story.append(Spacer(1, 1 * inch))
    story.append(Paragraph(
        "Generated by Patent Gap Finder v1.0.0",
        styles["CenterText"],
    ))
    story.append(Spacer(1, 0.3 * inch))
    story.append(Paragraph(
        "<i>This report is AI-generated and does not constitute legal advice.</i>",
        styles["Disclaimer"],
    ))
    story.append(PageBreak())


def _build_executive_summary(
    story: list,
    styles: dict,
    session: dict,
    patent_count: int,
    cluster_count: int,
    opportunity_count: int,
    top_opp_count: int,
) -> None:
    """Add executive summary page."""
    story.append(Paragraph("Executive Summary", styles["SectionHeading"]))
    story.append(HRFlowable(width="100%", thickness=1, color=BORDER_GRAY, spaceAfter=12))

    # Paper abstract
    abstract = session.get("paper_summary") or "No abstract available."
    story.append(Paragraph(
        _xml_escape(_safe_text(abstract)),
        styles["BodyText"],
    ))
    story.append(Spacer(1, 0.2 * inch))

    # Analysis stats table
    ipc_codes = session.get("top_ipc_codes") or []
    ipc_text = ", ".join(str(c) for c in ipc_codes[:6]) if ipc_codes else "N/A"

    data = [
        ["Metric", "Value"],
        ["Patents analyzed", str(patent_count)],
        ["Patent clusters identified", str(cluster_count)],
        ["Whitespace opportunities found", str(opportunity_count)],
        ["High-novelty opportunities (≥0.75)", str(top_opp_count)],
        ["IPC classification", ipc_text],
        ["Search coverage", "USPTO + EPO + Google Patents"],
    ]
    table = _make_table(data, col_widths=[3 * inch, 3.5 * inch])
    story.append(table)
    story.append(PageBreak())


def _build_landscape_overview(
    story: list,
    styles: dict,
    clusters: list[dict],
    patents: list[dict],
) -> None:
    """Add patent landscape overview page."""
    story.append(Paragraph("Patent Landscape Overview", styles["SectionHeading"]))
    story.append(HRFlowable(width="100%", thickness=1, color=BORDER_GRAY, spaceAfter=12))

    if clusters:
        # Cluster table
        data = [["Cluster", "Patent Count", "Technical Domain", "Avg. Similarity"]]
        for cl in clusters:
            data.append([
                _xml_escape(_safe_text(cl.get("label", "Unknown"))),
                str(cl.get("patent_count", 0)),
                _xml_escape(_safe_text(cl.get("technical_domain", ""))),
                f"{cl.get('avg_internal_similarity', 0.0):.3f}",
            ])
        table = _make_table(data, col_widths=[2.2 * inch, 1 * inch, 2.5 * inch, 1 * inch])
        story.append(table)
    else:
        story.append(Paragraph("No clusters available.", styles["BodyText"]))

    story.append(Spacer(1, 0.3 * inch))

    # IPC coverage summary
    ipc_set: set[str] = set()
    for p in patents:
        codes = p.get("ipc_codes") or []
        for code in codes:
            if isinstance(code, str):
                ipc_set.add(code[:4])
    if ipc_set:
        story.append(Paragraph("IPC Code Coverage", styles["SubSectionHeading"]))
        story.append(Paragraph(
            f"Prior art spans {len(ipc_set)} IPC subclasses: {', '.join(sorted(ipc_set)[:12])}",
            styles["BodyText"],
        ))

    story.append(PageBreak())


def _build_opportunity_page(
    story: list,
    styles: dict,
    opp: dict,
    index: int,
    patents_by_id: dict,
) -> None:
    """Add a single whitespace opportunity page."""
    story.append(Paragraph(
        f"Whitespace Opportunity #{index}",
        styles["SectionHeading"],
    ))
    story.append(HRFlowable(width="100%", thickness=1, color=BORDER_GRAY, spaceAfter=12))

    # Claim text excerpt
    claim_text = opp.get("claim_text", "")
    excerpt = claim_text[:200] + ("..." if len(claim_text) > 200 else "")
    story.append(Paragraph(
        f"<b>Claim:</b> {_xml_escape(_safe_text(excerpt))}",
        styles["BodyText"],
    ))

    # Novelty score
    score = opp.get("novelty_score", 0.0)
    bar = _novelty_bar(score)
    color = "#22c55e" if score >= 0.75 else "#f59e0b" if score >= 0.5 else "#ef4444"
    story.append(Paragraph(
        f"<b>Novelty Score:</b> <font color='{color}'>{bar}</font>",
        styles["BodyText"],
    ))

    # Recommended scope
    scope = opp.get("recommended_claim_scope", "medium")
    story.append(Paragraph(
        f"<b>Recommended Claim Scope:</b> {scope.upper()}",
        styles["BodyText"],
    ))
    story.append(Spacer(1, 0.15 * inch))

    # Gemini assessment
    assessment = opp.get("gemini_assessment") or ""
    if assessment:
        story.append(Paragraph("<b>AI Novelty Assessment:</b>", styles["BodyText"]))
        story.append(Paragraph(
            _xml_escape(_safe_text(assessment)),
            styles["BodyText"],
        ))
    story.append(Spacer(1, 0.15 * inch))

    # Nearest prior art table
    nearest_ids = opp.get("nearest_patent_ids") or []
    nearest_titles = opp.get("nearest_patent_titles") or []
    if nearest_ids:
        story.append(Paragraph("<b>Nearest Prior Art:</b>", styles["BodyText"]))
        data = [["Patent ID", "Title", "Assignee"]]
        for pid, title in zip(nearest_ids[:3], nearest_titles[:3]):
            p_detail = patents_by_id.get(pid, {})
            data.append([
                str(pid)[:20],
                _xml_escape(_safe_text(str(title)[:60])),
                _xml_escape(_safe_text(p_detail.get("assignee", "N/A")[:30])),
            ])
        table = _make_table(data, col_widths=[1.5 * inch, 3.5 * inch, 1.7 * inch])
        story.append(table)

    # IPC whitespace codes
    ipc_ws = opp.get("ipc_whitespace_codes") or []
    if ipc_ws:
        story.append(Spacer(1, 0.1 * inch))
        story.append(Paragraph(
            f"<b>IPC Gap Codes:</b> {', '.join(str(c) for c in ipc_ws)}",
            styles["BodyText"],
        ))

    story.append(PageBreak())


def _build_claims_section(
    story: list,
    styles: dict,
    claim_sets: list[dict],
) -> None:
    """Add drafted patent claims section."""
    if not claim_sets:
        story.append(Paragraph("Drafted Patent Claims", styles["SectionHeading"]))
        story.append(Paragraph(
            "No claims have been drafted for this session. Run the draft_claims "
            "tool to generate USPTO-format patent claims.",
            styles["BodyText"],
        ))
        story.append(PageBreak())
        return

    for i, cs in enumerate(claim_sets, 1):
        story.append(Paragraph(
            f"Claim Set for Opportunity #{i}",
            styles["SectionHeading"],
        ))
        story.append(HRFlowable(
            width="100%", thickness=1, color=BORDER_GRAY, spaceAfter=12,
        ))

        # IPC codes
        ipc_codes = cs.get("ipc_codes") or []
        if ipc_codes:
            story.append(Paragraph(
                f"<b>IPC Filing Codes:</b> {', '.join(str(c) for c in ipc_codes)}",
                styles["BodyText"],
            ))

        # Format claims
        claims_data = cs.get("claims") or []
        drafted = [
            DraftedClaim(**c) if isinstance(c, dict) else c
            for c in claims_data
        ]
        if drafted:
            formatted = format_claim_set(drafted)
            for line in formatted.split("\n"):
                if line.strip():
                    story.append(Paragraph(
                        _xml_escape(_safe_text(line)),
                        styles["ClaimText"],
                    ))
                else:
                    story.append(Spacer(1, 0.08 * inch))

            # Validation warnings
            warnings = validate_claim_set(drafted)
            if warnings:
                story.append(Spacer(1, 0.1 * inch))
                story.append(Paragraph(
                    "<b>Validation Notes:</b>",
                    styles["BodyText"],
                ))
                for w in warnings:
                    story.append(Paragraph(
                        f"• {_xml_escape(_safe_text(w))}",
                        styles["SmallText"],
                    ))

        # Disclaimer
        story.append(Spacer(1, 0.15 * inch))
        story.append(Paragraph(
            cs.get("gemini_disclaimer", "AI-generated claims — consult a patent attorney."),
            styles["Disclaimer"],
        ))
        story.append(PageBreak())


def _build_methodology_page(story: list, styles: dict) -> None:
    """Add methodology and disclaimer page."""
    story.append(Paragraph("Methodology &amp; Disclaimer", styles["SectionHeading"]))
    story.append(HRFlowable(width="100%", thickness=1, color=BORDER_GRAY, spaceAfter=12))

    story.append(Paragraph("<b>How This Analysis Works</b>", styles["SubSectionHeading"]))
    story.append(Paragraph(
        "Patent Gap Finder uses a multi-stage pipeline to identify patentable "
        "white-space in a research paper. First, the paper is parsed and key technical "
        "contributions are extracted as candidate patent claims using Google Gemini AI. "
        "These claims are classified into IPC/CPC patent codes to identify the relevant "
        "technological domain.",
        styles["BodyText"],
    ))
    story.append(Paragraph(
        "Next, the system searches three patent databases (USPTO, EPO, and Google Patents "
        "via SerpAPI) to build a comprehensive prior art landscape. All retrieved patents "
        "are embedded using sentence-transformers and clustered with HDBSCAN to reveal the "
        "structure of the existing patent space.",
        styles["BodyText"],
    ))
    story.append(Paragraph(
        "Finally, the extracted claims are compared against the patent landscape using "
        "vector similarity and Gemini AI novelty assessment. Claims that fall in regions "
        "with low patent density are flagged as white-space opportunities. For each "
        "opportunity, USPTO-format patent claims are drafted with proper independent "
        "and dependent claim structure.",
        styles["BodyText"],
    ))

    story.append(Spacer(1, 0.2 * inch))
    story.append(Paragraph("<b>Data Sources</b>", styles["SubSectionHeading"]))
    data = [
        ["Source", "Coverage", "Method"],
        ["USPTO PatentsView", "US patents (2000–present)", "REST API"],
        ["EPO Open Patent Services", "EU/worldwide patents", "OPS API"],
        ["SerpAPI / Google Patents", "Global patent search", "Web scraping API"],
    ]
    table = _make_table(data, col_widths=[2 * inch, 2.5 * inch, 2.2 * inch])
    story.append(table)

    story.append(Spacer(1, 0.15 * inch))
    story.append(Paragraph("<b>AI Model</b>", styles["SubSectionHeading"]))
    story.append(Paragraph(
        "Gemini 1.5 Flash (Google DeepMind) — used for claim extraction, IPC "
        "classification, cluster labeling, novelty assessment, and claim drafting.",
        styles["BodyText"],
    ))

    story.append(Spacer(1, 0.3 * inch))
    story.append(Paragraph("<b>Legal Disclaimer</b>", styles["SubSectionHeading"]))
    story.append(Paragraph(
        "This report was generated by an AI-powered patent gap analysis tool. The patent "
        "claims, assessments, and recommendations contained herein are provided for "
        "informational and research purposes only. They do NOT constitute legal advice. "
        "No attorney-client relationship is created by use of this tool. Before filing "
        "any patent application, you must consult a registered patent attorney or agent "
        "who can conduct a proper patentability analysis, prior art search, and claim "
        "drafting review. AI-generated claims may contain errors, omissions, or fail to "
        "meet USPTO requirements. The creators of this tool accept no liability for any "
        "decisions made based on this report.",
        styles["Disclaimer"],
    ))


# ──────────────────────────────────────────────────────────────────────
# Main report generation function
# ──────────────────────────────────────────────────────────────────────


async def generate_report(session_id: str) -> bytes:
    """Generate the complete patent gap analysis PDF report.

    Loads all session data from PostgreSQL and produces a multi-page
    PDF with cover page, summary, landscape, opportunities, claims,
    and methodology sections.

    Args:
        session_id: UUID of the analysis session.

    Returns:
        PDF file content as bytes.

    Raises:
        ValueError: If session_id is not found.
    """
    from patent_gap_finder.db.connection import get_db_session
    from patent_gap_finder.db.models import (
        AnalysisSession,
        PatentRecord,
        WhitespaceOpportunityRecord,
    )
    from patent_gap_finder.db.repositories import (
        landscape_repo,
        patent_repo,
    )

    async with get_db_session() as db:
        # Load session
        from sqlalchemy import select

        result = await db.execute(
            select(AnalysisSession).where(AnalysisSession.id == session_id)
        )
        session_obj = result.scalars().first()
        if not session_obj:
            raise ValueError(f"Session {session_id} not found")

        session_data = session_obj.to_dict()

        # Load patents
        patents = await patent_repo.get_patents_for_session(db, session_id)
        patents_list = []
        patents_by_id = {}
        for p in patents:
            p_dict = {
                "patent_id": p.patent_id,
                "title": p.title,
                "abstract": p.abstract,
                "assignee": p.assignee,
                "ipc_codes": p.ipc_codes,
                "cluster_id": p.cluster_id,
                "cluster_label": p.cluster_label,
            }
            patents_list.append(p_dict)
            patents_by_id[p.patent_id] = p_dict

        # Load clusters
        landscape_job = await landscape_repo.get_latest_landscape_job(db, session_id)
        clusters = []
        if landscape_job and landscape_job.cluster_records:
            for cr in landscape_job.cluster_records:
                if not cr.is_noise_cluster:
                    clusters.append({
                        "label": cr.label or "Unknown",
                        "patent_count": cr.patent_count,
                        "technical_domain": cr.technical_domain or "",
                        "avg_internal_similarity": cr.avg_internal_similarity or 0.0,
                    })

        # Load whitespace opportunities
        opps = await landscape_repo.get_whitespace_opportunities(db, session_id)
        opp_list = []
        for o in opps:
            opp_list.append({
                "id": o.id,
                "claim_text": o.claim_text,
                "claim_type": o.claim_type,
                "novelty_score": o.novelty_score,
                "nearest_cluster_label": o.nearest_cluster_label,
                "nearest_patent_ids": o.nearest_patent_ids,
                "nearest_patent_titles": o.nearest_patent_titles,
                "gemini_assessment": o.gemini_assessment,
                "gemini_confidence": o.gemini_confidence,
                "recommended_claim_scope": o.recommended_claim_scope,
                "ipc_whitespace_codes": o.ipc_whitespace_codes,
                "is_whitespace": o.is_whitespace,
            })

        # Load drafted claims
        claim_sets = []
        try:
            from patent_gap_finder.db.repositories import drafts_repo

            raw_sets = await drafts_repo.get_claim_sets_for_session(db, session_id)
            claim_sets = raw_sets
        except Exception as e:
            logger.warning("Could not load drafted claims: %s", e)

    # Build PDF
    styles = _build_styles()
    story: list = []
    buffer = io.BytesIO()

    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=0.75 * inch,
        leftMargin=0.75 * inch,
        topMargin=1 * inch,
        bottomMargin=0.75 * inch,
        title="Patent Gap Analysis Report",
        author="Patent Gap Finder",
    )

    # Page 1: Cover
    _build_cover_page(story, styles, session_data)

    # Page 2: Executive Summary
    ws_opps = [o for o in opp_list if o.get("is_whitespace")]
    top_count = sum(1 for o in ws_opps if o.get("novelty_score", 0) >= 0.75)
    _build_executive_summary(
        story,
        styles,
        session_data,
        patent_count=len(patents_list),
        cluster_count=len(clusters),
        opportunity_count=len(ws_opps),
        top_opp_count=top_count,
    )

    # Page 3: Landscape Overview
    _build_landscape_overview(story, styles, clusters, patents_list)

    # Pages 4+: Whitespace Opportunities
    sorted_opps = sorted(ws_opps, key=lambda o: o.get("novelty_score", 0), reverse=True)
    for i, opp in enumerate(sorted_opps, 1):
        _build_opportunity_page(story, styles, opp, i, patents_by_id)

    # Claims section
    _build_claims_section(story, styles, claim_sets)

    # Final page: Methodology
    _build_methodology_page(story, styles)

    # Build the PDF
    doc.build(story, onFirstPage=_add_page_number, onLaterPages=_add_page_number)

    pdf_bytes = buffer.getvalue()
    logger.info("Generated PDF report: %d bytes", len(pdf_bytes))
    return pdf_bytes
