import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.utils import email_validator


class _FakeAnswer(list):
    pass


class _FakeResolver:
    def __init__(self, answers=None, should_raise=False):
        self.answers = answers if answers is not None else _FakeAnswer(["mx1.example.com"])
        self.should_raise = should_raise
        self.lifetime = None
        self.timeout = None

    def resolve(self, domain, record_type):
        if self.should_raise:
            raise RuntimeError("dns failure")
        assert domain == "example.com"
        assert record_type == "MX"
        return self.answers


class _FakeResolverModule:
    def __init__(self, resolver):
        self._resolver = resolver

    def Resolver(self):
        return self._resolver


def test_validate_email_accepts_valid_format_by_default(monkeypatch):
    monkeypatch.delenv("EMAIL_VALIDATE_DOMAIN", raising=False)
    monkeypatch.delenv("EMAIL_VALIDATE_MX", raising=False)

    valid, error = email_validator.validate_email("candidate.one@gmail.com")

    assert valid is True
    assert error == ""


def test_validate_email_rejects_unresolvable_domain_when_enabled(monkeypatch):
    monkeypatch.setenv("EMAIL_VALIDATE_DOMAIN", "true")
    monkeypatch.delenv("EMAIL_VALIDATE_MX", raising=False)
    monkeypatch.setattr(email_validator, "_domain_resolves", lambda _domain: False)

    valid, error = email_validator.validate_email("candidate.one@example.com")

    assert valid is False
    assert error == "Candidate email domain could not be verified."


def test_validate_email_rejects_missing_mx_when_enabled(monkeypatch):
    monkeypatch.delenv("EMAIL_VALIDATE_DOMAIN", raising=False)
    monkeypatch.setenv("EMAIL_VALIDATE_MX", "true")
    monkeypatch.setattr(email_validator, "_DNS_RESOLVER", _FakeResolverModule(_FakeResolver(should_raise=True)))

    valid, error = email_validator.validate_email("candidate.one@example.com")

    assert valid is False
    assert error == "Candidate email domain has no valid MX records."


def test_validate_email_accepts_domain_with_mx_when_enabled(monkeypatch):
    monkeypatch.delenv("EMAIL_VALIDATE_DOMAIN", raising=False)
    monkeypatch.setenv("EMAIL_VALIDATE_MX", "true")
    monkeypatch.setattr(email_validator, "_DNS_RESOLVER", _FakeResolverModule(_FakeResolver()))

    valid, error = email_validator.validate_email("candidate.one@example.com")

    assert valid is True
    assert error == ""
