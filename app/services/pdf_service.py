"""
Generate candidate evaluation PDF reports using ReportLab.
"""

import os
from datetime import datetime, timezone
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable,
)

# Directory where PDFs are saved
REPORTS_DIR = Path("app/runtime/reports")
REPORTS_DIR.mkdir(parents=True, exist_ok=True)


# ---------- colour palette ----------
AZIRO_BLUE = colors.HexColor("#1a73e8")
AZIRO_DARK = colors.HexColor("#1e293b")
PASS_GREEN = colors.HexColor("#16a34a")
FAIL_RED = colors.HexColor("#dc2626")
PENDING_GREY = colors.HexColor("#6b7280")
HEADER_BG = colors.HexColor("#e8f0fe")
ROW_ALT_BG = colors.HexColor("#f8fafc")


def _build_styles():
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(
        "ReportTitle",
        parent=styles["Heading1"],
        fontSize=18,
        textColor=AZIRO_DARK,
        spaceAfter=2 * mm,
    ))
    styles.add(ParagraphStyle(
        "SubTitle",
        parent=styles["Normal"],
        fontSize=10,
        textColor=colors.grey,
        spaceAfter=4 * mm,
    ))
    styles.add(ParagraphStyle(
        "SectionHead",
        parent=styles["Heading2"],
        fontSize=13,
        textColor=AZIRO_BLUE,
        spaceBefore=6 * mm,
        spaceAfter=3 * mm,
    ))
    styles.add(ParagraphStyle(
        "CellText",
        parent=styles["Normal"],
        fontSize=9,
        leading=12,
    ))
    styles.add(ParagraphStyle(
        "CellTextBold",
        parent=styles["Normal"],
        fontSize=9,
        leading=12,
        fontName="Helvetica-Bold",
    ))
    return styles


def _status_color(status: str):
    if status == "PASS":
        return PASS_GREEN
    if status == "FAIL":
        return FAIL_RED
    return PENDING_GREY


def generate_candidate_pdf(candidate_data: dict) -> str:
    """
    Generate a PDF score card for a single candidate.

    Parameters
    ----------
    candidate_data : dict
        Same shape as returned by db_service.get_all_candidates_with_results()

    Returns
    -------
    str  – filename (relative to REPORTS_DIR)
    """
    name = candidate_data["name"]
    email = candidate_data["email"]
    role = candidate_data["role"]
    rounds = candidate_data.get("rounds", {})
    summary = candidate_data.get("summary", {})
    ts_id = candidate_data.get("test_session_id", 0)

    safe_name = "".join(c if c.isalnum() or c in " _-" else "_" for c in name).strip()
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"{safe_name}_{ts_id}_{timestamp}.pdf"
    filepath = REPORTS_DIR / filename

    doc = SimpleDocTemplate(
        str(filepath),
        pagesize=A4,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
    )

    styles = _build_styles()
    elements = []

    # ---- Title ----
    elements.append(Paragraph("Candidate Evaluation Report", styles["ReportTitle"]))
    elements.append(Paragraph(
        f"Generated on {datetime.now(timezone.utc).strftime('%d %b %Y, %H:%M UTC')}",
        styles["SubTitle"],
    ))
    elements.append(HRFlowable(width="100%", thickness=1, color=AZIRO_BLUE))
    elements.append(Spacer(1, 4 * mm))

    # ---- Candidate info ----
    elements.append(Paragraph("Candidate Details", styles["SectionHead"]))
    info_data = [
        ["Name", name],
        ["Email", email],
        ["Role", role],
        ["Batch", candidate_data.get("batch_id", "—")],
    ]
    info_table = Table(info_data, colWidths=[40 * mm, 120 * mm])
    info_table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    elements.append(info_table)
    elements.append(Spacer(1, 4 * mm))

    # ---- Round scores table ----
    elements.append(Paragraph("Round-wise Performance", styles["SectionHead"]))

    header = ["Round", "Label", "Score", "Percentage", "Threshold", "Status"]
    table_data = [header]

    for rk, rd in rounds.items():
        status_text = rd["status"]
        score_text = f'{rd["correct"]} / {rd["total"]}'
        pct_text = f'{rd["percentage"]:.1f}%'
        thresh_text = f'{rd["pass_threshold"]}%'
        table_data.append([rk, rd["round_label"], score_text, pct_text, thresh_text, status_text])

    col_widths = [18 * mm, 52 * mm, 25 * mm, 25 * mm, 25 * mm, 25 * mm]
    score_table = Table(table_data, colWidths=col_widths)

    # Build style commands
    ts_cmds = [
        # Header row
        ("BACKGROUND", (0, 0), (-1, 0), HEADER_BG),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("ALIGN", (2, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]

    # Alternating row backgrounds
    for i in range(1, len(table_data)):
        if i % 2 == 0:
            ts_cmds.append(("BACKGROUND", (0, i), (-1, i), ROW_ALT_BG))

    # Colour the Status column
    for i in range(1, len(table_data)):
        status_val = table_data[i][-1]
        ts_cmds.append(("TEXTCOLOR", (-1, i), (-1, i), _status_color(status_val)))
        ts_cmds.append(("FONTNAME", (-1, i), (-1, i), "Helvetica-Bold"))

    score_table.setStyle(TableStyle(ts_cmds))
    elements.append(score_table)
    elements.append(Spacer(1, 6 * mm))

    # ---- Summary ----
    elements.append(Paragraph("Summary", styles["SectionHead"]))
    verdict = summary.get("overall_verdict", "Pending")
    verdict_color = (
        PASS_GREEN if verdict == "Selected"
        else FAIL_RED if verdict == "Rejected"
        else PENDING_GREY
    )

    summary_data = [
        ["Total Rounds", str(summary.get("total_rounds", 0))],
        ["Attempted", str(summary.get("attempted_rounds", 0))],
        ["Passed", str(summary.get("passed_rounds", 0))],
        ["Failed", str(summary.get("failed_rounds", 0))],
        ["Overall %", f'{summary.get("overall_percentage", 0):.1f}%'],
        ["Verdict", verdict],
    ]
    sum_table = Table(summary_data, colWidths=[40 * mm, 50 * mm])
    sum_cmds = [
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("TEXTCOLOR", (1, -1), (1, -1), verdict_color),
        ("FONTNAME", (1, -1), (1, -1), "Helvetica-Bold"),
    ]
    sum_table.setStyle(TableStyle(sum_cmds))
    elements.append(sum_table)

    # ---- Footer ----
    elements.append(Spacer(1, 10 * mm))
    elements.append(HRFlowable(width="100%", thickness=0.5, color=colors.grey))
    elements.append(Spacer(1, 2 * mm))
    elements.append(Paragraph(
        "This report was auto-generated by the Aziro AI Hiring Platform. "
        "Scores are computed from online assessments only.",
        ParagraphStyle("Footer", fontSize=8, textColor=colors.grey),
    ))

    doc.build(elements)
    return filename
