"""Adapter OpenAI dla ImageProvider: Image API `images.generate` (spec §8.3, FR-05)."""

from __future__ import annotations

import base64
import binascii
from typing import Literal, cast

import openai

from kdp_studio.providers.base import (
    ImageRequest,
    ImageResult,
    ProviderError,
    Usage,
    png_dimensions,
)
from kdp_studio.providers.openai_common import (
    default_client,
    describe_openai_error,
    is_fatal,
    openai_retry_decision,
    usage_from,
)
from kdp_studio.providers.retry import RetryPolicy, call_with_retries

# Modele GPT Image przyjmują własne wymiary (wielokrotności 16, proporcje 1:3–3:1),
# więc zamiast przybliżenia 2:3 ze spec §8.3 dla 3:4 używamy dokładnych proporcji.
SIZES: dict[str, str] = {
    "1:1": "1024x1024",
    "3:4": "1152x1536",
    "4:3": "1536x1152",
    "2:3": "1024x1536",
    "3:2": "1536x1024",
}


OpenAIQuality = Literal["low", "medium", "high", "xhigh", "max", "auto"]
QUALITIES: tuple[str, ...] = ("low", "medium", "high", "xhigh", "max", "auto")


class OpenAIImageProvider:
    name = "openai"

    def __init__(
        self,
        model: str,
        client: openai.OpenAI | None = None,
        retry_policy: RetryPolicy | None = None,
    ) -> None:
        self.model = model
        self._client = client or default_client()
        self._retry_policy = retry_policy or RetryPolicy()

    def supported_aspects(self) -> list[str]:
        return list(SIZES)

    def generate(self, req: ImageRequest) -> ImageResult:
        size = SIZES.get(req.aspect)
        if size is None:
            raise ProviderError(f"OpenAI: brak rozmiaru dla proporcji {req.aspect}")
        if req.quality not in QUALITIES:
            raise ProviderError(f"OpenAI: nieobsługiwana jakość '{req.quality}'")
        quality = cast(OpenAIQuality, req.quality)
        try:
            response = call_with_retries(
                lambda: self._client.images.generate(
                    model=self.model,
                    prompt=req.prompt,
                    size=size,
                    quality=quality,
                    n=1,
                    output_format="png",
                    background="opaque",  # przezroczystość zamieniłaby tło w czerń w FR-06
                ),
                retry_after=openai_retry_decision,
                policy=self._retry_policy,
            )
        except openai.OpenAIError as e:
            raise ProviderError(describe_openai_error(e), fatal=is_fatal(e)) from e

        image = response.data[0] if response.data else None
        if image is None or not image.b64_json:
            raise ProviderError("OpenAI nie zwróciło obrazu", fatal=False)
        try:
            png = base64.b64decode(image.b64_json, validate=True)
            width, height = png_dimensions(png)
        except (binascii.Error, ValueError) as e:
            raise ProviderError(f"OpenAI zwróciło niepoprawny PNG: {e}", fatal=False) from e

        input_tokens, output_tokens = usage_from(response.usage)
        return ImageResult(
            png_bytes=png,
            width=width,
            height=height,
            usage=Usage(input_tokens=input_tokens, output_tokens=output_tokens),
            meta={
                "size": response.size or size,
                "quality": response.quality or req.quality,
                "revised_prompt": image.revised_prompt,
            },
        )
