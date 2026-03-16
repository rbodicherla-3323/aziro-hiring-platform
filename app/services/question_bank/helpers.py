import random
import re
from copy import deepcopy

DIFFICULTY_ALIASES = {
    'moderate': 'medium',
    'med': 'medium',
}

VALID_DIFFICULTIES = {'easy', 'medium', 'hard'}
VALID_STYLES = {'concept', 'scenario', 'debugging', 'architecture', 'operations'}
LENGTH_BALANCE_SUFFIXES = (
    " under stated conditions",
    " based on available context",
    " in this scenario",
    " for this case",
)


def normalize_difficulty(value):
    text = str(value or '').strip().lower()
    text = DIFFICULTY_ALIASES.get(text, text)
    return text


def normalize_style(value):
    text = str(value or '').strip().lower()
    if text in {'debug', 'debugging'}:
        return 'debugging'
    if text in {'ops', 'operation', 'operations'}:
        return 'operations'
    if text in {'arch', 'architecture'}:
        return 'architecture'
    if text in {'scenario', 'situational'}:
        return 'scenario'
    return text or 'concept'


def normalize_text(value):
    text = str(value or '').strip().lower()
    text = text.replace('–', '-').replace('—', '-')
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


def question_signature(question_text):
    text = normalize_text(question_text)
    text = re.sub(r'[^a-z0-9 ]+', '', text)
    return text


def _option_length(option_text):
    return len(normalize_text(option_text))


def rebalance_option_lengths(options, correct_answer):
    """
    Reduce answer-length guessing bias by ensuring the correct answer is not the
    unique longest or unique shortest option.
    """
    if not isinstance(options, list) or len(options) < 2 or correct_answer not in options:
        return options, correct_answer

    balanced = list(options)
    answer_index = balanced.index(correct_answer)

    for step in range(32):
        lengths = [_option_length(option) for option in balanced]
        longest = max(lengths)
        shortest = min(lengths)
        unique_longest_correct = lengths.count(longest) == 1 and lengths[answer_index] == longest
        unique_shortest_correct = lengths.count(shortest) == 1 and lengths[answer_index] == shortest

        if not unique_longest_correct and not unique_shortest_correct:
            break

        if unique_longest_correct:
            candidate_index = max(
                (idx for idx in range(len(balanced)) if idx != answer_index),
                key=lambda idx: lengths[idx],
            )
            suffix = LENGTH_BALANCE_SUFFIXES[step % len(LENGTH_BALANCE_SUFFIXES)]
            if not normalize_text(balanced[candidate_index]).endswith(normalize_text(suffix)):
                balanced[candidate_index] = f"{balanced[candidate_index]}{suffix}"
            continue

        if unique_shortest_correct:
            suffix = LENGTH_BALANCE_SUFFIXES[step % len(LENGTH_BALANCE_SUFFIXES)]
            if not normalize_text(balanced[answer_index]).endswith(normalize_text(suffix)):
                balanced[answer_index] = f"{balanced[answer_index]}{suffix}"
            correct_answer = balanced[answer_index]

    return balanced, balanced[answer_index]


def prepare_question_options(selected_questions, rng=None):
    rng = rng or random
    prepared = []
    for question in selected_questions:
        q = deepcopy(question)
        options = q.get('options')
        correct = q.get('correct_answer')
        if isinstance(options, list) and len(options) > 1 and correct in options:
            balanced_options, balanced_correct = rebalance_option_lengths(options, correct)
            q['options'] = balanced_options
            q['correct_answer'] = balanced_correct
            options = q['options']
            rng.shuffle(options)
        prepared.append(q)

    by_option_count = {}
    for idx, q in enumerate(prepared):
        options = q.get('options')
        correct = q.get('correct_answer')
        if isinstance(options, list) and len(options) > 1 and correct in options:
            by_option_count.setdefault(len(options), []).append(idx)

    for option_count, indices in by_option_count.items():
        if len(indices) < 2:
            continue
        start = rng.randrange(option_count)
        targets = [((start + i) % option_count) for i in range(len(indices))]
        rng.shuffle(targets)
        for q_idx, target_pos in zip(indices, targets):
            q = prepared[q_idx]
            options = q['options']
            correct = q['correct_answer']
            current_pos = options.index(correct)
            if current_pos != target_pos:
                options[current_pos], options[target_pos] = options[target_pos], options[current_pos]
    return prepared
