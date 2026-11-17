from __future__ import annotations

import base64
from types import SimpleNamespace
from typing import Any, cast

import httpx2
import openai
import pytest

from kdp_studio.config import ConfigError
from kdp_studio.providers.base import ImageRequest, ProviderError, Usage, png_dimensions
from kdp_studio.providers.fake import make_png
from kdp_studio.providers.openai_image import SIZES, OpenAIImageProvider
from kdp_studio.providers.registry import create_image_provider
from kdp_studio.providers.retry import RetryPolicy

REQUEST = httpx2.Request("POST", "https://api.openai.com/v1/images/generations")


class FakeImages:
    def __init__(self, *outcomes: Any) -> None:
        self.outcomes = list(outcomes)
        self.calls: list[dict[str, Any]] = []

    def generate(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        outcome = self.outcomes[min(len(self.calls), len(self.outcomes)) - 1]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    def edit(self, **kwargs: Any) -> Any:
        return self.generate(endpoint="edit", **kwargs)


def _provider(images: FakeImages) -> OpenAIImageProvider:
    client = cast(openai.OpenAI, SimpleNamespace(images=images))
    return OpenAIImageProvider(
        model="gpt-image-test", client=client, retry_policy=RetryPolicy(initial_delay_s=0)
    )


def _response(png: bytes | None = None, **extra: Any) -> Any:
    data = base64.b64encode(png if png is not None else make_png(1152, 1536)).decode()
    return SimpleNamespace(
        data=[SimpleNamespace(b64_json=data, revised_prompt="revised")],
        usage=SimpleNamespace(input_tokens=200, output_tokens=4000),
        size=extra.get("size", "1152x1536"),
        quality=extra.get("quality", "medium"),
    )


def _status_error(
    cls: type[openai.APIStatusError], status: int, message: str, code: str | None = None
) -> openai.APIStatusError:
    data = {"message": message, "type": "error", "code": code}
    response = httpx2.Response(status, request=REQUEST, json={"error": data})
    return cls(f"Error code: {status} - {data}", response=response, body=data)


def _generate(images: FakeImages, aspect: str = "3:4") -> Any:
    return _provider(images).generate(
        ImageRequest(prompt="a bear", aspect=aspect, quality="medium")
    )


def test_generate_returns_png_and_usage() -> None:
    images = FakeImages(_response())
    result = _generate(images)
    assert png_dimensions(result.png_bytes) == (1152, 1536)
    assert (result.width, result.height) == (1152, 1536)
    assert result.usage == Usage(input_tokens=200, output_tokens=4000)
    assert result.meta == {"size": "1152x1536", "quality": "medium", "revised_prompt": "revised"}
    assert images.calls == [
        {
            "model": "gpt-image-test",
            "prompt": "a bear",
            "size": "1152x1536",
            "quality": "medium",
            "n": 1,
            "output_format": "png",
            "background": "opaque",
        }
    ]


@pytest.mark.parametrize(("aspect", "size"), [("1:1", "1024x1024"), ("3:4", "1152x1536")])
def test_aspect_maps_to_size(aspect: str, size: str) -> None:
    images = FakeImages(_response())
    _generate(images, aspect)
    assert images.calls[0]["size"] == size


@pytest.mark.parametrize(("aspect", "size"), sorted(SIZES.items()))
def test_sizes_respect_model_limits(aspect: str, size: str) -> None:
    width, height = (int(x) for x in size.split("x"))
    a, b = (int(x) for x in aspect.split(":"))
    assert width % 16 == 0 and height % 16 == 0
    assert width * b == height * a  # dokładne proporcje
    assert 655_360 <= width * height <= 8_294_400


def test_unsupported_aspect_is_fatal() -> None:
    with pytest.raises(ProviderError, match="brak rozmiaru dla proporcji 5:7") as exc:
        _generate(FakeImages(_response()), aspect="5:7")
    assert exc.value.fatal


def test_unsupported_quality_is_fatal() -> None:
    provider = _provider(FakeImages(_response()))
    with pytest.raises(ProviderError, match="jakość 'ultra'"):
        provider.generate(ImageRequest(prompt="x", aspect="1:1", quality="ultra"))


@pytest.mark.parametrize(
    ("error", "fatal", "calls", "message"),
    [
        (
            _status_error(
                openai.BadRequestError, 400, "Your request was rejected", "moderation_blocked"
            ),
            False,
            1,
            "odrzuciło prompt w moderacji",
        ),
        (_status_error(openai.InternalServerError, 503, "overloaded"), False, 3, "HTTP 503"),
        (openai.APIConnectionError(request=REQUEST), False, 3, "brak połączenia"),
        (_status_error(openai.AuthenticationError, 401, "bad key sk-x***y"), True, 1, "HTTP 401"),
        (
            _status_error(openai.RateLimitError, 429, "no credits", "insufficient_quota"),
            True,
            1,
            "brak środków",
        ),
        (_status_error(openai.NotFoundError, 404, "model not found"), True, 1, "HTTP 404"),
    ],
)
def test_errors_are_classified(error: Exception, fatal: bool, calls: int, message: str) -> None:
    images = FakeImages(error)
    with pytest.raises(ProviderError, match=message) as exc:
        _generate(images)
    assert exc.value.fatal is fatal
    assert len(images.calls) == calls
    assert "sk-" not in str(exc.value)


def test_transient_error_then_success() -> None:
    images = FakeImages(_status_error(openai.RateLimitError, 429, "slow down"), _response())
    assert _generate(images).width == 1152
    assert len(images.calls) == 2


@pytest.mark.parametrize(
    "response",
    [
        SimpleNamespace(data=[], usage=None, size=None, quality=None),
        SimpleNamespace(
            data=[SimpleNamespace(b64_json=None, revised_prompt=None)],
            usage=None,
            size=None,
            quality=None,
        ),
        _response(png=b"GIF89a not a png"),
        SimpleNamespace(
            data=[SimpleNamespace(b64_json="%%%", revised_prompt=None)],
            usage=None,
            size=None,
            quality=None,
        ),
    ],
)
def test_bad_image_payload_is_page_error(response: Any) -> None:
    with pytest.raises(ProviderError) as exc:
        _generate(FakeImages(response))
    assert not exc.value.fatal


def test_missing_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(ConfigError, match="brak OPENAI_API_KEY"):
        OpenAIImageProvider(model="gpt-image-test")


def test_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-real")
    provider = create_image_provider("openai", "gpt-image-test")
    assert isinstance(provider, OpenAIImageProvider)
    assert provider.model == "gpt-image-test"
    with pytest.raises(ConfigError, match=r"nieznany dostawca obrazów 'gemini'\. Dostępni: openai"):
        create_image_provider("gemini", "x")


def test_png_dimensions_rejects_non_png() -> None:
    with pytest.raises(ValueError, match="nie są obrazem PNG"):
        png_dimensions(b"\x89PNG\r\n\x1a\nshort")


def test_reference_image_uses_the_edit_endpoint() -> None:
    images = FakeImages(_response(make_png(1024, 1024), size="1024x1024"))
    reference = make_png(64, 64, frame=True)
    result = _provider(images).generate(
        ImageRequest(prompt="color it", aspect="1:1", quality="low", reference_image=reference)
    )
    assert (result.width, result.height) == (1024, 1024)
    (call,) = images.calls
    assert call["endpoint"] == "edit"
    assert call["image"] == ("reference.png", reference, "image/png")
    assert call["input_fidelity"] == "high"
    assert (call["size"], call["quality"], call["background"]) == ("1024x1024", "low", "opaque")
