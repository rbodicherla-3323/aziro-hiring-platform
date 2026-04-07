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

_ACCESS_APPROVALS_REQUIRED_COLUMNS = {
    "approved_by": "VARCHAR(320)",
    "approved_at": "TIMESTAMP",
    "requested_at": "TIMESTAMP",
    "last_notified_at": "TIMESTAMP",
}
_ACCESS_APPROVALS_PROJECTED_COLUMNS = (
    "email",
    "is_active",
    "approved_by",
    "approved_at",
    "requested_at",
    "last_notified_at",
)

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


def _access_approval_columns() -> set[str]:
    try:
        bind = db.session.get_bind()
        inspector = sa.inspect(bind)
        if "access_approvals" not in set(inspector.get_table_names()):
            return set()
        return {c.get("name") for c in inspector.get_columns("access_approvals")}
    except Exception:
        return set()


def _coerce_datetime(value) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return _ensure_aware_utc(value)
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return None
        try:
            return _ensure_aware_utc(datetime.fromisoformat(raw.replace("Z", "+00:00")))
        except ValueError:
            return None
    return None


def _approval_projection_expr(column_name: str, available_cols: set[str]) -> str:
    if column_name in available_cols:
        return column_name
    if column_name == "is_active":
        return "0 AS is_active"
    return f"NULL AS {column_name}"


def _materialize_approval(row_mapping) -> Optional[AccessApproval]:
    row = dict(row_mapping or {})
    email = _normalize_email(row.get("email", ""))
    if not email:
        return None
    return AccessApproval(
        email=email,
        is_active=bool(row.get("is_active", False)),
        approved_by=row.get("approved_by"),
        approved_at=_coerce_datetime(row.get("approved_at")),
        requested_at=_coerce_datetime(row.get("requested_at")),
        last_notified_at=_coerce_datetime(row.get("last_notified_at")),
    )


def _legacy_fetch_approvals(email: str = "") -> list[AccessApproval]:
    available_cols = _access_approval_columns()
    if "email" not in available_cols or "is_active" not in available_cols:
        return []

    projection = ", ".join(
        _approval_projection_expr(column_name, available_cols)
        for column_name in _ACCESS_APPROVALS_PROJECTED_COLUMNS
    )
    query = f"SELECT {projection} FROM access_approvals"
    params = {}
    email = _normalize_email(email)
    if email:
        query += " WHERE lower(email) = :email"
        params["email"] = email
    query += " ORDER BY email"

    rows = db.session.execute(sa.text(query), params).mappings().all()
    approvals = []
    for row in rows:
        approval = _materialize_approval(row)
        if approval:
            approvals.append(approval)
    return approvals


def _legacy_get_approval(email: str) -> Optional[AccessApproval]:
    rows = _legacy_fetch_approvals(email=email)
    return rows[0] if rows else None


def _legacy_delete_approval(email: str) -> bool:
    email = _normalize_email(email)
    if not email:
        return False
    result = db.session.execute(
        sa.text("DELETE FROM access_approvals WHERE lower(email) = :email"),
        {"email": email},
    )
    db.session.commit()
    return bool(getattr(result, "rowcount", 0))


def _legacy_upsert_access_request(email: str) -> AccessApproval:
    email = _normalize_email(email)
    requested_at = _now_utc()
    available_cols = _access_approval_columns()

    row = _legacy_get_approval(email)
    if row:
        if "requested_at" in available_cols and not row.requested_at:
            db.session.execute(
                sa.text(
                    "UPDATE access_approvals "
                    "SET requested_at = COALESCE(requested_at, :requested_at) "
                    "WHERE lower(email) = :email"
                ),
                {"email": email, "requested_at": requested_at},
            )
            db.session.commit()
            row = _legacy_get_approval(email) or row
        return row

    insert_values = {"email": email, "is_active": False}
    if "team" in available_cols:
        insert_values["team"] = "access"
    if "requested_at" in available_cols:
        insert_values["requested_at"] = requested_at

    columns = ", ".join(insert_values.keys())
    placeholders = ", ".join(f":{key}" for key in insert_values.keys())
    bind = db.session.get_bind()
    dialect = getattr(getattr(bind, "dialect", None), "name", "")
    if dialect == "sqlite":
        statement = f"INSERT OR IGNORE INTO access_approvals ({columns}) VALUES ({placeholders})"
    else:
        statement = (
            f"INSERT INTO access_approvals ({columns}) VALUES ({placeholders}) "
            "ON CONFLICT (email) DO NOTHING"
        )
    db.session.execute(sa.text(statement), insert_values)
    db.session.commit()
    return _legacy_get_approval(email) or AccessApproval(email=email, is_active=False)


def _legacy_set_access_active(email: str, is_active: bool, approved_by: str) -> AccessApproval:
    email = _normalize_email(email)
    approved_by = _normalize_email(approved_by)
    now = _now_utc()
    row = _legacy_upsert_access_request(email)
    available_cols = _access_approval_columns()

    assignments = ["is_active = :is_active"]
    params = {"email": email, "is_active": bool(is_active)}
    if "approved_by" in available_cols:
        assignments.append("approved_by = :approved_by")
        params["approved_by"] = approved_by
    if "approved_at" in available_cols:
        assignments.append("approved_at = :approved_at")
        params["approved_at"] = now
    if "requested_at" in available_cols and not row.requested_at:
        assignments.append("requested_at = COALESCE(requested_at, :requested_at)")
        params["requested_at"] = now

    db.session.execute(
        sa.text(
            "UPDATE access_approvals "
            f"SET {', '.join(assignments)} "
            "WHERE lower(email) = :email"
        ),
        params,
    )
    db.session.commit()
    return _legacy_get_approval(email) or row


def _set_last_notified_at(email: str, notified_at: datetime) -> None:
    email = _normalize_email(email)
    if not email:
        return
    available_cols = _access_approval_columns()
    if "last_notified_at" not in available_cols:
        return
    db.session.execute(
        sa.text(
            "UPDATE access_approvals "
            "SET last_notified_at = :last_notified_at "
            "WHERE lower(email) = :email"
        ),
        {"email": email, "last_notified_at": notified_at},
    )
    db.session.commit()


def ensure_access_approvals_schema() -> None:
    """
    Keep the access_approvals table compatible with the current ORM model.

    Production VMs may already have an older version of the table. ``db.create_all()``
    will not alter that existing table, so we patch in the missing nullable columns
    at runtime to avoid user-specific login/admin 500s.
    """
    bind = db.session.get_bind()
    inspector = sa.inspect(bind)
    table_names = set(inspector.get_table_names())
    if "access_approvals" not in table_names:
        AccessApproval.__table__.create(bind=bind, checkfirst=True)
        db.session.commit()
        return

    cols = {c.get("name") for c in inspector.get_columns("access_approvals")}
    missing_cols = [
        col_name
        for col_name in _ACCESS_APPROVALS_REQUIRED_COLUMNS
        if col_name not in cols
    ]
    if not missing_cols:
        return

    try:
        for col_name in missing_cols:
            col_type = _ACCESS_APPROVALS_REQUIRED_COLUMNS[col_name]
            db.session.execute(
                sa.text(
                    f"ALTER TABLE access_approvals ADD COLUMN {col_name} {col_type}"
                )
            )
        db.session.commit()
        log.info(
            "Updated access_approvals schema with missing columns: %s",
            ", ".join(missing_cols),
        )
    except Exception:
        db.session.rollback()
        log.exception(
            "Failed to update access_approvals schema with missing columns: %s",
            ", ".join(missing_cols),
        )
        raise


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
    try:
        ensure_access_approvals_schema()
        rows = AccessApproval.query.all()
    except Exception:
        db.session.rollback()
        log.exception("Falling back to legacy access_approvals read path for list_approvals")
        rows = _legacy_fetch_approvals()
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
    try:
        ensure_access_approvals_schema()
        return AccessApproval.query.filter_by(email=email).first()
    except Exception:
        db.session.rollback()
        log.exception("Falling back to legacy access_approvals read path for %s", email)
        return _legacy_get_approval(email)



def delete_approval(email: str) -> bool:
    email = _normalize_email(email)
    if not email:
        return False

    try:
        ensure_access_approvals_schema()
        row = AccessApproval.query.filter_by(email=email).first()
        if not row:
            return False

        db.session.delete(row)
        db.session.commit()
        return True
    except Exception:
        db.session.rollback()
        log.exception("Falling back to legacy delete path for %s", email)
        return _legacy_delete_approval(email)

def upsert_access_request(email: str) -> AccessApproval:
    email = _normalize_email(email)
    log.info("Access request upsert start: %s", email)

    try:
        ensure_access_approvals_schema()
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
    except Exception:
        db.session.rollback()
        log.exception("Falling back to legacy upsert path for %s", email)
        return _legacy_upsert_access_request(email)

    requested_at = _now_utc()

    # If the DB still has a NOT NULL team column, use a raw insert that supplies team='access'.
    if _access_approvals_has_team():
        try:
            _legacy_insert_access_request_with_team(email=email, requested_at=requested_at)
            db.session.commit()
        except Exception:
            db.session.rollback()
            log.exception("Legacy access request insert failed for %s", email)
            return _legacy_upsert_access_request(email)
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
        if _access_approvals_has_team():
            try:
                _legacy_insert_access_request_with_team(email=email, requested_at=requested_at)
                db.session.commit()
                row = AccessApproval.query.filter_by(email=email).first()
                if row:
                    return row
            except Exception:
                db.session.rollback()
        return _legacy_upsert_access_request(email)
    except Exception:
        db.session.rollback()
        log.exception("Access request ORM upsert failed for %s; using legacy path", email)
        return _legacy_upsert_access_request(email)

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
    try:
        ensure_access_approvals_schema()
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
    except Exception:
        db.session.rollback()
        log.exception("Falling back to legacy set_access_active path for %s", email)
        return _legacy_set_access_active(email, is_active, approved_by)


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

    try:
        _set_last_notified_at(requester_email, now)
    except Exception:
        db.session.rollback()
        log.exception("Failed to persist last_notified_at for %s", requester_email)
    return True










