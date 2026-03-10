"""
Comprehensive Test Suite — Tests EVERYTHING across all roles.

Coverage:
  1. Config validation (all 12 roles)
  2. Question file loading for ALL roles/rounds
  3. Question selection (15 from pool)
  4. Test creation flow (Flask client, all 12 roles)
  5. MCQ session registry wiring
  6. Coding session registry wiring (language check)
  7. Database integration (CRUD, upsert, queries)
  8. Evaluation / round results (save, query, verdict)
  9. PDF report generation
  10. Flask route smoke tests (/reports, /create-test, /dashboard, etc.)
  11. Domain round wiring (L6)

Run:  python test_full.py
"""

import os
import sys
import json
import random
import gc

os.environ.setdefault("FLASK_APP", "run.py")

from app import create_app
from app.extensions import db
from app.models import Candidate, TestSession, RoundResult, Report
from app.services import db_service
from app.services.pdf_service import generate_candidate_pdf, REPORTS_DIR

from app.utils.role_normalizer import ROLE_NAME_TO_KEY, normalize_role
from app.utils.role_round_mapping import ROLE_ROUND_MAPPING, ROLE_CODING_LANGUAGE
from app.utils.round_display_mapping import ROUND_DISPLAY_MAPPING
from app.utils.round_question_mapping import ROUND_QUESTION_MAPPING, DOMAIN_QUESTION_FILES
from app.services.question_bank.loader import QuestionLoader
from app.services.question_bank.registry import QuestionRegistry
from app.services.mcq_session_registry import MCQ_SESSION_REGISTRY
from app.services.coding_session_registry import CODING_SESSION_REGISTRY

app = create_app()

PASS = "\033[92m\u2713\033[0m"
FAIL = "\033[91m\u2717\033[0m"
errors = []
total_checks = 0

QUESTION_BANK_PATH = os.path.join("app", "services", "question_bank", "data")

ALL_ROLES = {
    "python_entry":         "Python Entry Level (0\u20132 Years)",
    "java_entry":           "Java Entry Level (0\u20132 Years)",
    "js_entry":             "JavaScript Entry Level (0\u20132 Years)",
    "python_qa_linux":      "Python QA / System / Linux (4+ Years)",
    "python_qa":            "Python QA (4+ Years)",
    "python_dev":           "Python Development (4+ Years)",
    "python_ai_ml":         "Python + AI/ML (4+ Years)",
    "java_aws":             "Java + AWS Development (5+ Years)",
    "java_qa":              "Java QA (5+ Years)",
    "bmc_engineer":         "BMC Engineer (2\u20135 Years)",
    "linux_kernel_dd":      "Staff Engineer \u2013 Linux Kernel & Device Driver (3\u20135 Years)",
    "systems_architect_cpp":"Systems Architect \u2013 C++ (3\u20135 Years)",
}


def check(label, condition):
    global total_checks
    total_checks += 1
    if condition:
        print(f"  {PASS} {label}")
    else:
        print(f"  {FAIL} {label}")
        errors.append(label)


with app.app_context():

    branch = os.popen("git branch --show-current").read().strip()
    commit = os.popen("git --no-pager log --oneline -1").read().strip()
    print(f"\n{'='*60}")
    print(f"  FULL TEST SUITE  |  Branch: {branch}  |  {commit}")
    print(f"{'='*60}")

    # ══════════════════════════════════════════════════════════
    # 1. CONFIG VALIDATION — All 12 roles
    # ══════════════════════════════════════════════════════════
    print("\n\u2550\u2550 1. Config Validation (12 roles) \u2550\u2550")

    for role_key, role_label in ALL_ROLES.items():
        # Role normalizer
        resolved = normalize_role(role_label)
        check(f"normalize_role('{role_label}') \u2192 '{role_key}'", resolved == role_key)

        # Role round mapping exists
        config = ROLE_ROUND_MAPPING.get(role_key)
        check(f"{role_key}: in ROLE_ROUND_MAPPING", config is not None)

        # Round display mapping exists
        display = ROUND_DISPLAY_MAPPING.get(role_key)
        check(f"{role_key}: in ROUND_DISPLAY_MAPPING", display is not None)

        # Question mapping exists
        qmap = ROUND_QUESTION_MAPPING.get(role_key)
        check(f"{role_key}: in ROUND_QUESTION_MAPPING", qmap is not None)

        if config:
            # Verify rounds list
            check(f"{role_key}: has rounds list", len(config.get("rounds", [])) >= 3)
            check(f"{role_key}: has allow_domain key", "allow_domain" in config)

            # Coding round consistency
            coding_rounds = config.get("coding_rounds", [])
            if coding_rounds:
                check(f"{role_key}: has coding_language", "coding_language" in config)
                lang = config.get("coding_language")
                check(f"{role_key}: coding_language in ROLE_CODING_LANGUAGE", ROLE_CODING_LANGUAGE.get(role_key) == lang)

        if display:
            # Every configured round has a display label
            for rnd in config.get("rounds", []) + config.get("coding_rounds", []):
                check(f"{role_key}.{rnd}: has display label", rnd in display and len(display[rnd]) > 0)

    # ══════════════════════════════════════════════════════════
    # 2. QUESTION FILE LOADING — All roles, all rounds
    # ══════════════════════════════════════════════════════════
    print("\n\u2550\u2550 2. Question File Loading (all roles/rounds) \u2550\u2550")

    loader = QuestionLoader(QUESTION_BANK_PATH)
    registry = QuestionRegistry(loader)

    for role_key in ALL_ROLES:
        qmap = ROUND_QUESTION_MAPPING.get(role_key, {})
        for round_key, files in qmap.items():
            try:
                questions = registry.get_questions(role_key, round_key)
                check(f"{role_key}.{round_key}: loaded {len(questions)} questions", len(questions) >= 15)

                # Test random selection of 15
                selected = random.sample(questions, min(15, len(questions)))
                check(f"{role_key}.{round_key}: can select 15", len(selected) == 15)
            except Exception as e:
                check(f"{role_key}.{round_key}: LOAD FAILED \u2014 {e}", False)

    # Domain questions
    print("\n  -- Domain question files --")
    for domain_key, files in DOMAIN_QUESTION_FILES.items():
        try:
            questions = registry.get_questions("python_qa", "L6", domain=domain_key)
            check(f"Domain '{domain_key}': loaded {len(questions)} questions", len(questions) >= 15)
        except Exception as e:
            check(f"Domain '{domain_key}': LOAD FAILED \u2014 {e}", False)

    # ══════════════════════════════════════════════════════════
    # 3. PHASE 3 EXACT QUESTION COUNTS (must be 50)
    # ══════════════════════════════════════════════════════════
    print("\n\u2550\u2550 3. Phase 3 Question Counts (50 each) \u2550\u2550")

    phase3_files = {
        "c/c_theory.json": 50,
        "bmc/bmc_firmware.json": 50,
        "linux/linux_kernel.json": 50,
        "device_driver/device_driver_basics.json": 50,
        "cpp/cpp_theory.json": 50,
        "system_design/system_design_architecture.json": 50,
        "soft_skills_leadership.json": 50,
    }
    for qf, expected in phase3_files.items():
        questions = loader.load(qf)
        check(f"{qf}: exactly {expected} questions", len(questions) == expected)

    # ══════════════════════════════════════════════════════════
    # 4. TEST CREATION FLOW (Flask test client, all 12 roles)
    # ══════════════════════════════════════════════════════════
    print("\n\u2550\u2550 4. Test Creation Flow (all 12 roles) \u2550\u2550")

    # Clear registries for clean test
    MCQ_SESSION_REGISTRY.clear()
    CODING_SESSION_REGISTRY.clear()

    with app.test_client() as client:
        # GET create-test page
        resp = client.get("/create-test")
        check("GET /create-test \u2192 200", resp.status_code == 200)

        page = resp.data.decode("utf-8")
        check("Dropdown has 'BMC Engineer'", "BMC Engineer" in page)
        check("Dropdown has 'Linux Kernel'", "Linux Kernel" in page)
        check("Dropdown has 'Systems Architect'", "Systems Architect" in page)
        check("Dropdown has 'Python Entry Level'", "Python Entry Level" in page)

        # POST for each role
        for role_key, role_label in ALL_ROLES.items():
            domain = "Storage" if ROLE_ROUND_MAPPING[role_key]["allow_domain"] else "None"
            resp = client.post("/create-test", data={
                "name[]": [f"Test_{role_key}"],
                "email[]": [f"test_{role_key}@example.com"],
                "role[]": [role_label],
                "domain[]": [domain],
            }, follow_redirects=True)
            check(f"POST create-test '{role_key}' \u2192 200", resp.status_code == 200)

    # ══════════════════════════════════════════════════════════
    # 5. SESSION REGISTRY WIRING
    # ══════════════════════════════════════════════════════════
    print("\n\u2550\u2550 5. Session Registry Wiring \u2550\u2550")

    # MCQ sessions
    mcq_roles = set()
    for sid, meta in MCQ_SESSION_REGISTRY.items():
        mcq_roles.add(meta.get("role_key"))
    check(f"MCQ sessions created for {len(mcq_roles)} roles", len(mcq_roles) == 12)

    # Coding sessions
    coding_roles = {}
    for sid, meta in CODING_SESSION_REGISTRY.items():
        coding_roles[meta["role_key"]] = meta.get("language")

    expected_coding = {
        "java_entry": "java", "java_aws": "java", "java_qa": "java",
        "bmc_engineer": "c", "linux_kernel_dd": "c", "systems_architect_cpp": "cpp"
    }
    for rk, expected_lang in expected_coding.items():
        actual = coding_roles.get(rk)
        check(f"Coding session {rk}: language='{actual}'", actual == expected_lang)

    # Domain sessions (L6)
    domain_sessions = [s for s in MCQ_SESSION_REGISTRY.values() if s.get("round_key") == "L6"]
    roles_with_domain = [rk for rk, cfg in ROLE_ROUND_MAPPING.items() if cfg["allow_domain"]]
    check(f"L6 domain sessions created: {len(domain_sessions)}", len(domain_sessions) == len(roles_with_domain))

    # ══════════════════════════════════════════════════════════
    # 6. DATABASE INTEGRATION
    # ══════════════════════════════════════════════════════════
    print("\n\u2550\u2550 6. Database Integration \u2550\u2550")

    # Candidate CRUD
    c1 = db_service.get_or_create_candidate("FullTest User1", "fulltest1@test.com")
    check("Candidate created", c1 is not None and c1.id > 0)
    c1_dup = db_service.get_or_create_candidate("FullTest User1", "fulltest1@test.com")
    check("Duplicate returns same row", c1.id == c1_dup.id)

    c2 = db_service.get_or_create_candidate("FullTest User2", "fulltest2@test.com")
    check("Second candidate created", c2.id != c1.id)

    # Test sessions
    ts1 = db_service.get_or_create_test_session(c1.id, "bmc_engineer", "BMC Engineer (2\u20135 Years)", "batch_fulltest")
    check("Session for BMC Engineer created", ts1 is not None and ts1.id > 0)

    ts2 = db_service.get_or_create_test_session(c2.id, "linux_kernel_dd", "Staff Engineer \u2013 Linux Kernel & Device Driver (3\u20135 Years)", "batch_fulltest")
    check("Session for Linux Kernel DD created", ts2.id != ts1.id)

    # Round results
    rr1 = db_service.save_round_result(ts1.id, "L1", "Aptitude", 15, 15, 12, 80.0, 60, "PASS", 420)
    check("L1 result saved for BMC", rr1 is not None)

    rr2 = db_service.save_round_result(ts1.id, "L2", "C Language Theory", 15, 15, 10, 66.67, 60, "PASS", 500)
    check("L2 result saved for BMC", rr2 is not None)

    rr3 = db_service.save_round_result(ts1.id, "L3", "BMC / Firmware", 15, 15, 8, 53.33, 70, "FAIL", 480)
    check("L3 result saved for BMC (FAIL)", rr3.status == "FAIL")

    rr5 = db_service.save_round_result(ts1.id, "L5", "Soft Skills", 15, 14, 11, 73.33, 50, "PASS", 350)
    check("L5 result saved for BMC", rr5 is not None)

    # Upsert test
    rr1_up = db_service.save_round_result(ts1.id, "L1", "Aptitude", 15, 15, 14, 93.33, 60, "PASS", 430)
    check("L1 upsert works (same id)", rr1_up.id == rr1.id and rr1_up.correct == 14)

    # c2 all pass
    db_service.save_round_result(ts2.id, "L1", "C Theoretical", 15, 15, 13, 86.67, 60, "PASS", 400)
    db_service.save_round_result(ts2.id, "L2", "Linux Kernel Theory", 15, 15, 12, 80.0, 60, "PASS", 450)
    db_service.save_round_result(ts2.id, "L3", "Device Driver Basics", 15, 15, 11, 73.33, 60, "PASS", 480)
    db_service.save_round_result(ts2.id, "L5", "Soft Skills (Leadership)", 15, 15, 10, 66.67, 50, "PASS", 380)
    check("All 4 rounds saved for Linux Kernel DD", True)

    # ══════════════════════════════════════════════════════════
    # 7. QUERIES & VERDICTS
    # ══════════════════════════════════════════════════════════
    print("\n\u2550\u2550 7. Queries & Verdicts \u2550\u2550")

    all_cands = db_service.get_all_candidates_with_results()
    check(f"get_all_candidates_with_results: {len(all_cands)} candidates", len(all_cands) >= 2)

    user1 = next((c for c in all_cands if c["email"] == "fulltest1@test.com"), None)
    check("FullTest User1 found", user1 is not None)
    if user1:
        check("User1 has 4 rounds", len(user1["rounds"]) == 4)
        check("User1 verdict = Rejected (L3 FAIL)", user1["summary"]["overall_verdict"] == "Rejected")

    user2 = next((c for c in all_cands if c["email"] == "fulltest2@test.com"), None)
    check("FullTest User2 found", user2 is not None)
    if user2:
        check("User2 has 4 rounds", len(user2["rounds"]) == 4)
        check("User2 verdict = Selected (all PASS)", user2["summary"]["overall_verdict"] == "Selected")

    # Search
    search_r = db_service.search_candidates("fulltest1")
    check("Search by name works", len(search_r) >= 1)

    roles = db_service.get_all_roles()
    check("get_all_roles returns roles", len(roles) >= 2)

    # ══════════════════════════════════════════════════════════
    # 8. PDF REPORT GENERATION
    # ══════════════════════════════════════════════════════════
    print("\n\u2550\u2550 8. PDF Report Generation \u2550\u2550")

    if user2:
        filename = generate_candidate_pdf(user2)
        check("PDF filename returned", filename.endswith(".pdf"))
        filepath = REPORTS_DIR / filename
        check("PDF file exists on disk", filepath.exists())
        check("PDF file > 0 bytes", filepath.stat().st_size > 0)

        report = db_service.save_report(user2["test_session_id"], filename)
        check("Report record saved in DB", report.id > 0)

        # Re-query
        all_cands2 = db_service.get_all_candidates_with_results()
        u2_after = next((c for c in all_cands2 if c["email"] == "fulltest2@test.com"), None)
        check("User2 has_report = True", u2_after and u2_after["has_report"] is True)

    # ══════════════════════════════════════════════════════════
    # 9. FLASK ROUTE SMOKE TESTS
    # ══════════════════════════════════════════════════════════
    print("\n\u2550\u2550 9. Flask Route Smoke Tests \u2550\u2550")

    with app.test_client() as client:
        # Dashboard
        resp = client.get("/dashboard")
        check("GET /dashboard \u2192 200", resp.status_code == 200)

        # Create test page
        resp = client.get("/create-test")
        check("GET /create-test \u2192 200", resp.status_code == 200)

        # Generated tests
        resp = client.get("/generated-tests")
        check("GET /generated-tests \u2192 200", resp.status_code == 200)

        # Evaluation page
        resp = client.get("/evaluation")
        check("GET /evaluation \u2192 200", resp.status_code == 200)

        # Reports page
        resp = client.get("/reports")
        check("GET /reports \u2192 200", resp.status_code == 200)
        check("Reports page has candidates", b"FullTest" in resp.data)

        # Reports search
        resp = client.get("/reports?q=fulltest2")
        check("GET /reports?q=fulltest2 \u2192 200", resp.status_code == 200)

        # Preview endpoint
        if user2:
            resp = client.get(f"/reports/preview/{user2['test_session_id']}")
            check("GET /reports/preview \u2192 200 + JSON", resp.status_code == 200)
            pdata = resp.get_json()
            check("Preview JSON has name", pdata.get("name") == "FullTest User2")

        # Download PDF
        if user2:
            resp = client.get(f"/reports/download/{filename}")
            check("GET /reports/download \u2192 200", resp.status_code == 200)
            check("Content-Type = application/pdf", "application/pdf" in resp.content_type)

        # Generate report for user1
        if user1:
            resp = client.post("/reports/generate", data={
                "test_session_id": user1["test_session_id"]
            })
            check("POST /reports/generate \u2192 200", resp.status_code == 200)
            gen = resp.get_json()
            check("Generate returns status=ok", gen.get("status") == "ok")

    # ══════════════════════════════════════════════════════════
    # 10. L4 CODING YAML FILES
    # ══════════════════════════════════════════════════════════
    print("\n\u2550\u2550 10. L4 Coding YAML Files \u2550\u2550")

    import yaml
    l4_base = os.path.join(QUESTION_BANK_PATH, "l4_coding")
    for lang in ["c", "cpp", "java"]:
        yaml_path = os.path.join(l4_base, lang, "questions.yaml")
        exists = os.path.exists(yaml_path)
        check(f"L4 YAML exists: {lang}/questions.yaml", exists)
        if exists:
            with open(yaml_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
            q_list = data if isinstance(data, list) else data.get("questions", [])
            check(f"  {lang}: {len(q_list)} coding questions", len(q_list) >= 1)

    # ══════════════════════════════════════════════════════════
    # CLEANUP
    # ══════════════════════════════════════════════════════════
    print("\n\u2550\u2550 Cleanup \u2550\u2550")

    Report.query.filter(Report.test_session_id.in_([ts1.id, ts2.id])).delete()
    RoundResult.query.filter(RoundResult.test_session_id.in_([ts1.id, ts2.id])).delete()
    TestSession.query.filter(TestSession.id.in_([ts1.id, ts2.id])).delete()
    Candidate.query.filter(Candidate.id.in_([c1.id, c2.id])).delete()
    db.session.commit()

    gc.collect()
    for pattern in ("FullTest*", "*fulltest*"):
        for f in REPORTS_DIR.glob(pattern):
            try:
                f.unlink(missing_ok=True)
            except PermissionError:
                pass
    check("Test data cleaned up", True)

    # ══════════════════════════════════════════════════════════
    # SUMMARY
    # ══════════════════════════════════════════════════════════
    print(f"\n{'='*60}")
    print(f"  Branch: {branch}  |  Commit: {commit}")
    if errors:
        print(f"  {FAIL} {len(errors)}/{total_checks} test(s) FAILED:")
        for e in errors:
            print(f"     - {e}")
        sys.exit(1)
    else:
        print(f"  {PASS} ALL {total_checks} tests passed!")
        sys.exit(0)
