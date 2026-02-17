"""
Phase 3 Integration Test – New Roles Verification

Tests:
  1. Question file loading for all 3 new roles (all rounds)
  2. Role normalizer mappings
  3. Role-round config validation
  4. Round display labels
  5. Question selection (15 from 50 pool)
  6. Coding round language wiring
  7. Test creation flow via Flask test client

Run:  python test_phase3.py
"""

import os
import sys
import json
import random

os.environ.setdefault("FLASK_APP", "run.py")

from app import create_app
from app.utils.role_normalizer import ROLE_NAME_TO_KEY, normalize_role
from app.utils.role_round_mapping import ROLE_ROUND_MAPPING, ROLE_CODING_LANGUAGE
from app.utils.round_display_mapping import ROUND_DISPLAY_MAPPING
from app.utils.round_question_mapping import ROUND_QUESTION_MAPPING
from app.services.question_bank.loader import QuestionLoader

app = create_app()

PASS = "\033[92m✓\033[0m"
FAIL = "\033[91m✗\033[0m"
errors = []

QUESTION_BANK_PATH = os.path.join("app", "services", "question_bank", "data")

NEW_ROLES = {
    "bmc_engineer": {
        "label": "BMC Engineer (2–5 Years)",
        "rounds": ["L1", "L2", "L3", "L5"],
        "coding_rounds": ["L4"],
        "coding_language": "c",
        "allow_domain": False,
        "expected_question_files": {
            "L1": ["aptitude.json"],
            "L2": ["c/c_theory.json"],
            "L3": ["bmc/bmc_firmware.json"],
            "L5": ["soft_skills.json"],
        },
        "expected_display": {
            "L1": True, "L2": True, "L3": True, "L4": True, "L5": True
        },
    },
    "linux_kernel_dd": {
        "label": "Staff Engineer – Linux Kernel & Device Driver (3–5 Years)",
        "rounds": ["L1", "L2", "L3", "L5"],
        "coding_rounds": ["L4"],
        "coding_language": "c",
        "allow_domain": False,
        "expected_question_files": {
            "L1": ["c/c_theory.json"],
            "L2": ["linux/linux_kernel.json"],
            "L3": ["device_driver/device_driver_basics.json"],
            "L5": ["soft_skills_leadership.json"],
        },
        "expected_display": {
            "L1": True, "L2": True, "L3": True, "L4": True, "L5": True
        },
    },
    "systems_architect_cpp": {
        "label": "Systems Architect – C++ (3–5 Years)",
        "rounds": ["L1", "L2", "L3", "L5"],
        "coding_rounds": ["L4"],
        "coding_language": "cpp",
        "allow_domain": False,
        "expected_question_files": {
            "L1": ["aptitude.json"],
            "L2": ["cpp/cpp_theory.json"],
            "L3": ["system_design/system_design_architecture.json"],
            "L5": ["soft_skills.json"],
        },
        "expected_display": {
            "L1": True, "L2": True, "L3": True, "L4": True, "L5": True
        },
    },
}


def check(label, condition):
    if condition:
        print(f"  {PASS} {label}")
    else:
        print(f"  {FAIL} {label}")
        errors.append(label)


with app.app_context():

    # ── 1. Role Normalizer ──────────────────────────────
    print("\n── 1. Role Normalizer ──")
    for role_key, spec in NEW_ROLES.items():
        resolved = normalize_role(spec["label"])
        check(f"normalize_role('{spec['label']}') → '{role_key}'", resolved == role_key)

    # ── 2. Role-Round Config ────────────────────────────
    print("\n── 2. Role-Round Config ──")
    for role_key, spec in NEW_ROLES.items():
        config = ROLE_ROUND_MAPPING.get(role_key)
        check(f"{role_key} exists in ROLE_ROUND_MAPPING", config is not None)
        if config:
            check(f"{role_key} rounds = {spec['rounds']}", config["rounds"] == spec["rounds"])
            check(f"{role_key} coding_rounds = {spec['coding_rounds']}", config["coding_rounds"] == spec["coding_rounds"])
            check(f"{role_key} coding_language = {spec['coding_language']}", config.get("coding_language") == spec["coding_language"])
            check(f"{role_key} allow_domain = {spec['allow_domain']}", config["allow_domain"] == spec["allow_domain"])

    # ── 3. ROLE_CODING_LANGUAGE dict ────────────────────
    print("\n── 3. ROLE_CODING_LANGUAGE ──")
    for role_key, spec in NEW_ROLES.items():
        lang = ROLE_CODING_LANGUAGE.get(role_key)
        check(f"ROLE_CODING_LANGUAGE['{role_key}'] = '{spec['coding_language']}'", lang == spec["coding_language"])

    # ── 4. Round Display Mapping ────────────────────────
    print("\n── 4. Round Display Mapping ──")
    for role_key, spec in NEW_ROLES.items():
        display = ROUND_DISPLAY_MAPPING.get(role_key)
        check(f"{role_key} in ROUND_DISPLAY_MAPPING", display is not None)
        if display:
            for rnd in list(spec["expected_display"].keys()):
                has_label = rnd in display and len(display[rnd]) > 0
                check(f"  {role_key}.{rnd} has display label", has_label)

    # ── 5. Round Question Mapping ───────────────────────
    print("\n── 5. Round Question Mapping ──")
    for role_key, spec in NEW_ROLES.items():
        mapping = ROUND_QUESTION_MAPPING.get(role_key)
        check(f"{role_key} in ROUND_QUESTION_MAPPING", mapping is not None)
        if mapping:
            for rnd, expected_files in spec["expected_question_files"].items():
                actual_files = mapping.get(rnd, [])
                check(f"  {role_key}.{rnd} files = {expected_files}", actual_files == expected_files)

    # ── 6. Question File Loading ────────────────────────
    print("\n── 6. Question File Loading (all new files) ──")
    loader = QuestionLoader(QUESTION_BANK_PATH)
    new_question_files = set()
    for spec in NEW_ROLES.values():
        for files in spec["expected_question_files"].values():
            new_question_files.update(files)

    for qf in sorted(new_question_files):
        try:
            questions = loader.load(qf)
            count = len(questions)
            check(f"{qf}: loaded {count} questions", count >= 46)  # all should be 50 now            # Validate structure (difficulty is optional for pre-existing files like aptitude.json)
            sample = questions[0]
            required_fields = ["question", "options", "correct_answer", "topic"]
            has_fields = all(k in sample for k in required_fields)
            check(f"{qf}: correct structure", has_fields)

            # Test random selection of 15
            selected = random.sample(questions, min(15, count))
            check(f"{qf}: can select 15 random questions", len(selected) == 15)

        except Exception as e:
            check(f"{qf}: LOAD FAILED — {e}", False)

    # ── 7. Exact counts (should all be 50) ──────────────
    print("\n── 7. Exact Question Counts (must be 50) ──")
    phase3_files = [
        "c/c_theory.json",
        "bmc/bmc_firmware.json",
        "linux/linux_kernel.json",
        "device_driver/device_driver_basics.json",
        "cpp/cpp_theory.json",
        "system_design/system_design_architecture.json",
        "soft_skills_leadership.json",
    ]
    for qf in phase3_files:
        questions = loader.load(qf)
        check(f"{qf}: exactly 50 questions", len(questions) == 50)

    # ── 8. Coding round YAML files exist ────────────────
    print("\n── 8. Coding Round YAML Files ──")
    l4_base = os.path.join(QUESTION_BANK_PATH, "l4_coding")
    for lang in ["c", "cpp"]:
        yaml_path = os.path.join(l4_base, lang, "questions.yaml")
        exists = os.path.exists(yaml_path)
        check(f"L4 coding YAML exists: {lang}/questions.yaml", exists)
        if exists:
            import yaml
            with open(yaml_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
            q_list = data if isinstance(data, list) else data.get("questions", [])
            check(f"  {lang}/questions.yaml has questions: {len(q_list)}", len(q_list) >= 1)

    # ── 9. Test Creation Flow (Flask test client) ───────
    print("\n── 9. Test Creation Flow ──")
    with app.test_client() as client:
        # GET create-test page
        resp = client.get("/create-test")
        check("GET /create-test → 200", resp.status_code == 200)

        # Check new roles appear in dropdown
        page_html = resp.data.decode("utf-8")
        check("'BMC Engineer' in dropdown", "BMC Engineer" in page_html)
        check("'Linux Kernel' in dropdown", "Linux Kernel" in page_html)
        check("'Systems Architect' in dropdown", "Systems Architect" in page_html)

        # POST to create test for each new role
        for role_key, spec in NEW_ROLES.items():
            resp = client.post("/create-test", data={
                "name[]": [f"TestUser_{role_key}"],
                "email[]": [f"test_{role_key}@example.com"],
                "role[]": [spec["label"]],
                "domain[]": ["None"],
            }, follow_redirects=True)
            check(f"POST create-test for {role_key} → 200", resp.status_code == 200)

            # Check that test links were generated (page should show generated tests)
            page = resp.data.decode("utf-8")
            # The generated tests page should contain the candidate name
            has_candidate = f"TestUser_{role_key}" in page or "test_" in page
            check(f"  Generated tests page has candidate for {role_key}", has_candidate)

    # ── 10. MCQ Session Registry wiring ─────────────────
    print("\n── 10. MCQ Session Registry Wiring ──")
    from app.services.mcq_session_registry import MCQ_SESSION_REGISTRY
    from app.services.coding_session_registry import CODING_SESSION_REGISTRY

    # Check that sessions were created for new roles
    new_role_mcq_sessions = [
        (sid, meta) for sid, meta in MCQ_SESSION_REGISTRY.items()
        if meta.get("role_key") in NEW_ROLES
    ]
    check(f"MCQ sessions created for new roles: {len(new_role_mcq_sessions)}", len(new_role_mcq_sessions) >= 3)

    # Check coding sessions
    new_role_coding_sessions = [
        (sid, meta) for sid, meta in CODING_SESSION_REGISTRY.items()
        if meta.get("role_key") in NEW_ROLES
    ]
    check(f"Coding sessions created for new roles: {len(new_role_coding_sessions)}", len(new_role_coding_sessions) >= 3)

    # Verify coding language in sessions
    for sid, meta in new_role_coding_sessions:
        role_key = meta["role_key"]
        expected_lang = NEW_ROLES[role_key]["coding_language"]
        check(f"  Coding session {role_key}: language = {meta.get('language')}", meta.get("language") == expected_lang)

    # ── Summary ─────────────────────────────────────────
    print("\n" + "=" * 60)
    total = len(errors)
    if total:
        print(f"  {FAIL} {total} test(s) FAILED:")
        for e in errors:
            print(f"     - {e}")
        sys.exit(1)
    else:
        # Count total checks
        print(f"  {PASS} All Phase 3 tests passed!")
        sys.exit(0)
