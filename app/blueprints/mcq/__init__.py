from flask import Blueprint

mcq_bp = Blueprint(
    "mcq",
    __name__,
    url_prefix="/mcq"
)

from . import routes
