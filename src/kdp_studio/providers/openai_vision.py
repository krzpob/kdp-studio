"""Adapter OpenAI dla VisionProvider: Responses API z obrazem i structured outputs (FR-07)."""

from __future__ import annotations

import base64
from typing import Any, Literal

import openai

from kdp_studio.providers.base import ProviderError, SchemaT, Usage
from kdp_studio.providers.openai_common import (
    default_client,
    describe_openai_error,
    is_fatal,
    openai_retry_decision,
    usage_from,
)
from kdp_studio.providers.retry import RetryPolicy, call_with_retries

USER_TEXT = "Assess this coloring book page."
# "high": model widzi obraz w pełnej rozdzielczości kafelków, potrzebnej do wypatrzenia
# przerw w konturach i drobnego tekstu. Strona 1-bitowa to mały plik PNG.
Detail = Literal["low", "high", "auto"]


class OpenAIVisionProvider:
    name = "openai"

    def __init__(
        self,
        model: str,
        client: openai.OpenAI | None = None,
        retry_policy: RetryPolicy | None = None,
        detail: Detail = "high",
    ) -> None:
        self.model = model
        self.detail: Detail = detail
        self._client = client or default_client()
        self._retry_policy = retry_policy or RetryPolicy()

    def _input(self, image_png: bytes) -> list[Any]:
        data_url = "data:image/png;base64," + base64.b64encode(image_png).decode("ascii")
        return [
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": USER_TEXT},
                    {"type": "input_image", "image_url": data_url, "detail": self.detail},
                ],
            }
        ]

    def assess(
        self, image_png: bytes, instructions: str, schema: type[SchemaT]
    ) -> tuple[SchemaT, Usage]:
        try:
            response = call_with_retries(
                lambda: self._client.responses.parse(
                    model=self.model,
                    instructions=instructions,
                    input=self._input(image_png),
                    text_format=schema,
                ),
                retry_after=openai_retry_decision,
                policy=self._retry_policy,
            )
        except openai.OpenAIError as e:
            raise ProviderError(describe_openai_error(e), fatal=is_fatal(e)) from e

        parsed = response.output_parsed
        if parsed is None:
            # Odmowa oceny dotyczy tej jednej strony, nie całego przebiegu.
            raise ProviderError("OpenAI nie oceniło strony (odmowa?)", fatal=False)
        input_tokens, output_tokens = usage_from(response.usage)
        return parsed, Usage(input_tokens=input_tokens, output_tokens=output_tokens)
