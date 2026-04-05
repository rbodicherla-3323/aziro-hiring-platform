import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from flask import Flask

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.blueprints.evaluation import evaluation_bp
from app.blueprints.evaluation import routes as evaluation_routes
from app.blueprints.reports import reports_bp
from app.blueprints.reports import routes as reports_routes
from app.extensions import db
from app.models import Candidate, RoundResult, TestSession as CandidateTestSession
from app.services import db_service, evaluation_aggregator
from app.services.candidate_scope import build_candidate_key
from app.services.evaluation_aggregator import EvaluationAggregator


def _create_route_app(monkeypatch, blueprint):
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
    app.register_blueprint(blueprint)
    return app


def _create_db_app():
    app = Flask(__name__)
    app.secret_key = "test-secret"
    app.config["TESTING"] = True
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    db.init_app(app)
    with app.app_context():
        db.create_all()
    return app


def _candidate_payload(*, role, role_key, batch_id, test_session_id):
    email = "shared@example.com"
    return {
        "candidate_key": build_candidate_key(
            email=email,
            role_key=role_key,
            role_label=role,
            batch_id=batch_id,
        ),
        "name": "Shared Candidate",
        "email": email,
        "role": role,
        "role_key": role_key,
        "batch_id": batch_id,
        "test_session_id": test_session_id,
        "rounds": {
            "L2": {
                "round_label": "Technical Screening",
                "correct": 12,
                "total": 15,
                "attempted": 15,
                "percentage": 80,
                "pass_threshold": 70,
                "status": "PASS",
                "time_taken_seconds": 600,
                "round_number": 2,
            }
        },
        "summary": {
            "total_rounds": 1,
            "attempted_rounds": 1,
            "passed_rounds": 1,
            "failed_rounds": 0,
            "overall_percentage": 80,
            "overall_verdict": "Selected",
        },
    }


def _test_entry(*, role, role_key, batch_id, session_id):
    return {
        "name": "Shared Candidate",
        "email": "shared@example.com",
        "role": role,
        "role_key": role_key,
        "batch_id": batch_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "tests": {
            "L2": {
                "session_id": session_id,
                "label": "Technical Screening",
                "type": "mcq",
            }
        },
    }


def test_evaluation_aggregator_keeps_same_email_roles_separate(monkeypatch):
    qa_entry = _test_entry(
        role="Python QA",
        role_key="python_qa",
        batch_id="batch_qa_1",
        session_id="qa-l2-session",
    )
    dev_entry = _test_entry(
        role="Python Developer",
        role_key="python_dev",
        batch_id="batch_dev_1",
        session_id="dev-l2-session",
    )

    fake_round_query = SimpleNamespace(order_by=lambda *args, **kwargs: SimpleNamespace(all=lambda: []))
    fake_round_model = SimpleNamespace(
        query=fake_round_query,
        created_at=SimpleNamespace(desc=lambda: None),
    )

    monkeypatch.setattr(evaluation_aggregator, "GENERATED_TESTS", [qa_entry, dev_entry], raising=False)
    monkeypatch.setattr(
        evaluation_aggregator,
        "EVALUATION_STORE",
        {
            "qa-l2-session": {
                "candidate_name": "Shared Candidate",
                "email": "shared@example.com",
                "role_key": "python_qa",
                "role_label": "Python QA",
                "batch_id": "batch_qa_1",
                "round_key": "L2",
                "round_label": "Technical Screening",
                "correct": 13,
                "total_questions": 15,
                "attempted": 15,
                "percentage": 86.67,
                "pass_threshold": 70,
                "status": "PASS",
                "time_taken_seconds": 540,
            },
            "dev-l2-session": {
                "candidate_name": "Shared Candidate",
                "email": "shared@example.com",
                "role_key": "python_dev",
                "role_label": "Python Developer",
                "batch_id": "batch_dev_1",
                "round_key": "L2",
                "round_label": "Technical Screening",
                "correct": 9,
                "total_questions": 15,
                "attempted": 15,
                "percentage": 60,
                "pass_threshold": 70,
                "status": "FAIL",
                "time_taken_seconds": 580,
            },
        },
        raising=False,
    )
    monkeypatch.setattr(
        evaluation_aggregator,
        "TestLink",
        SimpleNamespace(query=SimpleNamespace(all=lambda: [])),
        raising=False,
    )
    monkeypatch.setattr(evaluation_aggregator, "RoundResult", fake_round_model, raising=False)
    monkeypatch.setattr(evaluation_aggregator, "MCQ_SESSION_REGISTRY", {}, raising=False)
    monkeypatch.setattr(evaluation_aggregator, "CODING_SESSION_REGISTRY", {}, raising=False)

    candidates = EvaluationAggregator.get_candidates()
    by_key = {candidate["candidate_key"]: candidate for candidate in candidates}

    qa_key = build_candidate_key(
        email="shared@example.com",
        role_key="python_qa",
        role_label="Python QA",
        batch_id="batch_qa_1",
    )
    dev_key = build_candidate_key(
        email="shared@example.com",
        role_key="python_dev",
        role_label="Python Developer",
        batch_id="batch_dev_1",
    )

    assert set(by_key) == {qa_key, dev_key}
    assert by_key[qa_key]["role"] == "Python QA"
    assert by_key[qa_key]["summary"]["overall_verdict"] == "Selected"
    assert by_key[dev_key]["role"] == "Python Developer"
    assert by_key[dev_key]["summary"]["overall_verdict"] == "Rejected"


def test_evaluation_route_filters_selected_candidate_by_candidate_key(monkeypatch):
    qa_candidate = _candidate_payload(
        role="Python QA",
        role_key="python_qa",
        batch_id="batch_qa_1",
        test_session_id=201,
    )
    dev_candidate = _candidate_payload(
        role="Python Developer",
        role_key="python_dev",
        batch_id="batch_dev_1",
        test_session_id=202,
    )
    qa_test = _test_entry(
        role="Python QA",
        role_key="python_qa",
        batch_id="batch_qa_1",
        session_id="qa-l2-session",
    )
    dev_test = _test_entry(
        role="Python Developer",
        role_key="python_dev",
        batch_id="batch_dev_1",
        session_id="dev-l2-session",
    )

    app = _create_route_app(monkeypatch, evaluation_bp)
    client = app.test_client()

    monkeypatch.setattr(evaluation_routes, "get_tests_for_user_today", lambda user_email: [qa_test, dev_test])
    monkeypatch.setattr(
        evaluation_routes.EvaluationAggregator,
        "get_candidates",
        staticmethod(lambda: [qa_candidate, dev_candidate]),
    )
    monkeypatch.setattr(
        evaluation_routes.db_service,
        "get_round_session_uuids_for_test_session",
        lambda *args, **kwargs: {"qa-l2-session"},
    )
    monkeypatch.setattr(
        evaluation_routes,
        "build_proctoring_summary_by_email",
        lambda emails, session_ids_by_email=None: {
            email: evaluation_routes.blank_proctoring_summary() for email in emails
        },
    )
    monkeypatch.setattr(
        evaluation_routes,
        "build_plagiarism_summary_by_candidates",
        lambda candidates: {
            str(candidate.get("email", "")).strip().lower(): evaluation_routes.blank_plagiarism_summary()
            for candidate in candidates
        },
    )

    response = client.post("/evaluation", data={"candidates": [qa_candidate["candidate_key"]]})

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert qa_candidate["candidate_key"] in body
    assert dev_candidate["candidate_key"] in body
    assert body.count('class="candidate-result-card"') == 1
    assert "Python QA" in body


def test_reports_generate_uses_selected_candidate_scope(monkeypatch):
    qa_candidate = _candidate_payload(
        role="Python QA",
        role_key="python_qa",
        batch_id="batch_qa_1",
        test_session_id=301,
    )
    dev_candidate = _candidate_payload(
        role="Python Developer",
        role_key="python_dev",
        batch_id="batch_dev_1",
        test_session_id=302,
    )

    app = _create_route_app(monkeypatch, reports_bp)
    client = app.test_client()
    captured = {}

    monkeypatch.setattr(
        reports_routes.EvaluationAggregator,
        "get_candidates",
        staticmethod(lambda: [qa_candidate, dev_candidate]),
    )
    monkeypatch.setattr(
        reports_routes,
        "build_proctoring_summary_by_email",
        lambda emails, session_ids_by_email=None: {
            email: reports_routes.blank_proctoring_summary() for email in emails
        },
    )
    monkeypatch.setattr(reports_routes, "build_plagiarism_summary_by_candidates", lambda candidates: {})
    monkeypatch.setattr(
        reports_routes.db_service,
        "get_round_session_uuids_for_test_session",
        lambda *args, **kwargs: {"qa-l2-session"},
    )
    monkeypatch.setattr(
        reports_routes.db_service,
        "ensure_candidate_session_for_report",
        lambda *args, **kwargs: SimpleNamespace(id=qa_candidate["test_session_id"]),
    )
    monkeypatch.setattr(reports_routes.db_service, "save_report", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        reports_routes.EvaluationService,
        "generate_candidate_overall_summary",
        staticmethod(lambda email, candidate_data=None: "overall summary"),
    )
    monkeypatch.setattr(
        reports_routes.EvaluationService,
        "generate_candidate_coding_round_summary",
        staticmethod(lambda email, candidate_data=None: None),
    )
    monkeypatch.setattr(
        reports_routes.EvaluationService,
        "get_candidate_coding_round_data",
        staticmethod(lambda email, candidate_data=None: None),
    )

    def _fake_generate_candidate_pdf(candidate_data):
        captured["candidate_data"] = dict(candidate_data)
        return "shared_candidate_python_qa.pdf"

    monkeypatch.setattr(reports_routes, "generate_candidate_pdf", _fake_generate_candidate_pdf)

    response = client.get(
        "/reports/generate/shared@example.com"
        f"?candidate_key={qa_candidate['candidate_key']}"
        "&role_key=python_qa"
        "&batch_id=batch_qa_1"
        f"&test_session_id={qa_candidate['test_session_id']}"
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["success"] is True
    assert captured["candidate_data"]["role"] == "Python QA"
    assert captured["candidate_data"]["role_key"] == "python_qa"
    assert captured["candidate_data"]["candidate_key"] == qa_candidate["candidate_key"]


def test_reports_search_keeps_same_email_candidates_separate_by_role(monkeypatch):
    app = _create_route_app(monkeypatch, reports_bp)
    client = app.test_client()

    monkeypatch.setattr(reports_routes, "get_tests_for_user_in_range", lambda *args, **kwargs: [])
    monkeypatch.setattr(
        reports_routes.db_service,
        "search_candidates_with_reports",
        lambda query, role_filter="": [
            {
                "name": "Shared Candidate",
                "email": "shared@example.com",
                "role": "Python QA",
                "role_key": "python_qa",
                "batch_id": "batch_qa_1",
                "test_session_id": 401,
                "created_at": "2026-03-31 10:00",
                "report_filename": "shared_candidate_python_qa.pdf",
            },
            {
                "name": "Shared Candidate",
                "email": "shared@example.com",
                "role": "Python Developer",
                "role_key": "python_dev",
                "batch_id": "batch_dev_1",
                "test_session_id": 402,
                "created_at": "2026-03-31 10:05",
                "report_filename": "shared_candidate_python_dev.pdf",
            },
        ],
    )

    response = client.get("/reports/search?q=shared@example.com")

    assert response.status_code == 200
    payload = response.get_json()
    assert len(payload["candidates"]) == 2
    assert {candidate["role"] for candidate in payload["candidates"]} == {
        "Python QA",
        "Python Developer",
    }
    assert {candidate["candidate_key"] for candidate in payload["candidates"]} == {
        build_candidate_key(
            email="shared@example.com",
            role_key="python_qa",
            role_label="Python QA",
            batch_id="batch_qa_1",
        ),
        build_candidate_key(
            email="shared@example.com",
            role_key="python_dev",
            role_label="Python Developer",
            batch_id="batch_dev_1",
        ),
    }


def test_db_candidate_report_data_respects_role_and_session_scope():
    app = _create_db_app()

    with app.app_context():
        candidate = Candidate(name="Shared Candidate", email="shared@example.com")
        db.session.add(candidate)
        db.session.flush()

        qa_session = CandidateTestSession(
            candidate_id=candidate.id,
            role_key="python_qa",
            role_label="Python QA",
            batch_id="batch_qa_1",
            created_by="dev@aziro.com",
        )
        dev_session = CandidateTestSession(
            candidate_id=candidate.id,
            role_key="python_dev",
            role_label="Python Developer",
            batch_id="batch_dev_1",
            created_by="dev@aziro.com",
        )
        db.session.add_all([qa_session, dev_session])
        db.session.flush()

        db.session.add_all(
            [
                RoundResult(
                    test_session_id=qa_session.id,
                    session_uuid="qa-l2-session",
                    round_key="L2",
                    round_label="Technical Screening",
                    total_questions=15,
                    attempted=15,
                    correct=13,
                    percentage=86.67,
                    pass_threshold=70,
                    status="PASS",
                ),
                RoundResult(
                    test_session_id=dev_session.id,
                    session_uuid="dev-l2-session",
                    round_key="L2",
                    round_label="Technical Screening",
                    total_questions=15,
                    attempted=15,
                    correct=9,
                    percentage=60,
                    pass_threshold=70,
                    status="FAIL",
                ),
            ]
        )
        db.session.commit()

        qa_by_session = db_service.get_candidate_report_data(
            "shared@example.com",
            test_session_id=qa_session.id,
        )
        qa_by_role = db_service.get_candidate_report_data(
            "shared@example.com",
            role_key="python_qa",
            batch_id="batch_qa_1",
        )
        dev_by_role = db_service.get_candidate_report_data(
            "shared@example.com",
            role_key="python_dev",
            batch_id="batch_dev_1",
        )

        assert qa_by_session["role"] == "Python QA"
        assert qa_by_session["test_session_id"] == qa_session.id
        assert qa_by_session["candidate_key"] == build_candidate_key(
            email="shared@example.com",
            role_key="python_qa",
            role_label="Python QA",
            batch_id="batch_qa_1",
        )
        assert qa_by_role["summary"]["overall_verdict"] == "Selected"
        assert dev_by_role["role"] == "Python Developer"
        assert dev_by_role["summary"]["overall_verdict"] == "Rejected"
