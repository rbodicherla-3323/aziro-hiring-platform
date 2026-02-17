"""Quick smoke test for DB service layer. Run and delete."""
from app import create_app
from app.services import db_service

app = create_app()
with app.app_context():
    # Test create candidate
    c = db_service.get_or_create_candidate("Test User", "test@example.com")
    print(f"Candidate: {c.id} - {c.name} ({c.email})")

    # Test create session
    ts = db_service.get_or_create_test_session(
        c.id, "python_entry", "Python Entry Level (0-2 Years)", "batch_test_001"
    )
    print(f"TestSession: {ts.id} - {ts.role_label} - {ts.batch_id}")

    # Test save round result
    rr = db_service.save_round_result(
        ts.id, "L1", "Aptitude", 15, 12, 10, 66.67, 60, "PASS", 300
    )
    print(f"RoundResult: {rr.id} - {rr.round_key} - {rr.status}")

    # Test query
    candidates = db_service.get_all_candidates_with_results()
    print(f"Total candidates in DB: {len(candidates)}")
    for cand in candidates:
        name = cand["name"]
        role = cand["role"]
        rounds = list(cand["rounds"].keys())
        verdict = cand["summary"]["overall_verdict"]
        print(f"  {name} - {role} - rounds: {rounds} - verdict: {verdict}")

    # Test PDF generation
    from app.services.pdf_service import generate_candidate_pdf
    filename = generate_candidate_pdf(candidates[0])
    print(f"PDF generated: {filename}")

    # Cleanup test data
    from app.extensions import db
    from app.models import RoundResult, TestSession, Candidate
    RoundResult.query.filter_by(test_session_id=ts.id).delete()
    TestSession.query.filter_by(id=ts.id).delete()
    Candidate.query.filter_by(id=c.id).delete()
    db.session.commit()
    print("Cleaned up test data. All OK!")
