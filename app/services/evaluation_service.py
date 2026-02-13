from app.services.evaluation_store import EVALUATION_STORE
from app.services.mcq_session_registry import MCQ_SESSION_REGISTRY
from flask import session
import time


class EvaluationService:

    @staticmethod
    def evaluate_mcq(session_id: str):

        mcq_key = f"mcq_{session_id}"
        mcq_data = session.get(mcq_key)
        session_meta = MCQ_SESSION_REGISTRY.get(session_id)

        if not session_meta:
            return

        # Candidate never opened test
        if not mcq_data:
            EVALUATION_STORE[session_id] = {
                "candidate_name": session_meta["candidate_name"],
                "email": session_meta["email"],
                "round_key": session_meta["round_key"],
                "round_label": session_meta["round_label"],
                "total_questions": 15,
                "attempted": 0,
                "correct": 0,
                "percentage": 0,
                "status": "FAIL",
                "time_taken_seconds": 0
            }
            return

        questions = mcq_data["questions"]
        answers = mcq_data["answers"]

        correct = 0
        attempted = len(answers)

        for idx, q in enumerate(questions):

            if str(idx) not in answers:
                continue

            selected_value = answers[str(idx)]
            correct_value = q.get("correct_answer")

            # ✅ Correct comparison for YOUR JSON structure
            if selected_value == correct_value:
                correct += 1

        total_questions = len(questions)

        percentage = (
            round((correct / total_questions) * 100, 2)
            if total_questions > 0 else 0
        )

        status = "PASS" if percentage >= 70 else "FAIL"

        # Calculate time taken
        start_time = mcq_data.get("start_time", 0)
        time_taken = int(time.time()) - start_time

        EVALUATION_STORE[session_id] = {
            "candidate_name": session_meta["candidate_name"],
            "email": session_meta["email"],
            "round_key": session_meta["round_key"],
            "round_label": session_meta["round_label"],
            "total_questions": total_questions,
            "attempted": attempted,
            "correct": correct,
            "percentage": percentage,
            "status": status,
            "time_taken_seconds": time_taken
        }
