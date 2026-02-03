import json
import os
import hashlib
from typing import List, Dict


class QuestionLoaderError(Exception):
    """Custom exception for question loading issues."""
    pass


class QuestionLoader:
    """
    Loads and normalizes MCQ questions from JSON files.
    JSON format is NOT modified. Normalization happens internally.
    """

    def __init__(self, base_path: str):
        """
        :param base_path: Path to question_bank folder
        Example: data/question_bank
        """
        self.base_path = base_path

    def load_from_file(self, file_path: str, skill: str) -> List[Dict]:
        """
        Load questions from a single JSON file and normalize them.
        """
        if not os.path.exists(file_path):
            raise QuestionLoaderError(f"Question file not found: {file_path}")

        with open(file_path, "r", encoding="utf-8") as f:
            try:
                raw_questions = json.load(f)
            except json.JSONDecodeError as e:
                raise QuestionLoaderError(f"Invalid JSON in {file_path}: {e}")

        if not isinstance(raw_questions, list):
            raise QuestionLoaderError(f"JSON root must be a list: {file_path}")

        normalized_questions = []

        for idx, q in enumerate(raw_questions):
            try:
                normalized = self._normalize_question(
                    q,
                    skill=skill,
                    index=idx,
                    source=file_path
                )
                normalized_questions.append(normalized)
            except QuestionLoaderError as e:
                # Skip bad questions, but do not crash
                print(f"[SKIPPED QUESTION] {e}")

        return normalized_questions

    def _normalize_question(
        self,
        raw: Dict,
        skill: str,
        index: int,
        source: str
    ) -> Dict:
        """
        Validate and normalize a single question.
        """

        required_fields = ["question", "options", "correct_answer"]

        for field in required_fields:
            if field not in raw:
                raise QuestionLoaderError(
                    f"Missing field '{field}' in {source} (index {index})"
                )

        question_text = raw["question"]
        options = raw["options"]
        correct_answer = raw["correct_answer"]
        topic = raw.get("topic", "General")

        if not isinstance(options, list) or len(options) < 2:
            raise QuestionLoaderError(
                f"Invalid options list in {source} (index {index})"
            )

        if correct_answer not in options:
            raise QuestionLoaderError(
                f"Correct answer not in options in {source} (index {index})"
            )

        correct_answer_index = options.index(correct_answer)

        # Stable ID using hash (question + skill)
        raw_id = f"{skill}:{question_text}"
        question_id = hashlib.md5(raw_id.encode()).hexdigest()[:12]

        return {
            "id": f"{skill}_{question_id}",
            "skill": skill,
            "topic": topic,
            "question": question_text,
            "options": options,
            "correct_answer_index": correct_answer_index,
        }
