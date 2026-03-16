# filepath: d:\Projects\aziro-hiring-platform\app\services\generated_tests_store.py
"""
In-memory store for generated test entries (per-server session).
Each entry tracks: name, email, role, tests dict, created_by, created_at.
"""
from datetime import datetime, timezone, timedelta
import os

GENERATED_TESTS = []


def _get_int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except Exception:
        return int(default)


SESSION_RETENTION_DAYS = _get_int_env("SESSION_RETENTION_DAYS", 7)


def _within_retention(dt: datetime) -> bool:
    now = datetime.now(timezone.utc)
    return dt >= (now - timedelta(days=SESSION_RETENTION_DAYS))


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
    entry_role = str(entry.get("role", "")).strip().lower()

    # Remove existing same-day duplicate records for same candidate+role by same creator.
    duplicate_indexes = []
    for idx, test in enumerate(GENERATED_TESTS):
        if str(test.get("created_by", "")).lower() != entry_creator:
            continue
        if str(test.get("email", "")).lower() != entry_email:
            continue
        if str(test.get("role", "")).strip().lower() != entry_role:
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
    results = []
    for t in GENERATED_TESTS:
        if t.get("created_by", "").lower() != user_email.lower():
            continue
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
    results = []
    for t in GENERATED_TESTS:
        if t.get("created_by", "").lower() != user_email.lower():
            continue
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
        if dt >= since:
            results.append(t)
    return results
