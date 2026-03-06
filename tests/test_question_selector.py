import random

import pytest

from app.services.question_bank.selector import QuestionSelectionError, select_questions


def _question(qid, difficulty, style="scenario"):
    return {
        "id": qid,
        "question": f"Question {qid}",
        "options": ["A plausible answer", "Another plausible answer", "Third plausible answer", "Fourth plausible answer"],
        "correct_answer": "A plausible answer",
        "topic": "Topic",
        "difficulty": difficulty,
        "style": style,
        "tags": ["tag"],
        "role_target": "java_entry",
        "round_target": "L2",
        "version_scope": ["java17", "java21"],
    }


def test_balanced_selector_returns_exact_mix():
    questions = []
    for difficulty in ("easy", "medium", "hard"):
        for idx in range(8):
            style = "debugging" if idx < 3 else "scenario"
            questions.append(_question(f"{difficulty}-{idx}", difficulty, style=style))

    selected = select_questions(
        questions=questions,
        total_count=15,
        strategy="balanced_difficulty_v2",
        rng=random.Random(42),
        constraints={"difficulty_mix": {"easy": 5, "medium": 5, "hard": 5}, "min_debugging_total": 3},
    )

    assert len(selected) == 15
    counts = {"easy": 0, "medium": 0, "hard": 0}
    debug_count = 0
    for question in selected:
        counts[question["difficulty"]] += 1
        if question["style"] == "debugging":
            debug_count += 1
    assert counts == {"easy": 5, "medium": 5, "hard": 5}
    assert debug_count >= 3


def test_balanced_selector_normalizes_moderate_to_medium():
    questions = []
    for idx in range(5):
        questions.append(_question(f"easy-{idx}", "easy", style="debugging" if idx == 0 else "scenario"))
        questions.append(_question(f"moderate-{idx}", "moderate", style="debugging" if idx == 1 else "scenario"))
        questions.append(_question(f"hard-{idx}", "hard", style="debugging" if idx == 2 else "scenario"))

    selected = select_questions(
        questions=questions,
        total_count=15,
        strategy="balanced_difficulty_v2",
        rng=random.Random(11),
        constraints={"difficulty_mix": {"easy": 5, "medium": 5, "hard": 5}, "min_debugging_total": 2},
    )

    counts = {"easy": 0, "medium": 0, "hard": 0}
    for question in selected:
        counts[question["difficulty"] if question["difficulty"] != "moderate" else "medium"] += 1
    assert counts == {"easy": 5, "medium": 5, "hard": 5}


def test_balanced_selector_fails_when_tier_missing():
    questions = []
    for idx in range(5):
        questions.append(_question(f"easy-{idx}", "easy"))
        questions.append(_question(f"medium-{idx}", "medium"))
    for idx in range(4):
        questions.append(_question(f"hard-{idx}", "hard"))

    with pytest.raises(QuestionSelectionError):
        select_questions(
            questions=questions,
            total_count=15,
            strategy="balanced_difficulty_v2",
            rng=random.Random(7),
            constraints={"difficulty_mix": {"easy": 5, "medium": 5, "hard": 5}},
        )


def test_balanced_selector_fails_when_debugging_minimum_unmet():
    questions = []
    for difficulty in ("easy", "medium", "hard"):
        for idx in range(5):
            questions.append(_question(f"{difficulty}-{idx}", difficulty, style="scenario"))

    with pytest.raises(QuestionSelectionError):
        select_questions(
            questions=questions,
            total_count=15,
            strategy="balanced_difficulty_v2",
            rng=random.Random(17),
            constraints={"difficulty_mix": {"easy": 5, "medium": 5, "hard": 5}, "min_debugging_total": 1},
        )


def test_balanced_selector_supports_enterprise_aiml_debugging_quota():
    questions = []
    for idx in range(5):
        questions.append(_question(f"easy-{idx}", "easy", style="scenario"))
    for idx in range(5):
        style = "debugging" if idx < 2 else "concept"
        questions.append(_question(f"medium-{idx}", "medium", style=style))
    for idx in range(6):
        style = "debugging" if idx < 3 else "operations"
        questions.append(_question(f"hard-{idx}", "hard", style=style))

    selected = select_questions(
        questions=questions,
        total_count=15,
        strategy="balanced_difficulty_v2",
        rng=random.Random(29),
        constraints={"difficulty_mix": {"easy": 5, "medium": 5, "hard": 5}, "min_debugging_total": 5},
    )

    counts = {"easy": 0, "medium": 0, "hard": 0}
    debug_count = 0
    for question in selected:
        counts[question["difficulty"]] += 1
        if question["style"] == "debugging":
            debug_count += 1

    assert counts == {"easy": 5, "medium": 5, "hard": 5}
    assert debug_count >= 5
