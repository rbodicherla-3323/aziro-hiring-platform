"""
Database service layer — thin wrappers around SQLAlchemy models.

All functions assume they are called inside a Flask app context.
In-memory stores remain the primary source during a running session;
these helpers persist data to the DB so it survives server restarts.
"""

from datetime import datetime, timezone
from app.extensions import db
from app.models import Candidate, TestSession, RoundResult, Report


# ---------------------------------------------------------------
# CANDIDATES
# ---------------------------------------------------------------

def get_or_create_candidate(name: str, email: str) -> Candidate:
    """Return existing candidate by email, or create a new one."""
    candidate = Candidate.query.filter_by(email=email).first()
    if candidate:
        # Update name in case it changed
        if candidate.name != name:
            candidate.name = name
            db.session.commit()
        return candidate

    candidate = Candidate(name=name, email=email)
    db.session.add(candidate)
    db.session.commit()
    return candidate


# ---------------------------------------------------------------
# TEST SESSIONS
# ---------------------------------------------------------------

def create_test_session(
    candidate_id: int,
    role_key: str,
    role_label: str,
    batch_id: str,
) -> TestSession:
    """Create a new test session row for a candidate."""
    ts = TestSession(
        candidate_id=candidate_id,
        role_key=role_key,
        role_label=role_label,
        batch_id=batch_id,
    )
    db.session.add(ts)
    db.session.commit()
    return ts


def get_test_session_by_batch_email(batch_id: str, email: str):
    """Look up a test session by batch + candidate email."""
    return (
        TestSession.query
        .join(Candidate)
        .filter(TestSession.batch_id == batch_id, Candidate.email == email)
        .first()
    )


def get_or_create_test_session(
    candidate_id: int,
    role_key: str,
    role_label: str,
    batch_id: str,
) -> TestSession:
    """Idempotent — returns existing session for same candidate+batch or creates one."""
    existing = (
        TestSession.query
        .filter_by(candidate_id=candidate_id, batch_id=batch_id)
        .first()
    )
    if existing:
        return existing
    return create_test_session(candidate_id, role_key, role_label, batch_id)


# ---------------------------------------------------------------
# ROUND RESULTS
# ---------------------------------------------------------------

def save_round_result(
    test_session_id: int,
    round_key: str,
    round_label: str,
    total_questions: int,
    attempted: int,
    correct: int,
    percentage: float,
    pass_threshold: int,
    status: str,
    time_taken_seconds: int = 0,
) -> RoundResult:
    """
    Upsert a round result.  If a result for the same session+round
    already exists it is updated (handles re-submissions).
    """
    rr = (
        RoundResult.query
        .filter_by(test_session_id=test_session_id, round_key=round_key)
        .first()
    )

    if rr:
        rr.round_label = round_label
        rr.total_questions = total_questions
        rr.attempted = attempted
        rr.correct = correct
        rr.percentage = percentage
        rr.pass_threshold = pass_threshold
        rr.status = status
        rr.time_taken_seconds = time_taken_seconds
        rr.submitted_at = datetime.now(timezone.utc)
    else:
        rr = RoundResult(
            test_session_id=test_session_id,
            round_key=round_key,
            round_label=round_label,
            total_questions=total_questions,
            attempted=attempted,
            correct=correct,
            percentage=percentage,
            pass_threshold=pass_threshold,
            status=status,
            time_taken_seconds=time_taken_seconds,
        )
        db.session.add(rr)

    db.session.commit()
    return rr


# ---------------------------------------------------------------
# QUERIES — used by Reports page
# ---------------------------------------------------------------

def get_all_candidates_with_results():
    """
    Return a list of dicts ready for the reports template.
    Each dict:
    {
        "id": <candidate_id>,
        "name": ...,
        "email": ...,
        "role": ...,
        "batch_id": ...,
        "test_session_id": ...,
        "rounds": { "L1": {...}, ... },
        "summary": { ... },
        "has_report": True/False,
        "report_filename": "..."
    }
    """
    sessions = (
        TestSession.query
        .join(Candidate)
        .order_by(TestSession.created_at.desc())
        .all()
    )

    results = []
    for ts in sessions:
        candidate = ts.candidate
        rounds_data = {}

        for rr in ts.round_results.all():
            rounds_data[rr.round_key] = {
                "round_label": rr.round_label,
                "correct": rr.correct,
                "total": rr.total_questions,
                "attempted": rr.attempted,
                "percentage": rr.percentage,
                "pass_threshold": rr.pass_threshold,
                "status": rr.status,
                "time_taken_seconds": rr.time_taken_seconds,
            }

        # Sort rounds
        ordered_rounds = ["L1", "L2", "L3", "L4", "L5", "L6"]
        sorted_rounds = {
            rk: rounds_data[rk]
            for rk in ordered_rounds
            if rk in rounds_data
        }

        # Summary
        total_rounds = len(sorted_rounds)
        attempted_rounds = sum(
            1 for r in sorted_rounds.values()
            if r["status"] not in ("Not Attempted",)
        )
        passed_rounds = sum(
            1 for r in sorted_rounds.values()
            if r["status"] == "PASS"
        )
        failed_rounds = sum(
            1 for r in sorted_rounds.values()
            if r["status"] == "FAIL"
        )
        attempted_pcts = [
            r["percentage"] for r in sorted_rounds.values()
            if r["status"] not in ("Not Attempted",)
        ]
        overall_pct = (
            round(sum(attempted_pcts) / len(attempted_pcts), 2)
            if attempted_pcts else 0
        )

        if attempted_rounds == 0:
            verdict = "Pending"
        elif failed_rounds == 0 and attempted_rounds == total_rounds:
            verdict = "Selected"
        elif failed_rounds > 0:
            verdict = "Rejected"
        else:
            verdict = "In Progress"

        # Check for existing report
        report = (
            Report.query
            .filter_by(test_session_id=ts.id)
            .order_by(Report.generated_at.desc())
            .first()
        )

        results.append({
            "id": candidate.id,
            "name": candidate.name,
            "email": candidate.email,
            "role": ts.role_label,
            "role_key": ts.role_key,
            "batch_id": ts.batch_id,
            "test_session_id": ts.id,
            "created_at": ts.created_at,
            "rounds": sorted_rounds,
            "summary": {
                "total_rounds": total_rounds,
                "attempted_rounds": attempted_rounds,
                "passed_rounds": passed_rounds,
                "failed_rounds": failed_rounds,
                "overall_percentage": overall_pct,
                "overall_verdict": verdict,
            },
            "has_report": report is not None,
            "report_filename": report.pdf_filename if report else None,
        })

    return results


def search_candidates(query_str: str = "", role_filter: str = ""):
    """Filter candidates by name/email search and role."""
    all_candidates = get_all_candidates_with_results()

    if query_str:
        q = query_str.lower()
        all_candidates = [
            c for c in all_candidates
            if q in c["name"].lower() or q in c["email"].lower()
        ]

    if role_filter and role_filter != "All Roles":
        all_candidates = [
            c for c in all_candidates
            if c["role"] == role_filter
        ]

    return all_candidates


def get_all_roles():
    """Return distinct role labels from test sessions."""
    rows = (
        db.session.query(TestSession.role_label)
        .distinct()
        .order_by(TestSession.role_label)
        .all()
    )
    return [r[0] for r in rows]


# ---------------------------------------------------------------
# REPORTS
# ---------------------------------------------------------------

def save_report(test_session_id: int, pdf_filename: str) -> Report:
    """Record that a PDF was generated."""
    report = Report(
        test_session_id=test_session_id,
        pdf_filename=pdf_filename,
    )
    db.session.add(report)
    db.session.commit()
    return report


def get_report_by_session(test_session_id: int):
    """Return latest report for a session."""
    return (
        Report.query
        .filter_by(test_session_id=test_session_id)
        .order_by(Report.generated_at.desc())
        .first()
    )
