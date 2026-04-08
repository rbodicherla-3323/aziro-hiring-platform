import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

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
    created_at = datetime.now(timezone.utc).isoformat()
    candidate = {
        "name": "Alice Example",
        "email": candidate_email,
        "role": "C++ Developer",
        "role_key": "cpp",
        "batch_id": "batch_cpp_1",
        "created_at": created_at,
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
        "created_at": created_at,
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
    assert 'data-email="alice@example.com"' in body
    assert 'data-test-session-id="None"' not in body


def test_reports_page_search_includes_report_backed_candidates(monkeypatch):
    app = _create_test_app(monkeypatch)
    client = app.test_client()

    monkeypatch.setattr(reports_routes, "get_tests_for_user_in_range", lambda user_email, since: [])
    monkeypatch.setattr(reports_routes.EvaluationAggregator, "get_candidates", staticmethod(lambda: []))
    monkeypatch.setattr(reports_routes.db_service, "search_candidates", lambda query, role_filter="": [])
    monkeypatch.setattr(
        reports_routes.db_service,
        "search_candidates_with_reports",
        lambda query, role_filter="": [
            {
                "name": "Archived Candidate",
                "email": "archived@example.com",
                "role": "Python Developer",
                "created_at": "2026-03-20 10:15",
                "report_filename": "archived_candidate_report.pdf",
            }
        ],
    )
    monkeypatch.setattr(
        reports_routes.db_service,
        "get_latest_report_for_email",
        lambda email, **kwargs: {
            "filename": "archived_candidate_report.pdf",
            "created_at": "2026-03-20 10:15",
        },
    )
    monkeypatch.setattr(
        reports_routes,
        "build_proctoring_summary_by_email",
        lambda emails, session_ids_by_email=None: {
            email: reports_routes.blank_proctoring_summary() for email in emails
        },
    )
    monkeypatch.setattr(reports_routes, "build_plagiarism_summary_by_candidates", lambda candidates: {})

    response = client.get("/reports?q=archived")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Archived Candidate" in body
    assert "archived@example.com" in body
    assert "archived_candidate_report.pdf" in body


def test_proctoring_screenshots_list_falls_back_to_empty_when_db_lookup_fails(monkeypatch):
    app = _create_test_app(monkeypatch)
    client = app.test_client()

    monkeypatch.setattr(
        reports_routes.db_service,
        "get_round_session_uuids_for_test_session",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("screenshots unavailable")),
    )

    response = client.get("/reports/proctoring/screenshots?test_session_id=101")

    assert response.status_code == 200
    assert response.get_json() == {"screenshots": []}


def test_proctoring_screenshot_detail_returns_404_when_db_lookup_fails(monkeypatch):
    app = _create_test_app(monkeypatch)
    client = app.test_client()

    monkeypatch.setattr(
        reports_routes.db_service,
        "get_proctoring_screenshot_by_id",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("screenshot unavailable")),
    )

    response = client.get("/reports/proctoring/screenshot/12")

    assert response.status_code == 404


def test_proctoring_screenshots_list_falls_back_to_email_when_session_scope_empty(monkeypatch):
    app = _create_test_app(monkeypatch)
    client = app.test_client()

    monkeypatch.setattr(
        reports_routes.db_service,
        "get_round_session_uuids_for_test_session",
        lambda *args, **kwargs: [],
    )
    monkeypatch.setattr(
        reports_routes.db_service,
        "get_proctoring_screenshots_by_session_ids",
        lambda *args, **kwargs: [],
    )
    monkeypatch.setattr(
        reports_routes.db_service,
        "get_proctoring_screenshots_by_email",
        lambda *args, **kwargs: [
            SimpleNamespace(
                id=7,
                captured_at=datetime(2026, 4, 8, 10, 30, tzinfo=timezone.utc),
                round_key="L2",
                round_label="Python Theory",
                source="mcq",
                event_type="interval_1min",
            )
        ],
    )

    response = client.get("/reports/proctoring/screenshots?test_session_id=101&email=alice@example.com")

    assert response.status_code == 200
    assert response.get_json()["screenshots"][0]["id"] == 7


def test_proctoring_screenshot_detail_serves_filesystem_fallback(monkeypatch):
    app = _create_test_app(monkeypatch)
    client = app.test_client()

    image_dir = PROJECT_ROOT / "app" / "runtime" / "reports_test_assets"
    image_dir.mkdir(parents=True, exist_ok=True)
    image_path = image_dir / f"shot_{uuid4().hex}.png"
    image_bytes = b"\x89PNG\r\n\x1a\nfallback-image"
    image_path.write_bytes(image_bytes)

    monkeypatch.setattr(
        reports_routes.db_service,
        "get_proctoring_screenshot_by_id",
        lambda *_args, **_kwargs: SimpleNamespace(
            id=22,
            image_bytes=None,
            screenshot_path=str(image_path),
            mime_type="image/png",
        ),
    )

    response = client.get("/reports/proctoring/screenshot/22")

    assert response.status_code == 200
    assert response.data == image_bytes
