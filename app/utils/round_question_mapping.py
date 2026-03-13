# app/utils/round_question_mapping.py

ROUND_QUESTION_MAPPING = {

    # -------------------------------------------------
    # PYTHON ENTRY
    # -------------------------------------------------
    "python_entry": {
        "L1": ["aptitude.json"],
        "L2": ["python/python_entry_theory_debug.json"],
        "L5": ["soft_skills.json"],
    },

    # -------------------------------------------------
    # JAVA ENTRY
    # -------------------------------------------------
    "java_entry": {
        "L1": ["aptitude.json"],
        "L2": ["java/java_entry_theory.json"],
        "L5": ["soft_skills.json"],
    },

    # -------------------------------------------------
    # JAVASCRIPT ENTRY
    # -------------------------------------------------
    "js_entry": {
        "L1": ["aptitude.json"],
        "L2": ["java_script/js_entry_theory_debug.json"],
        "L5": ["soft_skills.json"],
    },

    # -------------------------------------------------
    # PYTHON QA
    # -------------------------------------------------
    "python_qa": {
        "L2": ["python/python_senior_theory_debug.json"],
        "L3": ["qa/python_qa_enterprise_shared.json"],
        "L5": ["soft_skills.json"],
    },

    # -------------------------------------------------
    # PYTHON QA + LINUX
    # -------------------------------------------------
    "python_qa_linux": {
        "L1": ["linux/linux_fundamentals_enterprise.json"],
        "L2": ["python/python_senior_theory_debug.json"],
        "L3": ["qa/python_qa_enterprise_shared.json"],
        "L5": ["soft_skills.json"],
    },

    # -------------------------------------------------
    # PYTHON DEVELOPER
    # -------------------------------------------------
    "python_dev": {
        "L2": ["python/python_senior_theory_debug.json"],
        "L3": ["dev/python_dev_engineering.json"],
        "L5": ["soft_skills.json"],
    },

    # -------------------------------------------------
    # PYTHON AI / ML
    # -------------------------------------------------
    "python_ai_ml": {
        "L2": ["python/python_senior_theory_debug.json"],
        "L3": ["AI/ML/ai_ml_engineering.json"],
        "L5": ["soft_skills.json"],
    },

    # -------------------------------------------------
    # JAVA AWS
    # -------------------------------------------------
    "java_aws": {
        "L2": ["java/java_senior_theory_debug.json"],
        "L3": ["cloud/java_aws_cloud.json"],
        "L5": ["soft_skills.json"],
    },

    # -------------------------------------------------
    # JAVA QA
    # -------------------------------------------------
    "java_qa": {
        "L2": ["java/java_senior_theory_debug.json"],
        "L3": ["qa/java_qa_advanced.json"],
        "L5": ["soft_skills.json"],
    },

    # -------------------------------------------------
    # BMC ENGINEER  (Phase 3)
    # -------------------------------------------------
    "bmc_engineer": {
        "L2": ["c/c_senior_theory_debug.json"],
        "L3": ["bmc/bmc_firmware_engineering.json"],
        "L5": ["soft_skills.json"],
    },

    # -------------------------------------------------
    # STAFF ENGINEER - LINUX KERNEL & DEVICE DRIVER  (Phase 3)
    # -------------------------------------------------
    "linux_kernel_dd": {
        "L1": ["c/c_senior_theory_debug.json"],
        "L2": ["linux/linux_kernel_engineering.json"],
        "L3": ["device_driver/device_driver_engineering.json"],
        "L5": ["soft_skills_leadership.json"],
    },

    # -------------------------------------------------
    # SYSTEMS ARCHITECT (C++ BASED)  (Phase 3)
    # -------------------------------------------------
    "systems_architect_cpp": {
        "L2": ["cpp/cpp_senior_theory_debug.json"],
        "L3": ["system_design/cpp_system_design_architecture.json"],
        "L5": ["soft_skills.json"],
    },

    # -------------------------------------------------
    # C# DEVELOPER (3-6 YEARS)
    # -------------------------------------------------
    "csharp_dev": {
        "L2": ["csharp/csharp_senior_theory_debug.json"],
        "L3": ["dev/csharp_dev_foundations.json"],
        "L5": ["soft_skills.json"],
    },
}


# Domain rounds (COMMON)
DOMAIN_QUESTION_FILES = {
    "storage": ["domains/storage.json"],
    "virtualization": ["domains/virtualisation.json"],
    "networking": ["domains/networking.json"],
}
