# filepath: d:\Projects\aziro-hiring-platform\app\blueprints\evaluation\routes.py
"""
Evaluation page — scoped to current user's today session candidates.
"""
from flask import render_template, request, session

from . import evaluation_bp
from app.utils.auth_decorator import login_required
from app.services.candidate_scope import get_candidate_key
from app.services.generated_tests_store import get_tests_for_user_today
from app.services.evaluation_aggregator import EvaluationAggregator
from app.services.evaluation_service import EvaluationService, ROUND_PASS_PERCENTAGE, DEFAULT_PASS_PERCENTAGE
from app.services.proctoring_summary import build_proctoring_summary_by_email, blank_proctoring_summary
from app.services import db_service
from app.services.plagiarism_service import (
    build_plagiarism_summary_by_candidates,
    blank_plagiarism_summary,
)


def _session_scope_by_candidate_key(test_entries):
    scope = {}
    for entry in test_entries or []:
        candidate_key = get_candidate_key(
            {
                "email": (entry or {}).get("email", ""),
                "role_key": (entry or {}).get("role_key", ""),
                "role": (entry or {}).get("role", ""),
                "batch_id": (entry or {}).get("batch_id", ""),
            }
        )
        if not candidate_key:
            continue
        if candidate_key in scope:
            continue
        scope[candidate_key] = set()
        tests_map = (entry or {}).get("tests", {}) or {}
        if not isinstance(tests_map, dict):
            continue
        for test_meta in tests_map.values():
            session_id = str((test_meta or {}).get("session_id", "")).strip().lower()
            if session_id:
                scope[candidate_key].add(session_id)
    return scope


@evaluation_bp.route("/evaluation", methods=["GET", "POST"])
@login_required
def evaluation():
    user = session.get("user", {})
    user_email = user.get("email", "dev@aziro.com")

    # Get recent candidates for this user (retention window)
    user_tests = get_tests_for_user_today(user_email)
    user_candidate_keys = {
        get_candidate_key(
            {
                "email": (t or {}).get("email", ""),
                "role_key": (t or {}).get("role_key", ""),
                "role": (t or {}).get("role", ""),
                "batch_id": (t or {}).get("batch_id", ""),
            }
        )
        for t in user_tests
        if get_candidate_key(
            {
                "email": (t or {}).get("email", ""),
                "role_key": (t or {}).get("role_key", ""),
                "role": (t or {}).get("role", ""),
                "batch_id": (t or {}).get("batch_id", ""),
            }
        )
    }
    proctoring_scope = _session_scope_by_candidate_key(user_tests)

    # Get all evaluated candidates
    all_candidates = EvaluationAggregator.get_candidates()

    # Filter to only this user's today session candidates
    candidates = [
        c for c in all_candidates
        if str(c.get("candidate_key", "")).strip() in user_candidate_keys
    ]

    # Handle POST: filter to selected candidates
    selected_candidate_keys = []
    filtered_candidates = []

    if request.method == "POST":
        selected_candidate_keys = request.form.getlist("candidates")
        selected_key_set = {
            str(candidate_key or "").strip()
            for candidate_key in selected_candidate_keys
            if str(candidate_key or "").strip()
        }
        filtered_candidates = [
            c for c in candidates
            if str(c.get("candidate_key", "")).strip() in selected_key_set
        ]
        for candidate in filtered_candidates:
            email_key = str((candidate or {}).get("email", "")).strip().lower()
            session_ids = set()
            attempted_rounds = int(((candidate.get("summary") or {}).get("attempted_rounds") or 0))
            if attempted_rounds > 0:
                test_session_id = candidate.get("test_session_id")
                role_key = str((candidate or {}).get("role_key", "")).strip()
                batch_id = str((candidate or {}).get("batch_id", "")).strip()
                if not test_session_id:
                    try:
                        test_session_id = db_service.get_latest_test_session_id_for_candidate(
                            email_key,
                            created_by=user_email,
                            role_key=role_key,
                            batch_id=batch_id,
                        )
                    except Exception:
                        test_session_id = None
                if test_session_id:
                    try:
                        session_ids.update(
                            db_service.get_round_session_uuids_for_test_session(
                                test_session_id,
                                attempted_only=True,
                            )
                        )
                    except Exception:
                        pass
                if not session_ids:
                    session_ids.update(
                        proctoring_scope.get(str((candidate or {}).get("candidate_key", "")).strip(), set())
                    )
        for candidate in filtered_candidates:
            email_key = str(candidate.get("email", "")).strip().lower()
            attempted_rounds = int(((candidate.get("summary") or {}).get("attempted_rounds") or 0))
            if attempted_rounds <= 0:
                candidate["proctoring_summary"] = blank_proctoring_summary()
            else:
                session_ids = set()
                test_session_id = candidate.get("test_session_id")
                if test_session_id:
                    try:
                        session_ids.update(
                            db_service.get_round_session_uuids_for_test_session(
                                test_session_id,
                                attempted_only=True,
                            )
                        )
                    except Exception:
                        pass
                if not session_ids:
                    session_ids.update(
                        proctoring_scope.get(str((candidate or {}).get("candidate_key", "")).strip(), set())
                    )
                summaries_by_email = build_proctoring_summary_by_email(
                    {email_key},
                    session_ids_by_email={email_key: session_ids},
                )
                candidate["proctoring_summary"] = summaries_by_email.get(email_key, blank_proctoring_summary())
            candidate["plagiarism_summary"] = build_plagiarism_summary_by_candidates([candidate]).get(
                email_key,
                blank_plagiarism_summary(),
            )

    return render_template(
        "evaluation.html",
        candidates=candidates,
        selected_candidate_keys=selected_candidate_keys,
        filtered_candidates=filtered_candidates,
        pass_thresholds=ROUND_PASS_PERCENTAGE,
        default_threshold=DEFAULT_PASS_PERCENTAGE,
    )
