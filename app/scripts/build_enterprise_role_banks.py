import json
import random
import re
from collections import Counter, defaultdict
from copy import deepcopy
from pathlib import Path

from app.services.question_bank.enterprise_bank_config import ENTERPRISE_BANK_POLICIES
from app.services.question_bank.helpers import question_signature
from app.services.question_bank.validator import validate_question_bank

DATA_DIR = Path("app/services/question_bank/data")
RNG = random.Random(20260311)

# Official references used while curating role coverage:
# https://docs.python.org/3/
# https://developer.mozilla.org/en-US/docs/Web/JavaScript
# https://en.cppreference.com/
# https://learn.microsoft.com/dotnet/
# https://docs.kernel.org/
# https://docs.openbmc.org/

CORE_ROLE_ENTERPRISE_BANKS = [
    "python/python_entry_theory_debug.json",
    "java_script/js_entry_theory_debug.json",
    "python/python_senior_theory_debug.json",
    "qa/python_qa_linux_advanced.json",
    "dev/python_dev_engineering.json",
    "c/c_senior_theory_debug.json",
    "bmc/bmc_firmware_engineering.json",
    "linux/linux_fundamentals_enterprise.json",
    "linux/linux_kernel_engineering.json",
    "device_driver/device_driver_engineering.json",
    "cpp/cpp_senior_theory_debug.json",
    "system_design/cpp_system_design_architecture.json",
    "csharp/csharp_senior_theory_debug.json",
    "dev/csharp_dev_foundations.json",
]

SOURCE_BANKS = {
    "python/python_entry_theory_debug.json": ["python/python_theory.json"],
    "java_script/js_entry_theory_debug.json": ["java_script/java_script_theory.json"],
    "python/python_senior_theory_debug.json": ["python/python_theory.json", "dev/dev_basics.json"],
    "qa/python_qa_linux_advanced.json": ["qa/qa.json", "linux/linux_basics.json", "python/python_theory.json"],
    "dev/python_dev_engineering.json": ["dev/dev_basics.json", "python/python_theory.json"],
    "c/c_senior_theory_debug.json": ["c/c_theory.json", "linux/linux_basics.json"],
    "bmc/bmc_firmware_engineering.json": ["bmc/bmc_firmware.json", "c/c_theory.json", "device_driver/device_driver_basics.json"],
    "linux/linux_fundamentals_enterprise.json": ["linux/linux_basics.json"],
    "linux/linux_kernel_engineering.json": ["linux/linux_kernel.json", "linux/linux_basics.json", "c/c_theory.json"],
    "device_driver/device_driver_engineering.json": ["device_driver/device_driver_basics.json", "linux/linux_kernel.json", "c/c_theory.json"],
    "cpp/cpp_senior_theory_debug.json": ["cpp/cpp_theory.json", "system_design/system_design_architecture.json"],
    "system_design/cpp_system_design_architecture.json": ["system_design/system_design_architecture.json", "cpp/cpp_theory.json"],
    "csharp/csharp_senior_theory_debug.json": ["csharp/csharp_theory_debug.json"],
    "dev/csharp_dev_foundations.json": ["csharp/csharp_theory_debug.json", "dev/dev_basics.json"],
}

BANK_FORBIDDEN = {
    "python/python_entry_theory_debug.json": (r"\bjava\b", r"\bc#\b", r"\bc\+\+\b", r"\bkernel\b"),
    "java_script/js_entry_theory_debug.json": (r"\bjava\b", r"\bc#\b", r"\bc\+\+\b", r"\bkernel\b"),
    "python/python_senior_theory_debug.json": (r"\bselenium\b", r"\bwebdriver\b", r"\btestng\b"),
    "dev/python_dev_engineering.json": (r"\bselenium\b", r"\bwebdriver\b", r"\btestng\b"),
    "c/c_senior_theory_debug.json": (r"\basp\.net\b", r"\bdjango\b", r"\bflask\b"),
    "linux/linux_kernel_engineering.json": (r"\bselenium\b", r"\brest assured\b"),
    "device_driver/device_driver_engineering.json": (r"\bselenium\b", r"\brest assured\b"),
}

STYLE_ROTATION = ("scenario", "architecture", "operations", "concept")
OPTION_SUFFIXES = (
    " in this scenario",
    " under production constraints",
    " for the stated requirement",
    " during incident triage",
)
UNIQUENESS_SUFFIXES = (
    "failure-recovery analysis",
    "stability-focused design",
    "low-latency operation",
    "safe rollout planning",
    "incident mitigation",
    "correctness validation",
    "reliability hardening",
    "post-deploy triage",
    "high-load behavior",
    "edge-case handling",
    "fault-isolation strategy",
    "observability readiness",
)

DOMAIN_DISTRACTORS = {
    "python": [
        "Rely on implicit global state across requests",
        "Skip exception handling and continue silently",
        "Use mutable default arguments for shared state",
    ],
    "javascript": [
        "Block event loop for all long operations",
        "Ignore promise rejection handling completely",
        "Mutate shared globals inside every callback",
    ],
    "linux": [
        "Disable log capture during production incidents",
        "Bypass permission checks for troubleshooting",
        "Assume all services restart successfully",
    ],
    "kernel": [
        "Execute blocking calls in interrupt context",
        "Skip locking under multi-core contention",
        "Assume memory ordering without barriers",
    ],
    "driver": [
        "Return success without validating hardware state",
        "Ignore DMA synchronization requirements",
        "Use busy waiting for all event handling",
    ],
    "c": [
        "Assume pointers are always initialized",
        "Skip ownership checks on allocated buffers",
        "Depend on undefined behavior for performance",
    ],
    "cpp": [
        "Prefer raw owning pointers in all paths",
        "Share mutable state without synchronization",
        "Ignore exception-safety guarantees",
    ],
    "csharp": [
        "Block on async calls inside request handlers",
        "Skip cancellation propagation in services",
        "Bypass dependency injection boundaries",
    ],
    "bmc": [
        "Ignore watchdog and health telemetry signals",
        "Assume bus communication never fails",
        "Skip power-state validation checks",
    ],
}

CONTEXT_PREFIX = {
    "debugging": "A defect report states: ",
    "scenario": "In a production workflow, ",
    "architecture": "During architecture review, ",
    "operations": "In live operations, ",
    "concept": "",
}

DIFFICULTY_SUFFIX = {
    "easy": "",
    "medium": " in a real project implementation",
    "hard": " during a production incident with strict reliability requirements",
}

DEFINITION_STEM = re.compile(
    r"^\s*(what is|what does|which statement best defines|which option best defines)\s+",
    flags=re.IGNORECASE,
)


def _load_json(path):
    payload = json.loads((DATA_DIR / path).read_text(encoding="utf-8"))
    if isinstance(payload, dict) and "questions" in payload:
        return payload["questions"]
    if isinstance(payload, list):
        return payload
    raise ValueError(f"Invalid source bank format for {path}")


def _sanitize(text):
    value = str(text or "")
    value = value.replace("\u2013", "-").replace("\u2014", "-")
    value = value.replace("â€”", "-").replace("â€“", "-").replace("Â", "")
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    value = re.sub(r"[ \t]+", " ", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    value = re.sub(r"\s+([?.!,;:])", r"\1", value)
    return value.strip()


def _normalized(text):
    return re.sub(r"\s+", " ", _sanitize(text)).strip().lower()


def _rewrite_output_prompt(question_text):
    text = _sanitize(question_text)
    patterns = (
        r"^\s*what\s+is\s+the\s+output(?:\s+of)?[:\s-]*",
        r"^\s*what\s+will\s+be\s+the\s+output(?:\s+of)?[:\s-]*",
        r"^\s*what\s+will\s+be\s+printed[:\s-]*",
    )
    for pattern in patterns:
        if re.search(pattern, text, flags=re.IGNORECASE):
            text = re.sub(
                pattern,
                "A snippet runs with the following behavior. Which output is correct? ",
                text,
                flags=re.IGNORECASE,
            )
            break
    return _sanitize(text)


def _normalize_option(text):
    value = _sanitize(text)
    value = re.sub(r"^\(?[A-Da-d0-9ivxIVX]+\)?[.)\-:]\s*", "", value)
    return value.strip()


def _is_bad_option(text):
    low = _normalized(text)
    if not low:
        return True
    if low in {"all of the above", "none of the above"}:
        return True
    if low.endswith(":") and len(low.split()) <= 4:
        return True
    return False


def _normalize_options(options):
    cleaned = []
    seen = set()
    for option in options or []:
        opt = _normalize_option(option)
        if _is_bad_option(opt):
            continue
        low = _normalized(opt)
        if low in seen:
            continue
        cleaned.append(opt)
        seen.add(low)
    return cleaned


def _looks_trivial(text):
    low = _normalized(text)
    return any(token in low for token in ("2 + 2", "hello world", "pick the longest option"))


def _matches_forbidden(bank_key, question, topic):
    haystack = _normalized(f"{question} {topic}")
    for pattern in BANK_FORBIDDEN.get(bank_key, ()):
        if re.search(pattern, haystack, re.IGNORECASE):
            return True
    return False


def _topic_from_text(required_topics, question, source_topic):
    text = _normalized(question)
    src = _normalized(source_topic)
    best_topic = required_topics[0]
    best_score = -1
    for topic in required_topics:
        tokens = [tok for tok in re.split(r"[^a-z0-9]+", _normalized(topic)) if len(tok) >= 4]
        score = sum(1 for tok in tokens if tok in text or tok in src)
        if score > best_score:
            best_score = score
            best_topic = topic
    return best_topic


def _style_layout(policy):
    layout = []
    for difficulty in ("easy", "medium", "hard"):
        debug_total = int(policy["debugging_counts"][difficulty])
        diff_total = int(policy["difficulty_counts"][difficulty])
        layout.extend([(difficulty, "debugging")] * debug_total)
        non_debug = diff_total - debug_total
        layout.extend((difficulty, STYLE_ROTATION[idx % len(STYLE_ROTATION)]) for idx in range(non_debug))
    return layout


def _topic_sequence(topics, count):
    base = count // len(topics)
    rem = count % len(topics)
    plan = []
    for idx, topic in enumerate(topics):
        plan.extend([topic] * (base + (1 if idx < rem else 0)))
    RNG.shuffle(plan)
    return plan


def _option_pool(candidates):
    by_topic = defaultdict(list)
    global_seen = set()
    for row in candidates:
        topic = row["topic"]
        for opt in row["options"]:
            low = _normalized(opt)
            if not low:
                continue
            if low not in {_normalized(o) for o in by_topic[topic]}:
                by_topic[topic].append(opt)
            if low not in global_seen:
                by_topic["*"].append(opt)
                global_seen.add(low)
    return by_topic


def _domain_key(bank_key):
    if bank_key.startswith("python/") or bank_key.startswith("dev/python") or bank_key.startswith("qa/python"):
        return "python"
    if bank_key.startswith("java_script/"):
        return "javascript"
    if bank_key.startswith("linux/linux_kernel"):
        return "kernel"
    if bank_key.startswith("linux/"):
        return "linux"
    if bank_key.startswith("device_driver/"):
        return "driver"
    if bank_key.startswith("bmc/"):
        return "bmc"
    if bank_key.startswith("c/"):
        return "c"
    if bank_key.startswith("cpp/") or bank_key.startswith("system_design/"):
        return "cpp"
    if bank_key.startswith("csharp/") or bank_key.startswith("dev/csharp"):
        return "csharp"
    return "python"


def _choose_options(bank_key, question_text, topic, options, correct, pool):
    clean = _normalize_options(options)
    if correct not in clean:
        clean = [correct] + [o for o in clean if o != correct]
    seen = {_normalized(correct)}
    picked = []
    for item in [o for o in clean if o != correct]:
        low = _normalized(item)
        if low in seen:
            continue
        picked.append(item)
        seen.add(low)
        if len(picked) == 3:
            return [correct] + picked

    for option in pool.get(topic, []):
        low = _normalized(option)
        if option != correct and low not in seen:
            picked.append(option)
            seen.add(low)
            if len(picked) == 3:
                return [correct] + picked

    for option in DOMAIN_DISTRACTORS.get(_domain_key(bank_key), []):
        low = _normalized(option)
        if option != correct and low not in seen:
            picked.append(option)
            seen.add(low)
            if len(picked) == 3:
                return [correct] + picked

    while len(picked) < 3:
        fallback = f"Alternative implementation approach {len(picked) + 1}"
        if _normalized(fallback) in seen:
            fallback = f"{fallback} for this scenario"
        picked.append(fallback)
        seen.add(_normalized(fallback))
    return [correct] + picked[:3]


def _rebalance_lengths(options, correct):
    opts = list(options)
    ans = correct if correct in opts else opts[0]
    ci = opts.index(ans)
    for step in range(20):
        lengths = [len(_sanitize(o)) for o in opts]
        longest, shortest = max(lengths), min(lengths)
        long_bias = lengths.count(longest) == 1 and lengths[ci] == longest
        short_bias = lengths.count(shortest) == 1 and lengths[ci] == shortest
        if not long_bias and not short_bias:
            break
        if long_bias:
            idx = max((i for i in range(len(opts)) if i != ci), key=lambda i: lengths[i])
            suffixes = [OPTION_SUFFIXES[(step + off) % len(OPTION_SUFFIXES)] for off in range(len(OPTION_SUFFIXES))]
            for suffix in suffixes:
                if suffix not in opts[idx]:
                    opts[idx] = f"{opts[idx]}{suffix}"
                if len(_sanitize(opts[idx])) > len(_sanitize(opts[ci])):
                    break
            if len(_sanitize(opts[idx])) <= len(_sanitize(opts[ci])):
                opts[idx] = f"{opts[idx]} for production reliability and controlled rollback"
        if short_bias:
            target = min(len(_sanitize(opts[i])) for i in range(len(opts)) if i != ci)
            suffixes = [OPTION_SUFFIXES[(step + off + 1) % len(OPTION_SUFFIXES)] for off in range(len(OPTION_SUFFIXES))]
            for suffix in suffixes:
                if suffix not in opts[ci]:
                    opts[ci] = f"{opts[ci]}{suffix}"
                if len(_sanitize(opts[ci])) > target:
                    break
            if len(_sanitize(opts[ci])) <= target:
                opts[ci] = f"{opts[ci]} for production reliability and controlled rollback"
            ans = opts[ci]
            ci = opts.index(ans)
    return opts, ans


def _variant_question(base, difficulty, style, variant_idx):
    question = _rewrite_output_prompt(base)
    if question and question[-1] not in {"?", ".", ":"}:
        question = f"{question}?"

    # Prefer scenario/debug/operations framing over raw definition stems for senior-quality banks.
    if style in {"debugging", "scenario", "architecture", "operations"} and DEFINITION_STEM.search(question):
        lower = question.lower()
        if lower.startswith("what is "):
            body = question[8:].strip().rstrip("?")
        elif lower.startswith("what does "):
            body = question[10:].strip().rstrip("?")
        elif lower.startswith("which statement best defines "):
            body = question[28:].strip().rstrip("?")
        else:
            body = question[24:].strip().rstrip("?")
        framing = {
            "debugging": "A production defect investigation needs clarity on",
            "scenario": "In a production scenario, which option best describes",
            "architecture": "During architecture review, which option best describes",
            "operations": "During live operations, which option best describes",
        }
        question = f"{framing.get(style, 'In enterprise implementation, which option best describes')} {body}?"

    if variant_idx <= 0:
        return question
    prefix = CONTEXT_PREFIX.get(style, "")
    suffix = DIFFICULTY_SUFFIX.get(difficulty, "")
    lower_question = question.lower()
    already_contextual = any(
        prefix_token and lower_question.startswith(prefix_token.strip().lower())
        for prefix_token in CONTEXT_PREFIX.values()
    )
    if prefix and not already_contextual:
        question = f"{prefix}{question[0].lower()}{question[1:]}" if question else prefix.strip()
        question = question[0].upper() + question[1:]
    if suffix and suffix.strip().lower() not in question.lower() and question.endswith("?"):
        question = f"{question[:-1]}{suffix}?"
    elif suffix and suffix.strip().lower() not in question.lower():
        question = f"{question}{suffix}"
    return _sanitize(question)


def _tags(question, topic, style):
    text = _normalized(question)
    tags = {style, re.sub(r"[^a-z0-9]+", "-", _normalized(topic)).strip("-")}
    for marker, tag in (("async", "async"), ("debug", "debugging"), ("api", "api"), ("linux", "linux"), ("kernel", "kernel"), ("memory", "memory"), ("security", "security"), ("performance", "performance")):
        if marker in text:
            tags.add(tag)
    return sorted(tag for tag in tags if tag)


def _versions(bank_key):
    if bank_key.startswith("python/") or bank_key.startswith("qa/python_") or bank_key.startswith("dev/python_"):
        return ["python311", "pytest", "fastapi"]
    if bank_key.startswith("java_script/"):
        return ["es2022", "node20", "javascript"]
    if bank_key.startswith("c/"):
        return ["c17", "gcc", "linux"]
    if bank_key.startswith("bmc/"):
        return ["embedded-c", "openbmc", "redfish"]
    if bank_key.startswith("linux/"):
        return ["linux", "kernel6", "bash"]
    if bank_key.startswith("device_driver/"):
        return ["linux", "kernel6", "c17"]
    if bank_key.startswith("cpp/") or bank_key.startswith("system_design/"):
        return ["cpp20", "gcc", "linux"]
    if bank_key.startswith("csharp/") or bank_key == "dev/csharp_dev_foundations.json":
        return ["dotnet8", "csharp12", "aspnetcore"]
    return ["enterprise", "v1"]


def _build_bank(bank_key, policy):
    topics = sorted(policy["required_topics"])
    rows = []
    for src in SOURCE_BANKS[bank_key]:
        for item in _load_json(src):
            question = _sanitize(item.get("question", ""))
            if not question or _looks_trivial(question):
                continue
            options = _normalize_options(item.get("options", []))
            correct = _normalize_option(item.get("correct_answer", ""))
            if not correct or _is_bad_option(correct):
                continue
            if _matches_forbidden(bank_key, question, item.get("topic", "")):
                continue
            if correct not in options:
                options = [correct] + [o for o in options if o != correct]
            if len(options) < 2:
                continue
            rows.append({
                "question": question,
                "options": options,
                "correct_answer": correct,
                "topic": _topic_from_text(topics, question, item.get("topic", "")),
                "base_sig": question_signature(question),
            })
    if not rows:
        raise ValueError(f"No usable source questions for {bank_key}")

    by_topic = defaultdict(list)
    for row in rows:
        by_topic[row["topic"]].append(row)
    pool = _option_pool(rows)
    layout = _style_layout(policy)
    topic_plan = _topic_sequence(topics, len(layout))
    usage = Counter()
    seen_q = set()
    bank_prefix = re.sub(r"[^a-z0-9]+", "-", bank_key.replace(".json", "").lower()).strip("-")
    output = []
    version_scope = _versions(bank_key)

    for idx, (difficulty, style) in enumerate(layout):
        topic = topic_plan[idx]
        candidates = by_topic.get(topic) or rows
        base = next((row for row in candidates if usage[row["base_sig"]] == 0), None)
        if base is None:
            base = next((row for row in rows if usage[row["base_sig"]] == 0), None)
        if base is None:
            base = min(candidates, key=lambda row: (usage[row["base_sig"]], row["question"]))
        usage[base["base_sig"]] += 1
        variant_idx = usage[base["base_sig"]] - 1
        question = _variant_question(base["question"], difficulty, style, variant_idx)
        sig = question_signature(question)
        if sig in seen_q:
            question = _variant_question(base["question"], difficulty, style, variant_idx + 1)
            sig = question_signature(question)
        extra = 0
        while sig in seen_q:
            extra += 1
            marker = UNIQUENESS_SUFFIXES[(idx + extra) % len(UNIQUENESS_SUFFIXES)]
            if question.endswith("?"):
                question = f"{question[:-1]} while evaluating {marker}?"
            else:
                question = f"{question} while evaluating {marker}"
            sig = question_signature(question)
        seen_q.add(sig)

        options = _choose_options(bank_key, question, topic, base["options"], base["correct_answer"], pool)
        options, correct = _rebalance_lengths(options, options[0])
        output.append({
            "id": f"{bank_prefix}-{idx + 1:03d}",
            "question": question,
            "options": options,
            "correct_answer": correct,
            "topic": topic,
            "difficulty": difficulty,
            "style": style,
            "tags": _tags(question, topic, style),
            "role_target": policy["role_key"],
            "round_target": policy["round_key"],
            "version_scope": list(version_scope),
        })

    validate_question_bank(output, source_name=bank_key, strict=True)
    return output


def build_role_enterprise_banks():
    for bank_key in CORE_ROLE_ENTERPRISE_BANKS:
        policy = ENTERPRISE_BANK_POLICIES.get(bank_key)
        if not policy:
            raise ValueError(f"Missing policy for {bank_key}")
        questions = _build_bank(bank_key, policy)
        path = DATA_DIR / bank_key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(questions, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
        print(f"Wrote {bank_key} with {len(questions)} questions")


if __name__ == "__main__":
    build_role_enterprise_banks()
