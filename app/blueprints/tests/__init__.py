# filepath: d:\Projects\aziro-hiring-platform\app\blueprints\tests\__init__.py
from flask import Blueprint

tests_bp = Blueprint("tests", __name__)

from . import routes  # noqa: E402, F401
