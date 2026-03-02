# app/utils/role_round_mapping.py
ROLE_ROUND_MAPPING = {
    "python_entry": {
        "rounds": ["L1", "L2", "L3", "L5"],
        "coding_rounds": ["L4"],
        "coding_language": "python",
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
        "coding_rounds": ["L4"],
        "coding_language": "javascript",
        "allow_domain": False
    },
    "python_qa": {
        "rounds": ["L1", "L2", "L3", "L5"],
        "coding_rounds": ["L4"],
        "coding_language": "python",
        "allow_domain": True
    },
    "python_qa_linux": {
        "rounds": ["L1", "L2", "L3", "L5"],
        "coding_rounds": ["L4"],
        "coding_language": "python",
        "allow_domain": True
    },
    "python_dev": {
        "rounds": ["L1", "L2", "L3", "L5"],
        "coding_rounds": ["L4"],
        "coding_language": "python",
        "allow_domain": True
    },
    "python_ai_ml": {
        "rounds": ["L1", "L2", "L3", "L5"],
        "coding_rounds": ["L4"],
        "coding_language": "python",
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
        "allow_domain": True
    },

    # Staff Engineer - Linux Kernel & Device Driver:
    # C Theory -> Linux Kernel -> Device Driver -> Coding (C) -> Soft Skills (Leadership)
    "linux_kernel_dd": {
        "rounds": ["L1", "L2", "L3", "L5"],
        "coding_rounds": ["L4"],
        "coding_language": "c",
        "allow_domain": True
    },

    # Systems Architect (C++ Based):
    # Aptitude -> C++ Theory -> System Design -> Coding (C++) -> Soft Skills
    "systems_architect_cpp": {
        "rounds": ["L1", "L2", "L3", "L5"],
        "coding_rounds": ["L4"],
        "coding_language": "cpp",
        "allow_domain": True
    },

    # C# Developer (3-6 Years):
    # C# Theory + Debugging -> Developer Foundations -> Coding (C#) -> Soft Skills
    "csharp_dev": {
        "rounds": ["L2", "L3", "L5"],
        "coding_rounds": ["L4"],
        "coding_language": "csharp",
        "allow_domain": True
    },
}

# Map role_key -> coding language for L4
ROLE_CODING_LANGUAGE = {
    "python_entry": "python",
    "java_entry": "java",
    "js_entry": "javascript",
    "python_qa_linux": "python",
    "python_qa": "python",
    "python_dev": "python",
    "python_ai_ml": "python",
    "java_aws": "java",
    "java_qa": "java",
    "bmc_engineer": "c",
    "linux_kernel_dd": "c",
    "systems_architect_cpp": "cpp",
}
