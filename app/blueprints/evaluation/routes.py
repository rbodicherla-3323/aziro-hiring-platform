from flask import Blueprint, render_template

evaluation_bp = Blueprint("evaluation", __name__)

@evaluation_bp.route("/evaluation")
def evaluation():
    return render_template("evaluation.html")
