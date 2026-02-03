from flask import render_template, redirect, url_for, request
from . import mcq_bp


# -------------------------------------------------
# STEP 5: INSTRUCTION PAGE
# -------------------------------------------------
@mcq_bp.route("/start/<session_id>", methods=["GET"])
def start_test(session_id):
    """
    MCQ Instruction Page
    """

    # Temporary static data (backend will plug later)
    test_info = {
        "session_id": session_id,
        "role": "Python Developer",
        "round_name": "L2 – Python Theory",
        "total_questions": 15,
        "time_minutes": 20
    }

    return render_template(
        "mcq/start.html",
        test=test_info
    )


@mcq_bp.route("/begin/<session_id>", methods=["POST"])
def begin_test(session_id):
    """
    Redirect to first question
    """
    return redirect(
        url_for("mcq.question", session_id=session_id, q=0)
    )


# -------------------------------------------------
# STEP 6: QUESTION PAGE (ONE QUESTION AT A TIME)
# -------------------------------------------------
@mcq_bp.route("/question/<session_id>", methods=["GET", "POST"])
def question(session_id):
    """
    Single MCQ Question Page
    """

    # -------------------------------------------------
    # TEMP STATIC QUESTIONS (will be replaced by engine)
    # -------------------------------------------------
    questions = [
        {
            "id": 1,
            "text": "Which Python framework is best suited for large monolithic applications?",
            "options": ["Flask", "FastAPI", "Django", "Bottle"]
        },
        {
            "id": 2,
            "text": "Which keyword is used to create a generator in Python?",
            "options": ["return", "yield", "async", "await"]
        },
        {
            "id": 3,
            "text": "Which data structure maintains insertion order by default in Python 3.7+?",
            "options": ["set", "tuple", "dict", "list"]
        }
    ]

    total_questions = len(questions)

    # -------------------------------------------------
    # CURRENT QUESTION INDEX
    # -------------------------------------------------
    q_index = int(request.args.get("q", 0))

    # Safety check: if completed
    if q_index >= total_questions:
        return redirect(
            url_for("mcq.submit", session_id=session_id)
        )

    current_question = questions[q_index]

    # -------------------------------------------------
    # HANDLE ANSWER SUBMIT
    # -------------------------------------------------
    if request.method == "POST":
        # Later: store answer in session/DB
        next_q = q_index + 1
        return redirect(
            url_for("mcq.question", session_id=session_id, q=next_q)
        )

    return render_template(
        "mcq/question.html",
        session_id=session_id,
        question=current_question,
        q_index=q_index,
        total_questions=total_questions
    )


# -------------------------------------------------
# STEP 7: SUBMIT CONFIRMATION PAGE
# -------------------------------------------------
@mcq_bp.route("/submit/<session_id>", methods=["GET", "POST"])
def submit(session_id):
    """
    Final submit confirmation page
    """

    if request.method == "POST":
        # Later: finalize answers, score, persist, etc.
        return redirect(
            url_for("mcq.completed", session_id=session_id)
        )

    return render_template(
        "mcq/submit.html",
        session_id=session_id
    )


# -------------------------------------------------
# STEP 7: COMPLETION PAGE
# -------------------------------------------------
@mcq_bp.route("/completed/<session_id>", methods=["GET"])
def completed(session_id):
    """
    Test completed page
    """
    return render_template(
        "mcq/completed.html",
        session_id=session_id
    )
