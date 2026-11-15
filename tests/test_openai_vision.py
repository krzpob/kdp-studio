from __future__ import annotations

import base64
from types import SimpleNamespace
from typing import cast

import openai
import pytest
from pydantic import BaseModel

from kdp_studio.providers.base import ProviderError, Usage
from kdp_studio.providers.openai_vision import OpenAIVisionProvider
from kdp_studio.providers.registry import VISION_PROVIDERS, create_vision_provider
from kdp_studio.providers.retry import RetryPolicy
from tests.test_openai_text import FakeResponses, _status_error


class Verdict(BaseModel):
    passed: bool


def _provider(responses: FakeResponses) -> OpenAIVisionProvider:
    client = cast(openai.OpenAI, SimpleNamespace(responses=responses))
    return OpenAIVisionProvider(
        model="gpt-test", client=client, retry_policy=RetryPolicy(initial_delay_s=0)
    )


def test_sends_image_as_data_url_with_instructions() -> None:
    result = SimpleNamespace(
        output_parsed=Verdict(passed=True),
        usage=SimpleNamespace(input_tokens=3600, output_tokens=120),
    )
    responses = FakeResponses(result)
    parsed, usage = _provider(responses).assess(b"\x89PNG-bytes", "check it", Verdict)

    assert parsed == Verdict(passed=True)
    assert usage == Usage(input_tokens=3600, output_tokens=120)
    kwargs = responses.kwargs
    assert kwargs["model"] == "gpt-test"
    assert kwargs["instructions"] == "check it"
    assert kwargs["text_format"] is Verdict
    [message] = kwargs["input"]
    text, image = message["content"]
    assert text["type"] == "input_text"
    assert image["type"] == "input_image"
    assert image["detail"] == "high"
    encoded = base64.b64encode(b"\x89PNG-bytes").decode("ascii")
    assert image["image_url"] == f"data:image/png;base64,{encoded}"


def test_refusal_fails_only_the_page() -> None:
    responses = FakeResponses(SimpleNamespace(output_parsed=None, usage=None))
    with pytest.raises(ProviderError) as info:
        _provider(responses).assess(b"png", "x", Verdict)
    assert not info.value.fatal


def test_transient_error_after_retries_is_not_fatal() -> None:
    error = _status_error(openai.InternalServerError, 500, "overloaded")
    responses = FakeResponses(error=error)
    with pytest.raises(ProviderError) as info:
        _provider(responses).assess(b"png", "x", Verdict)
    assert not info.value.fatal
    assert responses.calls == 3


def test_bad_key_is_fatal_and_hides_the_message() -> None:
    error = _status_error(openai.AuthenticationError, 401, "Incorrect API key: sk-abc***xyz")
    with pytest.raises(ProviderError) as info:
        _provider(FakeResponses(error=error)).assess(b"png", "x", Verdict)
    assert info.value.fatal
    assert "sk-abc" not in str(info.value)


def test_registry_knows_openai_vision(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    assert "openai" in VISION_PROVIDERS
    provider = create_vision_provider("openai", "gpt-6-luna")
    assert isinstance(provider, OpenAIVisionProvider)
    assert provider.model == "gpt-6-luna"
