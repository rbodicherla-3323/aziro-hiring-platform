import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.services import generated_tests_store


def test_generated_tests_store_keeps_distinct_batches_for_same_candidate_same_day(monkeypatch):
    generated_tests_store.GENERATED_TESTS.clear()
    monkeypatch.setattr(generated_tests_store, "_safe_db_tests_for_user", lambda *args, **kwargs: [])

    generated_tests_store.add_generated_test(
        {
            "name": "Candidate One",
            "email": "candidate.one@example.com",
            "role": "Python QA",
            "role_key": "python_qa",
            "batch_id": "batch_alpha",
            "created_by": "owner@example.com",
            "created_at": "2026-04-08T10:00:00+00:00",
            "tests": {"L2": {"session_id": "session-a"}},
        }
    )
    generated_tests_store.add_generated_test(
        {
            "name": "Candidate One",
            "email": "candidate.one@example.com",
            "role": "Python QA",
            "role_key": "python_qa",
            "batch_id": "batch_beta",
            "created_by": "owner@example.com",
            "created_at": "2026-04-08T11:00:00+00:00",
            "tests": {"L2": {"session_id": "session-b"}},
        }
    )

    rows = generated_tests_store.get_tests_for_user_today("owner@example.com")

    assert len(rows) == 2
    assert {row["batch_id"] for row in rows} == {"batch_alpha", "batch_beta"}
