import sys
from pathlib import Path

from flask import Flask

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.blueprints.tests import tests_bp
from app.blueprints.tests import routes as tests_routes


def _create_test_app(monkeypatch):
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

    @app.context_processor
    def inject_access_admin_context():
        return {
            "is_access_admin": False,
            "access_admin_email": "",
            "access_admin_emails": [],
        }

    app.register_blueprint(tests_bp)
    return app


def test_generated_tests_page_normalizes_created_at_for_client_filters(monkeypatch):
    app = _create_test_app(monkeypatch)
    client = app.test_client()

    monkeypatch.setattr(
        tests_routes,
        "get_tests_for_user_today",
        lambda _user_email: [
            {
                "name": "Candidate One",
                "email": "candidate.one@example.com",
                "role": "Python QA",
                "created_at": "2026-04-08 12:44:49.080450",
                "tests": {
                    "L2": {
                        "label": "Round L2",
                        "url": "/mcq/start/session-1",
                        "session_id": "session-1",
                    }
                },
            }
        ],
    )

    response = client.get("/generated-tests")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "candidate.one@example.com" in body
    assert 'data-created-at="2026-04-08T12:44:49.080450+00:00"' in body
