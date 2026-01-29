from flask import Flask
from .config import Config

from .blueprints.auth.routes import auth_bp
from .blueprints.dashboard.routes import dashboard_bp
from .blueprints.tests.routes import tests_bp
from .blueprints.evaluation.routes import evaluation_bp

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(tests_bp)
    app.register_blueprint(evaluation_bp)

    return app
