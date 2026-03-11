import os
from pathlib import Path
from urllib.parse import urlparse

import psycopg2
from psycopg2.extras import RealDictCursor

try:
    from dotenv import load_dotenv
except Exception:  # pragma: no cover
    load_dotenv = None


def _load_env_files() -> None:
    """Load project-level .env files for local script runs."""
    if not load_dotenv:
        return
    project_root = Path(__file__).resolve().parents[2]
    load_dotenv(project_root / ".env")


def _describe_database_url(dsn: str) -> str:
    # Never print the raw DSN because it includes credentials.
    try:
        u = urlparse(dsn)
        host = u.hostname or "?"
        port = u.port or 5432
        user = u.username or "?"
        dbname = (u.path or "").lstrip("/") or "?"
        return f"host={host} port={port} db={dbname} user={user}"
    except Exception:
        return "(unparseable DATABASE_URL)"


def main() -> int:
    _load_env_files()

    database_url = (os.getenv("DATABASE_URL") or "").strip()

    if database_url.startswith("postgres://"):
        database_url = "postgresql://" + database_url[len("postgres://") :]

    if database_url:
        print(f"Connecting using DATABASE_URL: {_describe_database_url(database_url)}")
        try:
            conn = psycopg2.connect(database_url, cursor_factory=RealDictCursor)
        except Exception as exc:
            print(f"DB connection failed (DATABASE_URL): {exc}")
            return 1
    else:
        # Fallback (local): explicit params.
        dbname = os.getenv("DB_NAME", "aziro_hiring")
        user = os.getenv("DB_USER", "aziro")
        password = os.getenv("DB_PASSWORD", "")
        host = os.getenv("DB_HOST", "localhost")
        port = int(os.getenv("DB_PORT", "5432"))

        print(f"Connecting using params: host={host} port={port} db={dbname} user={user}")
        try:
            conn = psycopg2.connect(
                dbname=dbname,
                user=user,
                password=password,
                port=port,
                host=host,
                cursor_factory=RealDictCursor,
            )
        except Exception as exc:
            print(f"DB connection failed (params): {exc}")
            return 1

    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("SELECT current_database() AS db, current_user AS user, version() AS version;")
                row = cur.fetchone()
                print("Connected successfully.")
                print(row)
    finally:
        conn.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())