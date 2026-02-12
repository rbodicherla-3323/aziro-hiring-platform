from flask import Flask
from .config import Config
from .extensions import oauth

# ---------------------------
# BLUEPRINT IMPORTS
# ---------------------------
from .blueprints.auth.routes import auth_bp
from .blueprints.dashboard.routes import dashboard_bp
from .blueprints.tests.routes import tests_bp
from .blueprints.evaluation.routes import evaluation_bp
from .blueprints.reports.routes import reports_bp
from .blueprints.mcq import mcq_bp   # ✅ MCQ blueprint
from .blueprints.coding import coding_bp   # ✅ L4 Coding blueprint


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    # ---------------------------
    # OAUTH INITIALIZATION
    # ---------------------------
    oauth.init_app(app)

    oauth.register(
        name="google",
        client_id=app.config.get("GOOGLE_CLIENT_ID"),
        client_secret=app.config.get("GOOGLE_CLIENT_SECRET"),
        server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
        client_kwargs={"scope": "openid email profile"},
    )

    # ---------------------------
    # REGISTER BLUEPRINTS
    # ---------------------------
    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(tests_bp)
    app.register_blueprint(evaluation_bp)
    app.register_blueprint(reports_bp)
    app.register_blueprint(mcq_bp)   # ✅ MCQ ROUTES ENABLED
    app.register_blueprint(coding_bp)   # ✅ L4 CODING ROUTES ENABLED
    # ---------------------------
    # DEV MODE: BYPASS LOGIN
    # ---------------------------
    if app.config.get("AUTH_DISABLED"):
        @app.before_request
        def auto_login_for_dev():
            from flask import session
            session.setdefault("logged_in", True)
            session.setdefault("username", "dev@aziro.com")

    return app
