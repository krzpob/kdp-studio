from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

import httpx2
import openai
import pytest
from pydantic import BaseModel

from kdp_studio.config import ConfigError
from kdp_studio.providers.base import ProviderError, Usage
from kdp_studio.providers.openai_text import OpenAITextProvider
from kdp_studio.providers.registry import create_text_provider

REQUEST = httpx2.Request("POST", "https://api.openai.com/v1/responses")


class Answer(BaseModel):
    value: str


class FakeResponses:
    def __init__(self, result: Any = None, error: Exception | None = None) -> None:
        self.result = result
        self.error = error
        self.kwargs: dict[str, Any] = {}

    def parse(self, **kwargs: Any) -> Any:
        self.kwargs = kwargs
        if self.error:
            raise self.error
        return self.result


def _provider(responses: FakeResponses) -> OpenAITextProvider:
    client = cast(openai.OpenAI, SimpleNamespace(responses=responses))
    return OpenAITextProvider(model="gpt-test", client=client)


def _status_error(cls: type[openai.APIStatusError], status: int, body: str) -> Exception:
    response = httpx2.Response(status, request=REQUEST, json={"error": {"message": body}})
    return cls(body, response=response, body=None)


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
    ("error", "message"),
    [
        (
            _status_error(openai.RateLimitError, 429, "Rate limit reached"),
            "HTTP 429: Rate limit reached",
        ),
        (
            _status_error(openai.InternalServerError, 503, "overloaded"),
            "HTTP 503: overloaded",
        ),
        (openai.APIConnectionError(request=REQUEST), "brak połączenia z OpenAI"),
    ],
)
def test_api_errors_become_provider_errors(error: Exception, message: str) -> None:
    with pytest.raises(ProviderError, match=message):
        _provider(FakeResponses(error=error)).complete_json("s", "u", Answer)


def test_authentication_error_hides_key_fragment() -> None:
    error = _status_error(
        openai.AuthenticationError, 401, "Incorrect API key provided: sk-abc***wxyz"
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
