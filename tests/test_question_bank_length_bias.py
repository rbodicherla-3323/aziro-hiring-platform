import json
from pathlib import Path

from app.services.question_bank.helpers import normalize_text


DATA_DIR = Path("app/services/question_bank/data")


def _iter_questions_from_payload(payload):
    if isinstance(payload, dict) and isinstance(payload.get("questions"), list):
        return payload["questions"]
    if isinstance(payload, list):
        return payload
    return []


def _has_unique_extreme_correct(options, correct):
    lengths = [len(normalize_text(option)) for option in options]
    answer_index = options.index(correct)
    longest = max(lengths)
    shortest = min(lengths)
    unique_longest_correct = lengths.count(longest) == 1 and lengths[answer_index] == longest
    unique_shortest_correct = lengths.count(shortest) == 1 and lengths[answer_index] == shortest
    return unique_longest_correct or unique_shortest_correct


def test_all_question_banks_have_no_unique_longest_or_shortest_correct_answer():
    violations = []

    for path in sorted(DATA_DIR.rglob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        for idx, row in enumerate(_iter_questions_from_payload(payload), start=1):
            if not isinstance(row, dict):
                continue
            options = row.get("options")
            correct = row.get("correct_answer")
            if not isinstance(options, list) or len(options) < 2 or correct not in options:
                continue
            if _has_unique_extreme_correct(options, correct):
                qid = row.get("id") or f"index-{idx}"
                rel = path.as_posix().split("app/services/question_bank/data/", 1)[-1]
                violations.append(f"{rel}:{qid}")

    assert not violations, f"Length-bias violations found: {violations[:20]}"
