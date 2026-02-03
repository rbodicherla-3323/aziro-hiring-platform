from datetime import datetime, timezone
from typing import List, Dict, Optional
import uuid


class TestSessionError(Exception):
    pass


class TestSession:
    def __init__(
        self,
        candidate_id: str,
        role: str,
        round_name: str,
        skill: str,
        questions: List[Dict],
        time_limit_seconds: int = 900  # 15 minutes
    ):
        self.test_session_id = str(uuid.uuid4())
        self.candidate_id = candidate_id
        self.role = role
        self.round_name = round_name
        self.skill = skill

        self.questions = questions
        self.answers: Dict[str, int] = {}

        self.status = "created"
        self.start_time: Optional[datetime] = None
        self.end_time: Optional[datetime] = None
        self.time_limit_seconds = time_limit_seconds

    # -------------------------
    # Lifecycle
    # -------------------------

    def start(self):
        if self.status != "created":
            raise TestSessionError("Test session already started or completed")

        self.status = "started"
        self.start_time = datetime.now(timezone.utc)

    def submit(self):
        if self.status != "started":
            raise TestSessionError("Test session not active")

        self.status = "submitted"
        self.end_time = datetime.now(timezone.utc)

    # -------------------------
    # Answer Handling
    # -------------------------

    def answer_question(self, question_id: str, selected_option_index: int):
        if self.status != "started":
            raise TestSessionError("Cannot answer questions unless test is started")

        self.answers[question_id] = selected_option_index

    # -------------------------
    # Timing
    # -------------------------

    def time_elapsed_seconds(self) -> int:
        if not self.start_time:
            return 0

        end = self.end_time or datetime.now(timezone.utc)
        return int((end - self.start_time).total_seconds())

    def time_remaining_seconds(self) -> int:
        remaining = self.time_limit_seconds - self.time_elapsed_seconds()
        return max(0, remaining)

    def is_time_over(self) -> bool:
        return self.time_elapsed_seconds() >= self.time_limit_seconds

    # -------------------------
    # Serialization (CRITICAL)
    # -------------------------

    def to_dict(self) -> Dict:
        return {
            "test_session_id": self.test_session_id,
            "candidate_id": self.candidate_id,
            "role": self.role,
            "round_name": self.round_name,
            "skill": self.skill,
            "status": self.status,
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "time_limit_seconds": self.time_limit_seconds,
            "questions": self.questions,
            "answers": self.answers,
        }
