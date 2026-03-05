"""
Auth routes - Microsoft MSAL OAuth for @aziro.com users.
"""

import os
import time

import msal
import requests
from flask import flash, redirect, render_template, request, session, url_for

from . import auth_bp
from app.services.user_token_store import (
    clear_graph_delegated_token,
    set_graph_delegated_token,
)

# Azure AD Configuration
AZURE_CLIENT_ID = os.getenv("AZURE_CLIENT_ID", "")
AZURE_CLIENT_SECRET = os.getenv("AZURE_CLIENT_SECRET", "")
AZURE_TENANT_ID = os.getenv("AZURE_TENANT_ID", "common")
AZURE_REDIRECT_URI = os.getenv("AZURE_REDIRECT_URI", "").strip()
AUTHORITY = f"https://login.microsoftonline.com/{AZURE_TENANT_ID}"
SCOPES = ["User.Read", "Mail.Send"]


def _build_msal_app(cache=None):
    return msal.ConfidentialClientApplication(
        AZURE_CLIENT_ID,
        authority=AUTHORITY,
        client_credential=AZURE_CLIENT_SECRET,
        token_cache=cache,
    )


def _get_redirect_uri() -> str:
    """Return OAuth redirect URI."""
    if AZURE_REDIRECT_URI:
        return AZURE_REDIRECT_URI
    return url_for("auth.auth_callback", _external=True)


@auth_bp.route("/")
def index():
    """Root URL - always start at login page."""
    return redirect(url_for("auth.login"))


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    """Login page."""
    auth_disabled = os.getenv("AUTH_DISABLED", "").strip().lower() == "true"

    # Normal mode: force explicit Microsoft sign-in at app entry.
    if request.method == "GET":
        if not auth_disabled and (session.get("user") or session.get("oauth")):
            user = session.get("user", {})
            clear_graph_delegated_token(user.get("email", ""))
            session.clear()
        return render_template("login.html", error=None)

    # POST local login is allowed only in explicit dev-bypass mode.
    error = None
    if auth_disabled:
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()

        if not username.endswith("@aziro.com"):
            error = "Only @aziro.com email addresses are allowed."
        elif password == "aziro123":
            session["user"] = {
                "name": username.split("@")[0].title(),
                "email": username,
                "authenticated": True,
            }
            return redirect(url_for("dashboard.dashboard"))
        else:
            error = "Invalid credentials."
    else:
        error = "Use 'Continue with Microsoft' to sign in."

    return render_template("login.html", error=error)


@auth_bp.route("/login/microsoft")
def microsoft_login():
    """Initiate Microsoft OAuth2 flow."""
    if not AZURE_CLIENT_ID or AZURE_CLIENT_ID == "your-azure-client-id":
        flash("Microsoft login is not configured.", "warning")
        return redirect(url_for("auth.login"))

    try:
        app = _build_msal_app()
    except Exception as exc:
        flash(f"Microsoft login setup error: {exc}", "danger")
        return redirect(url_for("auth.login"))
    redirect_uri = _get_redirect_uri()

    try:
        auth_url = app.get_authorization_request_url(
            SCOPES,
            redirect_uri=redirect_uri,
        )
    except Exception as exc:
        flash(f"Microsoft login request failed: {exc}", "danger")
        return redirect(url_for("auth.login"))
    return redirect(auth_url)


@auth_bp.route("/auth/callback")
@auth_bp.route("/login/azure/callback")
def auth_callback():
    """Handle Microsoft OAuth2 callback (legacy and Azure-style paths)."""
    code = request.args.get("code")
    if not code:
        flash("Authentication failed - no authorization code received.", "danger")
        return redirect(url_for("auth.login"))

    try:
        app = _build_msal_app()
    except Exception as exc:
        flash(f"Authentication setup error: {exc}", "danger")
        return redirect(url_for("auth.login"))
    redirect_uri = _get_redirect_uri()

    try:
        result = app.acquire_token_by_authorization_code(
            code,
            scopes=SCOPES,
            redirect_uri=redirect_uri,
        )
    except Exception as exc:
        flash(f"Authentication callback failed: {exc}", "danger")
        return redirect(url_for("auth.login"))

    if "error" in result:
        flash(f"Authentication failed: {result.get('error_description', result['error'])}", "danger")
        return redirect(url_for("auth.login"))

    user_info = result.get("id_token_claims") or {}
    if not isinstance(user_info, dict):
        user_info = {}

    email = str(
        user_info.get("preferred_username")
        or user_info.get("upn")
        or user_info.get("email")
        or ""
    ).strip().lower()
    name = str(
        user_info.get("name")
        or user_info.get("given_name")
        or ""
    ).strip()

    access_token = result.get("access_token", "")
    if (not email or not name) and access_token:
        try:
            me_resp = requests.get(
                "https://graph.microsoft.com/v1.0/me?$select=displayName,mail,userPrincipalName",
                headers={"Authorization": f"Bearer {access_token}"},
                timeout=10,
            )
            if me_resp.status_code == 200:
                me = me_resp.json() if me_resp.content else {}
                if not email:
                    email = str(
                        me.get("mail")
                        or me.get("userPrincipalName")
                        or ""
                    ).strip().lower()
                if not name:
                    name = str(me.get("displayName") or "").strip()
        except Exception:
            pass

    if not name:
        name = email.split("@")[0].title() if email else "User"

    if not email.endswith("@aziro.com"):
        flash("Access denied. Only @aziro.com accounts are allowed.", "danger")
        return redirect(url_for("auth.login"))

    session["user"] = {
        "name": name,
        "email": email,
        "authenticated": True,
    }

    expires_in = result.get("expires_in", 3600)
    set_graph_delegated_token(
        user_email=email,
        access_token=access_token,
        expires_in=expires_in,
    )
    try:
        ttl = int(expires_in)
    except (TypeError, ValueError):
        ttl = 3600
    if ttl < 60:
        ttl = 60
    session["oauth"] = {
        "graph_access_token": access_token,
        "graph_access_token_expires_at": int(time.time()) + ttl,
    }

    return redirect(url_for("dashboard.dashboard"))


@auth_bp.route("/logout")
def logout():
    """Clear session and redirect to login."""
    user = session.get("user", {})
    clear_graph_delegated_token(user.get("email", ""))
    session.clear()
    return redirect(url_for("auth.login"))
