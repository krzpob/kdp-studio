"""FR-24: teksty pól modułów A+ Content (jedno wywołanie LLM) i ich kontrola w kodzie.

Zasady A+ (https://kdp.amazon.com/en_US/help/topic/G4WB7VPPEAREHAAD, sprawdzone 24.11.2026) są
ostrzejsze niż zasady opisu: zakazują nacisku czasem, świąt jako terminu albo okazji do zakupu,
przechwałek oraz cen i wezwań do zakupu. Model dostaje reguły w prompcie, a kod sprawdza teksty
listami z `config/markets.yaml` (`aplus_texts`): trafienie oznacza jedno ponowienie z uwagami,
potem ostrzeżenie. Fakty (liczba kolorowanek, druk, format) wstawia program z manifestu.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from pydantic import BaseModel, ConfigDict

from kdp_studio.config import AplusBanned, AplusLimits, AppConfig, MarketProfile
from kdp_studio.pipeline.aplus_models import (
    AplusCopy,
    ColumnCopy,
    FeaturesCopy,
    HeaderCopy,
    OverlayCopy,
)
from kdp_studio.pipeline.listing import content_issues
from kdp_studio.providers.base import ProviderError, TextProvider, Usage

GROUP_LABELS = {
    "time": "nacisk czasem",
    "occasion": "święto jako termin albo okazja do zakupu",
    "claims": "przechwałka",
    "sales": "sprzedaż",
}


# --- Zakazane sformułowania -------------------------------------------------------------------


def _normalize(text: str) -> str:
    return text.replace("\u2019", "'").replace("\u2018", "'").casefold()


def _phrase(phrase: str) -> re.Pattern[str]:
    """Całe słowo albo fraza, bez rozróżniania wielkości liter; spacje jako dowolne odstępy.
    Myślnik łączy słowa: „screen-free” nie zawiera zakazanego „free”."""
    body = r"\s+".join(re.escape(part) for part in _normalize(phrase).split())
    return re.compile(rf"(?<![\w-]){body}(?![\w-])")


def _found(text: str, phrases: Iterable[str]) -> list[str]:
    return [p for p in phrases if _phrase(p).search(text)]


def _occasion(text: str, banned: AplusBanned) -> list[str]:
    """Nazwa święta tylko w pobliżu słowa terminu, zakupu albo prezentu („in time for Easter”,
    „perfect Christmas gift”). Święto jako temat („Christmas coloring book”) przechodzi."""
    occasion = banned.occasion
    hits = _found(text, occasion.phrases)
    for holiday in occasion.holidays:
        for match in _phrase(holiday).finditer(text):
            before = " ".join(re.findall(r"\S+", text[: match.start()])[-occasion.window :])
            after = " ".join(re.findall(r"\S+", text[match.end() :])[: occasion.window])
            for word in occasion.context:
                if _phrase(word).search(before) or _phrase(word).search(after):
                    hits.append(f"{holiday} + {word}")
                    break
    return hits


def banned_hits(texts: Iterable[str], banned: AplusBanned) -> list[str]:
    """Zakazane sformułowania w tekstach, opisane po polsku: „przechwałka: „best””."""
    text = _normalize(" \n ".join(texts))
    groups = {
        "time": _found(text, banned.time),
        "occasion": _occasion(text, banned),
        "claims": _found(text, banned.claims),
        "sales": _found(text, banned.sales),
    }
    return [
        f"{GROUP_LABELS[group]}: {', '.join(f'„{h}”' for h in dict.fromkeys(hits))}"
        for group, hits in groups.items()
        if hits
    ]


def copy_texts(copy: AplusCopy) -> list[str]:
    """Wszystkie teksty pól, w kolejności modułów."""
    texts: list[str] = []
    for header in (copy.header_fan, copy.header_pages):
        if header is not None:
            texts += [header.headline, header.subheadline, header.body]
    if copy.overlay_facts is not None:
        texts += [copy.overlay_facts.headline, *copy.overlay_facts.items]
    if copy.features is not None:
        texts.append(copy.features.headline)
        for column in copy.features.columns:
            texts += [column.headline, column.body]
    return [t for t in texts if t]


def copy_issues(copy: AplusCopy, banned: AplusBanned | None) -> list[str]:
    """Zakazane sformułowania A+ i treści niedozwolone w opisie (emoji, adresy, ceny)."""
    texts = copy_texts(copy)
    issues = banned_hits(texts, banned) if banned is not None else []
    return issues + content_issues(texts)


# --- Limity znaków ---------------------------------------------------------------------------


def clip(text: str, limit: int) -> str:
    """Tekst skrócony do `limit` znaków na granicy słowa (bez wielokropka)."""
    text = text.strip()
    if len(text) <= limit:
        return text
    cut = text[:limit]
    space = cut.rfind(" ")
    if space > limit // 2:
        cut = cut[:space]
    return cut.rstrip(" ,;:-–")


def overlay_body(items: Sequence[str]) -> str:
    """Tekst nakładki: punkty listy numerowanej, każdy w osobnym wierszu."""
    return "\n".join(items)


def apply_limits(copy: AplusCopy, limits: AplusLimits) -> tuple[AplusCopy, list[str]]:
    """Teksty przycięte do limitów edytora A+, z ostrzeżeniem przy każdym przycięciu."""
    warnings: list[str] = []

    def fit(where: str, text: str, limit: int) -> str:
        clipped = clip(text, limit)
        if clipped != text.strip():
            warnings.append(f"{where}: {len(text)} znaków, przycięto do {limit}")
        return clipped

    data = copy.model_copy(deep=True)
    for name in ("header_fan", "header_pages"):
        header = getattr(data, name)
        if header is not None:
            setattr(
                data,
                name,
                HeaderCopy(
                    headline=fit(f"{name}.headline", header.headline, limits.header.headline),
                    subheadline=fit(
                        f"{name}.subheadline", header.subheadline, limits.header.headline
                    ),
                    body=fit(f"{name}.body", header.body, limits.header.body),
                ),
            )
    overlay = data.overlay_facts
    if overlay is not None:
        headline = fit("overlay_facts.headline", overlay.headline, limits.overlay.headline)
        items = list(overlay.items)
        while items and len(overlay_body(items)) > limits.overlay.body:
            dropped = items.pop()
            warnings.append(
                f"overlay_facts: fakty nie mieszczą się w {limits.overlay.body} znakach, "
                f"pominięto „{dropped}”"
            )
        data.overlay_facts = OverlayCopy(headline=headline, items=items)
    features = data.features
    if features is not None:
        data.features = FeaturesCopy(
            headline=fit("features.headline", features.headline, limits.columns.module_headline),
            columns=[
                ColumnCopy(
                    headline=fit(f"features.{i}.headline", c.headline, limits.columns.headline),
                    body=fit(f"features.{i}.body", c.body, limits.columns.body),
                )
                for i, c in enumerate(features.columns, start=1)
            ],
        )
    return data, warnings


# --- Wywołanie LLM -----------------------------------------------------------------------------


class _Header(BaseModel):
    model_config = ConfigDict(extra="forbid")
    headline: str
    subheadline: str
    body: str


class _Column(BaseModel):
    model_config = ConfigDict(extra="forbid")
    headline: str
    body: str


class _AplusTexts(BaseModel):
    """Schemat odpowiedzi modelu: bez limitów (pilnuje ich kod, jak w FR-03)."""

    model_config = ConfigDict(extra="forbid")
    header: _Header
    pages_header: _Header
    overlay_headline: str
    features_headline: str
    columns: list[_Column]


SYSTEM = """You write the text fields of Amazon A+ Content modules for a printed coloring book.
A+ Content appears below the book description on the product page. Write in {language} for
{domain}. Use plain text only: no HTML, no Markdown, no emoji. Formatting is added later in the
A+ editor.

Amazon A+ rules (strict, a breach gets the content rejected):
- No time pressure or novelty: no words like "now", "new", "latest", "yet", "just released".
- No holidays or seasons as a date or a reason to buy: never "gift", "holiday gift", "stocking
  stuffer", "in time for Christmas", "before Easter", "holidays", "holiday season". A holiday may
  appear only as the subject of the pictures (e.g. "Christmas scenes with Santa and reindeer").
- No claims or awards: no "perfect", "best", "ultimate", "must-have", "#1", "top-rated",
  "bestseller", no guarantees, no "recommended by", "approved", "tested".
- No prices, discounts, "free", "bonus", "buy now", "add to cart", shipping or Kindle.
- No references to customer reviews, ratings or other products.
- Describe only what the book really contains; do not invent page counts or features.
{banned}
Character limits (hard): header headline and subheadline {header_headline}, header body
{header_body}; overlay headline {overlay_headline}; features headline {columns_module};
column headline {column_headline}, column body {column_body}. Prefer short, concrete texts:
header body 1-2 sentences, column body 1-2 sentences."""

USER = """Book title: {title}
Subtitle: {subtitle}
Audience: {audience}
Book description: {description}
Facts shown elsewhere on the page (do not repeat them in the columns): {facts}

Fields to write:
- header: texts for an image of the book covers fanned out (headline above the image,
  subheadline and a short body below it). Can be minimal.
- pages_header: texts for an image of a few inside pages laid side by side.
- overlay_headline: a short headline for an overlay that lists the facts above.
- features_headline: the headline of a module with {columns} columns.
- columns: exactly {columns} columns, one per picture below, in this order. Each column
  shows the named page; describe what the child or adult gets from it (benefit, level of
  difficulty for the age, calm screen-free fun), not a fact from the list above.
{scenes}"""


@dataclass(frozen=True)
class AplusTextResult:
    copy: AplusCopy
    usage: Usage
    attempts: int
    warnings: list[str] = field(default_factory=list)


def _banned_prompt(banned: AplusBanned | None) -> str:
    if banned is None:
        return ""
    words = [*banned.time, *banned.occasion.phrases, *banned.claims, *banned.sales]
    return "Never use these words or phrases: " + ", ".join(f'"{w}"' for w in words) + "."


class AplusWriter:
    """Teksty modułów A+: jedno wywołanie, przy zakazanych sformułowaniach jedno ponowienie."""

    def __init__(self, provider: TextProvider, config: AppConfig) -> None:
        self.provider = provider
        self.config = config

    def write(
        self,
        market: MarketProfile,
        banned: AplusBanned | None,
        *,
        title: str,
        subtitle: str,
        description: str,
        audience: str,
        facts: Sequence[str],
        scenes: Sequence[str],
    ) -> AplusTextResult:
        limits = self.config.settings.aplus.limits
        system = SYSTEM.format(
            language=market.language,
            domain=market.domain,
            banned=_banned_prompt(banned),
            header_headline=limits.header.headline,
            header_body=limits.header.body,
            overlay_headline=limits.overlay.headline,
            columns_module=limits.columns.module_headline,
            column_headline=limits.columns.headline,
            column_body=limits.columns.body,
        )
        user = USER.format(
            title=title,
            subtitle=subtitle,
            audience=audience,
            description=description,
            facts="; ".join(facts),
            columns=len(scenes),
            scenes="\n".join(f"Column {i}: {scene}" for i, scene in enumerate(scenes, start=1)),
        )
        usage = Usage()
        copy = AplusCopy()
        issues: list[str] = []
        attempts = 0
        for attempts in (1, 2):
            prompt = user
            if issues:
                prompt += (
                    "\n\nYour previous texts broke the A+ rules ("
                    + "; ".join(issues)
                    + "). Rewrite all fields without these words and phrases."
                )
            try:
                response, call_usage = self.provider.complete_json(system, prompt, _AplusTexts)
            except ProviderError:
                if attempts == 1 or not issues:
                    raise
                break  # ponowienie nieudane: zostają teksty z pierwszej próby z ostrzeżeniem
            usage += call_usage
            copy = _to_copy(response, facts, len(scenes))
            # Fakty wstawia program, więc ponowienie dotyczy tylko tekstów od modelu.
            model_part = copy.model_copy(update={"overlay_facts": None})
            issues = copy_issues(model_part, banned)
            if not issues:
                break
        warnings = [f"teksty A+: {issue}" for issue in issues]
        warnings += [f"fakty A+: {issue}" for issue in copy_issues(_facts_only(facts), banned)]
        if len(copy.features.columns if copy.features else []) != len(scenes):
            warnings.append(f"teksty A+: model dał inną liczbę kolumn niż {len(scenes)}")
        return AplusTextResult(copy=copy, usage=usage, attempts=attempts, warnings=warnings)


def _facts_only(facts: Sequence[str]) -> AplusCopy:
    return AplusCopy(overlay_facts=OverlayCopy(items=list(facts)))


def _to_copy(response: _AplusTexts, facts: Sequence[str], columns: int) -> AplusCopy:
    def header(h: _Header) -> HeaderCopy:
        return HeaderCopy(
            headline=h.headline.strip(), subheadline=h.subheadline.strip(), body=h.body.strip()
        )

    cols = [ColumnCopy(headline=c.headline.strip(), body=c.body.strip()) for c in response.columns]
    cols = cols[:columns] + [ColumnCopy() for _ in range(columns - len(cols))]
    return AplusCopy(
        header_fan=header(response.header),
        header_pages=header(response.pages_header),
        overlay_facts=OverlayCopy(headline=response.overlay_headline.strip(), items=list(facts)),
        features=FeaturesCopy(headline=response.features_headline.strip(), columns=cols),
    )
