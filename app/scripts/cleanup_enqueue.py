import json
import os
import sys
from pathlib import Path

# Add the project root to Python path
project_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(project_root))

from redis import Redis

from app import create_app

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
QUEUE_NAME = os.getenv("DB_CLEANUP_QUEUE", "db_cleanup")
DEFAULT_DAYS = int(os.getenv("DB_CLEANUP_DAYS", "0"))


def get_redis_connection() -> Redis:
    return Redis.from_url(REDIS_URL, decode_responses=True)


def enqueue_cleanup(days: int = DEFAULT_DAYS) -> None:
    app = create_app()
    with app.app_context():
        redis_conn = get_redis_connection()
        payload = json.dumps({"days": days})
        redis_conn.rpush(QUEUE_NAME, payload)
        print(f"Enqueued cleanup job for records older than {days} days")


if __name__ == "__main__":
    enqueue_cleanup()
