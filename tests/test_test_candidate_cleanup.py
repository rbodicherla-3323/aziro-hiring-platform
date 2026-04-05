import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from flask import Flask

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.extensions import db
from app.models import Candidate, ProctoringScreenshot, Report, RoundResult, TestLink as CandidateTestLink, TestSession as CandidateTestSession
from app.services.coding_session_registry import CODING_SESSION_REGISTRY
from app.services.evaluation_store import EVALUATION_STORE
from app.services.generated_tests_store import GENERATED_TESTS
from app.services.mcq_session_registry import MCQ_SESSION_REGISTRY
from app.services import test_candidate_cleanup as cleanup_service
from app.services.test_candidate_cleanup import purge_expired_test_candidates


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


def _clear_stores():
    GENERATED_TESTS.clear()
    EVALUATION_STORE.clear()
    MCQ_SESSION_REGISTRY.clear()
    CODING_SESSION_REGISTRY.clear()


def test_expired_test_candidate_cleanup_purges_old_records_only(monkeypatch):
    app = _create_db_app()
    _clear_stores()

    now = datetime.now(timezone.utc)
    old_time = now - timedelta(minutes=61)
    recent_time = now - timedelta(minutes=30)

    report_dir = PROJECT_ROOT / ".tmp_cleanup_reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(cleanup_service, "REPORTS_DIR", report_dir)
    deleted_paths = []
    monkeypatch.setattr(
        cleanup_service,
        "_safe_unlink",
        lambda path_value: deleted_paths.append(str(path_value)) or True,
    )

    old_report_path = report_dir / "test_old_candidate_report.pdf"
    old_report_path.write_text("old report", encoding="utf-8")
    old_screenshot_path = report_dir / "test_old_candidate_shot.png"
    old_screenshot_path.write_text("old screenshot", encoding="utf-8")

    try:
        with app.app_context():
            old_candidate = Candidate(name="Test_Old Candidate", email="old.test@example.com", created_at=old_time)
            recent_candidate = Candidate(name="Test_Recent Candidate", email="recent.test@example.com", created_at=recent_time)
            real_candidate = Candidate(name="Real Candidate", email="real@example.com", created_at=old_time)
            db.session.add_all([old_candidate, recent_candidate, real_candidate])
            db.session.flush()

            old_session = CandidateTestSession(
                candidate_id=old_candidate.id,
                role_key="python_dev",
                role_label="Python Developer",
                batch_id="batch_old",
                created_by="hr@aziro.com",
                created_at=old_time,
            )
            recent_session = CandidateTestSession(
                candidate_id=recent_candidate.id,
                role_key="python_dev",
                role_label="Python Developer",
                batch_id="batch_recent",
                created_by="hr@aziro.com",
                created_at=recent_time,
            )
            real_session = CandidateTestSession(
                candidate_id=real_candidate.id,
                role_key="python_dev",
                role_label="Python Developer",
                batch_id="batch_real",
                created_by="hr@aziro.com",
                created_at=old_time,
            )
            db.session.add_all([old_session, recent_session, real_session])
            db.session.flush()

            db.session.add_all(
                [
                    CandidateTestLink(
                        session_id="old-session",
                        test_type="mcq",
                        candidate_name="Test_Old Candidate",
                        candidate_email="old.test@example.com",
                        role_key="python_dev",
                        role_label="Python Developer",
                        round_key="L2",
                        round_label="Technical Screening",
                        batch_id="batch_old",
                        created_by="hr@aziro.com",
                        created_at=old_time,
                        expires_at=old_time + timedelta(days=7),
                    ),
                    CandidateTestLink(
                        session_id="recent-session",
                        test_type="mcq",
                        candidate_name="Test_Recent Candidate",
                        candidate_email="recent.test@example.com",
                        role_key="python_dev",
                        role_label="Python Developer",
                        round_key="L2",
                        round_label="Technical Screening",
                        batch_id="batch_recent",
                        created_by="hr@aziro.com",
                        created_at=recent_time,
                        expires_at=recent_time + timedelta(days=7),
                    ),
                    CandidateTestLink(
                        session_id="real-session",
                        test_type="mcq",
                        candidate_name="Real Candidate",
                        candidate_email="real@example.com",
                        role_key="python_dev",
                        role_label="Python Developer",
                        round_key="L2",
                        round_label="Technical Screening",
                        batch_id="batch_real",
                        created_by="hr@aziro.com",
                        created_at=old_time,
                        expires_at=old_time + timedelta(days=7),
                    ),
                ]
            )
            db.session.add_all(
                [
                    RoundResult(
                        test_session_id=old_session.id,
                        session_uuid="old-session",
                        round_key="L2",
                        round_label="Technical Screening",
                        total_questions=15,
                        attempted=15,
                        correct=14,
                        percentage=93.33,
                        pass_threshold=70,
                        status="PASS",
                        created_at=old_time,
                    ),
                    RoundResult(
                        test_session_id=recent_session.id,
                        session_uuid="recent-session",
                        round_key="L2",
                        round_label="Technical Screening",
                        total_questions=15,
                        attempted=15,
                        correct=13,
                        percentage=86.67,
                        pass_threshold=70,
                        status="PASS",
                        created_at=recent_time,
                    ),
                ]
            )
            db.session.add_all(
                [
                    Report(
                        candidate_email="old.test@example.com",
                        test_session_id=old_session.id,
                        filename=old_report_path.name,
                        generated_by="hr@aziro.com",
                        created_at=old_time,
                    ),
                    Report(
                        candidate_email="recent.test@example.com",
                        test_session_id=recent_session.id,
                        filename="recent_test_candidate_report.pdf",
                        generated_by="hr@aziro.com",
                        created_at=recent_time,
                    ),
                ]
            )
            db.session.add_all(
                [
                    ProctoringScreenshot(
                        session_uuid="old-session",
                        candidate_email="old.test@example.com",
                        candidate_name="Test_Old Candidate",
                        round_key="L2",
                        round_label="Technical Screening",
                        source="mcq",
                        event_type="screenshot",
                        mime_type="image/png",
                        image_bytes=b"old",
                        image_size=3,
                        screenshot_path=str(old_screenshot_path.resolve()),
                        captured_at=old_time,
                        created_at=old_time,
                    ),
                    ProctoringScreenshot(
                        session_uuid="recent-session",
                        candidate_email="recent.test@example.com",
                        candidate_name="Test_Recent Candidate",
                        round_key="L2",
                        round_label="Technical Screening",
                        source="mcq",
                        event_type="screenshot",
                        mime_type="image/png",
                        image_bytes=b"new",
                        image_size=3,
                        screenshot_path="",
                        captured_at=recent_time,
                        created_at=recent_time,
                    ),
                ]
            )
            db.session.commit()

            GENERATED_TESTS.extend(
                [
                    {
                        "name": "Test_Old Candidate",
                        "email": "old.test@example.com",
                        "role": "Python Developer",
                        "role_key": "python_dev",
                        "created_by": "hr@aziro.com",
                        "created_at": old_time.isoformat(),
                        "tests": {"L2": {"session_id": "old-session", "type": "mcq"}},
                    },
                    {
                        "name": "Test_Recent Candidate",
                        "email": "recent.test@example.com",
                        "role": "Python Developer",
                        "role_key": "python_dev",
                        "created_by": "hr@aziro.com",
                        "created_at": recent_time.isoformat(),
                        "tests": {"L2": {"session_id": "recent-session", "type": "mcq"}},
                    },
                ]
            )
            MCQ_SESSION_REGISTRY["old-session"] = {
                "session_id": "old-session",
                "candidate_name": "Test_Old Candidate",
                "email": "old.test@example.com",
                "round_key": "L2",
                "created_at": old_time.isoformat(),
            }
            MCQ_SESSION_REGISTRY["recent-session"] = {
                "session_id": "recent-session",
                "candidate_name": "Test_Recent Candidate",
                "email": "recent.test@example.com",
                "round_key": "L2",
                "created_at": recent_time.isoformat(),
            }
            CODING_SESSION_REGISTRY["old-coding-session"] = {
                "session_id": "old-coding-session",
                "candidate_name": "Test_Old Candidate",
                "email": "old.test@example.com",
                "round_key": "L4",
                "created_at": old_time.isoformat(),
            }
            EVALUATION_STORE["old-session"] = {
                "candidate_name": "Test_Old Candidate",
                "email": "old.test@example.com",
                "round_key": "L2",
            }
            EVALUATION_STORE["recent-session"] = {
                "candidate_name": "Test_Recent Candidate",
                "email": "recent.test@example.com",
                "round_key": "L2",
            }

            summary = purge_expired_test_candidates(now=now)

            assert summary["generated_tests_removed"] == 1
            assert summary["mcq_sessions_removed"] == 1
            assert summary["coding_sessions_removed"] == 1
            assert summary["evaluation_entries_removed"] == 1
            assert summary["reports_removed"] == 1
            assert summary["screenshots_removed"] == 1
            assert summary["round_results_removed"] == 1
            assert summary["test_links_removed"] == 1
            assert summary["test_sessions_removed"] == 1
            assert summary["candidates_removed"] == 1

            assert [entry["name"] for entry in GENERATED_TESTS] == ["Test_Recent Candidate"]
            assert "old-session" not in list(MCQ_SESSION_REGISTRY.keys())
            assert "recent-session" in list(MCQ_SESSION_REGISTRY.keys())
            assert "old-coding-session" not in list(CODING_SESSION_REGISTRY.keys())
            assert "old-session" not in EVALUATION_STORE
            assert "recent-session" in EVALUATION_STORE

            assert Candidate.query.filter_by(name="Test_Old Candidate").count() == 0
            assert Candidate.query.filter_by(name="Test_Recent Candidate").count() == 1
            assert Candidate.query.filter_by(name="Real Candidate").count() == 1
            assert CandidateTestLink.query.filter_by(session_id="old-session").count() == 0
            assert CandidateTestLink.query.filter_by(session_id="recent-session").count() == 1
            assert Report.query.filter_by(candidate_email="old.test@example.com").count() == 0
            assert Report.query.filter_by(candidate_email="recent.test@example.com").count() == 1
            assert RoundResult.query.filter_by(session_uuid="old-session").count() == 0
            assert RoundResult.query.filter_by(session_uuid="recent-session").count() == 1
            assert ProctoringScreenshot.query.filter_by(session_uuid="old-session").count() == 0
            assert ProctoringScreenshot.query.filter_by(session_uuid="recent-session").count() == 1

        assert old_report_path.name in deleted_paths
        assert str(old_screenshot_path.resolve()) in deleted_paths
    finally:
        _clear_stores()
        if report_dir.exists():
            for path in report_dir.iterdir():
                try:
                    path.unlink()
                except OSError:
                    pass
            try:
                report_dir.rmdir()
            except OSError:
                pass



