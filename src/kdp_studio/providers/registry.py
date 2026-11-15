"""Rejestr implementacji dostawców wybieranych z `config/settings.yaml` (spec §8.2).

Nowy dostawca = nowy moduł w `providers/` i wpis w słowniku poniżej. Moduły są
importowane leniwie, więc SDK dostawcy ładuje się dopiero, gdy jest używany.
"""

from __future__ import annotations

import importlib
from typing import cast

from kdp_studio.config import ConfigError
from kdp_studio.providers.base import TextProvider

TEXT_PROVIDERS: dict[str, str] = {
    "openai": "kdp_studio.providers.openai_text:OpenAITextProvider",
}


def create_text_provider(name: str, model: str) -> TextProvider:
    target = TEXT_PROVIDERS.get(name)
    if target is None:
        allowed = ", ".join(TEXT_PROVIDERS)
        raise ConfigError(f"nieznany dostawca tekstu '{name}'. Dostępni: {allowed}")
    module_name, class_name = target.split(":")
    provider_cls = getattr(importlib.import_module(module_name), class_name)
    return cast(TextProvider, provider_cls(model=model))
