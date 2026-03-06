from app.utils.round_question_mapping import (
    DOMAIN_QUESTION_FILES,
    ROUND_QUESTION_MAPPING,
)


class QuestionRegistry:

    def __init__(self, loader):
        self.loader = loader

    def get_question_files(self, role_key, round_key, domain=None):
        if round_key == "L6":
            if not domain:
                return []
            return list(DOMAIN_QUESTION_FILES.get(domain.lower(), []))

        role_map = ROUND_QUESTION_MAPPING.get(role_key)
        if not role_map:
            return []
        return list(role_map.get(round_key, []))

    def get_questions(self, role_key, round_key, domain=None):
        questions = []
        for file_path in self.get_question_files(role_key, round_key, domain=domain):
            questions.extend(self.loader.load(file_path))
        return questions
