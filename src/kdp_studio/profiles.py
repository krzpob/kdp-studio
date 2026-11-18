"""FR-12: podgląd dostępnych profili wieku, stylu i formatu oraz rynków (FR-19)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Literal, Protocol, get_args

from kdp_studio.config import AppConfig, StyleProfile

ProfileKind = Literal["age", "style", "format", "market"]
PROFILE_KINDS: tuple[ProfileKind, ...] = get_args(ProfileKind)

_HEADERS: dict[ProfileKind, str] = {
    "age": "Wiek (--age)",
    "style": "Styl (--style)",
    "format": "Format (--format)",
    "market": "Rynek (--market)",
}


class _Described(Protocol):
    @property
    def name(self) -> str: ...
    @property
    def description(self) -> str: ...


def _profiles(config: AppConfig, kind: ProfileKind) -> Mapping[str, _Described]:
    if kind == "age":
        return config.ages
    if kind == "style":
        return config.styles
    if kind == "format":
        return config.formats
    return config.markets.markets


def _notes(profile: _Described, is_default: bool) -> list[str]:
    notes: list[str] = []
    if isinstance(profile, StyleProfile) and profile.allowed_ages is not None:
        notes.append(f"Tylko dla wieku: {', '.join(profile.allowed_ages)}.")
    if is_default:
        notes.append("Domyślny.")
    return notes


def format_profiles(
    config: AppConfig,
    kinds: tuple[ProfileKind, ...] = PROFILE_KINDS,
    default_format: str = "letter",
) -> list[str]:
    """Linie do wypisania: nagłówek grupy, potem `klucz  Nazwa: opis. Uwagi.`.

    `default_format` z CLI; domyślny rynek to `default_market` z settings.yaml.
    """
    lines: list[str] = []
    for kind in kinds:
        profiles = _profiles(config, kind)
        width = max(len(key) for key in profiles) + 2
        if lines:
            lines.append("")
        lines.append(_HEADERS[kind])
        for key, profile in profiles.items():
            description = " ".join(profile.description.split())
            default = (kind == "format" and key == default_format) or (
                kind == "market" and key == config.settings.default_market
            )
            notes = _notes(profile, is_default=default)
            text = " ".join([f"{profile.name}: {description}", *notes])
            lines.append(f"  {key:<{width}}{text}")
    return lines
