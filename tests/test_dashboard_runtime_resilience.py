import sys
from pathlib import Path
import time
from datetime import datetime, timezone

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from flask import Flask

from app.blueprints.coding import routes as coding_routes
from app.blueprints.coding import coding_bp
from app.blueprints.dashboard import routes as dashboard_routes
from app.blueprints.dashboard import dashboard_bp
from app.blueprints.evaluation import evaluation_bp
from app.blueprints.mcq import mcq_bp
from app.blueprints.reports import reports_bp
from app.blueprints.tests import tests_bp
from app.services.generated_tests_store import GENERATED_TESTS
from app.services import generated_tests_store
from app.services.coding_session_registry import CODING_SESSION_REGISTRY
from app.services.mcq_session_registry import MCQ_SESSION_REGISTRY
from app.services.user_token_store import set_graph_delegated_token, clear_graph_delegated_token
from app.utils import auth_decorator


def _make_app(include_test_generation: bool = False):
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
    app.register_blueprint(evaluation_bp)
    app.register_blueprint(reports_bp)
    if include_test_generation:
        app.register_blueprint(mcq_bp)
        app.register_blueprint(coding_bp)
    return app


def test_dashboard_renders_when_test_link_stats_fail(monkeypatch):
    monkeypatch.setenv("AUTH_DISABLED", "true")
    monkeypatch.setattr(
        dashboard_routes.db_service,
        "get_test_link_stats",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("test_links unavailable")),
    )
    monkeypatch.setattr(
        dashboard_routes.db_service,
        "get_active_test_session_count",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("test_links unavailable")),
    )
    monkeypatch.setattr(
        dashboard_routes.db_service,
        "get_test_link_monthly_series",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("test_links unavailable")),
    )

    app = _make_app()
    client = app.test_client()

    response = client.get("/dashboard")

    assert response.status_code == 200
    assert "Dashboard - Aziro Hiring Platform" in response.get_data(as_text=True)


def test_create_test_survives_test_link_persistence_failure(monkeypatch):
    GENERATED_TESTS.clear()

    monkeypatch.setenv("AUTH_DISABLED", "true")
    monkeypatch.setenv("AUTO_SEND_TEST_EMAILS", "false")
    monkeypatch.setattr(coding_routes, "get_language_runtime_status", lambda _language: (True, "ok"))
    monkeypatch.setattr(
        dashboard_routes.db_service,
        "save_test_link",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("persist unavailable")),
    )

    app = _make_app(include_test_generation=True)
    client = app.test_client()

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
    assert response.headers["Location"].endswith("/generated-tests")
    assert len(GENERATED_TESTS) == 1
    assert GENERATED_TESTS[0]["email"] == "candidate.one@example.com"


def test_generated_tests_store_returns_in_memory_rows_when_db_fallback_fails(monkeypatch):
    GENERATED_TESTS.clear()
    monkeypatch.setattr(
        generated_tests_store,
        "_load_db_tests_for_user",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("db offline")),
    )

    GENERATED_TESTS.append(
        {
            "name": "Candidate One",
            "email": "candidate.one@example.com",
            "role": "Java Entry Level (0-2 Years)",
            "tests": {
                "L2": {
                    "session_id": "session-123",
                    "label": "Round L2",
                    "url": "/mcq/start/session-123",
                    "type": "mcq",
                }
            },
            "created_by": "owner@example.com",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
    )

    rows = generated_tests_store.get_tests_for_user_today("owner@example.com")

    assert len(rows) == 1
    assert rows[0]["email"] == "candidate.one@example.com"


def test_generated_tests_page_shows_multiple_candidates_from_same_batch(monkeypatch):
    GENERATED_TESTS.clear()

    monkeypatch.setenv("AUTH_DISABLED", "true")
    monkeypatch.setenv("AUTO_SEND_TEST_EMAILS", "false")
    monkeypatch.setattr(coding_routes, "get_language_runtime_status", lambda _language: (True, "ok"))
    monkeypatch.setattr(
        dashboard_routes.db_service,
        "save_test_link",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("persist unavailable")),
    )

    app = _make_app(include_test_generation=True)
    client = app.test_client()

    response = client.post(
        "/create-test",
        data={
            "name[]": ["Candidate One", "Candidate Two"],
            "email[]": ["candidate.one@example.com", "candidate.two@example.com"],
            "role[]": ["Java Entry Level (0-2 Years)", "Java Entry Level (0-2 Years)"],
            "domain[]": ["None", "None"],
        },
        follow_redirects=True,
    )

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Candidate One" in body
    assert "Candidate Two" in body
    assert len(GENERATED_TESTS) == 2


def test_create_test_and_generated_tests_work_with_server_side_graph_token(monkeypatch):
    GENERATED_TESTS.clear()
    MCQ_SESSION_REGISTRY.clear()
    CODING_SESSION_REGISTRY.clear()
    clear_graph_delegated_token("qa.user@aziro.com")

    monkeypatch.setenv("AUTH_DISABLED", "false")
    monkeypatch.setenv("AZURE_CLIENT_ID", "configured-client-id")
    monkeypatch.setenv("AUTO_SEND_TEST_EMAILS", "false")
    monkeypatch.setattr(coding_routes, "get_language_runtime_status", lambda _language: (True, "ok"))
    monkeypatch.setattr(dashboard_routes.db_service, "save_test_link", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        auth_decorator,
        "decide_access",
        lambda **kwargs: type("Decision", (), {"allowed": True, "reason": ""})(),
    )

    app = _make_app(include_test_generation=True)
    client = app.test_client()

    set_graph_delegated_token("qa.user@aziro.com", "x" * 5000, expires_in=3600)
    with client.session_transaction() as sess:
        sess["user"] = {
            "name": "QA User",
            "email": "qa.user@aziro.com",
            "authenticated": True,
        }
        sess["oauth"] = {
            "graph_access_token_omitted": True,
            "graph_access_token_expires_at": int(time.time()) + 3600,
        }

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
    assert response.headers["Location"].endswith("/generated-tests")

    page = client.get("/generated-tests")

    assert page.status_code == 200
    body = page.get_data(as_text=True)
    assert "Candidate One" in body
    assert len(GENERATED_TESTS) == 1

    clear_graph_delegated_token("qa.user@aziro.com")
