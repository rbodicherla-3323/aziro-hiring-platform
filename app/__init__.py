from flask import Flask
from .config import Config
from .extensions import oauth

from .blueprints.auth.routes import auth_bp
from .blueprints.dashboard.routes import dashboard_bp
from .blueprints.tests.routes import tests_bp
from .blueprints.evaluation.routes import evaluation_bp


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    # Initialize OAuth
    oauth.init_app(app)

    # Register Google OAuth (EXACTLY like old project)
    oauth.register(
        name="google",
        client_id=app.config["GOOGLE_CLIENT_ID"],
        client_secret=app.config["GOOGLE_CLIENT_SECRET"],
        server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
        client_kwargs={"scope": "openid email profile"},
    )

    # Register blueprints
    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(tests_bp)
    app.register_blueprint(evaluation_bp)

        # 🔴 DEV MODE: bypass login
    if app.config.get("AUTH_DISABLED"):
        @app.before_request
        def auto_login_for_dev():
            from flask import session
            session.setdefault("logged_in", True)
            session.setdefault("username", "dev@aziro.com")


    return app
