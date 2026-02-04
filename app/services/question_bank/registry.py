from app.utils.round_question_mapping import (
    ROUND_QUESTION_MAPPING,
    DOMAIN_QUESTION_FILES
)


class QuestionRegistry:

    def __init__(self, loader):
        self.loader = loader

    def get_questions(self, role_key, round_key, domain=None):
        questions = []

        # -------------------------------
        # DOMAIN ROUND (L6)
        # -------------------------------
        if round_key == "L6":
            if not domain:
                return []

            file_list = DOMAIN_QUESTION_FILES.get(domain.lower(), [])
            for file_path in file_list:
                questions.extend(self.loader.load(file_path))

            return questions

        # -------------------------------
        # NORMAL MCQ ROUNDS (L1–L5)
        # -------------------------------
        role_map = ROUND_QUESTION_MAPPING.get(role_key)
        if not role_map:
            return []

        file_list = role_map.get(round_key, [])
        for file_path in file_list:
            questions.extend(self.loader.load(file_path))

        return questions
