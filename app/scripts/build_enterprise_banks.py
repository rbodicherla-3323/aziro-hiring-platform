import argparse
import json
from pathlib import Path

from app.scripts import build_enterprise_aiml_bank as aiml_builder
from app.scripts import build_enterprise_core_banks as core_builder
from app.scripts import build_enterprise_role_banks as role_builder
from app.scripts import build_enterprise_shared_banks as shared_builder
from app.services.question_bank.enterprise_bank_config import ENTERPRISE_BANK_POLICIES
from app.services.question_bank.validator import validate_question_bank

DATA_DIR = Path("app/services/question_bank/data")

CORE_TRACK_BANKS = {
    spec["bank_key"]
    for spec in core_builder.BANK_SPECS
    if spec["bank_key"] in ENTERPRISE_BANK_POLICIES
}
AIML_TRACK_BANKS = {aiml_builder.BANK_KEY}
GENERAL_ROLE_BANKS = set(role_builder.CORE_ROLE_ENTERPRISE_BANKS)
SHARED_POOL_BANKS = set(shared_builder.SHARED_BANK_SETTINGS.keys())
ALL_ENTERPRISE_BANKS = set(ENTERPRISE_BANK_POLICIES.keys())

PIPELINE_STEPS = (
    {
        "name": "core_role_banks",
        "builder": core_builder.build_all_banks,
        "banks": CORE_TRACK_BANKS,
    },
    {
        "name": "ai_ml_role_bank",
        "builder": aiml_builder.main,
        "banks": AIML_TRACK_BANKS,
    },
    {
        "name": "general_role_banks",
        "builder": role_builder.build_role_enterprise_banks,
        "banks": GENERAL_ROLE_BANKS,
    },
    {
        "name": "shared_pool_banks",
        "builder": shared_builder.build_shared_enterprise_banks,
        "banks": SHARED_POOL_BANKS,
    },
)


def _normalize_targets(target_banks=None):
    if not target_banks:
        return set(ALL_ENTERPRISE_BANKS)
    normalized = {str(item).strip() for item in target_banks if str(item).strip()}
    unknown = sorted(normalized - ALL_ENTERPRISE_BANKS)
    if unknown:
        raise ValueError(f"Unknown enterprise bank keys: {', '.join(unknown)}")
    return normalized


def _steps_for_targets(targets):
    steps = []
    for spec in PIPELINE_STEPS:
        if targets.intersection(spec["banks"]):
            steps.append(spec)
    return steps


def _validate_targets(targets, strict=True):
    for bank_key in sorted(targets):
        payload = json.loads((DATA_DIR / bank_key).read_text(encoding="utf-8"))
        questions = payload["questions"] if isinstance(payload, dict) else payload
        summary = validate_question_bank(questions, source_name=bank_key, strict=strict)
        print(
            f"Validated {bank_key}: total={summary['total_questions']} "
            f"difficulty={summary['difficulty_counts']} debugging={summary['debugging_counts']}"
        )


def build_enterprise_banks(target_banks=None, validate=True):
    targets = _normalize_targets(target_banks)
    steps = _steps_for_targets(targets)
    if not steps:
        raise ValueError("No builder steps selected for requested enterprise banks")

    for step in steps:
        print(f"Building {step['name']}...")
        step["builder"]()

    if validate:
        _validate_targets(targets, strict=True)

    print(f"Enterprise build complete. Banks built/validated: {len(targets)}")
    return sorted(targets)


def main():
    parser = argparse.ArgumentParser(
        description="Unified enterprise MCQ bank builder (all roles via shared config/validator pipeline)."
    )
    parser.add_argument(
        "--banks",
        nargs="*",
        default=None,
        help="Optional list of enterprise bank keys to build (default: all enterprise banks).",
    )
    parser.add_argument(
        "--no-validate",
        action="store_true",
        help="Skip strict validation after build.",
    )
    args = parser.parse_args()
    build_enterprise_banks(target_banks=args.banks, validate=not args.no_validate)


if __name__ == "__main__":
    main()
