#!/usr/bin/env python3
"""
Export last N days usage stats (tests created, reports generated) to CSV.

Usage:
  python export_usage.py --days 15
  python export_usage.py --days 15 --out usage_15d.csv
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

from sqlalchemy import create_engine, text

try:
    from dotenv import load_dotenv
except Exception:  # pragma: no cover - optional dependency
    load_dotenv = None


def _load_env():
    if load_dotenv is None:
        return
    root = Path(__file__).resolve().parent
    load_dotenv(root / ".env")
    load_dotenv(root / ".env.production", override=True)


def _get_database_url() -> str:
    db_url = (os.getenv("DATABASE_URL") or "").strip()
    if not db_url:
        print("ERROR: DATABASE_URL is not set. Add it to .env.production or env.", file=sys.stderr)
        raise SystemExit(1)
    if db_url.startswith("postgres://"):
        db_url = "postgresql://" + db_url[len("postgres://") :]
    if not db_url.startswith("postgresql://"):
        scheme = db_url.split(":", 1)[0] if ":" in db_url else db_url
        print(f"ERROR: DATABASE_URL must be postgresql://..., got {scheme}://", file=sys.stderr)
        raise SystemExit(1)
    return db_url


def _safe_iso(value) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.isoformat()
    return str(value)


def _query_rows(engine, sql: str, params: dict) -> list[dict]:
    with engine.connect() as conn:
        rows = conn.execute(text(sql), params).mappings().all()
    return [dict(r) for r in rows]


def export_usage(days: int, out_path: str | None):
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=int(days))

    engine = create_engine(_get_database_url())

    tests_sql = """
        SELECT
          created_by AS user_email,
          COUNT(*) AS tests_created,
          COUNT(DISTINCT candidate_email) AS candidates,
          MIN(created_at) AS first_test,
          MAX(created_at) AS last_test
        FROM test_links
        WHERE created_by <> ''
          AND created_at >= :start
          AND created_at < :end
        GROUP BY created_by
        ORDER BY tests_created DESC;
    """

    reports_sql = """
        SELECT
          generated_by AS user_email,
          COUNT(*) AS reports_generated,
          MIN(created_at) AS first_report,
          MAX(created_at) AS last_report
        FROM reports
        WHERE generated_by <> ''
          AND created_at >= :start
          AND created_at < :end
        GROUP BY generated_by
        ORDER BY reports_generated DESC;
    """

    combined_sql = """
        WITH tests AS (
          SELECT
            created_by AS user_email,
            COUNT(*) AS tests_created,
            COUNT(DISTINCT candidate_email) AS candidates,
            MIN(created_at) AS first_test,
            MAX(created_at) AS last_test
          FROM test_links
          WHERE created_by <> ''
            AND created_at >= :start
            AND created_at < :end
          GROUP BY created_by
        ),
        reports AS (
          SELECT
            generated_by AS user_email,
            COUNT(*) AS reports_generated,
            MIN(created_at) AS first_report,
            MAX(created_at) AS last_report
          FROM reports
          WHERE generated_by <> ''
            AND created_at >= :start
            AND created_at < :end
          GROUP BY generated_by
        )
        SELECT
          COALESCE(t.user_email, r.user_email) AS user_email,
          COALESCE(t.tests_created, 0) AS tests_created,
          COALESCE(t.candidates, 0) AS candidates,
          COALESCE(r.reports_generated, 0) AS reports_generated,
          t.first_test,
          t.last_test,
          r.first_report,
          r.last_report
        FROM tests t
        FULL OUTER JOIN reports r
          ON lower(t.user_email) = lower(r.user_email)
        ORDER BY tests_created DESC NULLS LAST, reports_generated DESC NULLS LAST;
    """

    params = {"start": start, "end": now}
    combined = _query_rows(engine, combined_sql, params)
    tests = _query_rows(engine, tests_sql, params)
    reports = _query_rows(engine, reports_sql, params)

    if not out_path:
        stamp = now.strftime("%Y%m%d_%H%M%S")
        out_path = f"usage_last_{days}_days_{stamp}.csv"

    out_file = Path(out_path)
    fieldnames = [
        "user_email",
        "tests_created",
        "candidates",
        "reports_generated",
        "first_test",
        "last_test",
        "first_report",
        "last_report",
    ]

    with out_file.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in combined:
            writer.writerow(
                {
                    "user_email": row.get("user_email", ""),
                    "tests_created": row.get("tests_created", 0),
                    "candidates": row.get("candidates", 0),
                    "reports_generated": row.get("reports_generated", 0),
                    "first_test": _safe_iso(row.get("first_test")),
                    "last_test": _safe_iso(row.get("last_test")),
                    "first_report": _safe_iso(row.get("first_report")),
                    "last_report": _safe_iso(row.get("last_report")),
                }
            )

    print(f"Date range (UTC): {start.isoformat()} -> {now.isoformat()}")
    print(f"Wrote combined summary: {out_file.as_posix()}")
    print(f"Users with tests: {len(tests)}")
    print(f"Users with reports: {len(reports)}")


def main():
    parser = argparse.ArgumentParser(description="Export usage summary for last N days.")
    parser.add_argument("--days", type=int, default=15, help="Number of days to include (default: 15).")
    parser.add_argument("--out", type=str, default="", help="Output CSV path.")
    args = parser.parse_args()

    _load_env()
    export_usage(days=max(1, args.days), out_path=args.out or None)


if __name__ == "__main__":
    main()
