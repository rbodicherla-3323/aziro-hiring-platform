import os
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask

from .access_config import get_access_admin_emails

# Always load project-level .env regardless of launch working directory.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")
load_dotenv(PROJECT_ROOT / ".env.production", override=True)

from .extensions import db, migrate
from .blueprints.dashboard import dashboard_bp
from .blueprints.mcq import mcq_bp
from .blueprints.tests import tests_bp
from .blueprints.evaluation import evaluation_bp
from .blueprints.coding import coding_bp
from .blueprints.reports import reports_bp
from .blueprints.auth import auth_bp
from .blueprints.access import access_bp


def create_app():
    app = Flask(__name__)
    app.secret_key = os.getenv("SECRET_KEY", "default-secret-key")

    # Database configuration
    database_url = (os.getenv("DATABASE_URL") or "").strip()
    if database_url:
        # Accept both postgresql:// and legacy postgres://
        if database_url.startswith("postgres://"):
            database_url = "postgresql://" + database_url[len("postgres://") :]

        if not database_url.startswith("postgresql://"):
            scheme = database_url.split(":", 1)[0]
            raise RuntimeError(
                f"DATABASE_URL must be a Postgres DSN (postgresql://...). Got: {scheme}://"
            )

        # Server (nginx) uses Postgres.
        app.config["SQLALCHEMY_DATABASE_URI"] = database_url
    else:
        # Local dev convenience: allow running without Postgres by falling back to SQLite.
        sqlite_path = Path(app.instance_path) / "aziro_hiring.sqlite3"
        sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{sqlite_path.as_posix()}"

    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["SESSION_PERMANENT"] = True
    proctoring_env = os.getenv("PROCTORING_ENABLED", "").strip().lower()
    app.config["PROCTORING_ENABLED"] = proctoring_env in {"1", "true", "yes", "on"}

    # Initialize extensions
    db.init_app(app)
    migrate.init_app(app, db)

    # Register blueprints
    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(mcq_bp)
    app.register_blueprint(tests_bp)
    app.register_blueprint(evaluation_bp)
    app.register_blueprint(coding_bp)
    app.register_blueprint(reports_bp)
    app.register_blueprint(access_bp)

    @app.context_processor
    def inject_access_admin_context():
        from flask import session

        user = session.get("user", {}) if isinstance(session.get("user"), dict) else {}
        user_email = str(user.get("email", "") or "").strip().lower()
        admin_emails = get_access_admin_emails()
        admin_display = ", ".join(admin_emails)
        return {
            "is_access_admin": bool(user_email and user_email in admin_emails),
            "access_admin_email": admin_display,
            "access_admin_emails": admin_emails,
        }

    @app.before_request
    def purge_expired_test_candidate_data():
        from flask import request as req

        if req.path.startswith("/static"):
            return
        try:
            from .services.test_candidate_cleanup import purge_expired_test_candidates
            purge_expired_test_candidates()
        except Exception:
            app.logger.exception("Failed to purge expired Test_ candidate data")

    # -- Permissions-Policy / Feature-Policy headers --
    @app.after_request
    def set_permissions_policy(response):
        response.headers["Permissions-Policy"] = (
            "display-capture=(self), camera=(self), microphone=(self), fullscreen=(self)"
        )
        response.headers["Feature-Policy"] = (
            "display-capture 'self'; camera 'self'; microphone 'self'; fullscreen 'self'"
        )
        return response

    # Create DB tables
    with app.app_context():
        from . import models  # noqa: F401
        from .services.access_approvals_service import ensure_access_approvals_schema

        db.create_all()
        try:
            ensure_access_approvals_schema()
        except Exception:
            app.logger.exception("Failed to ensure access approvals schema")

    # Inject asset version into all templates for cache busting
    from .config import Config

    app.jinja_env.globals["ASSET_VERSION"] = Config.ASSET_VERSION

    # Dev mode: Bypass login for local testing
    # Activates when AUTH_DISABLED=true  **or**  when Azure AD creds are
    # still the placeholder values (i.e. .env was never customised / is missing).
    auth_disabled_env = os.getenv("AUTH_DISABLED", "").lower() == "true"
    azure_client_id = os.getenv("AZURE_CLIENT_ID", "")
    azure_unconfigured = (
        not azure_client_id
        or azure_client_id == "your-azure-client-id"
    )
    dev_bypass = auth_disabled_env or azure_unconfigured

    if dev_bypass:
        @app.before_request
        def auto_login_for_dev():
            from flask import session, request as req
            # Skip bypass for static files
            if req.path.startswith("/static"):
                return
            if not session.get("user"):
                session["user"] = {
                    "name": "Dev User",
                    "email": "dev@aziro.com",
                    "authenticated": True
                }
    else:
        @app.before_request
        def clear_stale_dev_bypass_session():
            from flask import session

            user = session.get("user")
            if not isinstance(user, dict):
                return
            if (
                user.get("email") == "dev@aziro.com"
                and user.get("name") == "Dev User"
                and "oauth" not in session
            ):
                session.clear()
    return app

