"""FR-03: pomysły na strony i metadane książki w jednym wywołaniu LLM (D5)."""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Mapping, Sequence
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
KDP_TITLE_MAX_CHARS = 200  # tytuł i podtytuł razem (wytyczne metadanych KDP)
# Cel długości dla czytelności na okładce (FR-15); KDP: dłuższe tytuły kupujący przeskakują.
TITLE_AIM_CHARS = 60
SUBTITLE_AIM_CHARS = 80


# Opisy cech sceny (FR-03b), wspólne dla generowania i weryfikacji.
SUBJECT_HELP = (
    "Kind of the main character as one lowercase English noun, e.g. kitten, bear, girl; "
    "none when there are no characters."
)
CHARACTERS_HELP = "Number of characters (people or animals) in the scene; 0 for none."
ACTION_HELP = (
    "Main action of the characters as one lowercase English verb in base form, "
    "e.g. sit, decorate, carry, sled."
)
SETTING_HELP = "Where the scene happens in 1-3 lowercase English words, e.g. living room, kitchen."
ANCHORS_HELP = (
    "Places, objects or actions that the theme itself names, so they belong on most pages, in "
    "lowercase English, e.g. kitchen for 'cats in the kitchen' or sled for 'sledding'. Usually "
    "empty: 'Christmas cats' or 'dinosaurs' name no place, object or action."
)


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
    # Cechy sceny do kontroli różnorodności (FR-03b); liczy je kod, nie model.
    subject: str = Field(description=SUBJECT_HELP)
    characters: int = Field(description=CHARACTERS_HELP)
    action: str = Field(description=ACTION_HELP)
    setting: str = Field(description=SETTING_HELP)


class _LLMIdeas(BaseModel):
    book: _LLMBook
    theme_anchors: list[str] = Field(description=ANCHORS_HELP)
    pages: list[_LLMPage]


class _LLMMoreIdeas(BaseModel):
    pages: list[_LLMPage]


# --- Prompt -------------------------------------------------------------------------

SYSTEM_PROMPT = """\
You plan coloring books for Amazon KDP. You return book metadata and a list of page ideas.

Hard constraints (never break them):
- No copyrighted or trademarked characters, franchises, brands, logos, mascots or product names. \
Use only original, generic subjects.
- Every page is a distinctly different scene: a different subject, action or setting. \
Rewording another page does not count as a new idea.
- {theme_rule}
- Each scene must work as black-and-white line art for coloring: one single scene, no text, \
letters, numbers, signs or speech bubbles in the picture.
- Write `scene` and `elements` in English. Describe only what is visible (subject, action, \
setting, key objects). Do not mention art style, line weight, colors, shading or the words \
"coloring page"; those are added separately.
- Match the number of subjects and the scene complexity to the target audience.
- Vary the book as a whole: the number of characters (see the audience), their actions and \
poses, the settings and the viewpoints. Do not build many scenes around the same object, \
action or place, and do not show one character sitting beside an object again and again.
- Match the composition to the page format.

Metadata rules:
Amazon search weighs the title and subtitle most, then the keywords; the description barely \
counts. The title and subtitle are also printed on the front cover, so they must read well there.
- The book is sold on {domain} ({locale}). Write title, subtitle, description and keywords in \
{language}, with its spelling and the words that buyers there type when they search.
- Call the book a "{coloring_book}" (exactly this word, not another spelling or synonym).
- Title: the theme in the words buyers search for, plus "{coloring_book}" when it fits \
naturally. Short and catchy, readable on the cover: at most {title_aim} characters.
- Subtitle: the target audience, written exactly as "{audience}", optionally with a short phrase \
about what is inside (e.g. the main motifs). One audience only, as a natural phrase: no lists of \
audiences or words separated by "|" or commas. At most {subtitle_aim} characters, so it fits on \
the cover in one or two lines. Title and subtitle together: never more than {title_chars} \
characters.
- Description: plain text, no HTML, at most 4000 characters, no claims like "bestseller" or \
"free", no mention of AI.
- Keywords: exactly {max_keywords} short phrases that buyers would type, each at most \
{keyword_chars} characters. They carry what the title and subtitle leave out, so plan them:
  - 2-3 for other audiences: for children, age ranges that overlap the target ages (e.g. \
"kids ages 5-8" or "ages 4-8" for ages 6-8), girls and boys, a school stage such as preschool or \
kindergarten; for adults, e.g. teens and adults or seniors;
  - 1-2 for buying occasions and uses (a gift, a holiday, travel, quiet time, relaxation);
  - the rest for other words buyers use for the theme and its motifs (synonyms, sub-themes).
  Every keyword adds at least one word that is not in the title or subtitle. No keyword may \
differ from another only in spacing, punctuation, capitalization, word order or plural. No \
trademarks, brand or character names, quality claims ("best"), time-limited words ("new", "on \
sale") or Amazon program names.
"""

THEME_RULE = (
    "Every scene clearly belongs to the theme: its main subject, action or a clearly visible "
    "object is typical of the theme and is listed in `elements`. Motifs commonly used for the "
    "theme count (for Christmas also snowmen, sleds, mittens or snowy scenes). Generic words "
    'such as "holiday" or "festive" do not count, and neither does an everyday scene that would '
    "look the same on any other day (a birthday cake with a party crown, a tea party, a laundry "
    "basket); such a scene needs a concrete theme element (for Christmas: gingerbread cookies, "
    "a decorated tree, stockings, ornaments)."
)

PROFILE_PROMPT = """\
Theme (may be in any language, interpret it): {theme}

Target audience: {age_name}
- line work: {age_line}
- subjects per page: {age_subjects}
- background: {age_background}
- areas to color: {age_fill}
- guidance: {age_fragment}
- {cast}

Art style: {style_name} ({style_fragment})

Page format: {format_name}. Composition: {composition}
"""

USER_PROMPT = """\
{profile}
Return exactly {total} page ideas ({pages} pages plus {reserve} reserve ideas used when a page \
is rejected). All {total} must be different from each other.

The printed book has {pages} coloring pages; reserve ideas are never printed. If the title, \
subtitle or description mentions a number of pages, pictures or scenes, it must be {pages}.
"""


def reserve_count(pages: int, reserve_ratio: float) -> int:
    return math.ceil(pages * reserve_ratio)


def build_prompts(spec: BookSpec, config: AppConfig) -> tuple[str, str]:
    settings = config.settings
    reserve = reserve_count(spec.pages, settings.reserve_ratio)
    market = config.markets.markets[spec.market]
    system = SYSTEM_PROMPT.format(
        domain=market.domain,
        locale=market.locale,
        language=market.language,
        coloring_book=market.terms.coloring_book,
        audience=market.terms.age_phrase(config.ages[spec.age].age_range),
        max_keywords=KDP_MAX_KEYWORDS,
        keyword_chars=KDP_KEYWORD_MAX_CHARS,
        title_chars=KDP_TITLE_MAX_CHARS,
        title_aim=TITLE_AIM_CHARS,
        subtitle_aim=SUBTITLE_AIM_CHARS,
        theme_rule=THEME_RULE,
    )
    user = USER_PROMPT.format(
        profile=profile_prompt(spec, config),
        total=spec.pages + reserve,
        pages=spec.pages,
        reserve=reserve,
    )
    return system, user


MORE_PROMPT = """\
{profile}
Return exactly {count} NEW page ideas. Each must be different from every idea below \
(different subject, action or setting, not a rewording):
{existing}
{hints}"""


def build_more_prompts(
    spec: BookSpec,
    config: AppConfig,
    count: int,
    existing: Sequence[PageIdea],
    hints: Sequence[str] = (),
) -> tuple[str, str]:
    """Prompt dogenerowania pomysłów, gdy weryfikacja odrzuci za dużo (FR-03a).

    `hints` to wskazówki różnorodności dla nowych pomysłów (FR-03b, FR-17 `--redo`).
    """
    system, _ = build_prompts(spec, config)
    listing = "\n".join(f"- {idea.title}: {idea.scene}" for idea in existing) or "- (none)"
    advice = ""
    if hints:
        advice = (
            "\nThe book already has enough of some things. For the new ideas:\n"
            + "\n".join(f"- {hint}" for hint in hints)
            + "\n"
        )
    user = MORE_PROMPT.format(
        profile=profile_prompt(spec, config), count=count, existing=listing, hints=advice
    )
    return system, user


def cast_rule(share: float) -> str:
    """Wymagany udział scen z kilkoma postaciami (FR-03b), z profilu wieku."""
    if share <= 0:
        return "scenes with several characters: not required"
    return (
        f"scenes with two or three characters doing something together: at least "
        f"{round(share * 100)}% of the pages"
    )


def profile_prompt(spec: BookSpec, config: AppConfig) -> str:
    """Temat, wiek, styl i format: wspólna część promptów generowania i weryfikacji."""
    age = config.ages[spec.age]
    style = config.styles[spec.style]
    fmt = config.formats[spec.format]
    return PROFILE_PROMPT.format(
        theme=spec.theme,
        age_name=age.name,
        age_line=age.line,
        age_subjects=age.subjects,
        age_background=age.background,
        age_fill=age.fill_areas,
        age_fragment=age.prompt_fragment,
        cast=cast_rule(age.multi_subject_share),
        style_name=style.name,
        style_fragment=style.prompt_fragment,
        format_name=fmt.name,
        composition=fmt.composition_hint,
    )


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


def _respell(text: str, spelling: Mapping[str, str]) -> tuple[str, list[str]]:
    """Słowa innej odmiany języka zamienione na pisownię rynku, z zachowaniem wielkości liter."""
    if not spelling:
        return text, []
    changes: list[str] = []
    pattern = re.compile(r"\b(" + "|".join(map(re.escape, spelling)) + r")\b", re.IGNORECASE)

    def fix(match: re.Match[str]) -> str:
        word = match.group(0)
        right = spelling[word.casefold()]
        if word.isupper():
            right = right.upper()
        elif word[0].isupper():
            right = right[0].upper() + right[1:]
        changes.append(f"{word} → {right}")
        return right

    return pattern.sub(fix, text), changes


def apply_spelling(
    book: BookMetadata, spelling: Mapping[str, str]
) -> tuple[BookMetadata, list[str]]:
    """Metadane w pisowni rynku (FR-19, kontrola FR-03a): np. „Coloring” → „Colouring” na UK.

    Model dostaje odmianę języka w prompcie, ale potrafi wpleść słowo z innej odmiany; te
    kilka słów program poprawia sam, bez ponownego wywołania. Zwraca też listę zmian.
    """
    lowered = {wrong.casefold(): right for wrong, right in spelling.items()}
    changes: list[str] = []

    def fixed(text: str) -> str:
        new, made = _respell(text, lowered)
        changes.extend(made)
        return new

    result = BookMetadata(
        title=fixed(book.title),
        subtitle=fixed(book.subtitle),
        description=fixed(book.description),
        keywords=_clean_list([fixed(k) for k in book.keywords]),
    )
    return result, changes


def _words(text: str) -> list[str]:
    """Słowa do porównań metadanych: małe litery, bez interpunkcji, liczba pojedyncza.

    Liczba pojedyncza to tylko obcięte końcowe „s” (kids → kid), co wystarcza dla
    wariantów, przed którymi ostrzega KDP; w innych językach reguła po prostu rzadziej trafia.
    """
    words = re.findall(r"\w+", text.casefold())
    return [w[:-1] if len(w) > 3 and w.endswith("s") and not w.endswith("ss") else w for w in words]


def keyword_issues(book: BookMetadata) -> list[str]:
    """Słowa kluczowe, które nic nie dodają do wyszukiwania (FR-03); tylko do ostrzeżenia.

    Amazon wyszukuje po słowach z tytułu, podtytułu i słów kluczowych, a KDP odradza
    powtarzanie metadanych i warianty różniące się tylko pisownią, interpunkcją, wielkością
    liter czy liczbą mnogą. Program ich nie usuwa (użytkownik poprawia je w `ideas.json`
    albo w KDP), tylko wskazuje słowo kluczowe złożone wyłącznie ze słów tytułu i podtytułu
    oraz wariant wcześniejszego słowa kluczowego, także w innej kolejności słów.
    „kids ages 5-8” przy podtytule „for Kids Ages 6–8” jest w porządku, bo dodaje 5.
    """
    covered = set(_words(book.title)) | set(_words(book.subtitle))
    seen: set[tuple[str, ...]] = set()
    issues: list[str] = []
    for keyword in book.keywords:
        words = tuple(sorted(_words(keyword)))
        if words in seen:
            issues.append(f"„{keyword}” (wariant innego słowa kluczowego)")
        elif set(words) <= covered:
            issues.append(f"„{keyword}” (same słowa z tytułu i podtytułu)")
        seen.add(words)
    return issues


def missing_audience(book: BookMetadata, audience: str) -> bool:
    """Czy podtytuł nie podaje odbiorców z frazy rynku (np. „for Kids Ages 6–8”)."""
    return not set(_words(audience)) <= set(_words(book.subtitle))


def _page_id(index: int) -> str:
    return f"idea_{index:02d}"


def tag(text: str) -> str | None:
    """Cecha sceny małymi literami, bez zbędnych spacji; pusta to None (FR-03b)."""
    return " ".join(text.casefold().split()) or None


def _idea(index: int, page: _LLMPage) -> PageIdea:
    return PageIdea(
        id=_page_id(index),
        title=page.title,
        scene=page.scene,
        elements=_clean_list(page.elements),
        subject=tag(page.subject),
        characters=max(page.characters, 0),
        action=tag(page.action),
        setting=tag(page.setting),
    )


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
            length = len(book.title) + len(book.subtitle)
            if length > KDP_TITLE_MAX_CHARS:
                problem = (
                    f"tytuł i podtytuł mają razem {length} znaków "
                    f"(KDP: najwyżej {KDP_TITLE_MAX_CHARS})"
                )
                continue

            warnings: list[str] = []
            book, changes = apply_spelling(book, self.config.markets.markets[spec.market].spelling)
            if changes:
                counts = Counter(changes)
                listed = ", ".join(f"{c} ({n}×)" if n > 1 else c for c, n in counts.items())
                warnings.append(f"pisownia rynku {spec.market} w metadanych: {listed}")
            if issues := keyword_issues(book):
                warnings.append("słowa kluczowe nic nie dodają: " + ", ".join(issues))
            audience = self.config.markets.markets[spec.market].terms.age_phrase(
                self.config.ages[spec.age].age_range
            )
            if missing_audience(book, audience):
                warnings.append(f"podtytuł nie podaje odbiorców („{audience}”): {book.subtitle!r}")
            if len(book.subtitle) > SUBTITLE_AIM_CHARS or len(book.title) > TITLE_AIM_CHARS:
                warnings.append(
                    f"długi tytuł ({len(book.title)} zn.) lub podtytuł ({len(book.subtitle)} zn.): "
                    f"na okładce może być nieczytelny (cel: {TITLE_AIM_CHARS} i "
                    f"{SUBTITLE_AIM_CHARS} znaków)"
                )
            if len(pages) < expected:
                warnings.append(
                    f"model zwrócił {len(pages)} unikalnych pomysłów zamiast {expected}; "
                    f"zapas na odrzucone strony to {len(pages) - spec.pages}"
                )
            ideas = BookIdeas(
                book=book,
                theme_anchors=_clean_list([a.casefold() for a in response.theme_anchors]),
                pages=[_idea(i, page) for i, page in enumerate(pages[:expected], start=1)],
            )
            return IdeasResult(ideas=ideas, usage=usage, attempts=attempt, warnings=warnings)

        raise ProviderError(
            f"nie udało się wygenerować pomysłów w {self.max_attempts} próbach: {problem}"
        )

    def generate_more(
        self,
        spec: BookSpec,
        count: int,
        existing: Sequence[PageIdea],
        first_number: int,
        hints: Sequence[str] = (),
    ) -> tuple[list[PageIdea], Usage]:
        """Dogenerowuje do `count` nowych pomysłów różnych od `existing` (FR-03a).

        Numeracja od `first_number`; ostateczne id nadaje weryfikacja po scaleniu.
        """
        system, user = build_more_prompts(spec, self.config, count, existing, hints)
        response, usage = self.provider.complete_json(system, user, _LLMMoreIdeas)
        known = {_fingerprint(i.title) for i in existing} | {
            _fingerprint(i.scene) for i in existing
        }
        fresh = [
            p
            for p in _unique_pages(response.pages)
            if not {_fingerprint(p.title), _fingerprint(p.scene)} & known
        ]
        ideas = [_idea(first_number + i, p) for i, p in enumerate(fresh[:count])]
        return ideas, usage
