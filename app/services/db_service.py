# filepath: d:\Projects\aziro-hiring-platform\app\services\db_service.py
"""
Database service layer — CRUD operations for candidates, test sessions, round results, reports.
"""
import logging
from datetime import datetime, timezone

from app.extensions import db
from app.models import Candidate, TestSession, RoundResult, Report

log = logging.getLogger(__name__)


def get_or_create_candidate(name: str, email: str) -> Candidate:
    """Get existing candidate by email or create new one."""
    candidate = Candidate.query.filter_by(email=email).first()
    if not candidate:
        candidate = Candidate(name=name, email=email)
        db.session.add(candidate)
        db.session.commit()
    return candidate


def get_or_create_test_session(candidate_id: int, role_key: str, role_label: str = "",
                                batch_id: str = "", created_by: str = "") -> TestSession:
    """Get existing test session or create new one."""
    ts = TestSession.query.filter_by(
        candidate_id=candidate_id,
        role_key=role_key,
        batch_id=batch_id,
    ).first()
    if not ts:
        ts = TestSession(
            candidate_id=candidate_id,
            role_key=role_key,
            role_label=role_label,
            batch_id=batch_id,
            created_by=created_by,
        )
        db.session.add(ts)
        db.session.commit()
    return ts


def save_round_result(test_session_id: int, round_key: str, round_label: str,
                       total_questions: int, attempted: int, correct: int,
                       percentage: float, pass_threshold: float, status: str,
                       time_taken_seconds: int = 0, session_uuid: str = "",
                       round_type: str = "mcq", test_link: str = ""):
    """Save or update a round result."""
    existing = RoundResult.query.filter_by(
        test_session_id=test_session_id,
        round_key=round_key,
    ).first()

    if existing:
        existing.round_label = round_label
        existing.total_questions = total_questions
        existing.attempted = attempted
        existing.correct = correct
        existing.percentage = percentage
        existing.pass_threshold = pass_threshold
        existing.status = status
        existing.time_taken_seconds = time_taken_seconds
        if session_uuid:
            existing.session_uuid = session_uuid
        if round_type:
            existing.round_type = round_type
        if test_link:
            existing.test_link = test_link
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
            session_uuid=session_uuid,
            round_type=round_type,
            test_link=test_link,        )
        db.session.add(rr)
        existing = rr

    db.session.commit()
    return existing


def search_candidates(query: str, role_filter: str = ""):
    """Search candidates by name, email, or role."""
    like_query = f"%{query}%"

    base = Candidate.query.join(TestSession)

    filters = []
    if query:
        filters.append(
            db.or_(
                Candidate.name.ilike(like_query),
                Candidate.email.ilike(like_query),
                TestSession.role_label.ilike(like_query),
                TestSession.role_key.ilike(like_query),
            )
        )
    if role_filter:
        like_role = f"%{role_filter}%"
        filters.append(
            db.or_(
                TestSession.role_label.ilike(like_role),
                TestSession.role_key.ilike(like_role),
            )
        )

    if filters:
        base = base.filter(*filters)

    candidates = base.distinct().limit(50).all()

    results = []
    for c in candidates:
        sessions = TestSession.query.filter_by(candidate_id=c.id).all()
        for ts in sessions:
            results.append({
                "name": c.name,
                "email": c.email,
                "role": ts.role_label or ts.role_key,
                "created_at": ts.created_at.strftime("%Y-%m-%d %H:%M") if ts.created_at else "",
                "test_session_id": ts.id,
            })
    return results


def get_candidate_report_data(email: str) -> dict:
    """Get full candidate data for report generation."""
    candidate = Candidate.query.filter_by(email=email).first()
    if not candidate:
        return None

    # Get latest test session
    ts = (
        TestSession.query
        .filter_by(candidate_id=candidate.id)
        .order_by(TestSession.created_at.desc())
        .first()
    )
    if not ts:
        return None

    rounds = {}
    round_results = (
        RoundResult.query
        .filter_by(test_session_id=ts.id)
        .order_by(RoundResult.round_key)
        .all()
    )
    for rr in round_results:
        rounds[rr.round_key] = {
            "round_label": rr.round_label,
            "correct": rr.correct,
            "total": rr.total_questions,
            "attempted": rr.attempted,
            "percentage": rr.percentage,
            "pass_threshold": rr.pass_threshold,
            "status": rr.status,
            "time_taken_seconds": rr.time_taken_seconds,
        }

    # Compute summary
    total_rounds = len(rounds)
    attempted_rounds = sum(1 for r in rounds.values() if r["status"] not in ("Pending", "Not Attempted"))
    passed_rounds = sum(1 for r in rounds.values() if r["status"] == "PASS")
    failed_rounds = sum(1 for r in rounds.values() if r["status"] == "FAIL")

    attempted_percentages = [
        r["percentage"] for r in rounds.values()
        if r["status"] not in ("Pending", "Not Attempted")
    ]
    overall_percentage = (
        round(sum(attempted_percentages) / len(attempted_percentages), 2)
        if attempted_percentages else 0
    )

    if attempted_rounds == 0:
        overall_verdict = "Pending"
    elif failed_rounds == 0 and attempted_rounds == total_rounds:
        overall_verdict = "Selected"
    elif failed_rounds > 0:
        overall_verdict = "Rejected"
    else:
        overall_verdict = "In Progress"

    return {
        "name": candidate.name,
        "email": candidate.email,
        "role": ts.role_label or ts.role_key,
        "batch_id": ts.batch_id,
        "test_session_id": ts.id,
        "rounds": rounds,
        "summary": {
            "total_rounds": total_rounds,
            "attempted_rounds": attempted_rounds,
            "passed_rounds": passed_rounds,
            "failed_rounds": failed_rounds,
            "total_correct": sum(r["correct"] for r in rounds.values()),
            "total_questions": sum(r["total"] for r in rounds.values()),
            "overall_percentage": overall_percentage,
            "overall_verdict": overall_verdict,
        },
    }


def save_report(identifier, filename: str, generated_by: str = "") -> Report:
    """Save a report record to DB.

    ``identifier`` can be:
      - an int  → treated as test_session_id
      - a str   → treated as candidate_email (legacy callers)
    """
    if isinstance(identifier, int):
        # Resolve email from test_session → candidate
        ts = TestSession.query.get(identifier)
        candidate_email = ""
        if ts:
            cand = Candidate.query.get(ts.candidate_id)
            candidate_email = cand.email if cand else ""
        report = Report(
            test_session_id=identifier,
            candidate_email=candidate_email,
            filename=filename,
            generated_by=generated_by,
        )
    else:
        report = Report(
            candidate_email=identifier,
            filename=filename,
            generated_by=generated_by,
        )
    db.session.add(report)
    db.session.commit()
    return report


def get_report_by_id(report_id: int) -> Report:
    """Get a report by its ID."""
    return Report.query.get(report_id)


def get_all_roles():
    """Return a sorted list of unique role labels across all test sessions."""
    rows = (
        db.session.query(TestSession.role_label)
        .distinct()
        .order_by(TestSession.role_label)
        .all()
    )
    return [r[0] for r in rows if r[0]]


def get_all_candidates_with_results():
    """Get all candidates with their test session results, including report info."""
    candidates = Candidate.query.all()
    results = []
    for c in candidates:
        sessions = TestSession.query.filter_by(candidate_id=c.id).all()
        for ts in sessions:
            data = get_candidate_report_data(c.email)
            if data:
                # Attach report info
                report = (
                    Report.query
                    .filter_by(test_session_id=ts.id)
                    .order_by(Report.created_at.desc())
                    .first()
                )
                data["has_report"] = report is not None
                data["report_filename"] = report.filename if report else ""
                results.append(data)
    return results
