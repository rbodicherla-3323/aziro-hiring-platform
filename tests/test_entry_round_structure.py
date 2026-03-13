from app.utils.role_round_mapping import ROLE_ROUND_MAPPING
from app.utils.round_display_mapping import ROUND_DISPLAY_MAPPING
from app.utils.round_question_mapping import ROUND_QUESTION_MAPPING


def test_entry_roles_use_fixed_four_round_structure():
    for role_key in ("python_entry", "java_entry", "js_entry"):
        cfg = ROLE_ROUND_MAPPING[role_key]
        assert cfg["rounds"] == ["L1", "L2", "L5"]
        assert cfg["coding_rounds"] == ["L4"]


def test_entry_roles_l2_is_theory_plus_debugging_and_no_l3_mapping():
    assert ROUND_DISPLAY_MAPPING["python_entry"]["L2"] == "Python Theory + Debugging"
    assert ROUND_DISPLAY_MAPPING["java_entry"]["L2"] == "Java Theory + Debugging"
    assert ROUND_DISPLAY_MAPPING["js_entry"]["L2"] == "JavaScript Theory + Debugging"

    for role_key in ("python_entry", "java_entry", "js_entry"):
        assert "L3" not in ROUND_QUESTION_MAPPING[role_key]

