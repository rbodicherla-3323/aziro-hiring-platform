"""
Email service for sending generated test links to candidates.

Supports:
1) SMTP (Office365)
2) Microsoft Graph API (recommended for O365 enterprise policies)
3) Resend API (simple setup for local/dev and production)
"""
import os
import smtplib
from email.message import EmailMessage
from typing import Tuple
from urllib.parse import quote

import msal
import requests
from app.access_config import get_default_full_access_emails
from app.utils.email_validator import validate_email
from app.utils.round_order import ordered_present_round_keys


DEFAULT_FROM_EMAIL = "aziro-ai-hiring@aziro.com"
DEFAULT_SMTP_HOST = "smtp.office365.com"
DEFAULT_SMTP_PORT = 587
GRAPH_SCOPE = ["https://graph.microsoft.com/.default"]
RESEND_SEND_EMAIL_URL = "https://api.resend.com/emails"


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _normalize_email(value: str) -> str:
    return str(value or "").strip().lower()


def _get_default_test_link_share_emails(candidate_email: str = "") -> list[str]:
    candidate_key = _normalize_email(candidate_email)
    configured = sorted(
        _normalize_email(email)
        for email in (get_default_full_access_emails() or [])
        if _normalize_email(email)
    )
    seen = set()
    recipients = []
    for email in configured:
        if email == candidate_key or email in seen:
            continue
        seen.add(email)
        recipients.append(email)
    return recipients


def _graph_recipients(emails: list[str]) -> list[dict]:
    return [
        {"emailAddress": {"address": email}}
        for email in (emails or [])
        if _normalize_email(email)
    ]


def _build_email_body(candidate_name: str, role_label: str, tests: dict) -> str:
    lines = [
        f"Hi {candidate_name},",
        "",
        "Greetings from Aziro Technologies Pvt Ltd.",
        "",
        f"Your test links for the role \"{role_label}\" are ready.",
        "Please use a stable internet connection while attempting the tests.",
        "",
        "Test Links:",
        "",
    ]

    for idx, round_key in enumerate(ordered_present_round_keys(tests), start=1):
        test_info = tests.get(round_key, {})
        label = test_info.get("label", round_key)
        url = test_info.get("url", "")
        if url:
            lines.append(f"{idx}. {label}: {url}")

    lines.extend([
        "",
        "Regards,",
        "Aziro Technologies Pvt Ltd",
    ])
    return "\n".join(lines)


def _build_email_subject(role_label: str) -> str:
    return f"Aziro Hiring Platform - Test Links ({role_label})"


def _send_via_smtp(
    candidate_email: str,
    role_label: str,
    body: str,
    cc_emails: list[str] | None = None,
) -> Tuple[bool, str]:
    smtp_enabled = _env_bool("SMTP_ENABLED", default=True)
    if not smtp_enabled:
        return False, "SMTP email sending is disabled (SMTP_ENABLED=false)."

    smtp_host = os.getenv("SMTP_HOST", DEFAULT_SMTP_HOST).strip()
    smtp_port_raw = os.getenv("SMTP_PORT", str(DEFAULT_SMTP_PORT)).strip()
    try:
        smtp_port = int(smtp_port_raw)
    except ValueError:
        return False, f"Invalid SMTP_PORT: {smtp_port_raw}"
    smtp_use_tls = _env_bool("SMTP_USE_TLS", default=True)
    smtp_username = os.getenv("SMTP_USERNAME", DEFAULT_FROM_EMAIL).strip()
    smtp_password = os.getenv("SMTP_PASSWORD", "").strip()
    smtp_from_email = os.getenv("SMTP_FROM_EMAIL", smtp_username or DEFAULT_FROM_EMAIL).strip()

    if not smtp_username or not smtp_password:
        return False, "SMTP credentials are missing. Set SMTP_USERNAME and SMTP_PASSWORD."

    message = EmailMessage()
    message["Subject"] = _build_email_subject(role_label)
    message["From"] = smtp_from_email
    message["To"] = candidate_email
    cc_list = [email for email in (cc_emails or []) if _normalize_email(email)]
    if cc_list:
        message["Cc"] = ", ".join(cc_list)
    message.set_content(body)

    try:
        with smtplib.SMTP(smtp_host, smtp_port, timeout=15) as smtp:
            smtp.ehlo()
            if smtp_use_tls:
                smtp.starttls()
                smtp.ehlo()
            smtp.login(smtp_username, smtp_password)
            smtp.send_message(message)
        return True, ""
    except Exception as exc:
        return False, str(exc)


def _send_via_graph(
    candidate_email: str,
    role_label: str,
    body: str,
    cc_emails: list[str] | None = None,
) -> Tuple[bool, str]:
    tenant_id = os.getenv("AZURE_TENANT_ID", "").strip()
    client_id = os.getenv("AZURE_CLIENT_ID", "").strip()
    client_secret = os.getenv("AZURE_CLIENT_SECRET", "").strip()
    sender_email = (
        os.getenv("SENDER_EMAIL", "").strip()
        or os.getenv("SMTP_FROM_EMAIL", "").strip()
        or os.getenv("SMTP_USERNAME", "").strip()
        or DEFAULT_FROM_EMAIL
    )

    if not tenant_id or not client_id or not client_secret:
        return (
            False,
            "Graph credentials are missing. Set AZURE_TENANT_ID, AZURE_CLIENT_ID, and AZURE_CLIENT_SECRET.",
        )
    if not sender_email:
        return False, "SENDER_EMAIL is missing for Graph send."

    authority = f"https://login.microsoftonline.com/{tenant_id}"
    app = msal.ConfidentialClientApplication(
        client_id,
        authority=authority,
        client_credential=client_secret,
    )
    token_result = app.acquire_token_for_client(scopes=GRAPH_SCOPE)
    access_token = token_result.get("access_token")
    if not access_token:
        err = token_result.get("error_description") or token_result.get("error") or "Unknown token error"
        return False, f"Graph token acquisition failed: {err}"

    payload = {
        "message": {
            "subject": _build_email_subject(role_label),
            "body": {
                "contentType": "Text",
                "content": body,
            },
            "toRecipients": _graph_recipients([candidate_email]),
            "ccRecipients": _graph_recipients(cc_emails or []),
        },
        "saveToSentItems": "true",
    }

    sender_encoded = quote(sender_email)
    url = f"https://graph.microsoft.com/v1.0/users/{sender_encoded}/sendMail"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=20)
    except Exception as exc:
        return False, f"Graph request failed: {exc}"

    if response.status_code in (200, 202):
        return True, ""

    try:
        data = response.json()
    except Exception:
        data = {}
    message = (
        data.get("error", {}).get("message")
        or response.text
        or f"HTTP {response.status_code}"
    )
    return False, f"Graph send failed ({response.status_code}): {message}"


def _send_via_graph_delegated(
    candidate_email: str,
    role_label: str,
    body: str,
    delegated_access_token: str = "",
    delegated_sender_email: str = "",
    cc_emails: list[str] | None = None,
) -> Tuple[bool, str]:
    access_token = str(delegated_access_token or "").strip()
    if not access_token:
        return (
            False,
            "Delegated Graph token is missing or expired. Please sign in with Microsoft again.",
        )

    payload = {
        "message": {
            "subject": _build_email_subject(role_label),
            "body": {
                "contentType": "Text",
                "content": body,
            },
            "toRecipients": _graph_recipients([candidate_email]),
            "ccRecipients": _graph_recipients(cc_emails or []),
        },
        "saveToSentItems": "true",
    }
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }

    try:
        response = requests.post(
            "https://graph.microsoft.com/v1.0/me/sendMail",
            headers=headers,
            json=payload,
            timeout=20,
        )
    except Exception as exc:
        return False, f"Delegated Graph request failed: {exc}"

    if response.status_code in (200, 202):
        return True, ""

    try:
        data = response.json()
    except Exception:
        data = {}

    sender_hint = f" for signed-in user {delegated_sender_email}" if delegated_sender_email else ""
    message = (
        data.get("error", {}).get("message")
        or response.text
        or f"HTTP {response.status_code}"
    )
    return (
        False,
        f"Delegated Graph send failed ({response.status_code}){sender_hint}: {message}",
    )


def _send_via_resend(
    candidate_email: str,
    role_label: str,
    body: str,
    cc_emails: list[str] | None = None,
) -> Tuple[bool, str]:
    api_key = os.getenv("RESEND_API_KEY", "").strip()
    from_email = (
        os.getenv("RESEND_FROM_EMAIL", "").strip()
        or os.getenv("SENDER_EMAIL", "").strip()
        or os.getenv("SMTP_FROM_EMAIL", "").strip()
        or DEFAULT_FROM_EMAIL
    )

    if not api_key:
        return False, "Resend API key is missing. Set RESEND_API_KEY."
    if not from_email:
        return False, "Resend sender is missing. Set RESEND_FROM_EMAIL."

    payload = {
        "from": from_email,
        "to": [candidate_email],
        "cc": [email for email in (cc_emails or []) if _normalize_email(email)],
        "subject": _build_email_subject(role_label),
        "text": body,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    try:
        response = requests.post(
            RESEND_SEND_EMAIL_URL,
            headers=headers,
            json=payload,
            timeout=20,
        )
    except Exception as exc:
        return False, f"Resend request failed: {exc}"

    if 200 <= response.status_code < 300:
        return True, ""

    try:
        data = response.json()
    except Exception:
        data = {}

    # Resend error formats include top-level message or nested error.message
    message = (
        data.get("message")
        or data.get("error", {}).get("message")
        or response.text
        or f"HTTP {response.status_code}"
    )
    return False, f"Resend send failed ({response.status_code}): {message}"


def send_candidate_test_links_email(
    candidate_name: str,
    candidate_email: str,
    role_label: str,
    tests: dict,
    delegated_access_token: str = "",
    delegated_sender_email: str = "",
    force_delegated: bool = False,
) -> Tuple[bool, str]:
    """
    Send generated test links to one candidate.

    Returns:
        (True, "") on success
        (False, reason) on failure
    """
    email_provider = os.getenv("EMAIL_PROVIDER", "smtp").strip().lower()
    tests = tests or {}
    valid_providers = {"smtp", "graph", "graph_delegated", "resend", "auto"}
    if email_provider not in valid_providers:
        return (
            False,
            f"Invalid EMAIL_PROVIDER: {email_provider}. Use one of: smtp, graph, graph_delegated, resend, auto.",
        )

    email_ok, email_error = validate_email(candidate_email)
    if not email_ok:
        return False, email_error

    has_any_link = any((tests.get(k, {}) or {}).get("url") for k in tests.keys())
    if not has_any_link:
        return False, "No generated test links found for candidate."

    body = _build_email_body(candidate_name, role_label, tests)
    cc_emails = _get_default_test_link_share_emails(candidate_email)

    # Prefer logged-in user's mailbox whenever a delegated token is available.
    if force_delegated:
        if not delegated_access_token:
            return False, "Delegated Graph token is missing or expired. Please sign in with Microsoft again."
        delegated_ok, delegated_err = _send_via_graph_delegated(
            candidate_email=candidate_email,
            role_label=role_label,
            body=body,
            delegated_access_token=delegated_access_token,
            delegated_sender_email=delegated_sender_email,
            cc_emails=cc_emails,
        )
        if delegated_ok:
            return True, ""
        return False, delegated_err
    if delegated_access_token:
        delegated_ok, delegated_err = _send_via_graph_delegated(
            candidate_email=candidate_email,
            role_label=role_label,
            body=body,
            delegated_access_token=delegated_access_token,
            delegated_sender_email=delegated_sender_email,
            cc_emails=cc_emails,
        )
        if delegated_ok:
            return True, ""
        if email_provider == "graph_delegated":
            return False, delegated_err

    if email_provider == "graph":
        return _send_via_graph(
            candidate_email=candidate_email,
            role_label=role_label,
            body=body,
            cc_emails=cc_emails,
        )

    if email_provider == "graph_delegated":
        return False, "Delegated Graph token is missing or expired. Please sign in with Microsoft again."

    if email_provider == "smtp":
        return _send_via_smtp(
            candidate_email=candidate_email,
            role_label=role_label,
            body=body,
            cc_emails=cc_emails,
        )

    if email_provider == "resend":
        return _send_via_resend(
            candidate_email=candidate_email,
            role_label=role_label,
            body=body,
            cc_emails=cc_emails,
        )

    # auto mode: try delegated Graph, then Resend, then app Graph, then SMTP.
    delegated_ok, delegated_err = _send_via_graph_delegated(
        candidate_email=candidate_email,
        role_label=role_label,
        body=body,
        delegated_access_token=delegated_access_token,
        delegated_sender_email=delegated_sender_email,
        cc_emails=cc_emails,
    )
    if delegated_ok:
        return True, ""

    # auto mode fallback stack.
    resend_ok, resend_err = _send_via_resend(
        candidate_email=candidate_email,
        role_label=role_label,
        body=body,
        cc_emails=cc_emails,
    )
    if resend_ok:
        return True, ""

    graph_ok, graph_err = _send_via_graph(
        candidate_email=candidate_email,
        role_label=role_label,
        body=body,
        cc_emails=cc_emails,
    )
    if graph_ok:
        return True, ""

    smtp_ok, smtp_err = _send_via_smtp(
        candidate_email=candidate_email,
        role_label=role_label,
        body=body,
        cc_emails=cc_emails,
    )
    if smtp_ok:
        return True, ""

    return (
        False,
        (
            f"Delegated Graph failed: {delegated_err} | "
            f"Resend failed: {resend_err} | "
            f"Graph failed: {graph_err} | "
            f"SMTP failed: {smtp_err}"
        ),
    )

# ---- Generic plain-text email sender (used for access requests) ----

def _send_plain_via_smtp(
    to_email: str,
    subject: str,
    body: str,
) -> Tuple[bool, str]:
    smtp_enabled = _env_bool("SMTP_ENABLED", default=True)
    if not smtp_enabled:
        return False, "SMTP email sending is disabled (SMTP_ENABLED=false)."

    smtp_host = os.getenv("SMTP_HOST", DEFAULT_SMTP_HOST).strip()
    smtp_port_raw = os.getenv("SMTP_PORT", str(DEFAULT_SMTP_PORT)).strip()
    try:
        smtp_port = int(smtp_port_raw)
    except ValueError:
        return False, f"Invalid SMTP_PORT: {smtp_port_raw}"
    smtp_use_tls = _env_bool("SMTP_USE_TLS", default=True)
    smtp_username = os.getenv("SMTP_USERNAME", DEFAULT_FROM_EMAIL).strip()
    smtp_password = os.getenv("SMTP_PASSWORD", "").strip()
    smtp_from_email = os.getenv("SMTP_FROM_EMAIL", smtp_username or DEFAULT_FROM_EMAIL).strip()

    if not smtp_username or not smtp_password:
        return False, "SMTP credentials are missing. Set SMTP_USERNAME and SMTP_PASSWORD."

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = smtp_from_email
    message["To"] = to_email
    message.set_content(body)

    try:
        with smtplib.SMTP(smtp_host, smtp_port, timeout=15) as smtp:
            smtp.ehlo()
            if smtp_use_tls:
                smtp.starttls()
                smtp.ehlo()
            smtp.login(smtp_username, smtp_password)
            smtp.send_message(message)
        return True, ""
    except Exception as exc:
        return False, str(exc)


def _send_plain_via_graph(
    to_email: str,
    subject: str,
    body: str,
) -> Tuple[bool, str]:
    tenant_id = os.getenv("AZURE_TENANT_ID", "").strip()
    client_id = os.getenv("AZURE_CLIENT_ID", "").strip()
    client_secret = os.getenv("AZURE_CLIENT_SECRET", "").strip()
    sender_email = (
        os.getenv("SENDER_EMAIL", "").strip()
        or os.getenv("SMTP_FROM_EMAIL", "").strip()
        or os.getenv("SMTP_USERNAME", "").strip()
        or DEFAULT_FROM_EMAIL
    )

    if not tenant_id or not client_id or not client_secret:
        return (
            False,
            "Graph credentials are missing. Set AZURE_TENANT_ID, AZURE_CLIENT_ID, and AZURE_CLIENT_SECRET.",
        )
    if not sender_email:
        return False, "SENDER_EMAIL is missing for Graph send."

    authority = f"https://login.microsoftonline.com/{tenant_id}"
    app = msal.ConfidentialClientApplication(
        client_id,
        authority=authority,
        client_credential=client_secret,
    )
    token_result = app.acquire_token_for_client(scopes=GRAPH_SCOPE)
    access_token = token_result.get("access_token")
    if not access_token:
        err = token_result.get("error_description") or token_result.get("error") or "Unknown token error"
        return False, f"Graph token acquisition failed: {err}"

    payload = {
        "message": {
            "subject": subject,
            "body": {"contentType": "Text", "content": body},
            "toRecipients": [{"emailAddress": {"address": to_email}}],
        },
        "saveToSentItems": "true",
    }

    sender_encoded = quote(sender_email)
    url = f"https://graph.microsoft.com/v1.0/users/{sender_encoded}/sendMail"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=20)
    except Exception as exc:
        return False, f"Graph request failed: {exc}"

    if response.status_code in (200, 202):
        return True, ""

    try:
        data = response.json()
    except Exception:
        data = {}
    message = data.get("error", {}).get("message") or response.text or f"HTTP {response.status_code}"
    return False, f"Graph send failed ({response.status_code}): {message}"


def _send_plain_via_graph_delegated(
    to_email: str,
    subject: str,
    body: str,
    delegated_access_token: str = "",
    delegated_sender_email: str = "",
) -> Tuple[bool, str]:
    access_token = str(delegated_access_token or "").strip()
    if not access_token:
        return (
            False,
            "Delegated Graph token is missing or expired. Please sign in with Microsoft again.",
        )

    payload = {
        "message": {
            "subject": subject,
            "body": {"contentType": "Text", "content": body},
            "toRecipients": [{"emailAddress": {"address": to_email}}],
        },
        "saveToSentItems": "true",
    }
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }

    try:
        response = requests.post(
            "https://graph.microsoft.com/v1.0/me/sendMail",
            headers=headers,
            json=payload,
            timeout=20,
        )
    except Exception as exc:
        return False, f"Delegated Graph request failed: {exc}"

    if response.status_code in (200, 202):
        return True, ""

    try:
        data = response.json()
    except Exception:
        data = {}

    sender_hint = f" for signed-in user {delegated_sender_email}" if delegated_sender_email else ""
    message = data.get("error", {}).get("message") or response.text or f"HTTP {response.status_code}"
    return False, f"Delegated Graph send failed ({response.status_code}){sender_hint}: {message}"


def _send_plain_via_resend(
    to_email: str,
    subject: str,
    body: str,
) -> Tuple[bool, str]:
    api_key = os.getenv("RESEND_API_KEY", "").strip()
    from_email = (
        os.getenv("RESEND_FROM_EMAIL", "").strip()
        or os.getenv("SENDER_EMAIL", "").strip()
        or os.getenv("SMTP_FROM_EMAIL", "").strip()
        or DEFAULT_FROM_EMAIL
    )

    if not api_key:
        return False, "Resend API key is missing. Set RESEND_API_KEY."
    if not from_email:
        return False, "Resend sender is missing. Set RESEND_FROM_EMAIL."

    payload = {
        "from": from_email,
        "to": [to_email],
        "subject": subject,
        "text": body,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    try:
        response = requests.post(
            RESEND_SEND_EMAIL_URL,
            headers=headers,
            json=payload,
            timeout=20,
        )
    except Exception as exc:
        return False, f"Resend request failed: {exc}"

    if 200 <= response.status_code < 300:
        return True, ""

    try:
        data = response.json()
    except Exception:
        data = {}

    message = data.get("message") or data.get("error", {}).get("message") or response.text or f"HTTP {response.status_code}"
    return False, f"Resend send failed ({response.status_code}): {message}"


def send_plain_email(
    to_email: str,
    subject: str,
    body: str,
    delegated_access_token: str = "",
    delegated_sender_email: str = "",
) -> Tuple[bool, str]:
    """Send a plain-text email (used for access request notifications)."""
    try:
        email_provider = os.getenv("EMAIL_PROVIDER", "smtp").strip().lower()
        valid_providers = {"smtp", "graph", "graph_delegated", "resend", "auto"}
        if email_provider not in valid_providers:
            return (
                False,
                f"Invalid EMAIL_PROVIDER: {email_provider}. Use one of: smtp, graph, graph_delegated, resend, auto.",
            )

        to_email = str(to_email or "").strip()
        subject = str(subject or "").strip()
        body = str(body or "")
        if not to_email or not subject:
            return False, "Recipient and subject are required."

        if delegated_access_token:
            delegated_ok, delegated_err = _send_plain_via_graph_delegated(
                to_email=to_email,
                subject=subject,
                body=body,
                delegated_access_token=delegated_access_token,
                delegated_sender_email=delegated_sender_email,
            )
            if delegated_ok:
                return True, ""
            if email_provider == "graph_delegated":
                return False, delegated_err

        if email_provider == "graph":
            return _send_plain_via_graph(to_email=to_email, subject=subject, body=body)

        if email_provider == "graph_delegated":
            return False, "Delegated Graph token is missing or expired. Please sign in with Microsoft again."

        if email_provider == "smtp":
            return _send_plain_via_smtp(to_email=to_email, subject=subject, body=body)

        if email_provider == "resend":
            return _send_plain_via_resend(to_email=to_email, subject=subject, body=body)

        delegated_ok, delegated_err = _send_plain_via_graph_delegated(
            to_email=to_email,
            subject=subject,
            body=body,
            delegated_access_token=delegated_access_token,
            delegated_sender_email=delegated_sender_email,
        )
        if delegated_ok:
            return True, ""

        resend_ok, resend_err = _send_plain_via_resend(to_email=to_email, subject=subject, body=body)
        if resend_ok:
            return True, ""

        graph_ok, graph_err = _send_plain_via_graph(to_email=to_email, subject=subject, body=body)
        if graph_ok:
            return True, ""

        smtp_ok, smtp_err = _send_plain_via_smtp(to_email=to_email, subject=subject, body=body)
        if smtp_ok:
            return True, ""

        return (
            False,
            (
                f"Delegated Graph failed: {delegated_err} | "
                f"Resend failed: {resend_err} | "
                f"Graph failed: {graph_err} | "
                f"SMTP failed: {smtp_err}"
            ),
        )
    except Exception as exc:
        return False, f"Plain email send failed unexpectedly: {exc}"



