# filepath: d:\Projects\aziro-hiring-platform\app\utils\role_normalizer.py
ROLE_NAME_TO_KEY = {
    "Python Entry Level (0–2 Years)": "python_entry",
    "Java Entry Level (0–2 Years)": "java_entry",
    "JavaScript Entry Level (0–2 Years)": "js_entry",
    "Python QA / System / Linux (4+ Years)": "python_qa_linux",
    "Python QA (4+ Years)": "python_qa",
    "Python Development (4+ Years)": "python_dev",
    "Python + AI/ML (4+ Years)": "python_ai_ml",
    "Java + AWS Development (5+ Years)": "java_aws",
    "Java QA (5+ Years)": "java_qa",
    # ---- Phase 3: New Roles ----
    "BMC Engineer (2–5 Years)": "bmc_engineer",
    "Staff Engineer – Linux Kernel & Device Driver (3–5 Years)": "linux_kernel_dd",
    "Systems Architect – C++ (3–5 Years)": "systems_architect_cpp",
}


def normalize_role(role_label: str) -> str:
    return ROLE_NAME_TO_KEY.get(role_label)
