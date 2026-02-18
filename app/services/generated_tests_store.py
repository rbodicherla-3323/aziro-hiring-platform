# filepath: d:\Projects\aziro-hiring-platform\app\services\generated_tests_store.py
"""
In-memory store for generated test entries (per-server session).
Each entry tracks: name, email, role, tests dict, created_by, created_at.
"""
from datetime import datetime, timezone, timedelta

GENERATED_TESTS = []


def add_generated_test(entry: dict):
    """Add a generated test entry with user/timestamp tracking."""
    if "created_at" not in entry:
        entry["created_at"] = datetime.now(timezone.utc).isoformat()
    if "created_by" not in entry:
        entry["created_by"] = ""
    GENERATED_TESTS.append(entry)


def get_tests_for_user_today(user_email: str):
    """Return test entries created by a specific user today."""
    today = datetime.now(timezone.utc).date()
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
        if dt.date() == today:
            results.append(t)
    return results


def get_all_tests_today():
    """Return all test entries created today (all users)."""
    today = datetime.now(timezone.utc).date()
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
        if dt.date() == today:
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
