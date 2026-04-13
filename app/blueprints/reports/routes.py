# filepath: d:\Projects\aziro-hiring-platform\app\blueprints\reports\routes.py
"""
Reports page - recent session candidates + historical report search.
"""
import base64
import json
import mimetypes
import zipfile
from datetime import datetime, timezone, timedelta
from io import BytesIO
from math import ceil
from pathlib import Path
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
from app.services.pdf_service import generate_candidate_pdf, generate_consolidated_summary_pdf, generate_login_activity_pdf, REPORTS_DIR
from app.access_config import get_access_admin_emails

reports_bp = Blueprint("reports", __name__)
_VALID_PERIOD_FILTERS = {"today", "24h", "7d", "28d", "date"}
_MAX_CONSOLIDATED_SUMMARY_CANDIDATES = 60
_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_PROCTORING_SCREENSHOT_ROOT = (_PROJECT_ROOT / "app" / "runtime" / "proctoring" / "screenshots").resolve()
_PROCTORING_EVENTS_FILE = _PROJECT_ROOT / "app" / "runtime" / "proctoring" / "events.jsonl"


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


def _log_non_blocking_report_issue(message: str, *args):
    current_app.logger.exception(message, *args)


def _row_value(row, key: str, default=None):
    if isinstance(row, dict):
        return row.get(key, default)
    return getattr(row, key, default)


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


def _parse_iso_date(value: str) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return datetime.strptime(raw, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _normalize_admin_date_range(from_date: str = "", to_date: str = "") -> tuple[str, str, datetime | None, datetime | None]:
    from_raw = str(from_date or "").strip()
    to_raw = str(to_date or "").strip()
    from_dt = _parse_iso_date(from_raw)
    to_dt = _parse_iso_date(to_raw)

    if from_raw and not from_dt:
        from_raw = ""
    if to_raw and not to_dt:
        to_raw = ""

    start = from_dt
    end = (to_dt + timedelta(days=1)) if to_dt else None
    if start and end and start >= end:
        from_raw, to_raw = to_raw, from_raw
        start, end = _parse_iso_date(from_raw), (_parse_iso_date(to_raw) + timedelta(days=1)) if _parse_iso_date(to_raw) else None

    return from_raw, to_raw, start, end


def _admin_period_label(from_date: str = "", to_date: str = "") -> str:
    if from_date and to_date:
        return f"{from_date} to {to_date}"
    if from_date:
        return f"From {from_date}"
    if to_date:
        return f"Up to {to_date}"
    return "Custom Range"


def _is_reports_admin(user_email: str) -> bool:
    email = _normalize_email(user_email)
    return bool(email and email in {_normalize_email(value) for value in get_access_admin_emails()})


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


def _encode_screenshot_file_ref(path_value: str) -> str:
    raw = str(path_value or "").strip()
    if not raw:
        return ""
    encoded = base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii").rstrip("=")
    return f"file_{encoded}"


def _decode_screenshot_file_ref(ref: str) -> str:
    value = str(ref or "").strip()
    if not value.startswith("file_"):
        return ""
    payload = value[len("file_") :]
    if not payload:
        return ""
    try:
        padded = payload + ("=" * ((4 - len(payload) % 4) % 4))
        return base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")
    except Exception:
        return ""


def _resolve_screenshot_file(path_value: str) -> Path | None:
    raw = str(path_value or "").strip()
    if not raw:
        return None
    candidate = Path(raw)
    if not candidate.is_absolute():
        candidate = (_PROJECT_ROOT / candidate).resolve()
    else:
        candidate = candidate.resolve()
    try:
        candidate.relative_to(_PROCTORING_SCREENSHOT_ROOT)
    except Exception:
        return None
    if not candidate.exists() or not candidate.is_file():
        return None
    return candidate


def _load_proctoring_screenshots_from_events(*, email: str = "", session_ids=None, limit: int = 200):
    if not _PROCTORING_EVENTS_FILE.exists():
        return []

    email_key = _normalize_email(email)
    normalized_sessions = {
        str(session_id or "").strip().lower()
        for session_id in (session_ids or [])
        if str(session_id or "").strip()
    }
    results = []
    seen = set()

    try:
        with _PROCTORING_EVENTS_FILE.open("r", encoding="utf-8") as handle:
            for raw_line in handle:
                line = str(raw_line or "").strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue

                event_type = str(event.get("event_type") or "").strip()
                if not event_type.lower().startswith("screenshot:"):
                    continue

                event_email = _normalize_email(event.get("email", ""))
                session_uuid = str(event.get("session_id") or "").strip().lower()
                if normalized_sessions:
                    if not session_uuid or session_uuid not in normalized_sessions:
                        continue
                elif email_key and event_email != email_key:
                    continue
                elif not event_email and not session_uuid:
                    continue

                screenshot_path = str(event.get("screenshot_path") or "").strip()
                resolved_path = _resolve_screenshot_file(screenshot_path)
                if resolved_path is None:
                    continue

                dedupe_key = str(resolved_path).lower()
                if dedupe_key in seen:
                    continue
                seen.add(dedupe_key)

                details = event.get("details")
                if not isinstance(details, dict):
                    details = {}

                results.append(
                    {
                        "id": _encode_screenshot_file_ref(str(resolved_path)),
                        "captured_at": str(event.get("ts") or ""),
                        "round_key": str(details.get("round_key") or ""),
                        "round_label": str(event.get("round_label") or details.get("round_label") or ""),
                        "source": str(details.get("capture_source") or "events"),
                        "event_type": event_type,
                    }
                )
    except OSError:
        return []

    def _sort_key(item: dict):
        dt = _parse_created_at(item.get("captured_at", ""))
        return dt or datetime.min.replace(tzinfo=timezone.utc)

    return sorted(results, key=_sort_key, reverse=True)[:limit]


def _attach_report_info(candidate: dict):
    email_key = _normalize_email(candidate.get("email", ""))
    if not email_key:
        candidate["has_report"] = False
        candidate["report_filename"] = ""
        candidate["report_id"] = None
        return
    role_key = str(candidate.get("role_key", "") or "").strip()
    batch_id = str(candidate.get("batch_id", "") or "").strip()
    try:
        info = db_service.get_latest_report_for_email(
            email_key,
            test_session_id=candidate.get("test_session_id"),
            role_key=role_key,
            batch_id=batch_id,
        )
        # If a scoped lookup misses, keep report visibility stable by falling back
        # to any historical report for the same candidate email.
        if not info:
            info = db_service.get_latest_report_for_email(email_key)
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
    is_access_admin: bool = False,
    from_date: str = "",
    to_date: str = "",
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

    admin_from_date, admin_to_date, _admin_range_start, _admin_range_end = _normalize_admin_date_range(from_date, to_date)
    admin_date_range_mode = bool(is_access_admin and (admin_from_date or admin_to_date))

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

    database_scope_mode = bool(search_global_mode)
    if database_scope_mode:
        db_role_filter = role_filter if role_filter.lower() not in {"all", "all roles"} else ""
        db_query = q if search_global_mode else ""
        try:
            db_matches = db_service.search_candidates(
                db_query,
                db_role_filter,
            )
        except Exception as exc:
            current_app.logger.exception("DB candidate search failed: %s", exc)
            db_matches = []
        try:
            report_matches = db_service.search_candidates_with_reports(
                db_query,
                db_role_filter,
            )
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
    base_candidates = list(all_candidates_pool) if database_scope_mode else list(session_candidates)
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
        "search_global_mode": database_scope_mode,
        "admin_date_range_mode": admin_date_range_mode,
        "admin_date_from": admin_from_date,
        "admin_date_to": admin_to_date,
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


def _collect_admin_database_candidates(*, q: str = "", role_filter: str = "", from_date: str = "", to_date: str = "", is_access_admin: bool = False) -> dict:
    admin_from_date, admin_to_date, range_start, range_end = _normalize_admin_date_range(from_date, to_date)
    active = bool(is_access_admin and (admin_from_date or admin_to_date) and range_start and range_end)
    if not active:
        return {
            "active": False,
            "candidates": [],
            "groups": [],
            "count": 0,
            "total_candidates": 0,
            "total_reports": 0,
            "total_logins": 0,
            "period_label": "",
            "from_date": admin_from_date,
            "to_date": admin_to_date,
        }

    db_role_filter = role_filter if str(role_filter or "").strip().lower() not in {"all", "all roles"} else ""
    db_query = str(q or "").strip()
    try:
        activity_rows = db_service.get_created_candidate_activity(
            since=range_start,
            until=range_end,
            query_text=db_query,
            role_filter=db_role_filter,
        )
    except Exception as exc:
        current_app.logger.exception("Admin DB candidate activity lookup failed: %s", exc)
        activity_rows = []

    try:
        login_rows = db_service.get_login_audits_by_range(since=range_start, until=range_end)
    except Exception as exc:
        current_app.logger.exception("Admin DB login audit lookup failed: %s", exc)
        login_rows = []

    login_by_email = {}
    total_logins = 0
    for row in login_rows:
        email_key = _normalize_email(_row_value(row, "user_email", ""))
        if not email_key:
            continue
        total_logins += 1
        existing = login_by_email.get(email_key)
        logged_in_at = _row_value(row, "logged_in_at")
        row_name = str(_row_value(row, "user_name", "") or "").strip()
        auth_provider = str(_row_value(row, "auth_provider", "") or "").strip()
        if existing is None:
            login_by_email[email_key] = {
                "user_name": row_name,
                "logged_in_at": logged_in_at,
                "auth_provider": auth_provider,
                "login_count": 1,
            }
            continue

        existing["login_count"] = int(existing.get("login_count", 0) or 0) + 1
        if row_name and not str(existing.get("user_name", "") or "").strip():
            existing["user_name"] = row_name
        if auth_provider and not str(existing.get("auth_provider", "") or "").strip():
            existing["auth_provider"] = auth_provider
        if (logged_in_at or datetime.min.replace(tzinfo=timezone.utc)) > (existing.get("logged_in_at") or datetime.min.replace(tzinfo=timezone.utc)):
            existing["logged_in_at"] = logged_in_at
            if row_name:
                existing["user_name"] = row_name
            if auth_provider:
                existing["auth_provider"] = auth_provider

    groups_by_email = {}
    for email_key, login_meta in login_by_email.items():
        display_name = str(login_meta.get("user_name", "") or "").strip()
        if not display_name:
            display_name = email_key.split("@")[0].replace(".", " ").title()
        groups_by_email[email_key] = {
            "user_email": email_key,
            "user_name": display_name or "Unknown User",
            "last_login_at": login_meta.get("logged_in_at"),
            "auth_provider": str(login_meta.get("auth_provider", "") or "").strip(),
            "login_count": int(login_meta.get("login_count", 0) or 0),
            "candidates": [],
            "report_ids": [],
            "report_count": 0,
        }

    for row in activity_rows:
        creator_email = _normalize_email(row.get("creator_email", ""))
        if not creator_email:
            continue
        group = groups_by_email.get(creator_email)
        if group is None:
            group = {
                "user_email": creator_email,
                "user_name": creator_email.split("@")[0].replace(".", " ").title(),
                "last_login_at": None,
                "auth_provider": "",
                "login_count": 0,
                "candidates": [],
                "report_ids": [],
                "report_count": 0,
            }
            groups_by_email[creator_email] = group

        candidate = {
            "candidate_key": get_candidate_key(
                {
                    "email": row.get("candidate_email", ""),
                    "role_key": row.get("role_key", ""),
                    "role": row.get("role", ""),
                    "batch_id": row.get("batch_id", ""),
                }
            ),
            "name": str(row.get("candidate_name", "") or "").strip() or _normalize_email(row.get("candidate_email", "")),
            "email": _normalize_email(row.get("candidate_email", "")),
            "role": str(row.get("role", "") or "").strip(),
            "role_key": str(row.get("role_key", "") or "").strip(),
            "batch_id": str(row.get("batch_id", "") or "").strip(),
            "created_at": str(row.get("created_at", "") or "").strip(),
            "test_session_id": row.get("test_session_id"),
            "report_id": row.get("report_id"),
            "report_filename": str(row.get("report_filename", "") or "").strip(),
            "has_report": bool(row.get("report_id") and row.get("report_filename")),
        }
        if not candidate["has_report"]:
            _attach_report_info(candidate)
        group["candidates"].append(candidate)

        report_id = candidate.get("report_id")
        if report_id and report_id not in group["report_ids"]:
            group["report_ids"].append(report_id)

    groups = sorted(
        groups_by_email.values(),
        key=lambda item: (
            item.get("user_email") != "",
            item.get("user_name", "").lower(),
            item.get("user_email", "").lower(),
        ),
    )

    total_reports = 0
    total_candidates = 0
    for group in groups:
        group["candidates"] = sorted(group["candidates"], key=_created_sort_key, reverse=True)
        group["report_count"] = len(group["report_ids"])
        total_reports += group["report_count"]
        total_candidates += len(group["candidates"])

    return {
        "active": True,
        "candidates": [candidate for group in groups for candidate in group["candidates"]],
        "groups": groups,
        "count": len(groups),
        "total_candidates": total_candidates,
        "total_reports": total_reports,
        "total_logins": total_logins,
        "period_label": _admin_period_label(admin_from_date, admin_to_date),
        "from_date": admin_from_date,
        "to_date": admin_to_date,
    }


def _hydrate_candidate_from_db(candidate: dict):
    if not isinstance(candidate, dict):
        return
    summary = candidate.get("summary", {}) or {}
    if candidate.get("rounds") or candidate.get("results") or int(summary.get("attempted_rounds", 0) or 0) > 0:
        return

    email_key = _normalize_email(candidate.get("email", ""))
    test_session_id = candidate.get("test_session_id")
    if not email_key or not test_session_id:
        return

    try:
        db_candidate = db_service.get_candidate_report_data(
            email_key,
            test_session_id=test_session_id,
            role_key=str(candidate.get("role_key", "") or "").strip(),
            batch_id=str(candidate.get("batch_id", "") or "").strip(),
        )
    except Exception as exc:
        current_app.logger.exception("Failed to hydrate report candidate from DB for %s: %s", email_key, exc)
        return

    if not db_candidate:
        return

    preserved_key = str(candidate.get("candidate_key", "") or "").strip()
    candidate.update(db_candidate)
    if preserved_key and not str(candidate.get("candidate_key", "") or "").strip():
        candidate["candidate_key"] = preserved_key


@reports_bp.route("/reports")
@login_required
def reports():
    user = session.get("user", {})
    user_email = user.get("email", "dev@aziro.com")
    q = request.args.get("q", "").strip()
    role_filter = request.args.get("role", "").strip()
    date_filter = str(request.args.get("filter", "today") or "today").strip().lower()
    specific_date = str(request.args.get("date", "") or "").strip()
    from_date = str(request.args.get("from", "") or "").strip()
    to_date = str(request.args.get("to", "") or "").strip()
    admin_view_raw = str(request.args.get("admin_view", "") or "").strip().lower()
    admin_view_explicit = admin_view_raw in {"created_by", "login_users"}
    admin_view = admin_view_raw if admin_view_explicit else "created_by"
    admin_user_filter = _normalize_email(request.args.get("admin_user", ""))
    is_access_admin = _is_reports_admin(user_email)
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
        is_access_admin=is_access_admin,
        from_date=from_date,
        to_date=to_date,
    )
    admin_db_scope = _collect_admin_database_candidates(
        q=q,
        role_filter=role_filter,
        from_date=from_date,
        to_date=to_date,
        is_access_admin=is_access_admin,
    )
    if admin_db_scope.get("active") and not admin_view_explicit:
        admin_view = "login_users"
    admin_user_options = [
        {
            "email": str(group.get("user_email", "") or "").strip().lower(),
            "name": str(group.get("user_name", "") or "").strip() or str(group.get("user_email", "") or "").strip().lower(),
            "login_count": int(group.get("login_count", 0) or 0),
        }
        for group in admin_db_scope.get("groups", [])
        if str(group.get("user_email", "") or "").strip()
    ]
    admin_user_options = sorted(admin_user_options, key=lambda item: ((item["name"] or "").lower(), item["email"]))
    admin_selected_group = None
    if admin_user_filter:
        for group in admin_db_scope.get("groups", []):
            if _normalize_email(group.get("user_email", "")) == admin_user_filter:
                admin_selected_group = group
                break
    if admin_view == "login_users" and not admin_selected_group and admin_user_options:
        admin_user_filter = admin_user_options[0]["email"]
        for group in admin_db_scope.get("groups", []):
            if _normalize_email(group.get("user_email", "")) == admin_user_filter:
                admin_selected_group = group
                break

    def _normalize_report_ids(values) -> list[int]:
        normalized = []
        seen = set()
        for value in values or []:
            try:
                report_id = int(value)
            except (TypeError, ValueError):
                continue
            if report_id <= 0 or report_id in seen:
                continue
            seen.add(report_id)
            normalized.append(report_id)
        return normalized

    admin_all_report_ids = _normalize_report_ids(
        [
            report_id
            for group in admin_db_scope.get("groups", [])
            for report_id in (group.get("report_ids", []) or [])
        ]
    )
    admin_selected_group_report_ids = _normalize_report_ids(
        admin_selected_group.get("report_ids", []) if admin_selected_group else []
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
        _hydrate_candidate_from_db(candidate)
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
        admin_date_range_mode=admin_db_scope["active"],
        admin_date_from=admin_db_scope["from_date"],
        admin_date_to=admin_db_scope["to_date"],
        admin_db_candidates=admin_db_scope["candidates"],
        admin_db_groups=admin_db_scope["groups"],
        admin_db_count=admin_db_scope["count"],
        admin_db_total_candidates=admin_db_scope["total_candidates"],
        admin_db_total_reports=admin_db_scope["total_reports"],
        admin_db_total_logins=admin_db_scope["total_logins"],
        admin_db_period_label=admin_db_scope["period_label"],
        admin_view=admin_view,
        admin_user_filter=admin_user_filter,
        admin_user_options=admin_user_options,
        admin_selected_group=admin_selected_group,
        admin_all_report_ids=admin_all_report_ids,
        admin_selected_group_report_ids=admin_selected_group_report_ids,
        is_reports_admin=is_access_admin,
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


def _save_report_metadata_best_effort(*, identifier, filename: str, generated_by: str = ""):
    try:
        record = db_service.save_report(identifier, filename, generated_by)
        return record, True
    except Exception as exc:
        _log_non_blocking_report_issue(
            "Report metadata save failed for identifier=%s filename=%s: %s",
            identifier,
            filename,
            exc,
        )
        return None, False


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
    except Exception as exc:
        current_app.logger.exception(
            "Failed to generate AI overall summary for %s: %s",
            email_key,
            exc,
        )
        candidate_data["ai_overall_summary"] = None

    try:
        candidate_data["ai_coding_summary"] = EvaluationService.generate_candidate_coding_round_summary(
            email_key,
            candidate_data=candidate_data,
        )
    except Exception as exc:
        current_app.logger.exception(
            "Failed to generate AI coding summary for %s: %s",
            email_key,
            exc,
        )
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

        metadata_saved = False
        if ts and getattr(ts, "id", None):
            _, metadata_saved = _save_report_metadata_best_effort(
                identifier=ts.id,
                filename=filename,
                generated_by=user.get("email", ""),
            )
        if not metadata_saved:
            _, metadata_saved = _save_report_metadata_best_effort(
                identifier=email_key,
                filename=filename,
                generated_by=user.get("email", ""),
            )

        return jsonify({
            "success": True,
            "filename": filename,
            "candidate": candidate_data.get("name", email),
            "view_url": f"/reports/view/{filename}",
            "download_url": f"/reports/download-file/{filename}",
            "metadata_saved": metadata_saved,
        })
    except Exception as e:
        return jsonify({"success": False, "error": f"Failed to generate report: {str(e)}"}), 500


@reports_bp.route("/reports/proctoring/screenshots")
@login_required
def list_proctoring_screenshots():
    email = request.args.get("email", "").strip().lower()
    session_ids = []
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

    try:
        if test_session_id:
            session_ids = db_service.get_round_session_uuids_for_test_session(
                test_session_id,
                attempted_only=False,
            )
            records = db_service.get_proctoring_screenshots_by_session_ids(session_ids, limit=limit)
            if not records and email:
                records = db_service.get_proctoring_screenshots_by_email(email, limit=limit)
        else:
            records = db_service.get_proctoring_screenshots_by_email(email, limit=limit)
    except Exception as exc:
        current_app.logger.exception(
            "Failed to load proctoring screenshots for email=%s test_session_id=%s: %s",
            email,
            test_session_id,
            exc,
        )
        records = []
    if not records:
        fallback = _load_proctoring_screenshots_from_events(
            email=email,
            session_ids=session_ids if test_session_id else None,
            limit=limit,
        )
        if fallback:
            return jsonify({"screenshots": fallback})
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


@reports_bp.route("/reports/proctoring/screenshot/<path:screenshot_ref>")
@login_required
def get_proctoring_screenshot(screenshot_ref):
    screenshot_key = str(screenshot_ref or "").strip()
    if not screenshot_key:
        abort(404, description="Screenshot not found")

    if screenshot_key.isdigit():
        screenshot_id = int(screenshot_key)
        try:
            rec = db_service.get_proctoring_screenshot_by_id(screenshot_id)
        except Exception as exc:
            current_app.logger.exception(
                "Failed to load proctoring screenshot id=%s: %s",
                screenshot_id,
                exc,
            )
            abort(404, description="Screenshot not found")
        if not rec:
            abort(404, description="Screenshot not found")

        if rec.image_bytes:
            filename = f"proctoring_{rec.id}.png"
            return send_file(
                BytesIO(bytes(rec.image_bytes)),
                mimetype=rec.mime_type or "image/png",
                download_name=filename,
                as_attachment=False,
            )

        resolved = _resolve_screenshot_file(rec.screenshot_path)
        if resolved is not None:
            guessed_mime = rec.mime_type or mimetypes.guess_type(resolved.name)[0] or "image/png"
            return send_file(
                str(resolved),
                mimetype=guessed_mime,
                download_name=resolved.name,
                as_attachment=False,
            )
        abort(404, description="Screenshot not found")

    decoded_path = _decode_screenshot_file_ref(screenshot_key)
    resolved = _resolve_screenshot_file(decoded_path)
    if resolved is None:
        abort(404, description="Screenshot not found")

    guessed_mime = mimetypes.guess_type(resolved.name)[0] or "image/png"
    return send_file(
        str(resolved),
        mimetype=guessed_mime,
        download_name=resolved.name,
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


@reports_bp.route("/reports/admin/db-bulk-download", methods=["POST"])
@login_required
def download_admin_db_reports_zip():
    user = session.get("user", {}) if isinstance(session.get("user"), dict) else {}
    user_email = str(user.get("email", "") or "").strip().lower()
    if not _is_reports_admin(user_email):
        abort(403)

    raw_ids = request.form.getlist("report_ids")
    report_ids = []
    seen_ids = set()
    for value in raw_ids:
        try:
            report_id = int(str(value or "").strip())
        except (TypeError, ValueError):
            continue
        if report_id <= 0 or report_id in seen_ids:
            continue
        seen_ids.add(report_id)
        report_ids.append(report_id)

    if not report_ids:
        abort(400, description="No reports selected")

    reports = db_service.get_reports_by_ids(report_ids)
    report_files = []
    for report in reports:
        filename = str(getattr(report, "filename", "") or "").strip()
        if not filename:
            continue
        filepath = REPORTS_DIR / filename
        if not filepath.exists() or not filepath.is_file():
            continue
        report_files.append((filename, filepath))

    if not report_files:
        abort(404, description="Report files not found")

    buffer = BytesIO()
    with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        for filename, filepath in report_files:
            archive.write(filepath, arcname=filename)
    buffer.seek(0)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return send_file(
        buffer,
        mimetype="application/zip",
        as_attachment=True,
        download_name=f"candidate_reports_{timestamp}.zip",
    )


@reports_bp.route("/reports/admin/login-activity-pdf", methods=["POST"])
@login_required
def download_admin_login_activity_pdf():
    user = session.get("user", {}) if isinstance(session.get("user"), dict) else {}
    user_email = str(user.get("email", "") or "").strip().lower()
    if not _is_reports_admin(user_email):
        abort(403)

    from_date = str(request.form.get("from", "") or "").strip()
    to_date = str(request.form.get("to", "") or "").strip()
    from_date, to_date, range_start, range_end = _normalize_admin_date_range(from_date, to_date)
    if not (range_start and range_end):
        abort(400, description="Valid from/to dates are required")

    try:
        login_rows = db_service.get_login_audits_by_range(since=range_start, until=range_end)
    except Exception as exc:
        current_app.logger.exception("Admin login activity PDF lookup failed: %s", exc)
        abort(500, description="Failed to load login activity")

    normalized_rows = []
    unique_users = set()
    for row in login_rows:
        user_email_value = str(_row_value(row, "user_email", "") or "").strip().lower()
        user_name_value = str(_row_value(row, "user_name", "") or "").strip()
        auth_provider = str(_row_value(row, "auth_provider", "") or "").strip()
        logged_in_at = _row_value(row, "logged_in_at")
        logged_in_label = "-"
        if isinstance(logged_in_at, datetime):
            logged_in_label = logged_in_at.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        elif logged_in_at:
            logged_in_label = str(logged_in_at)

        if user_email_value:
            unique_users.add(user_email_value)

        normalized_rows.append({
            "user_name": user_name_value or "Unknown User",
            "user_email": user_email_value or "-",
            "auth_provider": auth_provider or "-",
            "logged_in_at": logged_in_label,
        })

    try:
        filename = generate_login_activity_pdf(
            normalized_rows,
            {
                "period_label": _admin_period_label(from_date, to_date),
                "generated_by": user_email,
                "total_logins": len(normalized_rows),
                "unique_users": len(unique_users),
            },
        )
    except Exception as exc:
        current_app.logger.exception("Failed to generate login activity PDF: %s", exc)
        abort(500, description="Failed to generate login activity PDF")

    filepath = REPORTS_DIR / filename
    return send_file(
        filepath,
        as_attachment=True,
        download_name=filename,
        mimetype="application/pdf",
        max_age=0,
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
    except Exception as exc:
        current_app.logger.exception(
            "Failed to generate AI overall summary for %s in generate-report-test: %s",
            email_key,
            exc,
        )
        candidate_data["ai_overall_summary"] = None
    try:
        candidate_data["ai_coding_summary"] = EvaluationService.generate_candidate_coding_round_summary(
            email_key,
            candidate_data=candidate_data,
        )
    except Exception as exc:
        current_app.logger.exception(
            "Failed to generate AI coding summary for %s in generate-report-test: %s",
            email_key,
            exc,
        )
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
        _, metadata_saved = _save_report_metadata_best_effort(
            identifier=test_session_id,
            filename=pdf_filename,
            generated_by=user.get("email", ""),
        )
        return jsonify({"status": "ok", "filename": pdf_filename, "metadata_saved": metadata_saved})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500



