# Hardcoded access configuration.
# If you want this configurable per environment, switch back to env vars.

ACCESS_ADMIN_EMAILS = {
    "njagadeesh@aziro.com",
    "rbodicherla@aziro.com",
}

def _normalize_email(email: str) -> str:
    return str(email or "").strip().lower()


def get_access_admin_emails() -> list[str]:
    return sorted(
        {
            _normalize_email(email)
            for email in (ACCESS_ADMIN_EMAILS or [])
            if _normalize_email(email)
        }
    )


# Backward-compatible single-admin alias (first in sorted order).
ACCESS_ADMIN_EMAIL = (get_access_admin_emails() or [""])[0]
DEFAULT_FULL_ACCESS_EMAILS = {
    "njagadeesh@aziro.com",
    "snaik@aziro.com",
    "sshaikh@aziro.com"
}

ACCESS_REQUEST_NOTIFY_ENABLED = True
ACCESS_REQUEST_COOLDOWN_HOURS = 24
