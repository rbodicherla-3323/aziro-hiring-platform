"""
Generate candidate evaluation PDF reports using ReportLab.
"""

import os
import re
from datetime import datetime, timezone
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable,
)
from app.services.ai_generator import generate_evaluation_summary
from app.utils.round_order import ordered_present_round_keys, round_number_map

# Directory where PDFs are saved (use absolute path relative to this file)
_SERVICE_DIR = Path(__file__).resolve().parent          # app/services/
_APP_DIR = _SERVICE_DIR.parent                          # app/
REPORTS_DIR = _APP_DIR / "runtime" / "reports"
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


def _to_inline_html(text: str) -> str:
    """Convert markdown bold (**text**) into ReportLab-friendly inline HTML."""
    parts = re.split(r"(\*\*.*?\*\*)", str(text))
    rendered = []
    for part in parts:
        if part.startswith("**") and part.endswith("**") and len(part) >= 4:
            rendered.append(f"<b>{escape(part[2:-2])}</b>")
        else:
            rendered.append(escape(part))
    return "".join(rendered)


def _markdown_to_reportlab_html(summary_text: str) -> str:
    """Render basic markdown to HTML supported by ReportLab Paragraph."""
    lines = str(summary_text or "").splitlines()
    html_lines = []
    for raw in lines:
        line = raw.rstrip()
        stripped = line.strip()
        if not stripped:
            html_lines.append("<br/>")
            continue

        if stripped.startswith("### "):
            html_lines.append(f"<b>{_to_inline_html(stripped[4:])}</b>")
            continue

        if stripped.startswith("- "):
            html_lines.append(f"&bull; {_to_inline_html(stripped[2:])}")
            continue

        if stripped.startswith("*   "):
            html_lines.append(f"&bull; {_to_inline_html(stripped[4:])}")
            continue

        if stripped.startswith("* "):
            html_lines.append(f"&bull; {_to_inline_html(stripped[2:])}")
            continue

        html_lines.append(_to_inline_html(stripped))

    return "<br/>".join(html_lines)


def _summary_html(summary_text: str) -> str:
    """Convert markdown-ish summary into richer ReportLab HTML."""
    lines = str(summary_text or "").splitlines()
    html_lines = []
    in_code_block = False

    for raw in lines:
        line = raw.rstrip("\n")
        stripped = line.strip()

        if stripped.startswith("```"):
            in_code_block = not in_code_block
            continue

        if in_code_block:
            html_lines.append(
                f"<font face='Courier' size='8' color='#0f172a'>{escape(line)}</font>"
            )
            continue

        if not stripped:
            html_lines.append("<br/>")
            continue

        if stripped.startswith("### "):
            html_lines.append(
                "<font size='11' color='#1a73e8'><b>"
                f"{_to_inline_html(stripped[4:])}"
                "</b></font>"
            )
            continue

        if stripped.rstrip(":").lower() == "key insights":
            html_lines.append(
                "<font size='10' color='#1e293b'><b>Key Insights:</b></font>"
            )
            continue

        if stripped.startswith("**") and stripped.endswith(":**"):
            html_lines.append(
                "<font size='10' color='#1e293b'><b>"
                f"{_to_inline_html(stripped[2:-3])}:</b></font>"
            )
            continue

        if stripped.startswith("- "):
            html_lines.append(f"&bull; {_to_inline_html(stripped[2:])}")
            continue

        if stripped.startswith("*   "):
            html_lines.append(f"&bull; {_to_inline_html(stripped[4:])}")
            continue

        if stripped.startswith("* "):
            html_lines.append(f"&bull; {_to_inline_html(stripped[2:])}")
            continue

        if stripped.startswith("• "):
            html_lines.append(f"&bull; {_to_inline_html(stripped[2:])}")
            continue

        html_lines.append(_to_inline_html(stripped))

    return "<br/>".join(html_lines)


def _build_summary_card(title: str, summary_text: str, styles, width: float):
    """Render summary into a bordered card with styled heading and body."""
    title_para = Paragraph(
        f"<font color='#1a73e8'><b>{escape(title)}</b></font>",
        styles["CellTextBold"],
    )
    body_html = _summary_html(summary_text)
    body_para = Paragraph(body_html, styles["CellText"])

    card = Table([[title_para], [body_para]], colWidths=[width])
    card.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, 0), colors.HexColor("#e8f0fe")),
        ("BACKGROUND", (0, 1), (0, 1), colors.HexColor("#f8fafc")),
        ("BOX", (0, 0), (-1, -1), 0.8, colors.HexColor("#cbd5e1")),
        ("LINEBELOW", (0, 0), (0, 0), 0.6, colors.HexColor("#cbd5e1")),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    return card


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
    proctoring_summary = candidate_data.get("proctoring_summary") or {}
    plagiarism_summary = candidate_data.get("plagiarism_summary") or {}
    ai_overall_summary = candidate_data.get("ai_overall_summary")
    ai_coding_summary = candidate_data.get("ai_coding_summary")
    if not ai_overall_summary:
        try:
            from app.services.evaluation_service import EvaluationService

            ai_overall_summary = EvaluationService.generate_candidate_overall_summary(
                email,
                candidate_data=candidate_data,
            )
        except Exception:
            ai_overall_summary = generate_evaluation_summary(candidate_data)
    if not ai_coding_summary:
        try:
            from app.services.evaluation_service import EvaluationService

            ai_coding_summary = EvaluationService.generate_candidate_coding_round_summary(
                email,
                candidate_data=candidate_data,
            )
        except Exception:
            ai_coding_summary = None
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

    # ---- Proctoring summary ----
    elements.append(Paragraph("Proctoring Summary", styles["SectionHead"]))
    proctor_rows = [
        ["Tab Switches", str(proctoring_summary.get("tab_switches", 0))],
        ["Fullscreen Exits", str(proctoring_summary.get("fullscreen_exits", 0))],
        ["Multi-Monitor Events", str(proctoring_summary.get("multi_monitor_events", 0))],
        ["Keyboard Shortcuts Blocked", str(proctoring_summary.get("keyboard_shortcuts_blocked", 0))],
        ["Copy/Paste Blocks", str(proctoring_summary.get("copy_paste_blocks", 0))],
        ["Right Click Blocks", str(proctoring_summary.get("right_click_blocks", 0))],
        ["Screenshots Captured", str(proctoring_summary.get("screenshot_captures", 0))],
        ["Multiple Face Events", str(proctoring_summary.get("multi_face_events", 0))],
        ["No Face Events", str(proctoring_summary.get("no_face_events", 0))],
        ["No Face Duration", f"{float(proctoring_summary.get('no_face_duration_seconds', 0) or 0):.1f}s"],
        ["Attention Deviations", str(proctoring_summary.get("attention_deviation_count", 0))],
        ["Suspicion Score", str(proctoring_summary.get("suspicion_score", 0))],
        ["Suspicion Threshold Exceeded", "YES" if proctoring_summary.get("suspicion_threshold_exceeded") else "NO"],
        ["Suspicion Threshold Events", str(proctoring_summary.get("suspicion_threshold_event_count", 0))],
    ]
    proctor_table = Table(proctor_rows, colWidths=[70 * mm, 90 * mm])
    proctor_table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("TEXTCOLOR", (0, 0), (-1, -1), AZIRO_DARK),
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#fffdf6")),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e7dcbf")),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    elements.append(proctor_table)
    elements.append(Spacer(1, 6 * mm))

    # ---- Plagiarism summary ----
    elements.append(Paragraph("Code Similarity Summary", styles["SectionHead"]))
    plagiarism_rows = [
        ["Risk Level", str(plagiarism_summary.get("risk_level", "LOW"))],
        ["Risk Score", f"{float(plagiarism_summary.get('risk_score', 0) or 0):.2f}"],
        ["Max Similarity", f"{float(plagiarism_summary.get('max_similarity', 0) or 0):.2f}%"],
        ["Matched Submissions", str(plagiarism_summary.get("matched_submissions", 0))],
        ["Compared Submissions", str(plagiarism_summary.get("compared_submissions", 0))],
    ]
    plagiarism_table = Table(plagiarism_rows, colWidths=[70 * mm, 90 * mm])
    plagiarism_table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("TEXTCOLOR", (0, 0), (-1, -1), AZIRO_DARK),
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f5f9ff")),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#d4e1f5")),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    elements.append(plagiarism_table)

    top_matches = plagiarism_summary.get("top_matches") or []
    if top_matches:
        elements.append(Spacer(1, 3 * mm))
        top_text = []
        for idx, match in enumerate(top_matches[:3], start=1):
            match_email = str(match.get("email", "unknown"))
            similarity = float(match.get("similarity", 0) or 0)
            top_text.append(f"{idx}. {match_email} ({similarity:.2f}%)")
        elements.append(
            Paragraph(
                "Top Similar Matches: " + "; ".join(top_text),
                styles["CellText"],
            )
        )
    elements.append(Spacer(1, 6 * mm))

    # ---- Round scores table ----
    elements.append(Paragraph("Round-wise Performance", styles["SectionHead"]))

    header = ["No", "Round", "Score", "Percentage", "Threshold", "Status"]
    table_data = [header]

    ordered_keys = ordered_present_round_keys(rounds)
    numbers = round_number_map(ordered_keys)

    for rk in ordered_keys:
        rd = rounds.get(rk) or {}
        status_text = rd.get("status", "Pending")
        score_text = f'{rd.get("correct", 0)} / {rd.get("total", 0)}'
        pct_text = f'{float(rd.get("percentage", 0) or 0):.1f}%'
        pass_threshold = rd.get("pass_threshold")
        thresh_text = f"{pass_threshold}%" if pass_threshold is not None else "-"
        number = rd.get("round_number", numbers.get(rk, 0))
        table_data.append([str(number), rd.get("round_label", rk), score_text, pct_text, thresh_text, status_text])

    col_widths = [14 * mm, 56 * mm, 25 * mm, 25 * mm, 25 * mm, 25 * mm]
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

    # ---- Overall Key Insights ----
    elements.append(Paragraph("Overall Evaluation Summary", styles["SectionHead"]))
    if ai_overall_summary:
        elements.append(
            _build_summary_card(
                "Overall Summary As Follows",
                ai_overall_summary,
                styles,
                doc.width,
            )
        )
    else:
        elements.append(Paragraph("Overall summary is unavailable.", styles["CellText"]))

    # ---- Coding Round Insights ----
    elements.append(Spacer(1, 5 * mm))
    elements.append(Paragraph("Coding Round Summary", styles["SectionHead"]))
    if ai_coding_summary:
        elements.append(
            _build_summary_card(
                "Coding Summary As Follows",
                ai_coding_summary,
                styles,
                doc.width,
            )
        )
    else:
        elements.append(Paragraph("Coding summary is unavailable.", styles["CellText"]))


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


def generate_login_activity_pdf(login_rows: list[dict], meta: dict | None = None) -> str:
    """Generate a PDF containing login activity for the selected date range."""
    meta = meta or {}
    period_label = str(meta.get("period_label", "") or "Custom Range").strip()
    generated_by = str(meta.get("generated_by", "") or "").strip()
    total_logins = int(meta.get("total_logins", len(login_rows)) or 0)
    unique_users = int(meta.get("unique_users", 0) or 0)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"login_activity_{timestamp}.pdf"
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

    elements.append(Paragraph("User Login Activity", styles["ReportTitle"]))
    elements.append(Paragraph(
        f"Generated on {datetime.now(timezone.utc).strftime('%d %b %Y, %H:%M UTC')}",
        styles["SubTitle"],
    ))
    elements.append(HRFlowable(width="100%", thickness=1, color=AZIRO_BLUE))
    elements.append(Spacer(1, 4 * mm))

    elements.append(Paragraph("Login Activity Scope", styles["SectionHead"]))
    info_data = [
        ["Period", period_label],
        ["Total Login Events", str(total_logins)],
        ["Unique Users", str(unique_users)],
        ["Generated By", generated_by or "System"],
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
    elements.append(Spacer(1, 6 * mm))

    elements.append(Paragraph("Login Events", styles["SectionHead"]))
    if login_rows:
        table_data = [[
            Paragraph("<b>User</b>", styles["CellTextBold"]),
            Paragraph("<b>Email</b>", styles["CellTextBold"]),
            Paragraph("<b>Provider</b>", styles["CellTextBold"]),
            Paragraph("<b>Logged In At</b>", styles["CellTextBold"]),
        ]]
        for row in login_rows:
            table_data.append([
                Paragraph(escape(str(row.get("user_name", "") or "-").strip() or "-"), styles["CellText"]),
                Paragraph(escape(str(row.get("user_email", "") or "-").strip() or "-"), styles["CellText"]),
                Paragraph(escape(str(row.get("auth_provider", "") or "-").strip() or "-"), styles["CellText"]),
                Paragraph(escape(str(row.get("logged_in_at", "") or "-").strip() or "-"), styles["CellText"]),
            ])

        table = Table(table_data, colWidths=[38 * mm, 60 * mm, 28 * mm, 34 * mm], repeatRows=1)
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), HEADER_BG),
            ("TEXTCOLOR", (0, 0), (-1, 0), AZIRO_DARK),
            ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#cbd5e1")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ]))
        for row_index in range(1, len(table_data)):
            if row_index % 2 == 0:
                table.setStyle(TableStyle([
                    ("BACKGROUND", (0, row_index), (-1, row_index), ROW_ALT_BG),
                ]))
        elements.append(table)
    else:
        elements.append(Paragraph("No login activity was found for the selected date range.", styles["CellText"]))

    elements.append(Spacer(1, 10 * mm))
    elements.append(HRFlowable(width="100%", thickness=0.5, color=colors.grey))
    elements.append(Spacer(1, 2 * mm))
    elements.append(Paragraph(
        "This PDF was generated from the reports admin login activity workflow in the Aziro AI Hiring Platform.",
        ParagraphStyle("Footer", fontSize=8, textColor=colors.grey),
    ))

    doc.build(elements)
    return filename


def generate_consolidated_summary_pdf(summary_text: str, meta: dict | None = None) -> str:
    """
    Generate a PDF for a consolidated candidate summary.

    Parameters
    ----------
    summary_text : str
        Consolidated summary content to render.
    meta : dict | None
        Optional metadata such as role, period label, candidate count, and batch ids.

    Returns
    -------
    str
        Filename relative to REPORTS_DIR.
    """
    meta = meta or {}
    role = str(meta.get("role", "") or "Selected Candidates").strip()
    period_label = str(meta.get("period_label", "") or "Current Scope").strip()
    candidate_count = int(meta.get("candidate_count", 0) or 0)
    batch_ids = [str(value).strip() for value in (meta.get("batch_ids", []) or []) if str(value).strip()]

    safe_role = "".join(ch if ch.isalnum() or ch in " _-" else "_" for ch in role).strip() or "consolidated_summary"
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"{safe_role}_consolidated_{timestamp}.pdf"
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

    elements.append(Paragraph("Consolidated Candidate Summary", styles["ReportTitle"]))
    elements.append(Paragraph(
        f"Generated on {datetime.now(timezone.utc).strftime('%d %b %Y, %H:%M UTC')}",
        styles["SubTitle"],
    ))
    elements.append(HRFlowable(width="100%", thickness=1, color=AZIRO_BLUE))
    elements.append(Spacer(1, 4 * mm))

    elements.append(Paragraph("Summary Scope", styles["SectionHead"]))
    info_data = [
        ["Role", role],
        ["Period", period_label],
        ["Candidates", str(candidate_count)],
        ["Batch", ", ".join(batch_ids) if batch_ids else "All Batches"],
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
    elements.append(Spacer(1, 6 * mm))

    elements.append(Paragraph("Consolidated Interview Feedback", styles["SectionHead"]))
    elements.append(
        _build_summary_card(
            "Consolidated Summary",
            str(summary_text or "").strip() or "Summary content is unavailable.",
            styles,
            doc.width,
        )
    )

    elements.append(Spacer(1, 10 * mm))
    elements.append(HRFlowable(width="100%", thickness=0.5, color=colors.grey))
    elements.append(Spacer(1, 2 * mm))
    elements.append(Paragraph(
        "This PDF was generated from the consolidated summary workflow in the Aziro AI Hiring Platform.",
        ParagraphStyle("Footer", fontSize=8, textColor=colors.grey),
    ))

    doc.build(elements)
    return filename
