import sys
from datetime import datetime, timezone
from io import BytesIO
import zipfile
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from flask import Flask, session

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

    @app.context_processor
    def inject_access_admin_context():
        user = session.get("user", {}) if isinstance(session.get("user"), dict) else {}
        user_email = str(user.get("email", "") or "").strip().lower()
        admin_emails = reports_routes.get_access_admin_emails()
        return {
            "is_access_admin": bool(user_email and user_email in admin_emails),
            "access_admin_email": ", ".join(admin_emails),
            "access_admin_emails": admin_emails,
        }

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
    monkeypatch.setattr(reports_routes.db_service, "search_candidates", lambda query="", role_filter="", **kwargs: [])
    monkeypatch.setattr(
        reports_routes.db_service,
        "search_candidates_with_reports",
        lambda query="", role_filter="", **kwargs: [
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
    monkeypatch.setattr(
        reports_routes,
        "_load_proctoring_screenshots_from_events",
        lambda **kwargs: [],
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


def test_proctoring_screenshots_list_uses_events_fallback_when_db_rows_missing(monkeypatch):
    app = _create_test_app(monkeypatch)
    client = app.test_client()

    monkeypatch.setattr(
        reports_routes.db_service,
        "get_round_session_uuids_for_test_session",
        lambda *args, **kwargs: ["session-abc"],
    )
    monkeypatch.setattr(
        reports_routes.db_service,
        "get_proctoring_screenshots_by_session_ids",
        lambda *args, **kwargs: [],
    )
    monkeypatch.setattr(
        reports_routes,
        "_load_proctoring_screenshots_from_events",
        lambda **kwargs: [
            {
                "id": "file_demo_token",
                "captured_at": "2026-04-08T10:30:00+00:00",
                "round_key": "L2",
                "round_label": "Python Theory",
                "source": "screen_stream",
                "event_type": "screenshot:interval_1min",
            }
        ],
    )

    response = client.get("/reports/proctoring/screenshots?test_session_id=101&email=alice@example.com")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["screenshots"][0]["id"] == "file_demo_token"


def test_proctoring_screenshot_detail_serves_filesystem_fallback(monkeypatch):
    app = _create_test_app(monkeypatch)
    client = app.test_client()

    image_dir = PROJECT_ROOT / "app" / "runtime" / "proctoring" / "screenshots" / "tests"
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


def test_proctoring_screenshot_detail_serves_encoded_file_ref(monkeypatch):
    app = _create_test_app(monkeypatch)
    client = app.test_client()

    image_dir = PROJECT_ROOT / "app" / "runtime" / "proctoring" / "screenshots" / "tests"
    image_dir.mkdir(parents=True, exist_ok=True)
    image_path = image_dir / f"shot_{uuid4().hex}.jpg"
    image_bytes = b"jpeg-fallback-image"
    image_path.write_bytes(image_bytes)

    encoded_ref = reports_routes._encode_screenshot_file_ref(str(image_path))

    response = client.get(f"/reports/proctoring/screenshot/{encoded_ref}")

    assert response.status_code == 200
    assert response.data == image_bytes


def test_reports_page_admin_date_range_fetches_database_candidates(monkeypatch):
    app = _create_test_app(monkeypatch)
    client = app.test_client()

    with client.session_transaction() as sess:
        sess["user"] = {
            "name": "Creator User",
            "email": "creator@example.com",
            "authenticated": True,
        }

    monkeypatch.setattr(reports_routes, "get_access_admin_emails", lambda: ["creator@example.com"])
    monkeypatch.setattr(reports_routes, "get_tests_for_user_in_range", lambda user_email, since: [])
    monkeypatch.setattr(reports_routes.EvaluationAggregator, "get_candidates", staticmethod(lambda: []))
    monkeypatch.setattr(
        reports_routes.db_service,
        "get_created_candidate_activity",
        lambda **kwargs: [
            {
                "creator_email": "creator@example.com",
                "candidate_name": "Date Scoped Candidate",
                "candidate_email": "scoped@example.com",
                "role": "Python Developer",
                "role_key": "python",
                "batch_id": "batch_py_1",
                "created_at": "2026-04-08 10:15",
                "test_session_id": 55,
                "report_id": 21,
                "report_filename": "date_scoped_candidate_report.pdf",
            }
        ],
    )
    monkeypatch.setattr(
        reports_routes.db_service,
        "get_login_audits_by_range",
        lambda **kwargs: [
            {
                "user_email": "creator@example.com",
                "user_name": "Creator User",
                "logged_in_at": datetime(2026, 4, 9, 11, 45, tzinfo=timezone.utc),
            }
        ],
    )
    monkeypatch.setattr(reports_routes.db_service, "get_latest_report_for_email", lambda *args, **kwargs: None)
    monkeypatch.setattr(reports_routes, "build_plagiarism_summary_by_candidates", lambda candidates: {})
    monkeypatch.setattr(
        reports_routes,
        "build_proctoring_summary_by_email",
        lambda emails, session_ids_by_email=None: {
            email: reports_routes.blank_proctoring_summary() for email in emails
        },
    )

    response = client.get("/reports?from=2026-04-01&to=2026-04-10")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "User Details" in body
    assert "Candidates Created By" in body
    assert "Showing database-backed candidates for 2026-04-01 to 2026-04-10." in body
    assert "Logged-in user summary for the selected database date range." in body
    assert "Creator User" in body
    assert "creator@example.com" in body
    assert 'value="" selected disabled hidden>Logged-in User<' in body
    assert 'id="adminCreatedBySelectBtn"' in body
    assert "Select a logged-in user and click Select to view the candidates created by that user." in body
    assert "Date Scoped Candidate" not in body
    assert "Download All User Logins PDF" in body


def test_admin_db_bulk_download_returns_zip(monkeypatch, tmp_path):
    app = _create_test_app(monkeypatch)
    client = app.test_client()

    with client.session_transaction() as sess:
        sess["user"] = {
            "name": "Reports Admin",
            "email": "admin@aziro.com",
            "authenticated": True,
        }

    monkeypatch.setattr(reports_routes, "get_access_admin_emails", lambda: ["admin@aziro.com"])
    pdf_path = tmp_path / "bulk_candidate_report.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 test pdf")
    monkeypatch.setattr(reports_routes, "REPORTS_DIR", tmp_path)
    monkeypatch.setattr(
        reports_routes.db_service,
        "get_reports_by_ids",
        lambda report_ids: [
            SimpleNamespace(
                id=7,
                filename="bulk_candidate_report.pdf",
                candidate_email="arjun@example.com",
                created_at=datetime(2026, 3, 31, 9, 0, tzinfo=timezone.utc),
                test_session=SimpleNamespace(
                    created_at=datetime(2026, 3, 31, 11, 19, tzinfo=timezone.utc),
                    candidate=SimpleNamespace(name="Arjun Patel"),
                ),
            )
        ],
    )

    response = client.post("/reports/admin/db-bulk-download", data={"report_ids": ["7"]})

    assert response.status_code == 200
    assert response.mimetype == "application/zip"
    assert 'consolidated_candidate_reports_' in response.headers.get("Content-Disposition", "")
    with zipfile.ZipFile(BytesIO(response.data)) as archive:
        assert archive.namelist() == ["Arjun_Patel-2026-03-31.pdf"]


def test_admin_db_bulk_download_keeps_same_day_reports_distinct(monkeypatch, tmp_path):
    app = _create_test_app(monkeypatch)
    client = app.test_client()

    with client.session_transaction() as sess:
        sess["user"] = {
            "name": "Reports Admin",
            "email": "admin@aziro.com",
            "authenticated": True,
        }

    monkeypatch.setattr(reports_routes, "get_access_admin_emails", lambda: ["admin@aziro.com"])
    first_pdf_path = tmp_path / "bulk_candidate_report_1.pdf"
    second_pdf_path = tmp_path / "bulk_candidate_report_2.pdf"
    first_pdf_path.write_bytes(b"%PDF-1.4 first test pdf")
    second_pdf_path.write_bytes(b"%PDF-1.4 second test pdf")
    monkeypatch.setattr(reports_routes, "REPORTS_DIR", tmp_path)
    monkeypatch.setattr(
        reports_routes.db_service,
        "get_reports_by_ids",
        lambda report_ids: [
            SimpleNamespace(
                id=7,
                filename="bulk_candidate_report_1.pdf",
                candidate_email="arjun@example.com",
                created_at=datetime(2026, 3, 26, 9, 0, tzinfo=timezone.utc),
                test_session=SimpleNamespace(
                    created_at=datetime(2026, 3, 26, 9, 23, 42, tzinfo=timezone.utc),
                    candidate=SimpleNamespace(name="Arjun Patel"),
                ),
            ),
            SimpleNamespace(
                id=8,
                filename="bulk_candidate_report_2.pdf",
                candidate_email="arjun@example.com",
                created_at=datetime(2026, 3, 26, 9, 0, tzinfo=timezone.utc),
                test_session=SimpleNamespace(
                    created_at=datetime(2026, 3, 26, 9, 40, 43, tzinfo=timezone.utc),
                    candidate=SimpleNamespace(name="Arjun Patel"),
                ),
            ),
        ],
    )

    response = client.post("/reports/admin/db-bulk-download", data={"report_ids": ["7", "8"]})

    assert response.status_code == 200
    assert response.mimetype == "application/zip"
    with zipfile.ZipFile(BytesIO(response.data)) as archive:
        assert archive.namelist() == [
            "Arjun_Patel-2026-03-26.pdf",
            "Arjun_Patel-2026-03-26_2.pdf",
        ]


def test_admin_db_bulk_download_regenerates_missing_report_files(monkeypatch, tmp_path):
    app = _create_test_app(monkeypatch)
    client = app.test_client()

    with client.session_transaction() as sess:
        sess["user"] = {
            "name": "Reports Admin",
            "email": "admin@aziro.com",
            "authenticated": True,
        }

    monkeypatch.setattr(reports_routes, "get_access_admin_emails", lambda: ["admin@aziro.com"])
    existing_pdf_path = tmp_path / "existing_report.pdf"
    existing_pdf_path.write_bytes(b"%PDF-1.4 existing test pdf")
    monkeypatch.setattr(reports_routes, "REPORTS_DIR", tmp_path)

    missing_report = SimpleNamespace(
        id=8,
        filename="missing_report.pdf",
        candidate_email="arjun@example.com",
        test_session_id=108,
        created_at=datetime(2026, 3, 31, 9, 0, tzinfo=timezone.utc),
        test_session=SimpleNamespace(
            id=108,
            created_at=datetime(2026, 3, 31, 11, 6, 48, tzinfo=timezone.utc),
            candidate=SimpleNamespace(name="Arjun Patel", email="arjun@example.com"),
        ),
    )
    existing_report = SimpleNamespace(
        id=7,
        filename="existing_report.pdf",
        candidate_email="arjun@example.com",
        test_session_id=107,
        created_at=datetime(2026, 3, 31, 9, 0, tzinfo=timezone.utc),
        test_session=SimpleNamespace(
            id=107,
            created_at=datetime(2026, 3, 31, 11, 19, 13, tzinfo=timezone.utc),
            candidate=SimpleNamespace(name="Arjun Patel", email="arjun@example.com"),
        ),
    )
    monkeypatch.setattr(
        reports_routes.db_service,
        "get_reports_by_ids",
        lambda report_ids: [existing_report, missing_report],
    )
    monkeypatch.setattr(
        reports_routes.db_service,
        "get_candidate_report_data",
        lambda email, test_session_id=None, **kwargs: {
            "candidate_key": f"candidate::{test_session_id}",
            "name": "Arjun Patel",
            "email": email,
            "role": "Python QA (4+ Years)",
            "role_key": "python_qa",
            "batch_id": "batch_py_1",
            "test_session_id": test_session_id,
            "rounds": {
                "L1": {
                    "round_label": "Python MCQ",
                    "correct": 8,
                    "total": 10,
                    "attempted": 10,
                    "percentage": 80,
                    "pass_threshold": 70,
                    "status": "PASS",
                    "time_taken_seconds": 600,
                }
            },
            "summary": {
                "total_rounds": 1,
                "attempted_rounds": 1,
                "passed_rounds": 1,
                "failed_rounds": 0,
                "total_correct": 8,
                "total_questions": 10,
                "overall_percentage": 80,
                "overall_verdict": "Selected",
            },
        },
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
            email: reports_routes.blank_proctoring_summary() for email in emails
        },
    )
    monkeypatch.setattr(reports_routes, "build_plagiarism_summary_by_candidates", lambda candidates: {})
    monkeypatch.setattr(
        reports_routes.EvaluationService,
        "generate_candidate_overall_summary",
        staticmethod(lambda email, candidate_data=None: "Overall summary"),
    )
    monkeypatch.setattr(
        reports_routes.EvaluationService,
        "generate_candidate_coding_round_summary",
        staticmethod(lambda email, candidate_data=None: "Coding summary"),
    )
    monkeypatch.setattr(
        reports_routes.EvaluationService,
        "get_candidate_coding_round_data",
        staticmethod(lambda email, candidate_data=None: None),
    )
    monkeypatch.setattr(reports_routes, "_save_report_metadata_best_effort", lambda **kwargs: (None, True))

    def _fake_generate_candidate_pdf(candidate_data):
        filename = f"generated_{candidate_data['test_session_id']}.pdf"
        (tmp_path / filename).write_bytes(b"%PDF-1.4 regenerated test pdf")
        return filename

    monkeypatch.setattr(reports_routes, "generate_candidate_pdf", _fake_generate_candidate_pdf)

    response = client.post("/reports/admin/db-bulk-download", data={"report_ids": ["7", "8"]})

    assert response.status_code == 200
    assert response.mimetype == "application/zip"
    with zipfile.ZipFile(BytesIO(response.data)) as archive:
        assert archive.namelist() == [
            "Arjun_Patel-2026-03-31.pdf",
            "Arjun_Patel-2026-03-31_2.pdf",
        ]


def test_admin_db_bulk_download_includes_filename_only_rows(monkeypatch, tmp_path):
    app = _create_test_app(monkeypatch)
    client = app.test_client()

    with client.session_transaction() as sess:
        sess["user"] = {
            "name": "Reports Admin",
            "email": "admin@aziro.com",
            "authenticated": True,
        }

    monkeypatch.setattr(reports_routes, "get_access_admin_emails", lambda: ["admin@aziro.com"])
    first_pdf_path = tmp_path / "existing_report_1.pdf"
    second_pdf_path = tmp_path / "existing_report_2.pdf"
    first_pdf_path.write_bytes(b"%PDF-1.4 first visible file")
    second_pdf_path.write_bytes(b"%PDF-1.4 second visible file")
    monkeypatch.setattr(reports_routes, "REPORTS_DIR", tmp_path)
    monkeypatch.setattr(reports_routes.db_service, "get_reports_by_ids", lambda report_ids: [])

    response = client.post(
        "/reports/admin/db-bulk-download",
        data={"report_filenames": ["existing_report_1.pdf", "existing_report_2.pdf"]},
    )

    assert response.status_code == 200
    assert response.mimetype == "application/zip"
    with zipfile.ZipFile(BytesIO(response.data)) as archive:
        assert archive.namelist() == ["existing_report_1.pdf", "existing_report_2.pdf"]


def test_admin_db_bulk_download_uses_selected_user_scope(monkeypatch, tmp_path):
    app = _create_test_app(monkeypatch)
    client = app.test_client()

    with client.session_transaction() as sess:
        sess["user"] = {
            "name": "Reports Admin",
            "email": "admin@aziro.com",
            "authenticated": True,
        }

    monkeypatch.setattr(reports_routes, "get_access_admin_emails", lambda: ["admin@aziro.com"])
    first_pdf_path = tmp_path / "scoped_report_1.pdf"
    second_pdf_path = tmp_path / "scoped_report_2.pdf"
    first_pdf_path.write_bytes(b"%PDF-1.4 scoped file 1")
    second_pdf_path.write_bytes(b"%PDF-1.4 scoped file 2")
    monkeypatch.setattr(reports_routes, "REPORTS_DIR", tmp_path)
    monkeypatch.setattr(
        reports_routes.db_service,
        "get_created_candidate_activity",
        lambda **kwargs: [
            {
                "creator_email": "creator@example.com",
                "candidate_name": "Arjun Patel",
                "candidate_email": "arjun@example.com",
                "role": "Python QA (4+ Years)",
                "role_key": "python_qa",
                "batch_id": "batch_py_1",
                "created_at": "2026-03-31 11:19:13",
                "test_session_id": 107,
                "report_id": 7,
                "report_filename": "scoped_report_1.pdf",
            },
            {
                "creator_email": "creator@example.com",
                "candidate_name": "Arjun Patel",
                "candidate_email": "arjun@example.com",
                "role": "Python QA (4+ Years)",
                "role_key": "python_qa",
                "batch_id": "batch_py_1",
                "created_at": "2026-03-31 11:06:48",
                "test_session_id": 108,
                "report_id": 8,
                "report_filename": "scoped_report_2.pdf",
            },
        ],
    )
    monkeypatch.setattr(
        reports_routes.db_service,
        "get_login_audits_by_range",
        lambda **kwargs: [
            {
                "user_email": "creator@example.com",
                "user_name": "Creator User",
                "logged_in_at": datetime(2026, 4, 9, 11, 45, tzinfo=timezone.utc),
                "auth_provider": "microsoft",
            }
        ],
    )
    monkeypatch.setattr(
        reports_routes.db_service,
        "get_reports_by_ids",
        lambda report_ids: [],
    )
    monkeypatch.setattr(
        reports_routes.db_service,
        "get_candidate_report_data",
        lambda email, test_session_id=None, **kwargs: {
            "candidate_key": f"candidate::{test_session_id}",
            "name": "Arjun Patel",
            "email": email,
            "role": "Python QA (4+ Years)",
            "role_key": "python_qa",
            "batch_id": "batch_py_1",
            "test_session_id": test_session_id,
            "rounds": {
                "L1": {
                    "round_label": "Python MCQ",
                    "correct": 8,
                    "total": 10,
                    "attempted": 10,
                    "percentage": 80,
                    "pass_threshold": 70,
                    "status": "PASS",
                    "time_taken_seconds": 600,
                }
            },
            "summary": {
                "total_rounds": 1,
                "attempted_rounds": 1,
                "passed_rounds": 1,
                "failed_rounds": 0,
                "total_correct": 8,
                "total_questions": 10,
                "overall_percentage": 80,
                "overall_verdict": "Selected",
            },
        },
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
            email: reports_routes.blank_proctoring_summary() for email in emails
        },
    )
    monkeypatch.setattr(reports_routes, "build_plagiarism_summary_by_candidates", lambda candidates: {})
    monkeypatch.setattr(
        reports_routes.EvaluationService,
        "generate_candidate_overall_summary",
        staticmethod(lambda email, candidate_data=None: "Overall summary"),
    )
    monkeypatch.setattr(
        reports_routes.EvaluationService,
        "generate_candidate_coding_round_summary",
        staticmethod(lambda email, candidate_data=None: "Coding summary"),
    )
    monkeypatch.setattr(
        reports_routes.EvaluationService,
        "get_candidate_coding_round_data",
        staticmethod(lambda email, candidate_data=None: None),
    )

    def _fake_generate_candidate_pdf(candidate_data):
        filename = f"generated_{candidate_data['test_session_id']}.pdf"
        (tmp_path / filename).write_bytes(f"%PDF-1.4 {candidate_data['test_session_id']}".encode())
        return filename

    monkeypatch.setattr(reports_routes, "generate_candidate_pdf", _fake_generate_candidate_pdf)

    response = client.post(
        "/reports/admin/db-bulk-download",
        data={
            "admin_user": "creator@example.com",
            "from": "2026-03-01",
            "to": "2026-03-31",
            "q": "",
            "role": "",
        },
    )

    assert response.status_code == 200
    assert response.mimetype == "application/zip"
    with zipfile.ZipFile(BytesIO(response.data)) as archive:
        assert archive.namelist() == [
            "Arjun_Patel-2026-03-31.pdf",
            "Arjun_Patel-2026-03-31_2.pdf",
        ]


def test_admin_db_bulk_download_scope_exports_all_visible_rows(monkeypatch, tmp_path):
    app = _create_test_app(monkeypatch)
    client = app.test_client()

    with client.session_transaction() as sess:
        sess["user"] = {
            "name": "Reports Admin",
            "email": "admin@aziro.com",
            "authenticated": True,
        }

    monkeypatch.setattr(reports_routes, "get_access_admin_emails", lambda: ["admin@aziro.com"])
    monkeypatch.setattr(
        reports_routes.db_service,
        "get_created_candidate_activity",
        lambda **kwargs: [
            {
                "creator_email": "creator@example.com",
                "candidate_name": "Arjun Patel",
                "candidate_email": "arjun@example.com",
                "role": "Python QA (4+ Years)",
                "role_key": "python_qa",
                "batch_id": "batch_py_1",
                "created_at": "2026-03-31 11:19:13.846009",
                "test_session_id": 107,
                "report_id": None,
                "report_filename": "",
            },
            {
                "creator_email": "creator@example.com",
                "candidate_name": "Arjun Patel",
                "candidate_email": "arjun@example.com",
                "role": "Python QA (4+ Years)",
                "role_key": "python_qa",
                "batch_id": "batch_py_1",
                "created_at": "2026-03-31 11:06:48.572426",
                "test_session_id": 108,
                "report_id": None,
                "report_filename": "",
            },
            {
                "creator_email": "creator@example.com",
                "candidate_name": "Arjun Patel",
                "candidate_email": "arjun@example.com",
                "role": "Python QA (4+ Years)",
                "role_key": "python_qa",
                "batch_id": "batch_py_1",
                "created_at": "2026-03-30 08:17:37.762033",
                "test_session_id": 109,
                "report_id": None,
                "report_filename": "",
            },
        ],
    )
    monkeypatch.setattr(
        reports_routes.db_service,
        "get_login_audits_by_range",
        lambda **kwargs: [
            {
                "user_email": "creator@example.com",
                "user_name": "Creator User",
                "logged_in_at": datetime(2026, 4, 9, 11, 45, tzinfo=timezone.utc),
                "auth_provider": "microsoft",
            }
        ],
    )
    monkeypatch.setattr(reports_routes, "REPORTS_DIR", tmp_path)
    monkeypatch.setattr(reports_routes.db_service, "get_reports_by_ids", lambda report_ids: [])
    monkeypatch.setattr(reports_routes.db_service, "get_latest_report_for_email", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        reports_routes.db_service,
        "get_candidate_report_data",
        lambda email, test_session_id=None, **kwargs: {
            "candidate_key": f"candidate::{test_session_id}",
            "name": "Arjun Patel",
            "email": email,
            "role": "Python QA (4+ Years)",
            "role_key": "python_qa",
            "batch_id": "batch_py_1",
            "test_session_id": test_session_id,
            "rounds": {
                "L1": {
                    "round_label": "Python MCQ",
                    "correct": 8,
                    "total": 10,
                    "attempted": 10,
                    "percentage": 80,
                    "pass_threshold": 70,
                    "status": "PASS",
                    "time_taken_seconds": 600,
                }
            },
            "summary": {
                "total_rounds": 1,
                "attempted_rounds": 1,
                "passed_rounds": 1,
                "failed_rounds": 0,
                "total_correct": 8,
                "total_questions": 10,
                "overall_percentage": 80,
                "overall_verdict": "Selected",
            },
        },
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
            email: reports_routes.blank_proctoring_summary() for email in emails
        },
    )
    monkeypatch.setattr(reports_routes, "build_plagiarism_summary_by_candidates", lambda candidates: {})
    monkeypatch.setattr(
        reports_routes.EvaluationService,
        "generate_candidate_overall_summary",
        staticmethod(lambda email, candidate_data=None: "Overall summary"),
    )
    monkeypatch.setattr(
        reports_routes.EvaluationService,
        "generate_candidate_coding_round_summary",
        staticmethod(lambda email, candidate_data=None: "Coding summary"),
    )
    monkeypatch.setattr(
        reports_routes.EvaluationService,
        "get_candidate_coding_round_data",
        staticmethod(lambda email, candidate_data=None: None),
    )

    def _fake_generate_candidate_pdf(candidate_data):
        filename = f"generated_{candidate_data['test_session_id']}.pdf"
        (tmp_path / filename).write_bytes(f"%PDF-1.4 {candidate_data['test_session_id']}".encode())
        return filename

    monkeypatch.setattr(reports_routes, "generate_candidate_pdf", _fake_generate_candidate_pdf)

    response = client.post(
        "/reports/admin/db-bulk-download",
        data={
            "admin_user": "creator@example.com",
            "from": "2026-03-01",
            "to": "2026-03-31",
            "q": "",
            "role": "",
        },
    )

    assert response.status_code == 200
    assert response.mimetype == "application/zip"
    with zipfile.ZipFile(BytesIO(response.data)) as archive:
        assert archive.namelist() == [
            "Arjun_Patel-2026-03-31.pdf",
            "Arjun_Patel-2026-03-31_2.pdf",
            "Arjun_Patel-2026-03-30.pdf",
        ]


def test_admin_created_by_details_endpoint_defaults_to_logged_in_user(monkeypatch):
    app = _create_test_app(monkeypatch)
    client = app.test_client()

    with client.session_transaction() as sess:
        sess["user"] = {
            "name": "Creator User",
            "email": "creator@example.com",
            "authenticated": True,
        }

    monkeypatch.setattr(reports_routes, "get_access_admin_emails", lambda: ["creator@example.com"])
    monkeypatch.setattr(
        reports_routes.db_service,
        "get_created_candidate_activity",
        lambda **kwargs: [
            {
                "creator_email": "creator@example.com",
                "candidate_name": "Date Scoped Candidate",
                "candidate_email": "scoped@example.com",
                "role": "Python Developer",
                "role_key": "python",
                "batch_id": "batch_py_1",
                "created_at": "2026-04-08 10:15",
                "test_session_id": 55,
                "report_id": 21,
                "report_filename": "date_scoped_candidate_report.pdf",
            }
        ],
    )
    monkeypatch.setattr(
        reports_routes.db_service,
        "get_login_audits_by_range",
        lambda **kwargs: [
            {
                "user_email": "creator@example.com",
                "user_name": "Creator User",
                "logged_in_at": datetime(2026, 4, 9, 11, 45, tzinfo=timezone.utc),
                "auth_provider": "microsoft",
            }
        ],
    )

    response = client.get("/reports/admin/created-by-details?from=2026-04-01&to=2026-04-10")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["selected_email"] == ""
    assert "Select a logged-in user and click Select to view the candidates created by that user." in payload["html"]

    response = client.get("/reports/admin/created-by-details?from=2026-04-01&to=2026-04-10&admin_user=creator@example.com")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["selected_email"] == "creator@example.com"
    assert "Date Scoped Candidate" in payload["html"]
    assert "Consolidated Evaluation Reports" in payload["html"]
