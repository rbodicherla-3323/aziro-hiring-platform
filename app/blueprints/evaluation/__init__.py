from flask import Blueprint

evaluation_bp = Blueprint("evaluation", __name__)
from . import routes
