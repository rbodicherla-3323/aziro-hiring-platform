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


def test_build_mcq_submission_details_keeps_unanswered_questions():
    details = EvaluationService._build_mcq_submission_details(
        [
            {
                "question": "What is Python?",
                "correct_answer": "Language",
                "topic": "Python Basics",
                "tags": ["python"],
                "options": ["Language", "Database"],
            },
            {
                "question": "What is OOP?",
                "correct_answer": "Paradigm",
                "topic": "Concepts",
                "tags": ["oop"],
                "options": ["Pattern", "Paradigm"],
            },
        ],
        {"0": "Language"},
    )

    assert len(details) == 2
    assert details[0]["is_answered"] is True
    assert details[0]["is_correct"] is True
    assert details[1]["is_answered"] is False
    assert details[1]["selected_answer"] == ""
    assert details[1]["correct_answer"] == "Paradigm"


def test_generate_candidate_pdf_invokes_new_detail_renderers(monkeypatch):
    output_dir = PROJECT_ROOT / "app" / "runtime" / "reports"
    output_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(pdf_service, "REPORTS_DIR", output_dir)

    candidate_data = {
        "name": "Alice Example",
        "email": "alice@example.com",
        "role": "Python Developer",
        "batch_id": "batch_py_1",
        "test_session_id": 52,
        "rounds": {
            "L2": {
                "round_label": "Python Theory",
                "correct": 10,
                "total": 15,
                "attempted": 12,
                "percentage": 66.7,
                "status": "FAIL",
                "pass_threshold": 70,
                "submission_details": {
                    "responses": [
                        {
                            "question_no": 1,
                            "question": "What is list comprehension?",
                            "selected_answer": "Python expression",
                            "correct_answer": "Python expression",
                            "is_answered": True,
                            "is_correct": True,
                            "topic": "Python",
                            "tags": ["python"],
                        },
                        {
                            "question_no": 2,
                            "question": "What is threading?",
                            "selected_answer": "",
                            "correct_answer": "Concurrency",
                            "is_answered": False,
                            "is_correct": False,
                            "topic": "Concurrency",
                            "tags": ["threads"],
                        },
                    ]
                },
            },
            "L4": {
                "round_label": "Coding Challenge",
                "correct": 1,
                "total": 1,
                "attempted": 1,
                "percentage": 100,
                "status": "PASS",
                "pass_threshold": 70,
            },
        },
        "proctoring_summary": {},
        "plagiarism_summary": {},
        "ai_overall_summary": "Overall summary text",
        "ai_coding_summary": "Coding summary text",
        "coding_round_data": {
            "round_label": "Coding Challenge",
            "status": "PASS",
            "percentage": 100,
            "correct": 1,
            "total": 1,
            "language": "python",
            "question_title": "Two Sum",
            "question_text": "Return indices of two numbers that add to target.",
            "submitted_code": "def solve(nums, target):\n    return [0, 1]\n",
            "public_tests": [{"input": [1, 2], "expected": [0, 1]}],
            "hidden_tests": [{"input": [2, 7, 11, 15], "expected": [0, 1]}],
        },
    }

    captured = {"coding_called": False, "mcq_called": False}
    original_coding_renderer = pdf_service._render_coding_details_section
    original_mcq_renderer = pdf_service._render_mcq_round_sections

    def _capture_coding(elements, styles, coding_round_data, doc_width):
        captured["coding_called"] = True
        assert coding_round_data["question_title"] == "Two Sum"
        return original_coding_renderer(elements, styles, coding_round_data, doc_width)

    def _capture_mcq(elements, styles, rounds):
        captured["mcq_called"] = True
        assert "L2" in rounds
        return original_mcq_renderer(elements, styles, rounds)

    monkeypatch.setattr(pdf_service, "_render_coding_details_section", _capture_coding)
    monkeypatch.setattr(pdf_service, "_render_mcq_round_sections", _capture_mcq)

    filename = pdf_service.generate_candidate_pdf(candidate_data)

    assert filename.endswith(".pdf")
    assert captured["coding_called"] is True
    assert captured["mcq_called"] is True


def test_strip_submitted_code_block_keeps_question_text_only():
    raw_summary = (
        "### Coding Round Summary\n"
        "Round: Coding Challenge (Python)\n"
        "Language: python\n"
        "Question: Remove Duplicates Preserve Order\n"
        "Problem Statement: Remove duplicates from list while preserving order.\n"
        "Submitted Code:\n"
        "def solve(nums):\n"
        "    return list(set(nums))\n"
    )

    cleaned = pdf_service._strip_submitted_code_block(raw_summary)

    assert "Submitted Code:" not in cleaned
    assert "Question: Remove Duplicates Preserve Order" in cleaned
    assert "Problem Statement: Remove duplicates from list while preserving order." in cleaned


def test_build_score_summary_rows_excludes_soft_skills_from_first_row():
    rounds = {
        "L2": {"round_label": "Python Theory", "correct": 7, "total": 10},
        "L4": {"round_label": "Coding Challenge", "correct": 8, "total": 10},
        "L5": {"round_label": "Soft Skills", "correct": 4, "total": 5},
    }
    rows = pdf_service._build_score_summary_rows(rounds, ["L2", "L4", "L5"])

    assert rows[0][1] == "Total (Excl. Soft Skills)"
    assert rows[0][2] == "15 / 20"
    assert rows[0][3] == "75.0%"
    assert rows[1][1] == "Overall (All Rounds)"
    assert rows[1][2] == "19 / 25"
    assert rows[1][3] == "76.0%"


def test_resolve_round_submission_details_prefers_latest_mcq_store_responses(monkeypatch):
    candidate_data = {
        "email": "alice@example.com",
        "role_key": "python_qa",
        "batch_id": "batch_py_1",
        "rounds": {
            "L2": {
                "round_label": "Python Theory",
                "session_uuid": "mcq-session-001",
                "submission_details": {
                    "responses": [
                        {
                            "question_no": 1,
                            "question": "What is Python?",
                            "selected_answer": "Database",
                            "correct_answer": "Language",
                            "is_answered": True,
                            "is_correct": False,
                        }
                    ]
                },
            }
        },
    }

    monkeypatch.setattr(
        "app.services.evaluation_service.get_latest_mcq_submission",
        lambda *args, **kwargs: {
            "responses": [
                {
                    "question_no": 1,
                    "question": "What is Python?",
                    "selected_answer": "Language",
                    "correct_answer": "Language",
                    "is_answered": True,
                    "is_correct": True,
                }
            ]
        },
    )
    monkeypatch.setattr(
        "app.services.evaluation_service.get_mcq_session_data",
        lambda *_args, **_kwargs: {
            "questions": [{"question": "What is Python?", "correct_answer": "Language"}],
            "answers": {"0": "Database"},
        },
    )

    details = EvaluationService._resolve_round_submission_details(
        candidate_data,
        "L2",
        candidate_data["rounds"]["L2"],
    )
    responses = details.get("responses", [])

    assert responses
    assert responses[0]["selected_answer"] == "Language"
    assert responses[0]["is_correct"] is True


def test_evaluate_mcq_persists_submission_details_to_mcq_store(monkeypatch):
    session_id = "mcq-persist-001"
    captured = {}
    original_store = dict(EVALUATION_STORE)
    EVALUATION_STORE.clear()
    from app.services.mcq_session_registry import MCQ_SESSION_REGISTRY
    original_registry_cache = dict(MCQ_SESSION_REGISTRY._cache)

    try:
        MCQ_SESSION_REGISTRY._cache[session_id] = {
            "session_id": session_id,
            "candidate_name": "Alice Example",
            "email": "alice@example.com",
            "role_key": "python_qa",
            "role_label": "Python Developer",
            "batch_id": "batch_py_1",
            "round_key": "L2",
            "round_label": "Python Theory",
        }

        monkeypatch.setattr(
            "app.services.evaluation_service.get_mcq_session_data",
            lambda _sid: {
                "questions": [
                    {
                        "question": "What is Python?",
                        "correct_answer": "Language",
                        "topic": "Basics",
                        "tags": ["python"],
                    }
                ],
                "answers": {"0": "Language"},
                "start_time": 1000,
            },
        )
        monkeypatch.setattr("app.services.evaluation_service.time.time", lambda: 1060)
        monkeypatch.setattr(
            "app.services.evaluation_service.EvaluationService._persist_result_to_db",
            staticmethod(lambda *_args, **_kwargs: None),
        )

        def _capture_save(**kwargs):
            captured.update(kwargs)

        monkeypatch.setattr("app.services.evaluation_service.save_mcq_submission", _capture_save)

        EvaluationService.evaluate_mcq(session_id)

        assert captured.get("session_id") == session_id
        assert captured.get("email") == "alice@example.com"
        assert captured.get("round_key") == "L2"
        assert isinstance(captured.get("responses"), list)
        assert captured["responses"][0]["selected_answer"] == "Language"
    finally:
        EVALUATION_STORE.clear()
        EVALUATION_STORE.update(original_store)
        MCQ_SESSION_REGISTRY._cache.clear()
        MCQ_SESSION_REGISTRY._cache.update(original_registry_cache)
