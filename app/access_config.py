# Hardcoded access configuration.
# Environment variables can extend these defaults without requiring a code edit.

import os

ACCESS_ADMIN_EMAILS = {
    "njagadeesh@aziro.com",
    "rbodicherla@aziro.com",
    "snaik@aziro.com",
    "sbhosale@aziro.com",
    "smrao@aziro.com",
}

def _normalize_email(email: str) -> str:
    return str(email or "").strip().lower()


def _normalize_domain(domain: str) -> str:
    return str(domain or "").strip().lower().lstrip("@")


def _parse_csv_emails(env_name: str) -> set[str]:
    raw = str(os.getenv(env_name, "") or "")
    return {
        _normalize_email(value)
        for value in raw.split(",")
        if _normalize_email(value)
    }


def _parse_csv_domains(env_name: str) -> set[str]:
    raw = str(os.getenv(env_name, "") or "")
    return {
        _normalize_domain(value)
        for value in raw.split(",")
        if _normalize_domain(value)
    }


def get_access_admin_emails() -> list[str]:
    return sorted(
        {
            _normalize_email(email)
            for email in ((ACCESS_ADMIN_EMAILS or set()) | _parse_csv_emails("ACCESS_ADMIN_EMAILS"))
            if _normalize_email(email)
        }
    )


# Backward-compatible single-admin alias (first in sorted order).
ACCESS_ADMIN_EMAIL = (get_access_admin_emails() or [""])[0]
DEFAULT_FULL_ACCESS_EMAILS = {
    "njagadeesh@aziro.com",
    "snaik@aziro.com",
    "sshaikh@aziro.com",
    "rbodicherla@aziro.com"
}


def get_default_full_access_emails() -> list[str]:
    return sorted(
        {
            _normalize_email(email)
            for email in ((DEFAULT_FULL_ACCESS_EMAILS or set()) | _parse_csv_emails("DEFAULT_FULL_ACCESS_EMAILS"))
            if _normalize_email(email)
        }
    )


def get_allowed_login_domains() -> list[str]:
    return sorted(
        {
            _normalize_domain(domain)
            for domain in ({"aziro.com"} | _parse_csv_domains("ALLOWED_LOGIN_DOMAINS"))
            if _normalize_domain(domain)
        }
    )


def get_allowed_login_domain_hint() -> str:
    domains = get_allowed_login_domains()
    return ", ".join(f"@{domain}" for domain in domains) if domains else "@aziro.com"


def is_allowed_login_email(email: str) -> bool:
    normalized = _normalize_email(email)
    if "@" not in normalized:
        return False
    domain = normalized.rsplit("@", 1)[-1]
    return domain in set(get_allowed_login_domains())


ACCESS_REQUEST_NOTIFY_ENABLED = True
ACCESS_REQUEST_COOLDOWN_HOURS = 24
