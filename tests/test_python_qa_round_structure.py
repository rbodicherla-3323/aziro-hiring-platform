from app.utils.role_round_mapping import ROLE_ROUND_MAPPING
from app.utils.round_display_mapping import ROUND_DISPLAY_MAPPING
from app.utils.round_order import ordered_present_round_keys


def test_python_qa_uses_five_step_live_round_structure():
    cfg = ROLE_ROUND_MAPPING["python_qa"]

    assert cfg["rounds"] == ["L2", "L3", "L3A", "L5"]
    assert cfg["coding_rounds"] == ["L4"]
    assert cfg["coding_language"] == "python"
    assert cfg["allow_domain"] is False


def test_python_qa_round_labels_and_order_match_live_flow():
    labels = ROUND_DISPLAY_MAPPING["python_qa"]

    assert labels["L2"] == "Python Theory + Debugging"
    assert labels["L3"] == "Python UI Automation"
    assert labels["L3A"] == "Python API Automation"
    assert labels["L4"] == "Coding Challenge (Python)"
    assert labels["L5"] == "Soft Skills"

    ordered = ordered_present_round_keys({"L2": {}, "L3": {}, "L3A": {}, "L4": {}, "L5": {}})
    assert ordered == ["L2", "L3", "L3A", "L4", "L5"]
