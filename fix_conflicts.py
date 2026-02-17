"""Fix merge conflicts by writing clean resolved files."""
import os

# 1. role_normalizer.py
with open('app/utils/role_normalizer.py', 'w', encoding='utf-8') as f:
    f.write('''# app/utils/role_normalizer.py
ROLE_NAME_TO_KEY = {
    "Python Entry Level (0\u20132 Years)": "python_entry",
    "Java Entry Level (0\u20132 Years)": "java_entry",
    "JavaScript Entry Level (0\u20132 Years)": "js_entry",
    "Python QA / System / Linux (4+ Years)": "python_qa_linux",
    "Python QA (4+ Years)": "python_qa",
    "Python Development (4+ Years)": "python_dev",
    "Python + AI/ML (4+ Years)": "python_ai_ml",
    "Java + AWS Development (5+ Years)": "java_aws",
    "Java QA (5+ Years)": "java_qa",
    # ---- Phase 3: New Roles ----
    "BMC Engineer (2\u20135 Years)": "bmc_engineer",
    "Staff Engineer \u2013 Linux Kernel & Device Driver (3\u20135 Years)": "linux_kernel_dd",
    "Systems Architect \u2013 C++ (3\u20135 Years)": "systems_architect_cpp",
}


def normalize_role(role_label: str) -> str:
    return ROLE_NAME_TO_KEY.get(role_label)
''')
print("1. role_normalizer.py written")

# 2. role_round_mapping.py
with open('app/utils/role_round_mapping.py', 'w', encoding='utf-8') as f:
    f.write('''# app/utils/role_round_mapping.py
ROLE_ROUND_MAPPING = {
    "python_entry": {
        "rounds": ["L1", "L2", "L3", "L5"],
        "coding_rounds": [],
        "allow_domain": False
    },
    "java_entry": {
        "rounds": ["L1", "L2", "L3", "L5"],
        "coding_rounds": ["L4"],
        "coding_language": "java",
        "allow_domain": False
    },
    "js_entry": {
        "rounds": ["L1", "L2", "L3", "L5"],
        "coding_rounds": [],
        "allow_domain": False
    },
    "python_qa": {
        "rounds": ["L1", "L2", "L3", "L5"],
        "coding_rounds": [],
        "allow_domain": True
    },
    "python_qa_linux": {
        "rounds": ["L1", "L2", "L3", "L5"],
        "coding_rounds": [],
        "allow_domain": True
    },
    "python_dev": {
        "rounds": ["L1", "L2", "L3", "L5"],
        "coding_rounds": [],
        "allow_domain": True
    },
    "python_ai_ml": {
        "rounds": ["L1", "L2", "L3", "L5"],
        "coding_rounds": [],
        "allow_domain": True
    },
    "java_aws": {
        "rounds": ["L1", "L2", "L3", "L5"],
        "coding_rounds": ["L4"],
        "coding_language": "java",
        "allow_domain": True
    },
    "java_qa": {
        "rounds": ["L1", "L2", "L3", "L5"],
        "coding_rounds": ["L4"],
        "coding_language": "java",
        "allow_domain": True
    },

    # ---- Phase 3: New Roles ----

    # BMC Engineer: Aptitude -> C Theory -> BMC/Firmware -> Coding (C) -> Soft Skills
    "bmc_engineer": {
        "rounds": ["L1", "L2", "L3", "L5"],
        "coding_rounds": ["L4"],
        "coding_language": "c",
        "allow_domain": False
    },

    # Staff Engineer - Linux Kernel & Device Driver:
    # C Theory -> Linux Kernel -> Device Driver -> Coding (C) -> Soft Skills (Leadership)
    "linux_kernel_dd": {
        "rounds": ["L1", "L2", "L3", "L5"],
        "coding_rounds": ["L4"],
        "coding_language": "c",
        "allow_domain": False
    },

    # Systems Architect (C++ Based):
    # Aptitude -> C++ Theory -> System Design -> Coding (C++) -> Soft Skills
    "systems_architect_cpp": {
        "rounds": ["L1", "L2", "L3", "L5"],
        "coding_rounds": ["L4"],
        "coding_language": "cpp",
        "allow_domain": False
    },
}

# Map role_key -> coding language for L4
ROLE_CODING_LANGUAGE = {
    "java_entry": "java",
    "java_aws": "java",
    "java_qa": "java",
    "bmc_engineer": "c",
    "linux_kernel_dd": "c",
    "systems_architect_cpp": "cpp",
}
''')
print("2. role_round_mapping.py written")

# 3. round_display_mapping.py
with open('app/utils/round_display_mapping.py', 'w', encoding='utf-8') as f:
    f.write('''# app/utils/round_display_mapping.py
ROUND_DISPLAY_MAPPING = {

    # ---------------- Python Entry ----------------
    "python_entry": {
        "L1": "Aptitude",
        "L2": "Python Theory",
        "L3": "Python Fundamentals",
        "L4": "Coding Challenge",
        "L5": "Soft Skills",
    },

    # ---------------- Java Entry ----------------
    "java_entry": {
        "L1": "Aptitude",
        "L2": "Java Theory",
        "L3": "Java Fundamentals",
        "L4": "Coding Challenge",
        "L5": "Soft Skills",
    },

    # ---------------- JavaScript Entry ----------------
    "js_entry": {
        "L1": "Aptitude",
        "L2": "JavaScript Theory",
        "L3": "JavaScript Fundamentals",
        "L4": "Coding Challenge",
        "L5": "Soft Skills",
    },

    # ---------------- Python QA ----------------
    "python_qa": {
        "L1": "Aptitude",
        "L2": "Python Theory",
        "L3": "QA & Testing",
        "L4": "Coding Challenge",
        "L5": "Soft Skills",
    },

    # ---------------- Python QA + Linux ----------------
    "python_qa_linux": {
        "L1": "Linux Fundamentals",
        "L2": "Python Theory",
        "L3": "QA & Testing (Advanced)",
        "L4": "Coding Challenge",
        "L5": "Soft Skills",
    },

    # ---------------- Python Developer ----------------
    "python_dev": {
        "L1": "Aptitude",
        "L2": "Python Advanced Concepts",
        "L3": "Development Skills",
        "L4": "Coding Challenge",
        "L5": "Soft Skills",
    },

    # ---------------- Python AI / ML ----------------
    "python_ai_ml": {
        "L1": "Aptitude",
        "L2": "Python Advanced Concepts",
        "L3": "AI / ML Fundamentals",
        "L4": "Coding Challenge",
        "L5": "Soft Skills",
    },

    # ---------------- Java AWS ----------------
    "java_aws": {
        "L1": "Aptitude",
        "L2": "Java Advanced Concepts",
        "L3": "AWS & Cloud Development",
        "L4": "Coding Challenge",
        "L5": "Soft Skills",
    },

    # ---------------- Java QA ----------------
    "java_qa": {
        "L1": "Aptitude",
        "L2": "Java Theory",
        "L3": "QA & Testing (Advanced)",
        "L4": "Coding Challenge",
        "L5": "Soft Skills",
    },

    # ---- Phase 3: New Roles ----

    # ---------------- BMC Engineer ----------------
    "bmc_engineer": {
        "L1": "Aptitude",
        "L2": "C Language Theory",
        "L3": "BMC / Firmware",
        "L4": "Coding Challenge (C)",
        "L5": "Soft Skills",
    },

    # ---------------- Linux Kernel & Device Driver ----------------
    "linux_kernel_dd": {
        "L1": "C Theoretical",
        "L2": "Linux Kernel Theory",
        "L3": "Device Driver Basics & Theory",
        "L4": "Coding Challenge (C)",
        "L5": "Soft Skills (Leadership & Ownership)",
    },

    # ---------------- Systems Architect (C++) ----------------
    "systems_architect_cpp": {
        "L1": "Aptitude",
        "L2": "C++ Theory",
        "L3": "System Design & Architecture",
        "L4": "Coding Challenge (C++)",
        "L5": "Soft Skills",
    },
}
''')
print("3. round_display_mapping.py written")

# 4. round_question_mapping.py
with open('app/utils/round_question_mapping.py', 'w', encoding='utf-8') as f:
    f.write('''# app/utils/round_question_mapping.py

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
''')
print("4. round_question_mapping.py written")

print("\nAll 4 config files resolved!")
