from app.services.evaluation_store import EVALUATION_STORE
from app.services.mcq_session_registry import MCQ_SESSION_REGISTRY
from flask import session


class EvaluationService:

    @staticmethod
    def evaluate_mcq(session_id: str):

        mcq_key = f"mcq_{session_id}"
        mcq_data = session.get(mcq_key)

        session_meta = MCQ_SESSION_REGISTRY.get(session_id)

        # Candidate never opened / session expired
        if not mcq_data or not session_meta:
            EVALUATION_STORE[session_id] = {
                "candidate_name": session_meta["candidate_name"] if session_meta else "Unknown",
                "email": session_meta["email"] if session_meta else "",
                "role_key": session_meta["role_key"] if session_meta else "",
                "round_key": session_meta["round_key"] if session_meta else "",
                "round_label": session_meta["round_label"] if session_meta else "",
                "total_questions": 15,
                "attempted": 0,
                "correct": 0,
                "percentage": 0,
                "submitted_in_time": False
            }
            return

        questions = mcq_data["questions"]
        answers = mcq_data["answers"]

        correct = 0
        attempted = len(answers)

        for idx, q in enumerate(questions):
            if str(idx) in answers:
                if answers[str(idx)] == q.get("answer"):
                    correct += 1

        percentage = round((correct / len(questions)) * 100, 2)

        EVALUATION_STORE[session_id] = {
            "candidate_name": session_meta["candidate_name"],
            "email": session_meta["email"],
            "role_key": session_meta["role_key"],
            "round_key": session_meta["round_key"],
            "round_label": session_meta["round_label"],
            "total_questions": len(questions),
            "attempted": attempted,
            "correct": correct,
            "percentage": percentage,
            "submitted_in_time": True
        }
