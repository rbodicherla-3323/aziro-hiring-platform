# filepath: d:\Projects\aziro-hiring-platform\app\blueprints\dashboard\routes.py
"""
Dashboard & Test Creation routes.
"""
import uuid
from datetime import datetime, timedelta, timezone

from flask import flash, redirect, render_template, request, session, url_for

from . import dashboard_bp
from app.services.coding_session_registry import CODING_SESSION_REGISTRY
from app.services.email_service import send_candidate_test_links_email
from app.services.evaluation_store import EVALUATION_STORE
from app.services.generated_tests_store import (
    GENERATED_TESTS,
    add_generated_test,
    get_all_tests_today,
    get_tests_for_user_today,
)
from app.services.mcq_session_registry import MCQ_SESSION_REGISTRY
from app.services.question_bank.loader import QuestionLoader
from app.services.question_bank.registry import QuestionRegistry
from app.services.question_bank.selector import build_frozen_mcq_round_payload, should_use_enterprise_selection
from app.services.question_bank.validator import QuestionBankValidationError
from app.services.user_token_store import (
    get_valid_graph_delegated_token,
    get_valid_graph_delegated_token_from_session,
)
from app.utils.auth_decorator import login_required
from app.utils.role_normalizer import normalize_role
from app.utils.role_round_mapping import ROLE_ROUND_MAPPING
from app.utils.round_display_mapping import ROUND_DISPLAY_MAPPING

APTITUDE_ENABLED_ROLE_KEYS = {"python_entry", "java_entry", "js_entry"}


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


def _compute_stats(test_list):
    """Compute stats dict from a list of generated test entries."""
    emails = set()
    total_tests = 0
    completed = 0
    pending = 0

    for test_entry in test_list:
        emails.add(test_entry.get("email", ""))
        tests = test_entry.get("tests", {})
        for _, test_info in tests.items():
            total_tests += 1
            session_id = test_info.get("session_id", "")
            if session_id and session_id in EVALUATION_STORE:
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
            start_dt = datetime.strptime(specific_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            end_dt = start_dt + timedelta(days=1)
        except ValueError:
            return test_list

        filtered = []
        for test_entry in test_list:
            created = test_entry.get("created_at", "")
            if isinstance(created, str):
                try:
                    created_dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
                except (TypeError, ValueError):
                    continue
            elif isinstance(created, datetime):
                created_dt = created
            else:
                continue
            if start_dt <= created_dt < end_dt:
                filtered.append(test_entry)
        return filtered
    else:
        return test_list

    filtered = []
    for test_entry in test_list:
        created = test_entry.get("created_at", "")
        if isinstance(created, str):
            try:
                created_dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
            except (TypeError, ValueError):
                continue
        elif isinstance(created, datetime):
            created_dt = created
        else:
            continue
        if created_dt >= cutoff:
            filtered.append(test_entry)
    return filtered


@dashboard_bp.route("/dashboard")
@login_required
def dashboard():
    user_email = _current_user_email()
    user_name = _current_user_name()

    date_filter = request.args.get("filter", "today")
    specific_date = request.args.get("date", "")
    if specific_date:
        date_filter = "date"

    all_today = get_all_tests_today()
    today_stats = _compute_stats(all_today)

    my_today = get_tests_for_user_today(user_email)
    my_today_stats = _compute_stats(my_today)

    my_all = [item for item in GENERATED_TESTS if item.get("created_by", "").lower() == user_email.lower()]
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


@dashboard_bp.route("/create-test", methods=["GET", "POST"])
@login_required
def create_test():
    if request.method == "GET":
        return render_template("test_create.html")

    names = request.form.getlist("name[]")
    emails = request.form.getlist("email[]")
    roles = request.form.getlist("role[]")
    domains = request.form.getlist("domain[]")
    resume_files = request.files.getlist("resume[]")
    jd_files = request.files.getlist("jd[]")

    user_email = _current_user_email()
    delegated_access_token = get_valid_graph_delegated_token(user_email)
    if not delegated_access_token:
        delegated_access_token = get_valid_graph_delegated_token_from_session(session.get("oauth", {}))

    batch_id = f"batch_{uuid.uuid4().hex[:8]}"
    email_success_count = 0
    email_failures = []

    loader = QuestionLoader(base_path="app/services/question_bank/data")
    question_registry = QuestionRegistry(loader)

    for i in range(len(names)):
        name = names[i].strip()
        email = emails[i].strip()
        role_label = roles[i].strip()
        domain = domains[i].strip() if i < len(domains) else "None"
        normalized_domain = domain.lower() if domain and domain != "None" else None

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
            mcq_rounds = [round_key for round_key in mcq_rounds if round_key != "L1"]
        coding_rounds = role_config.get("coding_rounds", [])
        coding_language = role_config.get("coding_language", "java")
        allow_domain = role_config.get("allow_domain", False)

        tests = {}
        pending_mcq_sessions = {}
        pending_coding_sessions = {}
        candidate_generation_error = None

        for round_key in mcq_rounds:
            session_id = uuid.uuid4().hex
            round_label = display_map.get(round_key, f"Round {round_key}")
            test_url = _build_test_url("mcq.start_test", session_id=session_id)
            session_payload = {
                "candidate_name": name,
                "email": email,
                "role_key": role_key,
                "role_label": role_label,
                "round_key": round_key,
                "round_label": round_label,
                "batch_id": batch_id,
                "domain": normalized_domain,
            }

            try:
                question_files = question_registry.get_question_files(
                    role_key=role_key,
                    round_key=round_key,
                    domain=normalized_domain,
                )
                if should_use_enterprise_selection(role_key, round_key, question_files):
                    questions = question_registry.get_questions(
                        role_key=role_key,
                        round_key=round_key,
                        domain=normalized_domain,
                    )
                    if not questions:
                        raise ValueError(f"No questions found for {role_label} {round_label}")
                    session_payload.update(
                        build_frozen_mcq_round_payload(
                            role_key=role_key,
                            round_key=round_key,
                            question_files=question_files,
                            questions=questions,
                        )
                    )
            except (FileNotFoundError, QuestionBankValidationError, ValueError) as exc:
                candidate_generation_error = f"{name} ({role_label}) failed for {round_label}: {exc}"
                break

            pending_mcq_sessions[session_id] = session_payload
            tests[round_key] = {
                "session_id": session_id,
                "label": round_label,
                "url": test_url,
                "type": "mcq",
            }

        if candidate_generation_error:
            flash(candidate_generation_error, "warning")
            continue

        for round_key in coding_rounds:
            session_id = uuid.uuid4().hex
            round_label = display_map.get(round_key, f"Coding Round {round_key}")
            test_url = _build_test_url("coding.start_test", session_id=session_id)

            pending_coding_sessions[session_id] = {
                "candidate_name": name,
                "email": email,
                "role_key": role_key,
                "role_label": role_label,
                "round_key": round_key,
                "round_label": round_label,
                "batch_id": batch_id,
                "language": coding_language,
                "domain": normalized_domain,
            }

            tests[round_key] = {
                "session_id": session_id,
                "label": round_label,
                "url": test_url,
                "type": "coding",
            }

        if allow_domain and normalized_domain:
            round_key = "L6"
            session_id = uuid.uuid4().hex
            round_label = f"Domain: {domain}"
            test_url = _build_test_url("mcq.start_test", session_id=session_id)

            pending_mcq_sessions[session_id] = {
                "candidate_name": name,
                "email": email,
                "role_key": role_key,
                "role_label": role_label,
                "round_key": round_key,
                "round_label": round_label,
                "batch_id": batch_id,
                "domain": normalized_domain,
            }

            tests[round_key] = {
                "session_id": session_id,
                "label": round_label,
                "url": test_url,
                "type": "mcq",
            }

        MCQ_SESSION_REGISTRY.update(pending_mcq_sessions)
        CODING_SESSION_REGISTRY.update(pending_coding_sessions)

        add_generated_test(
            {
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
            }
        )

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
        failed_preview = ", ".join(item["email"] for item in email_failures[:3])
        suffix = "" if len(email_failures) <= 3 else ", ..."
        failure_reason = email_failures[0].get("reason", "Unknown error")
        flash(
            f"Email sending failed for {len(email_failures)} candidate(s): "
            f"{failed_preview}{suffix}. {failure_reason}",
            "warning",
        )
    return redirect(url_for("tests.generated_tests"))
