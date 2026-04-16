"""
Generate candidate evaluation PDF reports using ReportLab.
"""

import os
import re
import json
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
CARD_BG = colors.HexColor("#f8fbff")
CARD_BORDER = colors.HexColor("#bfdbfe")
SOFT_SKILL_ROW_BG = colors.HexColor("#f0f9ff")
OVERALL_ROW_BG = colors.HexColor("#eef2ff")


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


def _is_soft_skill_round(round_key: str, round_data: dict) -> bool:
    key = str(round_key or "").strip().upper()
    label = str((round_data or {}).get("round_label", "") or "").strip().lower()
    if key == "L5":
        return True
    return "soft skill" in label


def _to_int_score(value) -> int:
    try:
        return int(value or 0)
    except Exception:
        try:
            return int(float(value or 0))
        except Exception:
            return 0


def _build_score_summary_rows(rounds: dict, ordered_keys: list[str]) -> list[list[str]]:
    total_correct = 0
    total_questions = 0
    non_soft_correct = 0
    non_soft_questions = 0

    for round_key in ordered_keys:
        round_data = rounds.get(round_key) or {}
        correct = _to_int_score(round_data.get("correct", 0))
        total = _to_int_score(round_data.get("total", 0))
        total_correct += correct
        total_questions += total
        if not _is_soft_skill_round(round_key, round_data):
            non_soft_correct += correct
            non_soft_questions += total

    def _percentage(correct: int, total: int) -> float:
        if total <= 0:
            return 0.0
        return (float(correct) / float(total)) * 100.0

    return [
        [
            "-",
            "Total (Excl. Soft Skills)",
            f"{non_soft_correct} / {non_soft_questions}",
            f"{_percentage(non_soft_correct, non_soft_questions):.1f}%",
            "-",
            "Summary",
        ],
        [
            "-",
            "Overall (All Rounds)",
            f"{total_correct} / {total_questions}",
            f"{_percentage(total_correct, total_questions):.1f}%",
            "-",
            "Summary",
        ],
    ]


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


def _strip_submitted_code_block(summary_text: str) -> str:
    """Remove trailing Submitted Code section from coding summary text."""
    if not summary_text:
        return summary_text

    lines = str(summary_text).splitlines()
    trimmed = []
    skipping = False
    for line in lines:
        stripped = line.strip()
        if not skipping and stripped.lower().startswith("submitted code:"):
            skipping = True
            continue

        if skipping:
            if stripped.startswith("### ") or stripped.lower().startswith("assessment:") or stripped.lower() == "key insights:":
                skipping = False
                trimmed.append(line)
            continue

        trimmed.append(line)

    cleaned = "\n".join(trimmed).strip()
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned or str(summary_text).strip()


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
        ("BACKGROUND", (0, 0), (0, 0), colors.HexColor("#dbeafe")),
        ("BACKGROUND", (0, 1), (0, 1), CARD_BG),
        ("BOX", (0, 0), (-1, -1), 0.85, CARD_BORDER),
        ("LINEBELOW", (0, 0), (0, 0), 0.7, CARD_BORDER),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    return card


def _normalize_text(value: str) -> str:
    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n")
    return re.sub(r"\s+", " ", text).strip()


def _format_value_for_pdf(value) -> str:
    if value is None:
        return "-"
    if isinstance(value, (str, int, float, bool)):
        text = str(value)
        return text.strip() if text.strip() else "-"
    try:
        return json.dumps(value, ensure_ascii=False)
    except Exception:
        return str(value)


def _code_to_html_block(code_text: str) -> str:
    lines = str(code_text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    if not lines:
        return "<font face='Courier' size='8' color='#dbeafe'>No submitted code found.</font>"

    rendered_lines = []
    for line in lines:
        escaped = escape(line).replace(" ", "&nbsp;").replace("\t", "&nbsp;" * 4)
        rendered_lines.append(f"<font face='Courier' size='8' color='#dbeafe'>{escaped}</font>")
    return "<br/>".join(rendered_lines)


def _status_band_from_percentage(percentage: float) -> tuple[str, str]:
    pct = float(percentage or 0)
    if pct >= 85:
        return "Strong", "Performance indicates strong command of this skill area."
    if pct >= 70:
        return "Competent", "Performance meets expected benchmark with generally good skill alignment."
    if pct >= 50:
        return "Developing", "Performance is partially aligned but requires improvement in consistency."
    return "Needs Improvement", "Performance indicates significant skill gaps for this assessed area."


def _build_mcq_round_analysis(round_label: str, round_data: dict, responses: list[dict]) -> str:
    percentage = float((round_data or {}).get("percentage", 0) or 0)
    attempted = int((round_data or {}).get("attempted", 0) or 0)
    total = int((round_data or {}).get("total", 0) or 0)
    correct = int((round_data or {}).get("correct", 0) or 0)
    threshold = float((round_data or {}).get("pass_threshold", 0) or 0)
    status = str((round_data or {}).get("status", "Pending") or "Pending")
    band, narrative = _status_band_from_percentage(percentage)

    topic_gaps = {}
    unanswered_count = 0
    for response in responses or []:
        if not isinstance(response, dict):
            continue
        is_answered = bool(response.get("is_answered"))
        if not is_answered:
            unanswered_count += 1
            continue
        if bool(response.get("is_correct")):
            continue
        topic = _normalize_text(response.get("topic", ""))
        tags = response.get("tags", []) if isinstance(response.get("tags"), list) else []
        signal = topic or _normalize_text(tags[0] if tags else "") or "concept coverage"
        topic_gaps[signal] = topic_gaps.get(signal, 0) + 1

    top_gaps = sorted(topic_gaps.items(), key=lambda item: (-item[1], item[0].lower()))
    gap_line = ""
    if top_gaps:
        labels = [label for label, _ in top_gaps[:3]]
        gap_line = f" Frequent weakness signals were observed in: {', '.join(labels)}."

    completion_line = ""
    if unanswered_count > 0:
        completion_line = (
            f" {unanswered_count} question(s) were left unanswered, which reduced round-level completion quality."
        )

    return (
        f"{round_label}: {status} with {percentage:.2f}% ({correct}/{total}, attempted {attempted}, threshold {threshold:.1f}%). "
        f"Skill band: {band}. {narrative}{gap_line}{completion_line}"
    )


def _build_coding_skill_analysis(coding_data: dict) -> tuple[list[str], list[str], str]:
    status = str((coding_data or {}).get("status", "") or "")
    percentage = float((coding_data or {}).get("percentage", 0) or 0)
    submitted_code = str((coding_data or {}).get("submitted_code", "") or "")
    normalized_code = submitted_code.lower()
    strengths = []
    weaknesses = []

    if status.upper() == "PASS" and percentage >= 85:
        strengths.append("Implementation appears functionally strong against the evaluated suite.")
        strengths.append("Candidate demonstrates good problem-to-code conversion ability.")
    elif status.upper() == "PASS":
        strengths.append("Submission clears the benchmark and demonstrates practical coding capability.")
        weaknesses.append("Further improvement is needed in robustness and optimization depth.")
    elif percentage >= 55:
        strengths.append("Candidate demonstrates partial logical command of the problem statement.")
        weaknesses.append("Correctness gaps remain and reduce production-readiness.")
    else:
        weaknesses.append("Submission does not satisfy expected correctness for the assigned coding task.")
        weaknesses.append("Algorithmic execution quality requires substantial reinforcement.")

    if "todo" in normalized_code:
        weaknesses.append("TODO markers indicate incomplete implementation.")
    if "print(" in normalized_code or "console.log(" in normalized_code:
        weaknesses.append("Output appears print-centric; evaluator may require return-based contract handling.")
    if ".sort(" in normalized_code or "sorted(" in normalized_code:
        strengths.append("Sorting strategy usage suggests familiarity with common optimization patterns.")
    if re.search(r"\b(for|while)\b", normalized_code):
        strengths.append("Control-flow constructs for iterative evaluation are present in the implementation.")
    if not strengths:
        strengths.append("Submission artifacts were limited; no strong indicators could be confirmed.")
    if not weaknesses:
        weaknesses.append("No critical implementation weakness was explicitly detected in the available snapshot.")

    _, assessment = _status_band_from_percentage(percentage)
    return strengths[:5], weaknesses[:6], assessment


def _render_coding_details_section(elements, styles, coding_round_data: dict, doc_width: float):
    if not isinstance(coding_round_data, dict):
        return

    language = str(coding_round_data.get("language", "") or "").strip() or "Unknown"
    question_title = str(coding_round_data.get("question_title", "") or "").strip() or "Coding Question"
    question_text = str(coding_round_data.get("question_text", "") or "").strip() or "Problem statement unavailable."
    submitted_code = str(coding_round_data.get("submitted_code", "") or "")
    public_tests = coding_round_data.get("public_tests", []) if isinstance(coding_round_data.get("public_tests"), list) else []
    hidden_tests = coding_round_data.get("hidden_tests", []) if isinstance(coding_round_data.get("hidden_tests"), list) else []

    elements.append(Spacer(1, 5 * mm))
    elements.append(Paragraph("Coding Question & Submission Details", styles["SectionHead"]))

    coding_meta = Table(
        [
            ["Round", str(coding_round_data.get("round_label", "Coding Round"))],
            ["Language", language],
            ["Score", f"{float(coding_round_data.get('percentage', 0) or 0):.2f}% ({int(coding_round_data.get('correct', 0) or 0)}/{int(coding_round_data.get('total', 0) or 0)})"],
            ["Status", str(coding_round_data.get("status", "Pending"))],
        ],
        colWidths=[42 * mm, doc_width - (42 * mm)],
    )
    coding_meta.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f8fafc")),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    elements.append(coding_meta)
    elements.append(Spacer(1, 3 * mm))
    elements.append(Paragraph("Assigned Question", styles["CellTextBold"]))

    question_card = Table(
        [
            [
                Paragraph("<b>Question Title</b>", styles["CellTextBold"]),
                Paragraph(escape(question_title), styles["CellText"]),
            ],
            [
                Paragraph("<b>Problem Statement</b>", styles["CellTextBold"]),
                Paragraph(escape(question_text), styles["CellText"]),
            ],
        ],
        colWidths=[38 * mm, doc_width - (38 * mm)],
    )
    question_card.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eff6ff")),
        ("BACKGROUND", (0, 1), (-1, 1), colors.HexColor("#f8fafc")),
        ("GRID", (0, 0), (-1, -1), 0.45, colors.HexColor("#bfdbfe")),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    elements.append(question_card)

    def _render_test_case_table(title: str, rows: list[dict], empty_label: str):
        elements.append(Spacer(1, 3 * mm))
        elements.append(Paragraph(title, styles["CellTextBold"]))
        if not rows:
            elements.append(Paragraph(empty_label, styles["CellText"]))
            return
        table_data = [[
            Paragraph("<b>#</b>", styles["CellTextBold"]),
            Paragraph("<b>Input</b>", styles["CellTextBold"]),
            Paragraph("<b>Expected</b>", styles["CellTextBold"]),
        ]]
        for idx, test in enumerate(rows, start=1):
            if not isinstance(test, dict):
                continue
            table_data.append([
                Paragraph(str(idx), styles["CellText"]),
                Paragraph(escape(_format_value_for_pdf(test.get("input", ""))), styles["CellText"]),
                Paragraph(escape(_format_value_for_pdf(test.get("expected", ""))), styles["CellText"]),
            ])
        idx_col = 12 * mm
        remaining = max(doc_width - idx_col, 90 * mm)
        io_col = remaining / 2.0
        table = Table(table_data, colWidths=[idx_col, io_col, io_col], repeatRows=1)
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), HEADER_BG),
            ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#cbd5e1")),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LEFTPADDING", (0, 0), (-1, -1), 5),
            ("RIGHTPADDING", (0, 0), (-1, -1), 5),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]))
        elements.append(table)

    _render_test_case_table("Sample Test Cases", public_tests, "No sample test cases available in persisted artifacts.")
    _render_test_case_table("Hidden Test Cases", hidden_tests, "No hidden test cases available in persisted artifacts.")

    elements.append(Spacer(1, 3 * mm))
    elements.append(Paragraph("Submitted Code", styles["CellTextBold"]))
    code_para = Paragraph(_code_to_html_block(submitted_code), styles["CellText"])
    code_table = Table([[code_para]], colWidths=[doc_width])
    code_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, 0), colors.HexColor("#0f172a")),
        ("BOX", (0, 0), (0, 0), 0.6, colors.HexColor("#1e40af")),
        ("TOPPADDING", (0, 0), (0, 0), 8),
        ("BOTTOMPADDING", (0, 0), (0, 0), 8),
        ("LEFTPADDING", (0, 0), (0, 0), 8),
        ("RIGHTPADDING", (0, 0), (0, 0), 8),
    ]))
    elements.append(code_table)

    strengths, weaknesses, assessment = _build_coding_skill_analysis(coding_round_data)
    elements.append(Spacer(1, 3 * mm))
    elements.append(Paragraph("Coding Skill Assessment (Deterministic)", styles["CellTextBold"]))
    elements.append(Paragraph(f"&bull; <b>Overall Assessment:</b> {escape(assessment)}", styles["CellText"]))
    for item in strengths:
        elements.append(Paragraph(f"&bull; <b>Strength:</b> {escape(item)}", styles["CellText"]))
    for item in weaknesses:
        elements.append(Paragraph(f"&bull; <b>Weakness:</b> {escape(item)}", styles["CellText"]))


def _render_mcq_round_sections(elements, styles, rounds: dict):
    mcq_keys = [rk for rk in ordered_present_round_keys(rounds) if str(rk).upper() != "L4"]
    if not mcq_keys:
        return

    elements.append(Spacer(1, 5 * mm))
    elements.append(Paragraph("MCQ Round-wise Question Review", styles["SectionHead"]))

    for round_key in mcq_keys:
        round_data = rounds.get(round_key) or {}
        if not isinstance(round_data, dict):
            continue
        submission_details = round_data.get("submission_details") or {}
        responses = submission_details.get("responses", []) if isinstance(submission_details, dict) else []
        if not isinstance(responses, list) or not responses:
            continue

        round_label = str(round_data.get("round_label", round_key) or round_key)
        elements.append(Paragraph(f"<b>{escape(round_label)}</b>", styles["CellTextBold"]))

        score_line = (
            f"Score: {int(round_data.get('correct', 0) or 0)}/{int(round_data.get('total', 0) or 0)} "
            f"({float(round_data.get('percentage', 0) or 0):.2f}%) | "
            f"Threshold: {float(round_data.get('pass_threshold', 0) or 0):.1f}% | "
            f"Status: {escape(str(round_data.get('status', 'Pending') or 'Pending'))}"
        )
        elements.append(Paragraph(score_line, styles["CellText"]))
        elements.append(Spacer(1, 1 * mm))

        table_data = [[
            Paragraph("<b>Q#</b>", styles["CellTextBold"]),
            Paragraph("<b>Question</b>", styles["CellTextBold"]),
            Paragraph("<b>Submitted</b>", styles["CellTextBold"]),
            Paragraph("<b>Correct</b>", styles["CellTextBold"]),
            Paragraph("<b>Result</b>", styles["CellTextBold"]),
        ]]
        row_styles = []
        row_index = 1
        for response in responses:
            if not isinstance(response, dict):
                continue
            question_no = int(response.get("question_no", row_index) or row_index)
            question_text = _normalize_text(response.get("question", "") or "Question text unavailable.")
            submitted = str(response.get("selected_answer", "") or "").strip()
            correct_answer = str(response.get("correct_answer", "") or "").strip()
            is_answered = bool(response.get("is_answered"))
            is_correct = bool(response.get("is_correct"))
            result = "Correct" if is_correct else "Unanswered" if not is_answered else "Incorrect"
            submitted_label = submitted if submitted else "-"
            correct_label = correct_answer if correct_answer else "-"

            table_data.append([
                Paragraph(str(question_no), styles["CellText"]),
                Paragraph(escape(question_text), styles["CellText"]),
                Paragraph(escape(submitted_label), styles["CellText"]),
                Paragraph(escape(correct_label), styles["CellText"]),
                Paragraph(
                    f"<b><font color='{ '#16a34a' if is_correct else '#dc2626' if is_answered else '#6b7280'}'>{result}</font></b>",
                    styles["CellText"],
                ),
            ])

            if is_correct:
                row_styles.append(("TEXTCOLOR", (2, row_index), (2, row_index), PASS_GREEN))
            elif is_answered:
                row_styles.append(("TEXTCOLOR", (2, row_index), (2, row_index), FAIL_RED))
            else:
                row_styles.append(("TEXTCOLOR", (2, row_index), (2, row_index), PENDING_GREY))
            row_index += 1

        review_table = Table(table_data, colWidths=[12 * mm, 76 * mm, 30 * mm, 30 * mm, 18 * mm], repeatRows=1)
        table_styles = [
            ("BACKGROUND", (0, 0), (-1, 0), HEADER_BG),
            ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#cbd5e1")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]
        for idx in range(1, len(table_data)):
            if idx % 2 == 0:
                table_styles.append(("BACKGROUND", (0, idx), (-1, idx), ROW_ALT_BG))
        table_styles.extend(row_styles)
        review_table.setStyle(TableStyle(table_styles))
        elements.append(review_table)

        analysis_text = _build_mcq_round_analysis(round_label, round_data, responses)
        elements.append(Spacer(1, 1 * mm))
        elements.append(Paragraph(f"<b>Round Analysis:</b> {escape(analysis_text)}", styles["CellText"]))
        elements.append(Spacer(1, 3 * mm))


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
    evaluation_service = None
    try:
        from app.services.evaluation_service import EvaluationService as _EvaluationService

        evaluation_service = _EvaluationService
        candidate_data = evaluation_service.enrich_candidate_submission_details(candidate_data)
    except Exception:
        evaluation_service = None

    name = candidate_data["name"]
    email = candidate_data["email"]
    role = candidate_data["role"]
    rounds = candidate_data.get("rounds", {})
    proctoring_summary = candidate_data.get("proctoring_summary") or {}
    plagiarism_summary = candidate_data.get("plagiarism_summary") or {}
    ai_overall_summary = candidate_data.get("ai_overall_summary")
    ai_coding_summary = candidate_data.get("ai_coding_summary")
    coding_round_data = candidate_data.get("coding_round_data")

    if not coding_round_data and evaluation_service is not None:
        try:
            coding_round_data = evaluation_service.get_candidate_coding_round_data(
                email,
                candidate_data=candidate_data,
            )
        except Exception:
            coding_round_data = None

    if not ai_overall_summary:
        try:
            if evaluation_service is not None:
                ai_overall_summary = evaluation_service.generate_candidate_overall_summary(
                    email,
                    candidate_data=candidate_data,
                )
            else:
                raise RuntimeError("Evaluation service unavailable")
        except Exception:
            ai_overall_summary = generate_evaluation_summary(candidate_data)
    if not ai_coding_summary:
        try:
            if evaluation_service is not None:
                ai_coding_summary = evaluation_service.generate_candidate_coding_round_summary(
                    email,
                    candidate_data=candidate_data,
                )
            else:
                raise RuntimeError("Evaluation service unavailable")
        except Exception:
            ai_coding_summary = None
    if ai_coding_summary:
        ai_coding_summary = _strip_submitted_code_block(ai_coding_summary)
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

    summary_row_start = len(table_data)
    summary_rows = _build_score_summary_rows(rounds if isinstance(rounds, dict) else {}, ordered_keys)
    table_data.extend(summary_rows)

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
    for i in range(1, summary_row_start):
        if i % 2 == 0:
            ts_cmds.append(("BACKGROUND", (0, i), (-1, i), ROW_ALT_BG))

    # Colour the Status column
    for i in range(1, summary_row_start):
        status_val = table_data[i][-1]
        ts_cmds.append(("TEXTCOLOR", (-1, i), (-1, i), _status_color(status_val)))
        ts_cmds.append(("FONTNAME", (-1, i), (-1, i), "Helvetica-Bold"))

    if len(summary_rows) >= 1:
        ts_cmds.extend([
            ("BACKGROUND", (0, summary_row_start), (-1, summary_row_start), SOFT_SKILL_ROW_BG),
            ("FONTNAME", (0, summary_row_start), (-1, summary_row_start), "Helvetica-Bold"),
            ("TEXTCOLOR", (-1, summary_row_start), (-1, summary_row_start), AZIRO_BLUE),
        ])
    if len(summary_rows) >= 2:
        overall_row = summary_row_start + 1
        ts_cmds.extend([
            ("BACKGROUND", (0, overall_row), (-1, overall_row), OVERALL_ROW_BG),
            ("FONTNAME", (0, overall_row), (-1, overall_row), "Helvetica-Bold"),
            ("TEXTCOLOR", (-1, overall_row), (-1, overall_row), AZIRO_BLUE),
        ])

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

    if isinstance(coding_round_data, dict):
        _render_coding_details_section(elements, styles, coding_round_data, doc.width)

    if isinstance(rounds, dict):
        _render_mcq_round_sections(elements, styles, rounds)


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
