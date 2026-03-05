import os
from functools import wraps

from flask import flash, redirect, session, url_for


def login_required(f):
    """Protect routes and require Microsoft-authenticated session in normal mode."""

    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get("user"):
            flash("Please sign in to access this page.", "danger")
            return redirect(url_for("auth.login"))

        auth_disabled = os.getenv("AUTH_DISABLED", "").strip().lower() == "true"
        if not auth_disabled:
            oauth = session.get("oauth")
            token = oauth.get("graph_access_token") if isinstance(oauth, dict) else ""
            if not token:
                session.clear()
                flash("Please sign in with Microsoft.", "danger")
                return redirect(url_for("auth.login"))

        return f(*args, **kwargs)

    return decorated_function
