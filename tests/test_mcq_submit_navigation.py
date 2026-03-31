import uuid
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from flask import Flask

from app.blueprints.mcq import mcq_bp
from app.services.evaluation_service import EvaluationService
from app.services.evaluation_store import EVALUATION_STORE
from app.services.mcq_runtime_store import clear_mcq_session_data
from app.services.mcq_session_registry import MCQ_SESSION_REGISTRY


def _register_mcq_session(session_id: str):
    MCQ_SESSION_REGISTRY[session_id] = {
        "candidate_name": "Candidate One",
        "email": "candidate.one@example.com",
        "role_key": "qa",
        "role_label": "QA Engineer",
        "round_key": "L2",
        "round_label": "Technical Screening",
        "batch_id": "batch_test_1",
        "selected_questions": [
            {
                "id": "q1",
                "question": "What is 2 + 2?",
                "options": ["3", "4", "5", "6"],
                "correct_answer": "4",
            },
            {
                "id": "q2",
                "question": "What is 3 + 3?",
                "options": ["5", "6", "7", "8"],
                "correct_answer": "6",
            },
        ],
        "question_bank_files": ["tests/mock_questions.json"],
    }


def _cleanup_session(session_id: str):
    MCQ_SESSION_REGISTRY.pop(session_id, None)
    clear_mcq_session_data(session_id)


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
    app.register_blueprint(mcq_bp)
    monkeypatch.setattr(EvaluationService, "_persist_result_to_db", staticmethod(lambda *args, **kwargs: None))
    return app


def test_mcq_question_post_accepts_json_accept_header_for_navigation(monkeypatch):
    session_id = f"mcq-nav-{uuid.uuid4().hex[:8]}"
    _register_mcq_session(session_id)
    EVALUATION_STORE.clear()

    app = _create_test_app(monkeypatch)
    client = app.test_client()

    try:
        start_response = client.get(f"/mcq/start/{session_id}")
        assert start_response.status_code == 200

        response = client.post(
            f"/mcq/question/{session_id}?q=0",
            data={"answer": "4", "nav": "next"},
            headers={"Accept": "application/json"},
        )

        assert response.status_code == 200
        payload = response.get_json()
        assert payload["done"] is False
        assert payload["question"]["q_index"] == 1
        assert payload["question"]["selected_answer"] is None
    finally:
        _cleanup_session(session_id)
        EVALUATION_STORE.clear()


def test_mcq_submit_post_accepts_json_accept_header_and_returns_redirect(monkeypatch):
    session_id = f"mcq-submit-{uuid.uuid4().hex[:8]}"
    _register_mcq_session(session_id)
    EVALUATION_STORE.clear()

    app = _create_test_app(monkeypatch)
    client = app.test_client()

    try:
        start_response = client.get(f"/mcq/start/{session_id}")
        assert start_response.status_code == 200

        response = client.post(
            f"/mcq/submit/{session_id}",
            headers={"Accept": "application/json"},
        )

        assert response.status_code == 200
        payload = response.get_json()
        assert payload["redirect_url"].endswith(f"/mcq/completed/{session_id}")
        assert session_id in EVALUATION_STORE

        # Link must be invalid once candidate submits.
        retry_response = client.get(f"/mcq/start/{session_id}")
        assert retry_response.status_code == 404
    finally:
        _cleanup_session(session_id)
        EVALUATION_STORE.clear()

