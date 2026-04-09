import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from flask import Flask

from app.blueprints.coding import routes as coding_routes
from app.blueprints.coding import coding_bp
from app.blueprints.dashboard import routes as dashboard_routes
from app.blueprints.dashboard import dashboard_bp
from app.blueprints.mcq import mcq_bp
from app.blueprints.tests import routes as tests_routes
from app.blueprints.tests import tests_bp
from app.services.coding_session_registry import CODING_SESSION_REGISTRY
from app.services import email_service
from app.services.generated_tests_store import GENERATED_TESTS
from app.services.mcq_session_registry import MCQ_SESSION_REGISTRY


def _seed_auth_session(client, with_oauth: bool = False):
    with client.session_transaction() as sess:
        sess["user"] = {"name": "QA User", "email": "qa.user@example.com"}
        sess["oauth"] = {"graph_access_token": "test-token"} if with_oauth else {}


def _make_app():
    app = Flask(
        __name__,
        root_path=str(PROJECT_ROOT / "app"),
        template_folder="templates",
        static_folder="static",
    )
    app.secret_key = "test-secret"
    app.config["TESTING"] = True
    app.jinja_env.globals["ASSET_VERSION"] = "test"
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(tests_bp)
    app.register_blueprint(mcq_bp)
    app.register_blueprint(coding_bp)
    return app


def test_create_test_auto_send_uses_provider_fallback_without_delegated_token(monkeypatch):
    GENERATED_TESTS.clear()
    MCQ_SESSION_REGISTRY.clear()
    CODING_SESSION_REGISTRY.clear()

    monkeypatch.setenv("AUTH_DISABLED", "true")
    monkeypatch.setenv("AUTO_SEND_TEST_EMAILS", "true")
    monkeypatch.setenv("EMAIL_PROVIDER", "smtp")
    monkeypatch.setattr(dashboard_routes, "get_valid_graph_delegated_token", lambda _email: "")
    monkeypatch.setattr(dashboard_routes, "get_valid_graph_delegated_token_from_session", lambda _oauth: "")
    monkeypatch.setattr(coding_routes, "get_language_runtime_status", lambda _language: (True, "ok"))
    monkeypatch.setattr(dashboard_routes.db_service, "save_test_link", lambda *args, **kwargs: None)

    sent_calls = []

    def _fake_send_candidate_test_links_email(**kwargs):
        sent_calls.append(kwargs)
        return True, ""

    monkeypatch.setattr(
        dashboard_routes,
        "send_candidate_test_links_email",
        _fake_send_candidate_test_links_email,
    )

    app = _make_app()
    client = app.test_client()
    _seed_auth_session(client, with_oauth=False)

    response = client.post(
        "/create-test",
        data={
            "name[]": ["Candidate One"],
            "email[]": ["candidate.one@example.com"],
            "role[]": ["Java Entry Level (0-2 Years)"],
            "domain[]": ["None"],
        },
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert len(sent_calls) == 1
    assert sent_calls[0]["candidate_email"] == "candidate.one@example.com"
    assert sent_calls[0]["delegated_access_token"] == ""
    assert not sent_calls[0].get("force_delegated", False)


def test_generated_tests_retry_send_does_not_force_delegated_token(monkeypatch):
    monkeypatch.setenv("AUTH_DISABLED", "true")
    monkeypatch.setenv("EMAIL_PROVIDER", "smtp")
    monkeypatch.setattr(tests_routes, "get_valid_graph_delegated_token", lambda _email: "")
    monkeypatch.setattr(tests_routes, "get_valid_graph_delegated_token_from_session", lambda _oauth: "")
    monkeypatch.setattr(
        tests_routes,
        "get_tests_for_user_today",
        lambda _email: [
            {
                "name": "Candidate One",
                "email": "candidate.one@example.com",
                "role": "Python QA (5+ Years)",
                "tests": {
                    "L2": {
                        "session_id": "session-123",
                        "label": "MCQ L2",
                        "url": "https://example.com/mcq/start/session-123",
                        "type": "mcq",
                    }
                },
            }
        ],
    )

    sent_calls = []

    def _fake_send_candidate_test_links_email(**kwargs):
        sent_calls.append(kwargs)
        return True, ""

    monkeypatch.setattr(
        tests_routes,
        "send_candidate_test_links_email",
        _fake_send_candidate_test_links_email,
    )

    app = _make_app()
    client = app.test_client()
    _seed_auth_session(client, with_oauth=False)

    response = client.post(
        "/generated-tests/send-emails",
        json={"emails": ["candidate.one@example.com"]},
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["success"] is True
    assert payload["sent_count"] == 1
    assert payload["failed_count"] == 0
    assert len(sent_calls) == 1
    assert sent_calls[0]["delegated_access_token"] == ""
    assert not sent_calls[0].get("force_delegated", False)


def test_send_candidate_test_links_email_shares_with_default_aziro_emails(monkeypatch):
    monkeypatch.setenv("EMAIL_PROVIDER", "smtp")

    captured = {}

    def _fake_send_via_smtp(*, candidate_email, role_label, body, cc_emails=None):
        captured["candidate_email"] = candidate_email
        captured["role_label"] = role_label
        captured["body"] = body
        captured["cc_emails"] = list(cc_emails or [])
        return True, ""

    monkeypatch.setattr(email_service, "_send_via_smtp", _fake_send_via_smtp)

    sent, error = email_service.send_candidate_test_links_email(
        candidate_name="Candidate One",
        candidate_email="candidate.one@example.com",
        role_label="Python QA",
        tests={
            "L2": {
                "label": "MCQ L2",
                "url": "https://example.com/mcq/start/session-123",
                "type": "mcq",
            }
        },
    )

    assert sent is True
    assert error == ""
    assert captured["candidate_email"] == "candidate.one@example.com"
    assert captured["cc_emails"] == [
        "njagadeesh@aziro.com",
        "rbodicherla@aziro.com",
        "snaik@aziro.com",
        "sshaikh@aziro.com",
    ]


def test_send_candidate_test_links_email_excludes_candidate_from_default_share_list(monkeypatch):
    monkeypatch.setenv("EMAIL_PROVIDER", "smtp")

    captured = {}

    def _fake_send_via_smtp(*, candidate_email, role_label, body, cc_emails=None):
        captured["candidate_email"] = candidate_email
        captured["cc_emails"] = list(cc_emails or [])
        return True, ""

    monkeypatch.setattr(email_service, "_send_via_smtp", _fake_send_via_smtp)

    sent, error = email_service.send_candidate_test_links_email(
        candidate_name="Internal Candidate",
        candidate_email="snaik@aziro.com",
        role_label="Python QA",
        tests={
            "L2": {
                "label": "MCQ L2",
                "url": "https://example.com/mcq/start/session-456",
                "type": "mcq",
            }
        },
    )

    assert sent is True
    assert error == ""
    assert captured["candidate_email"] == "snaik@aziro.com"
    assert captured["cc_emails"] == [
        "njagadeesh@aziro.com",
        "rbodicherla@aziro.com",
        "sshaikh@aziro.com",
    ]



def test_send_candidate_test_links_email_rejects_invalid_candidate_email(monkeypatch):
    monkeypatch.setenv("EMAIL_PROVIDER", "smtp")

    sent, error = email_service.send_candidate_test_links_email(
        candidate_name="Candidate One",
        candidate_email="candidate.one@gmail",
        role_label="Python QA",
        tests={
            "L2": {
                "label": "MCQ L2",
                "url": "https://example.com/mcq/start/session-invalid",
                "type": "mcq",
            }
        },
    )

    assert sent is False
    assert error == "Invalid candidate email address."


def test_create_test_skips_invalid_candidate_email(monkeypatch):
    GENERATED_TESTS.clear()
    MCQ_SESSION_REGISTRY.clear()
    CODING_SESSION_REGISTRY.clear()

    monkeypatch.setenv("AUTH_DISABLED", "true")
    monkeypatch.setenv("AUTO_SEND_TEST_EMAILS", "true")
    monkeypatch.setenv("EMAIL_PROVIDER", "smtp")
    monkeypatch.setattr(dashboard_routes, "get_valid_graph_delegated_token", lambda _email: "")
    monkeypatch.setattr(dashboard_routes, "get_valid_graph_delegated_token_from_session", lambda _oauth: "")

    sent_calls = []

    def _fake_send_candidate_test_links_email(**kwargs):
        sent_calls.append(kwargs)
        return True, ""

    monkeypatch.setattr(
        dashboard_routes,
        "send_candidate_test_links_email",
        _fake_send_candidate_test_links_email,
    )

    app = _make_app()
    client = app.test_client()
    _seed_auth_session(client, with_oauth=False)

    response = client.post(
        "/create-test",
        data={
            "name[]": ["Candidate One"],
            "email[]": ["candidate.one@gmail"],
            "role[]": ["Java Entry Level (0-2 Years)"],
            "domain[]": ["None"],
        },
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert sent_calls == []
    assert GENERATED_TESTS == []
    assert len(MCQ_SESSION_REGISTRY) == 0
    assert len(CODING_SESSION_REGISTRY) == 0


def test_generated_tests_retry_send_reports_invalid_candidate_email(monkeypatch):
    monkeypatch.setenv("AUTH_DISABLED", "true")
    monkeypatch.setenv("EMAIL_PROVIDER", "smtp")
    monkeypatch.setattr(tests_routes, "get_valid_graph_delegated_token", lambda _email: "")
    monkeypatch.setattr(tests_routes, "get_valid_graph_delegated_token_from_session", lambda _oauth: "")
    monkeypatch.setattr(
        tests_routes,
        "get_tests_for_user_today",
        lambda _email: [
            {
                "name": "Candidate One",
                "email": "candidate.one@gmail",
                "role": "Python QA (5+ Years)",
                "tests": {
                    "L2": {
                        "session_id": "session-123",
                        "label": "MCQ L2",
                        "url": "https://example.com/mcq/start/session-123",
                        "type": "mcq",
                    }
                },
            }
        ],
    )

    sent_calls = []

    def _fake_send_candidate_test_links_email(**kwargs):
        sent_calls.append(kwargs)
        return True, ""

    monkeypatch.setattr(
        tests_routes,
        "send_candidate_test_links_email",
        _fake_send_candidate_test_links_email,
    )

    app = _make_app()
    client = app.test_client()
    _seed_auth_session(client, with_oauth=False)

    response = client.post(
        "/generated-tests/send-emails",
        json={"emails": ["candidate.one@gmail"]},
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["success"] is True
    assert payload["sent_count"] == 0
    assert payload["failed_count"] == 1
    assert payload["failures"] == [
        {
            "email": "candidate.one@gmail",
            "reason": "Invalid candidate email address.",
        }
    ]
    assert sent_calls == []
