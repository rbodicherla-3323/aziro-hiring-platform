# filepath: d:\Projects\aziro-hiring-platform\app\blueprints\dashboard\routes.py
"""
Dashboard & Test Creation routes.
"""
import os
import uuid
from datetime import datetime, timezone, timedelta

from flask import render_template, request, redirect, url_for, session, flash

from . import dashboard_bp
from app.utils.auth_decorator import login_required
from app.utils.role_normalizer import normalize_role, ROLE_NAME_TO_KEY
from app.utils.role_round_mapping import ROLE_ROUND_MAPPING, ROLE_CODING_LANGUAGE
from app.utils.round_display_mapping import ROUND_DISPLAY_MAPPING
from app.utils.round_question_mapping import DOMAIN_QUESTION_FILES

from app.services.generated_tests_store import add_generated_test
from app.services.mcq_session_registry import MCQ_SESSION_REGISTRY
from app.services.coding_session_registry import CODING_SESSION_REGISTRY
from app.services import db_service
from app.services.question_bank.loader import QuestionLoader
from app.services.question_bank.registry import QuestionRegistry
from app.services.question_bank.selector import (
    QuestionSelectionError,
    build_frozen_mcq_round_payload,
    should_use_enterprise_selection,
)
from app.services.email_service import send_candidate_test_links_email
from app.services.user_token_store import (
    get_valid_graph_delegated_token,
    get_valid_graph_delegated_token_from_session,
)

APTITUDE_ENABLED_ROLE_KEYS = {"python_entry", "java_entry", "js_entry"}


# --------------------------------------------
# Helpers
# --------------------------------------------

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
    path = url_for(endpoint, **values)

    # Optional force-base URL for centralized execution environments.
    # Example: APP_PUBLIC_BASE_URL=https://azirohire.aziro.com
    forced_base = (os.getenv("APP_PUBLIC_BASE_URL") or "").strip().rstrip("/")
    if forced_base:
        return f"{forced_base}{path}"

    forwarded_proto = (request.headers.get("X-Forwarded-Proto") or "").split(",")[0].strip()
    forwarded_host = (request.headers.get("X-Forwarded-Host") or "").split(",")[0].strip()
    scheme = forwarded_proto or request.scheme
    host = forwarded_host or request.host
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


# --------------------------------------------
# Dashboard
# --------------------------------------------

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


# --------------------------------------------
# Create Test
# --------------------------------------------

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
    delegated_access_token = get_valid_graph_delegated_token(user_email)
    if not delegated_access_token:
        delegated_access_token = get_valid_graph_delegated_token_from_session(
            session.get("oauth", {}),
        )

    batch_id = f"batch_{uuid.uuid4().hex[:8]}"
    email_success_count = 0
    email_failures = []

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

        # Hard gate: only generate coding links if server runtime is available.
        if coding_rounds:
            from app.blueprints.coding.routes import get_language_runtime_status

            runtime_ok, runtime_requirement = get_language_runtime_status(coding_language)
            if not runtime_ok:
                flash(
                    f"Coding runtime unavailable on server for {coding_language.upper()}. "
                    f"Required: {runtime_requirement}. "
                    f"Coding round was skipped for candidate '{name}'.",
                    "warning",
                )
                coding_rounds = []

        tests = {}
        question_loader = QuestionLoader(base_path="app/services/question_bank/data")
        question_registry = QuestionRegistry(question_loader)
        candidate_generation_failed = False

        link_created_at = datetime.now(timezone.utc)
        link_expires_at = db_service.compute_test_link_expires_at(link_created_at)

        # Generate MCQ round links
        for round_key in mcq_rounds:
            question_files = question_registry.get_question_files(
                role_key=role_key,
                round_key=round_key,
                domain=domain.lower() if domain != "None" else None,
            )
            questions = question_registry.get_questions(
                role_key=role_key,
                round_key=round_key,
                domain=domain.lower() if domain != "None" else None,
            )
            if not questions:
                flash(
                    f"Question bank missing for role '{role_label}' round '{round_key}'. "
                    f"Candidate '{name}' was skipped.",
                    "danger",
                )
                candidate_generation_failed = True
                break

            frozen_payload = {}
            if should_use_enterprise_selection(role_key, round_key, question_files):
                try:
                    frozen_payload = build_frozen_mcq_round_payload(
                        role_key=role_key,
                        round_key=round_key,
                        question_files=question_files,
                        questions=questions,
                    )
                except (QuestionSelectionError, ValueError) as exc:
                    flash(
                        f"Enterprise MCQ freeze unavailable for role '{role_label}' round '{round_key}': {exc}. "
                        f"Using standard question selection for candidate '{name}'.",
                        "warning",
                    )
                    frozen_payload = {
                        "force_non_enterprise_selection": True,
                        "selection_error": str(exc),
                    }

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
                "question_bank_files": list(question_files),
                "created_by": user_email,
                "created_at": link_created_at.isoformat(),
                "expires_at": link_expires_at.isoformat(),
                "test_url": test_url,
            }
            if frozen_payload:
                mcq_meta.update(frozen_payload)

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
        if candidate_generation_failed:
            continue

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
                "question_bank_files": list(DOMAIN_QUESTION_FILES.get(domain.lower(), [])),
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
                "url": test_url,
                "type": "mcq",
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

        email_sent, email_error = send_candidate_test_links_email(
            candidate_name=name,
            candidate_email=email,
            role_label=role_label,
            tests=tests,
            delegated_access_token=delegated_access_token,
            delegated_sender_email=user_email,
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
