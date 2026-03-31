from pathlib import Path

from app.services.question_bank.loader import QuestionLoader
from app.services.question_bank.registry import QuestionRegistry
from app.services.question_bank.selector import build_frozen_mcq_round_payload
from app.services.question_bank.validator import validate_question_bank


DATA_DIR = Path(__file__).resolve().parents[1] / "app" / "services" / "question_bank" / "data"


def _loader():
    return QuestionLoader(str(DATA_DIR))


def test_python_entry_bank_validates_and_freezes():
    loader = _loader()
    source_name = "python/python_entry_theory_debug.json"
    questions = loader.load(source_name)

    validate_question_bank(questions, source_name=source_name, strict=True)

    payload = build_frozen_mcq_round_payload(
        "python_entry",
        "L2",
        [source_name],
        questions,
    )

    assert len(payload["selected_questions"]) == 15
    assert payload["question_bank_files"] == [source_name]


def test_non_entry_python_roles_share_updated_l2_bank():
    loader = _loader()
    registry = QuestionRegistry(loader)

    for role_key in ("python_qa", "python_qa_linux", "python_dev", "python_ai_ml"):
        source_files = registry.get_question_files(role_key, "L2")
        assert source_files == ["python/python_senior_theory_debug.json"]

        questions = registry.get_questions(role_key, "L2")
        validate_question_bank(questions, source_name=source_files[0], strict=True)

        payload = build_frozen_mcq_round_payload(
            role_key,
            "L2",
            source_files,
            questions,
        )

        assert len(payload["selected_questions"]) == 15
        assert payload["question_bank_files"] == source_files
