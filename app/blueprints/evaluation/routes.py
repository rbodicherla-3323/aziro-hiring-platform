# filepath: d:\Projects\aziro-hiring-platform\app\blueprints\evaluation\routes.py
"""
Evaluation page — scoped to current user's today session candidates.
"""
from flask import render_template, request, session

from . import evaluation_bp
from app.utils.auth_decorator import login_required
from app.services.generated_tests_store import get_tests_for_user_today
from app.services.evaluation_aggregator import EvaluationAggregator
from app.services.evaluation_service import EvaluationService, ROUND_PASS_PERCENTAGE, DEFAULT_PASS_PERCENTAGE
from app.services.proctoring_summary import build_proctoring_summary_by_email, blank_proctoring_summary
from app.services import db_service
from app.services.plagiarism_service import (
    build_plagiarism_summary_by_candidates,
    blank_plagiarism_summary,
)


def _session_scope_by_email(test_entries):
    scope = {}
    for entry in test_entries or []:
        email_key = str((entry or {}).get("email", "")).strip().lower()
        if not email_key:
            continue
        # test_entries are expected in latest-first order; keep only the latest row per email
        if email_key in scope:
            continue
        scope[email_key] = set()
        tests_map = (entry or {}).get("tests", {}) or {}
        if not isinstance(tests_map, dict):
            continue
        for test_meta in tests_map.values():
            session_id = str((test_meta or {}).get("session_id", "")).strip().lower()
            if session_id:
                scope[email_key].add(session_id)
    return scope


@evaluation_bp.route("/evaluation", methods=["GET", "POST"])
@login_required
def evaluation():
    user = session.get("user", {})
    user_email = user.get("email", "dev@aziro.com")

    # Get recent candidates for this user (retention window)
    user_tests = get_tests_for_user_today(user_email)
    user_emails = {
        str((t or {}).get("email", "")).strip().lower()
        for t in user_tests
        if str((t or {}).get("email", "")).strip()
    }
    proctoring_scope = _session_scope_by_email(user_tests)

    # Get all evaluated candidates
    all_candidates = EvaluationAggregator.get_candidates()

    # Filter to only this user's today session candidates
    candidates = [
        c for c in all_candidates
        if str(c.get("email", "")).strip().lower() in user_emails
    ]

    # Handle POST: filter to selected candidates
    selected_emails = []
    filtered_candidates = []

    if request.method == "POST":
        selected_emails = request.form.getlist("candidates")
        selected_email_keys = {
            str(email or "").strip().lower()
            for email in selected_emails
            if str(email or "").strip()
        }
        filtered_candidates = [
            c for c in candidates
            if str(c.get("email", "")).strip().lower() in selected_email_keys
        ]
        filtered_email_keys = {
            str((c or {}).get("email", "")).strip().lower()
            for c in filtered_candidates
            if str((c or {}).get("email", "")).strip()
        }
        scoped_session_ids = {}
        for candidate in filtered_candidates:
            email_key = str((candidate or {}).get("email", "")).strip().lower()
            if not email_key:
                continue
            session_ids = set()
            attempted_rounds = int(((candidate.get("summary") or {}).get("attempted_rounds") or 0))
            if attempted_rounds > 0:
                role_key = str((candidate or {}).get("role_key", "")).strip()
                batch_id = str((candidate or {}).get("batch_id", "")).strip()
                try:
                    test_session_id = db_service.get_latest_test_session_id_for_candidate(
                        email_key,
                        created_by=user_email,
                        role_key=role_key,
                        batch_id=batch_id,
                    )
                    if test_session_id:
                        session_ids.update(
                            db_service.get_round_session_uuids_for_test_session(
                                test_session_id,
                                attempted_only=True,
                            )
                        )
                except Exception:
                    test_session_id = None
                if not session_ids:
                    session_ids.update(proctoring_scope.get(email_key, set()))
            scoped_session_ids[email_key] = session_ids
        summaries_by_email = build_proctoring_summary_by_email(
            filtered_email_keys,
            session_ids_by_email=scoped_session_ids,
        )
        plagiarism_by_email = build_plagiarism_summary_by_candidates(filtered_candidates)
        for candidate in filtered_candidates:
            email_key = str(candidate.get("email", "")).strip().lower()
            attempted_rounds = int(((candidate.get("summary") or {}).get("attempted_rounds") or 0))
            if attempted_rounds <= 0:
                candidate["proctoring_summary"] = blank_proctoring_summary()
            else:
                candidate["proctoring_summary"] = summaries_by_email.get(email_key, blank_proctoring_summary())
            candidate["plagiarism_summary"] = plagiarism_by_email.get(email_key, blank_plagiarism_summary())

    return render_template(
        "evaluation.html",
        candidates=candidates,
        selected_emails=selected_emails,
        filtered_candidates=filtered_candidates,
        pass_thresholds=ROUND_PASS_PERCENTAGE,
        default_threshold=DEFAULT_PASS_PERCENTAGE,
    )
