import json
from pathlib import Path

import pytest

from app.services.question_bank.validator import (
    QuestionBankValidationError,
    validate_question_bank,
    validate_question_file,
)


BANK_PATH = Path("app/services/question_bank/data/AI/ML/ai_ml_engineering.json")


def test_enterprise_aiml_bank_validates_successfully():
    assert BANK_PATH.exists()

    summary = validate_question_file(BANK_PATH, strict=True)

    assert summary["ok"] is True
    assert summary["total_questions"] == 100
    assert summary["difficulty_counts"] == {"easy": 25, "medium": 35, "hard": 40}
    assert summary["debugging_counts"] == {"easy": 5, "medium": 12, "hard": 18}
    assert summary["style_counts"] == {
        "concept": 20,
        "scenario": 25,
        "debugging": 35,
        "architecture": 10,
        "operations": 10,
    }

    questions = json.loads(BANK_PATH.read_text(encoding="utf-8"))
    serialized = json.dumps(questions, ensure_ascii=False)
    for marker in ("â€”", "â€“", "Â", "Î"):
        assert marker not in serialized


def test_validator_rejects_unique_longest_correct_answer():
    bad_bank = [
        {
            "id": "aiml-bad-001",
            "question": "A model-monitoring alert fires only on weekends. Which explanation is most likely?",
            "options": [
                "Alert thresholds differ by calendar schedule in production and should be checked.",
                "Weekend traffic is illegal for machine learning systems.",
                "Metrics stop existing after Friday midnight.",
                "The model always retrains itself on Saturdays.",
            ],
            "correct_answer": "Alert thresholds differ by calendar schedule in production and should be checked.",
            "topic": "MLOps, Deployment, and Monitoring",
            "difficulty": "medium",
            "style": "debugging",
            "tags": ["monitoring", "alerts"],
            "role_target": "python_ai_ml",
            "round_target": "L3",
            "version_scope": ["python311", "mlflow"],
        }
    ]

    with pytest.raises(QuestionBankValidationError):
        validate_question_bank(bad_bank, source_name=None, strict=True)
