"""FR-07: kontrola jakości gotowej strony modelem z wizją.

Model ocenia stronę po obróbce (FR-06), czyli to, co trafi do druku, według kryteriów
ze spec: panele lub kolaż, cieniowanie, tekst, otwarte kontury, poziom szczegółów
niezgodny z profilem wieku, elementy niezgodne ze sceną oraz temat książki, którego nie widać
w samym rysunku (`theme_unclear`: zimowy brzeg, który bez kolorów może być letnią plażą).
Wynik `{pass, issues}` trafia do manifestu; odrzuconą stronę worker generuje ponownie z tego
samego pomysłu, a po `qa_max_retries` ponowieniach z zapasowego.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from kdp_studio.config import AppConfig
from kdp_studio.models import BookIdeas, BookSpec, PageIdea
from kdp_studio.providers.base import Usage, VisionProvider

Criterion = Literal[
    "panels",
    "shading",
    "text",
    "open_contours",
    "detail_level",
    "scene_mismatch",
    "theme_unclear",
    "other",
]


class QAIssue(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    criterion: Criterion
    detail: str  # po polsku, dla użytkownika


class QAResult(BaseModel):
    """Wynik QA zapisany w manifeście jako `{"pass": …, "issues": […]}` (spec §10)."""

    model_config = ConfigDict(
        frozen=True, extra="forbid", validate_by_name=True, serialize_by_alias=True
    )

    passed: bool = Field(alias="pass")
    issues: list[QAIssue] = []

    def summary(self) -> str:
        return "; ".join(f"{i.criterion}: {i.detail}" for i in self.issues) or "bez powodu"


# Schemat odpowiedzi modelu (docstring trafiłby do schematu, stąd komentarz). `pass` to
# słowo kluczowe Pythona, więc model zwraca `passed`.
class _LLMVerdict(BaseModel):
    passed: bool
    issues: list[QAIssue]


QA_INSTRUCTIONS = """\
You are the quality checker for a printed coloring book for {audience}. You get one finished \
page exactly as it will be printed: pure black line art on white, already thresholded to two \
colors, with white margins around the drawing. Decide whether the page can go into the book.

Reject the page (passed = false) only for these problems, each a separate issue:
- panels: several panels, a grid, a collage, a comic layout, or more than one separate \
illustration on the page.
- shading: shading, hatching, stippling, cross-hatching, grey-tone texture, or large solid \
black filled areas used as shadows or fills that a child cannot color. Small solid details \
such as pupils, noses or a cat's nose are fine.
- text: {text_rule}
- open_contours: outlines of the main shapes have gaps or are broken, so that colored areas \
would "leak" into each other. Tiny breaks in decorative lines do not count.
- detail_level: clearly too much or too little detail for this audience. Expected for this \
book: line weight {line}; subjects {subjects}; background {background}; color-in areas \
{fill_areas}.
- scene_mismatch: {scene_rule}
- theme_unclear: {theme_rule}
- other: any other defect that would make a buyer return the book (cut-off subject, \
deformed anatomy that looks broken, mostly empty page).

Calibration:
- A typical page from a good coloring book passes. Do not reject for matters of taste, small \
imperfections, or because a listed element is small or simplified.
- The scene does not need every element listed; reject for scene_mismatch only when the main \
subject is wrong or most key elements are missing.
- Judge theme_unclear on the black-and-white drawing as it is, without imagining colors. One \
clearly drawn hint of the theme is enough; reject only when nothing drawn points to it.
- White margins around the drawing are intended.

When the page passes, return passed = true and an empty issues list. When it fails, list every \
problem found. Write each issue's detail in Polish, briefly, pointing to where on the page it is.

Style of the book: {style}
Theme of the book: {theme}
Page scene: {title}. {scene}
Key elements: {elements}
"""


PAGE_TEXT_RULE = "any letters, words, numbers, signatures, logos or watermarks."
PAGE_SCENE_RULE = "the main subject or key elements of the scene below are missing or wrong."
PAGE_THEME_RULE = (
    "from the black-and-white line art alone a child cannot tell that the page belongs to a "
    "coloring book with the theme below, because the theme would show only through the colors "
    "chosen (for example a shore that could just as well be a summer beach in a winter book). "
    "Drawn hints such as snowflakes, icicles, snow on the ground or scarves in a winter book "
    "are enough."
)
# FR-14: napis i linię na imię dokłada program, więc kryteria text i scene_mismatch się zmieniają.
BELONGS_TO_TEXT_RULE = (
    "any letters, words, numbers, signatures, logos or watermarks other than the printed line "
    '"{text}" and the empty line for the owner\'s name below it, which the program adds on '
    "purpose."
)
BELONGS_TO_SCENE_RULE = (
    "the decorative elements do not match the theme of the book (key elements below), or "
    "there is no clear empty space around the printed line and the name line."
)
BELONGS_TO_THEME_RULE = "not used for this page (scene_mismatch covers the theme); never report it."


def _format(
    spec: BookSpec,
    config: AppConfig,
    *,
    title: str,
    scene: str,
    elements: list[str],
    theme: str = "-",
    text_rule: str = PAGE_TEXT_RULE,
    scene_rule: str = PAGE_SCENE_RULE,
    theme_rule: str = PAGE_THEME_RULE,
) -> str:
    age = config.ages[spec.age]
    return QA_INSTRUCTIONS.format(
        audience=age.name,
        line=age.line,
        subjects=age.subjects,
        background=age.background,
        fill_areas=age.fill_areas,
        style=" ".join(config.styles[spec.style].prompt_fragment.split()),
        title=title,
        scene=scene,
        elements=", ".join(elements) or "-",
        text_rule=text_rule,
        scene_rule=scene_rule,
        theme=theme,
        theme_rule=theme_rule,
    )


def book_theme(book: BookIdeas) -> str:
    """Temat książki dla QA po angielsku: tytuł z metadanych i słowa kluczowe tematu."""
    anchors = ", ".join(a for a in book.theme_anchors if a.strip())
    return f"{book.book.title} ({anchors})" if anchors else book.book.title


def qa_instructions(spec: BookSpec, config: AppConfig, idea: PageIdea, theme: str = "-") -> str:
    return _format(
        spec, config, title=idea.title, scene=idea.scene, elements=idea.elements, theme=theme
    )


def belongs_to_instructions(spec: BookSpec, config: AppConfig, elements: list[str]) -> str:
    """Kryteria FR-07 dla strony „This book belongs to…” (FR-14)."""
    settings = config.belongs_to_settings(spec.market)
    return _format(
        spec,
        config,
        title=f'Front page "{settings.text}" with a space for the owner\'s name',
        scene=" ".join(settings.composition.split()),
        elements=elements,
        text_rule=BELONGS_TO_TEXT_RULE.format(text=settings.text),
        scene_rule=BELONGS_TO_SCENE_RULE,
        theme_rule=BELONGS_TO_THEME_RULE,
    )


@dataclass
class QAChecker:
    """Ocena jednej strony; ProviderError z modelu przechodzi do workera."""

    vision: VisionProvider
    spec: BookSpec
    config: AppConfig
    ideas: BookIdeas
    _by_id: dict[str, PageIdea] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._by_id = {idea.id: idea for idea in self.ideas.pages}

    def check(self, image_png: bytes, idea_id: str) -> tuple[QAResult, Usage]:
        idea = self._by_id[idea_id]
        instructions = qa_instructions(self.spec, self.config, idea, book_theme(self.ideas))
        return self._assess(image_png, instructions)

    def check_belongs_to(self, image_png: bytes, elements: list[str]) -> tuple[QAResult, Usage]:
        """Strona „This book belongs to…” z napisem programu (FR-14)."""
        return self._assess(image_png, belongs_to_instructions(self.spec, self.config, elements))

    def _assess(self, image_png: bytes, instructions: str) -> tuple[QAResult, Usage]:
        verdict, usage = self.vision.assess(image_png, instructions, _LLMVerdict)
        issues = list(verdict.issues)
        if not verdict.passed and not issues:
            issues = [QAIssue(criterion="other", detail="model odrzucił stronę bez podania powodu")]
        return QAResult(passed=verdict.passed, issues=issues), usage
