import os
from flask import Flask, request
from dotenv import load_dotenv
from werkzeug.middleware.proxy_fix import ProxyFix

load_dotenv()

from .extensions import db, migrate
from .blueprints.dashboard import dashboard_bp
from .blueprints.mcq import mcq_bp
from .blueprints.tests import tests_bp
from .blueprints.evaluation import evaluation_bp
from .blueprints.coding import coding_bp
from .blueprints.reports import reports_bp
from .blueprints.auth import auth_bp


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def create_app():
    app = Flask(__name__)
    # Trust reverse-proxy headers (Nginx) so request.scheme/request.host
    # reflect the external URL (e.g. https://<vm-ip>) instead of upstream HTTP.
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1)
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
    # Keep proctoring optional while migration/deployment stabilizes.
    app.config["PROCTORING_ENABLED"] = _env_bool("PROCTORING_ENABLED", default=False)

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

    # ── Permissions-Policy & Security Headers ─────────────────────────
    # Browsers block getDisplayMedia() (screen sharing), getUserMedia()
    # (webcam), and requestFullscreen() unless the correct Permissions-Policy
    # headers are present.  This is especially critical when the app is
    # served over plain HTTP on a LAN IP (not localhost / not HTTPS).
    @app.after_request
    def set_permissions_headers(response):
        response.headers["Permissions-Policy"] = (
            "display-capture=(self), "
            "camera=(self), "
            "microphone=(self), "
            "fullscreen=(self)"
        )
        # Feature-Policy is the older name — some browsers still check it
        response.headers["Feature-Policy"] = (
            "display-capture 'self'; "
            "camera 'self'; "
            "microphone 'self'; "
            "fullscreen 'self'"
        )
        # Prevent stale exam screens and bfcache artifacts on manual refresh.
        if request.path.startswith("/mcq/") or request.path.startswith("/coding/"):
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        return response

    @app.context_processor
    def inject_runtime_flags():
        return {
            "proctoring_enabled": bool(app.config.get("PROCTORING_ENABLED", False)),
        }

    # Create DB tables
    with app.app_context():
        from . import models  # noqa: F401
        db.create_all()

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
