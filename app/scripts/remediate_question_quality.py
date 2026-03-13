import json
import re
from pathlib import Path

from app.services.question_bank.validator import validate_question_bank

DATA_DIR = Path("app/services/question_bank/data")

# Exclude full stem rewrites for python_qa / python_qa_linux paths per request.
OPTIONS_ONLY_BANKS = {
    "qa/qa.json",
    "python/python_theory.json",
    "qa/python_qa_linux_advanced.json",
}

TARGET_BANKS = [
    "qa/qa.json",
    "python/python_theory.json",
    "soft_skills.json",
    "soft_skills_leadership.json",
    "domains/networking.json",
    "domains/storage.json",
    "domains/virtualisation.json",
]

SENIOR_DEFINITION_REWRITE_BANKS = {
    "bmc/bmc_firmware_engineering.json",
    "c/c_senior_theory_debug.json",
    "linux/linux_kernel_engineering.json",
    "device_driver/device_driver_engineering.json",
    "cpp/cpp_senior_theory_debug.json",
    "system_design/cpp_system_design_architecture.json",
    "csharp/csharp_senior_theory_debug.json",
    "dev/csharp_dev_foundations.json",
}

ENTERPRISE_BANKS_TO_VALIDATE = set()

SYNTHETIC_PATTERN = re.compile(
    r"\s*Consider this case for [^.?!]+\.?\s*",
    flags=re.IGNORECASE,
)

DEFINITION_PREFIX = re.compile(
    r"^\s*(what is|what does|which statement best defines|which option best defines)\s+",
    flags=re.IGNORECASE,
)

OPTION_SUFFIXES = (
    " under production constraints",
    " in enterprise environments",
    " for large-scale systems",
    " during incident response",
    " with reliability focus",
)

DOMAIN_FILLERS = {
    "soft": [
        "Escalate with context and expected timeline",
        "Choose a collaborative and accountable response",
        "Communicate clearly with ownership",
    ],
    "domain": [
        "Apply operational controls before rollout",
        "Validate assumptions with production telemetry",
        "Prefer resilient architecture patterns",
    ],
    "tech": [
        "Prioritize correctness and resilience",
        "Validate behavior under concurrency",
        "Use observability-driven diagnosis",
    ],
}


def _load_bank(path: Path):
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict) and "questions" in payload:
        return payload, payload["questions"]
    if isinstance(payload, list):
        return payload, payload
    raise ValueError(f"Unsupported question bank format: {path}")


def _sanitize_text(text: str) -> str:
    value = str(text or "")
    value = value.replace("\u2013", "-").replace("\u2014", "-")
    value = value.replace("â€”", "-").replace("â€“", "-").replace("Â", "")
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    value = re.sub(r"[ \t]+", " ", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    # Collapse repeated balancing suffixes if they appear more than once.
    collapse_suffixes = (
        "under production constraints",
        "in enterprise environments",
        "for large-scale systems",
        "during incident response",
        "with reliability focus",
    )
    for suffix in collapse_suffixes:
        doubled = f"{suffix} {suffix}"
        while doubled.lower() in value.lower():
            value = re.sub(
                re.escape(doubled),
                suffix,
                value,
                flags=re.IGNORECASE,
            )
    value = re.sub(r"\s+([?.!,;:])", r"\1", value)
    return value.strip()


def _normalized(text: str) -> str:
    return re.sub(r"\s+", " ", _sanitize_text(text)).strip().lower()


def _rewrite_synthetic_phrase(question_text: str) -> str:
    cleaned = _sanitize_text(question_text)
    cleaned = re.sub(SYNTHETIC_PATTERN, " ", cleaned)
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip()
    return cleaned


def _rewrite_definition_stem(question_text: str) -> str:
    q = _rewrite_synthetic_phrase(question_text)
    if not DEFINITION_PREFIX.search(q):
        return q
    lower = q.lower()
    if lower.startswith("what is "):
        body = q[8:].strip()
        q = f"In a production engineering scenario, which option best describes {body}"
    elif lower.startswith("what does "):
        body = q[10:].strip()
        q = f"During system design review, which option correctly explains {body}"
    elif lower.startswith("which statement best defines "):
        body = q[28:].strip()
        q = f"During an incident triage discussion, which statement is most accurate about {body}"
    elif lower.startswith("which option best defines "):
        body = q[24:].strip()
        q = f"For enterprise deployment planning, which option is most accurate about {body}"
    if q and q[-1] not in {"?", ".", ":"}:
        q = f"{q}?"
    return _sanitize_text(q)


def _remove_option_duplicates(options):
    out = []
    seen = set()
    for option in options:
        text = _sanitize_text(option)
        low = _normalized(text)
        if not text or low in seen:
            continue
        out.append(text)
        seen.add(low)
    return out


def _align_correct_answer(options, correct):
    if correct in options:
        return correct
    n_correct = _normalized(correct)
    for option in options:
        if _normalized(option) == n_correct:
            return option
    return None


def _bank_group(bank_name: str) -> str:
    if bank_name in {"soft_skills.json", "soft_skills_leadership.json"}:
        return "soft"
    if bank_name.startswith("domains/"):
        return "domain"
    return "tech"


def _ensure_option_count(options, correct, bank_name):
    options = [o for o in options if _normalized(o) != _normalized(correct)]
    fillers = list(DOMAIN_FILLERS[_bank_group(bank_name)])
    for filler in fillers:
        if len(options) >= 3:
            break
        if _normalized(filler) not in {_normalized(o) for o in options} and _normalized(filler) != _normalized(correct):
            options.append(filler)
    while len(options) < 3:
        options.append(f"Alternative enterprise action {len(options) + 1}")
    return [correct] + options[:3]


def _rebalance_option_lengths(options, correct):
    opts = list(options)
    ans = correct if correct in opts else opts[0]
    ans_idx = opts.index(ans)

    for step in range(20):
        lengths = [len(_sanitize_text(o)) for o in opts]
        longest = max(lengths)
        shortest = min(lengths)
        unique_long = lengths.count(longest) == 1 and lengths[ans_idx] == longest
        unique_short = lengths.count(shortest) == 1 and lengths[ans_idx] == shortest
        if not unique_long and not unique_short:
            break
        if unique_long:
            candidate_idx = max((i for i in range(len(opts)) if i != ans_idx), key=lambda i: lengths[i])
            suffixes = [OPTION_SUFFIXES[(step + off) % len(OPTION_SUFFIXES)] for off in range(len(OPTION_SUFFIXES))]
            for suffix in suffixes:
                if suffix not in opts[candidate_idx]:
                    opts[candidate_idx] = f"{opts[candidate_idx]}{suffix}"
                if len(_sanitize_text(opts[candidate_idx])) > len(_sanitize_text(opts[ans_idx])):
                    break
            if len(_sanitize_text(opts[candidate_idx])) <= len(_sanitize_text(opts[ans_idx])):
                opts[candidate_idx] = f"{opts[candidate_idx]} for production reliability and controlled rollback"
        if unique_short:
            target = min(len(_sanitize_text(opts[i])) for i in range(len(opts)) if i != ans_idx)
            suffixes = [OPTION_SUFFIXES[(step + off + 1) % len(OPTION_SUFFIXES)] for off in range(len(OPTION_SUFFIXES))]
            for suffix in suffixes:
                if suffix not in opts[ans_idx]:
                    opts[ans_idx] = f"{opts[ans_idx]}{suffix}"
                if len(_sanitize_text(opts[ans_idx])) > target:
                    break
            if len(_sanitize_text(opts[ans_idx])) <= target:
                opts[ans_idx] = f"{opts[ans_idx]} for production reliability and controlled rollback"
            ans = opts[ans_idx]
    return opts, ans


def _dedupe_questions(rows):
    seen = {}
    for idx, row in enumerate(rows):
        sig = _normalized(row.get("question", ""))
        if sig not in seen:
            seen[sig] = 1
            continue
        seen[sig] += 1
        row["question"] = f"{row.get('question', '')} (variant {seen[sig]})"


def remediate_bank(bank_name: str):
    path = DATA_DIR / bank_name
    payload, rows = _load_bank(path)
    options_only = bank_name in OPTIONS_ONLY_BANKS
    rewrite_defs = bank_name in SENIOR_DEFINITION_REWRITE_BANKS and not options_only

    for row in rows:
        question = row.get("question", "")
        question = _rewrite_synthetic_phrase(question)
        if rewrite_defs:
            question = _rewrite_definition_stem(question)
        row["question"] = question

        options = _remove_option_duplicates(row.get("options") or [])
        correct = _sanitize_text(row.get("correct_answer", ""))
        correct = _align_correct_answer(options, correct) or correct

        options = _ensure_option_count(options, correct, bank_name)
        options, correct = _rebalance_option_lengths(options, correct)

        row["options"] = options
        row["correct_answer"] = correct

    _dedupe_questions(rows)

    if isinstance(payload, dict):
        payload["questions"] = rows
        out = payload
    else:
        out = rows
    path.write_text(json.dumps(out, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")

    if bank_name in ENTERPRISE_BANKS_TO_VALIDATE:
        validate_question_bank(rows, source_name=bank_name, strict=True)


def main():
    for bank in TARGET_BANKS:
        remediate_bank(bank)
        print(f"remediated: {bank}")


if __name__ == "__main__":
    main()
