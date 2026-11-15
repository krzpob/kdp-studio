"""Kontrakty dostawców (spec §8.2). Ten moduł nie może importować SDK dostawców."""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from typing import Any, Protocol, TypeVar

from pydantic import BaseModel, ConfigDict, Field

SchemaT = TypeVar("SchemaT", bound=BaseModel)

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


class Usage(BaseModel):
    """Zużycie jednego lub kilku wywołań API. Koszt w USD liczy FR-10."""

    model_config = ConfigDict(frozen=True)

    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)

    def __add__(self, other: Usage) -> Usage:
        return Usage(
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
        )


class ProviderError(Exception):
    """Błąd dostawcy po wyczerpaniu ponowień.

    `fatal=True` (domyślnie): błąd dotyczy całego przebiegu (zły klucz, brak środków,
    nieznany model), więc nie ma sensu wysyłać kolejnych zapytań (kod wyjścia 4).
    `fatal=False`: błąd dotyczy jednej strony (moderacja, przeciążenie po ponowieniach).
    Komunikat nie może zawierać kluczy API (NFR-10).
    """

    def __init__(self, message: str, *, fatal: bool = True) -> None:
        super().__init__(message)
        self.fatal = fatal


class TextProvider(Protocol):
    name: str
    model: str

    def complete_json(self, system: str, user: str, schema: type[SchemaT]) -> tuple[SchemaT, Usage]:
        """Zwraca odpowiedź zwalidowaną schematem `schema` (structured outputs)."""
        ...


@dataclass(frozen=True)
class ImageRequest:
    prompt: str
    aspect: str  # np. "3:4", z profilu formatu
    quality: str = "auto"
    seed: int | None = None  # adapter może zignorować, jeśli model nie obsługuje
    reference_image: bytes | None = None  # referencja stylu; adapter OpenAI w MVP ignoruje


@dataclass(frozen=True)
class ImageResult:
    png_bytes: bytes
    width: int
    height: int
    usage: Usage = field(default_factory=Usage)
    meta: dict[str, Any] = field(default_factory=dict)  # np. rozmiar, jakość, revised_prompt


class ImageProvider(Protocol):
    name: str
    model: str

    def supported_aspects(self) -> list[str]:
        """Proporcje, dla których adapter zna rozmiar obsługiwany przez model (FR-05)."""
        ...

    def generate(self, req: ImageRequest) -> ImageResult:
        """Jedno wywołanie = jedna grafika (D4)."""
        ...


def png_dimensions(data: bytes) -> tuple[int, int]:
    """Szerokość i wysokość z nagłówka IHDR. ValueError, jeśli to nie PNG."""
    if len(data) < 24 or not data.startswith(PNG_SIGNATURE) or data[12:16] != b"IHDR":
        raise ValueError("dane nie są obrazem PNG")
    width, height = struct.unpack(">II", data[16:24])
    return int(width), int(height)
