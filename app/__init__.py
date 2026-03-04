import os
from flask import Flask
from dotenv import load_dotenv

load_dotenv()

from .extensions import db, migrate
from .blueprints.dashboard import dashboard_bp
from .blueprints.mcq import mcq_bp
from .blueprints.tests import tests_bp
from .blueprints.evaluation import evaluation_bp
from .blueprints.coding import coding_bp
from .blueprints.reports import reports_bp
from .blueprints.auth import auth_bp


def create_app():
    app = Flask(__name__)
    app.secret_key = os.getenv("SECRET_KEY", "default-secret-key")

    # Database configuration
    app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv(
        "DATABASE_URL",
        "sqlite:///" + os.path.join(
            os.path.abspath(os.path.dirname(__file__)), "..", "instance", "aziro_hiring.db"
        )
    )
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["SESSION_PERMANENT"] = True

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

    # ── Permissions-Policy / Feature-Policy headers ──
    @app.after_request
    def set_permissions_policy(response):
        response.headers["Permissions-Policy"] = (
            "display-capture=(self), camera=(self), microphone=(self), fullscreen=(self)"
        )
        response.headers["Feature-Policy"] = (
            "display-capture 'self'; camera 'self'; microphone 'self'; fullscreen 'self'"
        )
        return response    # Create DB tables
    with app.app_context():
        from . import models  # noqa: F401
        db.create_all()

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

    return app