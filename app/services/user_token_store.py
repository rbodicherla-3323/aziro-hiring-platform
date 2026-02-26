"""
In-memory token store for per-user delegated Graph access tokens.

This avoids storing large OAuth access tokens in Flask's cookie session.
"""
import time
from typing import Dict


_GRAPH_DELEGATED_TOKENS: Dict[str, Dict[str, object]] = {}


def _email_key(user_email: str) -> str:
    return str(user_email or "").strip().lower()


def set_graph_delegated_token(user_email: str, access_token: str, expires_in: int = 3600) -> None:
    key = _email_key(user_email)
    token = str(access_token or "").strip()
    if not key or not token:
        return

    try:
        ttl_seconds = int(expires_in)
    except (TypeError, ValueError):
        ttl_seconds = 3600
    if ttl_seconds < 60:
        ttl_seconds = 60

    _GRAPH_DELEGATED_TOKENS[key] = {
        "access_token": token,
        "expires_at": int(time.time()) + ttl_seconds,
    }


def get_valid_graph_delegated_token(user_email: str, skew_seconds: int = 120) -> str:
    key = _email_key(user_email)
    record = _GRAPH_DELEGATED_TOKENS.get(key) if key else None
    if not record:
        return ""

    access_token = str(record.get("access_token", "")).strip()
    expires_at = int(record.get("expires_at", 0) or 0)
    now = int(time.time())
    if not access_token or expires_at <= now + int(skew_seconds):
        return ""
    return access_token


def get_valid_graph_delegated_token_from_session(oauth_session: dict, skew_seconds: int = 120) -> str:
    payload = oauth_session if isinstance(oauth_session, dict) else {}
    access_token = str(payload.get("graph_access_token", "")).strip()
    expires_at = int(payload.get("graph_access_token_expires_at", 0) or 0)
    now = int(time.time())
    if not access_token or expires_at <= now + int(skew_seconds):
        return ""
    return access_token


def clear_graph_delegated_token(user_email: str) -> None:
    key = _email_key(user_email)
    if key:
        _GRAPH_DELEGATED_TOKENS.pop(key, None)
