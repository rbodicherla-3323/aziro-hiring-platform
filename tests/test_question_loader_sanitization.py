import json
from pathlib import Path

from app.services.question_bank.loader import QuestionLoader


def _write_bank(base_dir: Path, relative_path: str, payload):
    file_path = base_dir / relative_path
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(json.dumps(payload, indent=2, ensure_ascii=True), encoding="utf-8")


def test_shared_pool_loader_strips_injected_suffixes_and_fillers(tmp_path: Path):
    payload = [
        {
            "question": "Statement: Example prompt.",
            "options": [
                "Only I follows for that enterprise scenario",
                "Only II follows",
                "Either I or II follows",
                "Delay action without confirming impact",
            ],
            "correct_answer": "Only I follows for that enterprise scenario",
            "topic": "Course of Action",
        }
    ]
    _write_bank(tmp_path, "aptitude.json", payload)

    loader = QuestionLoader(base_path=str(tmp_path))
    questions = loader.load("aptitude.json")
    question = questions[0]

    assert "Only I follows" in question["options"]
    assert all("for that enterprise scenario" not in option.lower() for option in question["options"])
    assert all("while meeting reliability expectations" not in option.lower() for option in question["options"])
    assert "delay action without confirming impact" not in {
        option.lower() for option in question["options"]
    }
    assert len(question["options"]) >= 4
    assert question["correct_answer"] in question["options"]


def test_non_shared_loader_does_not_drop_generic_options(tmp_path: Path):
    payload = [
        {
            "question": "What is the best action?",
            "options": [
                "Delay action without confirming impact",
                "Proceed after validation",
                "Escalate with evidence",
                "Document rationale",
            ],
            "correct_answer": "Proceed after validation",
            "topic": "General",
        }
    ]
    _write_bank(tmp_path, "python/custom_bank.json", payload)

    loader = QuestionLoader(base_path=str(tmp_path))
    questions = loader.load("python/custom_bank.json")
    options = questions[0]["options"]

    assert "Delay action without confirming impact" in options
    assert questions[0]["correct_answer"] == "Proceed after validation"


def test_loader_preserves_question_code_indentation(tmp_path: Path):
    payload = [
        {
            "question": "Find bug:\nfor i in range(3):\n    if i % 2 == 0:\n        print(i)\nprint('done')",
            "options": [
                "IndentationError",
                "NameError",
                "No issue",
                "TypeError",
            ],
            "correct_answer": "No issue",
            "topic": "Debugging",
        }
    ]
    _write_bank(tmp_path, "python/debug_bank.json", payload)

    loader = QuestionLoader(base_path=str(tmp_path))
    questions = loader.load("python/debug_bank.json")
    question_text = questions[0]["question"]

    assert "    if i % 2 == 0:" in question_text
    assert "        print(i)" in question_text


def test_loader_sanitizes_corrupted_output_question_options(tmp_path: Path):
    payload = [
        {
            "question": "A snippet runs with the following behavior. Which output is correct? print('Hello'.lower())?",
            "options": [
                "Hello in enterprise environments for large-scale systems",
                "Prioritize correctness and resilience in enterprise environments",
                "Use observability-driven diagnosis",
                "float",
            ],
            "correct_answer": "Hello in enterprise environments for large-scale systems",
            "topic": "Python Basics",
        }
    ]
    _write_bank(tmp_path, "python/custom_output_bank.json", payload)

    loader = QuestionLoader(base_path=str(tmp_path))
    question = loader.load("python/custom_output_bank.json")[0]

    assert question["question"].startswith(
        "A snippet runs with the following behavior. Which output is correct?"
    )
    assert "\nprint('Hello'.lower())" in question["question"]
    assert all("enterprise environments" not in opt.lower() for opt in question["options"])
    assert "Prioritize correctness and resilience in enterprise environments" not in question["options"]
    assert "Use observability-driven diagnosis" not in question["options"]
    assert "Hello" in question["options"]
    assert question["correct_answer"] == "Hello"
    assert len(question["options"]) >= 4
