# filepath: d:\Projects\aziro-hiring-platform\app\blueprints\reports\routes.py
"""
Reports page — recent session candidates + historical report search.
"""
from datetime import datetime, timezone, timedelta
from io import BytesIO
from flask import Blueprint, render_template, request, session, jsonify, send_file, abort

from app.utils.auth_decorator import login_required
from app.services.generated_tests_store import get_tests_for_user_in_range, SESSION_RETENTION_DAYS
from app.services.evaluation_aggregator import EvaluationAggregator
from app.services import db_service
from app.services.evaluation_service import EvaluationService
from app.services.proctoring_summary import build_proctoring_summary_by_email, blank_proctoring_summary
from app.services.plagiarism_service import (
    build_plagiarism_summary_by_candidates,
    blank_plagiarism_summary,
)
from app.services.pdf_service import generate_candidate_pdf, REPORTS_DIR

reports_bp = Blueprint("reports", __name__)


def _get_db_service():
    try:
        from app.services import db_service
        return db_service
    except Exception:
        return None


def _get_pdf_service():
    try:
        from app.services.pdf_service import generate_candidate_pdf, REPORTS_DIR
        return generate_candidate_pdf, REPORTS_DIR
    except Exception:
        return None, None


@reports_bp.route("/reports")
@login_required
def reports():
    user = session.get("user", {})
    user_email = user.get("email", "dev@aziro.com")
    q = request.args.get("q", "").strip()

    # Recent session candidates for this user (retention window)
    since = datetime.now(timezone.utc) - timedelta(days=SESSION_RETENTION_DAYS)
    user_tests = get_tests_for_user_in_range(user_email, since)

    def _parse_created_at(value):
        if isinstance(value, datetime):
            dt = value
        elif isinstance(value, str):
            try:
                dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except (ValueError, TypeError):
                return None
        else:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt

    def _created_sort_key(item):
        dt = _parse_created_at(item.get("created_at", ""))
        return dt or datetime.min.replace(tzinfo=timezone.utc)

    user_tests_sorted = sorted(user_tests, key=_created_sort_key, reverse=True)
    tests_by_email = {}
    for t in user_tests_sorted:
        email_key = str(t.get("email", "")).strip().lower()
        if not email_key:
            continue
        if email_key not in tests_by_email:
            tests_by_email[email_key] = t
    user_emails = set(tests_by_email.keys())

    # Get evaluation data for recent session candidates
    all_candidates = EvaluationAggregator.get_candidates()
    session_candidates = []
    for c in all_candidates:
        email_key = str(c.get("email", "")).strip().lower()
        if email_key in user_emails:
            c["created_at"] = tests_by_email[email_key].get("created_at", "")
            session_candidates.append(c)

    # Also add test entries that don't yet have evaluation data
    evaluated_emails = {str(c.get("email", "")).strip().lower() for c in session_candidates}
    for t in user_tests_sorted:
        email_key = str(t.get("email", "")).strip().lower()
        if not email_key or email_key in evaluated_emails:
            continue
        session_candidates.append({
            "name": t["name"],
            "email": t["email"],
            "role": t.get("role", ""),
            "role_key": t.get("role_key", ""),
            "batch_id": t.get("batch_id", ""),
            "created_at": t.get("created_at", ""),
            "rounds": {},
            "results": [],
            "summary": {
                "total_rounds": len(t.get("tests", {})),
                "attempted_rounds": 0,
                "passed_rounds": 0,
                "failed_rounds": 0,
            },
        })
        evaluated_emails.add(email_key)

    session_candidates.sort(key=_created_sort_key, reverse=True)

    def _attach_report_info(candidate):
        email_key = str(candidate.get("email", "")).strip().lower()
        if not email_key:
            candidate["has_report"] = False
            candidate["report_filename"] = ""
            candidate["report_id"] = None
            return
        info = db_service.get_latest_report_for_email(email_key)
        candidate["has_report"] = bool(info)
        candidate["report_filename"] = info.get("filename") if info else ""
        candidate["report_id"] = info.get("id") if info else None

    for cand in session_candidates:
        _attach_report_info(cand)

    # Apply search filter if q= is present
    if q:
        q_lower = q.lower()
        session_candidates = [
            c for c in session_candidates
            if q_lower in c.get("name", "").lower()
            or q_lower in c.get("email", "").lower()
            or q_lower in c.get("role", "").lower()
        ]

    summaries_by_email = build_proctoring_summary_by_email({c.get("email", "") for c in session_candidates})
    plagiarism_by_email = build_plagiarism_summary_by_candidates(session_candidates)
    for candidate in session_candidates:
        email_key = str(candidate.get("email", "")).strip().lower()
        candidate["proctoring_summary"] = summaries_by_email.get(email_key, blank_proctoring_summary())
        candidate["plagiarism_summary"] = plagiarism_by_email.get(email_key, blank_plagiarism_summary())

    return render_template(
        "reports.html",
        session_candidates=session_candidates,
        recent_days=SESSION_RETENTION_DAYS,
    )


@reports_bp.route("/reports/search")
@login_required
def search_reports():
    user = session.get("user", {})
    user_email = user.get("email", "dev@aziro.com")
    query = request.args.get("q", "").strip()
    if len(query) < 2:
        return jsonify({"candidates": []})

    results = []
    query_lower = query.lower()

    found_emails = set()

    # 1. Search DB (reports generated for any candidate - org-wide)
    try:
        db_results = db_service.search_candidates_with_reports(query)
        for r in db_results:
            email_key = str(r.get("email", "")).strip().lower()
            if email_key and email_key not in found_emails:
                results.append({
                    "name": r.get("name", ""),
                    "email": r.get("email", ""),
                    "role": r.get("role", "N/A"),
                    "created_at": r.get("created_at", ""),
                    "source": "database",
                    "has_report": True,
                    "report_filename": r.get("report_filename", ""),
                })
                found_emails.add(email_key)
    except Exception:
        pass

    # 2. Search this user's recent candidates (fallback)
    since = datetime.now(timezone.utc) - timedelta(days=SESSION_RETENTION_DAYS)
    user_tests = get_tests_for_user_in_range(user_email, since)
    for t in user_tests:
        if (query_lower in t.get("name", "").lower()
                or query_lower in t.get("email", "").lower()
                or query_lower in t.get("role", "").lower()):
            email_key = str(t.get("email", "")).strip().lower()
            if email_key and email_key not in found_emails:
                info = db_service.get_latest_report_for_email(email_key)
                results.append({
                    "name": t.get("name", ""),
                    "email": t.get("email", ""),
                    "role": t.get("role", "N/A"),
                    "source": "session",
                    "has_report": bool(info),
                    "report_filename": info.get("filename") if info else "",
                })
                found_emails.add(email_key)

    return jsonify({"candidates": results})


@reports_bp.route("/reports/generate/<path:email>")
@login_required
def generate_report(email):
    """Generate a PDF report for a candidate and return JSON with action URLs."""
    # First try from evaluation aggregator (in-memory data)
    all_candidates = EvaluationAggregator.get_candidates()
    candidate_data = None
    for c in all_candidates:
        if c["email"] == email:
            candidate_data = c
            break

    # Fallback to DB
    if not candidate_data:
        candidate_data = db_service.get_candidate_report_data(email)

    if not candidate_data:
        return jsonify({"success": False, "error": f"No data found for candidate: {email}"}), 404

    proctoring_by_email = build_proctoring_summary_by_email({email})
    candidate_data["proctoring_summary"] = proctoring_by_email.get(email.strip().lower(), blank_proctoring_summary())
    plagiarism_by_email = build_plagiarism_summary_by_candidates([candidate_data])
    candidate_data["plagiarism_summary"] = plagiarism_by_email.get(email.strip().lower(), blank_plagiarism_summary())

    # Attach AI summaries for PDF rendering.
    try:
        candidate_data["ai_overall_summary"] = EvaluationService.generate_candidate_overall_summary(email)
    except Exception:
        candidate_data["ai_overall_summary"] = None

    try:
        candidate_data["ai_coding_summary"] = EvaluationService.generate_candidate_coding_round_summary(email)
    except Exception:
        candidate_data["ai_coding_summary"] = None
    try:
        candidate_data["coding_round_data"] = EvaluationService.get_candidate_coding_round_data(email)
    except Exception:
        candidate_data["coding_round_data"] = None

    # Generate PDF
    try:
        user = session.get("user", {})
        ts = None
        try:
            ts = db_service.ensure_candidate_session_for_report(candidate_data, user.get("email", ""))
        except Exception:
            ts = None

        filename = generate_candidate_pdf(candidate_data)

        # Save report record to DB
        try:
            if ts and getattr(ts, "id", None):
                db_service.save_report(ts.id, filename, user.get("email", ""))
            else:
                db_service.save_report(email, filename, user.get("email", ""))
        except Exception:
            pass

        return jsonify({
            "success": True,
            "filename": filename,
            "candidate": candidate_data.get("name", email),
            "view_url": f"/reports/view/{filename}",
            "download_url": f"/reports/download-file/{filename}",
        })
    except Exception as e:
        return jsonify({"success": False, "error": f"Failed to generate report: {str(e)}"}), 500


@reports_bp.route("/reports/proctoring/screenshots")
@login_required
def list_proctoring_screenshots():
    email = request.args.get("email", "").strip()
    if not email:
        return jsonify({"screenshots": [], "error": "email required"}), 400

    try:
        limit_raw = request.args.get("limit", "200")
        limit = max(1, min(int(limit_raw), 500))
    except (TypeError, ValueError):
        limit = 200

    records = db_service.get_proctoring_screenshots_by_email(email, limit=limit)
    screenshots = []
    for rec in records:
        captured = rec.captured_at.isoformat() if rec.captured_at else ""
        screenshots.append({
            "id": rec.id,
            "captured_at": captured,
            "round_key": rec.round_key,
            "round_label": rec.round_label,
            "source": rec.source,
            "event_type": rec.event_type,
        })

    return jsonify({"screenshots": screenshots})


@reports_bp.route("/reports/proctoring/screenshot/<int:screenshot_id>")
@login_required
def get_proctoring_screenshot(screenshot_id):
    rec = db_service.get_proctoring_screenshot_by_id(screenshot_id)
    if not rec or not rec.image_bytes:
        abort(404, description="Screenshot not found")

    filename = f"proctoring_{rec.id}.png"
    return send_file(
        BytesIO(rec.image_bytes),
        mimetype=rec.mime_type or "image/png",
        download_name=filename,
        as_attachment=False,
    )


@reports_bp.route("/reports/view/<path:filename>")
@login_required
def view_report(filename):
    """View a PDF report inline in the browser."""
    filepath = REPORTS_DIR / filename
    if not filepath.exists():
        abort(404, description="Report file not found")

    return send_file(
        str(filepath),
        as_attachment=False,
        download_name=filename,
        mimetype="application/pdf",
    )


@reports_bp.route("/reports/download-file/<path:filename>")
@login_required
def download_report_file(filename):
    """Download a PDF report as attachment."""
    filepath = REPORTS_DIR / filename
    if not filepath.exists():
        abort(404, description="Report file not found")

    return send_file(
        str(filepath),
        as_attachment=True,
        download_name=filename,
        mimetype="application/pdf",
    )


@reports_bp.route("/reports/download/<int:report_id>")
@login_required
def download_report(report_id):
    """Download a previously generated report."""
    report = db_service.get_report_by_id(report_id)
    if not report:
        abort(404, description="Report not found")

    filepath = REPORTS_DIR / report.filename
    if not filepath.exists():
        abort(404, description="Report file not found on disk")

    return send_file(
        str(filepath),
        as_attachment=True,
        download_name=report.filename,
        mimetype="application/pdf",
    )


@reports_bp.route("/reports/preview/<int:test_session_id>")
@login_required
def preview_report(test_session_id):
    """Return candidate report data as JSON for preview."""
    from app.models import TestSession as TS, Candidate as C
    ts = TS.query.get(test_session_id)
    if not ts:
        return jsonify({"error": "Test session not found"}), 404
    cand = C.query.get(ts.candidate_id)
    if not cand:
        return jsonify({"error": "Candidate not found"}), 404

    data = db_service.get_candidate_report_data(cand.email)
    if not data:
        return jsonify({"error": "No report data available"}), 404

    return jsonify(data)


@reports_bp.route("/reports/download/<path:filename>")
@login_required
def download_report_by_filename(filename):
    """Download a PDF report by filename."""
    filepath = REPORTS_DIR / filename
    if not filepath.exists():
        abort(404, description="Report file not found")

    return send_file(
        str(filepath),
        as_attachment=True,
        download_name=filename,
        mimetype="application/pdf",
    )


@reports_bp.route("/reports/generate", methods=["POST"])
@login_required
def generate_report_by_session():
    """Generate a PDF report for a candidate given test_session_id (form/JSON)."""
    test_session_id = request.form.get("test_session_id") or (
        request.get_json(silent=True) or {}
    ).get("test_session_id")

    if not test_session_id:
        return jsonify({"status": "error", "error": "test_session_id required"}), 400

    test_session_id = int(test_session_id)
    from app.models import TestSession as TS, Candidate as C
    ts = TS.query.get(test_session_id)
    if not ts:
        return jsonify({"status": "error", "error": "Test session not found"}), 404
    cand = C.query.get(ts.candidate_id)
    if not cand:
        return jsonify({"status": "error", "error": "Candidate not found"}), 404

    candidate_data = db_service.get_candidate_report_data(cand.email)
    if not candidate_data:
        return jsonify({"status": "error", "error": "No data for candidate"}), 404

    try:
        pdf_filename = generate_candidate_pdf(candidate_data)
        user = session.get("user", {})
        db_service.save_report(test_session_id, pdf_filename, user.get("email", ""))
        return jsonify({"status": "ok", "filename": pdf_filename})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


