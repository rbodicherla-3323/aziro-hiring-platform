import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from flask import Flask

from app.blueprints.dashboard import dashboard_bp


def test_create_test_page_has_single_resume_upload(monkeypatch):
    monkeypatch.setenv("AUTH_DISABLED", "true")

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
    client = app.test_client()

    response = client.get("/create-test")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert body.count('name="resume[]"') == 1
    assert "supporting-upload" not in body


def test_create_test_page_contains_email_validated_note(monkeypatch):
    monkeypatch.setenv("AUTH_DISABLED", "true")

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
    client = app.test_client()

    response = client.get("/create-test")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Email Validated!" in body


def test_create_test_page_sets_present_session_anchor_before_submit(monkeypatch):
    monkeypatch.setenv("AUTH_DISABLED", "true")

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
    client = app.test_client()

    response = client.get("/create-test")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "GENERATED_TESTS_PRESENT_SESSION_STARTED_AT_KEY" in body
    assert "generated_tests_present_session_started_at" in body
    assert "String(Date.now())" in body
