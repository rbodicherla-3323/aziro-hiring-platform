ROLE_NAME_TO_KEY = {
    "Python Entry Level (0–2 Years)": "python_entry",
    "Java Entry Level (0–2 Years)": "java_entry",
    "JavaScript Entry Level (0–2 Years)": "js_entry",
    "Python QA / System / Linux (4+ Years)": "python_qa_linux",
    "Python QA (4+ Years)": "python_qa",
    "Python Development (4+ Years)": "python_dev",
    "Python + AI/ML (4+ Years)": "python_ai_ml",
    "Java + AWS Development (5+ Years)": "java_aws",
    "Java QA (5+ Years)": "java_qa"
}


def normalize_role(role_label: str) -> str:
    return ROLE_NAME_TO_KEY.get(role_label)
