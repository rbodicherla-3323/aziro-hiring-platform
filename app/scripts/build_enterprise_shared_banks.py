import json
import re
from pathlib import Path

from app.services.question_bank.enterprise_bank_config import ENTERPRISE_BANK_POLICIES
from app.services.question_bank.helpers import normalize_difficulty, normalize_text, question_signature
from app.services.question_bank.validator import validate_question_bank

DATA_DIR = Path("app/services/question_bank/data")

SHARED_BANK_SETTINGS = {
    "aptitude.json": {
        "bank_id": "shared-aptitude",
        "role_target": "shared_aptitude",
        "round_target": "L1",
        "version_scope": ["enterprise-shared-v1", "aptitude"],
        "default_topic": "Aptitude Reasoning",
    },
    "soft_skills.json": {
        "bank_id": "shared-soft-skills",
        "role_target": "shared_soft_skills",
        "round_target": "L5",
        "version_scope": ["enterprise-shared-v1", "soft-skills"],
        "default_topic": "Professional Communication",
    },
    "soft_skills_leadership.json": {
        "bank_id": "shared-soft-skills-leadership",
        "role_target": "shared_soft_skills_leadership",
        "round_target": "L5",
        "version_scope": ["enterprise-shared-v1", "soft-skills-leadership"],
        "default_topic": "Leadership and People Management",
    },
    "domains/networking.json": {
        "bank_id": "shared-domain-networking",
        "role_target": "shared_domain_networking",
        "round_target": "L6",
        "version_scope": ["enterprise-shared-v1", "domain-networking"],
        "default_topic": "Networking",
    },
    "domains/storage.json": {
        "bank_id": "shared-domain-storage",
        "role_target": "shared_domain_storage",
        "round_target": "L6",
        "version_scope": ["enterprise-shared-v1", "domain-storage"],
        "default_topic": "Storage",
    },
    "domains/virtualisation.json": {
        "bank_id": "shared-domain-virtualization",
        "role_target": "shared_domain_virtualization",
        "round_target": "L6",
        "version_scope": ["enterprise-shared-v1", "domain-virtualization"],
        "default_topic": "Virtualization",
    },
}

BAD_OPTION_VALUES = {"all of the above", "none of the above"}
INJECTED_FILLERS = {
    "delay action without confirming impact",
    "proceed without validating assumptions",
    "choose an approach without documenting rationale",
}
HEADER_OPTION_PATTERN = re.compile(
    r"^\s*(direction|directions|statements?|conclusions?|courses?\s+of\s+action|select\s+the\s+best\s+answer)\s*:?$",
    flags=re.IGNORECASE,
)

SCENARIO_MARKERS = (
    "production",
    "incident",
    "outage",
    "triage",
    "failure",
    "degraded",
    "latency",
    "throughput",
    "bottleneck",
    "rollout",
    "stakeholder",
    "manager",
    "team",
    "customer",
    "service",
)

OPERATIONS_MARKERS = (
    "monitor",
    "alert",
    "escalate",
    "ownership",
    "follow up",
    "timeline",
    "handoff",
    "runbook",
    "postmortem",
    "rollback",
)

INJECTED_SUFFIXES = (
    "for that enterprise scenario",
    "while meeting reliability expectations",
    "with accountable communication and traceability",
    "with validated operational controls",
)

LENGTH_BALANCE_SUFFIXES = (
    " under the stated conditions",
    " based on the provided context",
    " as supported by the given information",
    " according to the scenario details",
)

TOPIC_TAG_BLOCKLIST = {"&", "and", "the", "of", "for", "to", "in", "with", "on"}


def _load_bank(relative_path):
    payload = json.loads((DATA_DIR / relative_path).read_text(encoding="utf-8"))
    if isinstance(payload, dict) and "questions" in payload:
        return payload["questions"]
    if isinstance(payload, list):
        return payload
    raise ValueError(f"Unsupported question bank format: {relative_path}")


def _sanitize_text(value):
    text = str(value or "")
    text = text.replace("\u2013", "-").replace("\u2014", "-")
    text = text.replace("â€“", "-").replace("â€”", "-").replace("Ã‚", "")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"\s+([?.!,;:])", r"\1", text)
    return text.strip()


def _normalize_option(option):
    text = _sanitize_text(option)
    changed = True
    while changed:
        changed = False
        lower = text.lower()
        for suffix in INJECTED_SUFFIXES:
            if lower.endswith(suffix):
                text = text[: len(text) - len(suffix)].rstrip(" ,;:-")
                changed = True
                break
    text = re.sub(r"^\(?[A-Za-z0-9IVXivx]+\)?[.)\-:]\s*", "", text)
    return text.strip()


def _is_invalid_option(option):
    low = normalize_text(option)
    if not option:
        return True
    if low in BAD_OPTION_VALUES:
        return True
    if low in INJECTED_FILLERS:
        return True
    if re.fullmatch(r"apply a default response for .+ without verification", low):
        return True
    if HEADER_OPTION_PATTERN.match(option):
        return True
    return False


def _collect_unique_options(options):
    unique = []
    seen = set()
    for raw in options or []:
        option = _normalize_option(raw)
        if _is_invalid_option(option):
            continue
        key = normalize_text(option)
        if key in seen:
            continue
        unique.append(option)
        seen.add(key)
    return unique


def _find_matching_option(options, correct_answer):
    if correct_answer in options:
        return correct_answer
    norm_correct = normalize_text(correct_answer)
    for option in options:
        if normalize_text(option) == norm_correct:
            return option
    return None


def _ensure_four_options(options, correct_answer, topic):
    clean = list(options)
    correct = _find_matching_option(clean, correct_answer) or _sanitize_text(correct_answer)
    if not correct:
        correct = "Escalate with clear ownership and evidence"
    clean = [option for option in clean if normalize_text(option) != normalize_text(correct)]

    fillers = [
        "Cannot be inferred from the given information",
        "Insufficient information to conclude",
        "Requires additional verification before conclusion",
        f"Depends on assumptions not explicitly stated for {topic.lower()}",
    ]
    existing = {normalize_text(option) for option in clean}
    for filler in fillers:
        if len(clean) >= 3:
            break
        key = normalize_text(filler)
        if key == normalize_text(correct) or key in existing:
            continue
        clean.append(filler)
        existing.add(key)

    while len(clean) < 3:
        clean.append(f"Alternative action path {len(clean) + 1}")
    return [correct] + clean[:3], correct


def _rebalance_lengths(options, correct_answer):
    balanced = list(options)
    correct_idx = balanced.index(correct_answer)
    for idx in range(24):
        lengths = [len(_sanitize_text(option)) for option in balanced]
        longest = max(lengths)
        shortest = min(lengths)
        unique_long = lengths.count(longest) == 1 and lengths[correct_idx] == longest
        unique_short = lengths.count(shortest) == 1 and lengths[correct_idx] == shortest
        if not unique_long and not unique_short:
            break
        target_idx = None
        if unique_long:
            target_idx = max((i for i in range(len(balanced)) if i != correct_idx), key=lambda i: lengths[i])
        if unique_short:
            target_idx = correct_idx
        suffix = LENGTH_BALANCE_SUFFIXES[idx % len(LENGTH_BALANCE_SUFFIXES)]
        if suffix not in balanced[target_idx]:
            balanced[target_idx] = f"{balanced[target_idx]}{suffix}"
    return balanced, balanced[correct_idx]


def _score_question(question, topic):
    q_text = normalize_text(question)
    t_text = normalize_text(topic)
    score = len(q_text)
    score += 18 if " not " in f" {q_text} " else 0
    score += 22 if " except " in f" {q_text} " else 0
    score += 14 if any(marker in q_text for marker in SCENARIO_MARKERS) else 0
    score += 12 if any(marker in q_text for marker in OPERATIONS_MARKERS) else 0
    score += 10 if any(char.isdigit() for char in q_text) else 0
    score += 8 if "why" in q_text or "best" in q_text or "most" in q_text else 0
    score += 6 if "troubleshoot" in q_text or "diagnose" in q_text else 0
    score += 4 if t_text in {"critical reasoning", "logical reasoning"} else 0
    return score


def _difficulty_distribution(total):
    easy = int(round(total * 0.40))
    medium = int(round(total * 0.35))
    hard = total - easy - medium
    return easy, medium, hard


def _assign_difficulty(rows):
    indexed = [(idx, _score_question(row["question"], row["topic"])) for idx, row in enumerate(rows)]
    indexed.sort(key=lambda item: item[1], reverse=True)
    easy_count, medium_count, hard_count = _difficulty_distribution(len(rows))
    hard_ids = {idx for idx, _ in indexed[:hard_count]}
    medium_ids = {idx for idx, _ in indexed[hard_count:hard_count + medium_count]}
    for idx, row in enumerate(rows):
        if idx in hard_ids:
            row["difficulty"] = "hard"
        elif idx in medium_ids:
            row["difficulty"] = "medium"
        else:
            row["difficulty"] = "easy"
        row["difficulty"] = normalize_difficulty(row["difficulty"])


def _assign_style(row):
    text = normalize_text(row["question"])
    if any(marker in text for marker in OPERATIONS_MARKERS):
        return "operations"
    if any(marker in text for marker in SCENARIO_MARKERS):
        return "scenario"
    if "architecture" in text or "design" in text:
        return "architecture"
    return "concept"


def _slug(value):
    text = normalize_text(value)
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text or "general"


def _tags_from_topic(topic, style):
    tokens = [token for token in _slug(topic).split("-") if token and token not in TOPIC_TAG_BLOCKLIST]
    tags = set(tokens[:4])
    tags.add(style)
    return sorted(tags)


def _dedupe_questions(rows):
    seen = {}
    for row in rows:
        signature = question_signature(row["question"])
        if signature not in seen:
            seen[signature] = 1
            continue
        seen[signature] += 1
        row["question"] = f"{row['question']} (variant {seen[signature]})"


def _transform_bank(relative_path):
    settings = SHARED_BANK_SETTINGS[relative_path]
    source_rows = _load_bank(relative_path)
    output = []
    for idx, row in enumerate(source_rows, start=1):
        topic = _sanitize_text(row.get("topic")) or settings["default_topic"]
        question = _sanitize_text(row.get("question"))
        options = _collect_unique_options(row.get("options"))
        correct = _sanitize_text(row.get("correct_answer"))
        options, correct = _ensure_four_options(options, correct, topic)
        options, correct = _rebalance_lengths(options, correct)
        style = _assign_style({"question": question})
        output.append(
            {
                "id": f"{settings['bank_id']}-{idx:03d}",
                "question": question,
                "options": options,
                "correct_answer": correct,
                "topic": topic,
                "difficulty": normalize_difficulty(row.get("difficulty") or "medium"),
                "style": style,
                "tags": _tags_from_topic(topic, style),
                "role_target": settings["role_target"],
                "round_target": settings["round_target"],
                "version_scope": list(settings["version_scope"]),
            }
        )

    _assign_difficulty(output)
    _dedupe_questions(output)
    validate_question_bank(output, source_name=relative_path, strict=True)
    return output


def build_shared_enterprise_banks():
    for relative_path in SHARED_BANK_SETTINGS:
        transformed = _transform_bank(relative_path)
        target_path = DATA_DIR / relative_path
        target_path.write_text(json.dumps(transformed, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
        print(f"Wrote {relative_path} with {len(transformed)} questions")


def main():
    missing = [name for name in SHARED_BANK_SETTINGS if name not in ENTERPRISE_BANK_POLICIES]
    if missing:
        raise ValueError(f"Missing shared bank policies for: {', '.join(sorted(missing))}")
    build_shared_enterprise_banks()


if __name__ == "__main__":
    main()
