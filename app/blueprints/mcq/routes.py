from flask import render_template, redirect, url_for, request, session
from . import mcq_bp

from app.services.mcq_session_registry import MCQ_SESSION_REGISTRY
from .services import MCQSessionService
from app.services.evaluation_service import EvaluationService


# -------------------------------------------------
# START PAGE
# -------------------------------------------------
@mcq_bp.route("/start/<session_id>")
def start_test(session_id):

    session_meta = MCQ_SESSION_REGISTRY.get(session_id)
    if not session_meta:
        return "Invalid or expired test link", 404

    # ✅ PERMANENT FIX: RESET OLD SESSION (browser-safe)
    session_key = f"mcq_{session_id}"
    if session_key in session:
        session.pop(session_key)

    MCQSessionService.init_session(
        session_id=session_id,
        role_key=session_meta["role_key"],
        round_key=session_meta["round_key"],
        domain=session_meta.get("domain")
    )

    return render_template(
        "mcq/start.html",
        test={
            "session_id": session_id,
            "round_name": session_meta["round_label"],
            "total_questions": MCQSessionService.total_questions(session_id),
            "time_minutes": 20
        },
        candidate_name=session_meta["candidate_name"]
    )


# -------------------------------------------------
# BEGIN TEST
# -------------------------------------------------
@mcq_bp.route("/begin/<session_id>", methods=["POST"])
def begin_test(session_id):
    return redirect(
        url_for("mcq.question", session_id=session_id, q=0)
    )


# -------------------------------------------------
# QUESTION PAGE (ONE QUESTION AT A TIME)
# -------------------------------------------------
@mcq_bp.route("/question/<session_id>", methods=["GET", "POST"])
def question(session_id):

    session_meta = MCQ_SESSION_REGISTRY.get(session_id)
    if not session_meta:
        return "Invalid or expired test link", 404

    q_index = int(request.args.get("q", 0))

    question = MCQSessionService.get_question(session_id, q_index)
    if not question:
        return redirect(
            url_for("mcq.submit", session_id=session_id)
        )

    if request.method == "POST":
        MCQSessionService.save_answer(
            session_id,
            q_index,
            request.form.get("answer")
        )

        return redirect(
            url_for("mcq.question", session_id=session_id, q=q_index + 1)
        )

    return render_template(
        "mcq/question.html",
        question=question,
        q_index=q_index,
        total_questions=MCQSessionService.total_questions(session_id),
        remaining_seconds=MCQSessionService.remaining_time(session_id),
        session_id=session_id,
        candidate_name=session_meta["candidate_name"]
    )


# -------------------------------------------------
# SUBMIT CONFIRMATION
# -------------------------------------------------
@mcq_bp.route("/submit/<session_id>", methods=["GET", "POST"])
def submit(session_id):

    if request.method == "POST":
        # ✅ Evaluate only ONCE here
        EvaluationService.evaluate_mcq(session_id)

        return redirect(
            url_for("mcq.completed", session_id=session_id)
        )

    return render_template("mcq/submit.html")


# -------------------------------------------------
# COMPLETION PAGE
# -------------------------------------------------
@mcq_bp.route("/completed/<session_id>")
def completed(session_id):
    return render_template("mcq/completed.html")
