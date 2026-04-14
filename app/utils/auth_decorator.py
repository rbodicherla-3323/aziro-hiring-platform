import os
from functools import wraps

from flask import flash, redirect, session, url_for

from app.services.access_approvals_service import decide_access
from app.services.user_token_store import (
    clear_graph_delegated_token,
    get_valid_graph_delegated_token,
    get_valid_graph_delegated_token_from_session,
)


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

        user = session.get("user", {}) if isinstance(session.get("user"), dict) else {}
        user_email = str(user.get("email", "") or "").strip().lower()
        try:
            decision = decide_access(email=user_email)
        except Exception:
            clear_graph_delegated_token(user_email)
            session.clear()
            flash(
                "We could not verify your access right now. Please sign in again shortly or contact an access administrator.",
                "danger",
            )
            return redirect(url_for("auth.login"))
        if not decision.allowed:
            clear_graph_delegated_token(user_email)
            session.clear()
            flash("Your access has been revoked. Please sign in again.", "danger")
            return redirect(url_for("auth.login"))

        oauth = session.get("oauth") if isinstance(session.get("oauth"), dict) else {}
        token = get_valid_graph_delegated_token(user_email)
        if not token:
            token = get_valid_graph_delegated_token_from_session(oauth)
        if not token:
            session.clear()
            flash("Please sign in with Microsoft.", "danger")
            return redirect(url_for("auth.login"))

        return f(*args, **kwargs)

    return decorated_function
