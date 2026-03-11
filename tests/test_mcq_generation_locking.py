import pytest

from app import create_app
from app.blueprints.dashboard import routes as dashboard_routes
from app.blueprints.mcq.services import MCQSessionService
from app.services.generated_tests_store import GENERATED_TESTS
from app.services.mcq_runtime_store import clear_mcq_session_data
from app.services.mcq_session_registry import MCQ_SESSION_REGISTRY


def test_java_mcq_generation_locks_selected_questions(monkeypatch):
    GENERATED_TESTS.clear()
    MCQ_SESSION_REGISTRY.clear()

    monkeypatch.setattr(
        dashboard_routes,
        "send_candidate_test_links_email",
        lambda **kwargs: (False, "disabled for test"),
    )
    monkeypatch.setattr(
        dashboard_routes,
        "get_valid_graph_delegated_token",
        lambda _email: None,
    )
    monkeypatch.setattr(
        dashboard_routes,
        "get_valid_graph_delegated_token_from_session",
        lambda _oauth: None,
    )

    app = create_app()
    app.config["TESTING"] = True
    client = app.test_client()

    response = client.post(
        "/create-test",
        data={
            "name[]": ["Candidate One"],
            "email[]": ["candidate.one@example.com"],
            "role[]": ["Java Entry Level (0-2 Years)"],
            "domain[]": ["None"],
        },
        follow_redirects=False,
    )

    assert response.status_code == 302

    java_l2_sessions = [
        payload
        for payload in MCQ_SESSION_REGISTRY.values()
        if payload.get("role_key") == "java_entry" and payload.get("round_key") == "L2"
    ]
    assert len(java_l2_sessions) == 1
    payload = java_l2_sessions[0]
    assert payload["selection_strategy"] == "balanced_difficulty_v2"
    assert payload["difficulty_mix"] == {"easy": 5, "medium": 5, "hard": 5}
    assert len(payload["selected_questions"]) == 15
    assert len(payload["selected_question_ids"]) == 15
    assert payload["debugging_mix"] == {"easy": 1, "medium": 1, "hard": 1}

    java_l3_sessions = [
        p for p in MCQ_SESSION_REGISTRY.values()
        if p.get("role_key") == "java_entry" and p.get("round_key") == "L3"
    ]
    assert not java_l3_sessions

    session_id = next(
        key
        for key, payload in MCQ_SESSION_REGISTRY.items()
        if payload.get("role_key") == "java_entry" and payload.get("round_key") == "L2"
    )
    frozen_ids = list(MCQ_SESSION_REGISTRY[session_id]["selected_question_ids"])

    with app.test_request_context(f"/mcq/start/{session_id}"):
        MCQSessionService.init_session(session_id, "java_entry", "L2", force_reset=True)
        runtime_ids = [question["id"] for question in MCQSessionService.get_session_data(session_id)["questions"]]
        clear_mcq_session_data(session_id)

    assert runtime_ids == frozen_ids


def test_python_aiml_l3_generation_locks_selected_questions(monkeypatch):
    GENERATED_TESTS.clear()
    MCQ_SESSION_REGISTRY.clear()

    monkeypatch.setattr(
        dashboard_routes,
        "send_candidate_test_links_email",
        lambda **kwargs: (False, "disabled for test"),
    )
    monkeypatch.setattr(
        dashboard_routes,
        "get_valid_graph_delegated_token",
        lambda _email: None,
    )
    monkeypatch.setattr(
        dashboard_routes,
        "get_valid_graph_delegated_token_from_session",
        lambda _oauth: None,
    )

    app = create_app()
    app.config["TESTING"] = True
    client = app.test_client()

    response = client.post(
        "/create-test",
        data={
            "name[]": ["Candidate AIML"],
            "email[]": ["candidate.aiml@example.com"],
            "role[]": ["Python + AI/ML (4+ Years)"],
            "domain[]": ["None"],
        },
        follow_redirects=False,
    )

    assert response.status_code == 302

    l3_session_id, l3_payload = next(
        (key, payload)
        for key, payload in MCQ_SESSION_REGISTRY.items()
        if payload.get("role_key") == "python_ai_ml" and payload.get("round_key") == "L3"
    )

    assert l3_payload["question_bank_files"] == ["AI/ML/ai_ml_engineering.json"]
    assert l3_payload["selection_strategy"] == "balanced_difficulty_v2"
    assert l3_payload["difficulty_mix"] == {"easy": 5, "medium": 5, "hard": 5}
    assert len(l3_payload["selected_questions"]) == 15
    assert len(l3_payload["selected_question_ids"]) == 15
    assert sum(1 for question in l3_payload["selected_questions"] if question["style"] == "debugging") >= 5

    frozen_ids = list(l3_payload["selected_question_ids"])
    with app.test_request_context(f"/mcq/start/{l3_session_id}"):
        MCQSessionService.init_session(l3_session_id, "python_ai_ml", "L3", force_reset=True)
        runtime_ids = [question["id"] for question in MCQSessionService.get_session_data(l3_session_id)["questions"]]
        clear_mcq_session_data(l3_session_id)

    assert runtime_ids == frozen_ids


@pytest.mark.parametrize(
    ("role_label", "role_key", "l3_bank"),
    [
        ("Java QA (5+ Years)", "java_qa", "qa/java_qa_advanced.json"),
        ("Java + AWS Development (5+ Years)", "java_aws", "cloud/java_aws_cloud.json"),
    ],
)
def test_java_senior_rounds_use_shared_l2_and_role_specific_l3(monkeypatch, role_label, role_key, l3_bank):
    GENERATED_TESTS.clear()
    MCQ_SESSION_REGISTRY.clear()

    monkeypatch.setattr(
        dashboard_routes,
        "send_candidate_test_links_email",
        lambda **kwargs: (False, "disabled for test"),
    )
    monkeypatch.setattr(
        dashboard_routes,
        "get_valid_graph_delegated_token",
        lambda _email: None,
    )
    monkeypatch.setattr(
        dashboard_routes,
        "get_valid_graph_delegated_token_from_session",
        lambda _oauth: None,
    )

    app = create_app()
    app.config["TESTING"] = True
    client = app.test_client()

    response = client.post(
        "/create-test",
        data={
            "name[]": ["Candidate Two"],
            "email[]": ["candidate.two@example.com"],
            "role[]": [role_label],
            "domain[]": ["None"],
        },
        follow_redirects=False,
    )

    assert response.status_code == 302

    l2_session_id, l2_payload = next(
        (key, payload)
        for key, payload in MCQ_SESSION_REGISTRY.items()
        if payload.get("role_key") == role_key and payload.get("round_key") == "L2"
    )
    _, l3_payload = next(
        (key, payload)
        for key, payload in MCQ_SESSION_REGISTRY.items()
        if payload.get("role_key") == role_key and payload.get("round_key") == "L3"
    )

    assert l2_payload["question_bank_files"] == ["java/java_senior_theory_debug.json"]
    assert l3_payload["question_bank_files"] == [l3_bank]
    assert l2_payload["selection_strategy"] == "balanced_difficulty_v2"
    assert l2_payload["difficulty_mix"] == {"easy": 5, "medium": 5, "hard": 5}
    assert len(l2_payload["selected_questions"]) == 15
    assert {question["topic"] for question in l2_payload["selected_questions"]}.issubset(
        {
            "Java Language and Type System",
            "Strings and Immutability",
            "Collections and Contracts",
            "Generics and Type Safety",
            "Exceptions and Resource Handling",
            "Streams Lambdas and Method References",
            "Concurrency and Executors",
            "JVM Memory and GC",
            "Practical Debugging",
        }
    )

    l2_text = " ".join(question["question"] for question in l2_payload["selected_questions"]).lower()
    for marker in ("selenium", "webdriver", "testng", "junit", "rest assured", "spring boot", "cloudwatch"):
        assert marker not in l2_text

    frozen_ids = list(l2_payload["selected_question_ids"])
    with app.test_request_context(f"/mcq/start/{l2_session_id}"):
        MCQSessionService.init_session(l2_session_id, role_key, "L2", force_reset=True)
        runtime_ids = [question["id"] for question in MCQSessionService.get_session_data(l2_session_id)["questions"]]
        clear_mcq_session_data(l2_session_id)

    assert runtime_ids == frozen_ids
