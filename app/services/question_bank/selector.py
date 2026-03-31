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
    policy = get_enterprise_bank_policy(source_name=question_files[0])
    if not policy:
        return False
    # Shared pools (aptitude/soft skills/domain) are intentionally not frozen via
    # enterprise balanced selection. Keep technical role-round banks only.
    policy_role = str(policy.get("role_key", "")).strip().lower()
    if policy_role.startswith("shared_"):
        return False
    return True


def _debugging_count(questions):
    return sum(1 for question in questions if normalize_style(question.get('style')) == 'debugging')


def _debugging_mix(questions):
    counts = Counter()
    for question in questions:
        if normalize_style(question.get('style')) == 'debugging':
            counts[normalize_difficulty(question.get('difficulty'))] += 1
    return dict(counts)


def _distribute_debug_targets(groups, min_debugging_total, required_by_difficulty=None, difficulty_mix=None):
    required_by_difficulty = dict(required_by_difficulty or {})
    difficulty_mix = dict(difficulty_mix or ENTERPRISE_BALANCED_DIFFICULTY_MIX)
    debug_capacity = {
        difficulty: sum(1 for item in questions if normalize_style(item.get('style')) == 'debugging')
        for difficulty, questions in groups.items()
    }
    selected = {difficulty: 0 for difficulty in groups}

    for difficulty, required in required_by_difficulty.items():
        required = int(required or 0)
        if required <= 0:
            continue
        if required > debug_capacity.get(difficulty, 0):
            raise QuestionSelectionError(
                f'Not enough debugging questions in {difficulty}: required {required}, found {debug_capacity.get(difficulty, 0)}'
            )
        if required > int(difficulty_mix.get(difficulty, 0)):
            raise QuestionSelectionError(
                f'Debugging requirement exceeds difficulty mix for {difficulty}: required {required}, mix {difficulty_mix.get(difficulty, 0)}'
            )
        selected[difficulty] = required

    ordered = sorted(groups, key=lambda difficulty: debug_capacity.get(difficulty, 0), reverse=True)
    remaining = max(int(min_debugging_total or 0), sum(selected.values())) - sum(selected.values())
    for difficulty in ordered:
        if remaining <= 0:
            break
        if selected[difficulty] > 0:
            continue
        if debug_capacity.get(difficulty, 0) > 0:
            selected[difficulty] += 1
            remaining -= 1
    while remaining > 0:
        progress = False
        for difficulty in ordered:
            if remaining <= 0:
                break
            if selected[difficulty] >= int(difficulty_mix.get(difficulty, 0)):
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
    required_debug_by_difficulty = dict(constraints.get('selected_debugging_by_difficulty') or {})

    for difficulty, required in difficulty_mix.items():
        if len(groups.get(difficulty, [])) < required:
            raise QuestionSelectionError(
                f'Not enough {difficulty} questions: required {required}, found {len(groups.get(difficulty, []))}'
            )

    debug_targets = _distribute_debug_targets(
        groups,
        min_debugging_total,
        required_by_difficulty=required_debug_by_difficulty,
        difficulty_mix=difficulty_mix,
    )
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
        if difficulty in required_debug_by_difficulty:
            # For tiers with an explicit debugging quota, keep the rest theory-only.
            remaining_pool = [question for question in non_debug_questions if question not in chosen]
        else:
            remaining_pool = [question for question in bucket if question not in chosen]
        if len(remaining_pool) < remaining:
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

    validate_question_bank(
        questions,
        source_name=source_name,
        strict=bool(policy.get("strict_validation", True)),
    )
    selected = select_questions(
        questions=questions,
        total_count=15,
        strategy='balanced_difficulty_v2',
        rng=rng or random.Random(),
        constraints={
            'difficulty_mix': dict(policy.get('selection_difficulty_mix') or ENTERPRISE_BALANCED_DIFFICULTY_MIX),
            'min_debugging_total': policy.get('min_selected_debugging', 0),
            'selected_debugging_by_difficulty': policy.get('selected_debugging_by_difficulty', {}),
        },
    )

    return {
        'selected_questions': selected,
        'selected_question_ids': [question.get('id') for question in selected],
        'selection_strategy': 'balanced_difficulty_v2',
        'difficulty_mix': dict(policy.get('selection_difficulty_mix') or ENTERPRISE_BALANCED_DIFFICULTY_MIX),
        'debugging_mix': _debugging_mix(selected),
        'question_bank_files': list(question_files),
        'selection_locked_at': datetime.now(timezone.utc).isoformat(),
        'bank_version': policy.get('bank_version', ENTERPRISE_DEFAULT_BANK_VERSION),
    }


should_use_enterprise_java_selection = should_use_enterprise_selection
