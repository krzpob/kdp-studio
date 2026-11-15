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


KDP_MAX_KEYWORDS = 7

NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class BookMetadata(BaseModel):
    """Metadane pod listing KDP (FR-03)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    title: NonEmptyStr
    subtitle: Annotated[str, StringConstraints(strip_whitespace=True)]
    description: NonEmptyStr
    keywords: Annotated[list[NonEmptyStr], Field(max_length=KDP_MAX_KEYWORDS)]


class PageIdea(BaseModel):
    """Pomysł na jedną stronę kolorowanki (FR-03)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: Annotated[str, Field(pattern=r"^idea_\d{2,}$")]
    title: NonEmptyStr
    scene: NonEmptyStr  # po angielsku, gotowe do promptu obrazu
    elements: list[NonEmptyStr]


class RejectedIdea(BaseModel):
    """Pomysł odrzucony przez weryfikację (FR-03a)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    title: str
    scene: str
    reason: str


class RevisedIdea(BaseModel):
    """Pomysł poprawiony przez weryfikację; `id` wskazuje go w `pages`."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    original_title: str
    original_scene: str
    reason: str


class IdeaReview(BaseModel):
    """Ślad weryfikacji pomysłów zapisany w `ideas.json` (FR-03a)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    rejected: list[RejectedIdea] = []
    revised: list[RevisedIdea] = []
    added: int = 0  # pomysły dogenerowane w miejsce odrzuconych
    rounds: int = 1


class BookIdeas(BaseModel):
    """Zawartość `ideas.json`: pierwsze `pages` pomysłów to strony, reszta to zapas."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    book: BookMetadata
    pages: list[PageIdea]
    review: IdeaReview | None = None  # None: weryfikacja wyłączona


class PagePrompt(BaseModel):
    """Gotowy prompt obrazu dla jednego pomysłu (FR-04)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    idea_id: Annotated[str, Field(pattern=r"^idea_\d{2,}$")]
    prompt: NonEmptyStr


class BookPrompts(BaseModel):
    """Zawartość `prompts.json`: wspólny blok stylu i prompt każdego pomysłu."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    style_block: NonEmptyStr
    pages: list[PagePrompt]


def pages_in_book(pages: int, front_matter_pages: int) -> int:
    """Strony fizyczne przy druku jednostronnym: grafika + pusta strona (D8, FR-02)."""
    return pages * 2 + front_matter_pages
