from app.utils.round_question_mapping import ROUND_QUESTION_MAPPING


def test_java_role_mappings_point_to_new_banks():
    assert ROUND_QUESTION_MAPPING["java_entry"]["L2"] == ["java/java_entry_theory.json"]
    assert ROUND_QUESTION_MAPPING["java_entry"]["L3"] == ["java/java_entry_fundamentals.json"]
    assert ROUND_QUESTION_MAPPING["java_qa"]["L2"] == ["java/java_senior_theory_debug.json"]
    assert ROUND_QUESTION_MAPPING["java_qa"]["L3"] == ["qa/java_qa_advanced.json"]
    assert ROUND_QUESTION_MAPPING["java_aws"]["L2"] == ["java/java_senior_theory_debug.json"]
    assert ROUND_QUESTION_MAPPING["java_aws"]["L3"] == ["cloud/java_aws_cloud.json"]


def test_java_role_mappings_no_longer_use_legacy_shared_banks():
    java_targets = []
    for role_key in ("java_entry", "java_qa", "java_aws"):
        for file_list in ROUND_QUESTION_MAPPING[role_key].values():
            java_targets.extend(file_list)

    assert "java/java_theory.json" not in java_targets
    assert "qa/qa.json" not in java_targets
    assert "cloud/aws_basics.json" not in java_targets
