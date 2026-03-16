import json
from pathlib import Path

from app.services.question_bank.helpers import rebalance_option_lengths


DATA_DIR = Path("app/services/question_bank/data")


def _iter_question_bank_files():
    return sorted(DATA_DIR.rglob("*.json"))


def _load_questions(path: Path):
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict) and isinstance(payload.get("questions"), list):
        return payload, payload["questions"], True
    if isinstance(payload, list):
        return payload, payload, False
    return payload, None, None


def _save_payload(path: Path, payload):
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _rebalance_bank_questions(questions):
    changed = 0
    candidates = 0
    for row in questions:
        if not isinstance(row, dict):
            continue
        options = row.get("options")
        correct = row.get("correct_answer")
        if not isinstance(options, list) or len(options) < 2 or correct not in options:
            continue
        candidates += 1
        new_options, new_correct = rebalance_option_lengths(options, correct)
        if new_options != options or new_correct != correct:
            row["options"] = new_options
            row["correct_answer"] = new_correct
            changed += 1
    return candidates, changed


def main():
    total_files = 0
    processed_files = 0
    total_candidates = 0
    total_changed = 0

    for path in _iter_question_bank_files():
        total_files += 1
        payload, questions, _ = _load_questions(path)
        if questions is None:
            continue
        candidates, changed = _rebalance_bank_questions(questions)
        if changed:
            _save_payload(path, payload)
            processed_files += 1
        total_candidates += candidates
        total_changed += changed

    print(f"Scanned files: {total_files}")
    print(f"Updated files: {processed_files}")
    print(f"Question candidates: {total_candidates}")
    print(f"Questions changed: {total_changed}")


if __name__ == "__main__":
    main()
