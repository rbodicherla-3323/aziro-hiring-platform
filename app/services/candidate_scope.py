import re


def normalize_email(value: str) -> str:
    return str(value or "").strip().lower()


def normalize_role_key(value: str) -> str:
    return str(value or "").strip().lower()


def normalize_batch_id(value: str) -> str:
    return str(value or "").strip().lower()


def normalize_role_label(value: str) -> str:
    raw = str(value or "").strip().lower()
    return re.sub(r"\s+", " ", raw)


def build_candidate_key(
    *,
    email: str,
    role_key: str = "",
    role_label: str = "",
    batch_id: str = "",
) -> str:
    email_key = normalize_email(email)
    if not email_key:
        return ""

    batch_key = normalize_batch_id(batch_id)
    scope_role = normalize_role_key(role_key) or normalize_role_label(role_label)
    return "||".join((email_key, batch_key, scope_role))


def get_candidate_key(payload: dict | None) -> str:
    if not isinstance(payload, dict):
        return ""

    return build_candidate_key(
        email=payload.get("email", ""),
        role_key=payload.get("role_key", ""),
        role_label=payload.get("role", "") or payload.get("role_label", ""),
        batch_id=payload.get("batch_id", ""),
    )


def matches_candidate_scope(
    payload: dict | None,
    *,
    candidate_key: str = "",
    email: str = "",
    role_key: str = "",
    role_label: str = "",
    batch_id: str = "",
) -> bool:
    if not isinstance(payload, dict):
        return False

    payload_key = get_candidate_key(payload)
    requested_key = str(candidate_key or "").strip()
    if requested_key:
        return payload_key == requested_key

    email_key = normalize_email(email)
    if email_key and normalize_email(payload.get("email", "")) != email_key:
        return False

    requested_batch = normalize_batch_id(batch_id)
    payload_batch = normalize_batch_id(payload.get("batch_id", ""))
    if requested_batch and requested_batch != payload_batch:
        return False

    requested_role_key = normalize_role_key(role_key)
    payload_role_key = normalize_role_key(payload.get("role_key", ""))
    if requested_role_key and requested_role_key != payload_role_key:
        return False

    requested_role_label = normalize_role_label(role_label)
    payload_role_label = normalize_role_label(payload.get("role", "") or payload.get("role_label", ""))
    if requested_role_label and not requested_role_key and requested_role_label != payload_role_label:
        return False

    return bool(email_key or requested_batch or requested_role_key or requested_role_label)
