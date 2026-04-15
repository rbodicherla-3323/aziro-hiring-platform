import json
import os
import signal
import sys
import time
from pathlib import Path

# Add the project root to Python path
project_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(project_root))

from redis import Redis

from app import create_app
from app.services.db_cleanup import cleanup_candidate_test_data_older_than

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
QUEUE_NAME = os.getenv("DB_CLEANUP_QUEUE", "db_cleanup")
POLL_TIMEOUT = int(os.getenv("DB_CLEANUP_POLL_TIMEOUT", "5"))


def get_redis_connection() -> Redis:
    return Redis.from_url(REDIS_URL, decode_responses=True)


def run_worker() -> None:
    app = create_app()
    with app.app_context():
        redis_conn = get_redis_connection()
        print(f"Starting Redis cleanup worker on queue '{QUEUE_NAME}' ({REDIS_URL})")

        def handle_shutdown(signum, frame):
            print("Shutdown requested, exiting worker...")
            sys.exit(0)

        signal.signal(signal.SIGINT, handle_shutdown)
        signal.signal(signal.SIGTERM, handle_shutdown)

        while True:
            item = redis_conn.blpop(QUEUE_NAME, timeout=POLL_TIMEOUT)
            if item is None:
                continue

            _, payload = item
            try:
                job_data = json.loads(payload)
                days = int(job_data.get("days", 1))
            except (ValueError, TypeError, json.JSONDecodeError):
                print(f"Skipping malformed job payload: {payload}")
                continue

            print(f"Processing cleanup job for records older than {days} days")
            result = cleanup_candidate_test_data_older_than(days)
            print(f"Cleanup finished: {result}")
            time.sleep(0.1)


if __name__ == "__main__":
    run_worker()
