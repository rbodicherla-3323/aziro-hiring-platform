import sys
from pathlib import Path

from flask import Flask

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.blueprints.coding import coding_bp
from app.blueprints.coding.services import CodingSessionService
from app.extensions import db
from app.models import RuntimeSessionState
from app.services import db_service, runtime_session_store
from app.services.coding_runtime_store import (
    clear_coding_session_data,
    get_coding_session_data,
    set_coding_session_data,
)
from app.services.mcq_runtime_store import (
    clear_mcq_session_data,
    get_mcq_session_data,
    set_mcq_session_data,
)


def _create_db_app(include_coding_bp: bool = False):
    app = Flask(
        __name__,
        root_path=str(PROJECT_ROOT / "app"),
        template_folder="templates",
        static_folder="static",
    )
    app.secret_key = "test-secret"
    app.config["TESTING"] = True
    app.config["PROCTORING_ENABLED"] = False
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.jinja_env.globals["ASSET_VERSION"] = "test"
    db.init_app(app)
    with app.app_context():
        db.create_all()
    if include_coding_bp:
        app.register_blueprint(coding_bp)
    return app


def _clear_runtime_caches():
    runtime_session_store._RUNTIME_STORE_CACHE["mcq"].clear()
    runtime_session_store._RUNTIME_STORE_CACHE["coding"].clear()


def test_local_sqlite_runtime_store_stays_in_memory_only():
    app = _create_db_app()

    with app.app_context():
        _clear_runtime_caches()
        clear_mcq_session_data("local-mcq")

        set_mcq_session_data("local-mcq", {"questions": [{"id": "q1"}], "answers": {}})
        assert RuntimeSessionState.query.count() == 0

        _clear_runtime_caches()

        assert get_mcq_session_data("local-mcq") is None
        assert RuntimeSessionState.query.count() == 0


def test_runtime_store_can_persist_via_db_when_enabled(monkeypatch):
    app = _create_db_app()
    monkeypatch.setattr(runtime_session_store, "_should_use_db_store", lambda: True)

    with app.app_context():
        _clear_runtime_caches()
        clear_mcq_session_data("db-mcq")

        set_mcq_session_data("db-mcq", {"questions": [{"id": "q1"}], "answers": {"0": "A"}})
        assert RuntimeSessionState.query.count() == 1

        _clear_runtime_caches()

        restored = get_mcq_session_data("db-mcq")
        assert restored == {"questions": [{"id": "q1"}], "answers": {"0": "A"}}

        clear_mcq_session_data("db-mcq")
        _clear_runtime_caches()

        assert get_mcq_session_data("db-mcq") is None
        assert RuntimeSessionState.query.count() == 0


def test_coding_runtime_survives_worker_hop_when_db_mode_enabled(monkeypatch):
    app = _create_db_app(include_coding_bp=True)
    monkeypatch.setattr(runtime_session_store, "_should_use_db_store", lambda: True)

    session_id = "coding-db-hop"
    with app.app_context():
        _clear_runtime_caches()
        clear_coding_session_data(session_id)
        db_service.save_test_link(
            meta={
                "session_id": session_id,
                "candidate_name": "Candidate One",
                "email": "candidate.one@example.com",
                "role_key": "python_dev",
                "role_label": "Python Developer",
                "round_key": "L4",
                "round_label": "Coding Challenge",
                "batch_id": "batch_test_1",
                "language": "python",
            },
            test_type="coding",
            created_by="qa.user@aziro.com",
        )

    client = app.test_client()

    start_response = client.get(f"/coding/start/{session_id}")
    assert start_response.status_code == 200

    _clear_runtime_caches()

    save_response = client.post(
        f"/coding/save/{session_id}",
        json={"code": "print('db-backed')"},
    )
    assert save_response.status_code == 200

    _clear_runtime_caches()

    with app.app_context():
        restored = get_coding_session_data(session_id)
        assert restored is not None
        assert restored["code"] == "print('db-backed')"

        CodingSessionService.save_latest_run_summary(
            session_id,
            {"passed": 1, "total": 1, "run_hidden": False, "time_ms": 12, "status": "PASS"},
        )

    _clear_runtime_caches()

    with app.app_context():
        restored = get_coding_session_data(session_id)
        assert restored["latest_run_summary"]["status"] == "PASS"
        assert restored["latest_run_summary"]["passed"] == 1
