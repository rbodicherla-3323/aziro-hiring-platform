# filepath: d:\Projects\aziro-hiring-platform\app\services\generated_tests_store.py
"""
In-memory store for generated test entries (per-server session).
Each entry tracks: name, email, role, tests dict, created_by, created_at.
"""
from datetime import datetime, timezone, timedelta
import os

GENERATED_TESTS = []
GENERATED_TESTS_PRESENT_SESSION_KEY = "generated_tests_present_session_started_at"


def _get_int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except Exception:
        return int(default)


SESSION_RETENTION_DAYS = _get_int_env("SESSION_RETENTION_DAYS", 7)


def _within_retention(dt: datetime) -> bool:
    now = datetime.now(timezone.utc)
    return dt >= (now - timedelta(days=SESSION_RETENTION_DAYS))


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


def _entry_identity(entry: dict):
    created_by = str(entry.get("created_by", "")).strip().lower()
    batch_id = str(entry.get("batch_id", "")).strip().lower()
    email = str(entry.get("email", "")).strip().lower()
    name = str(entry.get("name", "")).strip().lower()
    role = str(entry.get("role_key", "") or entry.get("role", "")).strip().lower()
    candidate_key = email or name
    if not candidate_key:
        tests_map = entry.get("tests", {}) or {}
        session_ids = sorted(
            str((test_meta or {}).get("session_id", "")).strip().lower()
            for test_meta in tests_map.values()
            if str((test_meta or {}).get("session_id", "")).strip()
        )
        candidate_key = "|".join(session_ids)
    created_at = _parse_created_at(entry.get("created_at", ""))
    day_key = created_at.date().isoformat() if created_at else ""
    return created_by, batch_id, candidate_key, role, day_key


def _merge_entry_lists(primary: list[dict], secondary: list[dict]) -> list[dict]:
    merged = {}

    def _upsert(entry: dict):
        if not isinstance(entry, dict):
            return
        key = _entry_identity(entry)
        existing = merged.get(key)
        if existing is None:
            clone = dict(entry)
            clone["tests"] = dict(entry.get("tests", {}) or {})
            merged[key] = clone
            return

        existing_tests = existing.setdefault("tests", {})
        for rk, test in (entry.get("tests", {}) or {}).items():
            if rk not in existing_tests:
                existing_tests[rk] = test

        existing_dt = _parse_created_at(existing.get("created_at", ""))
        entry_dt = _parse_created_at(entry.get("created_at", ""))
        if entry_dt and (existing_dt is None or entry_dt > existing_dt):
            existing["created_at"] = entry.get("created_at", existing.get("created_at", ""))
            if entry.get("name"):
                existing["name"] = entry.get("name")
            if entry.get("role"):
                existing["role"] = entry.get("role")
            if entry.get("role_key"):
                existing["role_key"] = entry.get("role_key")
            if entry.get("batch_id"):
                existing["batch_id"] = entry.get("batch_id")

        if not existing.get("name") and entry.get("name"):
            existing["name"] = entry.get("name")
        if not existing.get("role") and entry.get("role"):
            existing["role"] = entry.get("role")

    for row in primary:
        _upsert(row)
    for row in secondary:
        _upsert(row)

    def _sort_key(entry: dict):
        dt = _parse_created_at(entry.get("created_at", ""))
        return dt or datetime.min.replace(tzinfo=timezone.utc)

    return sorted(merged.values(), key=_sort_key, reverse=True)


def _load_db_tests_for_user(user_email: str, since: datetime | None = None) -> list[dict]:
    """Best-effort DB fallback for generated tests when in-memory store is incomplete."""
    try:
        from app.extensions import db
        from app.models import TestLink
    except Exception:
        return []

    user_key = str(user_email or "").strip().lower()
    if not user_key:
        return []

    query = TestLink.query.filter(db.func.lower(TestLink.created_by) == user_key)
    if since is not None:
        query = query.filter(TestLink.created_at >= since)
    rows = query.order_by(TestLink.created_at.desc()).all()

    grouped = {}
    for row in rows:
        email = str(getattr(row, "candidate_email", "") or "").strip().lower()
        if not email:
            continue

        created_at = getattr(row, "created_at", None) or datetime.now(timezone.utc)
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)

        role_label = str(getattr(row, "role_label", "") or getattr(row, "role_key", "") or "General").strip()
        role_key = str(getattr(row, "role_key", "") or role_label).strip().lower()
        batch_id = str(getattr(row, "batch_id", "") or "").strip().lower()
        candidate_name = str(getattr(row, "candidate_name", "") or email).strip() or email
        dedupe_key = (
            user_key,
            batch_id,
            email or candidate_name.lower(),
            role_key,
            created_at.date().isoformat(),
        )

        entry = grouped.get(dedupe_key)
        if entry is None:
            entry = {
                "name": candidate_name,
                "email": email,
                "role": role_label,
                "role_key": str(getattr(row, "role_key", "") or "").strip(),
                "batch_id": str(getattr(row, "batch_id", "") or "").strip(),
                "tests": {},
                "created_by": user_key,
                "created_at": created_at.isoformat(),
                "status": "sent",
            }
            grouped[dedupe_key] = entry

        round_key = str(getattr(row, "round_key", "") or getattr(row, "session_id", "")).strip()
        if not round_key:
            continue

        test_type = str(getattr(row, "test_type", "") or "mcq").strip().lower()
        round_label = str(getattr(row, "round_label", "") or "").strip()
        if not round_label:
            if test_type == "coding":
                round_label = f"Coding {round_key}"
            else:
                round_label = f"Round {round_key}"

        session_id = str(getattr(row, "session_id", "") or "").strip()
        if not session_id:
            continue

        test_url = f"/coding/start/{session_id}" if test_type == "coding" else f"/mcq/start/{session_id}"
        entry["tests"][round_key] = {
            "session_id": session_id,
            "label": round_label,
            "url": test_url,
            "type": test_type,
        }

    def _sort_key(item: dict):
        dt = _parse_created_at(item.get("created_at", ""))
        return dt or datetime.min.replace(tzinfo=timezone.utc)

    return sorted(grouped.values(), key=_sort_key, reverse=True)


def _safe_db_tests_for_user(user_email: str, since: datetime | None = None) -> list[dict]:
    try:
        return _load_db_tests_for_user(user_email, since=since)
    except Exception:
        try:
            from app.extensions import db

            db.session.rollback()
        except Exception:
            pass
        return []


def add_generated_test(entry: dict):
    """Add or replace a generated test entry with user/timestamp tracking.

    For the same creator, email, role and calendar day, keep only the latest entry.
    """
    if "created_at" not in entry:
        entry["created_at"] = datetime.now(timezone.utc).isoformat()
    if "created_by" not in entry:
        entry["created_by"] = ""

    created = entry.get("created_at", "")
    entry_dt = None
    if isinstance(created, str):
        try:
            entry_dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            entry_dt = datetime.now(timezone.utc)
    elif isinstance(created, datetime):
        entry_dt = created
    else:
        entry_dt = datetime.now(timezone.utc)

    entry_day = entry_dt.date()
    entry_creator = str(entry.get("created_by", "")).lower()
    entry_email = str(entry.get("email", "")).lower()
    entry_name = str(entry.get("name", "")).strip().lower()
    entry_role = str(entry.get("role", "")).strip().lower()
    entry_role_key = str(entry.get("role_key", "")).strip().lower()
    entry_batch_id = str(entry.get("batch_id", "")).strip().lower()
    entry_candidate_key = entry_email or entry_name

    # Remove existing same-day duplicate records for same candidate+role by same creator.
    duplicate_indexes = []
    for idx, test in enumerate(GENERATED_TESTS):
        if str(test.get("created_by", "")).lower() != entry_creator:
            continue
        existing_email = str(test.get("email", "")).lower()
        existing_name = str(test.get("name", "")).strip().lower()
        existing_candidate_key = existing_email or existing_name
        if existing_candidate_key != entry_candidate_key:
            continue
        existing_role = str(test.get("role_key", "") or test.get("role", "")).strip().lower()
        if existing_role != (entry_role_key or entry_role):
            continue
        if str(test.get("batch_id", "")).strip().lower() != entry_batch_id:
            continue

        existing_created = test.get("created_at", "")
        if isinstance(existing_created, str):
            try:
                existing_dt = datetime.fromisoformat(existing_created.replace("Z", "+00:00"))
            except (ValueError, TypeError):
                continue
        elif isinstance(existing_created, datetime):
            existing_dt = existing_created
        else:
            continue

        if existing_dt.date() == entry_day:
            duplicate_indexes.append(idx)

    for idx in reversed(duplicate_indexes):
        GENERATED_TESTS.pop(idx)

    GENERATED_TESTS.append(entry)


def get_tests_for_user_today(user_email: str):
    """Return test entries created by a specific user in the retention window."""
    user_key = str(user_email or "").strip().lower()
    in_memory_results = []
    for t in GENERATED_TESTS:
        if str(t.get("created_by", "")).strip().lower() != user_key:
            continue
        dt = _parse_created_at(t.get("created_at", ""))
        if dt is None:
            continue
        if _within_retention(dt):
            in_memory_results.append(t)

    since = datetime.now(timezone.utc) - timedelta(days=SESSION_RETENTION_DAYS)
    db_results = _safe_db_tests_for_user(user_key, since=since)
    return _merge_entry_lists(in_memory_results, db_results)


def get_all_tests_today():
    """Return all test entries created in the retention window (all users)."""
    results = []
    for t in GENERATED_TESTS:
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
        if _within_retention(dt):
            results.append(t)
    return results


def get_tests_for_user_in_range(user_email: str, since: datetime):
    """Return test entries created by user since a given datetime."""
    user_key = str(user_email or "").strip().lower()
    in_memory_results = []
    for t in GENERATED_TESTS:
        if str(t.get("created_by", "")).strip().lower() != user_key:
            continue
        dt = _parse_created_at(t.get("created_at", ""))
        if dt is None:
            continue
        if dt >= since:
            in_memory_results.append(t)

    db_results = _safe_db_tests_for_user(user_key, since=since)
    return _merge_entry_lists(in_memory_results, db_results)


def delete_generated_tests_for_user(user_email: str, items: list[dict]) -> int:
    """Delete generated test entries for a user and return removed count.

    Each item may include: email (required), role (optional), created_at (optional).
    Matching priority:
    1) created_by + email + role + created_at
    2) created_by + email + role
    3) created_by + email
    """
    if not isinstance(items, list):
        return 0

    removed = 0
    user_key = str(user_email or "").strip().lower()

    for raw_item in items:
        if not isinstance(raw_item, dict):
            continue

        email_key = str(raw_item.get("email", "")).strip().lower()
        if not email_key:
            continue

        role_key = str(raw_item.get("role", "")).strip().lower()
        created_at_key = str(raw_item.get("created_at", "")).strip()

        target_idx = None

        for idx in range(len(GENERATED_TESTS) - 1, -1, -1):
            entry = GENERATED_TESTS[idx]
            if str(entry.get("created_by", "")).strip().lower() != user_key:
                continue
            if str(entry.get("email", "")).strip().lower() != email_key:
                continue

            entry_role = str(entry.get("role", "")).strip().lower()
            entry_created = str(entry.get("created_at", "")).strip()

            if role_key and entry_role != role_key:
                continue
            if created_at_key and entry_created != created_at_key:
                continue

            target_idx = idx
            break

        # Fallback when created_at doesn't match exactly but email/role do.
        if target_idx is None and role_key:
            for idx in range(len(GENERATED_TESTS) - 1, -1, -1):
                entry = GENERATED_TESTS[idx]
                if str(entry.get("created_by", "")).strip().lower() != user_key:
                    continue
                if str(entry.get("email", "")).strip().lower() != email_key:
                    continue
                if str(entry.get("role", "")).strip().lower() != role_key:
                    continue
                target_idx = idx
                break

        # Last fallback by email only.
        if target_idx is None:
            for idx in range(len(GENERATED_TESTS) - 1, -1, -1):
                entry = GENERATED_TESTS[idx]
                if str(entry.get("created_by", "")).strip().lower() != user_key:
                    continue
                if str(entry.get("email", "")).strip().lower() != email_key:
                    continue
                target_idx = idx
                break

        if target_idx is not None:
            GENERATED_TESTS.pop(target_idx)
            removed += 1

    return removed


