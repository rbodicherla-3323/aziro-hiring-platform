# filepath: d:\Projects\aziro-hiring-platform\app\blueprints\reports\routes.py
"""
Reports page - recent session candidates + historical report search.
"""
from datetime import datetime, timezone, timedelta
from io import BytesIO
from math import ceil
from flask import Blueprint, render_template, request, session, jsonify, send_file, abort, current_app

from app.utils.auth_decorator import login_required
from app.services.candidate_scope import get_candidate_key, matches_candidate_scope
from app.services.generated_tests_store import get_tests_for_user_in_range, SESSION_RETENTION_DAYS
from app.services.evaluation_aggregator import EvaluationAggregator
from app.services import db_service
from app.services.evaluation_service import EvaluationService
from app.services.proctoring_summary import build_proctoring_summary_by_email, blank_proctoring_summary
from app.services.plagiarism_service import (
    build_plagiarism_summary_by_candidates,
    blank_plagiarism_summary,
)
from app.services.pdf_service import generate_candidate_pdf, generate_consolidated_summary_pdf, REPORTS_DIR

reports_bp = Blueprint("reports", __name__)
_VALID_PERIOD_FILTERS = {"today", "24h", "7d", "28d", "date"}
_MAX_CONSOLIDATED_SUMMARY_CANDIDATES = 60


def _get_db_service():
    try:
        from app.services import db_service
        return db_service
    except Exception:
        return None


def _get_pdf_service():
    try:
        from app.services.pdf_service import generate_candidate_pdf, REPORTS_DIR
        return generate_candidate_pdf, REPORTS_DIR
    except Exception:
        return None, None


def _resolve_date_range(filter_type: str, specific_date: str = "", offset: int = 0):
    now = datetime.now(timezone.utc)
    offset = int(offset or 0)
    if offset > 0:
        offset = 0

    if filter_type == "today":
        start = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=offset)
        return start, start + timedelta(days=1)
    if filter_type == "24h":
        end = now + timedelta(hours=24 * offset)
        return end - timedelta(hours=24), end
    if filter_type == "7d":
        end = now + timedelta(days=7 * offset)
        return end - timedelta(days=7), end
    if filter_type == "28d":
        end = now + timedelta(days=28 * offset)
        return end - timedelta(days=28), end
    if filter_type == "date" and specific_date:
        try:
            d = datetime.strptime(specific_date, "%Y-%m-%d")
        except ValueError:
            return None, None
        start = d.replace(tzinfo=timezone.utc) + timedelta(days=offset)
        return start, start + timedelta(days=1)
    return None, None


def _period_label(filter_type: str, specific_date: str = "") -> str:
    if filter_type == "24h":
        return "Last 24 Hours"
    if filter_type == "7d":
        return "Last 7 Days"
    if filter_type == "28d":
        return "Last 28 Days"
    if filter_type == "date" and specific_date:
        return specific_date
    return "Today"

def _parse_created_at(value):
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            return None
    else:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _created_sort_key(item):
    dt = _parse_created_at(item.get("created_at", ""))
    return dt or datetime.min.replace(tzinfo=timezone.utc)


def _normalize_email(value: str) -> str:
    return str(value or "").strip().lower()


def _attach_report_info(candidate: dict):
    email_key = _normalize_email(candidate.get("email", ""))
    if not email_key:
        candidate["has_report"] = False
        candidate["report_filename"] = ""
        candidate["report_id"] = None
        return
    try:
        info = db_service.get_latest_report_for_email(
            email_key,
            test_session_id=candidate.get("test_session_id"),
            role_key=str(candidate.get("role_key", "") or "").strip(),
            batch_id=str(candidate.get("batch_id", "") or "").strip(),
        )
    except Exception as exc:
        current_app.logger.exception("Report lookup failed for %s: %s", email_key, exc)
        info = None
    candidate["has_report"] = bool(info)
    candidate["report_filename"] = info.get("filename") if info else ""
    candidate["report_id"] = info.get("id") if info else None


def _extract_test_session_ids(test_entry: dict) -> set[str]:
    session_ids = set()
    tests_map = (test_entry or {}).get("tests", {}) or {}
    if not isinstance(tests_map, dict):
        return session_ids

    for test_meta in tests_map.values():
        session_id = str((test_meta or {}).get("session_id", "")).strip().lower()
        if session_id:
            session_ids.add(session_id)

    return session_ids


def _session_scope_by_candidate_key(test_entries) -> dict[str, set[str]]:
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
        if not candidate_key or candidate_key in scope:
            continue
        scope[candidate_key] = set(_extract_test_session_ids(entry))
    return scope


def _attempted_rounds(candidate: dict) -> int:
    return int(((candidate or {}).get("summary") or {}).get("attempted_rounds") or 0)


def _collect_reports_scope(
    *,
    user_email: str,
    q: str = "",
    role_filter: str = "",
    date_filter: str = "today",
    specific_date: str = "",
    date_offset: int = 0,
):
    q = str(q or "").strip()
    role_filter = str(role_filter or "").strip()
    search_global_mode = bool(q)
    date_filter = str(date_filter or "today").strip().lower()
    specific_date = str(specific_date or "").strip()
    try:
        date_offset = int(date_offset or 0)
    except (TypeError, ValueError):
        date_offset = 0
    if date_offset > 0:
        date_offset = 0
    if specific_date:
        date_filter = "date"
    if date_filter not in _VALID_PERIOD_FILTERS:
        date_filter = "today"
    if date_filter != "date":
        specific_date = ""

    range_start, range_end = _resolve_date_range(date_filter, specific_date, date_offset)
    if not range_start or not range_end:
        date_filter = "today"
        specific_date = ""
        date_offset = 0
        range_start, range_end = _resolve_date_range("today")
    period_label = _period_label(date_filter, specific_date)

    user_tests = get_tests_for_user_in_range(user_email, range_start)
    user_tests = [
        t
        for t in user_tests
        if (dt := _parse_created_at(t.get("created_at", ""))) is not None
        and dt >= range_start
        and dt < range_end
    ]

    user_tests_sorted = sorted(user_tests, key=_created_sort_key, reverse=True)
    proctoring_scope = _session_scope_by_candidate_key(user_tests_sorted)
    tests_by_candidate_key = {}
    for t in user_tests_sorted:
        candidate_key = get_candidate_key(
            {
                "email": t.get("email", ""),
                "role_key": t.get("role_key", ""),
                "role": t.get("role", ""),
                "batch_id": t.get("batch_id", ""),
            }
        )
        if not candidate_key:
            continue
        if candidate_key not in tests_by_candidate_key:
            tests_by_candidate_key[candidate_key] = t
    user_candidate_keys = set(tests_by_candidate_key.keys())

    all_candidates = EvaluationAggregator.get_candidates()
    all_candidates_by_key = {}
    for c in all_candidates:
        candidate_key = str((c or {}).get("candidate_key", "")).strip() or get_candidate_key(c)
        if not candidate_key or candidate_key in all_candidates_by_key:
            continue
        if candidate_key in tests_by_candidate_key and not c.get("created_at"):
            c["created_at"] = tests_by_candidate_key[candidate_key].get("created_at", "")
        all_candidates_by_key[candidate_key] = c

    session_candidates = []
    for candidate_key in user_candidate_keys:
        candidate = all_candidates_by_key.get(candidate_key)
        if not candidate:
            continue
        if candidate_key in tests_by_candidate_key:
            candidate["created_at"] = tests_by_candidate_key[candidate_key].get("created_at", "")
        session_candidates.append(candidate)

    evaluated_candidate_keys = {
        str((c or {}).get("candidate_key", "")).strip() or get_candidate_key(c)
        for c in session_candidates
        if str((c or {}).get("candidate_key", "")).strip() or get_candidate_key(c)
    }
    for t in user_tests_sorted:
        candidate_key = get_candidate_key(
            {
                "email": t.get("email", ""),
                "role_key": t.get("role_key", ""),
                "role": t.get("role", ""),
                "batch_id": t.get("batch_id", ""),
            }
        )
        if not candidate_key or candidate_key in evaluated_candidate_keys:
            continue
        session_candidates.append({
            "candidate_key": candidate_key,
            "name": t["name"],
            "email": t["email"],
            "role": t.get("role", ""),
            "role_key": t.get("role_key", ""),
            "batch_id": t.get("batch_id", ""),
            "created_at": t.get("created_at", ""),
            "rounds": {},
            "results": [],
            "summary": {
                "total_rounds": len(t.get("tests", {})),
                "attempted_rounds": 0,
                "passed_rounds": 0,
                "failed_rounds": 0,
            },
        })
        evaluated_candidate_keys.add(candidate_key)
        all_candidates_by_key[candidate_key] = session_candidates[-1]

    if search_global_mode:
        db_role_filter = role_filter if role_filter.lower() not in {"all", "all roles"} else ""
        try:
            db_matches = db_service.search_candidates(q, db_role_filter)
        except Exception as exc:
            current_app.logger.exception("DB candidate search failed: %s", exc)
            db_matches = []
        try:
            report_matches = db_service.search_candidates_with_reports(q, db_role_filter)
        except Exception as exc:
            current_app.logger.exception("DB report search failed: %s", exc)
            report_matches = []

        for row in [*db_matches, *report_matches]:
            candidate_key = get_candidate_key(
                {
                    "email": row.get("email", ""),
                    "role_key": row.get("role_key", ""),
                    "role": row.get("role", ""),
                    "batch_id": row.get("batch_id", ""),
                }
            )
            if not candidate_key:
                continue
            existing = all_candidates_by_key.get(candidate_key)
            if existing is not None:
                if not existing.get("role"):
                    existing["role"] = str(row.get("role", "")).strip()
                if not existing.get("role_key"):
                    existing["role_key"] = str(row.get("role_key", "")).strip()
                if not existing.get("batch_id"):
                    existing["batch_id"] = str(row.get("batch_id", "")).strip()
                if not existing.get("name"):
                    existing["name"] = str(row.get("name", "")).strip() or _normalize_email(row.get("email", ""))
                if not existing.get("created_at"):
                    existing["created_at"] = str(row.get("created_at", "")).strip()
                if not existing.get("test_session_id") and row.get("test_session_id"):
                    existing["test_session_id"] = row.get("test_session_id")
                if row.get("report_filename"):
                    existing["report_filename"] = str(row.get("report_filename", "")).strip()
                    existing["has_report"] = True
                continue

            email_key = _normalize_email(row.get("email", ""))
            candidate_row = {
                "candidate_key": candidate_key,
                "name": str(row.get("name", "")).strip() or email_key,
                "email": email_key,
                "role": str(row.get("role", "")).strip(),
                "role_key": str(row.get("role_key", "")).strip(),
                "batch_id": str(row.get("batch_id", "")).strip(),
                "created_at": str(row.get("created_at", "")).strip(),
                "test_session_id": row.get("test_session_id"),
                "rounds": {},
                "summary": {
                    "total_rounds": 0,
                    "attempted_rounds": 0,
                    "passed_rounds": 0,
                    "failed_rounds": 0,
                    "overall_percentage": 0,
                    "overall_verdict": "Pending",
                },
            }
            if row.get("report_filename"):
                candidate_row["report_filename"] = str(row.get("report_filename", "")).strip()
                candidate_row["has_report"] = True
            all_candidates_by_key[candidate_key] = candidate_row

    session_candidates.sort(key=_created_sort_key, reverse=True)
    all_candidates_pool = list(all_candidates_by_key.values())
    all_candidates_pool.sort(key=_created_sort_key, reverse=True)
    base_candidates = list(all_candidates_pool) if search_global_mode else list(session_candidates)
    base_total_candidates = len(base_candidates)

    role_options = sorted(
        {
            str(c.get("role", "")).strip()
            for c in base_candidates
            if str(c.get("role", "")).strip()
        },
        key=lambda value: value.lower(),
    )
    session_total_candidates = len(session_candidates)

    filtered_candidates = list(base_candidates)
    if role_filter and role_filter.lower() not in {"all", "all roles"}:
        rf = role_filter.lower()
        filtered_candidates = [
            c for c in filtered_candidates
            if str(c.get("role", "")).strip().lower() == rf
        ]
    if q:
        q_lower = q.lower()
        filtered_candidates = [
            c for c in filtered_candidates
            if q_lower in c.get("name", "").lower()
            or q_lower in c.get("email", "").lower()
            or q_lower in c.get("role", "").lower()
        ]

    return {
        "filtered_candidates": filtered_candidates,
        "session_total_candidates": session_total_candidates,
        "base_total_candidates": base_total_candidates,
        "filtered_total_candidates": len(filtered_candidates),
        "role_options": role_options,
        "selected_role": role_filter or "All Roles",
        "search_query": q,
        "search_global_mode": search_global_mode,
        "date_filter": date_filter,
        "specific_date": specific_date,
        "date_offset": date_offset,
        "period_label": period_label,
        "range_start": range_start,
        "range_end": range_end,
        "proctoring_scope": proctoring_scope,
    }


def _candidate_summary_list_item(candidate: dict) -> dict:
    summary = candidate.get("summary", {}) or {}
    return {
        "candidate_key": str(candidate.get("candidate_key", "") or get_candidate_key(candidate)).strip(),
        "email": _normalize_email(candidate.get("email", "")),
        "name": str(candidate.get("name", "") or "").strip(),
        "role": str(candidate.get("role", "") or "").strip(),
        "role_key": str(candidate.get("role_key", "") or "").strip(),
        "batch_id": str(candidate.get("batch_id", "") or "").strip(),
        "test_session_id": candidate.get("test_session_id"),
        "created_at": str(candidate.get("created_at", "") or "").strip(),
        "overall_score": float(summary.get("overall_percentage", 0) or 0),
        "overall_verdict": str(summary.get("overall_verdict", "Pending") or "Pending"),
        "attempted_rounds": int(summary.get("attempted_rounds", 0) or 0),
        "total_rounds": int(summary.get("total_rounds", 0) or 0),
        "passed_rounds": int(summary.get("passed_rounds", 0) or 0),
        "failed_rounds": int(summary.get("failed_rounds", 0) or 0),
    }


def _build_batch_options(candidates: list[dict]) -> list[dict]:
    counts = {}
    for candidate in candidates:
        batch_id = str(candidate.get("batch_id", "") or "").strip()
        key = batch_id or "__none__"
        if key not in counts:
            counts[key] = {
                "value": batch_id,
                "label": batch_id or "No Batch",
                "count": 0,
            }
        counts[key]["count"] += 1

    def _sort_key(item: dict):
        is_empty = 1 if not item.get("value") else 0
        return (is_empty, str(item.get("label", "")).lower())

    return sorted(counts.values(), key=_sort_key)


@reports_bp.route("/reports")
@login_required
def reports():
    user = session.get("user", {})
    user_email = user.get("email", "dev@aziro.com")
    q = request.args.get("q", "").strip()
    role_filter = request.args.get("role", "").strip()
    date_filter = str(request.args.get("filter", "today") or "today").strip().lower()
    specific_date = str(request.args.get("date", "") or "").strip()
    try:
        date_offset = int(request.args.get("offset", "0"))
    except (TypeError, ValueError):
        date_offset = 0
    try:
        page = max(1, int(request.args.get("page", "1")))
    except (TypeError, ValueError):
        page = 1
    try:
        per_page = int(request.args.get("per_page", "8"))
    except (TypeError, ValueError):
        per_page = 8
    if per_page not in (5, 8, 10, 20, 50):
        per_page = 8

    scope = _collect_reports_scope(
        user_email=user_email,
        q=q,
        role_filter=role_filter,
        date_filter=date_filter,
        specific_date=specific_date,
        date_offset=date_offset,
    )
    filtered_candidates = scope["filtered_candidates"]
    filtered_total_candidates = scope["filtered_total_candidates"]
    range_start = scope["range_start"]
    range_end = scope["range_end"]
    proctoring_scope = scope["proctoring_scope"]
    total_pages = max(1, ceil(filtered_total_candidates / per_page)) if filtered_total_candidates else 1
    page = min(page, total_pages)
    start_idx = (page - 1) * per_page
    end_idx = start_idx + per_page
    paged_candidates = filtered_candidates[start_idx:end_idx]
    showing_from = start_idx + 1 if filtered_total_candidates else 0
    showing_to = start_idx + len(paged_candidates)
    for candidate in paged_candidates:
        _attach_report_info(candidate)
    for candidate in paged_candidates:
        email_key = str(candidate.get("email", "")).strip().lower()
        if _attempted_rounds(candidate) <= 0:
            candidate["proctoring_summary"] = blank_proctoring_summary()
        else:
            session_ids = set()
            test_session_id = candidate.get("test_session_id")
            if not test_session_id:
                role_key = str((candidate or {}).get("role_key", "")).strip()
                batch_id = str((candidate or {}).get("batch_id", "")).strip()
                try:
                    test_session_id = db_service.get_latest_test_session_id_for_candidate(
                        email_key,
                        created_by=user_email,
                        since=range_start,
                        until=range_end,
                        role_key=role_key,
                        batch_id=batch_id,
                    )
                except Exception as exc:
                    current_app.logger.exception(
                        "Failed to resolve scoped test session for %s: %s",
                        email_key,
                        exc,
                    )

                if not test_session_id:
                    try:
                        test_session_id = db_service.get_latest_test_session_id_for_candidate(
                            email_key,
                            role_key=role_key,
                            batch_id=batch_id,
                        )
                    except Exception as exc:
                        current_app.logger.exception(
                            "Fallback latest session lookup failed for %s: %s",
                            email_key,
                            exc,
                        )

            if test_session_id:
                candidate["test_session_id"] = test_session_id
                try:
                    session_ids.update(
                        db_service.get_round_session_uuids_for_test_session(
                            test_session_id,
                            attempted_only=True,
                        )
                    )
                except Exception as exc:
                    current_app.logger.exception(
                        "Failed to resolve round session UUIDs for %s (test_session_id=%s): %s",
                        email_key,
                        test_session_id,
                        exc,
                    )

            if not session_ids:
                session_ids.update(
                    proctoring_scope.get(str((candidate or {}).get("candidate_key", "")).strip(), set())
                )

            try:
                summaries_by_email = build_proctoring_summary_by_email(
                    {email_key},
                    session_ids_by_email={email_key: session_ids},
                )
            except Exception as exc:
                current_app.logger.exception("Failed to build proctoring summary for %s: %s", email_key, exc)
                summaries_by_email = {}
            candidate["proctoring_summary"] = summaries_by_email.get(email_key, blank_proctoring_summary())
        try:
            plagiarism_by_email = build_plagiarism_summary_by_candidates([candidate])
        except Exception as exc:
            current_app.logger.exception("Failed to build plagiarism summary for %s: %s", email_key, exc)
            plagiarism_by_email = {}
        candidate["plagiarism_summary"] = plagiarism_by_email.get(email_key, blank_plagiarism_summary())

    return render_template(
        "reports.html",
        session_candidates=paged_candidates,
        recent_days=SESSION_RETENTION_DAYS,
        session_total_candidates=scope["session_total_candidates"],
        base_total_candidates=scope["base_total_candidates"],
        search_global_mode=scope["search_global_mode"],
        filtered_total_candidates=filtered_total_candidates,
        role_options=scope["role_options"],
        selected_role=scope["selected_role"],
        search_query=scope["search_query"],
        page=page,
        per_page=per_page,
        total_pages=total_pages,
        showing_from=showing_from,
        showing_to=showing_to,
        date_filter=scope["date_filter"],
        specific_date=scope["specific_date"],
        date_offset=scope["date_offset"],
        period_label=scope["period_label"],
    )


@reports_bp.route("/reports/search")
@login_required
def search_reports():
    user = session.get("user", {})
    user_email = user.get("email", "dev@aziro.com")
    query = request.args.get("q", "").strip()
    if len(query) < 1:
        return jsonify({"candidates": []})

    results = []
    query_lower = query.lower()

    found_keys = set()

    # 1. Search DB (reports generated for any candidate - org-wide)
    try:
        db_results = db_service.search_candidates_with_reports(query)
        for r in db_results:
            candidate_key = get_candidate_key(
                {
                    "email": r.get("email", ""),
                    "role_key": r.get("role_key", ""),
                    "role": r.get("role", ""),
                    "batch_id": r.get("batch_id", ""),
                }
            )
            if candidate_key and candidate_key not in found_keys:
                results.append({
                    "name": r.get("name", ""),
                    "email": r.get("email", ""),
                    "role": r.get("role", "N/A"),
                    "role_key": r.get("role_key", ""),
                    "batch_id": r.get("batch_id", ""),
                    "candidate_key": candidate_key,
                    "test_session_id": r.get("test_session_id"),
                    "created_at": r.get("created_at", ""),
                    "source": "database",
                    "has_report": True,
                    "report_filename": r.get("report_filename", ""),
                })
                found_keys.add(candidate_key)
    except Exception:
        pass

    # 2. Search this user's recent candidates (fallback)
    since = datetime.now(timezone.utc) - timedelta(days=SESSION_RETENTION_DAYS)
    user_tests = get_tests_for_user_in_range(user_email, since)
    for t in user_tests:
        if (query_lower in t.get("name", "").lower()
            or query_lower in t.get("email", "").lower()
            or query_lower in t.get("role", "").lower()):
            candidate_key = get_candidate_key(
                {
                    "email": t.get("email", ""),
                    "role_key": t.get("role_key", ""),
                    "role": t.get("role", ""),
                    "batch_id": t.get("batch_id", ""),
                }
            )
            email_key = str(t.get("email", "")).strip().lower()
            if candidate_key and candidate_key not in found_keys:
                try:
                    info = db_service.get_latest_report_for_email(
                        email_key,
                        role_key=str(t.get("role_key", "") or "").strip(),
                        batch_id=str(t.get("batch_id", "") or "").strip(),
                    )
                except Exception:
                    info = None
                results.append({
                    "name": t.get("name", ""),
                    "email": t.get("email", ""),
                    "role": t.get("role", "N/A"),
                    "role_key": t.get("role_key", ""),
                    "batch_id": t.get("batch_id", ""),
                    "candidate_key": candidate_key,
                    "source": "session",
                    "has_report": bool(info),
                    "report_filename": info.get("filename") if info else "",
                })
                found_keys.add(candidate_key)

    def _normalize_for_search(value: str) -> str:
        raw = str(value or "").lower()
        cleaned = "".join(ch if ch.isalnum() or ch in "+.#@_-" else " " for ch in raw)
        return " ".join(cleaned.split())

    query_tokens = [tok for tok in _normalize_for_search(query).split(" ") if tok]

    def _score_candidate(item: dict, index: int):
        name = _normalize_for_search(item.get("name", ""))
        email = _normalize_for_search(item.get("email", ""))
        role = _normalize_for_search(item.get("role", ""))
        hay = " ".join(part for part in (name, email, role) if part).strip()
        if query_tokens and not all(tok in hay for tok in query_tokens):
            return (-1, index)

        score = 0
        for token in query_tokens:
            if email == token:
                score += 120
            if name == token:
                score += 90
            if role == token:
                score += 50
            if email.startswith(token):
                score += 40
            if name.startswith(token):
                score += 30
            if role.startswith(token):
                score += 18
            if f" {token}" in hay:
                score += 8
            if token in hay:
                score += 4
        if item.get("has_report"):
            score += 2
        return (score, index)

    scored = []
    for idx, item in enumerate(results):
        score, original_index = _score_candidate(item, idx)
        if score < 0:
            continue
        scored.append((score, original_index, item))
    scored.sort(key=lambda row: (-row[0], row[1]))

    ranked_results = [row[2] for row in scored[:60]]
    return jsonify({"candidates": ranked_results})


@reports_bp.route("/reports/consolidated/candidates")
@login_required
def list_consolidated_summary_candidates():
    user = session.get("user", {})
    user_email = user.get("email", "dev@aziro.com")

    scope = _collect_reports_scope(
        user_email=user_email,
        q=request.args.get("q", "").strip(),
        role_filter=request.args.get("role", "").strip(),
        date_filter=str(request.args.get("filter", "today") or "today").strip().lower(),
        specific_date=str(request.args.get("date", "") or "").strip(),
        date_offset=request.args.get("offset", "0"),
    )
    filtered_candidates = scope["filtered_candidates"]
    batch_options = _build_batch_options(filtered_candidates)

    return jsonify({
        "success": True,
        "scope": {
            "role": scope["selected_role"],
            "period_label": scope["period_label"],
            "search_global_mode": scope["search_global_mode"],
            "filtered_total_candidates": scope["filtered_total_candidates"],
        },
        "batch_options": batch_options,
        "candidates": [_candidate_summary_list_item(candidate) for candidate in filtered_candidates],
    })


@reports_bp.route("/reports/consolidated-summary", methods=["POST"])
@login_required
def generate_consolidated_summary():
    user = session.get("user", {})
    user_email = user.get("email", "dev@aziro.com")
    payload = request.get_json(silent=True) or {}

    scope = _collect_reports_scope(
        user_email=user_email,
        q=str(payload.get("q", "") or "").strip(),
        role_filter=str(payload.get("role", "") or "").strip(),
        date_filter=str(payload.get("filter", "today") or "today").strip().lower(),
        specific_date=str(payload.get("date", "") or "").strip(),
        date_offset=payload.get("offset", "0"),
    )
    filtered_candidates = scope["filtered_candidates"]
    candidates_by_key = {
        str(candidate.get("candidate_key", "") or get_candidate_key(candidate)).strip(): candidate
        for candidate in filtered_candidates
    }

    selected_candidate_keys = []
    for raw_candidate_key in payload.get("candidate_keys", []) or []:
        candidate_key = str(raw_candidate_key or "").strip()
        if candidate_key and candidate_key not in selected_candidate_keys:
            selected_candidate_keys.append(candidate_key)
    if not selected_candidate_keys:
        for raw_email in payload.get("candidate_emails", []) or []:
            email_key = _normalize_email(raw_email)
            if not email_key:
                continue
            for candidate_key, candidate in candidates_by_key.items():
                if _normalize_email(candidate.get("email", "")) == email_key and candidate_key not in selected_candidate_keys:
                    selected_candidate_keys.append(candidate_key)

    if not selected_candidate_keys:
        return jsonify({"success": False, "error": "Select at least one candidate."}), 400

    if len(selected_candidate_keys) > _MAX_CONSOLIDATED_SUMMARY_CANDIDATES:
        return jsonify({
            "success": False,
            "error": (
                f"Please select {_MAX_CONSOLIDATED_SUMMARY_CANDIDATES} candidates or fewer "
                "for one consolidated summary."
            ),
        }), 400

    selected_candidates = [
        candidates_by_key[candidate_key]
        for candidate_key in selected_candidate_keys
        if candidate_key in candidates_by_key
    ]
    if not selected_candidates:
        return jsonify({
            "success": False,
            "error": "The selected candidates are no longer available in the current scope.",
        }), 404

    batch_ids = sorted(
        {
            str(candidate.get("batch_id", "") or "").strip()
            for candidate in selected_candidates
            if str(candidate.get("batch_id", "") or "").strip()
        },
        key=lambda value: value.lower(),
    )
    scope_meta = {
        "role": scope["selected_role"],
        "period_label": scope["period_label"],
        "search_global_mode": scope["search_global_mode"],
        "search_query": scope["search_query"],
        "candidate_count": len(selected_candidates),
        "batch_ids": batch_ids,
    }

    try:
        summary_text = EvaluationService.generate_consolidated_summary(selected_candidates, scope_meta)
    except Exception as exc:
        current_app.logger.exception("Failed to generate consolidated summary: %s", exc)
        return jsonify({"success": False, "error": "Failed to generate consolidated summary."}), 500
    if not str(summary_text or "").strip():
        return jsonify({"success": False, "error": "Consolidated summary is unavailable for the selected candidates."}), 500

    return jsonify({
        "success": True,
        "summary": summary_text,
        "meta": {
            "candidate_count": len(selected_candidates),
            "role": scope["selected_role"],
            "period_label": scope["period_label"],
            "batch_ids": batch_ids,
        },
    })


@reports_bp.route("/reports/consolidated-summary/pdf", methods=["POST"])
@login_required
def download_consolidated_summary_pdf():
    payload = request.get_json(silent=True) or {}
    summary_text = str(payload.get("summary", "") or "").strip()
    meta = payload.get("meta", {}) if isinstance(payload.get("meta", {}), dict) else {}

    if not summary_text:
        return jsonify({"success": False, "error": "Summary text is required to generate a PDF."}), 400

    try:
        filename = generate_consolidated_summary_pdf(summary_text, meta)
    except Exception as exc:
        current_app.logger.exception("Failed to generate consolidated summary PDF: %s", exc)
        return jsonify({"success": False, "error": "Failed to generate summary PDF."}), 500

    return jsonify({
        "success": True,
        "filename": filename,
        "download_url": f"/reports/download-file/{filename}",
    })


@reports_bp.route("/reports/generate/<path:email>")
@login_required
def generate_report(email):
    """Generate a PDF report for a candidate and return JSON with action URLs."""
    email_key = str(email or "").strip().lower()
    if not email_key:
        return jsonify({"success": False, "error": "Candidate email is required"}), 400
    role_key = str(request.args.get("role_key", "") or "").strip()
    batch_id = str(request.args.get("batch_id", "") or "").strip()
    candidate_key = str(request.args.get("candidate_key", "") or "").strip()
    try:
        test_session_id = int(request.args.get("test_session_id", "") or 0) or None
    except (TypeError, ValueError):
        test_session_id = None

    # First try from evaluation aggregator (in-memory data)
    all_candidates = EvaluationAggregator.get_candidates()
    candidate_data = None
    for c in all_candidates:
        if matches_candidate_scope(
            c,
            candidate_key=candidate_key,
            email=email_key,
            role_key=role_key,
            batch_id=batch_id,
        ):
            candidate_data = c
            break

    # Fallback to DB
    if not candidate_data:
        candidate_data = db_service.get_candidate_report_data(
            email_key,
            test_session_id=test_session_id,
            role_key=role_key,
            batch_id=batch_id,
        )

    if not candidate_data:
        return jsonify({"success": False, "error": f"No data found for candidate: {email_key}"}), 404
    candidate_data["candidate_key"] = str(candidate_data.get("candidate_key", "") or candidate_key or get_candidate_key(candidate_data)).strip()

    attempted_rounds = _attempted_rounds(candidate_data)
    session_scope = set()
    test_session_id = candidate_data.get("test_session_id")
    user = session.get("user", {})
    creator_email = str((user or {}).get("email", "")).strip().lower()
    if not test_session_id:
        role_key = str((candidate_data or {}).get("role_key", "")).strip()
        batch_id = str((candidate_data or {}).get("batch_id", "")).strip()
        try:
            test_session_id = db_service.get_latest_test_session_id_for_candidate(
                email_key,
                created_by=creator_email,
                role_key=role_key,
                batch_id=batch_id,
            )
        except Exception as exc:
            current_app.logger.exception("Failed to resolve latest test session for %s: %s", email_key, exc)
            test_session_id = None
        if not test_session_id:
            try:
                test_session_id = db_service.get_latest_test_session_id_for_email(email_key)
            except Exception as exc:
                current_app.logger.exception(
                    "Fallback latest session lookup by email failed for %s: %s",
                    email_key,
                    exc,
                )
                test_session_id = None

    if test_session_id:
        try:
            session_scope.update(
                db_service.get_round_session_uuids_for_test_session(
                    int(test_session_id),
                    attempted_only=True,
                )
            )
        except Exception as exc:
            current_app.logger.exception(
                "Failed to resolve round session UUIDs for %s (test_session_id=%s): %s",
                email_key,
                test_session_id,
                exc,
            )

    if attempted_rounds <= 0:
        candidate_data["proctoring_summary"] = blank_proctoring_summary()
    else:
        proctoring_by_email = build_proctoring_summary_by_email(
            {email_key},
            session_ids_by_email={email_key: session_scope},
        )
        candidate_data["proctoring_summary"] = proctoring_by_email.get(email_key, blank_proctoring_summary())
    plagiarism_by_email = build_plagiarism_summary_by_candidates([candidate_data])
    candidate_data["plagiarism_summary"] = plagiarism_by_email.get(email_key, blank_plagiarism_summary())

    # Attach AI summaries for PDF rendering.
    try:
        candidate_data["ai_overall_summary"] = EvaluationService.generate_candidate_overall_summary(
            email_key,
            candidate_data=candidate_data,
        )
    except Exception:
        candidate_data["ai_overall_summary"] = None

    try:
        candidate_data["ai_coding_summary"] = EvaluationService.generate_candidate_coding_round_summary(
            email_key,
            candidate_data=candidate_data,
        )
    except Exception:
        candidate_data["ai_coding_summary"] = None
    try:
        candidate_data["coding_round_data"] = EvaluationService.get_candidate_coding_round_data(
            email_key,
            candidate_data=candidate_data,
        )
    except Exception:
        candidate_data["coding_round_data"] = None

    # Generate PDF
    try:
        ts = None
        try:
            ts = db_service.ensure_candidate_session_for_report(candidate_data, user.get("email", ""))
        except Exception:
            ts = None

        filename = generate_candidate_pdf(candidate_data)

        # Save report record to DB
        try:
            if ts and getattr(ts, "id", None):
                db_service.save_report(ts.id, filename, user.get("email", ""))
            else:
                db_service.save_report(email_key, filename, user.get("email", ""))
        except Exception:
            pass

        return jsonify({
            "success": True,
            "filename": filename,
            "candidate": candidate_data.get("name", email),
            "view_url": f"/reports/view/{filename}",
            "download_url": f"/reports/download-file/{filename}",
        })
    except Exception as e:
        return jsonify({"success": False, "error": f"Failed to generate report: {str(e)}"}), 500


@reports_bp.route("/reports/proctoring/screenshots")
@login_required
def list_proctoring_screenshots():
    email = request.args.get("email", "").strip()
    try:
        test_session_id = int(request.args.get("test_session_id", "") or 0) or None
    except (TypeError, ValueError):
        test_session_id = None
    if not email and not test_session_id:
        return jsonify({"screenshots": [], "error": "email or test_session_id required"}), 400

    try:
        limit_raw = request.args.get("limit", "200")
        limit = max(1, min(int(limit_raw), 500))
    except (TypeError, ValueError):
        limit = 200

    if test_session_id:
        session_ids = db_service.get_round_session_uuids_for_test_session(
            test_session_id,
            attempted_only=False,
        )
        records = db_service.get_proctoring_screenshots_by_session_ids(session_ids, limit=limit)
    else:
        records = db_service.get_proctoring_screenshots_by_email(email, limit=limit)
    screenshots = []
    for rec in records:
        captured = rec.captured_at.isoformat() if rec.captured_at else ""
        screenshots.append({
            "id": rec.id,
            "captured_at": captured,
            "round_key": rec.round_key,
            "round_label": rec.round_label,
            "source": rec.source,
            "event_type": rec.event_type,
        })

    return jsonify({"screenshots": screenshots})


@reports_bp.route("/reports/proctoring/screenshot/<int:screenshot_id>")
@login_required
def get_proctoring_screenshot(screenshot_id):
    rec = db_service.get_proctoring_screenshot_by_id(screenshot_id)
    if not rec or not rec.image_bytes:
        abort(404, description="Screenshot not found")

    filename = f"proctoring_{rec.id}.png"
    return send_file(
        BytesIO(rec.image_bytes),
        mimetype=rec.mime_type or "image/png",
        download_name=filename,
        as_attachment=False,
    )


@reports_bp.route("/reports/view/<path:filename>")
@login_required
def view_report(filename):
    """View a PDF report inline in the browser."""
    filepath = REPORTS_DIR / filename
    if not filepath.exists():
        abort(404, description="Report file not found")

    return send_file(
        str(filepath),
        as_attachment=False,
        download_name=filename,
        mimetype="application/pdf",
    )


@reports_bp.route("/reports/download-file/<path:filename>")
@login_required
def download_report_file(filename):
    """Download a PDF report as attachment."""
    filepath = REPORTS_DIR / filename
    if not filepath.exists():
        abort(404, description="Report file not found")

    return send_file(
        str(filepath),
        as_attachment=True,
        download_name=filename,
        mimetype="application/pdf",
    )


@reports_bp.route("/reports/download/<int:report_id>")
@login_required
def download_report(report_id):
    """Download a previously generated report."""
    report = db_service.get_report_by_id(report_id)
    if not report:
        abort(404, description="Report not found")

    filepath = REPORTS_DIR / report.filename
    if not filepath.exists():
        abort(404, description="Report file not found on disk")

    return send_file(
        str(filepath),
        as_attachment=True,
        download_name=report.filename,
        mimetype="application/pdf",
    )


@reports_bp.route("/reports/preview/<int:test_session_id>")
@login_required
def preview_report(test_session_id):
    """Return candidate report data as JSON for preview."""
    from app.models import TestSession as TS, Candidate as C
    ts = TS.query.get(test_session_id)
    if not ts:
        return jsonify({"error": "Test session not found"}), 404
    cand = C.query.get(ts.candidate_id)
    if not cand:
        return jsonify({"error": "Candidate not found"}), 404

    data = db_service.get_candidate_report_data(cand.email, test_session_id=test_session_id)
    if not data:
        return jsonify({"error": "No report data available"}), 404

    return jsonify(data)


@reports_bp.route("/reports/download/<path:filename>")
@login_required
def download_report_by_filename(filename):
    """Download a PDF report by filename."""
    filepath = REPORTS_DIR / filename
    if not filepath.exists():
        abort(404, description="Report file not found")

    return send_file(
        str(filepath),
        as_attachment=True,
        download_name=filename,
        mimetype="application/pdf",
    )


@reports_bp.route("/reports/generate", methods=["POST"])
@login_required
def generate_report_by_session():
    """Generate a PDF report for a candidate given test_session_id (form/JSON)."""
    test_session_id = request.form.get("test_session_id") or (
        request.get_json(silent=True) or {}
    ).get("test_session_id")

    if not test_session_id:
        return jsonify({"status": "error", "error": "test_session_id required"}), 400

    test_session_id = int(test_session_id)
    from app.models import TestSession as TS, Candidate as C
    ts = TS.query.get(test_session_id)
    if not ts:
        return jsonify({"status": "error", "error": "Test session not found"}), 404
    cand = C.query.get(ts.candidate_id)
    if not cand:
        return jsonify({"status": "error", "error": "Candidate not found"}), 404

    candidate_data = db_service.get_candidate_report_data(cand.email, test_session_id=test_session_id)
    if not candidate_data:
        return jsonify({"status": "error", "error": "No data for candidate"}), 404
    candidate_data["candidate_key"] = str(candidate_data.get("candidate_key", "") or get_candidate_key(candidate_data)).strip()

    email_key = str(cand.email or "").strip().lower()
    attempted_rounds = _attempted_rounds(candidate_data)
    if attempted_rounds <= 0:
        candidate_data["proctoring_summary"] = blank_proctoring_summary()
    else:
        try:
            scoped_session_ids = set(
                db_service.get_round_session_uuids_for_test_session(
                    test_session_id,
                    attempted_only=True,
                )
            )
        except Exception as exc:
            current_app.logger.exception(
                "Failed to fetch session scope for report generation test_session_id=%s: %s",
                test_session_id,
                exc,
            )
            scoped_session_ids = set()
        proctoring_by_email = build_proctoring_summary_by_email(
            {email_key},
            session_ids_by_email={email_key: scoped_session_ids},
        )
        candidate_data["proctoring_summary"] = proctoring_by_email.get(email_key, blank_proctoring_summary())
    plagiarism_by_email = build_plagiarism_summary_by_candidates([candidate_data])
    candidate_data["plagiarism_summary"] = plagiarism_by_email.get(email_key, blank_plagiarism_summary())

    try:
        candidate_data["ai_overall_summary"] = EvaluationService.generate_candidate_overall_summary(
            email_key,
            candidate_data=candidate_data,
        )
    except Exception:
        candidate_data["ai_overall_summary"] = None
    try:
        candidate_data["ai_coding_summary"] = EvaluationService.generate_candidate_coding_round_summary(
            email_key,
            candidate_data=candidate_data,
        )
    except Exception:
        candidate_data["ai_coding_summary"] = None
    try:
        candidate_data["coding_round_data"] = EvaluationService.get_candidate_coding_round_data(
            email_key,
            candidate_data=candidate_data,
        )
    except Exception:
        candidate_data["coding_round_data"] = None

    try:
        pdf_filename = generate_candidate_pdf(candidate_data)
        user = session.get("user", {})
        db_service.save_report(test_session_id, pdf_filename, user.get("email", ""))
        return jsonify({"status": "ok", "filename": pdf_filename})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500



