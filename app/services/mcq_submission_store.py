import json
from datetime import datetime, timezone
from pathlib import Path


STORE_FILE = Path("app/runtime/mcq_submissions.jsonl")


def _utc_now_iso():
    return datetime.now(timezone.utc).isoformat()


def save_mcq_submission(
    *,
    session_id: str,
    email: str,
    round_key: str,
    round_label: str,
    role: str = "",
    role_key: str = "",
    batch_id: str = "",
    responses=None,
    attempted: int = 0,
    correct: int = 0,
    total_questions: int = 0,
    percentage: float = 0.0,
    status: str = "",
):
    STORE_FILE.parent.mkdir(parents=True, exist_ok=True)
    responses_value = list(responses or []) if isinstance(responses, list) else []
    record = {
        "ts": _utc_now_iso(),
        "session_id": str(session_id or "").strip(),
        "email": str(email or "").strip().lower(),
        "round_key": str(round_key or "").strip(),
        "round_label": str(round_label or "").strip(),
        "role": str(role or "").strip(),
        "role_key": str(role_key or "").strip(),
        "batch_id": str(batch_id or "").strip(),
        "attempted": int(attempted or 0),
        "correct": int(correct or 0),
        "total_questions": int(total_questions or 0),
        "percentage": float(percentage or 0),
        "status": str(status or "").strip(),
        "responses": responses_value,
    }
    with STORE_FILE.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def get_latest_mcq_submission(
    email: str,
    round_key: str,
    *,
    role_key: str = "",
    batch_id: str = "",
    session_id: str = "",
):
    if not STORE_FILE.exists():
        return None

    latest = None
    email_key = str(email or "").strip().lower()
    role_key_filter = str(role_key or "").strip().lower()
    batch_id_filter = str(batch_id or "").strip().lower()
    session_id_filter = str(session_id or "").strip()

    with STORE_FILE.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue

            if str(record.get("email", "")).strip().lower() != email_key:
                continue
            if str(record.get("round_key", "")).strip() != str(round_key or "").strip():
                continue
            if session_id_filter and str(record.get("session_id", "")).strip() != session_id_filter:
                continue
            if role_key_filter and str(record.get("role_key", "")).strip().lower() != role_key_filter:
                continue
            if batch_id_filter and str(record.get("batch_id", "")).strip().lower() != batch_id_filter:
                continue
            latest = record

    return latest
