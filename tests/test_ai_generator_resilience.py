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
