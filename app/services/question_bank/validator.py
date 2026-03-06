import argparse
import json
import random
import re
from collections import Counter
from pathlib import Path

from app.services.question_bank.helpers import (
    VALID_DIFFICULTIES,
    VALID_STYLES,
    normalize_difficulty,
    normalize_style,
    normalize_text,
    prepare_question_options,
    question_signature,
)
from app.services.question_bank.enterprise_bank_config import ENTERPRISE_BANK_POLICIES

REQUIRED_FIELDS = {
    "id",
    "question",
    "options",
    "correct_answer",
    "topic",
    "difficulty",
    "style",
    "tags",
    "role_target",
    "round_target",
    "version_scope",
}
_VALIDATION_CACHE = {}
MOJIBAKE_MARKERS = ('â€”', 'â€“', 'Â', 'Î')


class QuestionBankValidationError(ValueError):
    pass


def _normalized_bank_fingerprint(questions):
    return tuple((str(q.get("id", "")), normalize_text(q.get("question", ""))) for q in questions)


def _is_output_only(question_text):
    text = normalize_text(question_text)
    return (
        text.startswith("what is the output")
        or text.startswith("what will be the output")
        or text.startswith("what will be printed")
    )


def _is_applied_style(question):
    style = normalize_style(question.get("style"))
    if style in {"scenario", "debugging", "architecture", "operations"}:
        return True
    text = normalize_text(question.get("question", ""))
    markers = (
        "production",
        "incident",
        "fails",
        "timeout",
        "latency",
        "stale",
        "root cause",
        "deployment",
        "observability",
        "debug",
        "exception",
        "ci pipeline",
        "parallel",
        "flaky",
    )
    return any(marker in text for marker in markers)


def _looks_trivial(question_text):
    text = normalize_text(question_text)
    bad_markers = (
        "2 + 2",
        "hello world",
        "which keyword stores numbers only",
        "pick the longest option",
    )
    return any(marker in text for marker in bad_markers)


def _looks_definition_only(question):
    text = normalize_text(question.get("question", ""))
    if _is_applied_style(question):
        return False
    definition_prefixes = (
        "what is ",
        "what does ",
        "which statement best defines",
        "which option best defines",
        "what is the purpose of ",
        "what is the key difference between ",
        "what does the term ",
    )
    return text.startswith(definition_prefixes)


def _contains_mojibake(question):
    fields = [question.get("question", ""), question.get("correct_answer", ""), question.get("topic", "")]
    fields.extend(question.get("options") or [])
    for value in fields:
        text = str(value or "")
        if any(marker in text for marker in MOJIBAKE_MARKERS):
            return True
    return False


def _unique_longest_or_shortest(options, correct_answer):
    lengths = [len(str(option).strip()) for option in options]
    correct_index = options.index(correct_answer)
    longest = max(lengths)
    shortest = min(lengths)
    unique_longest = lengths.count(longest) == 1 and lengths[correct_index] == longest
    unique_shortest = lengths.count(shortest) == 1 and lengths[correct_index] == shortest
    return unique_longest, unique_shortest


def _question_haystack(question):
    tags = question.get("tags") or []
    tag_text = " ".join(str(tag) for tag in tags)
    return normalize_text(f"{question.get('question', '')} {question.get('topic', '')} {tag_text}")


def _has_forbidden_pattern(question, patterns):
    haystack = _question_haystack(question)
    for pattern in patterns:
        if re.search(pattern, haystack, re.IGNORECASE):
            return pattern
    return None


def _has_forbidden_prefix(question_text, prefixes):
    normalized = normalize_text(question_text)
    for prefix in prefixes:
        if normalized.startswith(normalize_text(prefix)):
            return prefix
    return None


def _simulate_position_balance(questions, iterations=18):
    rng = random.Random(73)
    position_counts = Counter()
    total = 0
    for _ in range(iterations):
        if len(questions) < 15:
            break
        sample = rng.sample(questions, 15)
        prepared = prepare_question_options(sample, rng=random.Random(rng.randint(1, 10_000_000)))
        for question in prepared:
            options = question.get("options") or []
            correct = question.get("correct_answer")
            if correct in options:
                position_counts[options.index(correct)] += 1
                total += 1
    if total == 0:
        return {"ok": True, "ratios": {}}
    ratios = {position: count / float(total) for position, count in position_counts.items()}
    return {
        "ok": all(ratio <= 0.35 for ratio in ratios.values()),
        "ratios": ratios,
    }


def _validate_question_record(question, seen_ids, seen_signatures, strict):
    errors = []
    missing = [field for field in REQUIRED_FIELDS if field not in question]
    if missing:
        errors.append(f"missing fields: {', '.join(sorted(missing))}")
        return errors

    qid = str(question.get("id", "")).strip()
    if not qid:
        errors.append("empty id")
    elif qid in seen_ids:
        errors.append(f"duplicate id: {qid}")
    else:
        seen_ids.add(qid)

    signature = question_signature(question.get("question", ""))
    if not signature:
        errors.append("empty question text")
    elif signature in seen_signatures:
        errors.append(f"duplicate question text: {qid}")
    else:
        seen_signatures.add(signature)

    difficulty = normalize_difficulty(question.get("difficulty"))
    if difficulty not in VALID_DIFFICULTIES:
        errors.append(f"invalid difficulty: {question.get('difficulty')}")
    question["difficulty"] = difficulty

    style = normalize_style(question.get("style"))
    if style not in VALID_STYLES:
        errors.append(f"invalid style: {question.get('style')}")
    question["style"] = style

    options = question.get("options")
    if not isinstance(options, list) or len(options) < 4:
        errors.append("question must have at least 4 options")
    else:
        normalized_options = [normalize_text(option) for option in options]
        if len(set(normalized_options)) != len(normalized_options):
            errors.append(f"duplicate options: {qid}")
        correct = question.get("correct_answer")
        if correct not in options:
            errors.append(f"correct answer missing from options: {qid}")
        else:
            unique_longest, unique_shortest = _unique_longest_or_shortest(options, correct)
            if unique_longest:
                errors.append(f"unique longest correct answer: {qid}")
            if unique_shortest:
                errors.append(f"unique shortest correct answer: {qid}")
        forbidden = {"all of the above", "none of the above"}
        if any(normalize_text(option) in forbidden for option in options):
            errors.append(f"forbidden option pattern: {qid}")

    tags = question.get("tags")
    if not isinstance(tags, list) or not tags:
        errors.append(f"missing tags list: {qid}")

    versions = question.get("version_scope")
    if not isinstance(versions, list) or not versions:
        errors.append(f"missing version_scope list: {qid}")

    if strict and _looks_trivial(question.get("question", "")):
        errors.append(f"trivial wording detected: {qid}")
    if strict and _contains_mojibake(question):
        errors.append(f"mojibake detected: {qid}")

    return errors


def validate_question_bank(questions, source_name=None, strict=True):
    policy = ENTERPRISE_BANK_POLICIES.get(source_name)
    fingerprint = (source_name or "<memory>", _normalized_bank_fingerprint(questions), bool(strict))
    cached = _VALIDATION_CACHE.get(fingerprint)
    if cached:
        return cached

    seen_ids = set()
    seen_signatures = set()
    errors = []
    topic_counts = Counter()
    difficulty_counts = Counter()
    debugging_counts = Counter()
    style_counts = Counter()
    applied_count = 0
    output_count = 0
    output_prefix_count = 0
    definition_count = 0

    normalized_questions = []
    for question in questions:
        q = dict(question)
        record_errors = _validate_question_record(q, seen_ids, seen_signatures, strict)
        if record_errors:
            errors.extend(record_errors)
        topic = str(q.get("topic", "")).strip()
        if topic:
            topic_counts[topic] += 1
        difficulty = normalize_difficulty(q.get("difficulty"))
        if difficulty:
            difficulty_counts[difficulty] += 1
            if normalize_style(q.get("style")) == "debugging":
                debugging_counts[difficulty] += 1
        style = normalize_style(q.get("style"))
        if style:
            style_counts[style] += 1
        if _is_applied_style(q):
            applied_count += 1
        if _looks_definition_only(q):
            definition_count += 1
        if _is_output_only(q.get("question", "")):
            output_count += 1
            normalized_question_text = normalize_text(q.get("question", ""))
            if normalized_question_text.startswith("what is the output") or normalized_question_text.startswith(
                "what will be the output"
            ):
                output_prefix_count += 1
        normalized_questions.append(q)

    if policy:
        total_expected = sum(policy["difficulty_counts"].values())
        if len(normalized_questions) != total_expected:
            errors.append(
                f"bank size mismatch for {source_name}: expected {total_expected}, found {len(normalized_questions)}"
            )

        for difficulty, expected in policy["difficulty_counts"].items():
            actual = difficulty_counts.get(difficulty, 0)
            if actual != expected:
                errors.append(
                    f"difficulty count mismatch for {source_name} {difficulty}: expected {expected}, found {actual}"
                )

        for difficulty, expected in policy["debugging_counts"].items():
            actual = debugging_counts.get(difficulty, 0)
            if actual != expected:
                errors.append(
                    f"debugging count mismatch for {source_name} {difficulty}: expected {expected}, found {actual}"
                )

        expected_style_counts = policy.get("style_counts") or {}
        for style, expected in expected_style_counts.items():
            actual = style_counts.get(style, 0)
            if actual != expected:
                errors.append(f"style count mismatch for {source_name} {style}: expected {expected}, found {actual}")

        missing_topics = sorted(policy["required_topics"] - set(topic_counts))
        if missing_topics:
            errors.append(f"missing required topics for {source_name}: {', '.join(missing_topics)}")

        expected_topic_counts = policy.get("expected_topic_counts") or {}
        for topic, expected in expected_topic_counts.items():
            actual = topic_counts.get(topic, 0)
            if actual != expected:
                errors.append(f"topic count mismatch for {source_name} {topic}: expected {expected}, found {actual}")
        unexpected_topics = sorted(topic for topic in topic_counts if topic not in policy["required_topics"])
        if expected_topic_counts and unexpected_topics:
            errors.append(f"unexpected topics for {source_name}: {', '.join(unexpected_topics)}")

        allowed_topics = policy.get("allowed_topics")
        if allowed_topics:
            disallowed_topics = sorted(topic for topic in topic_counts if topic not in allowed_topics)
            if disallowed_topics:
                errors.append(f"disallowed topics for {source_name}: {', '.join(disallowed_topics)}")

        forbidden_patterns = policy.get("forbidden_patterns", ())
        forbidden_prefixes = policy.get("forbidden_prefixes", ())
        for question in normalized_questions:
            qid = question.get("id", "<unknown>")
            if forbidden_patterns:
                matched_pattern = _has_forbidden_pattern(question, forbidden_patterns)
                if matched_pattern:
                    errors.append(f"forbidden marker in {source_name} {qid}: {matched_pattern}")
            if forbidden_prefixes:
                matched_prefix = _has_forbidden_prefix(question.get("question", ""), forbidden_prefixes)
                if matched_prefix:
                    errors.append(f"forbidden prefix in {source_name} {qid}: {matched_prefix}")

        applied_ratio = applied_count / float(len(normalized_questions) or 1)
        if applied_ratio < float(policy.get("min_applied_ratio", 0.0)):
            errors.append(f"applied question ratio too low for {source_name}: {applied_ratio:.2f}")

        output_ratio = output_count / float(len(normalized_questions) or 1)
        if output_ratio > float(policy.get("max_output_ratio", 1.0)):
            errors.append(f"output-only ratio too high for {source_name}: {output_ratio:.2f}")

        output_prefix_ratio = output_prefix_count / float(len(normalized_questions) or 1)
        if output_prefix_ratio > float(policy.get("max_output_prefix_ratio", 1.0)):
            errors.append(f"output-prefix ratio too high for {source_name}: {output_prefix_ratio:.2f}")

        definition_ratio = definition_count / float(len(normalized_questions) or 1)
        if definition_ratio > float(policy.get("max_definition_ratio", 1.0)):
            errors.append(f"definition-only ratio too high for {source_name}: {definition_ratio:.2f}")

        balance = _simulate_position_balance(normalized_questions)
        if not balance["ok"]:
            errors.append(f"option position bias too high for {source_name}: {balance['ratios']}")
    else:
        balance = {"ok": True, "ratios": {}}

    summary = {
        "source_name": source_name,
        "total_questions": len(normalized_questions),
        "difficulty_counts": dict(difficulty_counts),
        "debugging_counts": dict(debugging_counts),
        "style_counts": dict(style_counts),
        "topic_counts": dict(topic_counts),
        "applied_ratio": applied_count / float(len(normalized_questions) or 1),
        "output_ratio": output_count / float(len(normalized_questions) or 1),
        "output_prefix_ratio": output_prefix_count / float(len(normalized_questions) or 1),
        "definition_ratio": definition_count / float(len(normalized_questions) or 1),
        "position_ratios": balance.get("ratios", {}),
        "errors": errors,
        "ok": not errors,
    }
    if strict and errors:
        raise QuestionBankValidationError("; ".join(errors[:20]))
    _VALIDATION_CACHE[fingerprint] = summary
    return summary


def validate_question_file(file_path, strict=True):
    path = Path(file_path)
    with path.open("r", encoding="utf-8") as fh:
        questions = json.load(fh)
    if isinstance(questions, dict) and "questions" in questions:
        questions = questions["questions"]
    normalized_path = str(path).replace("\\", "/")
    if "/data/" in normalized_path:
        source_name = normalized_path.split("/data/", 1)[-1]
    else:
        source_name = path.name
    return validate_question_bank(questions, source_name=source_name, strict=strict)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Validate MCQ question bank files.")
    parser.add_argument("files", nargs="+", help="Question bank JSON files to validate")
    parser.add_argument("--no-strict", action="store_true", help="Disable strict validation checks")
    args = parser.parse_args(argv)

    overall_errors = []
    for file_path in args.files:
        summary = validate_question_file(file_path, strict=not args.no_strict)
        if summary["ok"]:
            print(f"OK {file_path}: {summary['total_questions']} questions")
        else:
            print(f"FAIL {file_path}: {len(summary['errors'])} issue(s)")
            for error in summary["errors"][:20]:
                print(f"  - {error}")
            overall_errors.extend(summary["errors"])
    if overall_errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
