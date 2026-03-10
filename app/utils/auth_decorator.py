import os
from functools import wraps

from flask import flash, redirect, session, url_for


def _dev_bypass_enabled() -> bool:
    auth_disabled = os.getenv("AUTH_DISABLED", "").strip().lower() == "true"
    azure_client_id = os.getenv("AZURE_CLIENT_ID", "").strip()
    azure_unconfigured = (not azure_client_id) or azure_client_id == "your-azure-client-id"
    return auth_disabled or azure_unconfigured


def _ensure_dev_user() -> None:
    if not session.get("user"):
        session["user"] = {
            "name": "Dev User",
            "email": "dev@aziro.com",
            "authenticated": True,
        }


def login_required(f):
    """Protect routes and require Microsoft-authenticated session in normal mode."""

    @wraps(f)
    def decorated_function(*args, **kwargs):
        if _dev_bypass_enabled():
            _ensure_dev_user()
            return f(*args, **kwargs)

        if not session.get("user"):
            flash("Please sign in to access this page.", "danger")
            return redirect(url_for("auth.login"))

        oauth = session.get("oauth")
        token = oauth.get("graph_access_token") if isinstance(oauth, dict) else ""
        if not token:
            session.clear()
            flash("Please sign in with Microsoft.", "danger")
            return redirect(url_for("auth.login"))

        return f(*args, **kwargs)

    return decorated_function
