import json
import os


class QuestionLoader:

    def __init__(self, base_path: str):
        self.base_path = base_path

    def load(self, relative_path: str):
        file_path = os.path.join(self.base_path, relative_path)

        if not os.path.exists(file_path):
            raise FileNotFoundError(f"Question file not found: {file_path}")

        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        # ✅ NORMALIZATION (THIS IS THE KEY FIX)
        # If JSON is { "questions": [...] } → extract list
        if isinstance(data, dict) and "questions" in data:
            return data["questions"]

        # If JSON is already a list → return directly
        if isinstance(data, list):
            return data

        # Safety fallback
        raise ValueError(f"Invalid question format in {relative_path}")
