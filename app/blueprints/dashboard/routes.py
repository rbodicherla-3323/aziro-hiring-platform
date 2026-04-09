# filepath: d:\Projects\aziro-hiring-platform\app\blueprints\dashboard\routes.py
"""
Dashboard & Test Creation routes.
"""
import os
import uuid
from datetime import datetime, timezone, timedelta

from flask import render_template, request, redirect, url_for, session, flash, current_app

from . import dashboard_bp
from app.utils.auth_decorator import login_required
from app.utils.role_normalizer import normalize_role, ROLE_NAME_TO_KEY
from app.utils.role_round_mapping import ROLE_ROUND_MAPPING, ROLE_CODING_LANGUAGE
from app.utils.round_display_mapping import ROUND_DISPLAY_MAPPING
from app.utils.email_validator import normalize_email, validate_email
from app.utils.round_question_mapping import DOMAIN_QUESTION_FILES

from app.services.generated_tests_store import add_generated_test
from app.services.email_service import send_candidate_test_links_email
from app.services.user_token_store import (
    get_valid_graph_delegated_token,
    get_valid_graph_delegated_token_from_session,
)
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
from app.services.question_bank.validator import QuestionBankValidationError

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


def _resolve_date_range(filter_type: str, specific_date: str = "", offset: int = 0):
    now = datetime.now(timezone.utc)
    offset = int(offset or 0)
    # Future windows are not allowed for dashboard stats navigation.
    if offset > 0:
        offset = 0
    if filter_type == "today":
        start = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=offset)
        end = start + timedelta(days=1)
        return start, end
    if filter_type == "24h":
        end = now + timedelta(hours=24 * offset)
        return end - timedelta(hours=24), end
    if filter_type == "28d":
        end = now + timedelta(days=28 * offset)
        return end - timedelta(days=28), end
    if filter_type == "2d":
        end = now + timedelta(days=2 * offset)
        return end - timedelta(days=2), end
    if filter_type == "7d":
        end = now + timedelta(days=7 * offset)
        return end - timedelta(days=7), end
    if filter_type == "date" and specific_date:
        try:
            d = datetime.strptime(specific_date, "%Y-%m-%d")
            start = d.replace(tzinfo=timezone.utc) + timedelta(days=offset)
            end = start + timedelta(days=1)
            return start, end
        except ValueError:
            return None, None
    return None, None


def _percentage_delta(current: int | float, previous: int | float) -> float:
    current = float(current or 0)
    previous = float(previous or 0)
    if previous <= 0:
        return 100.0 if current > 0 else 0.0
    return ((current - previous) / previous) * 100.0


def _trend_payload(current: int | float, previous: int | float) -> dict:
    raw = _percentage_delta(current, previous)
    return {
        "raw": round(raw, 1),
        "pct": round(abs(raw), 1),
        "is_up": raw >= 0,
    }


def _safe_dashboard_value(loader, default, label: str):
    try:
        return loader()
    except Exception:
        current_app.logger.exception("Dashboard fallback used for %s", label)
        return default


def _empty_stats() -> dict:
    return {
        "total_candidates": 0,
        "total_tests": 0,
        "completed": 0,
        "pending": 0,
    }


def _empty_monthly_series(points: int) -> list[dict]:
    points = max(2, int(points or 6))
    return [
        {
            "key": f"fallback-{idx}",
            "label": "",
            "tests": 0,
            "completed": 0,
        }
        for idx in range(points)
    ]


def _persist_test_link_record(
    *,
    meta: dict,
    test_type: str,
    created_by: str,
    created_at: datetime,
    expires_at: datetime,
) -> None:
    try:
        db_service.save_test_link(
            meta=meta,
            test_type=test_type,
            created_by=created_by,
            created_at=created_at,
            expires_at=expires_at,
        )
    except Exception:
        current_app.logger.exception(
            "Failed to persist test link session_id=%s type=%s candidate=%s",
            str((meta or {}).get("session_id", "") or "").strip(),
            str(test_type or "").strip().lower(),
            str((meta or {}).get("email", "") or "").strip().lower(),
        )


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
    try:
        date_offset = int(request.args.get("offset", "0"))
    except (TypeError, ValueError):
        date_offset = 0
    if date_offset > 0:
        date_offset = 0
    if specific_date:
        date_filter = "date"

    # Today's stats scoped to current user.
    today_start, today_end = _resolve_date_range("today")
    today_stats = _safe_dashboard_value(
        lambda: db_service.get_test_link_stats(
            since=today_start,
            until=today_end,
            created_by=user_email,
        ),
        _empty_stats(),
        "today_stats",
    )

    # Kept for template compatibility.
    my_today_stats = today_stats
    active_sessions = _safe_dashboard_value(
        lambda: db_service.get_active_test_session_count(
            created_by=user_email,
            since=today_start,
            until=today_end,
        ),
        0,
        "active_sessions",
    )

    # My stats with date filter
    range_start, range_end = _resolve_date_range(date_filter, specific_date, date_offset)
    overall_stats = _safe_dashboard_value(
        lambda: db_service.get_test_link_stats(
            since=range_start,
            until=range_end,
        ),
        _empty_stats(),
        "overall_stats",
    )
    my_stats = _safe_dashboard_value(
        lambda: db_service.get_test_link_stats(
            since=range_start,
            until=range_end,
            created_by=user_email,
        ),
        _empty_stats(),
        "my_stats",
    )

    # Previous-period stats (same duration) for real trend percentages.
    prev_stats = {"total_candidates": 0, "total_tests": 0, "completed": 0, "pending": 0}
    if range_start and range_end and range_end > range_start:
        window = range_end - range_start
        prev_stats = _safe_dashboard_value(
            lambda: db_service.get_test_link_stats(
                since=range_start - window,
                until=range_start,
                created_by=user_email,
            ),
            _empty_stats(),
            "prev_stats",
        )

    tests_trend = _trend_payload(my_stats.get("total_tests", 0), prev_stats.get("total_tests", 0))
    pending_trend = _trend_payload(my_stats.get("pending", 0), prev_stats.get("pending", 0))
    completed_trend = _trend_payload(my_stats.get("completed", 0), prev_stats.get("completed", 0))

    def _build_chart_payload(series: list[dict]) -> dict:
        series_count = len(series)
        chart_top = 32.0
        chart_bottom = 184.0
        chart_left = 40.0
        chart_right = 338.0
        chart_height = chart_bottom - chart_top
        chart_width = chart_right - chart_left
        chart_max = max(
            1,
            max((pt.get("tests", 0) for pt in series), default=0),
            max((pt.get("completed", 0) for pt in series), default=0),
        )

        points = []
        for idx, point in enumerate(series):
            x = chart_left
            if series_count > 1:
                x = chart_left + (chart_width * idx / (series_count - 1))
            tests_value = int(point.get("tests", 0) or 0)
            completed_value = int(point.get("completed", 0) or 0)
            y_tests = chart_bottom - (tests_value / chart_max) * chart_height
            y_completed = chart_bottom - (completed_value / chart_max) * chart_height
            points.append(
                {
                    "label": point.get("label", ""),
                    "x": round(x, 1),
                    "tests": tests_value,
                    "completed": completed_value,
                    "y_tests": round(y_tests, 1),
                    "y_completed": round(y_completed, 1),
                }
            )

        tests_polyline = " ".join(f"{p['x']},{p['y_tests']}" for p in points)
        completed_polyline = " ".join(f"{p['x']},{p['y_completed']}" for p in points)

        y_tick_values = [chart_max, chart_max * 0.75, chart_max * 0.5, chart_max * 0.25, 0]
        y_ticks = []
        for tick_value in y_tick_values:
            y_pos = chart_bottom
            if chart_max > 0:
                y_pos = chart_bottom - (tick_value / chart_max) * chart_height
            y_ticks.append(
                {
                    "value": int(round(tick_value)),
                    "y": round(y_pos, 1),
                }
            )

        latest = points[-1] if points else {"tests": 0, "completed": 0}
        previous = points[-2] if len(points) > 1 else {"tests": 0, "completed": 0}

        return {
            "points": points,
            "y_ticks": y_ticks,
            "tests_polyline": tests_polyline,
            "completed_polyline": completed_polyline,
            "latest": latest,
            "tests_trend": _trend_payload(latest.get("tests", 0), previous.get("tests", 0)),
            "completed_trend": _trend_payload(latest.get("completed", 0), previous.get("completed", 0)),
        }

    # Member (current HR) monthly chart.
    performance_series = _safe_dashboard_value(
        lambda: db_service.get_test_link_monthly_series(
            points=6,
            created_by=user_email,
        ),
        _empty_monthly_series(6),
        "my_monthly_series",
    )
    my_chart = _build_chart_payload(performance_series)

    # Organization-wide monthly chart.
    overall_performance_series = _safe_dashboard_value(
        lambda: db_service.get_test_link_monthly_series(points=8),
        _empty_monthly_series(8),
        "overall_monthly_series",
    )
    overall_chart = _build_chart_payload(overall_performance_series)

    chart_points = my_chart["points"]
    chart_y_ticks = my_chart["y_ticks"]
    chart_tests_polyline = my_chart["tests_polyline"]
    chart_completed_polyline = my_chart["completed_polyline"]
    latest_point = my_chart["latest"]
    chart_tests_trend = my_chart["tests_trend"]
    chart_completed_trend = my_chart["completed_trend"]

    return render_template(
        "dashboard.html",
        user_name=user_name,
        user_email=user_email,
        today_stats=today_stats,
        my_today_stats=my_today_stats,
        overall_stats=overall_stats,
        my_stats=my_stats,
        prev_stats=prev_stats,
        tests_trend=tests_trend,
        pending_trend=pending_trend,
        completed_trend=completed_trend,
        date_filter=date_filter,
        specific_date=specific_date,
        date_offset=date_offset,
        performance_series=performance_series,
        chart_points=chart_points,
        chart_y_ticks=chart_y_ticks,
        chart_tests_polyline=chart_tests_polyline,
        chart_completed_polyline=chart_completed_polyline,
        chart_latest=latest_point,
        chart_tests_trend=chart_tests_trend,
        chart_completed_trend=chart_completed_trend,
        overall_chart_series=overall_performance_series,
        overall_chart_points=overall_chart["points"],
        overall_chart_y_ticks=overall_chart["y_ticks"],
        overall_chart_tests_polyline=overall_chart["tests_polyline"],
        overall_chart_completed_polyline=overall_chart["completed_polyline"],
        overall_chart_latest=overall_chart["latest"],
        overall_chart_tests_trend=overall_chart["tests_trend"],
        overall_chart_completed_trend=overall_chart["completed_trend"],
        active_sessions=active_sessions,
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
    batch_id = f"batch_{uuid.uuid4().hex[:8]}"

    auto_send_enabled = str(os.getenv("AUTO_SEND_TEST_EMAILS", "true")).strip().lower() not in {
        "0", "false", "no"
    }
    email_provider = str(os.getenv("EMAIL_PROVIDER", "smtp")).strip().lower()
    delegated_access_token = get_valid_graph_delegated_token(user_email)
    if not delegated_access_token:
        delegated_access_token = get_valid_graph_delegated_token_from_session(
            session.get("oauth", {}),
        )
    if delegated_access_token and not auto_send_enabled:
        # Outlook login should still auto-send even if env toggle is off.
        auto_send_enabled = True

    auto_sent = 0
    auto_failures = []
    auto_send_blocked = auto_send_enabled and email_provider == "graph_delegated" and not delegated_access_token

    for i in range(len(names)):
        name = names[i].strip()
        email = normalize_email(emails[i])
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

        email_ok, email_error = validate_email(email)
        if not email_ok:
            flash(f"{email_error} Candidate '{name}' was skipped.", "warning")
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
            try:
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
            except (FileNotFoundError, ValueError) as exc:
                current_app.logger.exception(
                    "Failed to load question bank for role=%s round=%s domain=%s",
                    role_key,
                    round_key,
                    domain,
                )
                flash(
                    f"Question bank failed to load for role '{role_label}' round '{round_key}'. "
                    f"Candidate '{name}' was skipped.",
                    "danger",
                )
                candidate_generation_failed = True
                break
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
                except (QuestionSelectionError, QuestionBankValidationError, ValueError) as exc:
                    current_app.logger.exception(
                        "Enterprise MCQ freeze failed for role=%s round=%s domain=%s",
                        role_key,
                        round_key,
                        domain,
                    )
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
            _persist_test_link_record(
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
            _persist_test_link_record(
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
            _persist_test_link_record(
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

        if auto_send_enabled and tests and not auto_send_blocked:
            sent, error = send_candidate_test_links_email(
                candidate_name=name,
                candidate_email=email,
                role_label=role_label,
                tests=tests,
                delegated_access_token=delegated_access_token,
                delegated_sender_email=user_email,
            )
            if sent:
                auto_sent += 1
            else:
                auto_failures.append({"email": email, "reason": error or "Send failed."})

    flash("Test links generated successfully!", "success")
    if auto_send_enabled:
        if auto_sent:
            flash(f"Auto emails sent to {auto_sent} candidate(s) from {user_email}.", "success")
        if auto_send_blocked:
            flash(
                "Auto email sending is enabled but your Microsoft delegated token is missing or expired. "
                "Please sign in again to send from your mailbox.",
                "warning",
            )
        if auto_failures:
            flash(f"{len(auto_failures)} email(s) failed to send. Check Generated Tests for retry.", "warning")
    return redirect(url_for("tests.generated_tests"))


@dashboard_bp.route("/api/dashboard-lifetime")
@login_required
def dashboard_lifetime():
    from flask import jsonify
    try:
        total = db_service.get_candidate_count()
    except Exception:
        total = 0
    return jsonify({"total_interviews": total})



