"""Rejestr implementacji dostawców wybieranych z `config/settings.yaml` (spec §8.2).

Nowy dostawca = nowy moduł w `providers/` i wpis w słowniku poniżej. Moduły są
importowane leniwie, więc SDK dostawcy ładuje się dopiero, gdy jest używany.
"""

from __future__ import annotations

import importlib
from typing import cast

from kdp_studio.config import ConfigError
from kdp_studio.providers.base import ImageProvider, TextProvider

TEXT_PROVIDERS: dict[str, str] = {
    "openai": "kdp_studio.providers.openai_text:OpenAITextProvider",
}
IMAGE_PROVIDERS: dict[str, str] = {
    "openai": "kdp_studio.providers.openai_image:OpenAIImageProvider",
}


def _instantiate(registry: dict[str, str], kind: str, name: str, model: str) -> object:
    target = registry.get(name)
    if target is None:
        allowed = ", ".join(registry)
        raise ConfigError(f"nieznany dostawca {kind} '{name}'. Dostępni: {allowed}")
    module_name, class_name = target.split(":")
    return getattr(importlib.import_module(module_name), class_name)(model=model)


def create_text_provider(name: str, model: str) -> TextProvider:
    return cast(TextProvider, _instantiate(TEXT_PROVIDERS, "tekstu", name, model))


def create_image_provider(name: str, model: str) -> ImageProvider:
    return cast(ImageProvider, _instantiate(IMAGE_PROVIDERS, "obrazów", name, model))
