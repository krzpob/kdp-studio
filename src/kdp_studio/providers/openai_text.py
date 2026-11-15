"""Adapter OpenAI dla TextProvider: Responses API ze structured outputs (spec §8.3)."""

from __future__ import annotations

import os

import openai

from kdp_studio.config import ConfigError
from kdp_studio.providers.base import ProviderError, SchemaT, Usage
from kdp_studio.providers.retry import RetryPolicy, call_with_retries

INSUFFICIENT_QUOTA = "insufficient_quota"
_TRANSIENT_STATUSES = {408, 409, 429}


def _api_message(error: openai.APIStatusError) -> str:
    """Treść błędu z odpowiedzi API, bez prefiksu SDK „Error code: NNN - {...}”."""
    body = error.body
    if isinstance(body, dict) and isinstance(body.get("message"), str):
        return str(body["message"])
    return error.message


def _retry_after_header(error: openai.APIStatusError) -> float | None:
    try:
        return float(error.response.headers.get("retry-after", ""))
    except ValueError:
        return None


def openai_retry_decision(error: Exception) -> float | bool:
    """False: błąd trwały. True albo sekundy z Retry-After: błąd przejściowy (FR-05)."""
    if isinstance(error, openai.APIConnectionError):  # w tym timeout
        return True
    if isinstance(error, openai.APIStatusError):
        if error.code == INSUFFICIENT_QUOTA:  # brak środków nie minie po ponowieniu
            return False
        if error.status_code in _TRANSIENT_STATUSES or error.status_code >= 500:
            suggested = _retry_after_header(error)
            return True if suggested is None else suggested
    return False


def describe_openai_error(error: openai.OpenAIError) -> str:
    """Opis błędu bez treści, która mogłaby zawierać fragment klucza API (NFR-10)."""
    if isinstance(error, openai.AuthenticationError):
        return "OpenAI odrzuciło klucz API (HTTP 401). Sprawdź OPENAI_API_KEY"
    if isinstance(error, openai.APIStatusError) and error.code == INSUFFICIENT_QUOTA:
        return (
            "brak środków na koncie OpenAI API (insufficient_quota). "
            "Doładuj je na platform.openai.com w Settings → Billing"
        )
    if isinstance(error, openai.APIStatusError):
        return f"OpenAI zwróciło HTTP {error.status_code}: {_api_message(error)}"
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
        retry_policy: RetryPolicy | None = None,
    ) -> None:
        if client is None:
            if not os.environ.get("OPENAI_API_KEY"):
                raise ConfigError(
                    "brak OPENAI_API_KEY. Ustaw zmienną środowiskową albo dodaj ją do pliku .env"
                )
            # Ponowienia robi call_with_retries, bo SDK ponawia też trwałe 429 (brak środków).
            client = openai.OpenAI(max_retries=0)
        self.model = model
        self._client = client
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
        usage = (
            Usage(
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
            )
            if response.usage
            else Usage()
        )
        return parsed, usage
