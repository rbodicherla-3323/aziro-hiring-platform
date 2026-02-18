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
                "rounds": {},
                "results": [],
                "summary": {
                    "total_rounds": len(t.get("tests", {})),
                    "attempted_rounds": 0,
                    "passed_rounds": 0,
                    "failed_rounds": 0,
                },
            })

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
