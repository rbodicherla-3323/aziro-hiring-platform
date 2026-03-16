import random

from app.services.question_bank.helpers import normalize_text, prepare_question_options


def _answer_not_unique_extreme(prepared_question):
    options = prepared_question["options"]
    answer = prepared_question["correct_answer"]
    answer_index = options.index(answer)
    lengths = [len(normalize_text(option)) for option in options]
    longest = max(lengths)
    shortest = min(lengths)
    unique_longest_correct = lengths.count(longest) == 1 and lengths[answer_index] == longest
    unique_shortest_correct = lengths.count(shortest) == 1 and lengths[answer_index] == shortest
    return not unique_longest_correct and not unique_shortest_correct


def test_prepare_question_options_rebalances_unique_longest_correct():
    question = {
        "question": "Which response best demonstrates ownership?",
        "options": [
            "Escalate quickly",
            "Wait",
            "Ignore",
            "Provide a clear status update with owner, ETA, risk, and mitigation",
        ],
        "correct_answer": "Provide a clear status update with owner, ETA, risk, and mitigation",
    }

    prepared = prepare_question_options([question], rng=random.Random(11))[0]

    assert prepared["correct_answer"] in prepared["options"]
    assert _answer_not_unique_extreme(prepared)


def test_prepare_question_options_rebalances_unique_shortest_correct():
    question = {
        "question": "Choose the most accurate answer.",
        "options": [
            "Use observability and rollback controls across staged rollout windows",
            "Use canary rollout with SLO checks",
            "Coordinate incident response with stakeholder updates",
            "Yes",
        ],
        "correct_answer": "Yes",
    }

    prepared = prepare_question_options([question], rng=random.Random(21))[0]

    assert prepared["correct_answer"] in prepared["options"]
    assert _answer_not_unique_extreme(prepared)


def test_prepare_question_options_preserves_answer_membership():
    question = {
        "question": "Pick the best option.",
        "options": [
            "Plan with checkpoints",
            "Share assumptions early",
            "Clarify dependencies",
            "Escalate blockers quickly",
        ],
        "correct_answer": "Clarify dependencies",
    }

    prepared = prepare_question_options([question], rng=random.Random(5))[0]

    assert prepared["correct_answer"] in prepared["options"]
    assert len(prepared["options"]) == 4
