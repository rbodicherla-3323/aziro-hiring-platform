import os
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models import AccessApproval
from app.services.email_service import send_plain_email
from app.access_config import (
    ACCESS_REQUEST_COOLDOWN_HOURS,
    ACCESS_REQUEST_NOTIFY_ENABLED,
    DEFAULT_FULL_ACCESS_EMAILS,
    get_access_admin_emails,
)

log = logging.getLogger(__name__)

def _normalize_email(email: str) -> str:
    return str(email or "").strip().lower()


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)

def _ensure_aware_utc(value: datetime | None) -> datetime | None:
    if not value:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)

def _access_approvals_has_team() -> bool:
    try:
        bind = db.session.get_bind()
        inspector = sa.inspect(bind)
        cols = [c.get("name") for c in inspector.get_columns("access_approvals")]
        return "team" in cols
    except Exception:
        return False


def _legacy_insert_access_request_with_team(email: str, requested_at: datetime) -> None:
    # Backward compatibility for DBs that still have a NOT NULL team column.
    bind = db.session.get_bind()
    dialect = getattr(bind, "dialect", None)
    name = getattr(dialect, "name", "") if dialect else ""

    if name == "sqlite":
        db.session.execute(
            sa.text(
                "INSERT OR IGNORE INTO access_approvals (email, team, is_active, requested_at) "
                "VALUES (:email, :team, :is_active, :requested_at)"
            ),
            {
                "email": email,
                "team": "access",
                "is_active": 0,
                "requested_at": requested_at,
            },
        )
        # If row exists but requested_at is null, fill it.
        db.session.execute(
            sa.text(
                "UPDATE access_approvals SET requested_at = COALESCE(requested_at, :requested_at) "
                "WHERE email = :email"
            ),
            {"email": email, "requested_at": requested_at},
        )
        return

    # Postgres (and others): try ON CONFLICT.
    db.session.execute(
        sa.text(
            "INSERT INTO access_approvals (email, team, is_active, requested_at) "
            "VALUES (:email, :team, :is_active, :requested_at) "
            "ON CONFLICT (email) DO UPDATE SET requested_at = COALESCE(access_approvals.requested_at, EXCLUDED.requested_at)"
        ),
        {
            "email": email,
            "team": "access",
            "is_active": False,
            "requested_at": requested_at,
        },
    )


@dataclass(frozen=True)
class ApprovalDecision:
    allowed: bool
    reason: str = ""


def list_approvals() -> list[AccessApproval]:
    rows = AccessApproval.query.all()
    # Sort in python to avoid cross-DB NULL ordering differences.
    def _sort_key(a: AccessApproval):
        approved_at = a.approved_at or datetime.min.replace(tzinfo=timezone.utc)
        requested_at = a.requested_at or datetime.min.replace(tzinfo=timezone.utc)
        return (
            0 if a.is_active else 1,
            -int(approved_at.timestamp()),
            -int(requested_at.timestamp()),
            a.email or "",
        )

    return sorted(rows, key=_sort_key)


def get_approval(email: str) -> Optional[AccessApproval]:
    email = _normalize_email(email)
    if not email:
        return None
    return AccessApproval.query.filter_by(email=email).first()



def delete_approval(email: str) -> bool:
    email = _normalize_email(email)
    if not email:
        return False

    row = AccessApproval.query.filter_by(email=email).first()
    if not row:
        return False

    db.session.delete(row)
    db.session.commit()
    return True

def upsert_access_request(email: str) -> AccessApproval:
    email = _normalize_email(email)
    log.info("Access request upsert start: %s", email)

    row = AccessApproval.query.filter_by(email=email).first()
    if row:
        if not row.requested_at:
            row.requested_at = _now_utc()
            db.session.commit()
        log.info(
            "Access request upsert done (existing): %s active=%s requested_at=%s last_notified_at=%s",
            row.email,
            row.is_active,
            row.requested_at,
            row.last_notified_at,
        )
        return row

    requested_at = _now_utc()

    # If the DB still has a NOT NULL team column, use a raw insert that supplies team='access'.
    if _access_approvals_has_team():
        try:
            _legacy_insert_access_request_with_team(email=email, requested_at=requested_at)
            db.session.commit()
        except Exception:
            db.session.rollback()
            raise
        row = AccessApproval.query.filter_by(email=email).first()
        if row:
            log.info(
                "Access request upsert done (legacy team insert): %s active=%s requested_at=%s last_notified_at=%s",
                row.email,
                row.is_active,
                row.requested_at,
                row.last_notified_at,
            )
            return row

    # Normal path (new schema without team).
    try:
        row = AccessApproval(
            email=email,
            is_active=False,
            requested_at=requested_at,
        )
        db.session.add(row)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        # Last resort: if schema mismatch still exists, try legacy insert.
        if _access_approvals_has_team():
            _legacy_insert_access_request_with_team(email=email, requested_at=requested_at)
            db.session.commit()
            row = AccessApproval.query.filter_by(email=email).first()
            if row:
                return row
        raise

    log.info(
        "Access request upsert done (new): %s active=%s requested_at=%s last_notified_at=%s",
        row.email,
        row.is_active,
        row.requested_at,
        row.last_notified_at,
    )
    return row


def set_access_active(email: str, is_active: bool, approved_by: str) -> AccessApproval:
    email = _normalize_email(email)
    approved_by = _normalize_email(approved_by)

    now = _now_utc()
    row = AccessApproval.query.filter_by(email=email).first()
    if not row:
        # Create a request row first (handles legacy schemas with NOT NULL team).
        row = upsert_access_request(email)

    row.is_active = bool(is_active)
    row.approved_by = approved_by
    row.approved_at = now
    if not row.requested_at:
        row.requested_at = now

    db.session.commit()
    return row


def decide_access(
    email: str,
    default_full_access_emails: Iterable[str] | None = None,
    access_admin_emails: Iterable[str] | None = None,
) -> ApprovalDecision:
    email = _normalize_email(email)

    # Default to hardcoded config.
    default_full_access = {
        _normalize_email(e)
        for e in (default_full_access_emails or DEFAULT_FULL_ACCESS_EMAILS or [])
        if _normalize_email(e)
    }
    admin_emails = {
        _normalize_email(e)
        for e in (access_admin_emails or get_access_admin_emails() or [])
        if _normalize_email(e)
    }

    if not email.endswith("@aziro.com"):
        return ApprovalDecision(False, "Only @aziro.com emails are allowed.")

    if email and (email in default_full_access or email in admin_emails):
        return ApprovalDecision(True, "")

    row = get_approval(email)
    if row and row.is_active:
        return ApprovalDecision(True, "")

    return ApprovalDecision(False, "Access request submitted. Please wait for approver approval.")


def maybe_notify_admin_of_request(
    requester_name: str,
    requester_email: str,
    management_url: str,
    delegated_access_token: str = "",
    delegated_sender_email: str = "",
) -> bool:
    if not bool(ACCESS_REQUEST_NOTIFY_ENABLED):
        return False

    admin_emails = get_access_admin_emails()
    if not admin_emails:
        return False

    requester_email = _normalize_email(requester_email)
    if not requester_email:
        return False

    row = upsert_access_request(requester_email)
    cooldown_hours = max(1, int(ACCESS_REQUEST_COOLDOWN_HOURS))
    now = _now_utc()
    last_notified_at = _ensure_aware_utc(row.last_notified_at)
    if last_notified_at and last_notified_at >= (now - timedelta(hours=cooldown_hours)):
        return False

    subject = f"Access Request: {requester_email}"
    body = "\n".join(
        [
            "A user requested access to the Aziro Hiring Platform.",
            "",
            f"Name: {requester_name or 'N/A'}",
            f"Email: {requester_email}",
            f"Requested at: {now.isoformat()}",
            "",
            f"Approve/revoke here: {management_url}",
        ]
    )

    sent_any = False
    errors = []
    for admin_email in admin_emails:
        ok, err = send_plain_email(
            to_email=admin_email,
            subject=subject,
            body=body,
            delegated_access_token=delegated_access_token,
            delegated_sender_email=delegated_sender_email,
        )
        if ok:
            sent_any = True
        else:
            errors.append(f"{admin_email}: {err}")

    if not sent_any:
        log.warning(
            "Access request email send failed (to=%s, requester=%s): %s",
            ", ".join(admin_emails),
            requester_email,
            "; ".join(errors) if errors else "unknown error",
        )
        return False

    if errors:
        log.warning(
            "Access request email partial failures (to=%s, requester=%s): %s",
            ", ".join(admin_emails),
            requester_email,
            "; ".join(errors),
        )

    row.last_notified_at = now
    db.session.commit()
    return True










