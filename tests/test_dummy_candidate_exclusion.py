import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
from datetime import datetime, timedelta, timezone

from flask import Flask

from app.extensions import db
from app.models import Candidate, RoundResult, TestLink as CandidateTestLink, TestSession as CandidateTestSession
from app.services import db_service
from app.services.db_service import is_dummy_candidate_name


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


def test_test_prefix_name_is_excluded_from_stats():
    assert is_dummy_candidate_name("Test_Sanity Candidate") is True
    assert is_dummy_candidate_name("test_candidate") is True
    assert is_dummy_candidate_name("Real Candidate") is False

    app = _create_db_app()
    now = datetime.now(timezone.utc)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)

    with app.app_context():
        real_candidate = Candidate(name="Real Candidate", email="real.candidate@example.com")
        dummy_name_candidate = Candidate(name="Test_Sanity Candidate", email="normal.email@example.com")
        db.session.add_all([real_candidate, dummy_name_candidate])
        db.session.flush()

        real_session = CandidateTestSession(
            candidate_id=real_candidate.id,
            role_key="python_dev",
            role_label="Python Developer",
            batch_id="batch_real",
            created_by="hr@aziro.com",
        )
        dummy_name_session = CandidateTestSession(
            candidate_id=dummy_name_candidate.id,
            role_key="python_dev",
            role_label="Python Developer",
            batch_id="batch_dummy_name",
            created_by="hr@aziro.com",
        )
        db.session.add_all([real_session, dummy_name_session])
        db.session.flush()

        db.session.add_all(
            [
                CandidateTestLink(
                    session_id="real-session",
                    test_type="mcq",
                    candidate_name="Real Candidate",
                    candidate_email="real.candidate@example.com",
                    role_key="python_dev",
                    role_label="Python Developer",
                    round_key="L2",
                    round_label="Technical Screening",
                    batch_id="batch_real",
                    created_by="hr@aziro.com",
                    created_at=now,
                    expires_at=now + timedelta(days=7),
                ),
                CandidateTestLink(
                    session_id="dummy-name-session",
                    test_type="mcq",
                    candidate_name="Test_Sanity Candidate",
                    candidate_email="normal.email@example.com",
                    role_key="python_dev",
                    role_label="Python Developer",
                    round_key="L2",
                    round_label="Technical Screening",
                    batch_id="batch_dummy_name",
                    created_by="hr@aziro.com",
                    created_at=now,
                    expires_at=now + timedelta(days=7),
                ),
            ]
        )
        db.session.add_all(
            [
                RoundResult(
                    test_session_id=real_session.id,
                    session_uuid="real-session",
                    round_key="L2",
                    round_label="Technical Screening",
                    total_questions=15,
                    attempted=15,
                    correct=12,
                    percentage=80,
                    pass_threshold=70,
                    status="PASS",
                ),
                RoundResult(
                    test_session_id=dummy_name_session.id,
                    session_uuid="dummy-name-session",
                    round_key="L2",
                    round_label="Technical Screening",
                    total_questions=15,
                    attempted=15,
                    correct=14,
                    percentage=93.33,
                    pass_threshold=70,
                    status="PASS",
                ),
            ]
        )
        db.session.commit()

        stats = db_service.get_test_link_stats(
            since=start,
            until=end,
            created_by="hr@aziro.com",
        )
        monthly_series = db_service.get_test_link_monthly_series(points=2, created_by="hr@aziro.com")

        assert db_service.get_candidate_count() == 1
        assert db_service.get_candidate_count(include_dummy=True) == 2
        assert stats == {
            "total_candidates": 1,
            "total_tests": 1,
            "completed": 1,
            "pending": 0,
        }
        assert monthly_series[-1]["tests"] == 1
        assert monthly_series[-1]["completed"] == 1
