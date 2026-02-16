import io
import zipfile
from pathlib import Path

from flask import (
    Blueprint, render_template, request, jsonify,
    send_file, abort,
)

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
def reports():
    """Render the reports page with real DB data."""
    search_q = request.args.get("q", "").strip()
    role_filter = request.args.get("role", "").strip()
    db_service = _get_db_service()
    if db_service is None:
        return render_template(
            "reports.html",
            candidates=[],
            roles=[],
            search_q=search_q,
            role_filter=role_filter,
        )

    candidates = db_service.search_candidates(search_q, role_filter)
    roles = db_service.get_all_roles()

    return render_template(
        "reports.html",
        candidates=candidates,
        roles=roles,
        search_q=search_q,
        role_filter=role_filter,
    )


@reports_bp.route("/reports/generate", methods=["POST"])
def generate_report():
    """Generate a PDF report for a single candidate session."""
    db_service = _get_db_service()
    if db_service is None:
        return jsonify({"error": "Database dependencies are unavailable"}), 503
    generate_candidate_pdf, _ = _get_pdf_service()
    if generate_candidate_pdf is None:
        return jsonify({"error": "PDF dependencies are unavailable"}), 503

    ts_id = request.form.get("test_session_id", type=int)
    if not ts_id:
        return jsonify({"error": "Missing test_session_id"}), 400

    # Find the candidate data
    all_candidates = db_service.get_all_candidates_with_results()
    candidate = next(
        (c for c in all_candidates if c["test_session_id"] == ts_id), None
    )
    if not candidate:
        return jsonify({"error": "Candidate session not found"}), 404

    # Generate PDF
    filename = generate_candidate_pdf(candidate)

    # Record in DB
    db_service.save_report(ts_id, filename)

    return jsonify({"status": "ok", "filename": filename})


@reports_bp.route("/reports/generate-bulk", methods=["POST"])
def generate_bulk_reports():
    """Generate PDF reports for multiple candidate sessions."""
    db_service = _get_db_service()
    if db_service is None:
        return jsonify({"error": "Database dependencies are unavailable"}), 503
    generate_candidate_pdf, _ = _get_pdf_service()
    if generate_candidate_pdf is None:
        return jsonify({"error": "PDF dependencies are unavailable"}), 503

    ts_ids = request.form.getlist("test_session_ids[]", type=int)
    if not ts_ids:
        return jsonify({"error": "No candidates selected"}), 400

    all_candidates = db_service.get_all_candidates_with_results()
    generated = []

    for ts_id in ts_ids:
        candidate = next(
            (c for c in all_candidates if c["test_session_id"] == ts_id), None
        )
        if not candidate:
            continue
        filename = generate_candidate_pdf(candidate)
        db_service.save_report(ts_id, filename)
        generated.append({"test_session_id": ts_id, "filename": filename})

    return jsonify({"status": "ok", "generated": generated, "count": len(generated)})


@reports_bp.route("/reports/download/<path:filename>")
def download_report(filename):
    """Serve a generated PDF file for download."""
    _, REPORTS_DIR = _get_pdf_service()
    if REPORTS_DIR is None:
        return jsonify({"error": "PDF dependencies are unavailable"}), 503
    filepath = REPORTS_DIR / filename
    if not filepath.exists():
        abort(404)
    return send_file(
        str(filepath.resolve()),
        as_attachment=True,
        download_name=filename,
        mimetype="application/pdf",
    )


@reports_bp.route("/reports/download-bulk", methods=["POST"])
def download_bulk_reports():
    """Download multiple reports as a single ZIP file."""
    _, REPORTS_DIR = _get_pdf_service()
    if REPORTS_DIR is None:
        return jsonify({"error": "PDF dependencies are unavailable"}), 503
    filenames = request.form.getlist("filenames[]")
    if not filenames:
        return jsonify({"error": "No files specified"}), 400

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for fn in filenames:
            filepath = REPORTS_DIR / fn
            if filepath.exists():
                zf.write(str(filepath.resolve()), fn)

    zip_buffer.seek(0)
    return send_file(
        zip_buffer,
        as_attachment=True,
        download_name="candidate_reports.zip",
        mimetype="application/zip",
    )


@reports_bp.route("/reports/preview/<int:test_session_id>")
def preview_report(test_session_id):
    """Return JSON data for the modal preview."""
    db_service = _get_db_service()
    if db_service is None:
        return jsonify({"error": "Database dependencies are unavailable"}), 503

    all_candidates = db_service.get_all_candidates_with_results()
    candidate = next(
        (c for c in all_candidates if c["test_session_id"] == test_session_id),
        None,
    )
    if not candidate:
        return jsonify({"error": "Not found"}), 404

    return jsonify({
        "name": candidate["name"],
        "email": candidate["email"],
        "role": candidate["role"],
        "batch_id": candidate["batch_id"],
        "rounds": candidate["rounds"],
        "summary": candidate["summary"],
        "has_report": candidate["has_report"],
        "report_filename": candidate["report_filename"],
    })
