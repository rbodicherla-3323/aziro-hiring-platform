# filepath: d:\Projects\aziro-hiring-platform\app\blueprints\tests\routes.py
"""
Generated Tests listing — scoped to current user's today session.
Also provides API endpoints for resume/JD extraction (from nikitha_local).
"""
import os

from flask import render_template, session, request, jsonify, current_app
from werkzeug.utils import secure_filename
from datetime import datetime

from . import tests_bp
from app.utils.auth_decorator import login_required
from app.utils.role_normalizer import ROLE_NAME_TO_KEY
from app.services.generated_tests_store import get_tests_for_user_today
from app.services.email_service import send_candidate_test_links_email
from app.services.document_intelligence import (
    allowed_file_extension,
    extract_text_from_file,
    extract_resume_identity,
    match_role_from_jd,
    get_mime_type_for_filename,
)


# ────────────────────────────────────────────
# Resume / JD Upload Helpers
# ────────────────────────────────────────────
UPLOAD_FOLDER = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "uploads"
)
ALLOWED_EXTENSIONS = {"pdf", "doc", "docx", "txt"}


def allowed_file(filename):
    return bool(filename and allowed_file_extension(filename))


def save_uploaded_file(file, candidate_name, file_type):
    """Save uploaded file and return the file path."""
    if not file or file.filename == "":
        return None
    if not allowed_file(file.filename):
        return None

    os.makedirs(UPLOAD_FOLDER, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    sanitized_name = secure_filename(candidate_name.replace(" ", "_"))
    original_ext = secure_filename(file.filename).rsplit(".", 1)[1].lower()
    filename = f"{sanitized_name}_{file_type}_{timestamp}.{original_ext}"

    filepath = os.path.join(UPLOAD_FOLDER, filename)
    file.save(filepath)
    return filepath


# ────────────────────────────────────────────
# API Endpoints — Resume & JD Extraction
# ────────────────────────────────────────────
@tests_bp.route("/api/extract-resume", methods=["POST"])
def extract_resume():
    """API endpoint to extract email and name from resume file."""
    if "resume" not in request.files:
        return jsonify({"error": "No file provided"}), 400

    file = request.files["resume"]
    if file.filename == "":
        return jsonify({"error": "No file selected"}), 400
    if not allowed_file(file.filename):
        return jsonify({"error": "File type not allowed"}), 400

    file_bytes = file.read()
    if not file_bytes:
        return jsonify({"error": "Uploaded file is empty"}), 400

    try:
        extraction = extract_text_from_file(file.filename, file_bytes)
        if extraction.get("error"):
            return jsonify({"error": extraction["error"]}), 400

        parsed = extract_resume_identity(
            extraction.get("text", ""),
            file.filename,
            use_ai_fallback=True,
            source_file_bytes=file_bytes,
            source_mime_type=get_mime_type_for_filename(file.filename),
            text_quality=extraction.get("text_quality", 0.0),
        )
        warnings = []
        warnings.extend(extraction.get("warnings", []))
        warnings.extend(parsed.get("warnings", []))

        response = {
            "name": parsed.get("name"),
            "email": parsed.get("email"),
            "name_found": parsed.get("name_found", False),
            "email_found": parsed.get("email_found", False),
            "messages": parsed.get("messages", {}),
            "confidence": parsed.get("confidence", {}),
            "warnings": warnings,
            "used_ai": parsed.get("used_ai", False),
            "file_type": extraction.get("file_type"),
            "extraction_method": extraction.get("extraction_method"),
            "text_length": extraction.get("text_length", 0),
            "text_quality": extraction.get("text_quality", 0.0),
        }
        if response["text_length"] == 0 or float(response.get("text_quality", 0.0) or 0.0) < 0.14:
            warnings_joined = " | ".join((response.get("warnings") or [])).lower()
            if "image-only" in warnings_joined or "image-heavy" in warnings_joined:
                unreadable_msg = "Resume PDF appears image-based. Upload a machine-readable PDF or fill details manually."
            else:
                unreadable_msg = "Unable to read resume text from this file. Upload a machine-readable PDF or fill details manually."
            messages = dict(response.get("messages") or {})
            if not response.get("name_found"):
                messages["name"] = unreadable_msg
            if not response.get("email_found"):
                messages["email"] = unreadable_msg
            response["messages"] = messages
        return jsonify(response), 200
    except Exception as exc:
        current_app.logger.exception("Resume extraction endpoint failed: %s", exc)
        fallback_msg = "Unable to process resume right now. Please fill details manually."
        return jsonify({
            "name": None,
            "email": None,
            "name_found": False,
            "email_found": False,
            "messages": {
                "name": fallback_msg,
                "email": fallback_msg,
            },
            "confidence": {"name": 0.0, "email": 0.0, "overall": 0.0},
            "warnings": [str(exc)],
            "used_ai": False,
            "file_type": "unknown",
            "extraction_method": "internal_error",
            "text_length": 0,
            "text_quality": 0.0,
        }), 200


@tests_bp.route("/api/extract-jd-role", methods=["POST"])
def extract_jd_role_endpoint():
    """API endpoint to extract and match role from JD file."""
    if "jd" not in request.files:
        return jsonify({"error": "No file provided"}), 400

    file = request.files["jd"]
    if file.filename == "":
        return jsonify({"error": "No file selected"}), 400
    if not allowed_file(file.filename):
        return jsonify({"error": "File type not allowed"}), 400

    file_bytes = file.read()
    if not file_bytes:
        return jsonify({"error": "Uploaded file is empty"}), 400

    try:
        extraction = extract_text_from_file(file.filename, file_bytes)
        if extraction.get("error"):
            return jsonify({"error": extraction["error"]}), 400

        matched = match_role_from_jd(
            extraction.get("text", ""),
            list(ROLE_NAME_TO_KEY.keys()),
            use_ai_fallback=True,
            source_file_bytes=file_bytes,
            source_mime_type=get_mime_type_for_filename(file.filename),
            text_quality=extraction.get("text_quality", 0.0),
            source_filename=file.filename,
        )

        warnings = []
        warnings.extend(extraction.get("warnings", []))
        warnings.extend(matched.get("warnings", []))

        response = {
            "role": matched.get("role"),
            "role_found": matched.get("role_found", False),
            "message": matched.get("message", ""),
            "confidence": matched.get("confidence", {}),
            "top_matches": matched.get("top_matches", []),
            "warnings": warnings,
            "used_ai": matched.get("used_ai", False),
            "file_type": extraction.get("file_type"),
            "extraction_method": extraction.get("extraction_method"),
            "text_length": extraction.get("text_length", 0),
            "text_quality": extraction.get("text_quality", 0.0),
        }
        if (
            (response["text_length"] == 0 or float(response.get("text_quality", 0.0) or 0.0) < 0.14)
            and not response.get("role_found")
        ):
            warnings_joined = " | ".join((response.get("warnings") or [])).lower()
            if "image-only" in warnings_joined or "image-heavy" in warnings_joined:
                response["message"] = "JD PDF appears image-based. Upload a machine-readable PDF or select role manually."
            else:
                response["message"] = "Unable to read JD text from this file. Upload a machine-readable PDF or select role manually."
        return jsonify(response), 200
    except Exception as exc:
        current_app.logger.exception("JD extraction endpoint failed: %s", exc)
        return jsonify({
            "role": None,
            "role_found": False,
            "message": "Unable to process JD right now. Please select role manually.",
            "confidence": {"score": 0, "normalized": 0.0, "margin": 0.0},
            "top_matches": [],
            "warnings": [str(exc)],
            "used_ai": False,
            "file_type": "unknown",
            "extraction_method": "internal_error",
            "text_length": 0,
            "text_quality": 0.0,
        }), 200


# ────────────────────────────────────────────
# Generated Tests — scoped to current user
# ────────────────────────────────────────────
@tests_bp.route("/generated-tests")
@login_required
def generated_tests():
    user = session.get("user", {})
    user_email = user.get("email", "dev@aziro.com")

    candidates = get_tests_for_user_today(user_email)

    return render_template(
        "generated_tests.html",
        candidates=candidates,
    )


@tests_bp.route("/generated-tests/send-emails", methods=["POST"])
@login_required
def send_generated_tests_emails():
    """Send generated test links to selected candidates for current logged-in user."""
    payload = request.get_json(silent=True) or {}
    raw_emails = payload.get("emails", [])

    if not isinstance(raw_emails, list):
        return jsonify({"success": False, "error": "Invalid email selection payload."}), 400

    selected_emails = []
    seen = set()
    for item in raw_emails:
        email = str(item or "").strip().lower()
        if not email or email in seen:
            continue
        selected_emails.append(email)
        seen.add(email)

    if not selected_emails:
        return jsonify({"success": False, "error": "No candidates selected."}), 400

    user = session.get("user", {})
    user_email = user.get("email", "dev@aziro.com")
    candidates = get_tests_for_user_today(user_email)
    candidates_by_email = {
        str(c.get("email", "")).strip().lower(): c
        for c in candidates
        if c.get("email")
    }

    sent_count = 0
    failures = []

    for email in selected_emails:
        candidate = candidates_by_email.get(email)
        if not candidate:
            failures.append({"email": email, "reason": "Candidate not found for this session."})
            continue

        sent, error = send_candidate_test_links_email(
            candidate_name=candidate.get("name", "Candidate"),
            candidate_email=candidate.get("email", email),
            role_label=candidate.get("role", ""),
            tests=candidate.get("tests", {}),
        )
        if sent:
            sent_count += 1
        else:
            failures.append({
                "email": candidate.get("email", email),
                "reason": error or "SMTP send failed.",
            })

    return jsonify({
        "success": True,
        "requested_count": len(selected_emails),
        "sent_count": sent_count,
        "failed_count": len(failures),
        "failures": failures,
    })
