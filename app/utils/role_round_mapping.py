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
    }
}

# Map role_key → coding language for L4
# Roles with C/C++ can be added here as needed
ROLE_CODING_LANGUAGE = {
    "java_entry": "java",
    "java_aws": "java",
    "java_qa": "java",
    # "python_entry": "c",      # uncomment to enable C coding for python roles
    # "python_dev": "cpp",      # uncomment to enable C++ coding for python dev
}
