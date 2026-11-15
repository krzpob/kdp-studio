"""FR-03: pomysły na strony i metadane książki w jednym wywołaniu LLM (D5)."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

from pydantic import BaseModel, Field, ValidationError

from kdp_studio.config import AppConfig
from kdp_studio.models import (
    KDP_MAX_KEYWORDS,
    BookIdeas,
    BookMetadata,
    BookSpec,
    PageIdea,
)
from kdp_studio.providers.base import ProviderError, TextProvider, Usage

DEFAULT_MAX_ATTEMPTS = 2
KDP_KEYWORD_MAX_CHARS = 50


# --- Schemat odpowiedzi LLM ---------------------------------------------------------
# Celowo bez ograniczeń (min/max): nie każdy model obsługuje je w structured outputs.
# Ograniczenia egzekwuje `_normalize` przy budowaniu modeli domenowych.


class _LLMBook(BaseModel):
    title: str = Field(description="Book title for the Amazon KDP listing.")
    subtitle: str = Field(description="Subtitle; may be empty.")
    description: str = Field(description="Plain-text book description for the KDP listing.")
    keywords: list[str] = Field(description="Up to 7 search keywords or short phrases.")


class _LLMPage(BaseModel):
    title: str = Field(description="Short page title.")
    scene: str = Field(
        description="English description of what is visible on the page, ready for an "
        "image prompt: subject, action, setting, key objects."
    )
    elements: list[str] = Field(description="Main objects visible in the scene.")


class _LLMIdeas(BaseModel):
    book: _LLMBook
    pages: list[_LLMPage]


# --- Prompt -------------------------------------------------------------------------

SYSTEM_PROMPT = """\
You plan coloring books for Amazon KDP. You return book metadata and a list of page ideas.

Hard constraints (never break them):
- No copyrighted or trademarked characters, franchises, brands, logos, mascots or product names. \
Use only original, generic subjects.
- Every page is a distinctly different scene: a different subject, action or setting. \
Rewording another page does not count as a new idea.
- Each scene must work as black-and-white line art for coloring: one single scene, no text, \
letters, numbers, signs or speech bubbles in the picture.
- Write `scene` and `elements` in English. Describe only what is visible (subject, action, \
setting, key objects). Do not mention art style, line weight, colors, shading or the words \
"coloring page"; those are added separately.
- Match the number of subjects and the scene complexity to the target audience.
- Match the composition to the page format.

Metadata rules:
- Write title, subtitle, description and keywords in {language}.
- Description: plain text, no HTML, at most 4000 characters, no claims like "bestseller" or \
"free", no mention of AI.
- Keywords: at most {max_keywords}, each at most {keyword_chars} characters, no trademarks, \
no words already in the title.
"""

USER_PROMPT = """\
Theme (may be in any language, interpret it): {theme}

Target audience: {age_name}
- line work: {age_line}
- subjects per page: {age_subjects}
- background: {age_background}
- areas to color: {age_fill}
- guidance: {age_fragment}

Art style: {style_name} ({style_fragment})

Page format: {format_name}. Composition: {composition}

Return exactly {total} page ideas ({pages} pages plus {reserve} reserve ideas used when a page \
is rejected). All {total} must be different from each other.

The printed book has {pages} coloring pages; reserve ideas are never printed. If the title, \
subtitle or description mentions a number of pages, pictures or scenes, it must be {pages}.
"""


def reserve_count(pages: int, reserve_ratio: float) -> int:
    return math.ceil(pages * reserve_ratio)


def build_prompts(spec: BookSpec, config: AppConfig) -> tuple[str, str]:
    age = config.ages[spec.age]
    style = config.styles[spec.style]
    fmt = config.formats[spec.format]
    settings = config.settings
    reserve = reserve_count(spec.pages, settings.reserve_ratio)
    system = SYSTEM_PROMPT.format(
        language=settings.metadata_language,
        max_keywords=KDP_MAX_KEYWORDS,
        keyword_chars=KDP_KEYWORD_MAX_CHARS,
    )
    user = USER_PROMPT.format(
        theme=spec.theme,
        age_name=age.name,
        age_line=age.line,
        age_subjects=age.subjects,
        age_background=age.background,
        age_fill=age.fill_areas,
        age_fragment=age.prompt_fragment,
        style_name=style.name,
        style_fragment=style.prompt_fragment,
        format_name=fmt.name,
        composition=fmt.composition_hint,
        total=spec.pages + reserve,
        pages=spec.pages,
        reserve=reserve,
    )
    return system, user


# --- Normalizacja -------------------------------------------------------------------


def _fingerprint(text: str) -> str:
    return re.sub(r"[\W_]+", " ", text.casefold()).strip()


def _clean_list(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        text = item.strip()
        key = text.casefold()
        if text and key not in seen:
            seen.add(key)
            result.append(text)
    return result


def _unique_pages(pages: list[_LLMPage]) -> list[_LLMPage]:
    """Usuwa puste i dosłownie powtórzone pomysły (ten sam tytuł albo ta sama scena)."""
    seen: set[str] = set()
    result: list[_LLMPage] = []
    for page in pages:
        keys = {_fingerprint(page.title), _fingerprint(page.scene)}
        if not page.title.strip() or not page.scene.strip() or keys & seen:
            continue
        seen |= keys
        result.append(page)
    return result


def _metadata(book: _LLMBook) -> BookMetadata:
    return BookMetadata(
        title=book.title,
        subtitle=book.subtitle,
        description=book.description,
        keywords=_clean_list(book.keywords)[:KDP_MAX_KEYWORDS],
    )


def _page_id(index: int) -> str:
    return f"idea_{index:02d}"


# --- Generator ----------------------------------------------------------------------


@dataclass(frozen=True)
class IdeasResult:
    ideas: BookIdeas
    usage: Usage
    attempts: int
    warnings: list[str] = field(default_factory=list)


@dataclass
class IdeaGenerator:
    provider: TextProvider
    config: AppConfig
    max_attempts: int = DEFAULT_MAX_ATTEMPTS

    def generate(self, spec: BookSpec) -> IdeasResult:
        """Jedno wywołanie LLM; ponowienie tylko, gdy pomysłów jest mniej niż stron."""
        system, user = build_prompts(spec, self.config)
        expected = spec.pages + reserve_count(spec.pages, self.config.settings.reserve_ratio)
        usage = Usage()
        problem = ""

        for attempt in range(1, self.max_attempts + 1):
            response, call_usage = self.provider.complete_json(system, user, _LLMIdeas)
            usage += call_usage
            pages = _unique_pages(response.pages)
            if len(pages) < spec.pages:
                problem = f"{len(pages)} unikalnych pomysłów zamiast co najmniej {spec.pages}"
                continue
            try:
                book = _metadata(response.book)
            except ValidationError as e:
                fields = ", ".join(str(err["loc"][0]) for err in e.errors())
                problem = f"niepoprawne metadane książki ({fields})"
                continue

            warnings: list[str] = []
            if len(pages) < expected:
                warnings.append(
                    f"model zwrócił {len(pages)} unikalnych pomysłów zamiast {expected}; "
                    f"zapas na odrzucone strony to {len(pages) - spec.pages}"
                )
            ideas = BookIdeas(
                book=book,
                pages=[
                    PageIdea(
                        id=_page_id(i),
                        title=page.title,
                        scene=page.scene,
                        elements=_clean_list(page.elements),
                    )
                    for i, page in enumerate(pages[:expected], start=1)
                ],
            )
            return IdeasResult(ideas=ideas, usage=usage, attempts=attempt, warnings=warnings)

        raise ProviderError(
            f"nie udało się wygenerować pomysłów w {self.max_attempts} próbach: {problem}"
        )
