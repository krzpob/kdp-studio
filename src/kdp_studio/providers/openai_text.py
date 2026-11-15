"""Adapter OpenAI dla TextProvider: Responses API ze structured outputs (spec §8.3)."""

from __future__ import annotations

import os

import openai

from kdp_studio.config import ConfigError
from kdp_studio.providers.base import ProviderError, SchemaT, Usage

DEFAULT_MAX_RETRIES = 3  # SDK ponawia 429, 5xx i błędy połączenia z backoffem


def describe_openai_error(error: openai.OpenAIError) -> str:
    """Opis błędu bez treści, która mogłaby zawierać fragment klucza API (NFR-10)."""
    if isinstance(error, openai.AuthenticationError):
        return "OpenAI odrzuciło klucz API (HTTP 401). Sprawdź OPENAI_API_KEY"
    if isinstance(error, openai.APIStatusError):
        return f"OpenAI zwróciło HTTP {error.status_code}: {error.message}"
    if isinstance(error, openai.APIConnectionError):
        return "brak połączenia z OpenAI (po ponowieniach)"
    if isinstance(error, openai.LengthFinishReasonError):
        return "odpowiedź OpenAI została ucięta (limit długości)"
    if isinstance(error, openai.ContentFilterFinishReasonError):
        return "OpenAI zablokowało odpowiedź filtrem treści"
    return f"błąd OpenAI: {type(error).__name__}"


class OpenAITextProvider:
    name = "openai"

    def __init__(
        self,
        model: str,
        client: openai.OpenAI | None = None,
        max_retries: int = DEFAULT_MAX_RETRIES,
    ) -> None:
        if client is None:
            if not os.environ.get("OPENAI_API_KEY"):
                raise ConfigError(
                    "brak OPENAI_API_KEY. Ustaw zmienną środowiskową albo dodaj ją do pliku .env"
                )
            client = openai.OpenAI(max_retries=max_retries)
        self.model = model
        self._client = client

    def complete_json(self, system: str, user: str, schema: type[SchemaT]) -> tuple[SchemaT, Usage]:
        try:
            response = self._client.responses.parse(
                model=self.model,
                instructions=system,
                input=user,
                text_format=schema,
            )
        except openai.OpenAIError as e:
            raise ProviderError(describe_openai_error(e)) from e

        parsed = response.output_parsed
        if parsed is None:
            raise ProviderError("OpenAI nie zwróciło odpowiedzi zgodnej ze schematem (odmowa?)")
        usage = (
            Usage(
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
            )
            if response.usage
            else Usage()
        )
        return parsed, usage
