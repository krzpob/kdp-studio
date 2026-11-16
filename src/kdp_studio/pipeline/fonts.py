"""Czcionki z repozytorium (`assets/fonts`, SIL OFL) dla napisów wpisywanych przez program."""

from __future__ import annotations

from pathlib import Path

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
