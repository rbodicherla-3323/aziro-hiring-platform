from flask import Blueprint

coding_bp = Blueprint(
    "coding",
    __name__,
    url_prefix="/coding"
)

from . import routes
