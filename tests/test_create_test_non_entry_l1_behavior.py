from app.utils.role_round_mapping import ROLE_ROUND_MAPPING


def test_non_entry_roles_do_not_include_aptitude_l1():
    non_entry_no_l1 = (
        "python_qa",
        "python_dev",
        "python_ai_ml",
        "java_qa",
        "java_aws",
        "bmc_engineer",
        "systems_architect_cpp",
        "csharp_dev",
    )
    for role_key in non_entry_no_l1:
        assert "L1" not in ROLE_ROUND_MAPPING[role_key]["rounds"]


def test_non_entry_roles_with_real_technical_l1_are_preserved():
    assert ROLE_ROUND_MAPPING["python_qa_linux"]["rounds"][0] == "L1"
    assert ROLE_ROUND_MAPPING["linux_kernel_dd"]["rounds"][0] == "L1"
