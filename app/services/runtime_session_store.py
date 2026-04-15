import json
import logging
from datetime import datetime, timezone

from flask import current_app, has_app_context

from app.extensions import db
from app.models import RuntimeSessionState, TestLink

log = logging.getLogger(__name__)

_RUNTIME_STORE_CACHE = {
    "mcq": {},
    "coding": {},
}


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_session_id(session_id: str) -> str:
    return str(session_id or "").strip()


def _normalize_store_name(store_name: str) -> str:
    return str(store_name or "").strip().lower()


def _cache_bucket(store_name: str) -> dict:
    return _RUNTIME_STORE_CACHE.setdefault(_normalize_store_name(store_name), {})


def _should_use_db_store() -> bool:
    if not has_app_context():
        return False
    uri = str(current_app.config.get("SQLALCHEMY_DATABASE_URI", "") or "").strip().lower()
    return uri.startswith("postgresql")


def _ensure_aware_utc(value):
    if not value:
        return None
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _is_expired(value) -> bool:
    expires_at = _ensure_aware_utc(value)
    if not expires_at:
        return False
    return expires_at <= _now_utc()


def _resolve_expires_at(session_id: str):
    link = db.session.get(TestLink, session_id)
    if not link:
        return None
    return _ensure_aware_utc(getattr(link, "expires_at", None))


def get_runtime_session_data(store_name: str, session_id: str):
    sid = _normalize_session_id(session_id)
    if not sid:
        return None

    bucket = _cache_bucket(store_name)
    if not _should_use_db_store():
        return bucket.get(sid)

    try:
        record = RuntimeSessionState.query.filter_by(
            store_name=_normalize_store_name(store_name),
            session_id=sid,
        ).first()
    except Exception as exc:
        db.session.rollback()
        log.warning("Runtime session DB read failed for %s/%s: %s", store_name, sid, exc)
        return bucket.get(sid)

    if not record:
        bucket.pop(sid, None)
        return None

    if _is_expired(record.expires_at):
        bucket.pop(sid, None)
        try:
            db.session.delete(record)
            db.session.commit()
        except Exception:
            db.session.rollback()
        return None

    try:
        payload = json.loads(record.payload_json or "{}")
    except (TypeError, ValueError) as exc:
        log.warning("Runtime session payload decode failed for %s/%s: %s", store_name, sid, exc)
        bucket.pop(sid, None)
        return None

    bucket[sid] = payload
    return payload


def set_runtime_session_data(store_name: str, session_id: str, data):
    sid = _normalize_session_id(session_id)
    if not sid:
        return

    bucket = _cache_bucket(store_name)
    bucket[sid] = data

    if not _should_use_db_store():
        return

    try:
        record = RuntimeSessionState.query.filter_by(
            store_name=_normalize_store_name(store_name),
            session_id=sid,
        ).first()
        if not record:
            record = RuntimeSessionState(
                store_name=_normalize_store_name(store_name),
                session_id=sid,
                created_at=_now_utc(),
            )
            record.expires_at = _resolve_expires_at(sid)

        record.payload_json = json.dumps(data or {}, ensure_ascii=False)
        record.updated_at = _now_utc()

        db.session.add(record)
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        log.warning("Runtime session DB write failed for %s/%s: %s", store_name, sid, exc)


def clear_runtime_session_data(store_name: str, session_id: str):
    sid = _normalize_session_id(session_id)
    if not sid:
        return

    bucket = _cache_bucket(store_name)
    bucket.pop(sid, None)

    if not _should_use_db_store():
        return

    try:
        RuntimeSessionState.query.filter_by(
            store_name=_normalize_store_name(store_name),
            session_id=sid,
        ).delete()
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        log.warning("Runtime session DB delete failed for %s/%s: %s", store_name, sid, exc)
