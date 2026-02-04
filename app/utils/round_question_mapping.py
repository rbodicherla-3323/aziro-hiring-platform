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
    }
}


# Domain rounds (COMMON)
DOMAIN_QUESTION_FILES = {
    "Storage": ["domains/storage.json"],
    "Virtualization": ["domains/virtualisation.json"],
    "Networking": ["domains/networking.json"]
}
