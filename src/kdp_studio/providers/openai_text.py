"""Adapter OpenAI dla TextProvider: Responses API ze structured outputs (spec §8.3)."""

from __future__ import annotations

import openai

from kdp_studio.providers.base import ProviderError, SchemaT, Usage
from kdp_studio.providers.openai_common import (
    default_client,
    describe_openai_error,
    openai_retry_decision,
    usage_from,
)
from kdp_studio.providers.retry import RetryPolicy, call_with_retries

__all__ = ["OpenAITextProvider", "describe_openai_error", "openai_retry_decision"]


class OpenAITextProvider:
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

    def complete_json(self, system: str, user: str, schema: type[SchemaT]) -> tuple[SchemaT, Usage]:
        try:
            response = call_with_retries(
                lambda: self._client.responses.parse(
                    model=self.model,
                    instructions=system,
                    input=user,
                    text_format=schema,
                ),
                retry_after=openai_retry_decision,
                policy=self._retry_policy,
            )
        except openai.OpenAIError as e:
            raise ProviderError(describe_openai_error(e)) from e

        parsed = response.output_parsed
        if parsed is None:
            raise ProviderError("OpenAI nie zwróciło odpowiedzi zgodnej ze schematem (odmowa?)")
        input_tokens, output_tokens = usage_from(response.usage)
        return parsed, Usage(input_tokens=input_tokens, output_tokens=output_tokens)
