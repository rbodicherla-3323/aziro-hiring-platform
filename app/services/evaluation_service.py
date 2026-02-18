from app.services.evaluation_store import EVALUATION_STORE
from app.services.mcq_session_registry import MCQ_SESSION_REGISTRY
from app.services.ai_generator import generate_evaluation_summary
from flask import session
import logging
import time

log = logging.getLogger(__name__)


# ---------------------------------------------------------------
# Per-round pass percentage thresholds
# ---------------------------------------------------------------
# Aptitude (L1)       → 60%  (general reasoning, slightly lenient)
# Technical Theory    → 70%  (core knowledge, standard bar)
# Technical Practical → 70%  (applied knowledge, standard bar)
# Soft Skills (L5)    → 50%  (subjective, more lenient)
# Domain (L6)         → 65%  (specialized but not core)
# ---------------------------------------------------------------
ROUND_PASS_PERCENTAGE = {
    "L1": 60,   # Aptitude – logical/quantitative reasoning
    "L2": 70,   # Technical Theory
    "L3": 70,   # Technical Fundamentals / Practical
    "L5": 50,   # Soft Skills – subjective, keep lenient
    "L6": 65,   # Domain-specific knowledge
}

DEFAULT_PASS_PERCENTAGE = 70


class EvaluationService:

    @staticmethod
    def get_pass_threshold(round_key: str) -> int:
        """Return the pass percentage for a given round."""
        return ROUND_PASS_PERCENTAGE.get(round_key, DEFAULT_PASS_PERCENTAGE)

    @staticmethod
    def evaluate_mcq(session_id: str):

        mcq_key = f"mcq_{session_id}"
        mcq_data = session.get(mcq_key)
        session_meta = MCQ_SESSION_REGISTRY.get(session_id)

        if not session_meta:
            return

        round_key = session_meta["round_key"]
        pass_threshold = EvaluationService.get_pass_threshold(round_key)        # Candidate never opened test
        if not mcq_data:
            result_data = {
                "candidate_name": session_meta["candidate_name"],
                "email": session_meta["email"],
                "round_key": round_key,
                "round_label": session_meta["round_label"],
                "total_questions": 15,
                "attempted": 0,
                "correct": 0,
                "percentage": 0,
                "pass_threshold": pass_threshold,
                "status": "FAIL",
                "time_taken_seconds": 0
            }
            EVALUATION_STORE[session_id] = result_data
            EvaluationService._persist_result_to_db(session_meta, result_data)
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

        status = "PASS" if percentage >= pass_threshold else "FAIL"

        # Calculate time taken
        start_time = mcq_data.get("start_time", 0)
        time_taken = int(time.time()) - start_time

        EVALUATION_STORE[session_id] = {
            "candidate_name": session_meta["candidate_name"],
            "email": session_meta["email"],
            "round_key": round_key,
            "round_label": session_meta["round_label"],
            "total_questions": total_questions,
            "attempted": attempted,
            "correct": correct,
            "percentage": percentage,
            "pass_threshold": pass_threshold,
            "status": status,
            "time_taken_seconds": time_taken
        }

        # -------------------------------------------------
        # Generate AI summary for the evaluation result
        # -------------------------------------------------
        result_data["ai_summary"] = generate_evaluation_summary({
            "candidate_name": session_meta["candidate_name"],
            "round_label": session_meta["round_label"],
            "total_questions": total_questions,
            "attempted": attempted,
            "correct": correct,
            "percentage": percentage,
            "pass_threshold": pass_threshold,
            "status": status
        })

        EVALUATION_STORE[session_id] = result_data

        # -------------------------------------------------
        # PERSIST to DB (best-effort, non-blocking)
        # -------------------------------------------------
        EvaluationService._persist_result_to_db(session_meta, {
            "round_key": round_key,
            "round_label": session_meta["round_label"],
            "total_questions": total_questions,
            "attempted": attempted,
            "correct": correct,
            "percentage": percentage,
            "pass_threshold": pass_threshold,
            "status": status,
            "time_taken_seconds": time_taken,
        })

    @staticmethod
    def _persist_result_to_db(session_meta: dict, result: dict):
        """Write a round result row into the database."""
        try:
            from app.services import db_service

            batch_id = session_meta.get("batch_id", "")
            email = session_meta.get("email", "")
            name = session_meta.get("candidate_name", "")

            if not batch_id or not email:
                return

            candidate = db_service.get_or_create_candidate(name, email)
            ts = db_service.get_or_create_test_session(
                candidate_id=candidate.id,
                role_key=session_meta.get("role_key", ""),
                role_label=session_meta.get("role_label", ""),
                batch_id=batch_id,
            )
            db_service.save_round_result(
                test_session_id=ts.id,
                round_key=result["round_key"],
                round_label=result["round_label"],
                total_questions=result["total_questions"],
                attempted=result["attempted"],
                correct=result["correct"],
                percentage=result["percentage"],
                pass_threshold=result["pass_threshold"],
                status=result["status"],
                time_taken_seconds=result.get("time_taken_seconds", 0),
            )
        except Exception as exc:
            log.warning("DB persist failed for round result: %s", exc)
