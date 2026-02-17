import uuid
from datetime import datetime, timezone
from flask import Blueprint, render_template, request, redirect, url_for, jsonify
from app.utils.round_display_mapping import ROUND_DISPLAY_MAPPING
from app.utils.role_normalizer import normalize_role
from app.utils.role_round_mapping import ROLE_ROUND_MAPPING
from app.services.generated_tests_store import GENERATED_TESTS
from app.services.mcq_session_registry import MCQ_SESSION_REGISTRY
from app.services.coding_session_registry import CODING_SESSION_REGISTRY
from app.services import db_service
import os
from werkzeug.utils import secure_filename
import re
import pdfplumber

tests_bp = Blueprint("tests", __name__)

# Upload folder configuration
UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "uploads")
ALLOWED_EXTENSIONS = {"pdf", "doc", "docx", "txt"}

def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

def extract_email_from_text(text):
    """Extract email from text using regex"""
    email_pattern = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'
    matches = re.findall(email_pattern, text)
    return matches[0] if matches else None

def extract_name_from_text(text):
    """Extract likely name from text (usually first or second line)"""
    lines = text.strip().split('\n')
    for line in lines[:5]:  # Check first 5 lines
        line = line.strip()
        if line and len(line) > 2 and len(line) < 100:
            # Skip lines that look like emails, URLs, or common headers
            if '@' not in line and 'http' not in line.lower() and 'resume' not in line.lower():
                return line
    return None

def extract_resume_data(file):
    """Extract email and name from resume file"""
    try:
        if file.filename.endswith('.pdf'):
            try:
                import io
                pdf_file = io.BytesIO(file.read())
                with pdfplumber.open(pdf_file) as pdf:
                    text = ""
                    for page in pdf.pages:
                        text += page.extract_text() or ""
            except Exception:
                return None
        else:
            # For non-PDF files, read as text
            text = file.read().decode('utf-8', errors='ignore')
        
        email = extract_email_from_text(text)
        name = extract_name_from_text(text)
        
        return {
            "email": email,
            "name": name
        }
    except Exception as e:
        print(f"Error extracting resume data: {e}")
        return None

def save_uploaded_file(file, candidate_name, file_type):
    """Save uploaded file and return the file path"""
    if not file or file.filename == "":
        return None
    
    if not allowed_file(file.filename):
        return None
    
    # Create upload folder if it doesn't exist
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    
    # Create a unique filename
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    sanitized_name = secure_filename(candidate_name.replace(" ", "_"))
    original_ext = secure_filename(file.filename).rsplit(".", 1)[1].lower()
    filename = f"{sanitized_name}_{file_type}_{timestamp}.{original_ext}"
    
    filepath = os.path.join(UPLOAD_FOLDER, filename)
    file.save(filepath)
    
    return filepath


@tests_bp.route("/api/extract-resume", methods=["POST"])
def extract_resume():
    """API endpoint to extract email and name from resume file"""
    if "resume" not in request.files:
        return jsonify({"error": "No file provided"}), 400
    
    file = request.files["resume"]
    
    if file.filename == "":
        return jsonify({"error": "No file selected"}), 400
    
    if not allowed_file(file.filename):
        return jsonify({"error": "File type not allowed"}), 400
    
    # Extract data from resume
    data = extract_resume_data(file)
    
    if data:
        return jsonify(data), 200
    else:
        return jsonify({"error": "Could not extract data from resume"}), 400


@tests_bp.route("/create-test", methods=["GET", "POST"])
def create_test():

    if request.method == "POST":

        names = request.form.getlist("name[]")
        emails = request.form.getlist("email[]")
        roles = request.form.getlist("role[]")
        domains = request.form.getlist("domain[]")
        
        # Get file uploads
        resume_files = request.files.getlist("resume[]")
        jd_files = request.files.getlist("jd[]")
        
        batch_id = datetime.now(timezone.utc).strftime("batch_%Y%m%d_%H%M%S")
        
        # Clear previous tests - only show newly generated ones
        GENERATED_TESTS.clear()

        for idx, (name, email, role_label, domain) in enumerate(zip(names, emails, roles, domains)):

            # Save uploaded files
            resume_path = None
            jd_path = None
            
            if idx < len(resume_files) and resume_files[idx]:
                resume_path = save_uploaded_file(resume_files[idx], name, "resume")
            
            if idx < len(jd_files) and jd_files[idx]:
                jd_path = save_uploaded_file(jd_files[idx], name, "jd")

            role_key = normalize_role(role_label)
            if not role_key:
                continue

            config = ROLE_ROUND_MAPPING[role_key]
            tests = {}

            # -------------------------------
            # MCQ ROUNDS (L1, L2, L3, L5)
            # -------------------------------
            for round_key in config["rounds"]:

                session_id = str(uuid.uuid4())

                MCQ_SESSION_REGISTRY[session_id] = {
                    "role_key": role_key,
                    "role_label": role_label,
                    "round_key": round_key,
                    "round_label": ROUND_DISPLAY_MAPPING
    .get(role_key, {})
    .get(round_key, round_key),

                    "batch_id": batch_id,
                    "domain": None,
                    "candidate_name": name,
                    "email": email,
                    "resume_path": resume_path,
                    "jd_path": jd_path
                }

                tests[round_key] = {
                    "label": ROUND_DISPLAY_MAPPING.get(role_key, {}).get(round_key, round_key),

                    "url": f"{request.host_url.rstrip('/')}/mcq/start/{session_id}"
                }

            # -------------------------------
            # CODING ROUND (L4)
            # -------------------------------
            coding_rounds = config.get("coding_rounds", [])
            coding_language = config.get("coding_language", "java")

            for round_key in coding_rounds:
                session_id = str(uuid.uuid4())

                CODING_SESSION_REGISTRY[session_id] = {
                    "role_key": role_key,
                    "role_label": role_label,
                    "round_key": round_key,
                    "round_label": ROUND_DISPLAY_MAPPING
    .get(role_key, {})
    .get(round_key, f"Coding Challenge ({round_key})"),
                    "language": coding_language,
                    "batch_id": batch_id,
                    "domain": None,
                    "candidate_name": name,
                    "email": email,
                    "resume_path": resume_path,
                    "jd_path": jd_path,
                }

                tests[round_key] = {
                    "label": ROUND_DISPLAY_MAPPING.get(role_key, {}).get(round_key, f"Coding Challenge ({round_key})"),
                    "url": f"{request.host_url.rstrip('/')}/coding/start/{session_id}"
                }

            # -------------------------------
            # DOMAIN ROUND (L6)
            # -------------------------------
            if config["allow_domain"] and domain and domain != "None":

                session_id = str(uuid.uuid4())

                MCQ_SESSION_REGISTRY[session_id] = {
                    "role_key": role_key,
                    "role_label": role_label,
                    "round_key": "L6",
                    "round_label": f"Domain – {domain}",
                    "domain": domain.lower(),
                    "batch_id": batch_id,
                    "candidate_name": name,
                    "email": email,
                    "resume_path": resume_path,
                    "jd_path": jd_path
                }

                tests["L6"] = {
                    "label": f"Domain – {domain}",
                    "url": f"{request.host_url.rstrip('/')}/mcq/start/{session_id}"
                }

            ROUND_ORDER = ["L1", "L2", "L3", "L4", "L5", "L6"]
            tests = dict(sorted(
                tests.items(),
                key=lambda x: ROUND_ORDER.index(x[0]) if x[0] in ROUND_ORDER else 99
            ))

            GENERATED_TESTS.append({
                "name": name,
                "email": email,
                "role": role_label,
                "resume_path": resume_path,
                "jd_path": jd_path,
                "tests": tests
            })

            # -------------------------------------------
            # PERSIST to DB (survives server restarts)
            # -------------------------------------------
            try:
                candidate = db_service.get_or_create_candidate(name, email)
                db_service.get_or_create_test_session(
                    candidate_id=candidate.id,
                    role_key=role_key,
                    role_label=role_label,
                    batch_id=batch_id,
                )
            except Exception:
                # DB write is best-effort; in-memory store is primary
                pass

        return redirect(url_for("tests.generated_tests"))

    return render_template("test_create.html")


@tests_bp.route("/generated-tests")
def generated_tests():
    return render_template(
        "generated_tests.html",
        candidates=GENERATED_TESTS
    )
