import logging
import csv
import io
import math
from datetime import datetime, timezone

from flask import flash, make_response, redirect, render_template, request, session, url_for

from . import access_bp
from app.access_config import get_access_admin_emails
from app.services.access_approvals_service import (
    delete_approval,
    get_approval,
    list_approvals,
    set_access_active,
)
from app.services.email_service import send_plain_email
from app.utils.auth_decorator import login_required

log = logging.getLogger(__name__)


def _normalize_email(email: str) -> str:
    return str(email or "").strip().lower()


def _current_user_email() -> str:
    user = session.get("user", {}) if isinstance(session.get("user"), dict) else {}
    return _normalize_email(user.get("email", ""))


def _access_admin_emails() -> list[str]:
    return get_access_admin_emails()


def _access_admin_display() -> str:
    return ", ".join(_access_admin_emails())


def _is_access_admin() -> bool:
    return bool(_current_user_email() in _access_admin_emails())


def _require_access_admin_page():
    if not _is_access_admin():
        flash("Access denied. Admin approval privileges required.", "danger")
        return redirect(url_for("dashboard.dashboard"))
    return None


def _extract_email_from_form() -> str:
    return _normalize_email(request.form.get("email", ""))


def _parse_int(value, default: int, minimum: int = 1, maximum: int = 200) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, parsed))


def _format_dt(dt) -> str:
    if not dt:
        return ""
    if isinstance(dt, datetime):
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    return str(dt)


def _status_payload(approval) -> tuple[str, str]:
    if approval.is_active:
        return "approved", "Approved"
    if approval.approved_by and approval.approved_at:
        return "revoked", "Revoked"
    if approval.requested_at:
        return "pending", "Pending"
    return "locked", "Locked"


def _approval_rows(approvals: list) -> list[dict]:
    rows = []
    for approval in approvals:
        status_key, status_label = _status_payload(approval)
        rows.append(
            {
                "email": approval.email,
                "status_key": status_key,
                "status_label": status_label,
                "requested_on": _format_dt(approval.requested_at),
                "approved_by": approval.approved_by or "-",
                "approved_at": _format_dt(approval.approved_at),
            }
        )
    return rows


def _pagination_bounds(total: int, page: int, per_page: int) -> tuple[int, int]:
    if total <= 0:
        return 0, 0
    start = (page - 1) * per_page + 1
    end = min(total, page * per_page)
    return start, end



def _send_access_revoked_admin_email(revoked_email: str, existed: bool) -> tuple[bool, str]:
    revoked_email = _normalize_email(revoked_email)
    admin_emails = _access_admin_emails()
    if not admin_emails:
        return False, "Missing admin email."

    subject = f"Access Revoked: {revoked_email or 'unknown'}"
    status_line = "Access status set to revoked (inactive)." if existed else "No approval entry existed in DB."
    body = "\n".join(
        [
            "Access was revoked in Access Management.",
            "",
            f"User: {revoked_email or 'N/A'}",
            f"Revoked by: {_current_user_email()}",
            status_line,
            "",
            f"Manage here: {url_for('access.access_management_page', _external=True)}",
        ]
    )

    oauth = session.get("oauth", {}) if isinstance(session.get("oauth"), dict) else {}
    delegated_token = str(oauth.get("graph_access_token", "") or "")
    delegated_sender = _current_user_email()

    # Skip the revoker — they get a dedicated confirmation email separately.
    revoker_email = _current_user_email()
    sent_any = False
    errors = []
    for admin_email in admin_emails:
        if admin_email == revoker_email:
            continue
        ok, err = send_plain_email(
            to_email=admin_email,
            subject=subject,
            body=body,
            delegated_access_token=delegated_token,
            delegated_sender_email=delegated_sender,
        )
        if ok:
            sent_any = True
        else:
            errors.append(f"{admin_email}: {err}")

    if not admin_emails or all(e == revoker_email for e in admin_emails):
        # All admins are the revoker — nothing extra to send; not a failure.
        return True, ""
    if not sent_any:
        return False, "; ".join(errors) if errors else "Failed to notify admin."
    return True, ""


def _send_access_revoked_revoker_email(revoked_email: str) -> tuple[bool, str]:
    revoked_email = _normalize_email(revoked_email)
    revoker_email = _current_user_email()
    if not revoker_email:
        return False, "Missing revoker email."

    subject = "Access Revoked (Confirmation)"
    body = "\n".join(
        [
            "You revoked access in Access Management.",
            "",
            f"User: {revoked_email or 'N/A'}",
            f"Revoked by: {revoker_email}",
            "",
            f"Manage here: {url_for('access.access_management_page', _external=True)}",
        ]
    )

    oauth = session.get("oauth", {}) if isinstance(session.get("oauth"), dict) else {}
    delegated_token = str(oauth.get("graph_access_token", "") or "")
    delegated_sender = revoker_email

    return send_plain_email(
        to_email=revoker_email,
        subject=subject,
        body=body,
        delegated_access_token=delegated_token,
        delegated_sender_email=delegated_sender,
    )


def _send_access_approved_user_email(approved_email: str) -> tuple[bool, str]:
    approved_email = _normalize_email(approved_email)
    if not approved_email:
        return False, "Missing recipient email."

    subject = "Access Approved"
    login_url = url_for("auth.login", _external=True)
    body = "\n".join(
        [
            "Your access to the Aziro Hiring Platform has been approved.",
            "",
            f"Email: {approved_email}",
            "",
            f"Login here: {login_url}",
        ]
    )

    oauth = session.get("oauth", {}) if isinstance(session.get("oauth"), dict) else {}
    delegated_token = str(oauth.get("graph_access_token", "") or "")
    delegated_sender = _current_user_email()

    return send_plain_email(
        to_email=approved_email,
        subject=subject,
        body=body,
        delegated_access_token=delegated_token,
        delegated_sender_email=delegated_sender,
    )



def _send_access_approved_approver_email(approved_email: str) -> tuple[bool, str]:
    approved_email = _normalize_email(approved_email)
    approver_email = _current_user_email()
    if not approver_email:
        return False, "Missing approver email."
    if approved_email and approver_email == approved_email:
        # Avoid sending two emails to the same inbox when admin approves themselves.
        return True, ""


    subject = "Access Approved (Confirmation)"
    body = "\n".join(
        [
            "You approved access in Access Management.",
            "",
            f"User: {approved_email or 'N/A'}",
            f"Approved by: {approver_email}",
            "",
            f"Manage here: {url_for('access.access_management_page', _external=True)}",
        ]
    )

    oauth = session.get("oauth", {}) if isinstance(session.get("oauth"), dict) else {}
    delegated_token = str(oauth.get("graph_access_token", "") or "")
    delegated_sender = approver_email

    return send_plain_email(
        to_email=approver_email,
        subject=subject,
        body=body,
        delegated_access_token=delegated_token,
        delegated_sender_email=delegated_sender,
    )

@access_bp.route("/access-management")
@login_required
def access_management_page():
    denied = _require_access_admin_page()
    if denied:
        return denied

    page = _parse_int(request.args.get("page"), default=1, minimum=1, maximum=10000)
    per_page = _parse_int(request.args.get("per_page"), default=6, minimum=1, maximum=100)

    try:
        rows_all = _approval_rows(list_approvals())
    except Exception:
        log.exception("Failed to load access approvals for management page")
        flash(
            "Access approvals could not be fully loaded right now. The page is being shown with no rows while the system recovers.",
            "warning",
        )
        rows_all = []
    total_requests = len(rows_all)
    approved_count = sum(1 for r in rows_all if r["status_key"] == "approved")
    pending_count = sum(1 for r in rows_all if r["status_key"] == "pending")
    revoked_count = sum(1 for r in rows_all if r["status_key"] == "revoked")

    total_pages = max(1, math.ceil(total_requests / per_page)) if total_requests else 1
    page = min(page, total_pages)

    slice_start = (page - 1) * per_page
    slice_end = slice_start + per_page
    rows_page = rows_all[slice_start:slice_end]
    range_start, range_end = _pagination_bounds(total_requests, page, per_page)

    page_numbers = list(range(max(1, page - 1), min(total_pages, page + 1) + 1))
    if 1 not in page_numbers and total_pages > 0:
        page_numbers.insert(0, 1)
    if total_pages not in page_numbers and total_pages > 1:
        page_numbers.append(total_pages)

    return render_template(
        "access.html",
        approvals=rows_page,
        access_admin_email=_access_admin_display(),
        total_requests=total_requests,
        approved_count=approved_count,
        pending_count=pending_count,
        revoked_count=revoked_count,
        page=page,
        per_page=per_page,
        total_pages=total_pages,
        page_numbers=page_numbers,
        range_start=range_start,
        range_end=range_end,
    )


@access_bp.route("/access-management/view")
@login_required
def access_management_view():
    denied = _require_access_admin_page()
    if denied:
        return denied

    email = _normalize_email(request.args.get("email", ""))
    if not email or not email.endswith("@aziro.com"):
        flash("Only @aziro.com emails are allowed.", "danger")
        return redirect(url_for("access.access_management_page"))

    try:
        approval = get_approval(email)
    except Exception:
        log.exception("Failed to load approval detail for %s", email)
        flash("Could not load that access record right now.", "warning")
        return redirect(url_for("access.access_management_page"))
    if not approval:
        flash(f"No approval entry found for {email}.", "warning")
        return redirect(url_for("access.access_management_page"))

    status_key, status_label = _status_payload(approval)
    detail = {
        "email": approval.email,
        "status_key": status_key,
        "status_label": status_label,
        "requested_on": _format_dt(approval.requested_at) or "-",
        "approved_by": approval.approved_by or "-",
        "approved_at": _format_dt(approval.approved_at) or "-",
        "is_active": bool(approval.is_active),
    }

    return render_template(
        "access_view.html",
        access_admin_email=_access_admin_display(),
        detail=detail,
    )


@access_bp.route("/access-management/add", methods=["POST"])
@login_required
def access_management_add():
    denied = _require_access_admin_page()
    if denied:
        return denied

    email = _extract_email_from_form()
    if not email.endswith("@aziro.com"):
        flash("Only @aziro.com emails are allowed.", "danger")
        return redirect(url_for("access.access_management_page"))

    try:
        existing = get_approval(email)
        was_active = bool(existing and existing.is_active)

        set_access_active(email=email, is_active=True, approved_by=_current_user_email())

        if not was_active:
            user_ok, user_err = _send_access_approved_user_email(email)
            approver_ok, approver_err = _send_access_approved_approver_email(email)

            if user_ok and approver_ok:
                flash(f"Added access for {email}. Emails sent to user and approver.", "success")
            else:
                parts = []
                if not user_ok:
                    parts.append(f"user email failed: {user_err}")
                if not approver_ok:
                    parts.append(f"approver email failed: {approver_err}")
                detail = "; ".join([p for p in parts if p])
                flash(f"Added access for {email}, but notifications had issues: {detail}", "warning")
        else:
            flash(f"{email} already has access.", "success")
    except Exception:
        log.exception("Access add failed for %s", email)
        flash(f"Could not add access for {email} right now.", "danger")

    return redirect(url_for("access.access_management_page"))


@access_bp.route("/access-management/approve", methods=["POST"])
@login_required
def access_management_approve():
    denied = _require_access_admin_page()
    if denied:
        return denied

    email = _extract_email_from_form()
    if not email.endswith("@aziro.com"):
        flash("Only @aziro.com emails are allowed.", "danger")
        return redirect(url_for("access.access_management_page"))

    try:
        existing = get_approval(email)
        was_active = bool(existing and existing.is_active)

        set_access_active(email=email, is_active=True, approved_by=_current_user_email())

        if not was_active:
            user_ok, user_err = _send_access_approved_user_email(email)
            approver_ok, approver_err = _send_access_approved_approver_email(email)

            if user_ok and approver_ok:
                flash(f"Approved access for {email}. Emails sent to user and approver.", "success")
            else:
                parts = []
                if not user_ok:
                    parts.append(f"user email failed: {user_err}")
                if not approver_ok:
                    parts.append(f"approver email failed: {approver_err}")
                detail = "; ".join([p for p in parts if p])
                flash(f"Approved access for {email}, but notifications had issues: {detail}", "warning")
        else:
            flash(f"Approved access for {email}.", "success")
    except Exception:
        log.exception("Access approve failed for %s", email)
        flash(f"Could not approve access for {email} right now.", "danger")

    return redirect(url_for("access.access_management_page"))


@access_bp.route("/access-management/reject", methods=["POST"])
@login_required
def access_management_reject():
    denied = _require_access_admin_page()
    if denied:
        return denied

    email = _extract_email_from_form()
    if not email.endswith("@aziro.com"):
        flash("Only @aziro.com emails are allowed.", "danger")
        return redirect(url_for("access.access_management_page"))

    try:
        if not get_approval(email):
            flash(f"No approval entry found for {email}.", "warning")
            return redirect(url_for("access.access_management_page"))

        set_access_active(email=email, is_active=False, approved_by=_current_user_email())
        flash(f"Rejected access for {email}.", "warning")
    except Exception:
        log.exception("Access reject failed for %s", email)
        flash(f"Could not reject access for {email} right now.", "danger")
    return redirect(url_for("access.access_management_page"))


@access_bp.route("/access-management/revoke", methods=["POST"])
@login_required
def access_management_revoke():
    denied = _require_access_admin_page()
    if denied:
        return denied

    email = _extract_email_from_form()
    if not email.endswith("@aziro.com"):
        flash("Only @aziro.com emails are allowed.", "danger")
        return redirect(url_for("access.access_management_page"))

    try:
        existed = bool(get_approval(email))
        if existed:
            set_access_active(email=email, is_active=False, approved_by=_current_user_email())

        # Notify revoker (confirmation) and other admins.
        revoker_ok, revoker_err = _send_access_revoked_revoker_email(email)
        admin_ok, admin_err = _send_access_revoked_admin_email(email, existed=existed)

        all_ok = revoker_ok and admin_ok
        if existed:
            if all_ok:
                flash(f"Revoked access for {email}. Notifications sent.", "warning")
            else:
                parts = []
                if not revoker_ok:
                    parts.append(f"revoker email failed: {revoker_err}")
                if not admin_ok:
                    parts.append(f"admin email failed: {admin_err}")
                detail = "; ".join(p for p in parts if p)
                flash(f"Revoked access for {email}, but notifications had issues: {detail}", "warning")
        else:
            if all_ok:
                flash(f"No approval entry found for {email}. Notifications sent.", "warning")
            else:
                parts = []
                if not revoker_ok:
                    parts.append(f"revoker email failed: {revoker_err}")
                if not admin_ok:
                    parts.append(f"admin email failed: {admin_err}")
                detail = "; ".join(p for p in parts if p)
                flash(f"No approval entry found for {email}. Notifications had issues: {detail}", "warning")
    except Exception:
        log.exception("Access revoke failed for %s", email)
        flash(f"Could not revoke access for {email} right now.", "danger")

    return redirect(url_for("access.access_management_page"))


@access_bp.route("/access-management/delete", methods=["POST"])
@login_required
def access_management_delete():
    denied = _require_access_admin_page()
    if denied:
        return denied

    email = _extract_email_from_form()
    if not email.endswith("@aziro.com"):
        flash("Only @aziro.com emails are allowed.", "danger")
        return redirect(url_for("access.access_management_page"))

    try:
        if delete_approval(email):
            flash(f"Deleted access record for {email}.", "warning")
        else:
            flash(f"No approval entry found for {email}.", "warning")
    except Exception:
        log.exception("Access delete failed for %s", email)
        flash(f"Could not delete access record for {email} right now.", "danger")
    return redirect(url_for("access.access_management_page"))


@access_bp.route("/access-management/bulk", methods=["POST"])
@login_required
def access_management_bulk():
    denied = _require_access_admin_page()
    if denied:
        return denied

    bulk_action = str(request.form.get("bulk_action", "")).strip().lower()
    emails = [_normalize_email(e) for e in request.form.getlist("emails") if _normalize_email(e)]

    if bulk_action not in {"approve", "reject", "revoke", "delete"}:
        flash("Invalid bulk action.", "danger")
        return redirect(url_for("access.access_management_page"))
    if not emails:
        flash("Select at least one user.", "warning")
        return redirect(url_for("access.access_management_page"))

    try:
        updated = 0
        for email in emails:
            if not email.endswith("@aziro.com"):
                continue
            if bulk_action == "approve":
                set_access_active(email=email, is_active=True, approved_by=_current_user_email())
                updated += 1
            elif bulk_action in {"reject", "revoke"}:
                if get_approval(email):
                    set_access_active(email=email, is_active=False, approved_by=_current_user_email())
                    updated += 1
            elif bulk_action == "delete":
                if delete_approval(email):
                    updated += 1

        if updated:
            flash(f"Bulk action '{bulk_action}' applied to {updated} user(s).", "success")
        else:
            flash("No records were updated.", "warning")
    except Exception:
        log.exception("Bulk access action failed: %s", bulk_action)
        flash("Could not complete the bulk access action right now.", "danger")
    return redirect(url_for("access.access_management_page"))


@access_bp.route("/access-management/export")
@login_required
def access_management_export():
    denied = _require_access_admin_page()
    if denied:
        return denied

    try:
        rows = _approval_rows(list_approvals())
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["email", "status", "requested_on", "approved_by", "approved_at"])
        for row in rows:
            writer.writerow(
                [
                    row["email"],
                    row["status_label"],
                    row["requested_on"],
                    row["approved_by"],
                    row["approved_at"],
                ]
            )

        response = make_response(output.getvalue())
        response.headers["Content-Type"] = "text/csv; charset=utf-8"
        response.headers["Content-Disposition"] = "attachment; filename=access_management.csv"
        return response
    except Exception:
        log.exception("Access export failed")
        flash("Could not export access approvals right now.", "danger")
        return redirect(url_for("access.access_management_page"))

