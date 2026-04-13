# filepath: d:\Projects\aziro-hiring-platform\app\blueprints\auth\routes.py
"""
Auth routes — Microsoft MSAL OAuth for @aziro.com users.
Also provides local dev fallback routes.
"""
import os
import time
import logging
import msal
import requests
from flask import render_template, redirect, url_for, session, request, flash

from . import auth_bp
from app.services.user_token_store import (
    set_graph_delegated_token,
    clear_graph_delegated_token,
)
from app.services.access_approvals_service import (
    decide_access,
    maybe_notify_admin_of_request,
    upsert_access_request,
)
from app.access_config import (
    get_access_admin_emails,
    get_allowed_login_domain_hint,
    get_default_full_access_emails,
    is_allowed_login_email,
)
from app.services.db_service import record_login_audit

# Azure AD Configuration
AZURE_CLIENT_ID = os.getenv("AZURE_CLIENT_ID", "")
AZURE_CLIENT_SECRET = os.getenv("AZURE_CLIENT_SECRET", "")
AZURE_TENANT_ID = os.getenv("AZURE_TENANT_ID", "common")
AZURE_REDIRECT_URI = os.getenv("AZURE_REDIRECT_URI", "").strip()
AUTHORITY = f"https://login.microsoftonline.com/{AZURE_TENANT_ID}"
# Delegated send support requires Mail.Send consent for the logged-in user.
# Keep only resource scopes for MSAL auth request; reserved OIDC scopes are
# added by the library as needed.
SCOPES = ["User.Read", "Mail.Send"]
DEFAULT_MAX_SESSION_GRAPH_TOKEN_LEN = 1200

log = logging.getLogger(__name__)


def _parse_csv_emails(env_value: str) -> list[str]:
    raw = str(env_value or "")
    parts = [p.strip().lower() for p in raw.split(",")]
    return [p for p in parts if p]


def _normalize_email(value: str) -> str:
    return str(value or "").strip().lower()


def _ordered_email_candidates(*values) -> list[str]:
    seen: set[str] = set()
    candidates: list[str] = []
    for value in values:
        normalized = _normalize_email(value)
        if not normalized or "@" not in normalized or normalized in seen:
            continue
        seen.add(normalized)
        candidates.append(normalized)
    return candidates


def _graph_profile_email_candidates(profile: dict) -> list[str]:
    if not isinstance(profile, dict):
        return []
    other_mails = profile.get("otherMails") or []
    if isinstance(other_mails, str):
        other_mails = [other_mails]
    elif not isinstance(other_mails, (list, tuple, set)):
        other_mails = []
    return _ordered_email_candidates(
        profile.get("mail"),
        *other_mails,
        profile.get("userPrincipalName"),
    )


def _fetch_graph_profile(access_token: str) -> dict:
    if not access_token:
        return {}
    try:
        me_resp = requests.get(
            "https://graph.microsoft.com/v1.0/me?$select=displayName,mail,userPrincipalName,otherMails",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=10,
        )
        if me_resp.status_code == 200:
            payload = me_resp.json() if me_resp.content else {}
            return payload if isinstance(payload, dict) else {}
    except Exception:
        log.exception("Failed to fetch Graph /me profile during auth callback")
    return {}


def _resolve_identity_email_and_name(user_info: dict, access_token: str) -> tuple[str, str]:
    if not isinstance(user_info, dict):
        user_info = {}

    claim_candidates = _ordered_email_candidates(
        user_info.get("email"),
        user_info.get("preferred_username"),
        user_info.get("upn"),
    )
    name = str(
        user_info.get("name")
        or user_info.get("given_name")
        or ""
    ).strip()

    if access_token and (not claim_candidates or not any(is_allowed_login_email(e) for e in claim_candidates) or not name):
        graph_profile = _fetch_graph_profile(access_token)
        graph_candidates = _graph_profile_email_candidates(graph_profile)
        merged_candidates = _ordered_email_candidates(
            *graph_candidates,
            *claim_candidates,
        )
        if merged_candidates:
            claim_candidates = merged_candidates
        if not name:
            name = str(graph_profile.get("displayName") or "").strip()

    email = next((candidate for candidate in claim_candidates if is_allowed_login_email(candidate)), "")
    if not email and claim_candidates:
        email = claim_candidates[0]
    if not name:
        name = email.split("@")[0].title() if email else "User"
    return email, name


def _allowed_email_error() -> str:
    message = f"Only allowed work email domains can sign in: {get_allowed_login_domain_hint()}."
    if not str(os.getenv("DATABASE_URL", "") or "").strip():
        message += " For local dev, update ALLOWED_LOGIN_DOMAINS in .env if needed."
    return message

def _build_msal_app(cache=None):
    return msal.ConfidentialClientApplication(
        AZURE_CLIENT_ID,
        authority=AUTHORITY,
        client_credential=AZURE_CLIENT_SECRET,
        token_cache=cache,
    )


def _get_redirect_uri() -> str:
    """
    Return OAuth redirect URI.
    Prefer explicit AZURE_REDIRECT_URI for VM/proxy deployments to avoid
    localhost callback mismatches.
    """
    if AZURE_REDIRECT_URI:
        return AZURE_REDIRECT_URI
    return url_for("auth.auth_callback", _external=True)


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

        if not is_allowed_login_email(username):
            error = _allowed_email_error()
        elif password == "aziro123":  # Dev mode password
            session["user"] = {
                "name": username.split("@")[0].title(),
                "email": username,
                "authenticated": True,
            }
            try:
                record_login_audit(username, username.split("@")[0].title(), auth_provider="password")
            except Exception:
                log.exception("Failed to record login audit for %s", username)
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
    """Handle Microsoft OAuth2 callback (supports legacy and Azure-style paths)."""
    code = request.args.get("code")
    if not code:
        flash("Authentication failed — no authorization code received.", "danger")
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

    access_token = result.get("access_token", "")
    email, name = _resolve_identity_email_and_name(
        result.get("id_token_claims") or {},
        access_token,
    )

    # Restrict to configured work email domains.
    if not is_allowed_login_email(email):
        flash(f"Access denied. {_allowed_email_error()}", "danger")
        return redirect(url_for("auth.login"))

    default_full_access = get_default_full_access_emails()
    access_admin_emails = get_access_admin_emails()
    try:
        decision = decide_access(
            email=email,
            default_full_access_emails=default_full_access,
            access_admin_emails=access_admin_emails,
        )
    except Exception:
        log.exception("Access decision lookup failed during auth callback for %s", email)
        flash("Authentication failed due to a temporary access check issue. Please try again.", "danger")
        return redirect(url_for("auth.login"))
    log.info("Access decision: email=%s allowed=%s", email, decision.allowed)
    if not decision.allowed:
        # Record the request for audit/UI visibility.
        if email.endswith("@aziro.com"):
            try:
                upsert_access_request(email=email)
            except Exception:
                log.exception("Failed to record access request for %s", email)

            try:
                management_url = url_for("access.access_management_page", _external=True)
                sent = maybe_notify_admin_of_request(
                    requester_name=name,
                    requester_email=email,
                    management_url=management_url,
                    delegated_access_token=access_token,
                    delegated_sender_email=email,
                )
                if not sent:
                    log.warning(
                        "Access request notification not sent (cooldown or email failure) for %s",
                        email,
                    )
            except Exception:
                log.exception("Failed to notify approver for access request %s", email)

        flash(decision.reason or "Access denied.", "danger")
        return redirect(url_for("auth.login"))
    try:
        session["user"] = {
            "name": name,
            "email": email,
            "authenticated": True,
        }
    except Exception:
        log.exception("Failed to write user session during auth callback for %s", email)
        flash("Authentication failed due to a temporary session issue. Please try again.", "danger")
        return redirect(url_for("auth.login"))
    try:
        record_login_audit(email, name, auth_provider="microsoft")
    except Exception:
        log.exception("Failed to record login audit for %s", email)

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
    # Keep session cookie small. Some users can receive very large delegated
    # access tokens (for example, due to heavy directory claims), which can
    # cause callback failures behind proxies when stored in cookie-backed sessions.
    max_token_len_raw = os.getenv(
        "MAX_SESSION_GRAPH_TOKEN_LEN",
        str(DEFAULT_MAX_SESSION_GRAPH_TOKEN_LEN),
    ).strip()
    try:
        max_session_graph_token_len = max(0, int(max_token_len_raw))
    except ValueError:
        max_session_graph_token_len = DEFAULT_MAX_SESSION_GRAPH_TOKEN_LEN

    oauth_payload = {
        "graph_access_token_expires_at": int(time.time()) + ttl,
    }
    if access_token and len(access_token) <= max_session_graph_token_len:
        oauth_payload["graph_access_token"] = access_token
    else:
        oauth_payload["graph_access_token_omitted"] = True
        if access_token:
            log.warning(
                "Skipped storing delegated Graph token in session (len=%s, max=%s) for %s",
                len(access_token),
                max_session_graph_token_len,
                email,
            )
    try:
        session["oauth"] = oauth_payload
    except Exception:
        log.exception("Failed to write oauth session during auth callback for %s", email)
        flash("Authentication failed due to a temporary session issue. Please try again.", "danger")
        return redirect(url_for("auth.login"))

    return redirect(url_for("dashboard.dashboard"))


@auth_bp.route("/logout")
def logout():
    """Clear session and redirect to login."""
    user = session.get("user", {})
    clear_graph_delegated_token(user.get("email", ""))
    session.clear()
    return redirect(url_for("auth.login"))









