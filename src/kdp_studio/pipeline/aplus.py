"""FR-24: krok A+ Content (`kdp-studio aplus`): plan modułów, grafiki, teksty, podgląd, manifest.

Bez wywołań API powstaje plan (moduły, strony, tabela porównawcza) i wszystkie grafiki. API
wołają tylko teksty (jedno wywołanie LLM, przy zakazanych sformułowaniach jedno ponowienie),
opcjonalnie pokolorowana strona i opcjonalnie grafiki kolumn z modelu (motywy z profilu wieku,
`aplus.features.source: generated`, jedno wywołanie na kolumnę, zapamiętywane po hashu).
Ponowne uruchomienie robi tylko to, co się zmieniło: grafiki według hasha okładki, stron
i ustawień, teksty według hasha metadanych i faktów; teksty poprawione ręcznie
w `aplus/texts.yaml` zostają.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import yaml
from PIL import Image
from pydantic import ValidationError

from kdp_studio.config import (
    AplusBanned,
    AplusComparisonBook,
    AplusFeatureTheme,
    AppConfig,
    MarketProfile,
)
from kdp_studio.models import BookIdeas
from kdp_studio.pipeline import aplus_images as images
from kdp_studio.pipeline.aplus_models import (
    EDITOR_MODULES,
    FOUR_COLUMNS,
    AplusBackgroundInfo,
    AplusColorPage,
    AplusCopy,
    AplusFeatureImage,
    AplusFileInfo,
    AplusInfo,
    AplusModuleInfo,
    ChartColumn,
    HeaderCopy,
    OverlayCopy,
    alt_key,
)
from kdp_studio.pipeline.aplus_preview import (
    PREVIEW_FILE,
    PreviewField,
    PreviewModule,
    render_preview,
)
from kdp_studio.pipeline.aplus_text import (
    AplusWriter,
    alt_issues,
    apply_limits,
    copy_issues,
    overlay_body,
)
from kdp_studio.pipeline.cost import CostTracker
from kdp_studio.pipeline.listing import book_facts, fact_lines
from kdp_studio.pipeline.manifest import Manifest, ManifestPage, sha256_bytes, sha256_file
from kdp_studio.pipeline.output import write_bytes_atomic
from kdp_studio.providers.base import ImageProvider, ImageRequest, ProviderError, TextProvider

APLUS_DIR = "aplus"
TEXTS_FILE = "texts.yaml"
RAW_DIR = "raw"
OVERLAY_PAGES = 3
COLOR_PROMPT = (
    "Color this black-and-white coloring page as a finished, neatly colored page, as if a "
    "child colored it with bright crayons and markers. Keep every line, shape and the "
    "composition exactly as they are; only fill the areas with color. White paper around the "
    "drawing. No text, no letters, no frame."
)
FEATURE_ASPECT = "1:1"
# Grafika kolumny z modelu: scena motywu z profilu wieku, strona książki jako referencja.
# Ograniczenia są w kodzie, nie w profilu: A+ nie może wprowadzać w błąd co do produktu.
FEATURE_PROMPT = (
    "A realistic, softly lit photo for the product page of a printed coloring book: {scene}. "
    "The coloring page in the photo is the reference image: keep its drawing, every line and "
    "shape, unchanged. The page shows {page_scene}.{theme} Only hands may appear: no faces, "
    "no heads, no whole people. The book is a glued paperback with plain white paper: no "
    "spiral binding, no perforated edges, no thick card pages. No text, no letters, no "
    "numbers, no logos, no brand marks, no watermarks. Square composition."
)


class AplusError(Exception):
    """Książka nie jest gotowa do A+ albo plik tekstów ma zły format (kod 1)."""

    def __init__(self, errors: list[str]) -> None:
        super().__init__("; ".join(errors))
        self.errors = errors


# --- Plan --------------------------------------------------------------------------------------


def aplus_blockers(book_dir: Path, manifest: Manifest) -> list[str]:
    """Czego brakuje do A+: stron `ok` (FR-17) i okładki `ok` z plikami (FR-15)."""
    problems = []
    missing = [
        p.name
        for p in manifest.pages
        if p.status != "ok" or not (book_dir / f"{p.name}.png").is_file()
    ]
    if missing:
        problems.append(
            f"strony bez statusu ok: {', '.join(missing)}; najpierw kdp-studio images i "
            f"finalize {book_dir}"
        )
    cover = manifest.cover
    files = cover.files if cover is not None else None
    if cover is None or cover.status != "ok" or files is None:
        problems.append(f"brak gotowej okładki (FR-15): najpierw kdp-studio cover {book_dir}")
    else:
        for name in (files.png, files.front):
            if name is None or not (book_dir / name).is_file():
                problems.append(f"brak pliku okładki {name}: kdp-studio cover {book_dir}")
    return problems


def spread(pages: Sequence[ManifestPage], count: int) -> list[ManifestPage]:
    """`count` stron rozłożonych równo po książce."""
    if count <= 0 or not pages:
        return []
    step = len(pages) / count
    indexes = dict.fromkeys(int(step * i + step / 2) for i in range(min(count, len(pages))))
    return [pages[i] for i in indexes]


@dataclass
class AplusPlan:
    modules: list[str]
    skipped: dict[str, str]
    features: list[ManifestPage]
    sheets: list[ManifestPage]
    strip: list[ManifestPage]
    chart: list[ChartColumn]
    warnings: list[str] = field(default_factory=list)


def _trim_text(trim: Sequence[float]) -> str:
    width, height = trim
    cm = f"{round(width * 2.54, 1):g} × {round(height * 2.54, 1):g} cm"
    return f"{width:g} × {height:g} in ({cm})"


def chart_column(
    book_dir: Path,
    manifest: Manifest,
    title: str,
    config: AppConfig,
    market: MarketProfile,
    labels: dict[str, str],
    asin: str | None,
) -> ChartColumn:
    """Kolumna tabeli porównawczej z manifestu książki (bez wywołań API)."""
    age = config.ages.get(manifest.input.age)
    age_text = market.terms.age_phrase(age.age_range if age is not None else None)
    return ChartColumn(
        asin=asin,
        book=str(book_dir),
        title=title,
        rows={
            labels["age"]: age_text,
            labels["pages"]: str(manifest.input.pages),
            labels["size"]: _trim_text(manifest.layout.trim_in),
        },
    )


def comparison_chart(
    book_dir: Path,
    manifest: Manifest,
    title: str,
    books: Sequence[AplusComparisonBook],
    config: AppConfig,
    market: MarketProfile,
    labels: dict[str, str],
    load: Callable[[Path], tuple[Manifest, str]],
) -> tuple[list[ChartColumn], list[str]]:
    """Kolumny tabeli: ta książka (gdy nie ma jej na liście, na początku, bez ASIN) i książki
    z konfiguracji. Książka bez manifestu wypada z ostrzeżeniem; najwyżej 6 kolumn."""
    warnings: list[str] = []
    columns: list[ChartColumn] = []
    here = book_dir.resolve()
    if all(Path(b.book).resolve() != here for b in books):
        columns.append(chart_column(book_dir, manifest, title, config, market, labels, None))
    for entry in books:
        path = Path(entry.book)
        if path.resolve() == here:
            columns.append(
                chart_column(book_dir, manifest, title, config, market, labels, entry.asin)
            )
            continue
        try:
            other, other_title = load(path)
        except (OSError, ValueError, KeyError) as e:
            warnings.append(f"tabela porównawcza: pominięto {entry.asin} ({path}): {e}")
            continue
        columns.append(chart_column(path, other, other_title, config, market, labels, entry.asin))
    if len(columns) > 6:
        warnings.append(f"tabela porównawcza: najwyżej 6 książek, pominięto {len(columns) - 6}")
        columns = columns[:6]
    return columns, warnings


def plan_aplus(
    book_dir: Path,
    manifest: Manifest,
    title: str,
    config: AppConfig,
    market: MarketProfile,
    labels: dict[str, str] | None,
    books: Sequence[AplusComparisonBook],
    load: Callable[[Path], tuple[Manifest, str]],
) -> AplusPlan:
    """Moduły w kolejności, strony do grafik i tabela porównawcza; bez wywołań API."""
    settings = config.settings.aplus
    modules: list[str] = list(settings.modules)
    skipped: dict[str, str] = {}
    warnings: list[str] = []
    chart: list[ChartColumn] = []
    if "logo" in modules:
        logo = settings.logo_path
        if logo is None:
            skipped["logo"] = (
                "brak banera: ustaw aplus.logo (plik 600 × 180 przygotowany poza programem)"
            )
        elif not logo.is_file():
            skipped["logo"] = f"brak pliku banera {logo} (aplus.logo)"
    if "comparison" in modules:
        if labels is None:
            chart, reason = [], "brak etykiet tabeli dla języka rynku (aplus_texts w markets.yaml)"
        else:
            chart, chart_warnings = comparison_chart(
                book_dir, manifest, title, books, config, market, labels, load
            )
            warnings += chart_warnings
            reason = "tabela porównawcza potrzebuje co najmniej 2 książek (aplus.comparison)"
        if len(chart) < 2:
            chart = []
            index = modules.index("comparison")
            if "header_pages" in modules:
                modules.pop(index)
                warnings.append(f"{reason}: moduł pominięty")
            else:
                modules[index] = "header_pages"
                warnings.append(f"{reason}: w jej miejscu drugi mockup (strony wnętrza)")
    cover = manifest.cover
    used = set()
    if cover is not None:
        used = {cover.front_page, *cover.thumbnails}
    ready = [p for p in manifest.pages if p.status == "ok"]
    rest = [p for p in ready if p.name not in used] or ready
    columns = settings.features.columns if "features" in modules else 0
    sheets = settings.header_pages.count if "header_pages" in modules else 0
    strip = OVERLAY_PAGES if "overlay_facts" in modules else 0
    picked = spread(rest, columns + sheets + strip)
    if len(picked) < columns + sheets + strip:
        picked = (picked * (columns + sheets + strip))[: columns + sheets + strip]
    groups: list[list[ManifestPage]] = [[], [], []]
    sizes = [columns, sheets, strip]
    cursor = 0
    for page in picked:  # na zmianę, żeby każda grafika miała strony z całej książki
        while len(groups[cursor % 3]) >= sizes[cursor % 3]:
            cursor += 1
        groups[cursor % 3].append(page)
        cursor += 1
    return AplusPlan(modules, skipped, groups[0], groups[1], groups[2], chart, warnings)


# --- Hashe -------------------------------------------------------------------------------------


def _sha(parts: Sequence[str]) -> str:
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()


def images_inputs_sha256(
    book_dir: Path,
    manifest: Manifest,
    plan: AplusPlan,
    config: AppConfig,
    color: Path | None,
    generated: Sequence[Path] = (),
) -> str:
    """Hash wejść grafik: pliki okładki i stron, ustawienia, baner, pokolorowana strona
    i grafiki kolumn z modelu."""
    cover = manifest.cover
    assert cover is not None and cover.files is not None
    settings = config.settings.aplus
    parts = [
        settings.model_dump_json(exclude={"limits", "comparison", "color_page"}),
        json.dumps(plan.modules),
        json.dumps(cover.geometry, sort_keys=True),
    ]
    for name in (cover.files.png, cover.files.front):
        assert name is not None
        parts.append(sha256_file(book_dir / name))
    for page in [*plan.features, *plan.sheets, *plan.strip]:
        parts.append(f"{page.name}:{sha256_file(book_dir / f'{page.name}.png')}")
    logo = settings.logo_path
    if logo is not None and logo.is_file():
        parts.append(sha256_file(logo))
    if color is not None:
        parts.append(sha256_file(color))
    parts += [f"generated:{sha256_file(path)}" for path in generated]
    return _sha(parts)


def texts_inputs_sha256(
    ideas: BookIdeas,
    facts: Sequence[str],
    scenes: Sequence[str],
    market: MarketProfile,
    config: AppConfig,
    banned: AplusBanned | None,
    images: Sequence[tuple[str, str]] = (),
) -> str:
    """Hash wejść tekstów: metadane, fakty, sceny kolumn, opisy grafik (do tekstów
    alternatywnych), rynek, limity i zakazane słowa."""
    book = ideas.book
    return _sha(
        [
            book.title,
            book.subtitle,
            book.description,
            *facts,
            *scenes,
            *(f"{key}: {what}" for key, what in images),
            market.model_dump_json(),
            config.settings.aplus.limits.model_dump_json(),
            "" if banned is None else banned.model_dump_json(),
        ]
    )


# --- Teksty ----------------------------------------------------------------------------------


def dump_texts(copy: AplusCopy) -> bytes:
    data = copy.model_dump(exclude_none=True)
    header = (
        "# Teksty modułów A+ (FR-24). Możesz je poprawić: program ich nie nadpisze przy kolejnym\n"
        "# `kdp-studio aplus`. Usuń plik, żeby powstały od nowa.\n"
    )
    return (header + yaml.safe_dump(data, allow_unicode=True, sort_keys=False)).encode("utf-8")


def load_texts(path: Path) -> AplusCopy:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return AplusCopy.model_validate(data)
    except (yaml.YAMLError, ValidationError, UnicodeDecodeError) as e:
        raise AplusError([f"{path}: zły format tekstów A+ ({e})"]) from e


# --- Wykonanie ---------------------------------------------------------------------------------


@dataclass
class AplusOutcome:
    info: AplusInfo
    written_images: bool
    texts_source: str  # "model", "zapisane", "poprawione ręcznie", "brak"
    budget_exceeded: bool = False
    provider_error: ProviderError | None = None


@dataclass
class AplusRun:
    book_dir: Path
    manifest: Manifest
    ideas: BookIdeas
    config: AppConfig
    market: MarketProfile
    banned: AplusBanned | None
    plan: AplusPlan
    color_page: bool
    quality: str
    feature_images: bool = False  # kolumny z grafikami z modelu (aplus.features.source)
    text_provider: TextProvider | None = None
    image_provider: ImageProvider | None = None
    costs: CostTracker | None = None
    log: Callable[[str], None] = print

    @property
    def out(self) -> Path:
        return self.book_dir / APLUS_DIR

    def facts(self) -> list[str]:
        texts = self.config.markets.texts_for(self.market.locale)
        if texts is None or not texts.listing:
            return []
        # Kolumna z motywem o druku jednostronnym przejmuje ten fakt: nakładka go nie powtarza.
        taken = {t.fact for t in self.themes() if t is not None}
        return fact_lines(
            book_facts(self.manifest, self.config),
            texts.listing,
            single_sided_fact="single_sided" not in taken,
        )

    def scenes(self) -> list[str]:
        """Co pokazuje każda kolumna, dla modelu tekstów: scena strony albo motyw z korzyścią."""
        ideas = {i.id: i for i in self.ideas.pages}
        result = []
        for page, theme in zip(self.plan.features, self.themes(), strict=True):
            if theme is None:
                result.append(ideas[page.idea_id].scene if page.idea_id in ideas else page.name)
            else:
                result.append(
                    f"a photo of {theme.scene}; the page shows {self._page_scene(page)}. "
                    f"Write about this benefit: {theme.benefit}"
                )
        return result

    # --- Kolumny z grafikami z modelu ---

    def themes(self) -> list[AplusFeatureTheme | None]:
        """Motyw każdej kolumny (None: strona książki). Motywy z profilu wieku, w kolejności,
        bez tych, których warunek książka nie spełnia (np. druk jednostronny)."""
        count = len(self.plan.features)
        if not self.feature_images or "features" not in self.plan.modules:
            return [None] * count
        age = self.config.ages.get(self.manifest.input.age)
        single_sided = self.manifest.input.single_sided
        fitting = [
            t
            for t in (age.aplus_features if age is not None else [])
            if t.requires != "single_sided" or single_sided
        ]
        themes: list[AplusFeatureTheme | None] = list(fitting[:count])
        return themes + [None] * (count - len(themes))

    def theme_warnings(self) -> list[str]:
        if not self.feature_images or "features" not in self.plan.modules:
            return []
        missing = sum(1 for t in self.themes() if t is None)
        if not missing:
            return []
        return [
            f"kolumny A+: za mało motywów dla wieku {self.manifest.input.age} (aplus_features w "
            f"ages.yaml): {missing} z {len(self.plan.features)} kolumn ze stronami książki"
        ]

    def color_column(self) -> int | None:
        """Kolumna (od 0) z pokolorowaną stroną: pierwsza ze stroną książki, nie z modelu."""
        if not self.color_page:
            return None
        return next((k for k, t in enumerate(self.themes()) if t is None), None)

    def _feature_prompt(self, theme: AplusFeatureTheme, page: ManifestPage) -> str:
        anchors = self.ideas.theme_anchors
        return FEATURE_PROMPT.format(
            scene=theme.scene.strip().rstrip("."),
            page_scene=self._page_scene(page),
            theme=f" The book's theme: {', '.join(anchors)}." if anchors else "",
        )

    def _feature_quality(self) -> str:
        return self.config.settings.aplus.features.image_quality or self.quality

    def _feature_sha(self, prompt: str, page: ManifestPage) -> str:
        return _sha(
            [
                prompt,
                sha256_file(self.book_dir / f"{page.name}.png"),
                self.config.settings.models.image,
                self._feature_quality(),
            ]
        )

    def _feature_raw(self, column: int) -> Path:
        return self.out / RAW_DIR / f"features_{column}.png"

    def _cached_feature(
        self, column: int, theme: AplusFeatureTheme, page: ManifestPage
    ) -> AplusFeatureImage | None:
        previous = self.manifest.aplus.feature_images if self.manifest.aplus else []
        sha = self._feature_sha(self._feature_prompt(theme, page), page)
        for entry in previous:
            if (
                entry.column == column
                and entry.inputs_sha256 == sha
                and (self.book_dir / entry.raw).is_file()
            ):
                return entry
        return None

    def features_needed(self) -> bool:
        """Czy któraś kolumna potrzebuje nowej grafiki z modelu (wywołanie API)."""
        return any(
            theme is not None and self._cached_feature(k, theme, page) is None
            for k, (page, theme) in enumerate(
                zip(self.plan.features, self.themes(), strict=True), start=1
            )
        )

    def _feature_images(self, outcome: AplusOutcome) -> dict[int, Path]:
        """Grafiki kolumn z modelu (kolumna od 1 → plik). Kolumna bez grafiki dostaje stronę
        książki z ostrzeżeniem; błąd krytyczny dostawcy przerywa krok."""
        result: dict[int, Path] = {}
        outcome.info.warnings += self.theme_warnings()
        for k, (page, theme) in enumerate(
            zip(self.plan.features, self.themes(), strict=True), start=1
        ):
            if theme is None:
                continue
            cached = self._cached_feature(k, theme, page)
            if cached is not None:
                outcome.info.feature_images.append(cached)
                result[k] = self.book_dir / cached.raw
                continue
            fallback = f"kolumna {k} ({theme.label}): strona książki zamiast grafiki z modelu"
            provider = self.image_provider
            assert provider is not None
            if FEATURE_ASPECT not in provider.supported_aspects():
                outcome.info.warnings.append(
                    f"{fallback} ({provider.name} nie rysuje kwadratów {FEATURE_ASPECT})"
                )
                continue
            if self.costs is not None and self.costs.over_budget():
                outcome.budget_exceeded = True
                outcome.info.warnings.append(f"{fallback} (przekroczony limit kosztu)")
                continue
            prompt = self._feature_prompt(theme, page)
            source = self.book_dir / f"{page.name}.png"
            quality = self._feature_quality()
            self.log(f"Grafika kolumny {k} ({theme.label}, {provider.name}, {provider.model})…")
            try:
                image = provider.generate(
                    ImageRequest(
                        prompt=prompt,
                        aspect=FEATURE_ASPECT,
                        quality=quality,
                        reference_image=source.read_bytes(),
                    )
                )
            except ProviderError as e:
                if e.fatal:
                    raise
                outcome.info.warnings.append(f"{fallback} ({e})")
                continue
            if self.costs is not None:
                self.costs.add("images", provider.model, image.usage)
            raw = self._feature_raw(k)
            raw.parent.mkdir(parents=True, exist_ok=True)
            write_bytes_atomic(raw, image.png_bytes)
            outcome.info.feature_images.append(
                AplusFeatureImage(
                    column=k,
                    theme=theme.key,
                    page=page.name,
                    prompt=prompt,
                    raw=raw.relative_to(self.book_dir).as_posix(),
                    inputs_sha256=self._feature_sha(prompt, page),
                    model=provider.model,
                    quality=quality,
                )
            )
            result[k] = raw
        return result

    def _page_scene(self, page: ManifestPage) -> str:
        ideas = {i.id: i for i in self.ideas.pages}
        idea = ideas.get(page.idea_id)
        return idea.scene.strip().rstrip(".") if idea is not None else page.name

    def alt_images(self) -> list[tuple[str, str]]:
        """Grafiki, które dostają tekst alternatywny od modelu: (klucz `alt_key()`, co pokazuje
        grafika, po angielsku). Baner ma tekst z `aplus.logo_alt`, nie od modelu."""
        title = self.ideas.book.title
        result: list[tuple[str, str]] = []
        for name in self.plan.modules:
            if name in self.plan.skipped or name == "logo":
                continue
            if name == "header_fan":
                result.append(
                    (
                        name,
                        f'The front and back covers of the coloring book "{title}", lying flat '
                        "and fanned out on a plain background",
                    )
                )
            elif name == "header_pages":
                scenes = "; ".join(self._page_scene(p) for p in self.plan.sheets)
                result.append(
                    (
                        name,
                        f"{len(self.plan.sheets)} black-and-white inside pages of the coloring "
                        f"book, fanned out: {scenes}",
                    )
                )
            elif name == "overlay_facts":
                scenes = "; ".join(self._page_scene(p) for p in self.plan.strip)
                result.append(
                    (
                        name,
                        f"A row of {len(self.plan.strip)} black-and-white coloring pages from "
                        f"the book: {scenes}",
                    )
                )
            elif name == "features":
                color_column = self.color_column()
                for k, (page, theme) in enumerate(
                    zip(self.plan.features, self.themes(), strict=True), start=1
                ):
                    if theme is not None:
                        what = f"A photo of {theme.scene}; the page shows {self._page_scene(page)}"
                        result.append((alt_key(name, k), what))
                        continue
                    kind = (
                        "A coloring page from the book, colored in with crayons"
                        if color_column == k - 1
                        else "A black-and-white coloring page from the book"
                    )
                    result.append((alt_key(name, k), f"{kind}: {self._page_scene(page)}"))
            elif name == "comparison":
                for k, column in enumerate(self.plan.chart, start=1):
                    result.append(
                        (alt_key(name, k), f'The front cover of the coloring book "{column.title}"')
                    )
        return result

    def alt_keys(self) -> list[str]:
        """Klucze tekstów alternatywnych wszystkich grafik, z banerem."""
        logo = "logo" in self.plan.modules and "logo" not in self.plan.skipped
        return (["logo"] if logo else []) + [key for key, _ in self.alt_images()]

    def _with_logo_alt(self, copy: AplusCopy) -> AplusCopy:
        """Tekst alternatywny banera z `aplus.logo_alt`, chyba że plik tekstów ma własny."""
        logo_alt = self.config.settings.aplus.logo_alt
        if "logo" not in self.alt_keys() or not logo_alt or copy.alt.get("logo"):
            return copy
        return copy.model_copy(update={"alt": {"logo": logo_alt.strip(), **copy.alt}})

    def texts_state(self) -> str:
        """„edited”, „current” albo „new”: czy teksty trzeba napisać modelem."""
        previous = self.manifest.aplus
        path = self.out / TEXTS_FILE
        if not path.is_file() or previous is None:
            return "new"
        if previous.texts_sha256 is not None and sha256_file(path) != previous.texts_sha256:
            return "edited"
        inputs = texts_inputs_sha256(
            self.ideas,
            self.facts(),
            self.scenes(),
            self.market,
            self.config,
            self.banned,
            self.alt_images(),
        )
        return "current" if previous.texts_inputs_sha256 == inputs else "new"

    def color_needed(self) -> bool:
        column = self.color_column()
        if column is None or not self.plan.features:
            return False
        previous = self.manifest.aplus.color_page if self.manifest.aplus else None
        page = self.plan.features[column]
        raw = self.out / RAW_DIR / f"{page.name}_color.png"
        page_sha = sha256_file(self.book_dir / f"{page.name}.png")
        return not (
            previous is not None
            and previous.page == page.name
            and previous.page_sha256 == page_sha
            and raw.is_file()
        )

    # --- Pokolorowana strona ---

    def _color_page(self, outcome: AplusOutcome) -> Path | None:
        column = self.color_column()
        if self.color_page and column is None and self.plan.features:
            outcome.info.warnings.append(
                "pokolorowana strona: wszystkie kolumny mają grafiki z modelu, pominięta"
            )
        if column is None or not self.plan.features:
            return None
        page = self.plan.features[column]
        raw = self.out / RAW_DIR / f"{page.name}_color.png"
        previous = self.manifest.aplus.color_page if self.manifest.aplus else None
        if not self.color_needed():
            outcome.info.color_page = previous
            return raw
        provider = self.image_provider
        assert provider is not None
        if self.costs is not None and self.costs.over_budget():
            outcome.budget_exceeded = True
            outcome.info.warnings.append("przekroczony limit kosztu: bez pokolorowanej strony")
            return None
        ideas = {i.id: i for i in self.ideas.pages}
        idea = ideas.get(page.idea_id)
        prompt = COLOR_PROMPT + (
            f"\nThe picture shows: {idea.scene.strip().rstrip('.')}." if idea is not None else ""
        )
        source = self.book_dir / f"{page.name}.png"
        aspect = self.config.formats[self.manifest.input.format].aspect
        self.log(f"Koloruję stronę {page.name} ({provider.name}, {provider.model})…")
        try:
            result = provider.generate(
                ImageRequest(
                    prompt=prompt,
                    aspect=aspect,
                    quality=self.quality,
                    reference_image=source.read_bytes(),
                )
            )
        except ProviderError as e:
            if e.fatal:
                raise
            outcome.info.warnings.append(f"pokolorowana strona: {e}")
            return None
        if self.costs is not None:
            self.costs.add("images", provider.model, result.usage)
        raw.parent.mkdir(parents=True, exist_ok=True)
        write_bytes_atomic(raw, result.png_bytes)
        outcome.info.color_page = AplusColorPage(
            page=page.name,
            prompt=prompt,
            raw=raw.relative_to(self.book_dir).as_posix(),
            page_sha256=sha256_file(source),
            model=provider.model,
            quality=self.quality,
        )
        return raw

    # --- Grafiki ---

    def _file_info(self, saved: images.SavedImage) -> AplusFileInfo:
        return AplusFileInfo(
            path=saved.path.relative_to(self.book_dir).as_posix(),
            width=saved.width,
            height=saved.height,
            bytes=saved.bytes,
        )

    def _render(
        self, color: Path | None, generated: dict[int, Path], outcome: AplusOutcome
    ) -> None:
        """Wszystkie grafiki modułów (bez API), stare pliki z katalogu aplus/ znikają."""
        settings = self.config.settings.aplus
        cover = self.manifest.cover
        assert cover is not None and cover.files is not None
        assert cover.files.png is not None and cover.files.front is not None
        ext = settings.image_format
        self.out.mkdir(parents=True, exist_ok=True)
        for old in list(self.out.glob("*.jpg")) + list(self.out.glob("*.png")):
            old.unlink()
        with Image.open(self.book_dir / cover.files.png) as full:
            back, spine = images.cover_faces(full, cover.geometry)
        with Image.open(self.book_dir / cover.files.front) as front_file:
            front = front_file.convert("RGB")
        choice = images.pick_background([front, back], settings.header_fan.background)
        outcome.info.background = AplusBackgroundInfo(
            name=choice.name,
            rgb=choice.rgb,
            delta_e=choice.delta_e,
            darkened_steps=choice.darkened_steps,
            scores=choice.scores,
        )
        if choice.delta_e < settings.header_fan.background.min_delta_e:
            outcome.info.warnings.append(
                f"tło {choice.name}: ΔE {choice.delta_e:g} poniżej progu "
                f"{settings.header_fan.background.min_delta_e:g} mimo przyciemnienia"
            )

        color_column = self.color_column()

        def page_image(page: ManifestPage) -> Image.Image:
            with Image.open(self.book_dir / f"{page.name}.png") as file:
                return file.convert("RGB")

        scale = settings.scale
        for index, name in enumerate(self.plan.modules, start=1):
            info = AplusModuleInfo(name=name, editor=EDITOR_MODULES[name])
            stem = self.out / f"{index:02d}_{name}"
            if name in self.plan.skipped:
                info.skipped = self.plan.skipped[name]
            elif name == "logo":
                logo = settings.logo_path
                assert logo is not None
                saved, logo_warnings = images.prepare_logo(
                    logo, stem.with_suffix(f".{ext}"), settings
                )
                info.files.append(self._file_info(saved))
                outcome.info.warnings += logo_warnings
            elif name == "header_fan":
                img = images.fan_header(
                    front,
                    back,
                    spine,
                    choice.rgb,
                    settings.header_fan,
                    images.scaled(images.HEADER_SIZE, scale),
                )
                saved = images.save_image(img, stem.with_suffix(f".{ext}"), settings)
                info.files.append(self._file_info(saved))
            elif name == "header_pages":
                img = images.pages_header(
                    [page_image(p) for p in self.plan.sheets],
                    choice.rgb,
                    settings.header_pages,
                    settings.header_fan,
                    images.scaled(images.HEADER_SIZE, scale),
                )
                saved = images.save_image(img, stem.with_suffix(f".{ext}"), settings)
                info.files.append(self._file_info(saved))
                info.pages = [p.name for p in self.plan.sheets]
            elif name == "overlay_facts":
                img = images.overlay_strip(
                    [page_image(p) for p in self.plan.strip],
                    choice.rgb,
                    settings.header_fan,
                    images.scaled(images.OVERLAY_SIZE, scale),
                    settings.overlay_facts,
                )
                saved = images.save_image(img, stem.with_suffix(f".{ext}"), settings)
                info.files.append(self._file_info(saved))
                info.pages = [p.name for p in self.plan.strip]
            elif name == "features":
                columns = settings.features.columns
                if columns == 4:
                    info.editor = FOUR_COLUMNS
                side = images.COLUMN_SIDE[columns] * scale
                for k, page in enumerate(self.plan.features, start=1):
                    if k in generated:
                        with Image.open(generated[k]) as model_image:
                            square = images.photo_square(model_image, side)
                    elif color is not None and color_column == k - 1:
                        with Image.open(color) as colored:
                            square = images.column_square(colored, side, settings.features.margin)
                    else:
                        square = images.column_square(
                            page_image(page), side, settings.features.margin
                        )
                    path = self.out / f"{index:02d}_features_{k}.{ext}"
                    info.files.append(self._file_info(images.save_image(square, path, settings)))
                info.pages = [p.name for p in self.plan.features]
            outcome.info.modules.append(info)

    # --- Teksty ---

    def _texts(self, outcome: AplusOutcome) -> None:
        self._write_texts(outcome)
        info = outcome.info
        info.texts = self._with_logo_alt(info.texts)
        if outcome.texts_source == "brak":
            return
        # Grafiki od modelu sprawdza już AplusWriter; tu baner i pliki poprawione ręcznie.
        keys = self.alt_keys() if outcome.texts_source != "model" else ["logo"]
        keys = [k for k in keys if k in self.alt_keys()]
        for issue in alt_issues(info.texts, keys):
            hint = " (baner: ustaw aplus.logo_alt)" if "logo" in issue else ""
            info.warnings.append(f"teksty A+: {issue}{hint}")

    def _write_texts(self, outcome: AplusOutcome) -> None:
        path = self.out / TEXTS_FILE
        state = self.texts_state()
        previous = self.manifest.aplus
        facts = self.facts()
        scenes = self.scenes()
        images = self.alt_images()
        inputs = texts_inputs_sha256(
            self.ideas, facts, scenes, self.market, self.config, self.banned, images
        )
        limits = self.config.settings.aplus.limits
        if state == "edited":
            copy = load_texts(path)
            outcome.texts_source = "poprawione ręcznie"
            outcome.info.texts_edited = True
            outcome.info.texts_sha256 = previous.texts_sha256 if previous else None
            outcome.info.texts_inputs_sha256 = previous.texts_inputs_sha256 if previous else None
            _, limit_warnings = apply_limits(copy, limits)
            outcome.info.warnings += [f"{w} (plik poprawiony ręcznie)" for w in limit_warnings]
            outcome.info.warnings += [
                f"teksty A+: {issue}" for issue in copy_issues(copy, self.banned)
            ]
            outcome.info.texts = copy
            return
        if state == "current" and previous is not None:
            outcome.texts_source = "zapisane"
            outcome.info.texts = previous.texts
            outcome.info.texts_sha256 = previous.texts_sha256
            outcome.info.texts_inputs_sha256 = previous.texts_inputs_sha256
            return
        provider = self.text_provider
        assert provider is not None
        if self.costs is not None and self.costs.over_budget():
            outcome.budget_exceeded = True
            outcome.texts_source = "brak"
            outcome.info.warnings.append("przekroczony limit kosztu: teksty A+ nie powstały")
            return
        self.log(f"Piszę teksty A+ ({provider.name}, {provider.model})…")
        try:
            result = AplusWriter(provider, self.config).write(
                self.market,
                self.banned,
                title=self.ideas.book.title,
                subtitle=self.ideas.book.subtitle,
                description=self.ideas.book.description,
                audience=self._audience(),
                facts=facts,
                scenes=scenes,
                images=images,
            )
        except ProviderError as e:
            if e.fatal:
                raise
            outcome.provider_error = e
            outcome.texts_source = "brak"
            outcome.info.warnings.append(f"teksty A+: {e}")
            return
        if self.costs is not None:
            self.costs.add("aplus", provider.model, result.usage)
        copy, limit_warnings = apply_limits(result.copy, limits)
        outcome.info.warnings += result.warnings + limit_warnings
        data = dump_texts(copy)
        write_bytes_atomic(path, data)
        outcome.texts_source = "model"
        outcome.info.texts = copy
        outcome.info.texts_sha256 = sha256_bytes(data)
        outcome.info.texts_inputs_sha256 = inputs

    def _audience(self) -> str:
        age = self.config.ages.get(self.manifest.input.age)
        return self.market.terms.age_phrase(age.age_range if age is not None else None)

    # --- Całość ---

    def run(self) -> AplusOutcome:
        previous = self.manifest.aplus
        info = AplusInfo(
            created_at=datetime.now(UTC).isoformat(timespec="seconds"),
            modules=[],
            chart=self.plan.chart,
            warnings=list(self.plan.warnings),
            cost_usd=previous.cost_usd if previous is not None else 0.0,
        )
        outcome = AplusOutcome(info=info, written_images=False, texts_source="brak")
        spent_before = self.costs.spent if self.costs is not None else 0.0
        try:
            color = self._color_page(outcome)
            generated = self._feature_images(outcome)
            sha = images_inputs_sha256(
                self.book_dir,
                self.manifest,
                self.plan,
                self.config,
                color,
                [generated[k] for k in sorted(generated)],
            )
            files_ok = previous is not None and all(
                (self.book_dir / f.path).is_file() for m in previous.modules for f in m.files
            )
            if previous is not None and previous.images_sha256 == sha and files_ok:
                info.modules = previous.modules
                info.background = previous.background
            else:
                self._render(color, generated, outcome)
                outcome.written_images = True
            info.images_sha256 = sha
            self._texts(outcome)
        finally:
            spent = (self.costs.spent if self.costs is not None else 0.0) - spent_before
            info.cost_usd = round(info.cost_usd + spent, 6)
        if outcome.provider_error is not None or outcome.budget_exceeded:
            info.status = "partial"
        write_bytes_atomic(
            self.book_dir / PREVIEW_FILE,
            render_preview(self.ideas.book.title, preview_modules(info, self.config)).encode(),
        )
        return outcome


# --- Podgląd -----------------------------------------------------------------------------------


def preview_modules(info: AplusInfo, config: AppConfig) -> list[PreviewModule]:
    """Moduły podglądu `aplus.html` z grafikami i polami w kolejności edytora."""
    limits = config.settings.aplus.limits
    texts = info.texts
    result: list[PreviewModule] = []
    for index, module in enumerate(info.modules, start=1):
        title = f"{index}. {module.editor}"
        note = ""
        fields: list[PreviewField] = []
        warnings = [module.skipped] if module.skipped else []
        if module.name == "logo":
            note = "Baner wydawcy, wspólny dla wszystkich książek. Bez pól tekstowych."
        elif module.name in ("header_fan", "header_pages"):
            header = getattr(texts, module.name) or HeaderCopy()
            note = "Mockup gotowej książki: wystarczy minimum tekstu, pola można zostawić puste."
            fields = [
                PreviewField("Nagłówek nad obrazem", header.headline, limits.header.headline),
                PreviewField("Nagłówek pod obrazem", header.subheadline, limits.header.headline),
                PreviewField(
                    "Tekst",
                    header.body,
                    limits.header.body,
                    hint="Najważniejsze słowa możesz pogrubić paskiem edytora.",
                ),
            ]
        elif module.name == "overlay_facts":
            overlay = texts.overlay_facts or OverlayCopy()
            side = "prawa" if config.settings.aplus.overlay_facts.text_side == "right" else "lewa"
            note = (
                f"Wybierz jasną nakładkę (Light). Na komputerze Amazon kładzie ramkę z tekstem "
                f"na obrazie ({side} część jest pod nią pusta); na telefonie tekst jest pod "
                "obrazem."
            )
            fields = [
                PreviewField("Nagłówek", overlay.headline, limits.overlay.headline),
                PreviewField(
                    "Tekst: fakty z manifestu",
                    overlay_body(overlay.items),
                    limits.overlay.body,
                    hint="Wklej, zaznacz wszystkie wiersze i włącz listę numerowaną w pasku "
                    "edytora.",
                    lines=True,
                ),
            ]
        elif module.name == "features":
            features = texts.features
            note = "Obraz każdej kolumny to strona książki; teksty mówią o korzyściach."
            if info.feature_images:
                columns = ", ".join(str(f.column) for f in info.feature_images)
                note = (
                    f"Kolumny {columns} mają grafiki z modelu obrazu (motywy z profilu wieku), "
                    "pozostałe to strony książki. Przy wgrywaniu tych grafik zaznacz w bibliotece "
                    "grafik pole „AI-generated people”, bo pokazują dłonie z modelu."
                )
            if features is not None:
                fields = [
                    PreviewField(
                        "Nagłówek modułu", features.headline, limits.columns.module_headline
                    )
                ]
                for k, column in enumerate(features.columns, start=1):
                    fields += [
                        PreviewField(
                            f"Kolumna {k}: nagłówek", column.headline, limits.columns.headline
                        ),
                        PreviewField(f"Kolumna {k}: tekst", column.body, limits.columns.body),
                    ]
        elif module.name == "comparison":
            note = (
                "Tabelę układa się w KDP z numerów ASIN książek z Twojego konta; wiersze cech "
                "przepisz z tabeli niżej."
            )
        is_chart = module.name == "comparison"
        result.append(
            PreviewModule(
                title=title,
                note=note,
                images=module.files,
                fields=fields,
                chart=info.chart if is_chart else (),
                warnings=warnings,
                alts=[
                    texts.alt.get(alt_key(module.name, k), "")
                    for k in range(1, len(module.files) + 1)
                ],
                chart_alts=[
                    texts.alt.get(alt_key("comparison", k), "")
                    for k in range(1, len(info.chart) + 1)
                ]
                if is_chart
                else (),
                alt_limit=limits.alt_text,
            )
        )
    return result


def load_other_book(path: Path) -> tuple[Manifest, str]:
    """Manifest i tytuł innej książki do tabeli porównawczej."""
    data = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
    manifest = Manifest.model_validate(data)
    ideas = json.loads((path / "ideas.json").read_text(encoding="utf-8"))
    return manifest, str(ideas["book"]["title"])
