import os
import re
import socket

try:
    import dns.resolver as _DNS_RESOLVER
except Exception:
    _DNS_RESOLVER = None


_EMAIL_REGEX = re.compile(
    r"^[A-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Z0-9-]+(?:\.[A-Z0-9-]+)+$",
    re.IGNORECASE,
)


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def normalize_email(value: str) -> str:
    return str(value or "").strip().lower()


def _extract_domain(email: str) -> str:
    parts = str(email or "").rsplit("@", 1)
    if len(parts) != 2:
        return ""
    return parts[1].strip().lower()


def _domain_resolves(domain: str) -> bool:
    try:
        socket.getaddrinfo(domain, None)
        return True
    except Exception:
        return False


def _domain_has_mx(domain: str) -> tuple[bool, str]:
    if _DNS_RESOLVER is None:
        return False, "MX verification is enabled but dnspython is not installed."

    timeout = float(os.getenv("EMAIL_MX_TIMEOUT_SECONDS", "3") or "3")
    resolver = _DNS_RESOLVER.Resolver()
    resolver.lifetime = timeout
    resolver.timeout = timeout

    try:
        answers = resolver.resolve(domain, "MX")
    except Exception:
        return False, "Candidate email domain has no valid MX records."

    return (len(list(answers)) > 0), "Candidate email domain has no valid MX records."


def is_valid_email(value: str) -> bool:
    email = str(value or "").strip()
    if not email or len(email) > 254:
        return False
    return bool(_EMAIL_REGEX.fullmatch(email))


def validate_email(value: str) -> tuple[bool, str]:
    email = str(value or "").strip()
    if not is_valid_email(email):
        return False, "Invalid candidate email address."

    domain = _extract_domain(email)
    if not domain:
        return False, "Invalid candidate email address."

    if _env_bool("EMAIL_VALIDATE_DOMAIN", default=False) and not _domain_resolves(domain):
        return False, "Candidate email domain could not be verified."

    if _env_bool("EMAIL_VALIDATE_MX", default=False):
        has_mx, message = _domain_has_mx(domain)
        if not has_mx:
            return False, message

    return True, ""
