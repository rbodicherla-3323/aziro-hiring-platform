import os
import sys
import time
from pathlib import Path

# Add the project root to Python path
project_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(project_root))

from app.scripts.cleanup_enqueue import enqueue_cleanup

DEFAULT_DAYS = int(os.getenv("DB_CLEANUP_DAYS", "1"))
SCHEDULE_INTERVAL_SECONDS = int(os.getenv("DB_CLEANUP_INTERVAL_SECONDS", str(24 * 60 * 60)))


def schedule_daily_cleanup(days: int = DEFAULT_DAYS, interval_seconds: int = SCHEDULE_INTERVAL_SECONDS) -> None:
    print(
        f"Starting cleanup scheduler: enqueue every {interval_seconds} seconds "
        f"for records older than {days} days"
    )

    while True:
        enqueue_cleanup(days)
        time.sleep(interval_seconds)


if __name__ == "__main__":
    schedule_daily_cleanup()
