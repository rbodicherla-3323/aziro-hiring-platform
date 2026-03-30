from app.utils.round_question_mapping import ROUND_QUESTION_MAPPING


def test_all_in_scope_role_round_banks_match_enterprise_mapping():
    expected = {
        "python_entry": {
            "L1": ["aptitude.json"],
            "L2": ["python/python_entry_theory_debug.json"],
            "L5": ["soft_skills.json"],
        },
        "java_entry": {
            "L1": ["aptitude.json"],
            "L2": ["java/java_entry_theory.json"],
            "L5": ["soft_skills.json"],
        },
        "js_entry": {
            "L1": ["aptitude.json"],
            "L2": ["java_script/js_entry_theory_debug.json"],
            "L5": ["soft_skills.json"],
        },
        "python_qa_linux": {
            "L1": ["linux/linux_fundamentals_enterprise.json"],
            "L2": ["python/python_senior_theory_debug.json"],
            "L3": ["qa/python_qa_enterprise_shared.json"],
            "L5": ["soft_skills.json"],
        },
        "python_dev": {
            "L2": ["python/python_senior_theory_debug.json"],
            "L3": ["dev/python_dev_engineering.json"],
            "L5": ["soft_skills.json"],
        },
        "python_ai_ml": {
            "L2": ["python/python_senior_theory_debug.json"],
            "L3": ["AI/ML/ai_ml_engineering.json"],
            "L5": ["soft_skills.json"],
        },
        "java_qa": {
            "L2": ["java/java_senior_theory_debug.json"],
            "L3": ["qa/java_qa_advanced.json"],
            "L5": ["soft_skills.json"],
        },
        "java_aws": {
            "L2": ["java/java_senior_theory_debug.json"],
            "L3": ["cloud/java_aws_cloud.json"],
            "L5": ["soft_skills.json"],
        },
        "bmc_engineer": {
            "L2": ["c/c_senior_theory_debug.json"],
            "L3": ["bmc/bmc_firmware_engineering.json"],
            "L5": ["soft_skills.json"],
        },
        "linux_kernel_dd": {
            "L1": ["c/c_senior_theory_debug.json"],
            "L2": ["linux/linux_kernel_engineering.json"],
            "L3": ["device_driver/device_driver_engineering.json"],
            "L5": ["soft_skills_leadership.json"],
        },
        "systems_architect_cpp": {
            "L2": ["cpp/cpp_senior_theory_debug.json"],
            "L3": ["system_design/cpp_system_design_architecture.json"],
            "L5": ["soft_skills.json"],
        },
        "csharp_dev": {
            "L2": ["csharp/csharp_senior_theory_debug.json"],
            "L3": ["dev/csharp_dev_foundations.json"],
            "L5": ["soft_skills.json"],
        },
    }
    for role_key, expected_rounds in expected.items():
        assert ROUND_QUESTION_MAPPING[role_key] == expected_rounds


def test_python_qa_no_longer_includes_aptitude_l1():
    assert ROUND_QUESTION_MAPPING["python_qa"] == {
        "L2": ["python/python_senior_theory_debug.json"],
        "L3": ["qa/python_qa_enterprise_ui.json"],
        "L3A": ["qa/python_qa_enterprise_api.json"],
        "L5": ["soft_skills.json"],
    }
