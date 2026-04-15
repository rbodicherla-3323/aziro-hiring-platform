from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.extensions import db
from app.models import Candidate, Report, RoundResult, TestSession, ProctoringScreenshot

REPORTS_DIR = Path(__file__).resolve().parents[2] / "runtime" / "reports"


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _safe_remove_report_file(filename: str) -> bool:
    if not filename:
        return False
    try:
        path = Path(str(filename).strip())
        if not path.is_absolute():
            path = (REPORTS_DIR / path).resolve()
        if path.exists() and path.is_file():
            path.unlink()
            return True
    except Exception:
        return False
    return False


def cleanup_candidate_test_data_older_than(days: int = 30, now: datetime | None = None) -> dict[str, int]:
    now = now or _now_utc()
    cutoff = now - timedelta(days=days)

    summary = {
        "reports_deleted": 0,
        "round_results_deleted": 0,
        "test_sessions_deleted": 0,
        "candidates_deleted": 0,
        "proctoring_screenshots_deleted": 0,
        "access_approvals_deleted": 0,
        "test_links_deleted": 0,
    }

    # Delete reports older than cutoff
    old_reports = Report.query.filter(Report.created_at <= cutoff).all()
    for report in old_reports:
        _safe_remove_report_file(getattr(report, "filename", ""))
        db.session.delete(report)
    summary["reports_deleted"] = len(old_reports)

    # Delete round_results older than cutoff
    summary["round_results_deleted"] = (
        RoundResult.query
        .filter(RoundResult.created_at <= cutoff)
        .delete(synchronize_session=False)
    )

    # Delete test_sessions older than cutoff
    summary["test_sessions_deleted"] = (
        TestSession.query
        .filter(TestSession.created_at <= cutoff)
        .delete(synchronize_session=False)
    )

    # Delete candidates older than cutoff
    summary["candidates_deleted"] = (
        Candidate.query
        .filter(Candidate.created_at <= cutoff)
        .delete(synchronize_session=False)
    )

    # Delete proctoring_screenshots older than cutoff (using captured_at)
    summary["proctoring_screenshots_deleted"] = (
        ProctoringScreenshot.query
        .filter(ProctoringScreenshot.captured_at <= cutoff)
        .delete(synchronize_session=False)
    )

    # Delete access_approvals older than cutoff (using requested_at)
    summary["access_approvals_deleted"] = (
        AccessApproval.query
        .filter(AccessApproval.requested_at <= cutoff)
        .delete(synchronize_session=False)
    )

    # Delete test_links older than cutoff
    summary["test_links_deleted"] = (
        TestLink.query
        .filter(TestLink.created_at <= cutoff)
        .delete(synchronize_session=False)
    )

    db.session.commit()
    return summary
