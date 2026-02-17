# app/utils/role_normalizer.py
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
    """Normalize a role label to its key, tolerant of hyphen/en-dash differences."""
    if not role_label:
        return None
    # Direct match first
    result = ROLE_NAME_TO_KEY.get(role_label)
    if result:
        return result
    # Normalize dashes: replace regular hyphen with en-dash and try again
    normalized = role_label.replace("-", "\u2013")
    result = ROLE_NAME_TO_KEY.get(normalized)
    if result:
        return result
    # Normalize dashes: replace en-dash with regular hyphen and try again
    normalized = role_label.replace("\u2013", "-")
    for key, value in ROLE_NAME_TO_KEY.items():
        if key.replace("\u2013", "-") == normalized:
            return value
    return None
