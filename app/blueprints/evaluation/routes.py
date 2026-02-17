# filepath: d:\Projects\aziro-hiring-platform\app\blueprints\evaluation\routes.py
"""
Evaluation page — scoped to current user's today session candidates.
"""
from flask import render_template, request, session

from . import evaluation_bp
from app.utils.auth_decorator import login_required
from app.services.generated_tests_store import get_tests_for_user_today
from app.services.evaluation_aggregator import EvaluationAggregator
from app.services.evaluation_service import EvaluationService, ROUND_PASS_PERCENTAGE, DEFAULT_PASS_PERCENTAGE


@evaluation_bp.route("/evaluation", methods=["GET", "POST"])
@login_required
def evaluation():
    user = session.get("user", {})
    user_email = user.get("email", "dev@aziro.com")

    # Get today's candidates for this user
    user_tests = get_tests_for_user_today(user_email)
    user_emails = {t["email"] for t in user_tests}

    # Get all evaluated candidates
    all_candidates = EvaluationAggregator.get_candidates()

    # Filter to only this user's today session candidates
    candidates = [c for c in all_candidates if c["email"] in user_emails]

    # Handle POST: filter to selected candidates
    selected_emails = []
    filtered_candidates = []

    if request.method == "POST":
        selected_emails = request.form.getlist("candidates")
        filtered_candidates = [c for c in candidates if c["email"] in selected_emails]

    return render_template(
        "evaluation.html",
        candidates=candidates,
        selected_emails=selected_emails,
        filtered_candidates=filtered_candidates,
        pass_thresholds=ROUND_PASS_PERCENTAGE,
        default_threshold=DEFAULT_PASS_PERCENTAGE,
    )
