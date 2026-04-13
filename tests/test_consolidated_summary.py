import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.services.ai_generator import _build_fallback_consolidated_summary
from app.services import pdf_service
from app.services.evaluation_service import EvaluationService
from app.services.evaluation_store import EVALUATION_STORE


def _candidate(email, role, batch_id, l2_status, l2_percentage, l4_status, l4_percentage):
    return {
        "name": email.split("@")[0].title(),
        "email": email,
        "role": role,
        "batch_id": batch_id,
        "rounds": {
            "L2": {
                "round_label": "Technical Screening",
                "correct": 11 if l2_status == "PASS" else 6,
                "total": 15,
                "attempted": 15,
                "percentage": l2_percentage,
                "pass_threshold": 70,
                "status": l2_status,
                "time_taken_seconds": 900,
            },
            "L4": {
                "round_label": "Coding Challenge",
                "correct": 1 if l4_status == "PASS" else 0,
                "total": 1,
                "attempted": 1,
                "percentage": l4_percentage,
                "pass_threshold": 70,
                "status": l4_status,
                "time_taken_seconds": 1800,
            },
        },
    }


def _candidate_with_details(email, role, batch_id, memory_topic, coding_title):
    return {
        "name": email.split("@")[0].title(),
        "email": email,
        "role": role,
        "batch_id": batch_id,
        "rounds": {
            "L2": {
                "round_label": "Technical Screening",
                "correct": 6,
                "total": 15,
                "attempted": 15,
                "percentage": 40,
                "pass_threshold": 70,
                "status": "FAIL",
                "time_taken_seconds": 900,
                "submission_details": {
                    "responses": [
                        {
                            "question": "Explain stack vs heap allocation in C++ object lifetimes.",
                            "topic": memory_topic,
                            "tags": [memory_topic, "object lifetime"],
                            "is_correct": False,
                        },
                        {
                            "question": "How does RAII help with deterministic resource cleanup?",
                            "topic": memory_topic,
                            "tags": [memory_topic, "raii"],
                            "is_correct": False,
                        },
                        {
                            "question": "What is a virtual function?",
                            "topic": "OOP",
                            "tags": ["polymorphism"],
                            "is_correct": True,
                        },
                    ],
                },
            },
            "L4": {
                "round_label": "Coding Challenge",
                "correct": 0,
                "total": 1,
                "attempted": 1,
                "percentage": 0,
                "pass_threshold": 70,
                "status": "FAIL",
                "time_taken_seconds": 1800,
                "submission_details": {
                    "question_title": coding_title,
                    "question_text": "Reverse a singly linked list in place.",
                    "language": "cpp",
                },
            },
        },
    }


def test_prepare_consolidated_summary_payload_aggregates_counts():
    candidates = [
        _candidate("alice@example.com", "C++ Developer", "batch_cpp_1", "PASS", 78, "FAIL", 0),
        _candidate("bob@example.com", "C++ Developer", "batch_cpp_1", "PASS", 82, "PASS", 100),
    ]

    payload = EvaluationService._prepare_consolidated_summary_payload(
        candidates,
        {"role": "C++ Developer", "period_label": "Today"},
    )

    assert payload is not None
    assert payload["scope"]["role"] == "C++ Developer"
    assert payload["scope"]["candidate_count"] == 2
    assert payload["aggregate"]["verdict_counts"]["Rejected"] == 1
    assert payload["aggregate"]["verdict_counts"]["Selected"] == 1

    round_stats = payload["aggregate"]["round_stats"]
    assert [row["round_label"] for row in round_stats] == ["Technical Screening", "Coding Challenge"]
    assert round_stats[0]["attempted_candidates"] == 2
    assert round_stats[1]["failed_candidates"] == 1
    assert round_stats[1]["passed_candidates"] == 1


def test_fallback_consolidated_summary_contains_expected_sections():
    candidates = [
        _candidate("alice@example.com", "C++ Developer", "batch_cpp_1", "PASS", 78, "FAIL", 0),
        _candidate("bob@example.com", "C++ Developer", "batch_cpp_1", "PASS", 82, "PASS", 100),
    ]
    payload = EvaluationService._prepare_consolidated_summary_payload(
        candidates,
        {"role": "C++ Developer", "period_label": "Today"},
    )

    summary = _build_fallback_consolidated_summary(payload)

    assert "Consolidated Interview Feedback" in summary
    assert "Overall Outcome" in summary
    assert "Key Observations" in summary
    assert "Overall Assessment & Recommendations" in summary
    assert "C++ Developer" in summary


def test_prepare_consolidated_summary_payload_extracts_gap_and_coding_signals():
    candidates = [
        _candidate_with_details("alice@example.com", "C++ Developer", "batch_cpp_1", "Memory Management", "Linked List Reversal"),
        _candidate_with_details("bob@example.com", "C++ Developer", "batch_cpp_1", "Memory Management", "Linked List Reversal"),
    ]

    payload = EvaluationService._prepare_consolidated_summary_payload(
        candidates,
        {"role": "C++ Developer", "period_label": "Today"},
    )

    assert payload is not None

    gap_signals = payload["aggregate"]["recurring_gap_signals"]
    assert gap_signals
    assert gap_signals[0]["signal_label"] == "Memory Management"
    assert gap_signals[0]["candidate_occurrences"] == 2

    coding_signals = payload["aggregate"]["coding_signals"]
    assert coding_signals
    assert coding_signals[0]["question_title"] == "Linked List Reversal"
    assert coding_signals[0]["failed_candidates"] == 2
    assert coding_signals[0]["languages"] == ["cpp"]


def test_prepare_consolidated_summary_payload_uses_live_round_details():
    original_store = dict(EVALUATION_STORE)
    EVALUATION_STORE.clear()
    try:
        EVALUATION_STORE["session-1"] = {
            "candidate_name": "Alice",
            "email": "alice@example.com",
            "round_key": "L2",
            "round_label": "Technical Screening",
            "total_questions": 15,
            "attempted": 15,
            "correct": 5,
            "percentage": 33.33,
            "pass_threshold": 70,
            "status": "FAIL",
            "time_taken_seconds": 900,
            "submission_details": {
                "responses": [
                    {
                        "question": "Explain stack vs heap allocation in C++ object lifetimes.",
                        "topic": "Memory Management",
                        "tags": ["Memory Management", "object lifetime"],
                        "is_correct": False,
                    }
                ],
            },
        }

        payload = EvaluationService._prepare_consolidated_summary_payload(
            [_candidate("alice@example.com", "C++ Developer", "batch_cpp_1", "FAIL", 33.33, "FAIL", 0)],
            {"role": "C++ Developer", "period_label": "Today"},
        )

        assert payload is not None
        gap_signals = payload["aggregate"]["recurring_gap_signals"]
        assert gap_signals
        assert gap_signals[0]["signal_label"] == "Memory Management"
    finally:
        EVALUATION_STORE.clear()
        EVALUATION_STORE.update(original_store)


def test_generate_consolidated_summary_pdf_creates_file(monkeypatch):
    output_dir = PROJECT_ROOT / "app" / "runtime" / "reports"
    output_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(pdf_service, "REPORTS_DIR", output_dir)

    filename = pdf_service.generate_consolidated_summary_pdf(
        "Consolidated Interview Feedback\n\nOverall Outcome\nThe batch was mixed.",
        {
            "role": "C++ Developer",
            "period_label": "Today",
            "candidate_count": 2,
            "batch_ids": ["batch_cpp_1"],
        },
    )

    assert filename.endswith(".pdf")
    pdf_path = output_dir / filename
    assert pdf_path.exists()
    assert pdf_path.stat().st_size > 0


def test_generate_candidate_pdf_uses_role_scoped_summary_services(monkeypatch):
    output_dir = PROJECT_ROOT / "app" / "runtime" / "reports"
    output_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(pdf_service, "REPORTS_DIR", output_dir)

    candidate_data = {
        "name": "Alice Example",
        "email": "alice@example.com",
        "role": "Python Developer",
        "batch_id": "batch_py_1",
        "test_session_id": 42,
        "rounds": {
            "L2": {
                "round_label": "Python Theory",
                "correct": 10,
                "total": 15,
                "percentage": 66.7,
                "status": "FAIL",
                "pass_threshold": 70,
            },
            "L4": {
                "round_label": "Coding Challenge",
                "correct": 1,
                "total": 1,
                "percentage": 100,
                "status": "PASS",
                "pass_threshold": 70,
            },
        },
        "proctoring_summary": {},
        "plagiarism_summary": {},
    }

    captured = {}

    def _fake_overall(email, candidate_data=None):
        captured["overall_email"] = email
        captured["overall_candidate"] = dict(candidate_data or {})
        return "Scoped overall summary"

    def _fake_coding(email, candidate_data=None):
        captured["coding_email"] = email
        captured["coding_candidate"] = dict(candidate_data or {})
        return "Scoped coding summary"

    monkeypatch.setattr(
        "app.services.evaluation_service.EvaluationService.generate_candidate_overall_summary",
        staticmethod(_fake_overall),
    )
    monkeypatch.setattr(
        "app.services.evaluation_service.EvaluationService.generate_candidate_coding_round_summary",
        staticmethod(_fake_coding),
    )
    monkeypatch.setattr(
        pdf_service,
        "generate_evaluation_summary",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("raw fallback should not be used")),
    )

    filename = pdf_service.generate_candidate_pdf(candidate_data)

    assert filename.endswith(".pdf")
    assert captured["overall_email"] == "alice@example.com"
    assert captured["coding_email"] == "alice@example.com"
