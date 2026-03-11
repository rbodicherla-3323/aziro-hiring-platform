from pathlib import Path

from app.utils.role_round_mapping import ROLE_ROUND_MAPPING
from app.utils.round_question_mapping import ROUND_QUESTION_MAPPING


QUESTION_BANK_ROOT = Path("app/services/question_bank/data")


def test_all_role_round_mappings_have_question_files():
    for role_key, role_cfg in ROLE_ROUND_MAPPING.items():
        mapped_rounds = ROUND_QUESTION_MAPPING.get(role_key, {})
        assert mapped_rounds, f"Missing question mapping for role: {role_key}"

        for round_key in role_cfg.get("rounds", []):
            assert round_key in mapped_rounds, f"Missing mapping for {role_key}.{round_key}"
            files = mapped_rounds[round_key]
            assert isinstance(files, list) and files, f"Empty mapping for {role_key}.{round_key}"

            for rel_path in files:
                file_path = QUESTION_BANK_ROOT / rel_path
                assert file_path.exists(), f"Missing question bank file: {rel_path}"
