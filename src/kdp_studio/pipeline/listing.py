"""Opis książki do KDP (FR-03): HTML składany przez program z części od modelu i faktów.

Model pisze tylko treść (hasło, akapit o zawartości, korzyści, zdanie na koniec) i może w niej
wyróżniać słowa znacznikami `<b>`, `<i>`, `<u>`. Strukturę (pogrubiony tytuł, nagłówki, listy)
i fakty o książce (liczba kolorowanek, druk, format, strony wstępne) dokłada program, więc
każdy opis ma wszystkie części, a liczby zgadzają się z manifestem. Fakty pochodzą z manifestu,
dlatego opis składa się od nowa w `finalize`, np. po zmianie trybu druku (FR-22).
"""

from __future__ import annotations

import html
import re
from collections.abc import Sequence
from dataclasses import dataclass
from html.parser import HTMLParser

from kdp_studio.config import AppConfig, FrontTexts
from kdp_studio.models import BookMetadata
from kdp_studio.pipeline.manifest import Manifest

DESCRIPTION_FILE = "description.html"
KDP_DESCRIPTION_MAX_CHARS = 4000  # limit KDP, licząc znaczniki HTML
DESCRIPTION_AIM_CHARS = 2000  # dłuższy opis: ostrzeżenie (kupujący czyta zwykle początek)
FACTS_RESERVE_CHARS = 600  # miejsce na tytuł, fakty i nagłówki przy kontroli w kroku 1
INLINE_TAGS = ("b", "i", "u")  # jedyne znaczniki dozwolone w tekstach od modelu


class _InlineSanitizer(HTMLParser):
    """Przepisuje tekst: dozwolone znaczniki bez atrybutów, reszta jako zwykły tekst."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.open: list[str] = []
        self.problems: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag not in INLINE_TAGS:
            self.problems.append(f"niedozwolony znacznik <{tag}>")
            return
        if attrs:
            self.problems.append(f"atrybuty w <{tag}>")
        self.out.append(f"<{tag}>")
        self.open.append(tag)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.problems.append(f"niedozwolony znacznik <{tag}/>")

    def handle_endtag(self, tag: str) -> None:
        if tag not in INLINE_TAGS:
            self.problems.append(f"niedozwolony znacznik </{tag}>")
            return
        if tag not in self.open:
            self.problems.append(f"</{tag}> bez otwarcia")
            return
        while self.open:  # zamyka też znaczniki otwarte wewnątrz, w dobrej kolejności
            inner = self.open.pop()
            self.out.append(f"</{inner}>")
            if inner == tag:
                break

    def handle_data(self, data: str) -> None:
        self.out.append(html.escape(data, quote=False))

    def result(self) -> str:
        for tag in reversed(self.open):
            self.problems.append(f"<{tag}> bez zamknięcia")
            self.out.append(f"</{tag}>")
        self.open.clear()
        return re.sub(r"\s+", " ", "".join(self.out)).strip()


def sanitize_inline(text: str) -> tuple[str, list[str]]:
    """Tekst od modelu jako bezpieczny fragment HTML (FR-03) i lista znalezionych usterek.

    Zostają tylko `<b>`, `<i>`, `<u>` bez atrybutów, domknięte; inne znaczniki znikają, ale ich
    treść zostaje; znaki `<`, `>` i `&` w tekście są zakodowane.
    """
    parser = _InlineSanitizer()
    parser.feed(text)
    parser.close()
    clean = parser.result()
    return clean, list(dict.fromkeys(parser.problems))


def plain_text(fragment: str) -> str:
    """Fragment HTML jako zwykły tekst (np. do tylnej okładki, FR-15)."""
    return html.unescape(re.sub(r"<[^>]*>", "", fragment)).strip()


_EMOJI = re.compile("[\U0001f000-\U0001faff☀-➿⬀-⯿️]")
_URL = re.compile(r"https?://|www\.|\b[\w.-]+\.(?:com|net|org|pl|de)\b", re.IGNORECASE)
_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.]+\b")
_PRICE = re.compile(r"[$€£]\s?\d|\d\s?(?:zł|pln|eur|usd)\b", re.IGNORECASE)
_SALES = re.compile(
    r"(?<![\w-])(?:review|reviews|rate|rating|free|discount|sale|price|buy now|add to cart|"
    r"bestseller|best-seller|recenzj\w*|opini\w*|gratis|rabat\w*|bewertung\w*|kostenlos)(?![\w-])",
    re.IGNORECASE,
)


def content_issues(texts: Sequence[str]) -> list[str]:
    """Treści, których KDP nie przyjmuje w opisie: emoji, adresy, ceny, prośby o recenzje,
    hasła sprzedażowe. Wykrywanie jest przybliżone, więc to tylko ostrzeżenia."""
    joined = " ".join(plain_text(t) for t in texts)
    issues: list[str] = []
    if _EMOJI.search(joined):
        issues.append("emoji")
    if _URL.search(joined) or _EMAIL.search(joined):
        issues.append("adres strony albo e-mail")
    if _PRICE.search(joined):
        issues.append("cena")
    words = sorted({m.group(0).casefold() for m in _SALES.finditer(joined)})
    if words:
        issues.append("słowa sprzedażowe albo prośba o recenzję: " + ", ".join(words))
    return issues


@dataclass(frozen=True)
class BookFacts:
    """Fakty o książce do opisu, z manifestu, nie od modelu."""

    pages: int
    single_sided: bool
    trim_in: tuple[float, float]
    first_page: str | None  # "title", "belongs-to" albo None
    instructions: bool
    adults: bool


def book_facts(manifest: Manifest, config: AppConfig) -> BookFacts:
    data = manifest.input
    owner = data.copyright_owner is not None  # książka ze stronami wstępnymi FR-23
    first_page: str | None = None
    if owner:
        first_page = data.first_page or config.settings.front_matter.first_page
    elif manifest.front_matter.belongs_to is not None:
        first_page = "belongs-to"
    age = config.ages.get(data.age)
    return BookFacts(
        pages=data.pages,
        single_sided=data.single_sided,
        trim_in=manifest.layout.trim_in,
        first_page=first_page,
        instructions=owner and data.front_matter_pages >= 4,
        adults=age is not None and age.age_range is None,
    )


def _number(value: float, comma: bool) -> str:
    text = f"{value:g}"
    return text.replace(".", ",") if comma else text


def fact_lines(facts: BookFacts, listing: dict[str, str]) -> list[str]:
    width, height = facts.trim_in
    trim_in = f"{_number(width, False)} × {_number(height, False)} in"
    trim_cm = (
        f"{_number(round(width * 2.54, 1), True)} × {_number(round(height * 2.54, 1), True)} cm"
    )
    lines = [
        listing["pages_single" if facts.single_sided else "pages_double"].format(pages=facts.pages),
        listing["size"].format(trim_in=trim_in, trim_cm=trim_cm),
    ]
    if facts.first_page == "title":
        lines.append(listing["first_page_title"])
    elif facts.first_page == "belongs-to":
        lines.append(listing["first_page_belongs_to"])
    if facts.instructions:
        lines.append(listing["instructions"])
    return lines


def description_parts_length(book: BookMetadata) -> int:
    """Długość części od modelu ze znacznikami list (kontrola limitu w kroku 1, FR-03)."""
    items = sum(len(b) + len("<li></li>") for b in book.benefits)
    texts = (book.headline or "", book.about or book.description, book.closing or "")
    return sum(len(t) + len("<p></p>") for t in texts) + items + len("<ul></ul>")


def render_description(book: BookMetadata, facts: BookFacts, texts: FrontTexts | None) -> str:
    """Opis do KDP: pogrubiony tytuł, hasło, akapit, fakty, korzyści i zdanie na koniec.

    Bez tłumaczeń `listing` dla języka rynku opis nie ma listy faktów ani nagłówka korzyści.
    Stara książka bez części od modelu dostaje swój zwykły opis jako akapit.
    """
    esc = html.escape
    parts = [f"<b>{esc(book.title, quote=False)}</b>"]
    if book.headline:
        parts.append(f"<h4>{book.headline}</h4>")
    about = book.about or esc(book.description, quote=False)
    parts.append(f"<p>{about}</p>")
    listing = texts.listing if texts is not None and texts.listing else None
    if listing is not None:
        items = "".join(f"<li>{esc(line, quote=False)}</li>" for line in fact_lines(facts, listing))
        parts.append(f"<ul>{items}</ul>")
    if book.benefits:
        if listing is not None:
            heading = listing["benefits_adults" if facts.adults else "benefits_kids"]
            parts.append(f"<h5>{esc(heading, quote=False)}</h5>")
        parts.append("<ul>" + "".join(f"<li>{b}</li>" for b in book.benefits) + "</ul>")
    if book.closing:
        parts.append(f"<p>{book.closing}</p>")
    return "\n".join(parts) + "\n"
