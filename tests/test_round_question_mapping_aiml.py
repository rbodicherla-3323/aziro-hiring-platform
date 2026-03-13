from app.utils.round_question_mapping import ROUND_QUESTION_MAPPING


def test_python_aiml_mapping_points_to_enterprise_bank():
    assert ROUND_QUESTION_MAPPING["python_ai_ml"]["L2"] == ["python/python_senior_theory_debug.json"]
    assert ROUND_QUESTION_MAPPING["python_ai_ml"]["L3"] == ["AI/ML/ai_ml_engineering.json"]
