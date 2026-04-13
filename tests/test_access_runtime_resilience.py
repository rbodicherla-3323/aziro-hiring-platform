import sys
from pathlib import Path
from types import SimpleNamespace

import sqlalchemy as sa
from flask import Flask, session

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.blueprints.access import access_bp
from app.blueprints.access import routes as access_routes
from app.blueprints.auth import auth_bp
from app.blueprints.auth import routes as auth_routes
from app.extensions import db
from app.services import access_approvals_service as access_service
from app.services.access_approvals_service import ensure_access_approvals_schema, get_approval
from app.access_config import (
    get_access_admin_emails,
    get_default_full_access_emails,
    is_allowed_login_email,
)


def _make_access_app(monkeypatch):
    monkeypatch.setenv("AUTH_DISABLED", "false")
    monkeypatch.setenv("AZURE_CLIENT_ID", "configured-client-id")

    app = Flask(
        __name__,
        root_path=str(PROJECT_ROOT / "app"),
        template_folder="templates",
        static_folder="static",
    )
    app.secret_key = "test-secret"
    app.config["TESTING"] = True
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.jinja_env.globals["ASSET_VERSION"] = "test"
    db.init_app(app)
    app.register_blueprint(access_bp)
    app.register_blueprint(auth_bp)

    @app.context_processor
    def inject_access_admin_context():
        user = session.get("user", {}) if isinstance(session.get("user"), dict) else {}
        user_email = str(user.get("email", "") or "").strip().lower()
        admin_emails = get_access_admin_emails()
        return {
            "is_access_admin": bool(user_email and user_email in admin_emails),
            "access_admin_email": ", ".join(admin_emails),
            "access_admin_emails": admin_emails,
        }

    return app


def _make_auth_app(monkeypatch):
    monkeypatch.setenv("AUTH_DISABLED", "false")
    monkeypatch.setenv("AZURE_CLIENT_ID", "configured-client-id")

    app = Flask(
        __name__,
        root_path=str(PROJECT_ROOT / "app"),
        template_folder="templates",
        static_folder="static",
    )
    app.secret_key = "test-secret"
    app.config["TESTING"] = True
    app.jinja_env.globals["ASSET_VERSION"] = "test"
    app.register_blueprint(auth_bp)
    app.add_url_rule("/dashboard", endpoint="dashboard.dashboard", view_func=lambda: "dashboard")
    return app


def _seed_admin_session(client):
    with client.session_transaction() as sess:
        sess["user"] = {
            "name": "Access Admin",
            "email": "njagadeesh@aziro.com",
            "authenticated": True,
        }
        sess["oauth"] = {"graph_access_token": "test-token"}


def _create_legacy_access_table():
    db.session.execute(
        sa.text(
            "CREATE TABLE access_approvals ("
            "email VARCHAR(320) PRIMARY KEY, "
            "team VARCHAR(50) NOT NULL, "
            "is_active BOOLEAN NOT NULL DEFAULT 0)"
        )
    )
    db.session.execute(
        sa.text(
            "INSERT INTO access_approvals (email, team, is_active) "
            "VALUES (:email, :team, :is_active)"
        ),
        {
            "email": "legacy.user@aziro.com",
            "team": "access",
            "is_active": True,
        },
    )
    db.session.commit()


def test_access_approval_schema_is_backfilled_for_legacy_table(monkeypatch):
    app = _make_access_app(monkeypatch)

    with app.app_context():
        _create_legacy_access_table()
        ensure_access_approvals_schema()

        approval = get_approval("legacy.user@aziro.com")
        assert approval is not None
        assert approval.email == "legacy.user@aziro.com"
        assert bool(approval.is_active) is True

        cols = {
            col.get("name")
            for col in sa.inspect(db.session.get_bind()).get_columns("access_approvals")
        }
        assert {"approved_by", "approved_at", "requested_at", "last_notified_at"}.issubset(cols)


def test_access_management_page_renders_with_legacy_access_schema(monkeypatch):
    app = _make_access_app(monkeypatch)
    with app.app_context():
        _create_legacy_access_table()

    client = app.test_client()
    _seed_admin_session(client)

    response = client.get("/access-management")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Access Management" in body
    assert "legacy.user@aziro.com" in body


def test_auth_callback_redirects_cleanly_when_access_decision_errors(monkeypatch):
    class _FakeMsalApp:
        def acquire_token_by_authorization_code(self, code, scopes, redirect_uri):
            return {
                "access_token": "graph-token",
                "expires_in": 3600,
                "id_token_claims": {
                    "preferred_username": "user.one@aziro.com",
                    "name": "User One",
                },
            }

    app = _make_auth_app(monkeypatch)
    client = app.test_client()

    monkeypatch.setattr(auth_routes, "_build_msal_app", lambda cache=None: _FakeMsalApp())
    monkeypatch.setattr(auth_routes, "decide_access", lambda **kwargs: (_ for _ in ()).throw(RuntimeError("approval lookup failed")))

    response = client.get("/auth/callback?code=test-code", follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/login")


def test_auth_callback_prefers_allowed_graph_mail_over_guest_upn(monkeypatch):
    class _FakeMsalApp:
        def acquire_token_by_authorization_code(self, code, scopes, redirect_uri):
            return {
                "access_token": "graph-token",
                "expires_in": 3600,
                "id_token_claims": {
                    "preferred_username": "bodicherla_ravikumar_ad.msystechnologies.com#ext#@tenant.onmicrosoft.com",
                    "name": "Ravikumar Bodicherla",
                },
            }

    class _FakeGraphResponse:
        status_code = 200
        content = b'{"ok": true}'

        @staticmethod
        def json():
            return {
                "displayName": "Ravikumar Bodicherla",
                "mail": "bodicherla.ravikumar@ad.msystechnologies.com",
                "userPrincipalName": "bodicherla_ravikumar_ad.msystechnologies.com#ext#@tenant.onmicrosoft.com",
                "otherMails": ["rbodicherla@aziro.com"],
            }

    resolved = {}
    monkeypatch.setenv("ALLOWED_LOGIN_DOMAINS", "aziro.com,ad.msystechnologies.com")
    monkeypatch.setenv(
        "DEFAULT_FULL_ACCESS_EMAILS",
        "bodicherla.ravikumar@ad.msystechnologies.com",
    )

    app = _make_auth_app(monkeypatch)
    client = app.test_client()

    monkeypatch.setattr(auth_routes, "_build_msal_app", lambda cache=None: _FakeMsalApp())
    monkeypatch.setattr(auth_routes.requests, "get", lambda *args, **kwargs: _FakeGraphResponse())
    monkeypatch.setattr(auth_routes, "set_graph_delegated_token", lambda **kwargs: None)
    monkeypatch.setattr(auth_routes, "record_login_audit", lambda *args, **kwargs: None)

    def _allow_access(email, **kwargs):
        resolved["email"] = email
        return SimpleNamespace(allowed=True, reason="")

    monkeypatch.setattr(auth_routes, "decide_access", _allow_access)

    response = client.get("/auth/callback?code=test-code", follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/dashboard")
    assert resolved["email"] == "bodicherla.ravikumar@ad.msystechnologies.com"
    with client.session_transaction() as sess:
        assert sess["user"]["email"] == "bodicherla.ravikumar@ad.msystechnologies.com"
        assert bool(sess["user"]["authenticated"]) is True


def test_access_management_approve_works_with_legacy_schema_when_schema_sync_fails(monkeypatch):
    app = _make_access_app(monkeypatch)
    with app.app_context():
        _create_legacy_access_table()

    monkeypatch.setattr(
        access_service,
        "ensure_access_approvals_schema",
        lambda: (_ for _ in ()).throw(PermissionError("ALTER TABLE denied")),
    )
    monkeypatch.setattr(access_routes, "_send_access_approved_user_email", lambda email: (False, "mail disabled"))
    monkeypatch.setattr(access_routes, "_send_access_approved_approver_email", lambda email: (False, "mail disabled"))

    client = app.test_client()
    _seed_admin_session(client)

    response = client.post(
        "/access-management/approve",
        data={"email": "fresh.user@aziro.com"},
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/access-management")
    with app.app_context():
        approval = get_approval("fresh.user@aziro.com")
        assert approval is not None
        assert approval.email == "fresh.user@aziro.com"
        assert bool(approval.is_active) is True


def test_access_management_add_redirects_cleanly_when_notification_raises(monkeypatch):
    app = _make_access_app(monkeypatch)
    with app.app_context():
        db.create_all()

    monkeypatch.setattr(
        access_routes,
        "send_plain_email",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("mail transport crashed")),
    )

    client = app.test_client()
    _seed_admin_session(client)

    response = client.post(
        "/access-management/add",
        data={"email": "invite.user@aziro.com"},
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/access-management")
    with app.app_context():
        approval = get_approval("invite.user@aziro.com")
        assert approval is not None
        assert bool(approval.is_active) is True


def test_env_extensions_allow_non_default_work_domain_login(monkeypatch):
    monkeypatch.setenv("ALLOWED_LOGIN_DOMAINS", "aziro.com,ad.msystechnologies.com")
    monkeypatch.setenv(
        "DEFAULT_FULL_ACCESS_EMAILS",
        "bodicherla.ravikumar@ad.msystechnologies.com",
    )

    assert is_allowed_login_email("bodicherla.ravikumar@ad.msystechnologies.com") is True
    assert "bodicherla.ravikumar@ad.msystechnologies.com" in get_default_full_access_emails()

    decision = access_service.decide_access("bodicherla.ravikumar@ad.msystechnologies.com")

    assert decision.allowed is True


def test_local_denied_access_reason_points_to_env_allowlist(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(access_service, "get_approval", lambda email: None)

    decision = access_service.decide_access("new.user@aziro.com")

    assert decision.allowed is False
    assert "DEFAULT_FULL_ACCESS_EMAILS" in decision.reason


def test_default_access_admins_include_dev_account():
    assert "dev@aziro.com" in get_access_admin_emails()
