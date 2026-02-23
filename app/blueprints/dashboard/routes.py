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

from app.services.generated_tests_store import (
    GENERATED_TESTS,
    add_generated_test,
    get_tests_for_user_today,
    get_all_tests_today,
    get_tests_for_user_in_range,
)
from app.services.mcq_session_registry import MCQ_SESSION_REGISTRY
from app.services.coding_session_registry import CODING_SESSION_REGISTRY
from app.services.evaluation_store import EVALUATION_STORE
from app.services.email_service import send_candidate_test_links_email


# ────────────────────────────────────────────
# Helpers
# ────────────────────────────────────────────

def _current_user_email():
    user = session.get("user", {})
    return user.get("email", "dev@aziro.com")


def _current_user_name():
    user = session.get("user", {})
    return user.get("name", "Dev User")


def _compute_stats(test_list):
    """Compute stats dict from a list of generated test entries."""
    emails = set()
    total_tests = 0
    completed = 0
    pending = 0

    for t in test_list:
        emails.add(t.get("email", ""))
        tests = t.get("tests", {})
        for level, test_info in tests.items():
            total_tests += 1
            sid = test_info.get("session_id", "")
            if sid and sid in EVALUATION_STORE:
                completed += 1
            else:
                pending += 1

    return {
        "total_candidates": len(emails),
        "total_tests": total_tests,
        "completed": completed,
        "pending": pending,
    }


def _filter_tests_by_date(test_list, filter_type, specific_date=None):
    """Filter test entries by date range."""
    now = datetime.now(timezone.utc)

    if filter_type == "today":
        cutoff = now.replace(hour=0, minute=0, second=0, microsecond=0)
    elif filter_type == "24h":
        cutoff = now - timedelta(hours=24)
    elif filter_type == "2d":
        cutoff = now - timedelta(days=2)
    elif filter_type == "7d":
        cutoff = now - timedelta(days=7)
    elif filter_type == "date" and specific_date:
        try:
            d = datetime.strptime(specific_date, "%Y-%m-%d")
            cutoff = d.replace(tzinfo=timezone.utc)
            end = cutoff + timedelta(days=1)
            results = []
            for t in test_list:
                created = t.get("created_at", "")
                if isinstance(created, str):
                    try:
                        dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
                    except (ValueError, TypeError):
                        continue
                elif isinstance(created, datetime):
                    dt = created
                else:
                    continue
                if cutoff <= dt < end:
                    results.append(t)
            return results
        except ValueError:
            return test_list
    else:
        return test_list

    results = []
    for t in test_list:
        created = t.get("created_at", "")
        if isinstance(created, str):
            try:
                dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
            except (ValueError, TypeError):
                continue
        elif isinstance(created, datetime):
            dt = created
        else:
            continue
        if dt >= cutoff:
            results.append(t)
    return results


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
    all_today = get_all_tests_today()
    today_stats = _compute_stats(all_today)

    # My today stats
    my_today = get_tests_for_user_today(user_email)
    my_today_stats = _compute_stats(my_today)

    # My stats with date filter
    my_all = [t for t in GENERATED_TESTS if t.get("created_by", "").lower() == user_email.lower()]
    my_filtered = _filter_tests_by_date(my_all, date_filter, specific_date)
    my_stats = _compute_stats(my_filtered)

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
    aptitude_enabled_values = request.form.getlist("aptitude_enabled[]")
    if not aptitude_enabled_values:
        # Backward compatibility with older form field name.
        aptitude_enabled_values = request.form.getlist("aptitude_optional[]")

    # Get file uploads (resume & JD)
    resume_files = request.files.getlist("resume[]")
    jd_files = request.files.getlist("jd[]")

    user_email = _current_user_email()
    batch_id = f"batch_{uuid.uuid4().hex[:8]}"
    email_success_count = 0
    email_failures = []

    for i in range(len(names)):
        name = names[i].strip()
        email = emails[i].strip()
        role_label = roles[i].strip()
        domain = domains[i].strip() if i < len(domains) else "None"
        aptitude_enabled_raw = (
            aptitude_enabled_values[i].strip().lower()
            if i < len(aptitude_enabled_values)
            else "yes"
        )
        aptitude_enabled = aptitude_enabled_raw in ("yes", "true", "1")

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

        role_config = ROLE_ROUND_MAPPING.get(role_key, {})
        display_map = ROUND_DISPLAY_MAPPING.get(role_key, {})

        mcq_rounds = list(role_config.get("rounds", []))
        if not aptitude_enabled:
            mcq_rounds = [rk for rk in mcq_rounds if rk != "L1"]
        coding_rounds = role_config.get("coding_rounds", [])
        coding_language = role_config.get("coding_language", "java")
        allow_domain = role_config.get("allow_domain", False)

        tests = {}

        # Generate MCQ round links
        for round_key in mcq_rounds:
            session_id = uuid.uuid4().hex
            round_label = display_map.get(round_key, f"Round {round_key}")

            # Build dynamic URL using request host
            test_url = f"{request.scheme}://{request.host}/mcq/start/{session_id}"

            MCQ_SESSION_REGISTRY[session_id] = {
                "candidate_name": name,
                "email": email,
                "role_key": role_key,
                "role_label": role_label,
                "round_key": round_key,
                "round_label": round_label,
                "batch_id": batch_id,
                "domain": domain.lower() if domain != "None" else None,
            }

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

            test_url = f"{request.scheme}://{request.host}/coding/start/{session_id}"

            CODING_SESSION_REGISTRY[session_id] = {
                "candidate_name": name,
                "email": email,
                "role_key": role_key,
                "role_label": role_label,
                "round_key": round_key,
                "round_label": round_label,
                "batch_id": batch_id,
                "language": coding_language,
                "domain": domain.lower() if domain != "None" else None,
            }

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

            test_url = f"{request.scheme}://{request.host}/mcq/start/{session_id}"

            MCQ_SESSION_REGISTRY[session_id] = {
                "candidate_name": name,
                "email": email,
                "role_key": role_key,
                "role_label": role_label,
                "round_key": round_key,
                "round_label": round_label,
                "batch_id": batch_id,
                "domain": domain.lower(),
            }

            tests[round_key] = {
                "session_id": session_id,
                "label": round_label,
                "url": test_url,
                "type": "mcq",
            }        # Store in generated tests
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

        email_sent, email_error = send_candidate_test_links_email(
            candidate_name=name,
            candidate_email=email,
            role_label=role_label,
            tests=tests,
        )
        if email_sent:
            email_success_count += 1
        else:
            email_failures.append({"email": email, "reason": email_error})

    flash("Test links generated successfully!", "success")
    if email_success_count:
        flash(f"Test links emailed to {email_success_count} candidate(s).", "success")
    if email_failures:
        failed_preview = ", ".join(f["email"] for f in email_failures[:3])
        suffix = "" if len(email_failures) <= 3 else ", ..."
        failure_reason = email_failures[0].get("reason", "Unknown error")
        flash(
            f"Email sending failed for {len(email_failures)} candidate(s): "
            f"{failed_preview}{suffix}. {failure_reason}",
            "warning",
        )
    return redirect(url_for("tests.generated_tests"))
