import random
import re
from copy import deepcopy

DIFFICULTY_ALIASES = {
    'moderate': 'medium',
    'med': 'medium',
}

VALID_DIFFICULTIES = {'easy', 'medium', 'hard'}
VALID_STYLES = {'concept', 'scenario', 'debugging', 'architecture', 'operations'}


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


def prepare_question_options(selected_questions, rng=None):
    rng = rng or random
    prepared = []
    for question in selected_questions:
        q = deepcopy(question)
        options = q.get('options')
        correct = q.get('correct_answer')
        if isinstance(options, list) and len(options) > 1 and correct in options:
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
