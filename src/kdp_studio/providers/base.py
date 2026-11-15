"""Kontrakty dostawców (spec §8.2). Ten moduł nie może importować SDK dostawców."""

from __future__ import annotations

from typing import Protocol, TypeVar

from pydantic import BaseModel, ConfigDict, Field

SchemaT = TypeVar("SchemaT", bound=BaseModel)


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
    """Błąd dostawcy po wyczerpaniu ponowień (kod wyjścia 4).

    Komunikat nie może zawierać kluczy API (NFR-10).
    """


class TextProvider(Protocol):
    name: str
    model: str

    def complete_json(self, system: str, user: str, schema: type[SchemaT]) -> tuple[SchemaT, Usage]:
        """Zwraca odpowiedź zwalidowaną schematem `schema` (structured outputs)."""
        ...
