import time
import random
from flask import session

from app.services.question_bank.loader import QuestionLoader
from app.services.question_bank.registry import QuestionRegistry

QUESTION_COUNT = 15
DEFAULT_DURATION_MINUTES = 20


class MCQSessionService:
    """
    Handles MCQ session lifecycle:
    - loads correct questions per role & round
    - randomizes questions
    - stores answers
    - enforces timer
    """

    @staticmethod
    def init_session(session_id, role_key, round_key, domain=None):
        session_key = f"mcq_{session_id}"

        # ✅ Do not recreate session
        if session_key in session:
            return

        loader = QuestionLoader(
            base_path="app/services/question_bank/data"
        )
        registry = QuestionRegistry(loader)

        # ✅ THIS IS THE ONLY SOURCE OF QUESTIONS
        questions = registry.get_questions(
            role_key=role_key,
            round_key=round_key,
            domain=domain
        )

        if not questions:
            raise ValueError(
                f"No questions found for role={role_key}, round={round_key}, domain={domain}"
            )

        selected_questions = random.sample(
            questions,
            min(QUESTION_COUNT, len(questions))
        )

        session[session_key] = {
            "questions": selected_questions,
            "answers": {},
            "start_time": int(time.time()),
            "duration_seconds": DEFAULT_DURATION_MINUTES * 60
        }

    @staticmethod
    def get_question(session_id, index):
        data = session.get(f"mcq_{session_id}")
        if not data:
            return None

        if index >= len(data["questions"]):
            return None

        return data["questions"][index]

    @staticmethod
    def save_answer(session_id, index, answer):
        data = session.get(f"mcq_{session_id}")
        if not data:
            return

        data["answers"][str(index)] = answer
        session.modified = True

    @staticmethod
    def get_answer(session_id, index):
        data = session.get(f"mcq_{session_id}")
        if not data:
            return None

        return data["answers"].get(str(index))

    @staticmethod
    def total_questions(session_id):
        data = session.get(f"mcq_{session_id}")
        return len(data["questions"]) if data else 0

    @staticmethod
    def remaining_time(session_id):
        data = session.get(f"mcq_{session_id}")
        if not data:
            return 0

        elapsed = int(time.time()) - data["start_time"]
        return max(0, data["duration_seconds"] - elapsed)
