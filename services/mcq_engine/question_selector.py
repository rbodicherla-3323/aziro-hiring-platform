import random
from typing import List, Optional


class QuestionSelectionError(Exception):
    pass


def select_random_questions(
    questions: List[dict],
    count: int = 15,
    seed: Optional[str] = None
) -> List[dict]:
    """
    Select random MCQ questions without repetition.

    Args:
        questions: List of question dictionaries
        count: Number of questions to select
        seed: Optional seed for deterministic selection

    Returns:
        List of selected questions
    """

    if not questions:
        raise QuestionSelectionError("Question list is empty")

    if len(questions) < count:
        raise QuestionSelectionError(
            f"Not enough questions: requested {count}, available {len(questions)}"
        )

    rng = random.Random(seed)

    # sample() guarantees no duplicates
    selected = rng.sample(questions, count)

    return selected
