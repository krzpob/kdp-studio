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


def _edit(provider: OpenAIImageProvider) -> Any:
    return provider.generate(
        ImageRequest(
            prompt="color it", aspect="1:1", quality="low", reference_image=make_png(64, 64)
        )
    )


@pytest.mark.parametrize(
    "error",
    [
        _status_error(
            openai.BadRequestError,
            400,
            "The model 'gpt-image-2.6-flare' does not support the 'input_fidelity' parameter.",
        ),
        openai.BadRequestError(
            "Error code: 400",
            response=httpx2.Response(400, request=REQUEST),
            body={"message": "Unsupported parameter.", "param": "input_fidelity"},
        ),
    ],
    ids=["message", "param"],
)
def test_edit_retries_without_unsupported_input_fidelity(error: Exception) -> None:
    images = FakeImages(error, _response(make_png(1024, 1024), size="1024x1024"))
    provider = _provider(images)
    result = _edit(provider)
    assert (result.width, result.height) == (1024, 1024)
    first, second = images.calls
    assert first["input_fidelity"] == "high"
    assert isinstance(second["input_fidelity"], openai.Omit)  # SDK nie wysyła parametru
    # Adapter pamięta odmowę: kolejne zapytanie (np. tył okładki) od razu bez parametru.
    _edit(provider)
    assert isinstance(images.calls[2]["input_fidelity"], openai.Omit)


def test_other_bad_request_on_edit_is_not_retried() -> None:
    error = _status_error(openai.BadRequestError, 400, "Invalid size.")
    images = FakeImages(error)
    with pytest.raises(ProviderError, match="Invalid size"):
        _edit(_provider(images))
    assert len(images.calls) == 1


def test_generate_never_drops_parameters_on_bad_request() -> None:
    error = _status_error(
        openai.BadRequestError, 400, "does not support the 'input_fidelity' parameter."
    )
    images = FakeImages(error)
    with pytest.raises(ProviderError):
        _generate(images)
    assert len(images.calls) == 1


def _outpaint(provider: OpenAIImageProvider) -> Any:
    return provider.generate(
        ImageRequest(
            prompt="extend it",
            aspect="4:3",
            quality="low",
            reference_image=make_png(64, 48),
            mask=make_png(64, 48),
        )
    )


def test_mask_goes_to_the_edit_endpoint() -> None:
    images = FakeImages(_response(make_png(1536, 1152), size="1536x1152"))
    _outpaint(_provider(images))
    (call,) = images.calls
    assert call["endpoint"] == "edit" and call["size"] == "1536x1152"
    assert call["mask"][0] == "mask.png" and call["mask"][2] == "image/png"
    # Bez maski parametr nie trafia do zapytania.
    images = FakeImages(_response(make_png(1024, 1024), size="1024x1024"))
    _edit(_provider(images))
    assert isinstance(images.calls[0]["mask"], openai.Omit)


def test_rejected_mask_and_input_fidelity_are_dropped_and_remembered() -> None:
    fidelity = _status_error(
        openai.BadRequestError, 400, "The model does not support the 'input_fidelity' parameter."
    )
    mask = _status_error(openai.BadRequestError, 400, "The model does not support 'mask'.")
    ok = _response(make_png(1536, 1152), size="1536x1152")
    images = FakeImages(fidelity, mask, ok)
    provider = _provider(images)
    _outpaint(provider)
    first, second, third = images.calls
    assert first["input_fidelity"] == "high" and not isinstance(first["mask"], openai.Omit)
    assert isinstance(second["input_fidelity"], openai.Omit)
    assert not isinstance(second["mask"], openai.Omit)
    assert isinstance(third["mask"], openai.Omit)  # samo płótno, bez maski
    _outpaint(provider)
    assert isinstance(images.calls[3]["mask"], openai.Omit)
    assert isinstance(images.calls[3]["input_fidelity"], openai.Omit)
