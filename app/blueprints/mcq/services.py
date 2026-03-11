import random
import re
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
from app.services.question_bank.registry import QuestionRegistry
from app.services.question_bank.selector import (
    build_frozen_mcq_round_payload,
    should_use_enterprise_selection,
)

QUESTION_COUNT = 15
DEFAULT_DURATION_MINUTES = 20

_JAVA_QA_WORDING_REPLACEMENTS = (
    (r"\bDuring a QA test\b", "During testing"),
    (r"\bIn a QA test\b", "In testing"),
    (r"\bA QA test\b", "A Java scenario"),
    (r"\bA QA engineer\b", "An engineer"),
    (r"\bQA test\b", "Java scenario"),
    (r"\bQA automation\b", "Java automation"),
    (r"\bQA\b", "Java"),
)

_JAVA_PYTHON_WORDING_REPLACEMENTS = (
    (r"\bDjango REST Framework\b", "Spring Security"),
    (r"\bDjango ORM\b", "JPA/Hibernate ORM"),
    (r"\bFastAPI\b", "Spring WebFlux"),
    (r"\bFlask\b", "Micronaut"),
    (r"\bDjango\b", "Spring Boot"),
    (r"\bPyPI\b", "Maven Central"),
    (r"\bpip\b", "Maven"),
    (r"\bPython\b", "Java"),
)


def _apply_replacements(text, replacements):
    value = str(text or "")
    for pattern, replacement in replacements:
        value = re.sub(pattern, replacement, value, flags=re.IGNORECASE)
    return value


def _normalize_question_wording_for_role(question, role_key):
    if not isinstance(question, dict):
        return question

    if not str(role_key or "").startswith("java_"):
        return question

    normalized = dict(question)
    replacements = list(_JAVA_PYTHON_WORDING_REPLACEMENTS)
    if role_key == "java_entry":
        replacements.extend(_JAVA_QA_WORDING_REPLACEMENTS)

    normalized["question"] = _apply_replacements(normalized.get("question", ""), replacements)
    normalized["correct_answer"] = _apply_replacements(normalized.get("correct_answer", ""), replacements)
    options = normalized.get("options")
    if isinstance(options, list):
        normalized["options"] = [_apply_replacements(option, replacements) for option in options]
    return normalized


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

        if force_reset:
            clear_mcq_session_data(session_id)
            session.pop(session_key, None)

        if get_mcq_session_data(session_id):
            return

        loader = QuestionLoader(base_path="app/services/question_bank/data")
        registry = QuestionRegistry(loader)
        session_meta = MCQ_SESSION_REGISTRY.get(session_id, {})

        selected_questions = session_meta.get("selected_questions")
        if selected_questions:
            selected_questions = deepcopy(selected_questions)
        else:
            question_files = registry.get_question_files(role_key=role_key, round_key=round_key, domain=domain)
            questions = registry.get_questions(role_key=role_key, round_key=round_key, domain=domain)

            if not questions:
                raise ValueError(f"No questions found for role={role_key}, round={round_key}, domain={domain}")

            if should_use_enterprise_selection(role_key, round_key, question_files):
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
            else:
                selected_questions = random.sample(questions, min(QUESTION_COUNT, len(questions)))

        selected_questions = MCQSessionService._prepare_selected_questions(
            selected_questions=selected_questions,
            role_key=role_key,
        )

        data = {
            "questions": selected_questions,
            "answers": {},
            "start_time": int(time.time()),
            "duration_seconds": DEFAULT_DURATION_MINUTES * 60,
        }
        set_mcq_session_data(session_id, data)

        session[session_key] = {"runtime_store": True}
        session.modified = True

    @staticmethod
    def _prepare_selected_questions(selected_questions, role_key):
        prepared = prepare_question_options(selected_questions, rng=random)
        return [
            _normalize_question_wording_for_role(question, role_key)
            for question in prepared
        ]

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

        elapsed = int(time.time()) - data["start_time"]
        return max(0, data["duration_seconds"] - elapsed)

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
