from flask import render_template, request
from . import evaluation_bp
from app.services.evaluation_aggregator import EvaluationAggregator


@evaluation_bp.route("/evaluation", methods=["GET", "POST"])
def evaluation():

    candidates = EvaluationAggregator.get_candidates()
    selected_emails = []

    if request.method == "POST":
        selected_emails = request.form.getlist("candidates")

        candidates = [
            c for c in candidates
            if c["email"] in selected_emails
        ]

    return render_template(
        "evaluation.html",
        candidates=candidates,
        selected_emails=selected_emails
    )
