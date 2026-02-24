# filepath: d:\Projects\aziro-hiring-platform\app\blueprints\tests\routes.py
"""
Generated Tests listing — scoped to current user's today session.
Also provides API endpoints for resume/JD extraction (from nikitha_local).
"""
import os
import re
import io
import importlib

from flask import render_template, session, request, jsonify
from werkzeug.utils import secure_filename
from datetime import datetime

from . import tests_bp
from app.utils.auth_decorator import login_required
from app.services.generated_tests_store import get_tests_for_user_today
from app.services.email_service import send_candidate_test_links_email


# ────────────────────────────────────────────
# Resume / JD Upload Helpers
# ────────────────────────────────────────────
UPLOAD_FOLDER = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "uploads"
)
ALLOWED_EXTENSIONS = {"pdf", "doc", "docx", "txt"}


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def extract_email_from_text(text):
    """Extract email from text using regex."""
    email_pattern = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'
    matches = re.findall(email_pattern, text)
    return matches[0] if matches else None


def extract_name_from_text(text):
    """
    Extract the candidate's name from resume text using three strategies:
      1. Label pattern  — looks for "Name: …" or "Full Name: …"
      2. Heuristic scan — first short line that looks like a human name
         (2-4 title-cased words, no digits/special chars, not a heading keyword)
      3. Email-adjacent — derive name from the first email address found
    """
    if not text:
        return None

    lines = [ln.strip() for ln in text.strip().split('\n') if ln.strip()]

    # ── Strategy 1: explicit label ──────────────────────
    label_re = re.compile(
        r'(?:full\s*)?name\s*[:\-–]\s*(.+)', re.IGNORECASE
    )
    for line in lines[:15]:
        m = label_re.match(line)
        if m:
            candidate = m.group(1).strip().strip('.')
            if 2 < len(candidate) < 60 and '@' not in candidate:
                return candidate

    # ── Strategy 2: heuristic first "name-looking" line ─
    skip_words = {
        'resume', 'curriculum', 'vitae', 'cv', 'objective', 'summary',
        'experience', 'education', 'skills', 'address', 'phone',
        'contact', 'profile', 'about', 'references', 'declaration',
        'page', 'confidential',
    }
    name_word_re = re.compile(r"^[A-Z][a-zA-Z\u00C0-\u024F'-]+$")

    for line in lines[:10]:
        low = line.lower()
        # skip lines with emails, urls, phone-like strings, or heading keywords
        if '@' in line or 'http' in low:
            continue
        if re.search(r'\d{5,}', line):          # phone / zip
            continue
        if any(kw in low for kw in skip_words):
            continue

        words = line.split()
        if len(words) < 2 or len(words) > 5:
            continue
        if all(name_word_re.match(w) for w in words):
            return line

    # ── Strategy 3: derive from email ───────────────────
    email = extract_email_from_text(text)
    if email:
        local = email.split('@')[0]
        # strip trailing digits (e.g. john.doe123 → john.doe)
        local = re.sub(r'\d+$', '', local)
        parts = re.split(r'[._\-]', local)
        if 1 < len(parts) <= 4:
            name = ' '.join(p.capitalize() for p in parts if p)
            if len(name) > 3:
                return name

    return None


def _extract_text_from_pdf(file):
    """Extract text from uploaded PDF using pdfplumber if available."""
    pdfplumber = importlib.import_module("pdfplumber")
    pdf_file = io.BytesIO(file.read())
    with pdfplumber.open(pdf_file) as pdf:
        text = ""
        for page in pdf.pages:
            text += page.extract_text() or ""
    return text


def extract_resume_data(file):
    """Extract email and name from resume file."""
    try:
        if file.filename.endswith('.pdf'):
            try:
                text = _extract_text_from_pdf(file)
            except Exception:
                return None
        else:
            text = file.read().decode('utf-8', errors='ignore')

        return {
            "email": extract_email_from_text(text),
            "name": extract_name_from_text(text),
        }
    except Exception as e:
        print(f"Error extracting resume data: {e}")
        return None


def extract_jd_role(text):
    """
    Extract and match job role from JD text.
    Returns the best matching role label from available roles.
    """
    text_lower = text.lower()

    role_keywords = {
        "Python Entry Level (0\u20132 Years)": ["python", "entry level", "junior"],
        "Java Entry Level (0\u20132 Years)": ["java", "entry level", "junior"],
        "JavaScript Entry Level (0\u20132 Years)": ["javascript", " js ", "node.js", "entry level"],
        "Python QA / System / Linux (4+ Years)": ["python", "qa", "linux", "system"],
        "Python QA (4+ Years)": ["python", "qa"],
        "Python Development (4+ Years)": ["python", "development", "developer", "engineer"],
        "Python + AI/ML (4+ Years)": ["python", "ai", "machine learning", "ml"],
        "Java + AWS Development (5+ Years)": ["java", "aws", "development"],
        "Java QA (5+ Years)": ["java", "qa"],
        "BMC Engineer (2\u20135 Years)": ["bmc", "firmware", "bios"],
        "Staff Engineer \u2013 Linux Kernel & Device Driver (3\u20135 Years)": ["linux kernel", "device driver", "kernel"],
        "Systems Architect \u2013 C++ (3\u20135 Years)": ["c++", "cpp", "systems architect"],
    }

    scores = {}
    for role_label, keywords in role_keywords.items():
        score = sum(1 for kw in keywords if kw in text_lower)
        scores[role_label] = score

    best_match = max(scores, key=scores.get)
    return best_match if scores[best_match] > 0 else None


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

    data = extract_resume_data(file)
    if data:
        return jsonify(data), 200
    return jsonify({"error": "Could not extract data from resume"}), 400


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

    try:
        if file.filename.endswith('.pdf'):
            text = _extract_text_from_pdf(file)
        else:
            text = file.read().decode('utf-8', errors='ignore')

        matched_role = extract_jd_role(text)
        if matched_role:
            return jsonify({"role": matched_role}), 200
        return jsonify({"role": None, "message": "Could not determine role from JD"}), 200

    except Exception as e:
        print(f"Error extracting JD role: {e}")
        return jsonify({"error": "Error processing JD file"}), 400


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
