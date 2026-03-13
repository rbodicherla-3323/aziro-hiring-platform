from datetime import datetime, timezone

from app.services import db_service


def _parse_dt(value):
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            return None
    return None


def _is_expired(meta, now=None):
    expires_at = meta.get("expires_at") if isinstance(meta, dict) else None
    if not expires_at:
        return False
    dt = _parse_dt(expires_at)
    if not dt:
        return False
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    now = now or datetime.now(timezone.utc)
    return dt <= now


class PersistentSessionRegistry:
    def __init__(self, test_type: str):
        self._cache = {}
        self._test_type = str(test_type or "").strip().lower()

    def get(self, session_id, default=None):
        sid = str(session_id or "").strip()
        if not sid:
            return default

        meta = self._cache.get(sid)
        if meta:
            if _is_expired(meta):
                self._cache.pop(sid, None)
                return default
            return meta

        try:
            record = db_service.get_test_link_meta(sid)
        except Exception:
            return default

        if not record:
            return default

        record_type = str(record.get("test_type") or "").strip().lower()
        if record_type and self._test_type and record_type != self._test_type:
            return default

        if _is_expired(record):
            return default

        self._cache[sid] = record
        return record

    def __getitem__(self, session_id):
        meta = self.get(session_id)
        if meta is None:
            raise KeyError(session_id)
        return meta

    def __setitem__(self, session_id, value):
        sid = str(session_id or "").strip()
        if not sid:
            return
        self._cache[sid] = value

    def pop(self, session_id, default=None):
        return self._cache.pop(session_id, default)

    def items(self):
        return self._cache.items()

    def values(self):
        return self._cache.values()

    def keys(self):
        return self._cache.keys()

    def __iter__(self):
        return iter(self._cache)

    def __len__(self):
        return len(self._cache)
