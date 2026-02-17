from functools import wraps
from flask import session, redirect, url_for, flash


def login_required(f):
    """Decorator to protect routes — redirects to login if not authenticated."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get("user"):
            flash("Please sign in to access this page.", "danger")
            return redirect(url_for("auth.login"))
        return f(*args, **kwargs)
    return decorated_function