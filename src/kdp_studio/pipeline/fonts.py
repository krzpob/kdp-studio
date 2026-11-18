"""Czcionki z repozytorium (`assets/fonts`, SIL OFL) dla napisów wpisywanych przez program."""

from __future__ import annotations

from functools import cache
from pathlib import Path

from fontTools.ttLib import TTFont, TTLibError
from PIL import ImageFont


class FontError(Exception):
    """Brak czcionki albo jej wariantu."""


def load_font(path: Path, size: int, variation: str | None = None) -> ImageFont.FreeTypeFont:
    """Czcionka w rozmiarze `size` px; `variation` to nazwa wariantu fontu zmiennego."""
    try:
        font = ImageFont.truetype(str(path), max(1, size))
    except OSError as e:
        raise FontError(f"nie można wczytać czcionki {path}: {e}") from e
    if variation:
        try:
            font.set_variation_by_name(variation)
        except (OSError, ValueError) as e:
            raise FontError(f"czcionka {path.name} nie ma wariantu {variation}") from e
    return font


@cache
def _codepoints(path: Path) -> frozenset[int]:
    try:
        with TTFont(str(path), lazy=True) as font:
            cmap = font.getBestCmap() or {}
    except (OSError, TTLibError) as e:
        raise FontError(f"nie można odczytać mapy znaków czcionki {path}: {e}") from e
    return frozenset(cmap)


def missing_chars(path: Path, text: str) -> str:
    """Znaki tekstu, których czcionka nie ma (bez odstępów), w kolejności, bez powtórzeń.

    Pillow rysuje brakujący znak jako pusty prostokąt bez ostrzeżenia, więc program sprawdza
    mapę znaków czcionki, zanim wyda pieniądze na API (FR-19).
    """
    available = _codepoints(path)
    missing = [c for c in dict.fromkeys(text) if not c.isspace() and ord(c) not in available]
    return "".join(missing)
