import uuid
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from flask import Flask

from app.blueprints.coding import coding_bp
from app.blueprints.coding import routes as coding_routes
from app.blueprints.coding.services import CodingSessionService
from app.services.coding_session_registry import CODING_SESSION_REGISTRY
from app.services.coding_runtime_store import clear_coding_session_data


def _register_coding_session(session_id: str):
    CODING_SESSION_REGISTRY[session_id] = {
        "candidate_name": "Candidate One",
        "email": "candidate.one@example.com",
        "role_key": "python_dev",
        "role_label": "Python Developer",
        "round_key": "L4",
        "round_label": "Coding Challenge",
        "batch_id": "batch_test_1",
        "language": "python",
    }


def _cleanup_session(session_id: str):
    CODING_SESSION_REGISTRY.pop(session_id, None)
    clear_coding_session_data(session_id)


def _create_test_app(monkeypatch):
    app = Flask(
        __name__,
        root_path=str(PROJECT_ROOT / "app"),
        template_folder="templates",
        static_folder="static",
    )
    app.secret_key = "test-secret"
    app.config["TESTING"] = True
    app.config["PROCTORING_ENABLED"] = False
    app.jinja_env.globals["ASSET_VERSION"] = "test"
    app.register_blueprint(coding_bp)

    # Avoid async evaluation side-effects in this route-level behavior test.
    monkeypatch.setattr(coding_routes, "_evaluate_and_store_coding_result", lambda *args, **kwargs: None)
    return app


def test_coding_submit_invalidates_link_for_reentry(monkeypatch):
    session_id = f"coding-submit-{uuid.uuid4().hex[:8]}"
    _register_coding_session(session_id)

    app = _create_test_app(monkeypatch)
    client = app.test_client()

    try:
        response = client.post(
            f"/coding/submit/{session_id}",
            json={"code": "print('done')"},
            headers={"X-Requested-With": "XMLHttpRequest"},
        )

        assert response.status_code == 200
        payload = response.get_json()
        assert payload["redirect_url"].endswith(f"/coding/completed/{session_id}")

        # Link must be invalid once candidate submits.
        retry_response = client.get(f"/coding/start/{session_id}")
        assert retry_response.status_code == 404
    finally:
        _cleanup_session(session_id)


def test_coding_reentry_before_submit_preserves_timer_and_code(monkeypatch):
    session_id = f"coding-resume-{uuid.uuid4().hex[:8]}"
    _register_coding_session(session_id)

    app = _create_test_app(monkeypatch)
    client = app.test_client()

    try:
        start_response = client.get(f"/coding/start/{session_id}")
        assert start_response.status_code == 200

        begin_response = client.post(
            f"/coding/begin/{session_id}",
            headers={"X-Requested-With": "XMLHttpRequest"},
        )
        assert begin_response.status_code == 200
        assert begin_response.get_json()["status"] == "ok"

        CodingSessionService.save_code(session_id, "print('resume')")
        runtime = CodingSessionService.get_session_data(session_id)
        runtime["start_time"] -= 180
        remaining_before = CodingSessionService.remaining_time(session_id)

        retry_start = client.get(f"/coding/start/{session_id}")
        assert retry_start.status_code == 200

        retry_begin = client.post(
            f"/coding/begin/{session_id}",
            headers={"X-Requested-With": "XMLHttpRequest"},
        )
        assert retry_begin.status_code == 200
        assert retry_begin.get_json()["status"] == "ok"

        remaining_after = CodingSessionService.remaining_time(session_id)
        assert abs(remaining_after - remaining_before) <= 1
        assert CodingSessionService.get_code(session_id) == "print('resume')"

        editor_response = client.get(f"/coding/editor/{session_id}")
        assert editor_response.status_code == 200
    finally:
        _cleanup_session(session_id)

