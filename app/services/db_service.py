# filepath: d:\Projects\aziro-hiring-platform\app\services\db_service.py
"""
Database service layer — CRUD operations for candidates, test sessions, round results, reports.
"""
import logging
from datetime import datetime, timezone, timedelta

from app.services.candidate_scope import build_candidate_key
from app.extensions import db
from app.models import Candidate, TestSession, RoundResult, Report, ProctoringScreenshot, TestLink, LoginAudit

log = logging.getLogger(__name__)

TEST_LINK_TTL_HOURS = 168


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _dt_to_iso(value) -> str:
    if not value:
        return ""
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _parse_dt(value) -> datetime | None:
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


DUMMY_CANDIDATE_NAME_PREFIX = "test_"
DUMMY_CANDIDATE_SQL_NAME_PREFIX_PATTERN = r"test\_%"


def is_dummy_candidate_name(name: str) -> bool:
    normalized = str(name or "").strip().lower()
    if not normalized:
        return False
    return normalized.startswith(DUMMY_CANDIDATE_NAME_PREFIX)


def _exclude_dummy_test_links(query):
    return query.filter(
        ~db.func.lower(TestLink.candidate_name).like(
            DUMMY_CANDIDATE_SQL_NAME_PREFIX_PATTERN,
            escape="\\",
        )
    )


def _exclude_dummy_candidates(query):
    return query.filter(
        ~db.func.lower(Candidate.name).like(
            DUMMY_CANDIDATE_SQL_NAME_PREFIX_PATTERN,
            escape="\\",
        )
    )


def save_proctoring_screenshot(
    *,
    session_uuid: str,
    candidate_email: str,
    candidate_name: str,
    round_key: str,
    round_label: str,
    source: str,
    event_type: str,
    mime_type: str,
    image_bytes: bytes,
    image_size: int,
    captured_at=None,
    screenshot_path: str = "",
):
    if not image_bytes:
        return None

    record = ProctoringScreenshot(
        session_uuid=session_uuid or "",
        candidate_email=(candidate_email or "").strip().lower(),
        candidate_name=candidate_name or "",
        round_key=round_key or "",
        round_label=round_label or "",
        source=source or "mcq",
        event_type=event_type or "screenshot",
        mime_type=mime_type or "image/png",
        image_bytes=image_bytes,
        image_size=int(image_size or len(image_bytes)),
        screenshot_path=screenshot_path or "",
    )
    if captured_at is not None:
        record.captured_at = captured_at

    db.session.add(record)
    db.session.commit()
    return record


def get_proctoring_screenshots_by_email(email: str, limit: int = 200):
    if not email:
        return []
    q = (
        ProctoringScreenshot.query
        .filter_by(candidate_email=email.strip().lower())
        .order_by(ProctoringScreenshot.captured_at.desc())
        .limit(limit)
    )
    return q.all()


def get_proctoring_screenshots_by_session_ids(session_ids, limit: int = 200):
    normalized_session_ids = {
        str(session_id or "").strip().lower()
        for session_id in (session_ids or [])
        if str(session_id or "").strip()
    }
    if not normalized_session_ids:
        return []

    q = (
        ProctoringScreenshot.query
        .filter(db.func.lower(ProctoringScreenshot.session_uuid).in_(normalized_session_ids))
        .order_by(ProctoringScreenshot.captured_at.desc())
        .limit(limit)
    )
    return q.all()


def get_proctoring_screenshot_by_id(screenshot_id: int):
    return ProctoringScreenshot.query.get(screenshot_id)


def get_or_create_candidate(name: str, email: str) -> Candidate:
    """Get existing candidate by email or create new one."""
    candidate = Candidate.query.filter_by(email=email).first()
    if not candidate:
        candidate = Candidate(name=name, email=email)
        db.session.add(candidate)
        db.session.commit()
        return candidate

    # Update placeholder names when better data arrives.
    incoming_name = str(name or "").strip()
    existing_name = str(candidate.name or "").strip()
    if incoming_name:
        existing_lower = existing_name.lower()
        email_lower = str(candidate.email or "").strip().lower()
        if not existing_name or existing_lower in {"candidate", email_lower}:
            candidate.name = incoming_name
            db.session.commit()
    return candidate


def get_candidate_count(*, include_dummy: bool = False) -> int:
    query = Candidate.query
    if not include_dummy:
        query = _exclude_dummy_candidates(query)
    return int(query.count())


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
    ).order_by(RoundResult.created_at.desc()).first()

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


def compute_test_link_expires_at(created_at: datetime | None = None) -> datetime:
    base = created_at or _now_utc()
    return base + timedelta(hours=TEST_LINK_TTL_HOURS)


def save_test_link(
    meta: dict,
    test_type: str,
    created_by: str = "",
    created_at: datetime | None = None,
    expires_at: datetime | None = None,
) -> TestLink | None:
    session_id = str((meta or {}).get("session_id") or "").strip()
    if not session_id:
        return None

    created_at = created_at or _now_utc()
    expires_at = expires_at or compute_test_link_expires_at(created_at)

    record = TestLink.query.get(session_id)
    if not record:
        record = TestLink(session_id=session_id)

    record.test_type = str(test_type or "mcq").strip().lower() or "mcq"
    record.candidate_name = str(meta.get("candidate_name", "") or "").strip()
    record.candidate_email = str(meta.get("email", "") or "").strip().lower()
    record.role_key = str(meta.get("role_key", "") or "").strip()
    record.role_label = str(meta.get("role_label", "") or "").strip()
    record.round_key = str(meta.get("round_key", "") or "").strip()
    record.round_label = str(meta.get("round_label", "") or "").strip()
    record.batch_id = str(meta.get("batch_id", "") or "").strip()
    record.domain = meta.get("domain") or None
    record.language = str(meta.get("language", "") or "").strip()
    record.created_by = str(created_by or meta.get("created_by", "") or "").strip().lower()
    record.created_at = created_at
    record.expires_at = expires_at

    db.session.add(record)
    db.session.commit()
    return record


def get_test_link_meta(session_id: str) -> dict | None:
    session_id = str(session_id or "").strip()
    if not session_id:
        return None

    record = TestLink.query.get(session_id)
    if not record:
        return None

    return {
        "session_id": record.session_id,
        "test_type": record.test_type,
        "candidate_name": record.candidate_name or "",
        "email": record.candidate_email or "",
        "role_key": record.role_key or "",
        "role_label": record.role_label or "",
        "round_key": record.round_key or "",
        "round_label": record.round_label or "",
        "batch_id": record.batch_id or "",
        "domain": record.domain,
        "language": record.language or "",
        "created_by": record.created_by or "",
        "created_at": _dt_to_iso(record.created_at),
        "expires_at": _dt_to_iso(record.expires_at),
    }

def is_test_link_completed(session_id: str) -> bool:
    sid = str(session_id or "").strip().lower()
    if not sid:
        return False

    try:
        row = (
            RoundResult.query
            .filter(db.func.lower(RoundResult.session_uuid) == sid)
            .filter(RoundResult.status.in_(("PASS", "FAIL")))
            .first()
        )
        return row is not None
    except Exception:
        return False


def expire_test_link_now(
    session_id: str,
    when: datetime | None = None,
    *,
    meta: dict | None = None,
    test_type: str = "",
) -> bool:
    """
    Expire a test link immediately.

    Returns True when a link record was found and updated; False otherwise.
    This helper is intentionally fail-safe so candidate submit flows are never blocked.
    """
    sid = str(session_id or "").strip()
    if not sid:
        return False

    when = when or _now_utc()

    try:
        record = TestLink.query.get(sid)
        if not record and isinstance(meta, dict):
            created_at = _parse_dt(meta.get("created_at")) or when
            fallback_type = str(test_type or meta.get("test_type", "") or "mcq").strip().lower() or "mcq"
            record = save_test_link(
                meta=meta,
                test_type=fallback_type,
                created_by=str(meta.get("created_by", "") or "").strip().lower(),
                created_at=created_at,
                expires_at=when,
            )
        if not record:
            return False
        record.expires_at = when
        db.session.add(record)
        db.session.commit()
        return True
    except Exception:
        db.session.rollback()
        return False

def get_test_link_stats(
    since: datetime | None = None,
    until: datetime | None = None,
    created_by: str | None = None,
) -> dict:
    query = _exclude_dummy_test_links(TestLink.query)

    if created_by:
        query = query.filter(db.func.lower(TestLink.created_by) == created_by.strip().lower())

    if since:
        query = query.filter(TestLink.created_at >= since)

    if until:
        query = query.filter(TestLink.created_at < until)

    total_tests = query.count()
    total_candidates = (
        query.with_entities(db.func.count(db.distinct(TestLink.candidate_email))).scalar()
        or 0
    )

    completed_query = (
        query.join(
            RoundResult,
            db.func.lower(RoundResult.session_uuid) == db.func.lower(TestLink.session_id),
        )
        .filter(RoundResult.status.in_(("PASS", "FAIL")))
    )
    completed = completed_query.distinct(TestLink.session_id).count()

    pending = max(0, total_tests - completed)

    return {
        "total_candidates": int(total_candidates),
        "total_tests": int(total_tests),
        "completed": int(completed),
        "pending": int(pending),
    }


def get_active_test_session_count(
    *,
    created_by: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    as_of: datetime | None = None,
) -> int:
    """
    Count active test sessions from real DB state.
    A session is considered active when:
    - its test link is not expired, and
    - it does not yet have a PASS/FAIL round result.
    """
    as_of = as_of or _now_utc()

    query = _exclude_dummy_test_links(TestLink.query)
    if created_by:
        query = query.filter(db.func.lower(TestLink.created_by) == created_by.strip().lower())
    if since:
        query = query.filter(TestLink.created_at >= since)
    if until:
        query = query.filter(TestLink.created_at < until)

    query = query.filter(
        db.or_(TestLink.expires_at.is_(None), TestLink.expires_at > as_of)
    )

    session_rows = query.with_entities(TestLink.session_id).all()
    session_ids = {
        str(row[0]).strip().lower()
        for row in session_rows
        if row and row[0]
    }
    if not session_ids:
        return 0

    completed_rows = (
        db.session.query(db.func.lower(RoundResult.session_uuid))
        .filter(db.func.lower(RoundResult.session_uuid).in_(session_ids))
        .filter(RoundResult.status.in_(("PASS", "FAIL")))
        .distinct()
        .all()
    )
    completed_ids = {
        str(row[0]).strip().lower()
        for row in completed_rows
        if row and row[0]
    }

    return max(0, len(session_ids - completed_ids))


def _month_start_utc(value: datetime) -> datetime:
    return datetime(value.year, value.month, 1, tzinfo=timezone.utc)


def _add_months_utc(value: datetime, delta_months: int) -> datetime:
    total = value.year * 12 + (value.month - 1) + delta_months
    year = total // 12
    month = total % 12 + 1
    return datetime(year, month, 1, tzinfo=timezone.utc)


def get_test_link_monthly_series(
    *,
    points: int = 6,
    created_by: str | None = None,
) -> list[dict]:
    """
    Return monthly test activity series.
    Each item: {"key": "YYYY-MM", "label": "Mon", "tests": int, "completed": int}
    """
    points = max(2, int(points or 6))
    now = _now_utc()
    current_month = _month_start_utc(now)

    buckets = []
    index_by_key = {}
    for idx in range(points):
        start = _add_months_utc(current_month, -(points - 1 - idx))
        end = _add_months_utc(start, 1)
        key = f"{start.year:04d}-{start.month:02d}"
        buckets.append(
            {
                "key": key,
                "label": start.strftime("%b"),
                "start": start,
                "end": end,
                "tests": 0,
                "completed": 0,
            }
        )
        index_by_key[key] = idx

    query = (
        _exclude_dummy_test_links(TestLink.query)
        .with_entities(TestLink.session_id, TestLink.created_at)        .filter(TestLink.created_at >= buckets[0]["start"])
        .filter(TestLink.created_at < buckets[-1]["end"])
    )
    if created_by:
        query = query.filter(db.func.lower(TestLink.created_by) == created_by.strip().lower())

    links = query.all()
    if not links:
        return [
            {
                "key": b["key"],
                "label": b["label"],
                "tests": 0,
                "completed": 0,
            }
            for b in buckets
        ]

    link_entries = []
    session_ids = set()
    for row in links:
        session_id = str(getattr(row, "session_id", "") or "").strip().lower()
        created_at = getattr(row, "created_at", None)
        if not session_id or not created_at:
            continue
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        key = f"{created_at.year:04d}-{created_at.month:02d}"
        bucket_idx = index_by_key.get(key)
        if bucket_idx is None:
            continue
        buckets[bucket_idx]["tests"] += 1
        session_ids.add(session_id)
        link_entries.append((session_id, bucket_idx))

    completed_ids = set()
    if session_ids:
        completed_rows = (
            db.session.query(db.func.lower(RoundResult.session_uuid))
            .filter(db.func.lower(RoundResult.session_uuid).in_(session_ids))
            .filter(RoundResult.status.in_(("PASS", "FAIL")))
            .distinct()
            .all()
        )
        completed_ids = {
            str(r[0]).strip().lower()
            for r in completed_rows
            if r and r[0]
        }

    for session_id, bucket_idx in link_entries:
        if session_id in completed_ids:
            buckets[bucket_idx]["completed"] += 1

    return [
        {
            "key": b["key"],
            "label": b["label"],
            "tests": int(b["tests"]),
            "completed": int(b["completed"]),
        }
        for b in buckets
    ]


def search_candidates(
    query: str = "",
    role_filter: str = "",
    date_start: datetime | None = None,
    date_end: datetime | None = None,
):
    """Search candidates by name, email, or role, optionally constrained by test session dates."""
    like_query = f"%{query}%"

    base = _exclude_dummy_candidates(db.session.query(Candidate, TestSession).join(TestSession))

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
    if date_start:
        filters.append(TestSession.created_at >= date_start)
    if date_end:
        filters.append(TestSession.created_at < date_end)

    if filters:
        base = base.filter(*filters)

    rows = (
        base
        .order_by(TestSession.created_at.desc(), TestSession.id.desc())
        .limit(250)
        .all()
    )

    results = []
    seen = set()
    for c, ts in rows:
        dedupe_key = (c.id, ts.id)
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        results.append({
            "name": c.name,
            "email": c.email,
            "role": ts.role_label or ts.role_key,
            "role_key": ts.role_key or "",
            "batch_id": ts.batch_id or "",
            "created_at": ts.created_at.strftime("%Y-%m-%d %H:%M") if ts.created_at else "",
            "test_session_id": ts.id,
        })
    return results


def search_candidates_with_reports(
    query: str = "",
    role_filter: str = "",
    date_start: datetime | None = None,
    date_end: datetime | None = None,
):
    """Search candidates that have at least one generated report."""
    like_query = f"%{query}%"

    base = (
        db.session.query(Report, Candidate, TestSession)
        .outerjoin(
            Candidate,
            db.func.lower(Report.candidate_email) == db.func.lower(Candidate.email),
        )
        .outerjoin(
            TestSession,
            Report.test_session_id == TestSession.id,
        )
    )

    filters = []
    if query:
        filters.append(
            db.or_(
                Candidate.name.ilike(like_query),
                Candidate.email.ilike(like_query),
                Report.candidate_email.ilike(like_query),
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
    if date_start:
        filters.append(
            db.or_(
                Report.created_at >= date_start,
                TestSession.created_at >= date_start,
            )
        )
    if date_end:
        filters.append(
            db.or_(
                Report.created_at < date_end,
                TestSession.created_at < date_end,
            )
        )

    if filters:
        base = base.filter(*filters)

    rows = (
        base
        .order_by(Report.created_at.desc())
        .limit(250)
        .all()
    )

    results = []
    seen_rows = set()
    for report, cand, ts in rows:
        email = (cand.email if cand else report.candidate_email) or ""
        email = email.strip().lower()
        candidate_name = str(cand.name if cand else "").strip()
        if is_dummy_candidate_name(candidate_name):
            continue
        role_key = ""
        batch_id = ""
        if ts:
            role_key = ts.role_key or ""
            batch_id = ts.batch_id or ""
        dedupe_key = (
            email,
            int(ts.id) if ts else None,
            int(report.id) if report else None,
        )
        if not email or dedupe_key in seen_rows:
            continue
        role = ""
        created_at = ""
        test_session_id = None
        if ts:
            role = ts.role_label or ts.role_key
            created_at = ts.created_at.strftime("%Y-%m-%d %H:%M") if ts.created_at else ""
            test_session_id = ts.id
        elif report and report.created_at:
            created_at = report.created_at.strftime("%Y-%m-%d %H:%M")
        results.append({
            "name": cand.name if cand and cand.name else email,
            "email": email,
            "role": role,
            "role_key": role_key,
            "batch_id": batch_id,
            "created_at": created_at,
            "test_session_id": test_session_id,
            "report_filename": report.filename if report else "",
            "report_id": report.id if report else None,
        })
        seen_rows.add(dedupe_key)
    return results


def record_login_audit(user_email: str, user_name: str = "", auth_provider: str = "") -> LoginAudit | None:
    email = str(user_email or "").strip().lower()
    if not email:
        return None
    audit = LoginAudit(
        user_email=email,
        user_name=str(user_name or "").strip(),
        auth_provider=str(auth_provider or "").strip(),
    )
    db.session.add(audit)
    db.session.commit()
    return audit


def get_login_audits_by_range(*, since: datetime | None = None, until: datetime | None = None) -> list[LoginAudit]:
    query = LoginAudit.query
    if since:
        query = query.filter(LoginAudit.logged_in_at >= since)
    if until:
        query = query.filter(LoginAudit.logged_in_at < until)
    return query.order_by(LoginAudit.logged_in_at.desc(), LoginAudit.id.desc()).all()


def get_created_candidate_activity(*, since: datetime | None = None, until: datetime | None = None, query_text: str = "", role_filter: str = "") -> list[dict]:
    query = _exclude_dummy_candidates(
        db.session.query(TestSession, Candidate)
        .join(Candidate, TestSession.candidate_id == Candidate.id)
    )
    if since:
        query = query.filter(TestSession.created_at >= since)
    if until:
        query = query.filter(TestSession.created_at < until)
    if role_filter and role_filter.strip().lower() not in {"all", "all roles"}:
        role_like = f"%{role_filter.strip()}%"
        query = query.filter(db.or_(TestSession.role_label.ilike(role_like), TestSession.role_key.ilike(role_like)))
    if query_text:
        like = f"%{query_text.strip()}%"
        query = query.filter(db.or_(Candidate.name.ilike(like), Candidate.email.ilike(like), TestSession.created_by.ilike(like), TestSession.role_label.ilike(like), TestSession.role_key.ilike(like), TestSession.batch_id.ilike(like)))

    rows = query.order_by(TestSession.created_at.desc(), TestSession.id.desc()).all()
    activity = []
    creator_cache = {}
    for ts, cand in rows:
        report = Report.query.filter(Report.test_session_id == ts.id).order_by(Report.created_at.desc(), Report.id.desc()).first()
        candidate_email = str(cand.email or "").strip().lower()
        role_key = str(ts.role_key or "").strip()
        batch_id = str(ts.batch_id or "").strip()
        creator_email = str(ts.created_by or "").strip().lower()

        if not creator_email:
            cache_key = (candidate_email, role_key.lower(), batch_id.lower())
            creator_email = creator_cache.get(cache_key, "")
            if not creator_email:
                link = (
                    TestLink.query
                    .filter(db.func.lower(TestLink.candidate_email) == candidate_email)
                    .filter(db.func.lower(TestLink.role_key) == role_key.lower())
                    .filter(db.func.lower(TestLink.batch_id) == batch_id.lower())
                    .filter(db.func.length(db.func.trim(db.func.coalesce(TestLink.created_by, ""))) > 0)
                    .order_by(TestLink.created_at.desc())
                    .first()
                )
                creator_email = str(link.created_by or "").strip().lower() if link else ""
                creator_cache[cache_key] = creator_email

        activity.append({
            "creator_email": creator_email,
            "candidate_name": str(cand.name or "").strip(),
            "candidate_email": candidate_email,
            "role": str(ts.role_label or ts.role_key or "").strip(),
            "role_key": role_key,
            "batch_id": batch_id,
            "created_at": ts.created_at,
            "test_session_id": ts.id,
            "report_id": int(report.id) if report else None,
            "report_filename": str(report.filename or "").strip() if report else "",
        })
    return activity


def get_reports_by_ids(report_ids) -> list[Report]:
    normalized = []
    for value in (report_ids or []):
        try:
            normalized.append(int(value))
        except (TypeError, ValueError):
            continue
    if not normalized:
        return []
    return Report.query.filter(Report.id.in_(normalized)).order_by(Report.created_at.desc(), Report.id.desc()).all()


def has_report_for_email(email: str) -> bool:
    """Return True if any report exists for the given candidate email."""
    if not email:
        return False
    email_lc = email.strip().lower()

    direct = (
        Report.query
        .filter(db.func.lower(Report.candidate_email) == email_lc)
        .first()
    )
    if direct:
        return True

    linked = (
        db.session.query(Report.id)
        .join(TestSession, Report.test_session_id == TestSession.id)
        .join(Candidate, TestSession.candidate_id == Candidate.id)
        .filter(db.func.lower(Candidate.email) == email_lc)
        .first()
    )
    return linked is not None


def get_latest_report_for_email(
    email: str,
    *,
    test_session_id: int | None = None,
    role_key: str = "",
    batch_id: str = "",
) -> dict | None:
    """Return latest report info for a candidate email, optionally scoped to one test session/role/batch."""
    if not email:
        return None
    email_lc = email.strip().lower()

    report = None
    if test_session_id:
        report = (
            Report.query
            .filter(Report.test_session_id == int(test_session_id))
            .order_by(Report.created_at.desc())
            .first()
        )

    if not report:
        report = (
            db.session.query(Report)
            .join(TestSession, Report.test_session_id == TestSession.id)
            .join(Candidate, TestSession.candidate_id == Candidate.id)
            .filter(db.func.lower(Candidate.email) == email_lc)
        )
        if role_key:
            report = report.filter(db.func.lower(TestSession.role_key) == str(role_key).strip().lower())
        if batch_id:
            report = report.filter(db.func.lower(TestSession.batch_id) == str(batch_id).strip().lower())
        report = report.order_by(Report.created_at.desc()).first()

    if not report:
        report = (
            Report.query
            .filter(db.func.lower(Report.candidate_email) == email_lc)
            .order_by(Report.created_at.desc())
            .first()
        )

    if not report:
        return None

    return {
        "id": report.id,
        "filename": report.filename,
        "created_at": report.created_at,
    }


def get_latest_test_session_id_for_candidate(
    email: str,
    *,
    created_by: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    role_key: str = "",
    batch_id: str = "",
) -> int | None:
    """Return latest test_session_id for a candidate with optional scope filters."""
    email_key = str(email or "").strip().lower()
    if not email_key:
        return None

    query = (
        db.session.query(TestSession.id)
        .join(Candidate, TestSession.candidate_id == Candidate.id)
        .filter(db.func.lower(Candidate.email) == email_key)
    )
    if created_by:
        query = query.filter(db.func.lower(TestSession.created_by) == str(created_by).strip().lower())
    if since:
        query = query.filter(TestSession.created_at >= since)
    if until:
        query = query.filter(TestSession.created_at < until)
    if role_key:
        query = query.filter(db.func.lower(TestSession.role_key) == str(role_key).strip().lower())
    if batch_id:
        query = query.filter(db.func.lower(TestSession.batch_id) == str(batch_id).strip().lower())

    row = query.order_by(TestSession.created_at.desc(), TestSession.id.desc()).first()
    if not row or not row[0]:
        return None
    return int(row[0])


def get_latest_test_session_id_for_email(email: str) -> int | None:
    """Backward-compatible alias for latest session lookup by email only."""
    return get_latest_test_session_id_for_candidate(email)


def get_round_session_uuids_for_test_session(test_session_id: int, attempted_only: bool = True) -> list[str]:
    """Return unique round session_uuid values for a test_session_id."""
    if not test_session_id:
        return []

    query = RoundResult.query.filter_by(test_session_id=int(test_session_id))
    if attempted_only:
        query = query.filter(
            db.func.lower(RoundResult.status).notin_(("pending", "not attempted", ""))
        )

    rows = query.with_entities(RoundResult.session_uuid).all()
    seen = set()
    ordered = []
    for row in rows:
        session_uuid = str(row[0] if row else "").strip().lower()
        if not session_uuid or session_uuid in seen:
            continue
        seen.add(session_uuid)
        ordered.append(session_uuid)
    return ordered


def get_candidate_report_data(
    email: str,
    *,
    test_session_id: int | None = None,
    role_key: str = "",
    batch_id: str = "",
) -> dict:
    """Get full candidate data for report generation, optionally scoped to one test session/role/batch."""
    email_key = str(email or "").strip().lower()
    candidate = (
        Candidate.query
        .filter(db.func.lower(Candidate.email) == email_key)
        .first()
        if email_key
        else None
    )

    ts = None
    if test_session_id:
        ts = TestSession.query.get(int(test_session_id))
        if ts and not candidate:
            candidate = Candidate.query.get(ts.candidate_id)
    if not candidate and not ts:
        return None

    if not ts:
        query = TestSession.query.filter_by(candidate_id=candidate.id)
        if role_key:
            query = query.filter(db.func.lower(TestSession.role_key) == str(role_key).strip().lower())
        if batch_id:
            query = query.filter(db.func.lower(TestSession.batch_id) == str(batch_id).strip().lower())
        ts = (
            query
            .order_by(TestSession.created_at.desc(), TestSession.id.desc())
            .first()
        )
    if not ts:
        return None

    if not candidate:
        candidate = Candidate.query.get(ts.candidate_id)
    if not candidate:
        return None

    rounds = {}
    round_results = (
        RoundResult.query
        .filter_by(test_session_id=ts.id)
        .order_by(RoundResult.round_key, RoundResult.created_at)
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
        "candidate_key": build_candidate_key(
            email=candidate.email,
            role_key=ts.role_key,
            role_label=ts.role_label,
            batch_id=ts.batch_id,
        ),
        "name": candidate.name,
        "email": candidate.email,
        "role": ts.role_label or ts.role_key,
        "role_key": ts.role_key,
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


def ensure_candidate_session_for_report(candidate_data: dict, generated_by: str = ""):
    """Ensure candidate + test session exist for a report generated from in-memory data."""
    if not candidate_data:
        return None

    email = str(candidate_data.get("email", "")).strip().lower()
    if not email:
        return None

    name = candidate_data.get("name", "") or email
    role_key = candidate_data.get("role_key") or candidate_data.get("role") or "general"
    role_label = candidate_data.get("role") or candidate_data.get("role_key") or role_key
    batch_id = candidate_data.get("batch_id", "") or ""

    candidate = get_or_create_candidate(name, email)
    return get_or_create_test_session(
        candidate_id=candidate.id,
        role_key=role_key,
        role_label=role_label,
        batch_id=batch_id,
        created_by=generated_by,
    )


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
        candidate_email = (candidate_email or "").strip().lower()
        report = Report(
            test_session_id=identifier,
            candidate_email=candidate_email,
            filename=filename,
            generated_by=generated_by,
        )
    else:
        report = Report(
            candidate_email=(identifier or "").strip().lower(),
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
    candidates = _exclude_dummy_candidates(Candidate.query).all()
    results = []
    for c in candidates:
        sessions = TestSession.query.filter_by(candidate_id=c.id).all()
        for ts in sessions:
            data = get_candidate_report_data(c.email, test_session_id=ts.id)
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











