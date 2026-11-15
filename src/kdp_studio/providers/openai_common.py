"""Wspólne elementy adapterów OpenAI: klient, klasyfikacja i opis błędów."""

from __future__ import annotations

import os

import openai

from kdp_studio.config import ConfigError

INSUFFICIENT_QUOTA = "insufficient_quota"
MODERATION_BLOCKED = "moderation_blocked"
_TRANSIENT_STATUSES = {408, 409, 429}


def default_client() -> openai.OpenAI:
    if not os.environ.get("OPENAI_API_KEY"):
        raise ConfigError(
            "brak OPENAI_API_KEY. Ustaw zmienną środowiskową albo dodaj ją do pliku .env"
        )
    # Ponowienia robi call_with_retries, bo SDK ponawia też trwałe 429 (brak środków).
    return openai.OpenAI(max_retries=0)


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


def is_fatal(error: openai.OpenAIError) -> bool:
    """Czy błąd dotyczy całego przebiegu, a nie jednego zapytania."""
    if isinstance(error, openai.APIStatusError) and error.code == MODERATION_BLOCKED:
        return False
    return openai_retry_decision(error) is False


def describe_openai_error(error: openai.OpenAIError) -> str:
    """Opis błędu bez treści, która mogłaby zawierać fragment klucza API (NFR-10)."""
    if isinstance(error, openai.AuthenticationError):
        return "OpenAI odrzuciło klucz API (HTTP 401). Sprawdź OPENAI_API_KEY"
    if isinstance(error, openai.APIStatusError) and error.code == INSUFFICIENT_QUOTA:
        return (
            "brak środków na koncie OpenAI API (insufficient_quota). "
            "Doładuj je na platform.openai.com w Settings → Billing"
        )
    if isinstance(error, openai.APIStatusError) and error.code == MODERATION_BLOCKED:
        return f"OpenAI odrzuciło prompt w moderacji (moderation_blocked): {_api_message(error)}"
    if isinstance(error, openai.APIStatusError):
        return f"OpenAI zwróciło HTTP {error.status_code}: {_api_message(error)}"
    if isinstance(error, openai.APIConnectionError):
        return "brak połączenia z OpenAI (po ponowieniach)"
    if isinstance(error, openai.LengthFinishReasonError):
        return "odpowiedź OpenAI została ucięta (limit długości)"
    if isinstance(error, openai.ContentFilterFinishReasonError):
        return "OpenAI zablokowało odpowiedź filtrem treści"
    return f"błąd OpenAI: {type(error).__name__}"


def usage_from(response_usage: object | None) -> tuple[int, int]:
    """(input_tokens, output_tokens) z obiektu `usage` odpowiedzi SDK albo (0, 0)."""
    if response_usage is None:
        return 0, 0
    return (
        int(getattr(response_usage, "input_tokens", 0) or 0),
        int(getattr(response_usage, "output_tokens", 0) or 0),
    )
