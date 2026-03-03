"""
PDF report generation using ReportLab.
Produces a branded A4 weekly intelligence briefing.
"""

import os
from datetime import datetime
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, HRFlowable
from reportlab.lib.colors import HexColor


BRAND_DARK = HexColor("#1a365d")
BRAND_MID = HexColor("#2b6cb0")
BRAND_LIGHT = HexColor("#4a5568")
BRAND_MUTED = HexColor("#a0aec0")
TEXT_DARK = HexColor("#2d3748")
ACCENT = HexColor("#e53e3e")

# Built once at import time — styles are static
_STYLES = None


def _build_styles():
    base = getSampleStyleSheet()

    title = ParagraphStyle(
        "RIQTitle",
        parent=base["Title"],
        fontSize=24,
        textColor=BRAND_DARK,
        spaceAfter=4,
        fontName="Helvetica-Bold",
    )
    subtitle = ParagraphStyle(
        "RIQSubtitle",
        parent=base["Normal"],
        fontSize=10,
        textColor=BRAND_LIGHT,
        spaceAfter=4,
    )
    week_label = ParagraphStyle(
        "RIQWeek",
        parent=base["Normal"],
        fontSize=9,
        textColor=BRAND_MUTED,
        spaceAfter=16,
    )
    heading = ParagraphStyle(
        "RIQHeading",
        parent=base["Heading2"],
        fontSize=13,
        textColor=BRAND_MID,
        spaceBefore=14,
        spaceAfter=6,
        fontName="Helvetica-Bold",
    )
    body = ParagraphStyle(
        "RIQBody",
        parent=base["Normal"],
        fontSize=10,
        leading=15,
        textColor=TEXT_DARK,
        spaceAfter=5,
    )
    bullet = ParagraphStyle(
        "RIQBullet",
        parent=body,
        leftIndent=14,
        spaceAfter=4,
    )
    numbered = ParagraphStyle(
        "RIQNumbered",
        parent=body,
        leftIndent=14,
        fontName="Helvetica-Bold",
        spaceAfter=4,
    )
    footer = ParagraphStyle(
        "RIQFooter",
        parent=base["Normal"],
        fontSize=8,
        textColor=BRAND_MUTED,
        alignment=1,  # centre
    )

    return {
        "title": title,
        "subtitle": subtitle,
        "week_label": week_label,
        "heading": heading,
        "body": body,
        "bullet": bullet,
        "numbered": numbered,
        "footer": footer,
    }


def _get_styles():
    global _STYLES
    if _STYLES is None:
        _STYLES = _build_styles()
    return _STYLES


def generate_pdf_report(
    report_text: str,
    restaurant_name: str,
    week_start: str,
    week_end: str,
    output_path: str,
    kpi_summary: str = "",
) -> str:
    """
    Generate a branded PDF from the markdown-style report text.
    Optionally includes a KPI summary box below the header.
    Returns the output_path on success.
    """
    parent_dir = os.path.dirname(output_path)
    if parent_dir:
        os.makedirs(parent_dir, exist_ok=True)

    doc = SimpleDocTemplate(
        output_path,
        pagesize=A4,
        topMargin=22 * mm,
        bottomMargin=22 * mm,
        leftMargin=22 * mm,
        rightMargin=22 * mm,
    )

    styles = _get_styles()
    story = []

    # Header
    story.append(Paragraph("Restaurant-IQ", styles["title"]))
    story.append(Paragraph(f"Weekly Intelligence Briefing — {restaurant_name}", styles["subtitle"]))
    story.append(
        Paragraph(
            f"Period: {week_start} to {week_end} &nbsp;&nbsp;|&nbsp;&nbsp; "
            f"Generated: {datetime.now().strftime('%d %B %Y at %H:%M')}",
            styles["week_label"],
        )
    )
    story.append(HRFlowable(width="100%", thickness=1, color=BRAND_MID, spaceAfter=10))

    # KPI summary section (if provided)
    if kpi_summary:
        story.append(Paragraph("KEY PERFORMANCE INDICATORS", styles["heading"]))
        for kpi_line in kpi_summary.split("\n"):
            kpi_line = kpi_line.strip()
            if not kpi_line or kpi_line.startswith("─") or kpi_line.startswith("KPI DASHBOARD"):
                continue
            story.append(Paragraph(kpi_line, styles["body"]))
        story.append(HRFlowable(width="100%", thickness=0.5, color=BRAND_MUTED, spaceAfter=8))
        story.append(Spacer(1, 6))

    # Parse report text
    for line in report_text.split("\n"):
        line = line.strip()
        if not line:
            story.append(Spacer(1, 5))
            continue

        if line.startswith("## "):
            heading_text = line[3:].strip()
            story.append(Paragraph(heading_text, styles["heading"]))

        elif line.startswith("# "):
            heading_text = line[2:].strip()
            story.append(Paragraph(heading_text, styles["heading"]))

        elif line.startswith("- ") or line.startswith("* "):
            content = line[2:].strip()
            story.append(Paragraph(f"&#8226; {content}", styles["bullet"]))

        elif line[:2] in ("1.", "2.", "3.", "4.", "5.", "6.", "7.", "8.", "9."):
            story.append(Paragraph(f"<b>{line}</b>", styles["numbered"]))

        elif line.startswith("---"):
            story.append(HRFlowable(width="100%", thickness=0.5, color=BRAND_MUTED, spaceAfter=6))

        else:
            story.append(Paragraph(line, styles["body"]))

    # Footer
    story.append(Spacer(1, 20))
    story.append(HRFlowable(width="100%", thickness=0.5, color=BRAND_MUTED, spaceAfter=8))
    story.append(
        Paragraph(
            "Restaurant-IQ &nbsp;|&nbsp; AI-Driven Intelligence for London Food Businesses "
            "&nbsp;|&nbsp; Confidential",
            styles["footer"],
        )
    )

    doc.build(story)
    return output_path
