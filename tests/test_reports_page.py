import sys
from pathlib import Path

from flask import Flask

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.blueprints.reports import reports_bp
from app.blueprints.reports import routes as reports_routes


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
    app.register_blueprint(reports_bp)
    return app


def test_reports_page_renders_for_attempted_candidate_scope(monkeypatch):
    candidate_email = "alice@example.com"
    candidate = {
        "name": "Alice Example",
        "email": candidate_email,
        "role": "C++ Developer",
        "role_key": "cpp",
        "batch_id": "batch_cpp_1",
        "created_at": "2026-03-27T05:00:00+00:00",
        "rounds": {},
        "summary": {
            "total_rounds": 1,
            "attempted_rounds": 1,
            "passed_rounds": 1,
            "failed_rounds": 0,
            "overall_percentage": 82,
            "overall_verdict": "Selected",
        },
    }
    test_entry = {
        "name": "Alice Example",
        "email": candidate_email,
        "role": "C++ Developer",
        "role_key": "cpp",
        "batch_id": "batch_cpp_1",
        "created_at": "2026-03-27T05:00:00+00:00",
        "tests": {
            "L2": {"session_id": "test-session-1"},
        },
    }

    app = _create_test_app(monkeypatch)
    client = app.test_client()

    monkeypatch.setattr(reports_routes, "get_tests_for_user_in_range", lambda user_email, since: [test_entry])
    monkeypatch.setattr(reports_routes.EvaluationAggregator, "get_candidates", staticmethod(lambda: [candidate]))
    monkeypatch.setattr(reports_routes.db_service, "get_latest_report_for_email", lambda email: None)
    monkeypatch.setattr(
        reports_routes.db_service,
        "get_latest_test_session_id_for_candidate",
        lambda *args, **kwargs: 101,
    )
    monkeypatch.setattr(
        reports_routes.db_service,
        "get_round_session_uuids_for_test_session",
        lambda *args, **kwargs: {"round-session-1"},
    )
    monkeypatch.setattr(
        reports_routes,
        "build_proctoring_summary_by_email",
        lambda emails, session_ids_by_email=None: {
            candidate_email: reports_routes.blank_proctoring_summary()
        },
    )
    monkeypatch.setattr(reports_routes, "build_plagiarism_summary_by_candidates", lambda candidates: {})

    response = client.get("/reports")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Alice Example" in body
    assert "C++ Developer" in body
