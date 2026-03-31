import json
from datetime import datetime, timezone
from pathlib import Path


STORE_FILE = Path("app/runtime/coding_submissions.jsonl")


def _utc_now_iso():
    return datetime.now(timezone.utc).isoformat()


def save_coding_submission(
    *,
    session_id: str,
    email: str,
    round_key: str,
    round_label: str,
    role: str,
    language: str,
    question_title: str,
    question_text: str,
    submitted_code: str,
    starter_code: str = "",
    role_key: str = "",
    batch_id: str = "",
):
    STORE_FILE.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "ts": _utc_now_iso(),
        "session_id": session_id,
        "email": email,
        "round_key": round_key,
        "round_label": round_label,
        "role": role,
        "language": language,
        "question_title": question_title,
        "question_text": question_text,
        "submitted_code": submitted_code,
        "starter_code": starter_code,
        "role_key": role_key,
        "batch_id": batch_id,
    }
    with STORE_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def get_latest_coding_submission(
    email: str,
    round_key: str = "L4",
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
    with STORE_FILE.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue

            if str(rec.get("email", "")).strip().lower() != email_key or rec.get("round_key") != round_key:
                continue
            if session_id_filter and str(rec.get("session_id", "")).strip() != session_id_filter:
                continue
            if role_key_filter and str(rec.get("role_key", "")).strip().lower() != role_key_filter:
                continue
            if batch_id_filter and str(rec.get("batch_id", "")).strip().lower() != batch_id_filter:
                continue
            latest = rec

    return latest
