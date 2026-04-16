import random
import time
from copy import deepcopy

from flask import session

from app.services.mcq_runtime_store import (
    clear_mcq_session_data,
    get_mcq_session_data,
    mcq_session_key,
    set_mcq_session_data,
)
from app.services.mcq_session_registry import MCQ_SESSION_REGISTRY
from app.services.question_bank.helpers import prepare_question_options
from app.services.question_bank.loader import QuestionLoader
from app.services.question_bank.loader import sanitize_question_record
from app.services.question_bank.registry import QuestionRegistry
from app.services.question_bank.selector import (
    build_frozen_mcq_round_payload,
    should_use_enterprise_selection,
)

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
    def init_session(session_id, role_key, round_key, domain=None, force_reset=False):
        session_key = mcq_session_key(session_id)
        existing = get_mcq_session_data(session_id)

        if force_reset:
            if existing:
                session[session_key] = {"runtime_store": True}
                session.modified = True
                return
            session.pop(session_key, None)

        if existing:
            session[session_key] = {"runtime_store": True}
            session.modified = True
            return

        loader = QuestionLoader(base_path="app/services/question_bank/data")
        registry = QuestionRegistry(loader)
        session_meta = MCQ_SESSION_REGISTRY.get(session_id, {})
        force_non_enterprise = bool(session_meta.get("force_non_enterprise_selection"))

        selected_questions = session_meta.get("selected_questions")
        source_file = None
        if selected_questions:
            selected_questions = deepcopy(selected_questions)
            files = session_meta.get("question_bank_files") or []
            if not files:
                files = registry.get_question_files(role_key=role_key, round_key=round_key, domain=domain)
            if files:
                source_file = files[0]
        else:
            question_files = registry.get_question_files(role_key=role_key, round_key=round_key, domain=domain)
            questions = registry.get_questions(role_key=role_key, round_key=round_key, domain=domain)
            if question_files:
                source_file = question_files[0]

            if not questions:
                raise ValueError(f"No questions found for role={role_key}, round={round_key}, domain={domain}")

            if (not force_non_enterprise) and should_use_enterprise_selection(role_key, round_key, question_files):
                try:
                    frozen_payload = build_frozen_mcq_round_payload(
                        role_key=role_key,
                        round_key=round_key,
                        question_files=question_files,
                        questions=questions,
                        rng=random.Random(),
                    )
                    session_meta.update(frozen_payload)
                    MCQ_SESSION_REGISTRY[session_id] = session_meta
                    selected_questions = deepcopy(frozen_payload["selected_questions"])
                except Exception:
                    # Graceful runtime fallback keeps existing links usable even if
                    # strict enterprise validation/select rules fail.
                    selected_questions = random.sample(questions, min(QUESTION_COUNT, len(questions)))
            else:
                selected_questions = random.sample(questions, min(QUESTION_COUNT, len(questions)))

        if source_file:
            selected_questions = [sanitize_question_record(question, relative_path=source_file) for question in selected_questions]

        selected_questions = MCQSessionService._prepare_selected_questions(selected_questions)

        data = {
            "questions": selected_questions,
            "answers": {},
            # Timer starts only when candidate actually begins the test.
            "start_time": 0,
            "duration_seconds": DEFAULT_DURATION_MINUTES * 60,
        }
        set_mcq_session_data(session_id, data)

        session[session_key] = {"runtime_store": True}
        session.modified = True

    @staticmethod
    def _prepare_selected_questions(selected_questions):
        return prepare_question_options(selected_questions, rng=random)

    @staticmethod
    def get_question(session_id, index):
        data = MCQSessionService.get_session_data(session_id)
        if not data:
            return None

        if index >= len(data["questions"]):
            return None

        return data["questions"][index]

    @staticmethod
    def save_answer(session_id, index, answer):
        data = MCQSessionService.get_session_data(session_id)
        if not data:
            return

        data["answers"][str(index)] = answer
        set_mcq_session_data(session_id, data)
        session.modified = True

    @staticmethod
    def get_answer(session_id, index):
        data = MCQSessionService.get_session_data(session_id)
        if not data:
            return None

        return data["answers"].get(str(index))

    @staticmethod
    def total_questions(session_id):
        data = MCQSessionService.get_session_data(session_id)
        return len(data["questions"]) if data else 0

    @staticmethod
    def remaining_time(session_id):
        data = MCQSessionService.get_session_data(session_id)
        if not data:
            return 0

        start_time = int(data.get("start_time", 0) or 0)
        if not start_time:
            return data["duration_seconds"]

        elapsed = max(0, int(time.time()) - start_time)
        return max(0, data["duration_seconds"] - elapsed)

    @staticmethod
    def start_timer(session_id, force_reset=False):
        """Start timer on first candidate entry; optionally reset stale start times."""
        data = MCQSessionService.get_session_data(session_id)
        if not data:
            return 0

        current_start = int(data.get("start_time", 0) or 0)
        if force_reset or not current_start:
            data["start_time"] = int(time.time())
            if int(data.get("duration_seconds", 0) or 0) <= 0:
                data["duration_seconds"] = DEFAULT_DURATION_MINUTES * 60
            set_mcq_session_data(session_id, data)
            session.modified = True

        return MCQSessionService.remaining_time(session_id)

    @staticmethod
    def get_session_data(session_id):
        session_key = mcq_session_key(session_id)
        data = get_mcq_session_data(session_id)
        if data:
            return data

        legacy = session.get(session_key)
        if isinstance(legacy, dict) and "questions" in legacy and "answers" in legacy:
            set_mcq_session_data(session_id, legacy)
            return legacy
        return None

    @staticmethod
    def clear_session(session_id):
        session_key = mcq_session_key(session_id)
        clear_mcq_session_data(session_id)
        session.pop(session_key, None)
        session.modified = True
