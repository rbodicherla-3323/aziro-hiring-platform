# filepath: d:\Projects\aziro-hiring-platform\app\blueprints\auth\routes.py
"""
Auth routes — Microsoft MSAL OAuth for @aziro.com users.
Also provides local dev fallback routes.
"""
import os
import msal
from flask import render_template, redirect, url_for, session, request, flash

from . import auth_bp

# Azure AD Configuration
AZURE_CLIENT_ID = os.getenv("AZURE_CLIENT_ID", "")
AZURE_CLIENT_SECRET = os.getenv("AZURE_CLIENT_SECRET", "")
AZURE_TENANT_ID = os.getenv("AZURE_TENANT_ID", "common")
AUTHORITY = f"https://login.microsoftonline.com/{AZURE_TENANT_ID}"
SCOPES = ["User.Read"]


def _build_msal_app(cache=None):
    return msal.ConfidentialClientApplication(
        AZURE_CLIENT_ID,
        authority=AUTHORITY,
        client_credential=AZURE_CLIENT_SECRET,
        token_cache=cache,
    )


@auth_bp.route("/")
def index():
    """Root URL — redirect to dashboard if logged in, else login."""
    if session.get("user"):
        return redirect(url_for("dashboard.dashboard"))
    return redirect(url_for("auth.login"))


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    """Login page."""
    if session.get("user"):
        return redirect(url_for("dashboard.dashboard"))

    error = None
    if request.method == "POST":
        # Simple email/password login for dev mode
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()

        if not username.endswith("@aziro.com"):
            error = "Only @aziro.com email addresses are allowed."
        elif password == "aziro123":  # Dev mode password
            session["user"] = {
                "name": username.split("@")[0].title(),
                "email": username,
                "authenticated": True,
            }
            return redirect(url_for("dashboard.dashboard"))
        else:
            error = "Invalid credentials."

    return render_template("login.html", error=error)


@auth_bp.route("/login/microsoft")
def microsoft_login():
    """Initiate Microsoft OAuth2 flow."""
    if not AZURE_CLIENT_ID or AZURE_CLIENT_ID == "your-azure-client-id":
        flash("Microsoft login is not configured. Use email/password login.", "warning")
        return redirect(url_for("auth.login"))

    app = _build_msal_app()
    redirect_uri = url_for("auth.auth_callback", _external=True)

    auth_url = app.get_authorization_request_url(
        SCOPES,
        redirect_uri=redirect_uri,
    )
    return redirect(auth_url)


@auth_bp.route("/auth/callback")
def auth_callback():
    """Handle Microsoft OAuth2 callback."""
    code = request.args.get("code")
    if not code:
        flash("Authentication failed — no authorization code received.", "danger")
        return redirect(url_for("auth.login"))

    app = _build_msal_app()
    redirect_uri = url_for("auth.auth_callback", _external=True)

    result = app.acquire_token_by_authorization_code(
        code,
        scopes=SCOPES,
        redirect_uri=redirect_uri,
    )

    if "error" in result:
        flash(f"Authentication failed: {result.get('error_description', result['error'])}", "danger")
        return redirect(url_for("auth.login"))

    # Get user info from ID token claims
    user_info = result.get("id_token_claims", {})
    email = user_info.get("preferred_username", "").lower()
    name = user_info.get("name", email.split("@")[0].title())

    # Restrict to @aziro.com emails
    if not email.endswith("@aziro.com"):
        flash("Access denied. Only @aziro.com accounts are allowed.", "danger")
        return redirect(url_for("auth.login"))

    session["user"] = {
        "name": name,
        "email": email,
        "authenticated": True,
    }

    return redirect(url_for("dashboard.dashboard"))


@auth_bp.route("/logout")
def logout():
    """Clear session and redirect to login."""
    session.clear()
    return redirect(url_for("auth.login"))
