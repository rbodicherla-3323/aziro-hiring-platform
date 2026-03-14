# app/utils/role_normalizer.py
import html
import re


ROLE_NAME_TO_KEY = {
    "Python Entry Level (0-2 Years)": "python_entry",
    "Java Entry Level (0-2 Years)": "java_entry",
    "JavaScript Entry Level (0-2 Years)": "js_entry",
    "Python QA / System / Linux (4+ Years)": "python_qa_linux",
    "Python QA (4+ Years)": "python_qa",
    "Python Development (4+ Years)": "python_dev",
    "Python + AI/ML (4+ Years)": "python_ai_ml",
    "Java + AWS Development (5+ Years)": "java_aws",
    "Java QA (5+ Years)": "java_qa",
    "BMC Engineer (2-5 Years)": "bmc_engineer",
    "Staff Engineer - Linux Kernel & Device Driver (3-5 Years)": "linux_kernel_dd",
    "Systems Architect - C++ (3-5 Years)": "systems_architect_cpp",
    "C++ Developer (3-6 Years)": "cpp_dev",
    "C# Developer (3-6 Years)": "csharp_dev",
}


ROLE_LABEL_ALIASES = {
    "Python Entry Level (0\u20132 Years)": "python_entry",
    "Java Entry Level (0\u20132 Years)": "java_entry",
    "JavaScript Entry Level (0\u20132 Years)": "js_entry",
    "BMC Engineer (2\u20135 Years)": "bmc_engineer",
    "Staff Engineer \u2013 Linux Kernel & Device Driver (3\u20135 Years)": "linux_kernel_dd",
    "Systems Architect \u2013 C++ (3\u20135 Years)": "systems_architect_cpp",
    "C++ Developer (3\u20136 Years)": "cpp_dev",
    "C# Developer (3\u20136 Years)": "csharp_dev",
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
    for label, role_key in {**ROLE_NAME_TO_KEY, **ROLE_LABEL_ALIASES}.items()
}


def normalize_role(role_label: str) -> str:
    direct = ROLE_NAME_TO_KEY.get(role_label)
    if direct:
        return direct

    alias = ROLE_LABEL_ALIASES.get(role_label)
    if alias:
        return alias

    return _NORMALIZED_ROLE_NAME_TO_KEY.get(_normalize_role_label(role_label))
