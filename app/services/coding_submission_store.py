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
    }
    with STORE_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def get_latest_coding_submission(email: str, round_key: str = "L4"):
    if not STORE_FILE.exists():
        return None

    latest = None
    with STORE_FILE.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue

            if rec.get("email") != email or rec.get("round_key") != round_key:
                continue
            latest = rec

    return latest
