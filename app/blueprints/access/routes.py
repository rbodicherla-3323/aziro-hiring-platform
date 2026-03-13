from flask import flash, redirect, render_template, request, session, url_for

from . import access_bp
from app.access_config import get_access_admin_emails
from app.services.access_approvals_service import delete_approval, get_approval, list_approvals, set_access_active
from app.services.email_service import send_plain_email
from app.utils.auth_decorator import login_required


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



def _send_access_revoked_admin_email(revoked_email: str, existed: bool) -> tuple[bool, str]:
    revoked_email = _normalize_email(revoked_email)
    admin_emails = _access_admin_emails()
    if not admin_emails:
        return False, "Missing admin email."

    subject = f"Access Revoked: {revoked_email or 'unknown'}"
    status_line = "Entry deleted from approvals table." if existed else "No approval entry existed in DB."
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

    sent_any = False
    errors = []
    for admin_email in admin_emails:
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

    if not sent_any:
        return False, "; ".join(errors) if errors else "Failed to notify admin."
    return True, ""
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

    approvals = list_approvals()
    return render_template(
        "access.html",
        approvals=approvals,
        access_admin_email=_access_admin_display(),
    )


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

    existed = bool(get_approval(email))
    deleted = delete_approval(email)

    # Notify admin (even if it was already missing).
    notify_ok, notify_err = _send_access_revoked_admin_email(email, existed=existed)

    if deleted:
        if notify_ok:
            flash(f"Revoked access for {email}. Entry deleted. Admin notified.", "warning")
        else:
            flash(f"Revoked access for {email}. Entry deleted, but notification failed: {notify_err}", "warning")
    else:
        if notify_ok:
            flash(f"No approval entry found for {email}. Admin notified.", "warning")
        else:
            flash(f"No approval entry found for {email}. Notification failed: {notify_err}", "warning")



    return redirect(url_for("access.access_management_page"))

