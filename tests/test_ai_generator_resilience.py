import sys
from pathlib import Path
from types import SimpleNamespace

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.services import ai_generator


class _FailingModels:
    def generate_content(self, *args, **kwargs):
        raise RuntimeError("sdk unavailable")


class _SuccessfulModels:
    def __init__(self, text):
        self._text = text

    def generate_content(self, *args, **kwargs):
        return SimpleNamespace(text=self._text)


class _EmptyModels:
    def generate_content(self, *args, **kwargs):
        return SimpleNamespace(text="   ")


def test_rest_client_trusts_proxy_env_when_present(monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.internal:8080")
    monkeypatch.delenv("GEMINI_TRUST_ENV", raising=False)

    client = ai_generator._GeminiRestModels("test-key")

    assert client._session.trust_env is True


def test_generate_summary_uses_secondary_client_when_primary_fails(monkeypatch):
    summary_text = "AI summary from fallback client."
    fallback_client = ai_generator._FallbackGeminiClient(
        primary_client=SimpleNamespace(models=_FailingModels()),
        secondary_client=SimpleNamespace(models=_SuccessfulModels(summary_text)),
    )

    monkeypatch.setattr(ai_generator, "_get_ai_client", lambda: fallback_client)

    result = ai_generator.generate_evaluation_summary(
        {
            "name": "Alice Example",
            "role": "Python Developer",
            "summary": {"attempted_rounds": 1, "total_rounds": 1, "passed_rounds": 1, "failed_rounds": 0},
            "rounds": {},
        }
    )

    assert result == summary_text


def test_generate_summary_uses_secondary_client_when_primary_returns_empty(monkeypatch):
    summary_text = "AI summary from secondary client."
    fallback_client = ai_generator._FallbackGeminiClient(
        primary_client=SimpleNamespace(models=_EmptyModels()),
        secondary_client=SimpleNamespace(models=_SuccessfulModels(summary_text)),
    )

    monkeypatch.setattr(ai_generator, "_get_ai_client", lambda: fallback_client)

    result = ai_generator.generate_evaluation_summary(
        {
            "name": "Alice Example",
            "role": "Python Developer",
            "summary": {"attempted_rounds": 1, "total_rounds": 1, "passed_rounds": 1, "failed_rounds": 0},
            "rounds": {},
        }
    )

    assert result == summary_text


def test_gemini_env_value_prefers_repo_dotenv_override(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "stale-env-key")
    monkeypatch.setattr(
        ai_generator,
        "_get_dotenv_gemini_overrides",
        lambda: {"GEMINI_API_KEY": "fresh-dotenv-key"},
    )

    assert ai_generator._get_env_value("GEMINI_API_KEY") == "fresh-dotenv-key"


def test_non_gemini_env_value_keeps_process_env_precedence(monkeypatch):
    monkeypatch.setenv("SOME_OTHER_SETTING", "process-value")
    monkeypatch.setattr(
        ai_generator,
        "_get_dotenv_gemini_overrides",
        lambda: {"GEMINI_API_KEY": "fresh-dotenv-key"},
    )

    assert ai_generator._get_env_value("SOME_OTHER_SETTING") == "process-value"


def test_gemini_env_missing_in_dotenv_does_not_inherit_stale_process_flag(monkeypatch):
    monkeypatch.setenv("GEMINI_CLIENT_MODE", "rest")
    monkeypatch.setattr(
        ai_generator,
        "_get_dotenv_gemini_overrides",
        lambda: {"GEMINI_API_KEY": "fresh-dotenv-key"},
    )

    assert ai_generator._get_env_value("GEMINI_CLIENT_MODE") is None


def test_fallback_overall_summary_is_narrative_not_raw_score_dump():
    summary = ai_generator._build_fallback_summary(
        {
            "name": "Alice Example",
            "role": "Python Developer",
            "summary": {
                "attempted_rounds": 2,
                "total_rounds": 2,
                "passed_rounds": 1,
                "failed_rounds": 1,
                "overall_percentage": 63.33,
            },
            "rounds": {
                "L2": {
                    "round_label": "Python Theory",
                    "correct": 5,
                    "total": 15,
                    "percentage": 33.33,
                    "pass_threshold": 70,
                    "status": "FAIL",
                },
                "L4": {
                    "round_label": "Coding Challenge",
                    "correct": 8,
                    "total": 10,
                    "percentage": 80.0,
                    "pass_threshold": 70,
                    "status": "PASS",
                },
            },
        }
    )

    assert "Round-wise Detailed Insights" in summary
    assert "Status = FAIL;" not in summary
    assert "demonstrated strong command" in summary or "met the expected benchmark" in summary


def test_fallback_coding_summary_includes_assessment_and_heuristics():
    summary = ai_generator._build_fallback_coding_summary(
        {
            "round_label": "Coding Challenge (Python)",
            "status": "FAIL",
            "percentage": 20.0,
            "correct": 1,
            "total": 5,
            "language": "python",
            "question_title": "Merge Intervals",
            "question_text": "Merge all overlapping intervals.",
            "submitted_code": "def solve(intervals):\n    # TODO: finish\n    print(intervals)\n    return None\n",
            "overall_rounds": {},
        }
    )

    assert "Assessment:" in summary
    assert "TODO" in summary or "todo" in summary.lower()
    assert "print" in summary.lower()
