# aziro-hiring-platform
AI based Interview & Hiring Platform

## Periodic Redis cleanup for old candidate test data

This project now includes a Redis-backed queue and scheduler for cleaning up old test-related data.

### New scripts
- `app/scripts/cleanup_enqueue.py` — enqueue a one-off cleanup job into Redis
- `app/scripts/cleanup_worker.py` — run a Redis worker that processes cleanup jobs
- `app/scripts/cleanup_scheduler.py` — schedule daily cleanup jobs by enqueueing them periodically

### Requirements
Install dependencies after updating `requirements.txt`:

```bash
pip install -r requirements.txt
```

### Running cleanup manually

```bash
python app/scripts/cleanup_enqueue.py
```

### Starting the worker

```bash
python app/scripts/cleanup_worker.py
```

### Scheduling daily cleanup

```bash
python app/scripts/cleanup_scheduler.py
```

This registers a recurring cleanup job that runs every 24 hours by default.

### Environment variables

- `REDIS_URL` — Redis connection string (default: `redis://localhost:6379/0`)
- `DB_CLEANUP_QUEUE` — queue name (default: `db_cleanup`)
- `DB_CLEANUP_DAYS` — number of days to keep records (default: `30`)
- `DB_CLEANUP_INTERVAL_SECONDS` — scheduler interval in seconds (default: `86400`)
- `DB_CLEANUP_JOB_ID` — scheduler job identifier (default: `daily_db_cleanup`)
