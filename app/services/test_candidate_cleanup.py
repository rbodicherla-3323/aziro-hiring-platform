from datetime import datetime, timezone, timedelta
from pathlib import Path

from app.extensions import db
from app.models import Candidate, TestSession, RoundResult, Report, ProctoringScreenshot, TestLink
from app.services.coding_session_registry import CODING_SESSION_REGISTRY
from app.services.evaluation_store import EVALUATION_STORE
from app.services.generated_tests_store import GENERATED_TESTS
from app.services.mcq_session_registry import MCQ_SESSION_REGISTRY
from app.services.pdf_service import REPORTS_DIR

TEST_CANDIDATE_NAME_PREFIX = "test_"
TEST_CANDIDATE_SQL_NAME_PREFIX_PATTERN = r"test\_%"
TEST_CANDIDATE_TTL_MINUTES = 60


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _parse_dt(value):
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            return None
    else:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def is_test_candidate_name(name: str) -> bool:
    normalized = str(name or "").strip().lower()
    if not normalized:
        return False
    return normalized.startswith(TEST_CANDIDATE_NAME_PREFIX)


def _is_expired_test_candidate(name: str, created_at, cutoff: datetime) -> bool:
    if not is_test_candidate_name(name):
        return False
    created_dt = _parse_dt(created_at)
    if created_dt is None:
        return False
    return created_dt <= cutoff


def _safe_unlink(path_value) -> bool:
    path_text = str(path_value or "").strip()
    if not path_text:
        return False
    try:
        path = Path(path_text)
        if not path.is_absolute():
            path = (REPORTS_DIR / path_text).resolve()
        if path.exists() and path.is_file():
            path.unlink()
            return True
    except Exception:
        return False
    return False


def _purge_generated_tests(cutoff: datetime) -> dict:
    removed = 0
    session_ids = set()

    for idx in range(len(GENERATED_TESTS) - 1, -1, -1):
        entry = GENERATED_TESTS[idx]
        if not _is_expired_test_candidate(entry.get("name", ""), entry.get("created_at"), cutoff):
            continue
        for test in (entry.get("tests", {}) or {}).values():
            session_id = str((test or {}).get("session_id", "") or "").strip().lower()
            if session_id:
                session_ids.add(session_id)
        _safe_unlink(entry.get("resume_path", ""))
        _safe_unlink(entry.get("jd_path", ""))
        GENERATED_TESTS.pop(idx)
        removed += 1

    return {"removed": removed, "session_ids": session_ids}


def _purge_registry(registry, cutoff: datetime) -> dict:
    removed = 0
    session_ids = set()
    for session_id, meta in list(registry.items()):
        if not _is_expired_test_candidate((meta or {}).get("candidate_name", ""), (meta or {}).get("created_at"), cutoff):
            continue
        sid = str(session_id or "").strip().lower()
        if sid:
            session_ids.add(sid)
        registry.pop(session_id, None)
        removed += 1
    return {"removed": removed, "session_ids": session_ids}


def _purge_evaluation_store(cutoff: datetime, session_ids: set[str]) -> int:
    removed = 0
    for session_id, result in list(EVALUATION_STORE.items()):
        sid = str(session_id or "").strip().lower()
        if sid and sid in session_ids:
            EVALUATION_STORE.pop(session_id, None)
            removed += 1
            continue
        if not _is_expired_test_candidate((result or {}).get("candidate_name", ""), (result or {}).get("created_at"), cutoff):
            continue
        EVALUATION_STORE.pop(session_id, None)
        removed += 1
    return removed


def purge_expired_test_candidates(now: datetime | None = None) -> dict:
    now = now or _now_utc()
    cutoff = now - timedelta(minutes=TEST_CANDIDATE_TTL_MINUTES)
    summary = {
        "generated_tests_removed": 0,
        "mcq_sessions_removed": 0,
        "coding_sessions_removed": 0,
        "evaluation_entries_removed": 0,
        "reports_removed": 0,
        "screenshots_removed": 0,
        "round_results_removed": 0,
        "test_links_removed": 0,
        "test_sessions_removed": 0,
        "candidates_removed": 0,
    }

    generated = _purge_generated_tests(cutoff)
    mcq_registry = _purge_registry(MCQ_SESSION_REGISTRY, cutoff)
    coding_registry = _purge_registry(CODING_SESSION_REGISTRY, cutoff)

    expired_session_uuids = set()
    expired_session_uuids.update(generated["session_ids"])
    expired_session_uuids.update(mcq_registry["session_ids"])
    expired_session_uuids.update(coding_registry["session_ids"])

    summary["generated_tests_removed"] = generated["removed"]
    summary["mcq_sessions_removed"] = mcq_registry["removed"]
    summary["coding_sessions_removed"] = coding_registry["removed"]

    expired_test_links = (
        TestLink.query
        .filter(
            db.func.lower(TestLink.candidate_name).like(
                TEST_CANDIDATE_SQL_NAME_PREFIX_PATTERN,
                escape="\\",
            )
        )
        .filter(TestLink.created_at <= cutoff)
        .all()
    )
    expired_session_uuids.update(
        str(link.session_id or "").strip().lower()
        for link in expired_test_links
        if getattr(link, "session_id", None)
    )

    expired_test_sessions = (
        db.session.query(TestSession)
        .join(Candidate, TestSession.candidate_id == Candidate.id)
        .filter(
            db.func.lower(Candidate.name).like(
                TEST_CANDIDATE_SQL_NAME_PREFIX_PATTERN,
                escape="\\",
            )
        )
        .filter(TestSession.created_at <= cutoff)
        .all()
    )
    expired_test_session_ids = {int(ts.id) for ts in expired_test_sessions if getattr(ts, "id", None)}
    expired_candidate_ids = {int(ts.candidate_id) for ts in expired_test_sessions if getattr(ts, "candidate_id", None)}

    expired_reports = (
        db.session.query(Report)
        .outerjoin(TestSession, Report.test_session_id == TestSession.id)
        .outerjoin(Candidate, TestSession.candidate_id == Candidate.id)
        .filter(
            db.or_(
                Report.test_session_id.in_(expired_test_session_ids) if expired_test_session_ids else db.false(),
                db.and_(
                    db.func.lower(Candidate.name).like(
                        TEST_CANDIDATE_SQL_NAME_PREFIX_PATTERN,
                        escape="\\",
                    ),
                    Report.created_at <= cutoff,
                ),
            )
        )
        .all()
    )
    for report in expired_reports:
        _safe_unlink(REPORTS_DIR / str(report.filename or "").strip())
        db.session.delete(report)
    summary["reports_removed"] = len(expired_reports)

    expired_screenshots = (
        ProctoringScreenshot.query
        .filter(
            db.or_(
                db.func.lower(ProctoringScreenshot.candidate_name).like(
                    TEST_CANDIDATE_SQL_NAME_PREFIX_PATTERN,
                    escape="\\",
                ),
                db.func.lower(ProctoringScreenshot.session_uuid).in_(expired_session_uuids) if expired_session_uuids else db.false(),
            )
        )
        .filter(ProctoringScreenshot.created_at <= cutoff)
        .all()
    )
    for shot in expired_screenshots:
        _safe_unlink(shot.screenshot_path)
        db.session.delete(shot)
    summary["screenshots_removed"] = len(expired_screenshots)

    expired_round_results = (
        RoundResult.query
        .filter(
            db.or_(
                RoundResult.test_session_id.in_(expired_test_session_ids) if expired_test_session_ids else db.false(),
                db.func.lower(RoundResult.session_uuid).in_(expired_session_uuids) if expired_session_uuids else db.false(),
            )
        )
        .all()
    )
    for result in expired_round_results:
        db.session.delete(result)
    summary["round_results_removed"] = len(expired_round_results)

    for link in expired_test_links:
        db.session.delete(link)
    summary["test_links_removed"] = len(expired_test_links)

    for ts in expired_test_sessions:
        db.session.delete(ts)
    summary["test_sessions_removed"] = len(expired_test_sessions)

    summary["evaluation_entries_removed"] = _purge_evaluation_store(cutoff, expired_session_uuids)

    expired_candidates = (
        Candidate.query
        .filter(
            db.func.lower(Candidate.name).like(
                TEST_CANDIDATE_SQL_NAME_PREFIX_PATTERN,
                escape="\\",
            )
        )
        .filter(Candidate.created_at <= cutoff)
        .all()
    )
    for candidate in expired_candidates:
        remaining_sessions = TestSession.query.filter_by(candidate_id=candidate.id).first()
        if remaining_sessions is not None:
            continue
        db.session.delete(candidate)
        summary["candidates_removed"] += 1

    db.session.commit()
    return summary
