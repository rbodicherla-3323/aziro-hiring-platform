from authlib.integrations.flask_client import OAuth
import os

DB_ENABLED = True
try:
    from flask_sqlalchemy import SQLAlchemy
    from flask_migrate import Migrate
except ModuleNotFoundError:
    DB_ENABLED = False

    class SQLAlchemy:  # type: ignore[override]
        def init_app(self, app):
            app.logger.warning(
                "Flask-SQLAlchemy is not installed. DB-backed features are disabled."
            )

    class Migrate:  # type: ignore[override]
        def init_app(self, app, db):
            app.logger.warning(
                "Flask-Migrate is not installed. Migration features are disabled."
            )

oauth = OAuth()
db = SQLAlchemy()
migrate = Migrate()


def init_oauth(app):
    oauth.init_app(app)
    oauth.register(
        name="google",
        client_id=os.getenv("GOOGLE_CLIENT_ID"),
        client_secret=os.getenv("GOOGLE_CLIENT_SECRET"),
        server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
        client_kwargs={"scope": "openid email profile"}
    )
    return oauth
