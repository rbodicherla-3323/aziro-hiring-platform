# filepath: d:\Projects\aziro-hiring-platform\app\blueprints\tests\routes.py
"""
Generated Tests listing — scoped to current user's today session.
Also provides API endpoints for resume/JD extraction (from nikitha_local).
"""
import os
import csv
import io
import re
import zipfile
import posixpath
import xml.etree.ElementTree as ET

from flask import render_template, session, request, jsonify, current_app
from werkzeug.utils import secure_filename
from datetime import datetime

from . import tests_bp
from app.utils.auth_decorator import login_required
from app.utils.role_normalizer import ROLE_NAME_TO_KEY
from app.services.generated_tests_store import (
    GENERATED_TESTS_PRESENT_SESSION_KEY,
    get_tests_for_user_today,
    delete_generated_tests_for_user,
)
from app.services.email_service import send_candidate_test_links_email
from app.services.user_token_store import (
    get_valid_graph_delegated_token,
    get_valid_graph_delegated_token_from_session,
)
from app.services.document_intelligence import (
    allowed_file_extension,
    extract_text_from_file,
    extract_resume_identity,
    match_role_from_jd,
    get_mime_type_for_filename,
)
from app.utils.round_order import INTERNAL_ROUND_ORDER
from app.utils.email_validator import normalize_email, validate_email


# --------------------------------------------
# Resume / JD Upload Helpers
# --------------------------------------------
UPLOAD_FOLDER = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "uploads"
)
ALLOWED_EXTENSIONS = {"pdf", "doc", "docx", "txt"}
ALLOWED_BULK_IMPORT_EXTENSIONS = {"xlsx", "csv"}
MAX_BULK_IMPORT_ROWS = 200


def allowed_file(filename):
    return bool(filename and allowed_file_extension(filename))


def _normalize_header(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").strip().lower())


def _extract_extension(filename: str) -> str:
    safe = str(filename or "").strip().lower()
    if "." not in safe:
        return ""
    return safe.rsplit(".", 1)[1]


def _extract_csv_rows(file_bytes: bytes) -> list[list[str]]:
    text = file_bytes.decode("utf-8-sig", errors="replace")
    reader = csv.reader(io.StringIO(text))
    return [list(row) for row in reader]


def _xlsx_col_to_index(cell_ref: str) -> int:
    letters = "".join(ch for ch in str(cell_ref or "") if ch.isalpha()).upper()
    if not letters:
        return -1
    idx = 0
    for char in letters:
        idx = (idx * 26) + (ord(char) - ord("A") + 1)
    return idx - 1


def _extract_xlsx_rows(file_bytes: bytes) -> list[list[str]]:
    ns_main = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    ns_doc = {
        "m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
        "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    }
    ns_rel = {"r": "http://schemas.openxmlformats.org/package/2006/relationships"}

    with zipfile.ZipFile(io.BytesIO(file_bytes)) as archive:
        shared_strings: list[str] = []
        if "xl/sharedStrings.xml" in archive.namelist():
            root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
            for node in root.findall("m:si", ns_main):
                parts = [text_node.text or "" for text_node in node.findall(".//m:t", ns_main)]
                shared_strings.append("".join(parts))

        workbook_root = ET.fromstring(archive.read("xl/workbook.xml"))
        first_sheet = workbook_root.find("m:sheets/m:sheet", ns_doc)
        if first_sheet is None:
            return []

        rel_id = str(first_sheet.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id") or "").strip()
        if not rel_id:
            return []

        rels_root = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        target = ""
        for rel in rels_root.findall("r:Relationship", ns_rel):
            if str(rel.get("Id") or "").strip() == rel_id:
                target = str(rel.get("Target") or "").strip()
                break
        if not target:
            return []

        normalized_target = posixpath.normpath(str(target or "").replace("\\", "/").lstrip("/"))
        if normalized_target.startswith("xl/"):
            sheet_path = normalized_target
        else:
            sheet_path = f"xl/{normalized_target}"
        if sheet_path not in archive.namelist():
            return []

        sheet_root = ET.fromstring(archive.read(sheet_path))
        rows: list[list[str]] = []

        for row_node in sheet_root.findall(".//m:sheetData/m:row", ns_main):
            values_by_col: dict[int, str] = {}
            max_col = -1
            for cell in row_node.findall("m:c", ns_main):
                col_idx = _xlsx_col_to_index(cell.get("r", ""))
                if col_idx < 0:
                    continue

                cell_type = str(cell.get("t") or "").strip()
                value = ""
                if cell_type == "inlineStr":
                    inline_parts = [node.text or "" for node in cell.findall(".//m:is/m:t", ns_main)]
                    value = "".join(inline_parts)
                else:
                    raw_value = cell.find("m:v", ns_main)
                    raw_text = (raw_value.text or "") if raw_value is not None else ""
                    if cell_type == "s":
                        try:
                            value = shared_strings[int(raw_text)]
                        except Exception:
                            value = raw_text
                    else:
                        value = raw_text

                values_by_col[col_idx] = str(value).strip()
                if col_idx > max_col:
                    max_col = col_idx

            if max_col < 0:
                rows.append([])
                continue

            row_values = ["" for _ in range(max_col + 1)]
            for col_idx, value in values_by_col.items():
                row_values[col_idx] = value
            rows.append(row_values)

    return rows


def _extract_bulk_candidates(rows: list[list[str]]) -> tuple[list[dict], list[str], list[str]]:
    if not rows:
        return [], ["The uploaded file is empty."], []

    headers = [str(item or "").strip() for item in (rows[0] or [])]
    header_map = {_normalize_header(value): idx for idx, value in enumerate(headers) if str(value or "").strip()}

    aliases = {
        "name": {"name", "fullname", "candidatename", "username"},
        "email": {"email", "emailid", "emailaddress", "candidateemail"},
        "role": {"role", "position", "jobrole", "candidaterole"},
        "domain": {"domain", "specialization", "practice"},
    }

    index_name = next((header_map.get(alias) for alias in aliases["name"] if alias in header_map), None)
    index_email = next((header_map.get(alias) for alias in aliases["email"] if alias in header_map), None)
    index_role = next((header_map.get(alias) for alias in aliases["role"] if alias in header_map), None)
    index_domain = next((header_map.get(alias) for alias in aliases["domain"] if alias in header_map), None)

    missing = []
    if index_name is None:
        missing.append("name")
    if index_email is None:
        missing.append("email")
    if index_role is None:
        missing.append("role")
    if missing:
        return [], [f"Missing required column(s): {', '.join(missing)}"], []

    candidates: list[dict] = []
    errors: list[str] = []
    warnings: list[str] = []

    for row_num, row in enumerate(rows[1:], start=2):
        def _get(index: int | None) -> str:
            if index is None or index < 0 or index >= len(row):
                return ""
            return str(row[index] or "").strip()

        name = _get(index_name)
        email = _get(index_email).lower()
        role = _get(index_role)
        domain = _get(index_domain) or "None"

        if not any([name, email, role, domain]):
            continue

        row_errors = []
        if not name:
            row_errors.append("name is empty")
        if not email:
            row_errors.append("email is empty")
        elif "@" not in email or "." not in email.split("@")[-1]:
            row_errors.append("email format is invalid")
        if not role:
            row_errors.append("role is empty")

        if row_errors:
            errors.append(f"Row {row_num}: {', '.join(row_errors)}")
            continue

        candidates.append({
            "name": name,
            "email": email,
            "role": role,
            "domain": domain,
            "row_number": row_num,
        })

        if len(candidates) >= MAX_BULK_IMPORT_ROWS:
            warnings.append(f"Only first {MAX_BULK_IMPORT_ROWS} valid rows were imported.")
            break

    if not candidates and not errors:
        errors.append("No candidate rows were found after the header.")

    return candidates, errors, warnings



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


# --------------------------------------------
# API Endpoints — Resume & JD Extraction
# --------------------------------------------
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


@tests_bp.route("/api/import-candidates", methods=["POST"])
@login_required
def import_candidates_endpoint():
    """Parse bulk candidate upload (.xlsx/.csv) and return normalized rows."""
    if "candidate_file" not in request.files:
        return jsonify({"success": False, "error": "No file provided."}), 400

    upload = request.files["candidate_file"]
    filename = str(upload.filename or "").strip()
    if not filename:
        return jsonify({"success": False, "error": "No file selected."}), 400

    ext = _extract_extension(filename)
    if ext not in ALLOWED_BULK_IMPORT_EXTENSIONS:
        allowed = ", ".join(sorted(ALLOWED_BULK_IMPORT_EXTENSIONS))
        return jsonify({"success": False, "error": f"Unsupported file type. Use: {allowed}"}), 400

    try:
        file_bytes = upload.read()
        if not file_bytes:
            return jsonify({"success": False, "error": "Uploaded file is empty."}), 400

        if ext == "csv":
            raw_rows = _extract_csv_rows(file_bytes)
        else:
            raw_rows = _extract_xlsx_rows(file_bytes)

        candidates, row_errors, warnings = _extract_bulk_candidates(raw_rows)
        if not candidates:
            return jsonify({
                "success": False,
                "error": "No valid candidate rows found in uploaded file.",
                "row_errors": row_errors,
                "warnings": warnings,
            }), 400

        return jsonify({
            "success": True,
            "candidates": candidates,
            "row_errors": row_errors,
            "warnings": warnings,
            "imported_count": len(candidates),
        })
    except zipfile.BadZipFile:
        return jsonify({"success": False, "error": "Invalid .xlsx file."}), 400
    except Exception as exc:
        current_app.logger.exception("Bulk candidate import failed: %s", exc)
        return jsonify({"success": False, "error": "Failed to parse uploaded file."}), 500


# --------------------------------------------
# Generated Tests — scoped to current user (retention window)
# --------------------------------------------
@tests_bp.route("/generated-tests")
@login_required
def generated_tests():
    user = session.get("user", {})
    user_email = user.get("email", "dev@aziro.com")

    candidates = get_tests_for_user_today(user_email)

    return render_template(
        "generated_tests.html",
        candidates=candidates,
        present_session_started_at=session.get(GENERATED_TESTS_PRESENT_SESSION_KEY, ""),
        round_order=INTERNAL_ROUND_ORDER,
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
        email = normalize_email(item)
        if not email or email in seen:
            continue
        selected_emails.append(email)
        seen.add(email)

    if not selected_emails:
        return jsonify({"success": False, "error": "No candidates selected."}), 400

    user = session.get("user", {})
    user_email = user.get("email", "dev@aziro.com")
    delegated_access_token = get_valid_graph_delegated_token(user_email)
    if not delegated_access_token:
        delegated_access_token = get_valid_graph_delegated_token_from_session(
            session.get("oauth", {}),
        )
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

        candidate_email = normalize_email(candidate.get("email", email))
        email_ok, email_error = validate_email(candidate_email)
        if not email_ok:
            failures.append({"email": candidate.get("email", email), "reason": email_error})
            continue

        sent, error = send_candidate_test_links_email(
            candidate_name=candidate.get("name", "Candidate"),
            candidate_email=candidate_email,
            role_label=candidate.get("role", ""),
            tests=candidate.get("tests", {}),
            delegated_access_token=delegated_access_token,
            delegated_sender_email=user_email,
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


@tests_bp.route("/generated-tests/delete", methods=["POST"])
@login_required
def delete_generated_tests():
    """Delete selected generated test rows for the current logged-in user."""
    payload = request.get_json(silent=True) or {}
    raw_items = payload.get("items", [])

    if not isinstance(raw_items, list):
        return jsonify({"success": False, "error": "Invalid delete payload."}), 400

    items = []
    for raw in raw_items:
        if isinstance(raw, dict):
            email = str(raw.get("email", "")).strip().lower()
            role = str(raw.get("role", "")).strip()
            created_at = str(raw.get("created_at", "")).strip()
            if not email:
                continue
            items.append({
                "email": email,
                "role": role,
                "created_at": created_at,
            })
        else:
            email = str(raw or "").strip().lower()
            if not email:
                continue
            items.append({"email": email, "role": "", "created_at": ""})

    if not items:
        return jsonify({"success": False, "error": "No candidates selected."}), 400

    user = session.get("user", {})
    user_email = user.get("email", "dev@aziro.com")
    removed_count = delete_generated_tests_for_user(user_email, items)

    return jsonify({
        "success": True,
        "requested_count": len(items),
        "removed_count": removed_count,
    })

