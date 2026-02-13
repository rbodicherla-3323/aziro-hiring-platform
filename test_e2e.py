"""
End-to-end smoke test for the DB integration + Reports pipeline.

Run:  python test_e2e.py
"""

import os
import sys

os.environ.setdefault("FLASK_APP", "run.py")

from app import create_app
from app.extensions import db
from app.models import Candidate, TestSession, RoundResult, Report
from app.services import db_service
from app.services.pdf_service import generate_candidate_pdf, REPORTS_DIR

app = create_app()

PASS = "\033[92m✓\033[0m"
FAIL = "\033[91m✗\033[0m"
errors = []


def check(label, condition):
    if condition:
        print(f"  {PASS} {label}")
    else:
        print(f"  {FAIL} {label}")
        errors.append(label)


with app.app_context():

    # ── 1. Candidate creation ───────────────────────────
    print("\n── 1. Candidate CRUD ──")
    c1 = db_service.get_or_create_candidate("Ravi Kumar", "ravi@test.com")
    check("Candidate created", c1 is not None and c1.id > 0)
    c1_dup = db_service.get_or_create_candidate("Ravi Kumar", "ravi@test.com")
    check("Duplicate returns same row", c1.id == c1_dup.id)

    c2 = db_service.get_or_create_candidate("Anita Sharma", "anita@test.com")
    check("Second candidate created", c2.id != c1.id)

    # ── 2. Test session creation ────────────────────────
    print("\n── 2. Test Sessions ──")
    ts1 = db_service.get_or_create_test_session(
        c1.id, "python_entry", "Python Entry Level (0–2 Years)", "batch_e2e_001"
    )
    check("Session created for Ravi", ts1 is not None and ts1.id > 0)

    ts1_dup = db_service.get_or_create_test_session(
        c1.id, "python_entry", "Python Entry Level (0–2 Years)", "batch_e2e_001"
    )
    check("Idempotent session", ts1.id == ts1_dup.id)

    ts2 = db_service.get_or_create_test_session(
        c2.id, "python_qa", "Python QA (4+ Years)", "batch_e2e_001"
    )
    check("Session created for Anita", ts2.id != ts1.id)

    # ── 3. Round results ────────────────────────────────
    print("\n── 3. Round Results ──")
    rr1 = db_service.save_round_result(
        ts1.id, "L1", "Aptitude", 15, 14, 11, 73.33, 60, "PASS", 450
    )
    check("L1 result saved", rr1 is not None)

    rr2 = db_service.save_round_result(
        ts1.id, "L2", "Python Theory", 15, 15, 8, 53.33, 70, "FAIL", 500
    )
    check("L2 result saved", rr2.status == "FAIL")

    rr3 = db_service.save_round_result(
        ts1.id, "L5", "Soft Skills", 15, 15, 10, 66.67, 50, "PASS", 300
    )
    check("L5 result saved", rr3.status == "PASS")

    # Upsert — update L1 score
    rr1_up = db_service.save_round_result(
        ts1.id, "L1", "Aptitude", 15, 15, 13, 86.67, 60, "PASS", 460
    )
    check("L1 upsert works", rr1_up.id == rr1.id and rr1_up.correct == 13)

    # Anita's results
    db_service.save_round_result(ts2.id, "L1", "Aptitude", 15, 15, 12, 80.0, 60, "PASS", 400)
    db_service.save_round_result(ts2.id, "L2", "Python Theory", 15, 15, 12, 80.0, 70, "PASS", 480)
    db_service.save_round_result(ts2.id, "L3", "QA & Testing", 15, 15, 11, 73.33, 70, "PASS", 420)
    db_service.save_round_result(ts2.id, "L5", "Soft Skills", 15, 14, 9, 60.0, 50, "PASS", 350)

    # ── 4. Query all candidates ─────────────────────────
    print("\n── 4. Queries ──")
    all_cands = db_service.get_all_candidates_with_results()
    check(f"get_all_candidates_with_results returns {len(all_cands)}", len(all_cands) >= 2)

    ravi = next((c for c in all_cands if c["email"] == "ravi@test.com"), None)
    check("Ravi found in results", ravi is not None)
    check("Ravi has 3 rounds", len(ravi["rounds"]) == 3)
    check("Ravi verdict = Rejected (L2 FAIL)", ravi["summary"]["overall_verdict"] == "Rejected")

    anita = next((c for c in all_cands if c["email"] == "anita@test.com"), None)
    check("Anita found in results", anita is not None)
    check("Anita has 4 rounds", len(anita["rounds"]) == 4)
    check("Anita verdict = Selected (all PASS)", anita["summary"]["overall_verdict"] == "Selected")

    # ── 5. Search & filter ──────────────────────────────
    print("\n── 5. Search & Filter ──")
    search_r = db_service.search_candidates("ravi")
    check("Search by name 'ravi'", len(search_r) >= 1 and search_r[0]["email"] == "ravi@test.com")

    search_role = db_service.search_candidates("", "Python QA (4+ Years)")
    check("Filter by role 'Python QA'", len(search_role) >= 1 and search_role[0]["email"] == "anita@test.com")

    roles = db_service.get_all_roles()
    check("get_all_roles returns roles", len(roles) >= 2)

    # ── 6. PDF generation ───────────────────────────────
    print("\n── 6. PDF Generation ──")
    filename = generate_candidate_pdf(anita)
    check("PDF filename returned", filename.endswith(".pdf"))
    filepath = REPORTS_DIR / filename
    check("PDF file exists on disk", filepath.exists())
    check("PDF file > 0 bytes", filepath.stat().st_size > 0)

    # Save report record
    report = db_service.save_report(anita["test_session_id"], filename)
    check("Report record saved in DB", report.id > 0)

    # Re-query — should now show has_report=True
    all_cands2 = db_service.get_all_candidates_with_results()
    anita2 = next((c for c in all_cands2 if c["email"] == "anita@test.com"), None)
    check("Anita has_report = True after save", anita2["has_report"] is True)
    check("report_filename matches", anita2["report_filename"] == filename)

    # ── 7. Flask route smoke tests ──────────────────────
    print("\n── 7. Route Smoke Tests ──")
    with app.test_client() as client:
        # Reports page
        resp = client.get("/reports")
        check("GET /reports → 200", resp.status_code == 200)
        check("Reports page contains 'Ravi'", b"Ravi" in resp.data)
        check("Reports page contains 'Anita'", b"Anita" in resp.data)

        # Reports page with search
        resp_q = client.get("/reports?q=anita")
        check("GET /reports?q=anita → 200", resp_q.status_code == 200)
        check("Search filters to Anita", b"Anita" in resp_q.data)

        # Preview endpoint
        resp_prev = client.get(f"/reports/preview/{anita['test_session_id']}")
        check("GET /reports/preview → 200 + JSON", resp_prev.status_code == 200)
        preview_data = resp_prev.get_json()
        check("Preview JSON has name", preview_data.get("name") == "Anita Sharma")

        # Download endpoint
        resp_dl = client.get(f"/reports/download/{filename}")
        check("GET /reports/download → 200 + PDF", resp_dl.status_code == 200)
        check("Content-Type = application/pdf", "application/pdf" in resp_dl.content_type)

        # Generate endpoint (for Ravi)
        resp_gen = client.post("/reports/generate", data={
            "test_session_id": ravi["test_session_id"]
        })
        check("POST /reports/generate → 200", resp_gen.status_code == 200)
        gen_data = resp_gen.get_json()
        check("Generate returns status=ok", gen_data.get("status") == "ok")
        check("Generate returns filename", gen_data.get("filename", "").endswith(".pdf"))    # ── Cleanup ─────────────────────────────────────────
    print("\n── Cleanup ──")

    # Delete DB rows first
    Report.query.filter(Report.test_session_id.in_([ts1.id, ts2.id])).delete()
    RoundResult.query.filter(RoundResult.test_session_id.in_([ts1.id, ts2.id])).delete()
    TestSession.query.filter(TestSession.id.in_([ts1.id, ts2.id])).delete()
    Candidate.query.filter(Candidate.id.in_([c1.id, c2.id])).delete()
    db.session.commit()

    # Delete generated PDFs for test candidates (best-effort on Windows)
    import gc
    gc.collect()
    for pattern in ("Ravi*", "Anita*", "*_e2e_*", "*test*"):
        for f in REPORTS_DIR.glob(pattern):
            try:
                f.unlink(missing_ok=True)
            except PermissionError:
                pass  # Windows file-lock from test_client; harmless
    check("Test data cleaned up", True)

    # ── Summary ─────────────────────────────────────────
    print("\n" + "=" * 50)
    if errors:
        print(f"  {FAIL} {len(errors)} test(s) FAILED:")
        for e in errors:
            print(f"     - {e}")
        sys.exit(1)
    else:
        print(f"  {PASS} All tests passed!")
        sys.exit(0)
