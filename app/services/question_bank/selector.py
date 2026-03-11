import random
from collections import Counter, defaultdict
from copy import deepcopy
from datetime import datetime, timezone

from app.services.question_bank.helpers import normalize_difficulty, normalize_style
from app.services.question_bank.enterprise_bank_config import (
    ENTERPRISE_BALANCED_DIFFICULTY_MIX,
    ENTERPRISE_DEFAULT_BANK_VERSION,
    get_enterprise_bank_policy,
    is_enterprise_role,
)
from app.services.question_bank.validator import validate_question_bank, QuestionBankValidationError


class QuestionSelectionError(ValueError):
    pass


def should_use_enterprise_selection(role_key, round_key, question_files=None):
    if not is_enterprise_role(role_key):
        return False
    if not question_files or len(question_files) != 1:
        return False
    return get_enterprise_bank_policy(source_name=question_files[0]) is not None


def _debugging_count(questions):
    return sum(1 for question in questions if normalize_style(question.get('style')) == 'debugging')


def _debugging_mix(questions):
    counts = Counter()
    for question in questions:
        if normalize_style(question.get('style')) == 'debugging':
            counts[normalize_difficulty(question.get('difficulty'))] += 1
    return dict(counts)


def _distribute_debug_targets(groups, min_debugging_total):
    debug_capacity = {difficulty: sum(1 for item in questions if normalize_style(item.get('style')) == 'debugging') for difficulty, questions in groups.items()}
    selected = {difficulty: 0 for difficulty in groups}
    ordered = sorted(groups, key=lambda difficulty: debug_capacity.get(difficulty, 0), reverse=True)
    remaining = min_debugging_total
    for difficulty in ordered:
        if remaining <= 0:
            break
        if debug_capacity.get(difficulty, 0) > 0:
            selected[difficulty] += 1
            remaining -= 1
    while remaining > 0:
        progress = False
        for difficulty in ordered:
            if remaining <= 0:
                break
            if selected[difficulty] >= ENTERPRISE_BALANCED_DIFFICULTY_MIX[difficulty]:
                continue
            if selected[difficulty] >= debug_capacity.get(difficulty, 0):
                continue
            selected[difficulty] += 1
            remaining -= 1
            progress = True
        if not progress:
            break
    if remaining > 0:
        raise QuestionSelectionError(f'Unable to satisfy minimum debugging requirement of {min_debugging_total}')
    return selected


def select_questions(questions, total_count, strategy='flat_random', rng=None, constraints=None):
    rng = rng or random.Random()
    constraints = constraints or {}
    if not questions:
        raise QuestionSelectionError('No questions available for selection')

    if strategy != 'balanced_difficulty_v2':
        if len(questions) < total_count:
            raise QuestionSelectionError(f'Need {total_count} questions, found {len(questions)}')
        return rng.sample(list(questions), total_count)

    groups = defaultdict(list)
    for question in questions:
        difficulty = normalize_difficulty(question.get('difficulty'))
        groups[difficulty].append(question)

    difficulty_mix = dict(constraints.get('difficulty_mix') or ENTERPRISE_BALANCED_DIFFICULTY_MIX)
    min_debugging_total = int(constraints.get('min_debugging_total', 0) or 0)
    debugging_by_difficulty = constraints.get('debugging_by_difficulty') or {}

    for difficulty, required in difficulty_mix.items():
        if len(groups.get(difficulty, [])) < required:
            raise QuestionSelectionError(
                f'Not enough {difficulty} questions: required {required}, found {len(groups.get(difficulty, []))}'
            )

    enforce_exact_debugging_mix = bool(debugging_by_difficulty)
    if enforce_exact_debugging_mix:
        debug_targets = {difficulty: 0 for difficulty in difficulty_mix}
        forced_total = 0
        for difficulty, required in difficulty_mix.items():
            forced = int(debugging_by_difficulty.get(difficulty, 0) or 0)
            if forced < 0:
                raise QuestionSelectionError(f'Invalid debugging target for {difficulty}: {forced}')
            if forced > required:
                raise QuestionSelectionError(
                    f'Debugging target for {difficulty} exceeds required questions ({forced} > {required})'
                )
            available_debug = sum(
                1 for item in groups.get(difficulty, [])
                if normalize_style(item.get('style')) == 'debugging'
            )
            if available_debug < forced:
                raise QuestionSelectionError(
                    f'Not enough debugging questions in {difficulty}: need {forced}, found {available_debug}'
                )
            debug_targets[difficulty] = forced
            forced_total += forced

        if min_debugging_total > forced_total:
            distributed_targets = _distribute_debug_targets(groups, min_debugging_total)
            for difficulty in difficulty_mix:
                debug_targets[difficulty] = max(
                    debug_targets.get(difficulty, 0),
                    distributed_targets.get(difficulty, 0),
                )
    else:
        debug_targets = _distribute_debug_targets(groups, min_debugging_total)
    selected = []
    for difficulty, required in difficulty_mix.items():
        bucket = list(groups.get(difficulty, []))
        debug_questions = [question for question in bucket if normalize_style(question.get('style')) == 'debugging']
        non_debug_questions = [question for question in bucket if normalize_style(question.get('style')) != 'debugging']

        need_debug = debug_targets.get(difficulty, 0)
        chosen = []
        if need_debug:
            if len(debug_questions) < need_debug:
                raise QuestionSelectionError(f'Not enough debugging questions in {difficulty}: need {need_debug}')
            chosen.extend(rng.sample(debug_questions, need_debug))
        remaining = required - len(chosen)
        if enforce_exact_debugging_mix:
            remaining_pool = [question for question in non_debug_questions if question not in chosen]
        else:
            remaining_pool = [question for question in bucket if question not in chosen]
        if len(remaining_pool) < remaining:
            if enforce_exact_debugging_mix:
                raise QuestionSelectionError(
                    f'Not enough non-debugging questions remaining in {difficulty} to satisfy exact mix'
                )
            raise QuestionSelectionError(f'Not enough questions remaining in {difficulty}')
        chosen.extend(rng.sample(remaining_pool, remaining))
        selected.extend(chosen)

    rng.shuffle(selected)
    if len(selected) != total_count:
        raise QuestionSelectionError(f'Selected {len(selected)} questions, expected {total_count}')
    if _debugging_count(selected) < min_debugging_total:
        raise QuestionSelectionError('Selected set did not meet debugging minimum after selection')
    return [deepcopy(question) for question in selected]


def build_frozen_mcq_round_payload(role_key, round_key, question_files, questions, rng=None):
    if not should_use_enterprise_selection(role_key, round_key, question_files):
        return {}
    if len(question_files) != 1:
        raise QuestionSelectionError('Enterprise selection expects exactly one source bank file')
    source_name = question_files[0]
    policy = get_enterprise_bank_policy(source_name=source_name)
    if not policy:
        raise QuestionSelectionError(f'No enterprise bank policy found for {source_name}')

    validate_question_bank(questions, source_name=source_name, strict=True)
    selected = select_questions(
        questions=questions,
        total_count=15,
        strategy='balanced_difficulty_v2',
        rng=rng or random.Random(),
        constraints={
            'difficulty_mix': ENTERPRISE_BALANCED_DIFFICULTY_MIX,
            'min_debugging_total': policy.get('min_selected_debugging', 0),
            'debugging_by_difficulty': policy.get('selected_debugging_by_difficulty') or {},
        },
    )

    return {
        'selected_questions': selected,
        'selected_question_ids': [question.get('id') for question in selected],
        'selection_strategy': 'balanced_difficulty_v2',
        'difficulty_mix': dict(ENTERPRISE_BALANCED_DIFFICULTY_MIX),
        'debugging_mix': _debugging_mix(selected),
        'question_bank_files': list(question_files),
        'selection_locked_at': datetime.now(timezone.utc).isoformat(),
        'bank_version': policy.get('bank_version', ENTERPRISE_DEFAULT_BANK_VERSION),
    }


should_use_enterprise_java_selection = should_use_enterprise_selection
