"""
Email service for sending generated test links to candidates.
Uses Outlook / Office365 SMTP with environment-based configuration.
"""
import os
import smtplib
from email.message import EmailMessage
from typing import Tuple


DEFAULT_FROM_EMAIL = "aziro-ai-hiring@aziro.com"
DEFAULT_SMTP_HOST = "smtp.office365.com"
DEFAULT_SMTP_PORT = 587


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _round_sort_key(round_key: str):
    if round_key.startswith("L") and round_key[1:].isdigit():
        return (0, int(round_key[1:]))
    return (1, round_key)


def _build_email_body(candidate_name: str, role_label: str, tests: dict) -> str:
    lines = [
        f"Hi {candidate_name},",
        "",
        f"Your test links for the role \"{role_label}\" are ready.",
        "Please complete all rounds using the links below:",
        "",
    ]

    for round_key in sorted(tests.keys(), key=_round_sort_key):
        test_info = tests.get(round_key, {})
        label = test_info.get("label", round_key)
        url = test_info.get("url", "")
        if url:
            lines.append(f"{round_key} - {label}: {url}")

    lines.extend([
        "",
        "Regards,",
        "Aziro Hiring Team",
    ])
    return "\n".join(lines)


def send_candidate_test_links_email(
    candidate_name: str,
    candidate_email: str,
    role_label: str,
    tests: dict,
) -> Tuple[bool, str]:
    """
    Send generated test links to one candidate.

    Returns:
        (True, "") on success
        (False, reason) on failure
    """
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
    tests = tests or {}

    if not smtp_username or not smtp_password:
        return False, "SMTP credentials are missing. Set SMTP_USERNAME and SMTP_PASSWORD."

    has_any_link = any((tests.get(k, {}) or {}).get("url") for k in tests.keys())
    if not has_any_link:
        return False, "No generated test links found for candidate."

    message = EmailMessage()
    message["Subject"] = f"Aziro Hiring Platform - Test Links ({role_label})"
    message["From"] = smtp_from_email
    message["To"] = candidate_email
    message.set_content(_build_email_body(candidate_name, role_label, tests))

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
