# app/utils/role_normalizer.py
import html
import re


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


def _normalize_role_label(value: str) -> str:
    text = html.unescape(str(value or ""))
    text = text.replace("\u00e2\u20ac\u201c", "-").replace("\u00e2\u20ac\u201d", "-")
    text = text.replace("\u2013", "-").replace("\u2014", "-")
    text = re.sub(r"\s*-\s*", "-", text)
    text = re.sub(r"\s*\+\s*", "+", text)
    text = " ".join(text.split())
    return text.strip().lower()

_NORMALIZED_ROLE_NAME_TO_KEY = {
    _normalize_role_label(label): role_key
    for label, role_key in ROLE_NAME_TO_KEY.items()
}


def normalize_role(role_label: str) -> str:
    direct = ROLE_NAME_TO_KEY.get(role_label)
    if direct:
        return direct

    return _NORMALIZED_ROLE_NAME_TO_KEY.get(_normalize_role_label(role_label))
