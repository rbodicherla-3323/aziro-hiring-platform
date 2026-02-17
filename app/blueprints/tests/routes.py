# filepath: d:\Projects\aziro-hiring-platform\app\blueprints\tests\routes.py
"""
Generated Tests listing — scoped to current user's today session.
"""
from flask import render_template, session

from . import tests_bp
from app.utils.auth_decorator import login_required
from app.services.generated_tests_store import get_tests_for_user_today


@tests_bp.route("/generated-tests")
@login_required
def generated_tests():
    user = session.get("user", {})
    user_email = user.get("email", "dev@aziro.com")

    candidates = get_tests_for_user_today(user_email)

    return render_template(
        "generated_tests.html",
        candidates=candidates,
    )
