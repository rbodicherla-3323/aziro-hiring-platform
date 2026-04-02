import json
import os
import re


HEADER_OPTION_PATTERN = re.compile(
    r"^\s*(direction|directions|statements?|conclusions?|assumptions?|arguments?|courses?\s+of\s+action|select\s+the\s+best\s+answer)\s*:?$",
    flags=re.IGNORECASE,
)

SHARED_POOL_FILES = {
    "aptitude.json",
    "soft_skills.json",
    "soft_skills_leadership.json",
    "domains/networking.json",
    "domains/storage.json",
    "domains/virtualisation.json",
}

INJECTED_SUFFIXES = (
    "under production constraints in enterprise environments for large-scale systems",
    "in enterprise environments for large-scale systems",
    "under production constraints in enterprise environments",
    "in enterprise environments",
    "for that enterprise scenario",
    "while meeting reliability expectations",
    "with accountable communication and traceability",
    "with validated operational controls",
)

INJECTED_FILLERS = {
    "delay action without confirming impact",
    "proceed without validating assumptions",
    "choose an approach without documenting rationale",
    "prioritize correctness and resilience in enterprise environments",
    "use observability-driven diagnosis",
    "validate behavior under concurrency",
}

GENERIC_FALLBACK_OPTIONS = (
    "Cannot be inferred from the given information",
    "Insufficient information to conclude",
    "Requires additional verification before conclusion",
    "Depends on assumptions not provided in the prompt",
)

OUTPUT_FALLBACK_OPTIONS = (
    "None",
    "0",
    "1",
    "True",
    "False",
    "TypeError",
    "NameError",
    "ValueError",
)

CODE_TEXT_PATTERN = re.compile(
    r"(```|^\s*(from\s+[A-Za-z_][A-Za-z0-9_.]*\s+import|import\s+[A-Za-z_][A-Za-z0-9_.]*|def\s+[A-Za-z_][A-Za-z0-9_]*|class\s+[A-Za-z_][A-Za-z0-9_]*|if\s*\(|for\s*\(|while\s*\(|try\s*:|except\b|finally\s*:|#include\b)|[{};]|=>|::|[A-Za-z_][A-Za-z0-9_]*\s*=\s*[^=\s])",
    flags=re.IGNORECASE | re.MULTILINE,
)

SNIPPET_PROMPT_INLINE_PATTERN = re.compile(
    r"^(A snippet runs with the following behavior\.\s*Which output is correct\?)\s*(.+)$",
    flags=re.IGNORECASE | re.DOTALL,
)

OUTPUT_PROMPT_INLINE_PATTERN = re.compile(
    r"^(What is the output of:)\s*(.+)$",
    flags=re.IGNORECASE | re.DOTALL,
)


def _is_shared_pool_path(relative_path: str) -> bool:
    normalized = str(relative_path or "").replace("\\", "/").strip().lower()
    return normalized in SHARED_POOL_FILES or normalized.startswith("domains/")


def _normalize_whitespace(value: str) -> str:
    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n[ \t]+", "\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _normalize_question_text(value: str) -> str:
    """
    Normalize question text while preserving code indentation.
    """
    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\t", "    ")
    # Preserve leading indentation in each line; only trim trailing spaces.
    text = "\n".join(line.rstrip() for line in text.split("\n"))
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"^\s*\n+", "", text)
    text = re.sub(r"\n+\s*$", "", text)
    return text


def _normalize_plain_text(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _normalize_code_text(value: str) -> str:
    return _normalize_question_text(value)


def _looks_like_code_text(value: str) -> bool:
    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n")
    if not text.strip():
        return False
    if "```" in text:
        return True

    lines = [line for line in text.split("\n") if line.strip()]
    if not lines:
        return False

    strong_lines = sum(1 for line in lines if CODE_TEXT_PATTERN.search(line))
    if len(lines) == 1:
        single = lines[0].strip()
        if not re.search(r"[{};=()]|=>|::|->", single):
            return False

    if strong_lines >= 2:
        return True

    if len(lines) >= 2:
        indented_lines = sum(1 for line in lines if re.match(r"^\s{2,}\S", line))
        if indented_lines >= 1 and strong_lines >= 1:
            return True

    return bool(CODE_TEXT_PATTERN.search(text))


def _strip_injected_suffixes(value: str) -> str:
    text = _normalize_plain_text(value)
    if not text:
        return text
    changed = True
    while changed:
        changed = False
        lower = text.lower()
        for suffix in INJECTED_SUFFIXES:
            if lower.endswith(suffix):
                text = text[: len(text) - len(suffix)].rstrip(" ,;:-")
                changed = True
                break
    return text.strip()


def _clean_question_text(value: str) -> str:
    text = _normalize_question_text(value)
    text = re.sub(r"\?{2,}", "?", text)
    # Fix malformed imports like "Assumption s:" / "Statement s:".
    text = re.sub(r"\b(Statement|Conclusion|Argument|Assumption)\s+s\s*:", r"\1s:", text, flags=re.IGNORECASE)
    # Normalize inline snippet-style prompts into two lines:
    # prompt line + code line(s). This keeps code rendering stable.
    for pattern in (SNIPPET_PROMPT_INLINE_PATTERN, OUTPUT_PROMPT_INLINE_PATTERN):
        match = pattern.match(text.strip())
        if not match:
            continue
        prompt = _normalize_plain_text(match.group(1))
        payload = str(match.group(2) or "").strip()
        if payload:
            text = f"{prompt}\n{payload}"
        break
    return text


def _clean_option_text(value: str) -> str:
    raw_text = str(value or "")
    if _looks_like_code_text(raw_text):
        text = _normalize_code_text(raw_text)
        text = re.sub(r"^\s*\(?[A-Za-z0-9IVXivx]+\)?[.)\-:]\s*", "", text, count=1)
        return text.strip()

    text = _strip_injected_suffixes(raw_text)
    text = re.sub(r"\?{2,}", "?", text)
    text = re.sub(r"^\(?[A-Za-z0-9IVXivx]+\)?[.)\-:]\s*", "", text)
    text = re.sub(r"\s+([?.!,;:])", r"\1", text)
    return text.strip()


def _normalize_key(value: str) -> str:
    return _normalize_plain_text(value).lower()


def _is_injected_filler(option: str) -> bool:
    normalized = _normalize_key(option)
    if normalized in INJECTED_FILLERS:
        return True
    if normalized.startswith("prioritize correctness and resilience"):
        return True
    if normalized.startswith("use observability-driven diagnosis"):
        return True
    if normalized.startswith("validate behavior under concurrency"):
        return True
    return bool(re.fullmatch(r"apply a default response for .+ without verification", normalized))


def _looks_like_output_question(question_text: str) -> bool:
    text = _normalize_plain_text(question_text).lower()
    if not text:
        return False
    if "output" not in text:
        return False
    return bool(
        re.search(
            r"(which output is correct|what is the output of|what does this output|print\(|console\.log|printf\(|system\.out\.println|writeline\()",
            text,
        )
    )


def _is_output_option_candidate(option: str) -> bool:
    text = _normalize_plain_text(option)
    if not text:
        return False
    low = text.lower()
    if _is_injected_filler(text):
        return False
    if "enterprise environments" in low or "production constraints" in low or "large-scale systems" in low:
        return False
    # Output choices should be concise values, not narrative sentences.
    if len(text.split()) > 7:
        return False
    return True


def _is_valid_option(option: str, remove_fillers: bool) -> bool:
    if not option:
        return False
    if HEADER_OPTION_PATTERN.match(option):
        return False
    low = _normalize_key(option)
    if low in {"all of the above", "none of the above"}:
        return False
    if remove_fillers and _is_injected_filler(option):
        return False
    return True


def _find_matching_option(options: list[str], correct_answer: str) -> str | None:
    if correct_answer in options:
        return correct_answer
    normalized_correct = _normalize_key(correct_answer)
    for option in options:
        if _normalize_key(option) == normalized_correct:
            return option
    return None


def _ensure_minimum_options(options: list[str], correct_answer: str, output_question: bool = False) -> list[str]:
    if len(options) >= 4:
        return options
    existing = {_normalize_key(opt) for opt in options}
    fallback_pool = OUTPUT_FALLBACK_OPTIONS if output_question else GENERIC_FALLBACK_OPTIONS
    for fallback in fallback_pool:
        low = _normalize_key(fallback)
        if low in existing or low == _normalize_key(correct_answer):
            continue
        options.append(fallback)
        existing.add(low)
        if len(options) >= 4:
            break
    while len(options) < 4:
        options.append(f"Alternative option {len(options) + 1}")
    return options


def _sanitize_question_record(question: dict, remove_fillers: bool) -> dict:
    row = dict(question)

    if "question" in row:
        row["question"] = _clean_question_text(row.get("question"))
    if "text" in row and not row.get("question"):
        row["text"] = _clean_question_text(row.get("text"))
    if "topic" in row:
        row["topic"] = _normalize_plain_text(row.get("topic"))

    question_text = row.get("question") or row.get("text") or ""
    output_question = _looks_like_output_question(question_text)

    raw_options = row.get("options")
    if not isinstance(raw_options, list):
        return row

    cleaned_options = []
    seen = set()
    for raw in raw_options:
        option = _clean_option_text(raw)
        if output_question and not _is_output_option_candidate(option):
            continue
        if not _is_valid_option(option, remove_fillers=remove_fillers):
            continue
        key = _normalize_key(option)
        if key in seen:
            continue
        seen.add(key)
        cleaned_options.append(option)

    cleaned_correct = _clean_option_text(row.get("correct_answer", ""))
    if (remove_fillers or output_question) and _is_injected_filler(cleaned_correct):
        cleaned_correct = ""
    if output_question and not _is_output_option_candidate(cleaned_correct):
        cleaned_correct = ""

    matched_correct = _find_matching_option(cleaned_options, cleaned_correct)
    if not matched_correct and cleaned_options:
        matched_correct = cleaned_options[0]

    cleaned_options = _ensure_minimum_options(
        cleaned_options,
        matched_correct or cleaned_correct,
        output_question=output_question,
    )
    if not matched_correct:
        matched_correct = _find_matching_option(cleaned_options, cleaned_correct) or cleaned_options[0]

    row["options"] = cleaned_options
    row["correct_answer"] = matched_correct
    return row


def sanitize_question_record(question: dict, relative_path: str | None = None) -> dict:
    remove_fillers = _is_shared_pool_path(relative_path or "")
    return _sanitize_question_record(question, remove_fillers=remove_fillers)


class QuestionLoader:
    def __init__(self, base_path: str):
        self.base_path = base_path

    def load(self, relative_path: str):
        file_path = os.path.join(self.base_path, relative_path)

        if not os.path.exists(file_path):
            raise FileNotFoundError(f"Question file not found: {file_path}")

        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        if isinstance(data, dict) and "questions" in data:
            questions = data["questions"]
        elif isinstance(data, list):
            questions = data
        else:
            raise ValueError(f"Invalid question format in {relative_path}")

        if not isinstance(questions, list):
            raise ValueError(f"Invalid question list in {relative_path}")

        remove_fillers = _is_shared_pool_path(relative_path)
        return [
            _sanitize_question_record(question, remove_fillers=remove_fillers)
            if isinstance(question, dict)
            else question
            for question in questions
        ]
