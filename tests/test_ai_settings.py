import sys
from pathlib import Path

from flask import Flask, session

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.access_config import get_access_admin_emails
from app.blueprints.access import access_bp
from app.blueprints.auth import auth_bp
from app.extensions import db
from app.models import AIProviderConfig
from app.services import ai_generator, ai_settings_service, document_intelligence


def _make_app(monkeypatch):
    monkeypatch.setenv("AUTH_DISABLED", "false")
    monkeypatch.setenv("AZURE_CLIENT_ID", "configured-client-id")

    app = Flask(
        __name__,
        root_path=str(PROJECT_ROOT / "app"),
        template_folder="templates",
        static_folder="static",
    )
    app.secret_key = "test-secret"
    app.config["TESTING"] = True
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.jinja_env.globals["ASSET_VERSION"] = "test"
    db.init_app(app)
    app.register_blueprint(access_bp)
    app.register_blueprint(auth_bp)

    @app.context_processor
    def inject_access_admin_context():
        user = session.get("user", {}) if isinstance(session.get("user"), dict) else {}
        user_email = str(user.get("email", "") or "").strip().lower()
        admin_emails = get_access_admin_emails()
        return {
            "is_access_admin": bool(user_email and user_email in admin_emails),
            "access_admin_email": ", ".join(admin_emails),
            "access_admin_emails": admin_emails,
        }

    return app


def _seed_admin_session(client):
    with client.session_transaction() as sess:
        sess["user"] = {
            "name": "Access Admin",
            "email": "njagadeesh@aziro.com",
            "authenticated": True,
        }
        sess["oauth"] = {"graph_access_token": "test-token"}


def _candidate_payload():
    return {
        "name": "Alice Example",
        "role": "Python Developer",
        "summary": {
            "attempted_rounds": 1,
            "total_rounds": 1,
            "passed_rounds": 1,
            "failed_rounds": 0,
            "overall_percentage": 92.0,
        },
        "rounds": {
            "L2": {
                "round_label": "Python Theory",
                "correct": 14,
                "total": 15,
                "percentage": 93.33,
                "pass_threshold": 70,
                "status": "PASS",
            }
        },
    }


def test_ai_settings_page_renders_for_access_admin(monkeypatch):
    app = _make_app(monkeypatch)
    with app.app_context():
        db.create_all()

    client = app.test_client()
    _seed_admin_session(client)

    response = client.get("/ai-settings")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Unified AI Settings" in body
    assert "Global Provider" in body
    assert "AI Coverage" in body


def test_provider_config_is_encrypted_in_db(monkeypatch):
    app = _make_app(monkeypatch)
    with app.app_context():
        db.create_all()
        ai_settings_service.save_global_ai_settings(
            "openai",
            api_key="sk-test-1234567890",
            default_model="gpt-4.1-mini",
            is_enabled=True,
            updated_by="admin@aziro.com",
        )

        row = db.session.get(AIProviderConfig, "openai")
        assert row is not None
        assert row.api_key_encrypted
        assert "sk-test-1234567890" not in row.api_key_encrypted
        assert row.api_key_last4 == "7890"

        provider_rows = ai_settings_service.list_provider_statuses()
        openai_row = next(item for item in provider_rows if item["provider_key"] == "openai")
        assert openai_row["runtime_source"] == "ui"
        assert openai_row["masked_key"].endswith("7890")
        assert openai_row["is_selected"] is True


def test_unified_provider_applies_to_all_ai_features(monkeypatch):
    app = _make_app(monkeypatch)
    with app.app_context():
        db.create_all()
        ai_settings_service.save_global_ai_settings(
            "openai",
            api_key="sk-openai-1234567890",
            default_model="gpt-4.1-mini",
            is_enabled=True,
            updated_by="admin@aziro.com",
        )

        for feature_key in (
            "overall_summary",
            "coding_summary",
            "consolidated_summary",
            "resume_identity",
            "jd_role_match",
        ):
            plan = ai_settings_service.resolve_feature_execution_plan(feature_key)
            assert [item["provider_key"] for item in plan["providers"]] == ["openai"]


def test_generate_evaluation_summary_uses_openai_provider_from_unified_settings(monkeypatch):
    app = _make_app(monkeypatch)
    with app.app_context():
        db.create_all()
        ai_settings_service.save_global_ai_settings(
            "openai",
            api_key="sk-openai-1234567890",
            default_model="gpt-4.1-mini",
            is_enabled=True,
            updated_by="admin@aziro.com",
        )

        monkeypatch.setattr(
            ai_generator,
            "_generate_openai_text",
            lambda api_key, model, prompt, json_mode=False, temperature=None: "OpenAI-driven overall summary.",
        )
        monkeypatch.setattr(
            ai_generator,
            "_generate_gemini_text",
            lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("Gemini should not be called")),
        )

        result = ai_generator.generate_evaluation_summary(_candidate_payload())

        assert result == "OpenAI-driven overall summary."


def test_generate_evaluation_summary_falls_back_when_selected_provider_fails(monkeypatch):
    app = _make_app(monkeypatch)
    with app.app_context():
        db.create_all()
        ai_settings_service.save_global_ai_settings(
            "openai",
            api_key="sk-openai-1234567890",
            default_model="gpt-4.1-mini",
            is_enabled=True,
            updated_by="admin@aziro.com",
        )

        monkeypatch.setattr(
            ai_generator,
            "_generate_openai_text",
            lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("invalid api key")),
        )

        result = ai_generator.generate_evaluation_summary(_candidate_payload())

        assert "Round-wise Detailed Insights" in result
        assert "Alice Example" in result


def test_resume_extraction_uses_selected_provider_for_ai_text_flow(monkeypatch):
    app = _make_app(monkeypatch)
    with app.app_context():
        db.create_all()
        ai_settings_service.save_global_ai_settings(
            "openai",
            api_key="sk-openai-1234567890",
            default_model="gpt-4.1-mini",
            is_enabled=True,
            updated_by="admin@aziro.com",
        )

        monkeypatch.setattr(
            ai_generator,
            "_generate_openai_text",
            lambda api_key, model, prompt, json_mode=False, temperature=None: (
                '{"name":"Alice Example","email":"alice@example.com","confidence_name":0.91,"confidence_email":0.93}'
            ),
        )

        payload = document_intelligence._ai_resume_extraction("Candidate profile text without a clear email header")

        assert payload is not None
        assert payload["name"] == "Alice Example"
        assert payload["email"] == "alice@example.com"


def test_selected_provider_without_ui_key_uses_fallback_mode_instead_of_env(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "env-openai-key")

    app = _make_app(monkeypatch)
    with app.app_context():
        db.create_all()
        ai_settings_service.save_global_ai_settings(
            "openai",
            api_key="",
            default_model="gpt-4.1-mini",
            is_enabled=True,
            updated_by="admin@aziro.com",
        )

        plan = ai_settings_service.resolve_feature_execution_plan("overall_summary")
        state = ai_settings_service.get_global_ai_settings_state()

        assert plan["providers"] == []
        assert state["fallback_mode"] is True


def test_unified_ai_settings_can_be_saved_from_ui(monkeypatch):
    app = _make_app(monkeypatch)
    with app.app_context():
        db.create_all()
        ai_settings_service.save_global_ai_settings(
            "gemini",
            api_key="gemini-1234567890",
            default_model="gemini-2.5-flash",
            is_enabled=True,
            updated_by="admin@aziro.com",
        )

    client = app.test_client()
    _seed_admin_session(client)

    response = client.post(
        "/ai-settings",
        data={
            "provider_key": "openai",
            "is_enabled": "1",
            "api_key": "sk-ui-1234567890",
            "default_model": "gpt-4.1-mini",
        },
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/ai-settings")
    with app.app_context():
        openai_row = db.session.get(AIProviderConfig, "openai")
        gemini_row = db.session.get(AIProviderConfig, "gemini")
        assert openai_row is not None
        assert openai_row.is_enabled is True
        assert openai_row.api_key_last4 == "7890"
        assert gemini_row is not None
        assert gemini_row.is_enabled is False
