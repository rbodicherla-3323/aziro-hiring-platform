# app/utils/round_question_mapping.py

ROUND_QUESTION_MAPPING = {

    # -------------------------------------------------
    # PYTHON ENTRY
    # -------------------------------------------------
    "python_entry": {
        "L1": ["aptitude.json"],
        "L2": ["python/python_theory.json"],
        "L3": ["python/python_theory.json"],
        "L5": ["soft_skills.json"]
    },

    # -------------------------------------------------
    # JAVA ENTRY
    # -------------------------------------------------
    "java_entry": {
        "L1": ["aptitude.json"],
        "L2": ["java/java_theory.json"],
        "L3": ["java/java_theory.json"],
        "L5": ["soft_skills.json"]
    },

    # -------------------------------------------------
    # JAVASCRIPT ENTRY
    # -------------------------------------------------
    "js_entry": {
        "L1": ["aptitude.json"],
        "L2": ["java_script/java_script_theory.json"],
        "L3": ["java_script/java_script_theory.json"],
        "L5": ["soft_skills.json"]
    },

    # -------------------------------------------------
    # PYTHON QA
    # -------------------------------------------------
    "python_qa": {
        "L1": ["aptitude.json"],
        "L2": ["python/python_theory.json"],
        "L3": ["qa/qa.json"],
        "L5": ["soft_skills.json"]
    },

    # -------------------------------------------------
    # PYTHON QA + LINUX
    # -------------------------------------------------
    "python_qa_linux": {
        "L1": ["linux/linux_basics.json"],
        "L2": ["python/python_theory.json"],
        "L3": ["qa/qa.json"],
        "L5": ["soft_skills.json"]
    },

    # -------------------------------------------------
    # PYTHON DEVELOPER
    # -------------------------------------------------
    "python_dev": {
        "L1": ["aptitude.json"],
        "L2": ["python/python_theory.json"],
        "L3": ["dev/dev_basics.json"],
        "L5": ["soft_skills.json"]
    },

    # -------------------------------------------------
    # PYTHON AI / ML
    # -------------------------------------------------
    "python_ai_ml": {
        "L1": ["aptitude.json"],
        "L2": ["python/python_theory.json"],
        "L3": ["AI/ML/ai_ml_basics.json"],
        "L5": ["soft_skills.json"]
    },

    # -------------------------------------------------
    # JAVA AWS
    # -------------------------------------------------
    "java_aws": {
        "L1": ["aptitude.json"],
        "L2": ["java/java_theory.json"],
        "L3": ["cloud/aws_basics.json"],
        "L5": ["soft_skills.json"]
    },

    # -------------------------------------------------
    # JAVA QA
    # -------------------------------------------------
    "java_qa": {
        "L1": ["aptitude.json"],
        "L2": ["java/java_theory.json"],
        "L3": ["qa/qa.json"],
        "L5": ["soft_skills.json"]
    },

    # -------------------------------------------------
    # BMC ENGINEER  (Phase 3)
    # -------------------------------------------------
    "bmc_engineer": {
        "L1": ["aptitude.json"],
        "L2": ["c/c_theory.json"],
        "L3": ["bmc/bmc_firmware.json"],
        "L5": ["soft_skills.json"]
    },

    # -------------------------------------------------
    # STAFF ENGINEER - LINUX KERNEL & DEVICE DRIVER  (Phase 3)
    # -------------------------------------------------
    "linux_kernel_dd": {
        "L1": ["c/c_theory.json"],
        "L2": ["linux/linux_kernel.json"],
        "L3": ["device_driver/device_driver_basics.json"],
        "L5": ["soft_skills_leadership.json"]
    },

    # -------------------------------------------------
    # SYSTEMS ARCHITECT (C++ BASED)  (Phase 3)
    # -------------------------------------------------
    "systems_architect_cpp": {
        "L1": ["aptitude.json"],
        "L2": ["cpp/cpp_theory.json"],
        "L3": ["system_design/system_design_architecture.json"],
        "L5": ["soft_skills.json"]
    },
}


# Domain rounds (COMMON)
DOMAIN_QUESTION_FILES = {
    "storage": ["domains/storage.json"],
    "virtualization": ["domains/virtualisation.json"],
    "networking": ["domains/networking.json"]
}
