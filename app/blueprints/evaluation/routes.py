from flask import render_template, request, jsonify
from . import evaluation_bp
from app.services.evaluation_aggregator import EvaluationAggregator
from app.services.evaluation_service import ROUND_PASS_PERCENTAGE, DEFAULT_PASS_PERCENTAGE


@evaluation_bp.route("/evaluation", methods=["GET", "POST"])
def evaluation():

    all_candidates = EvaluationAggregator.get_candidates()

    selected_emails = []
    filtered_candidates = []

    if request.method == "POST":
        selected_emails = request.form.getlist("candidates")

        filtered_candidates = [
            c for c in all_candidates
            if c["email"] in selected_emails
        ]

    return render_template(
        "evaluation.html",
        candidates=all_candidates,
        selected_emails=selected_emails,
        filtered_candidates=filtered_candidates,
        pass_thresholds=ROUND_PASS_PERCENTAGE,
        default_threshold=DEFAULT_PASS_PERCENTAGE
    )
