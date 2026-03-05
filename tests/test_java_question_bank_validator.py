from copy import deepcopy
from pathlib import Path

import pytest

from app.services.question_bank.validator import QuestionBankValidationError, validate_question_bank, validate_question_file


BANK_PATHS = [
    "app/services/question_bank/data/java/java_entry_theory.json",
    "app/services/question_bank/data/java/java_entry_fundamentals.json",
    "app/services/question_bank/data/java/java_senior_theory_debug.json",
    "app/services/question_bank/data/qa/java_qa_advanced.json",
    "app/services/question_bank/data/cloud/java_aws_cloud.json",
]


def test_generated_java_banks_pass_validation():
    for path in BANK_PATHS:
        summary = validate_question_file(path, strict=True)
        assert summary["ok"], path
        assert summary["total_questions"] == 100


def test_validator_rejects_unique_longest_correct_answer():
    question = {
        "id": "demo-001",
        "question": "A service fails only in production. Which explanation is strongest?",
        "options": [
            "The JVM is old.",
            "The database is slow.",
            "A race condition is triggered only under higher production concurrency and the current locking strategy is unsafe.",
            "The logs are short.",
        ],
        "correct_answer": "A race condition is triggered only under higher production concurrency and the current locking strategy is unsafe.",
        "topic": "Debugging Fundamentals",
        "difficulty": "hard",
        "style": "debugging",
        "tags": ["race-condition"],
        "role_target": "java_entry",
        "round_target": "L2",
        "version_scope": ["java17", "java21"],
    }

    with pytest.raises(QuestionBankValidationError):
        validate_question_bank([question], source_name=None, strict=True)


def test_validator_rejects_duplicate_question_text():
    question = {
        "id": "demo-001",
        "question": "Which fix is safest for a stale element issue?",
        "options": [
            "Re-locate the element after the DOM update.",
            "Use Thread.sleep for every click.",
            "Disable explicit waits completely.",
            "Close and reopen the browser after each step.",
        ],
        "correct_answer": "Re-locate the element after the DOM update.",
        "topic": "Selenium WebDriver",
        "difficulty": "medium",
        "style": "scenario",
        "tags": ["stale-element"],
        "role_target": "java_qa",
        "round_target": "L3",
        "version_scope": ["java17", "java21"],
    }
    duplicate = deepcopy(question)
    duplicate["id"] = "demo-002"

    with pytest.raises(QuestionBankValidationError):
        validate_question_bank([question, duplicate], source_name=None, strict=True)


def test_shared_senior_l2_bank_is_pure_java_only():
    summary = validate_question_file(
        "app/services/question_bank/data/java/java_senior_theory_debug.json",
        strict=True,
    )

    assert summary["ok"]
    assert summary["total_questions"] == 100

    bank_text = Path("app/services/question_bank/data/java/java_senior_theory_debug.json").read_text(encoding="utf-8").lower()
    for marker in (
        '"topic": "java language and type system"',
        '"topic": "strings and immutability"',
        '"topic": "collections and contracts"',
        '"topic": "generics and type safety"',
        '"topic": "exceptions and resource handling"',
        '"topic": "streams lambdas and method references"',
        '"topic": "concurrency and executors"',
        '"topic": "jvm memory and gc"',
        '"topic": "practical debugging"',
    ):
        assert marker in bank_text

    for marker in (
        "selenium",
        "webdriver",
        "testng",
        "junit",
        "rest assured",
        "cloudwatch",
        "spring boot",
        "actuator",
        '"topic": "spring boot production readiness"',
        '"topic": "aws sdk v2 credentials"',
    ):
        assert marker not in bank_text


def test_java_qa_and_java_aws_l3_banks_remain_domain_specific():
    qa_text = Path("app/services/question_bank/data/qa/java_qa_advanced.json").read_text(encoding="utf-8").lower()
    aws_text = Path("app/services/question_bank/data/cloud/java_aws_cloud.json").read_text(encoding="utf-8").lower()

    assert "selenium" in qa_text
    assert "junit" in qa_text
    assert "rest assured" in qa_text

    assert "aws" in aws_text
    assert "lambda" in aws_text
    assert "cloudwatch" in aws_text
