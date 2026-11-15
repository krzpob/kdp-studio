from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

import httpx2
import openai
import pytest
from pydantic import BaseModel

from kdp_studio.config import ConfigError
from kdp_studio.providers.base import ProviderError, Usage
from kdp_studio.providers.openai_text import OpenAITextProvider, openai_retry_decision
from kdp_studio.providers.registry import create_text_provider
from kdp_studio.providers.retry import RetryPolicy

REQUEST = httpx2.Request("POST", "https://api.openai.com/v1/responses")


class Answer(BaseModel):
    value: str


class FakeResponses:
    """Kolejne wywołania `parse` zwracają albo rzucają kolejne elementy `outcomes`."""

    def __init__(self, result: Any = None, error: Exception | None = None) -> None:
        self.outcomes: list[Any] = [error if error is not None else result]
        self.calls = 0
        self.kwargs: dict[str, Any] = {}

    @classmethod
    def sequence(cls, *outcomes: Any) -> FakeResponses:
        fake = cls()
        fake.outcomes = list(outcomes)
        return fake

    def parse(self, **kwargs: Any) -> Any:
        self.kwargs = kwargs
        outcome = self.outcomes[min(self.calls, len(self.outcomes) - 1)]
        self.calls += 1
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


NO_WAIT = RetryPolicy(initial_delay_s=0)


def _provider(responses: FakeResponses) -> OpenAITextProvider:
    client = cast(openai.OpenAI, SimpleNamespace(responses=responses))
    return OpenAITextProvider(model="gpt-test", client=client, retry_policy=NO_WAIT)


def _status_error(
    cls: type[openai.APIStatusError],
    status: int,
    message: str,
    code: str | None = None,
    headers: dict[str, str] | None = None,
) -> openai.APIStatusError:
    """Błąd zbudowany tak jak w SDK: komunikat z prefiksem, `body` = obiekt `error`."""
    data = {"message": message, "type": "error", "code": code}
    response = httpx2.Response(status, request=REQUEST, json={"error": data}, headers=headers)
    return cls(f"Error code: {status} - {data}", response=response, body=data)


def _ok(value: str = "ok") -> Any:
    return SimpleNamespace(output_parsed=Answer(value=value), usage=None)


def test_returns_parsed_output_and_usage() -> None:
    result = SimpleNamespace(
        output_parsed=Answer(value="ok"),
        usage=SimpleNamespace(input_tokens=120, output_tokens=30),
    )
    responses = FakeResponses(result)
    parsed, usage = _provider(responses).complete_json("sys", "usr", Answer)
    assert parsed == Answer(value="ok")
    assert usage == Usage(input_tokens=120, output_tokens=30)
    assert responses.kwargs == {
        "model": "gpt-test",
        "instructions": "sys",
        "input": "usr",
        "text_format": Answer,
    }


def test_missing_usage_is_zero() -> None:
    result = SimpleNamespace(output_parsed=Answer(value="ok"), usage=None)
    _, usage = _provider(FakeResponses(result)).complete_json("s", "u", Answer)
    assert usage == Usage()


def test_refusal_is_provider_error() -> None:
    result = SimpleNamespace(output_parsed=None, usage=None)
    with pytest.raises(ProviderError, match="zgodnej ze schematem"):
        _provider(FakeResponses(result)).complete_json("s", "u", Answer)


@pytest.mark.parametrize(
    ("error", "message", "calls"),
    [
        (
            _status_error(openai.RateLimitError, 429, "Rate limit reached", "rate_limit_exceeded"),
            "OpenAI zwróciło HTTP 429: Rate limit reached",
            3,
        ),
        (
            _status_error(openai.InternalServerError, 503, "overloaded"),
            "OpenAI zwróciło HTTP 503: overloaded",
            3,
        ),
        (openai.APIConnectionError(request=REQUEST), "brak połączenia z OpenAI", 3),
        (
            _status_error(openai.BadRequestError, 400, "Invalid schema"),
            "OpenAI zwróciło HTTP 400: Invalid schema",
            1,
        ),
    ],
)
def test_api_errors_become_provider_errors(error: Exception, message: str, calls: int) -> None:
    responses = FakeResponses(error=error)
    with pytest.raises(ProviderError) as exc:
        _provider(responses).complete_json("s", "u", Answer)
    assert str(exc.value).startswith(message)
    assert "Error code" not in str(exc.value)
    assert responses.calls == calls


def test_insufficient_quota_is_not_retried() -> None:
    error = _status_error(
        openai.RateLimitError, 429, "You have no credits remaining.", "insufficient_quota"
    )
    responses = FakeResponses(error=error)
    with pytest.raises(ProviderError, match="brak środków na koncie OpenAI API") as exc:
        _provider(responses).complete_json("s", "u", Answer)
    assert "Settings → Billing" in str(exc.value)
    assert responses.calls == 1


def test_transient_error_then_success() -> None:
    responses = FakeResponses.sequence(
        _status_error(openai.InternalServerError, 502, "bad gateway"), _ok("second")
    )
    parsed, _ = _provider(responses).complete_json("s", "u", Answer)
    assert parsed == Answer(value="second")
    assert responses.calls == 2


@pytest.mark.parametrize(
    ("error", "decision"),
    [
        (_status_error(openai.RateLimitError, 429, "slow down", "rate_limit_exceeded"), True),
        (
            _status_error(openai.RateLimitError, 429, "slow down", headers={"retry-after": "7"}),
            7.0,
        ),
        (_status_error(openai.RateLimitError, 429, "no money", "insufficient_quota"), False),
        (_status_error(openai.InternalServerError, 500, "oops"), True),
        (_status_error(openai.ConflictError, 409, "locked"), True),
        (_status_error(openai.AuthenticationError, 401, "bad key"), False),
        (_status_error(openai.NotFoundError, 404, "no such model"), False),
        (openai.APITimeoutError(request=REQUEST), True),
        (ValueError("not an API error"), False),
    ],
)
def test_retry_decision(error: Exception, decision: float | bool) -> None:
    assert openai_retry_decision(error) == decision
    assert type(openai_retry_decision(error)) is type(decision)


def test_authentication_error_hides_key_fragment() -> None:
    error = _status_error(
        openai.AuthenticationError,
        401,
        "Incorrect API key provided: sk-abc***wxyz",
        "invalid_api_key",
    )
    with pytest.raises(ProviderError) as exc:
        _provider(FakeResponses(error=error)).complete_json("s", "u", Answer)
    assert "sk-" not in str(exc.value)
    assert "HTTP 401" in str(exc.value)


def test_missing_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(ConfigError, match="brak OPENAI_API_KEY"):
        OpenAITextProvider(model="gpt-test")


def test_registry_creates_openai_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-real")
    provider = create_text_provider("openai", "gpt-test")
    assert isinstance(provider, OpenAITextProvider)
    assert provider.model == "gpt-test"


def test_registry_unknown_provider() -> None:
    with pytest.raises(ConfigError, match=r"nieznany dostawca tekstu 'gemini'\. Dostępni: openai"):
        create_text_provider("gemini", "x")
