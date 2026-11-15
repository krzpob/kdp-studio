"""Modele danych pipeline'u (spec §8.2)."""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

PAGES_MIN = 1
PAGES_MAX = 200


class BookSpec(BaseModel):
    """Zwalidowane parametry wejściowe książki (FR-01, FR-02).

    Pola `age`, `style` i `format` to klucze profili; ich istnienie sprawdza
    `kdp_studio.validation.validate_book_spec`, bo wymaga to wczytanej konfiguracji.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    theme: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
    age: str
    style: str
    format: str
    pages: Annotated[int, Field(ge=PAGES_MIN, le=PAGES_MAX)]
    front_matter_pages: Annotated[int, Field(ge=0)]

    @property
    def pages_in_book(self) -> int:
        return pages_in_book(self.pages, self.front_matter_pages)


def pages_in_book(pages: int, front_matter_pages: int) -> int:
    """Strony fizyczne przy druku jednostronnym: grafika + pusta strona (D8, FR-02)."""
    return pages * 2 + front_matter_pages
