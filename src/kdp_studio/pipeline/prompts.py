"""FR-04: prompty obrazu dla stron książki.

Prompt strony = opis sceny z FR-03 + wspólny blok stylu, identyczny dla wszystkich
stron książki (styl, wiek, format i stałe ograniczenia). Spójność serii zapewnia
ten wspólny blok, nie pamięć modelu: każda grafika to osobne wywołanie API (D4).
"""

from __future__ import annotations

from dataclasses import dataclass

from kdp_studio.config import AppConfig
from kdp_studio.models import BookIdeas, BookPrompts, BookSpec, PageIdea, PagePrompt

FIXED_CONSTRAINTS = (
    "black and white line art, coloring book page, single illustration, one scene, "
    "pure white background, closed outlines, no shading, no grayscale, no text, no grid, "
    "no multiple panels, no collage, no frame"
)


@dataclass(frozen=True)
class PromptBuilder:
    spec: BookSpec
    config: AppConfig

    @property
    def style_block(self) -> str:
        """Część promptu wspólna dla wszystkich stron książki."""
        style = self.config.styles[self.spec.style]
        age = self.config.ages[self.spec.age]
        fmt = self.config.formats[self.spec.format]
        return (
            f"Style: {_sentence(style.prompt_fragment)}\n"
            f"Line work and detail: {_sentence(age.prompt_fragment)}\n"
            f"Composition: {_sentence(fmt.composition_hint)}\n"
            f"Requirements: {_sentence(FIXED_CONSTRAINTS)}"
        )

    def page_prompt(self, idea: PageIdea) -> PagePrompt:
        return PagePrompt(
            idea_id=idea.id,
            prompt=f"Scene: {_sentence(idea.scene)}\n{self.style_block}",
        )

    def build(self, ideas: BookIdeas) -> BookPrompts:
        """Prompty dla wszystkich pomysłów, także zapasowych (gotowe na ponowienie po QA)."""
        return BookPrompts(
            style_block=self.style_block,
            pages=[self.page_prompt(idea) for idea in ideas.pages],
        )


def _sentence(text: str) -> str:
    """Jedna linia zakończona kropką: składa białe znaki z YAML i nie dubluje kropki."""
    flat = " ".join(text.split()).rstrip(" .")
    return f"{flat}."
