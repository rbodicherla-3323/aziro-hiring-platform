from app.services.question_bank.loader import QuestionLoader


SHARED_BANKS = (
    "aptitude.json",
    "soft_skills.json",
    "soft_skills_leadership.json",
    "domains/networking.json",
    "domains/storage.json",
    "domains/virtualisation.json",
)


def _load_questions(relative_path):
    loader = QuestionLoader(base_path="app/services/question_bank/data")
    return loader.load(relative_path)


def test_shared_banks_pass_strict_validation():
    forbidden_markers = (
        "for that enterprise scenario",
        "while meeting reliability expectations",
        "with accountable communication and traceability",
        "with validated operational controls",
        "delay action without confirming impact",
    )
    for bank in SHARED_BANKS:
        questions = _load_questions(bank)
        assert questions, f"no questions loaded for {bank}"
        for question in questions:
            options = question.get("options") or []
            assert len(options) >= 4, f"insufficient options for {bank} question {question.get('id')}"
            correct = question.get("correct_answer")
            assert correct in options, f"correct answer missing from options for {bank} question {question.get('id')}"
            for option in options:
                low = str(option or "").lower()
                assert not any(marker in low for marker in forbidden_markers), (
                    f"artifact marker remained in {bank} question {question.get('id')}: {option}"
                )
