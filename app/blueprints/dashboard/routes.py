# filepath: d:\Projects\aziro-hiring-platform\app\blueprints\dashboard\routes.py
"""
Dashboard & Test Creation routes.
"""
import uuid
from datetime import datetime, timezone, timedelta

from flask import render_template, request, redirect, url_for, session, flash

from . import dashboard_bp
from app.utils.auth_decorator import login_required
from app.utils.role_normalizer import normalize_role, ROLE_NAME_TO_KEY
from app.utils.role_round_mapping import ROLE_ROUND_MAPPING, ROLE_CODING_LANGUAGE
from app.utils.round_display_mapping import ROUND_DISPLAY_MAPPING
from app.utils.round_question_mapping import ROUND_QUESTION_MAPPING

from app.services.generated_tests_store import add_generated_test
from app.services.mcq_session_registry import MCQ_SESSION_REGISTRY
from app.services.coding_session_registry import CODING_SESSION_REGISTRY
from app.services import db_service

APTITUDE_ENABLED_ROLE_KEYS = {"python_entry", "java_entry", "js_entry"}


# ────────────────────────────────────────────
# Helpers
# ────────────────────────────────────────────

def _current_user_email():
    user = session.get("user", {})
    return user.get("email", "dev@aziro.com")


def _current_user_name():
    user = session.get("user", {})
    return user.get("name", "Dev User")


def _build_test_url(endpoint, **values):
    """
    Build an absolute test URL that respects reverse-proxy headers.
    This prevents generating http:// links when the app is externally served over HTTPS.
    """
    forwarded_proto = (request.headers.get("X-Forwarded-Proto") or "").split(",")[0].strip()
    forwarded_host = (request.headers.get("X-Forwarded-Host") or "").split(",")[0].strip()
    scheme = forwarded_proto or request.scheme
    host = forwarded_host or request.host
    path = url_for(endpoint, **values)
    return f"{scheme}://{host}{path}"


def _resolve_date_range(filter_type: str, specific_date: str = ""):
    now = datetime.now(timezone.utc)
    if filter_type == "today":
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=1)
        return start, end
    if filter_type == "24h":
        return now - timedelta(hours=24), now
    if filter_type == "2d":
        return now - timedelta(days=2), now
    if filter_type == "7d":
        return now - timedelta(days=7), now
    if filter_type == "date" and specific_date:
        try:
            d = datetime.strptime(specific_date, "%Y-%m-%d")
            start = d.replace(tzinfo=timezone.utc)
            end = start + timedelta(days=1)
            return start, end
        except ValueError:
            return None, None
    return None, None


# ────────────────────────────────────────────
# Dashboard
# ────────────────────────────────────────────

@dashboard_bp.route("/dashboard")
@login_required
def dashboard():
    user_email = _current_user_email()
    user_name = _current_user_name()

    # Date filter
    date_filter = request.args.get("filter", "today")
    specific_date = request.args.get("date", "")
    if specific_date:
        date_filter = "date"

    # Today's stats (all users)
    today_start, today_end = _resolve_date_range("today")
    today_stats = db_service.get_test_link_stats(
        since=today_start,
        until=today_end,
    )

    # My today stats
    my_today_stats = db_service.get_test_link_stats(
        since=today_start,
        until=today_end,
        created_by=user_email,
    )

    # My stats with date filter
    range_start, range_end = _resolve_date_range(date_filter, specific_date)
    my_stats = db_service.get_test_link_stats(
        since=range_start,
        until=range_end,
        created_by=user_email,
    )

    return render_template(
        "dashboard.html",
        user_name=user_name,
        user_email=user_email,
        today_stats=today_stats,
        my_today_stats=my_today_stats,
        my_stats=my_stats,
        date_filter=date_filter,
        specific_date=specific_date,
    )


# ────────────────────────────────────────────
# Create Test
# ────────────────────────────────────────────

@dashboard_bp.route("/create-test", methods=["GET", "POST"])
@login_required
def create_test():
    if request.method == "GET":
        return render_template("test_create.html")

    # POST: Generate test links
    names = request.form.getlist("name[]")
    emails = request.form.getlist("email[]")
    roles = request.form.getlist("role[]")
    domains = request.form.getlist("domain[]")

    # Get file uploads (resume & JD)
    resume_files = request.files.getlist("resume[]")
    jd_files = request.files.getlist("jd[]")

    user_email = _current_user_email()
    batch_id = f"batch_{uuid.uuid4().hex[:8]}"

    for i in range(len(names)):
        name = names[i].strip()
        email = emails[i].strip()
        role_label = roles[i].strip()
        domain = domains[i].strip() if i < len(domains) else "None"

        # Save uploaded files if present
        resume_path = None
        jd_path = None
        if i < len(resume_files) and resume_files[i] and resume_files[i].filename:
            from app.blueprints.tests.routes import save_uploaded_file
            resume_path = save_uploaded_file(resume_files[i], name, "resume")
        if i < len(jd_files) and jd_files[i] and jd_files[i].filename:
            from app.blueprints.tests.routes import save_uploaded_file
            jd_path = save_uploaded_file(jd_files[i], name, "jd")

        if not name or not email or not role_label:
            continue

        role_key = normalize_role(role_label)
        if not role_key:
            flash(f"Unknown role: {role_label}", "warning")
            continue

        aptitude_enabled = role_key in APTITUDE_ENABLED_ROLE_KEYS
        role_config = ROLE_ROUND_MAPPING.get(role_key, {})
        display_map = ROUND_DISPLAY_MAPPING.get(role_key, {})

        mcq_rounds = list(role_config.get("rounds", []))
        if not aptitude_enabled:
            mcq_rounds = [rk for rk in mcq_rounds if rk != "L1"]
        coding_rounds = role_config.get("coding_rounds", [])
        coding_language = role_config.get("coding_language", "java")
        allow_domain = role_config.get("allow_domain", False)

        tests = {}

        link_created_at = datetime.now(timezone.utc)
        link_expires_at = db_service.compute_test_link_expires_at(link_created_at)

        # Generate MCQ round links
        for round_key in mcq_rounds:
            session_id = uuid.uuid4().hex
            round_label = display_map.get(round_key, f"Round {round_key}")

            # Build dynamic URL using forwarded scheme/host when behind proxy.
            test_url = _build_test_url("mcq.start_test", session_id=session_id)

            mcq_meta = {
                "session_id": session_id,
                "candidate_name": name,
                "email": email,
                "role_key": role_key,
                "role_label": role_label,
                "round_key": round_key,
                "round_label": round_label,
                "batch_id": batch_id,
                "domain": domain.lower() if domain != "None" else None,
                "created_by": user_email,
                "created_at": link_created_at.isoformat(),
                "expires_at": link_expires_at.isoformat(),
                "test_url": test_url,
            }
            MCQ_SESSION_REGISTRY[session_id] = mcq_meta
            db_service.save_test_link(
                meta=mcq_meta,
                test_type="mcq",
                created_by=user_email,
                created_at=link_created_at,
                expires_at=link_expires_at,
            )

            tests[round_key] = {
                "session_id": session_id,
                "label": round_label,
                "url": test_url,
                "type": "mcq",
            }

        # Generate Coding round links
        for round_key in coding_rounds:
            session_id = uuid.uuid4().hex
            round_label = display_map.get(round_key, f"Coding Round {round_key}")

            test_url = _build_test_url("coding.start_test", session_id=session_id)

            coding_meta = {
                "session_id": session_id,
                "candidate_name": name,
                "email": email,
                "role_key": role_key,
                "role_label": role_label,
                "round_key": round_key,
                "round_label": round_label,
                "batch_id": batch_id,
                "language": coding_language,
                "domain": domain.lower() if domain != "None" else None,
                "created_by": user_email,
                "created_at": link_created_at.isoformat(),
                "expires_at": link_expires_at.isoformat(),
                "test_url": test_url,
            }
            CODING_SESSION_REGISTRY[session_id] = coding_meta
            db_service.save_test_link(
                meta=coding_meta,
                test_type="coding",
                created_by=user_email,
                created_at=link_created_at,
                expires_at=link_expires_at,
            )

            tests[round_key] = {
                "session_id": session_id,
                "label": round_label,
                "url": test_url,
                "type": "coding",
            }

        # Domain round (L6) if applicable
        if allow_domain and domain and domain != "None":
            round_key = "L6"
            session_id = uuid.uuid4().hex
            round_label = f"Domain: {domain}"

            test_url = _build_test_url("mcq.start_test", session_id=session_id)

            mcq_domain_meta = {
                "session_id": session_id,
                "candidate_name": name,
                "email": email,
                "role_key": role_key,
                "role_label": role_label,
                "round_key": round_key,
                "round_label": round_label,
                "batch_id": batch_id,
                "domain": domain.lower(),
                "created_by": user_email,
                "created_at": link_created_at.isoformat(),
                "expires_at": link_expires_at.isoformat(),
                "test_url": test_url,
            }
            MCQ_SESSION_REGISTRY[session_id] = mcq_domain_meta
            db_service.save_test_link(
                meta=mcq_domain_meta,
                test_type="mcq",
                created_by=user_email,
                created_at=link_created_at,
                expires_at=link_expires_at,
            )

            tests[round_key] = {
                "session_id": session_id,
                "label": round_label,
                "url": test_url,                "type": "mcq",
            }

        # Store in generated tests
        add_generated_test({
            "name": name,
            "email": email,
            "role": role_label,
            "role_key": role_key,
            "batch_id": batch_id,
            "aptitude_enabled": aptitude_enabled,
            "tests": tests,
            "resume_path": resume_path,
            "jd_path": jd_path,
            "created_by": user_email,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })

    flash("Test links generated successfully!", "success")
    flash("Emails will be sent only when 'Send Emails to Selected' is clicked.", "info")
    return redirect(url_for("tests.generated_tests"))
