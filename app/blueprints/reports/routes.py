# filepath: d:\Projects\aziro-hiring-platform\app\blueprints\reports\routes.py
"""
Reports page — today's session candidates + historical DB search.
"""
import os
from flask import Blueprint, render_template, request, session, jsonify, send_file, abort

from app.utils.auth_decorator import login_required
from app.services.generated_tests_store import get_tests_for_user_today, GENERATED_TESTS
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


@reports_bp.route("/reports")
@login_required
def reports():
    user = session.get("user", {})
    user_email = user.get("email", "dev@aziro.com")

    # Today's session candidates for this user
    user_tests = get_tests_for_user_today(user_email)
    user_emails = {t["email"] for t in user_tests}

    # Get evaluation data for today's session candidates
    all_candidates = EvaluationAggregator.get_candidates()
    session_candidates = [c for c in all_candidates if c["email"] in user_emails]

    # Also add test entries that don't yet have evaluation data
    evaluated_emails = {c["email"] for c in session_candidates}
    for t in user_tests:
        if t["email"] not in evaluated_emails:
            session_candidates.append({
                "name": t["name"],
                "email": t["email"],
                "role": t.get("role", ""),
                "role_key": t.get("role_key", ""),
                "batch_id": t.get("batch_id", ""),
                "rounds": {},
                "results": [],
                "summary": {
                    "total_rounds": len(t.get("tests", {})),
                    "attempted_rounds": 0,
                    "passed_rounds": 0,
                    "failed_rounds": 0,
                },
            })

    summaries_by_email = build_proctoring_summary_by_email({c.get("email", "") for c in session_candidates})
    plagiarism_by_email = build_plagiarism_summary_by_candidates(session_candidates)
    for candidate in session_candidates:
        email_key = str(candidate.get("email", "")).strip().lower()
        candidate["proctoring_summary"] = summaries_by_email.get(email_key, blank_proctoring_summary())
        candidate["plagiarism_summary"] = plagiarism_by_email.get(email_key, blank_plagiarism_summary())    # Also pull DB-stored candidates (historical)
    db_candidates = []
    try:
        q = request.args.get("q", "").strip()
        if q:
            # search_candidates returns flat dicts; resolve to full report data
            search_hits = db_service.search_candidates(q)
            seen = set()
            for hit in search_hits:
                email = hit.get("email", "")
                if email not in seen:
                    full = db_service.get_candidate_report_data(email)
                    if full:
                        db_candidates.append(full)
                    seen.add(email)
        else:
            db_candidates = db_service.get_all_candidates_with_results()
    except Exception:
        pass

    # Merge: DB candidates that aren't already in session_candidates
    session_emails = {c.get("email", "") for c in session_candidates}
    for dc in db_candidates:
        if dc.get("email", "") not in session_emails:
            dc.setdefault("proctoring_summary", blank_proctoring_summary())
            dc.setdefault("plagiarism_summary", blank_plagiarism_summary())
            session_candidates.append(dc)
            session_emails.add(dc.get("email", ""))
    return render_template(
        "reports.html",
        session_candidates=session_candidates,
    )


@reports_bp.route("/reports/search")
@login_required
def search_reports():
    query = request.args.get("q", "").strip()
    if len(query) < 2:
        return jsonify({"candidates": []})

    results = []
    query_lower = query.lower()

    # 1. Search in-memory generated tests (via EvaluationAggregator)
    all_candidates = EvaluationAggregator.get_candidates()
    for c in all_candidates:
        if (query_lower in c.get("name", "").lower()
                or query_lower in c.get("email", "").lower()
                or query_lower in c.get("role", "").lower()):
            results.append({
                "name": c["name"],
                "email": c["email"],
                "role": c.get("role", "N/A"),
                "source": "session",
            })

    # Also search GENERATED_TESTS that may not have evaluation data yet
    found_emails = {r["email"] for r in results}
    for t in GENERATED_TESTS:
        if t["email"] not in found_emails:
            if (query_lower in t.get("name", "").lower()
                    or query_lower in t.get("email", "").lower()
                    or query_lower in t.get("role", "").lower()):
                results.append({
                    "name": t["name"],
                    "email": t["email"],
                    "role": t.get("role", "N/A"),
                    "source": "session",
                })
                found_emails.add(t["email"])

    # 2. Search DB (historical)
    try:
        db_results = db_service.search_candidates(query)
        for r in db_results:
            if r["email"] not in found_emails:
                results.append({
                    "name": r["name"],
                    "email": r["email"],
                    "role": r.get("role", "N/A"),
                    "created_at": r.get("created_at", ""),
                    "source": "database",
                })
                found_emails.add(r["email"])
    except Exception:
        pass

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
        filename = generate_candidate_pdf(candidate_data)

        # Save report record to DB
        user = session.get("user", {})
        try:
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


@reports_bp.route("/reports/preview/<int:test_session_id>")
@login_required
def preview_report(test_session_id):
    """Return JSON preview data for a candidate by test_session_id."""
    from app.models import TestSession, Candidate
    ts = TestSession.query.get(test_session_id)
    if not ts:
        return jsonify({"error": "Test session not found"}), 404
    candidate = Candidate.query.get(ts.candidate_id)
    if not candidate:
        return jsonify({"error": "Candidate not found"}), 404

    data = db_service.get_candidate_report_data(candidate.email)
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
    """Generate a PDF report for a candidate by test_session_id (POST)."""
    from app.models import TestSession, Candidate
    test_session_id = request.form.get("test_session_id")
    if not test_session_id and request.is_json:
        test_session_id = request.json.get("test_session_id")
    if not test_session_id:
        return jsonify({"status": "error", "error": "test_session_id required"}), 400

    ts = TestSession.query.get(int(test_session_id))
    if not ts:
        return jsonify({"status": "error", "error": "Test session not found"}), 404
    candidate = Candidate.query.get(ts.candidate_id)
    if not candidate:
        return jsonify({"status": "error", "error": "Candidate not found"}), 404

    candidate_data = db_service.get_candidate_report_data(candidate.email)
    if not candidate_data:
        return jsonify({"status": "error", "error": "No data for candidate"}), 404

    # Attach proctoring + plagiarism summaries
    email = candidate.email
    proctoring_by_email = build_proctoring_summary_by_email({email})
    candidate_data["proctoring_summary"] = proctoring_by_email.get(email.strip().lower(), blank_proctoring_summary())
    plagiarism_by_email = build_plagiarism_summary_by_candidates([candidate_data])
    candidate_data["plagiarism_summary"] = plagiarism_by_email.get(email.strip().lower(), blank_plagiarism_summary())

    try:
        filename = generate_candidate_pdf(candidate_data)
        user = session.get("user", {})
        try:
            db_service.save_report(int(test_session_id), filename, user.get("email", ""))
        except Exception:
            pass
        return jsonify({"status": "ok", "filename": filename})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@reports_bp.route("/reports/download-by-id/<int:report_id>")
@login_required
def download_report_by_id(report_id):
    """Download a previously generated report by DB id."""
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
