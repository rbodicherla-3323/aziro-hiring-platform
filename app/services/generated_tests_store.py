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
