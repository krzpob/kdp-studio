"""Ładowanie i walidacja konfiguracji z katalogu `config/` (spec §7, §9.2)."""

from __future__ import annotations

import os
from datetime import date
from decimal import Decimal
from itertools import pairwise
from pathlib import Path
from typing import Annotated, Any, Literal, Self, get_args

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

CONFIG_DIR_ENV = "KDP_STUDIO_CONFIG_DIR"
DEFAULT_CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"

POTRACE_ALPHAMAX_MAX = 1.3334  # powyżej potrace nie tworzy narożników


class ConfigError(Exception):
    """Nieprawidłowa lub brakująca konfiguracja (kod wyjścia 1)."""


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class PotraceParams(_Strict):
    turdsize: Annotated[int, Field(ge=0)]
    alphamax: Annotated[float, Field(ge=0, le=POTRACE_ALPHAMAX_MAX)]
    opttolerance: Annotated[float, Field(ge=0)]


class PostprocessParams(_Strict):
    threshold: Literal["otsu"] | Annotated[int, Field(ge=0, le=255)]
    min_speck_area: Annotated[int, Field(ge=0)]
    potrace: PotraceParams


class BelongsToAge(_Strict):
    """Napis i miejsce na imię na stronie „This book belongs to…” dla wieku (FR-14)."""

    font_pt: Annotated[float, Field(gt=0)] = 36
    name_line_height_in: Annotated[float, Field(gt=0)] = 0.7
    outline_text: bool = False


class AgeProfile(_Strict):
    name: str
    description: str
    line: str
    subjects: str
    background: str
    fill_areas: str
    prompt_fragment: str
    # FR-03b: minimalny udział stron z 2+ postaciami; 0 wyłącza (np. jeden obiekt dla maluchów)
    multi_subject_share: Annotated[float, Field(ge=0, le=1)] = 0.0
    # FR-19: wiek dzieci [od, do] do wzoru wieku rynku (terms.ages); brak = dorośli (terms.adults)
    age_range: tuple[Annotated[int, Field(ge=0)], Annotated[int, Field(ge=0)]] | None = None
    belongs_to: BelongsToAge = BelongsToAge()
    postprocess: PostprocessParams

    @model_validator(mode="after")
    def _age_range_order(self) -> Self:
        if self.age_range is not None and self.age_range[0] > self.age_range[1]:
            raise ValueError(f"age_range: od > do ({self.age_range[0]} > {self.age_range[1]})")
        return self


class StyleProfile(_Strict):
    name: str
    description: str
    prompt_fragment: str
    allowed_ages: list[str] | None = None

    def allows(self, age: str) -> bool:
        return self.allowed_ages is None or age in self.allowed_ages


class FormatProfile(_Strict):
    name: str
    description: str
    trim_in: tuple[Annotated[float, Field(gt=0)], Annotated[float, Field(gt=0)]]
    dpi: Annotated[int, Field(gt=0)]
    page_px: tuple[Annotated[int, Field(gt=0)], Annotated[int, Field(gt=0)]]
    aspect: Annotated[str, Field(pattern=r"^\d+:\d+$")]
    safe_margin_in: Annotated[float, Field(ge=0)]
    composition_hint: str

    @model_validator(mode="after")
    def _page_px_matches_trim(self) -> Self:
        expected = (round(self.trim_in[0] * self.dpi), round(self.trim_in[1] * self.dpi))
        if self.page_px != expected:
            raise ValueError(f"page_px {list(self.page_px)} != trim_in × dpi {list(expected)}")
        return self


class ProviderSettings(_Strict):
    """Nazwy implementacji z rejestru `kdp_studio.providers.registry` (spec §8.2)."""

    text: str = "openai"
    image: str = "openai"
    vision: str = "openai"  # QA (FR-07)


class ModelSettings(_Strict):
    text: Annotated[str, Field(min_length=1)] = "gpt-6-luna"
    image: Annotated[str, Field(min_length=1)] = "gpt-image-2.6-flare"
    vision: Annotated[str, Field(min_length=1)] = "gpt-6-luna"  # QA (FR-07)


ImageQuality = Literal["low", "medium", "high", "auto"]
LogLevel = Literal["info", "debug"]  # NFR-09
MAX_CONCURRENCY = 16
MAX_QA_RETRIES = 5
MAX_QA_IDEAS = 5  # pomysły na stronę przy QA (własny i zapasowe)


class GutterRow(_Strict):
    max_pages: Annotated[int, Field(gt=0)]
    gutter_in: Annotated[float, Field(ge=0)]


class KdpMargins(_Strict):
    """Tabela marginesów KDP bez spadu (spec §7.4)."""

    outside_min_in: Annotated[float, Field(ge=0)] = 0.25
    gutter_by_pages: Annotated[list[GutterRow], Field(min_length=1)] = [
        GutterRow(max_pages=150, gutter_in=0.375),
        GutterRow(max_pages=300, gutter_in=0.5),
        GutterRow(max_pages=500, gutter_in=0.625),
        GutterRow(max_pages=700, gutter_in=0.75),
        GutterRow(max_pages=828, gutter_in=0.875),
    ]

    @model_validator(mode="after")
    def _rows_increase(self) -> Self:
        rows = self.gutter_by_pages
        for prev, row in pairwise(rows):
            if row.max_pages <= prev.max_pages or row.gutter_in <= prev.gutter_in:
                raise ValueError(
                    "wiersze gutter_by_pages muszą rosnąć według max_pages i gutter_in"
                )
        return self

    @property
    def max_pages(self) -> int:
        return self.gutter_by_pages[-1].max_pages

    def gutter_in(self, pages_in_book: int) -> float | None:
        """Margines przy grzbiecie dla książki o `pages_in_book` stronach; None ponad tabelą."""
        for row in self.gutter_by_pages:
            if pages_in_book <= row.max_pages:
                return row.gutter_in
        return None


Share = Annotated[float, Field(gt=0, le=1)]


class DiversitySettings(_Strict):
    """Limity różnorodności pomysłów (FR-03b): najwyższy udział stron z tą samą wartością."""

    max_action_share: Share = 0.3
    max_setting_share: Share = 0.3
    max_element_share: Share = 0.35


class ModelPrice(_Strict):
    """Cena modelu w USD za milion tokenów (FR-10)."""

    input_per_1m: Annotated[float, Field(ge=0)]
    output_per_1m: Annotated[float, Field(ge=0)]


class ApiPricing(_Strict):
    """Cennik API przepisany ze strony dostawcy (FR-10); źródło i data dla kontroli."""

    source: str = ""
    checked: str = ""
    models: dict[str, ModelPrice] = {}


DEFAULT_MAX_COST_USD = 5.0
CMYK_PROFILE_ENV = "KDP_STUDIO_CMYK_PROFILE"  # własny profil ICC okładki z .env (FR-15)
REPO_ROOT = DEFAULT_CONFIG_DIR.parent  # ścieżki zasobów (np. czcionek) są względne wobec repo
Fraction = Annotated[float, Field(ge=0, le=1)]


class TextBox(_Strict):
    """Prostokąt względem obszaru treści strony, w ułamkach jego szerokości i wysokości."""

    x: Fraction
    y: Fraction
    width: Annotated[float, Field(gt=0, le=1)]
    height: Annotated[float, Field(gt=0, le=1)]

    @model_validator(mode="after")
    def _inside(self) -> Self:
        if self.x + self.width > 1 or self.y + self.height > 1:
            raise ValueError("text_box wychodzi poza obszar treści (x + width i y + height ≤ 1)")
        return self


class BelongsToSettings(_Strict):
    """Strona „This book belongs to…” (FR-14)."""

    # None: napis z `terms.belongs_to` rynku książki (FR-19); tekst tu ma pierwszeństwo.
    text: Annotated[str, Field(min_length=1)] | None = None
    composition: Annotated[str, Field(min_length=1)] = (
        "a decorative frame made of theme elements around a large empty blank plaque in the "
        "center of the page, the plaque is completely empty with nothing written or drawn inside it"
    )
    text_box: TextBox = TextBox(x=0.2, y=0.37, width=0.6, height=0.3)
    max_ink_ratio: Annotated[float, Field(ge=0, le=1)] = 0.005
    max_retries: Annotated[int, Field(ge=0, le=MAX_QA_RETRIES)] = 2
    font: str = "assets/fonts/Fredoka-Variable.ttf"
    font_variation: str | None = "SemiBold"  # nazwa wariantu fontu zmiennego; None: domyślny
    fallback_art_height: Annotated[float, Field(gt=0.2, lt=0.9)] = 0.55

    @property
    def font_path(self) -> Path:
        path = Path(self.font)
        return path if path.is_absolute() else REPO_ROOT / path


# --- Strony wstępne (FR-23) ----------------------------------------------------------------

FirstPage = Literal["title", "belongs-to"]
CopyrightVariant = Literal["minimal", "short", "full"]
COPYRIGHT_FIELDS = {"year": 0, "owner": ""}  # wstawki w tekście praw autorskich
INSTRUCTION_KEYS = ("heading", "intro", "section", "body")
# Zdania opisu KDP składane przez program (FR-03): fakty o książce i nagłówek korzyści.
LISTING_FIELDS: dict[str, dict[str, object]] = {
    "pages_single": {"pages": 0},
    "pages_double": {"pages": 0},
    "size": {"trim_in": "", "trim_cm": ""},
    "first_page_title": {},
    "first_page_belongs_to": {},
    "instructions": {},
    "benefits_kids": {},
    "benefits_adults": {},
}


def _repo_path(value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


class FrontMatterSettings(_Strict):
    """Strony przed kolorowankami: strona 1, prawa autorskie i instrukcja (FR-23)."""

    first_page: FirstPage = "belongs-to"  # --first-page w generate i front-matter
    instructions: bool = True  # instrukcja i pusta strona za nią: 4 strony wstępne zamiast 2
    copyright: CopyrightVariant = "short"  # --copyright
    in_generate: bool = True  # generate robi strony z modelem (front-matter) przed finalize
    text_font: str = "assets/fonts/NotoSans-Variable.ttf"  # zwykły tekst (prawa, instrukcja)
    text_font_variation: str | None = "Regular"
    text_bold_variation: str | None = "Bold"  # śródtytuł instrukcji
    copyright_pt: Annotated[float, Field(gt=0)] = 12
    copyright_min_pt: Annotated[float, Field(gt=0)] = 9

    @property
    def text_font_path(self) -> Path:
        return _repo_path(self.text_font)

    @model_validator(mode="after")
    def _sizes(self) -> Self:
        if self.copyright_min_pt > self.copyright_pt:
            raise ValueError("front_matter.copyright_min_pt nie może być większy niż copyright_pt")
        return self

    @property
    def pages(self) -> int:
        """Liczba stron wstępnych: strona 1 i prawa autorskie, z instrukcją także pusta."""
        return 4 if self.instructions else 2


class InteriorSettings(_Strict):
    """Wnętrze książki (FR-22): tryb druku i `interior.pdf`."""

    single_sided: bool = True  # --single-sided/--double-sided; D8: grafika z pustym tyłem
    pdf: bool = True  # finalize składa interior.pdf, gdy wszystkie strony są gotowe


class PublisherSettings(_Strict):
    # Właściciel praw autorskich (`{owner}` na stronie praw, FR-23); --copyright-owner nadpisuje.
    copyright_owner: Annotated[str, Field(min_length=1)] | None = None


class TitlePageSettings(_Strict):
    """Strona 1 do kolorowania z tytułem książki (FR-23, `--first-page title`)."""

    composition: Annotated[str, Field(min_length=1)] = (
        "a cheerful scene with the main characters and objects of the book in the lower two "
        "thirds of the page; the top third of the page is completely empty white space with "
        "nothing drawn in it"
    )
    text_box: TextBox = TextBox(x=0.04, y=0.0, width=0.92, height=0.3)  # pole na tytuł
    max_ink_ratio: Annotated[float, Field(ge=0, le=1)] = 0.005
    max_retries: Annotated[int, Field(ge=0, le=MAX_QA_RETRIES)] = 2
    font_variation: str | None = "Bold"  # czcionka napisów rynku (FR-19), litery konturowe
    font_pt: Annotated[float, Field(gt=0)] = 54  # największy rozmiar tytułu


class InstructionsSettings(_Strict):
    """Strona 3 z instrukcją i ilustracją z główną postacią książki (FR-23)."""

    # {subject}: główna postać książki (najczęstszy `subject` stron, jak w FR-14).
    composition: Annotated[str, Field(min_length=1)] = (
        "{subject} slips a blank sheet of thick paper behind a page of an open coloring book "
        "lying on a table, two big curved arrows show how the sheet slides under the page"
    )
    art_box: TextBox = TextBox(x=0.0, y=0.45, width=1.0, height=0.55)  # ilustracja pod tekstem
    max_retries: Annotated[int, Field(ge=0, le=MAX_QA_RETRIES)] = 2
    heading_pt: Annotated[float, Field(gt=0)] = 30
    section_pt: Annotated[float, Field(gt=0)] = 16
    body_pt: Annotated[float, Field(gt=0)] = 13
    heading_variation: str | None = "Bold"  # czcionka napisów rynku (FR-19)
    fallback_art: str = "assets/front_matter/instructions.svg"  # bez postaci, po max_retries

    @property
    def fallback_art_path(self) -> Path:
        return _repo_path(self.fallback_art)

    @model_validator(mode="after")
    def _subject_field(self) -> Self:
        try:
            self.composition.format(subject="x")
        except (KeyError, IndexError, ValueError) as e:
            raise ValueError(
                f"instructions.composition: nieznane pole {e}; dozwolone: {{subject}}"
            ) from e
        return self


class BarcodeBox(_Strict):
    """Pole kodu kreskowego KDP na tylnej okładce (FR-15)."""

    width_in: Annotated[float, Field(gt=0)] = 2.0
    height_in: Annotated[float, Field(gt=0)] = 1.2
    from_spine_in: Annotated[float, Field(ge=0)] = 0.25
    from_bottom_in: Annotated[float, Field(ge=0)] = 0.25


class KdpCover(_Strict):
    """Wartości KDP dla okładki paperback (FR-15, D10): zmienia się je tylko, gdy KDP zmieni zasady.

    Oprawa miękka, wnętrze czarno-białe i biały papier to stałe założenia, więc grubość
    papieru jest jedna.
    """

    bleed_in: Annotated[float, Field(ge=0)] = 0.125
    paper_factor_in: Annotated[float, Field(gt=0)] = 0.002252
    safe_in: Annotated[float, Field(ge=0)] = 0.125  # tekst od linii cięcia i zgięcia
    spine_safe_in: Annotated[float, Field(ge=0)] = 0.0625  # tekst grzbietu od linii zgięcia
    spine_text_kdp_min_pages: Annotated[int, Field(gt=0)] = 79
    barcode: BarcodeBox = BarcodeBox()


class TemplateColor(_Strict):
    rgb: tuple[int, int, int]
    tolerance: Annotated[int, Field(ge=0, le=255)]


class TemplateColors(_Strict):
    """Kolory szablonu z kalkulatora okładek KDP (skalibrowane na tests/fixtures/kdp_templates)."""

    live_bleed_pink: TemplateColor = TemplateColor(rgb=(255, 175, 176), tolerance=40)
    barcode_yellow: TemplateColor = TemplateColor(rgb=(255, 255, 0), tolerance=60)
    fold_blue: TemplateColor = TemplateColor(rgb=(18, 6, 220), tolerance=60)
    trim_black: TemplateColor = TemplateColor(rgb=(0, 0, 0), tolerance=80)


RenderingIntent = Literal["perceptual", "relative_colorimetric"]


class CmykSettings(_Strict):
    """Konwersja okładki do CMYK (FR-15). Domyślny profil ICC jest w assets/icc/."""

    profile: str | None = None
    rendering_intent: RenderingIntent = "perceptual"
    black_point_compensation: bool = True
    max_total_ink_pct: Annotated[int, Field(ge=100, le=400)] = 300
    gamut_warn_delta_e: Annotated[float, Field(gt=0)] = 10
    gamut_warn_area_pct: Annotated[float, Field(ge=0, le=100)] = 5

    @property
    def profile_path(self) -> Path | None:
        if self.profile is None:
            return None
        path = Path(self.profile).expanduser()
        return path if path.is_absolute() else REPO_ROOT / path


# Pola promptu tyłu (FR-15 etap 3), wypełniane przez `pipeline/cover_back.py`.
BACK_PROMPT_FIELDS = {"horizon": "", "colors": "", "spine_pct": 0, "margin_pct": 0}
DEFAULT_BACK_PROMPT = (
    "Paint the back cover and spine of the same children's coloring book as the reference "
    "image, which is its front cover. Make one wide background picture in the same style, "
    "palette and lighting, as if the world of the front cover continued to the left. "
    "{horizon} Along the right edge, where it joins the front cover, the background colors "
    "from top to bottom are: {colors}. The right {spine_pct}% of the picture is the spine: "
    "only plain background there, no objects. Keep the bottom right corner calm and plain. "
    "Keep any objects at least {margin_pct}% away from every edge and keep the middle mostly "
    "calm background, because thumbnails of inner pages will be placed on it. Use vivid but "
    "print-friendly colors (no neon, no fluorescent colors). No text, no letters, no title, "
    "no logos, no frame, no border."
)

# Pola promptu dorysowania tyłu do przodu (maska); ten sam plik.
OUTPAINT_PROMPT_FIELDS = {"area_pct": 0, "spine_pct": 0, "margin_pct": 0}
DEFAULT_OUTPAINT_PROMPT = (
    "Extend this picture to the left. The right part is the left edge of the front cover of a "
    "children's coloring book; the empty white area on the left ({area_pct}% of the width) is "
    "the back cover and spine of the same book. Fill the empty area so that the picture "
    "continues seamlessly: the same wall, floor, ground or sky, the same lines, boards and "
    "horizon at exactly the same height, the same style, palette and lighting. Do not change "
    "the right part. Do not continue characters or objects cut by the edge into the new area. "
    "The right {spine_pct}% of the new area, next to the existing part, is the spine: only "
    "plain background there, no objects. Keep the bottom right corner of the new area calm "
    "and plain. Keep any new objects at least {margin_pct}% away from the edges of the new "
    "area and keep its middle mostly calm background, because thumbnails of inner pages will "
    "be placed on it. Use vivid but print-friendly colors (no neon, no fluorescent colors). "
    "No text, no letters, no title, no logos, no frame, no border."
)


class CoverSettings(_Strict):
    """Nasze ustawienia okładki (FR-15)."""

    key_margin_in: Annotated[float, Field(ge=0)] = 0.375
    spine_text_min_pages: Annotated[int, Field(gt=0)] = 100
    thumbnails: Annotated[int, Field(ge=3, le=4)] = 3
    thumbnail_frame_ratio: Annotated[float, Field(gt=0)] = 2.0
    thumbnail_frame_min_pt: Annotated[float, Field(gt=0)] = 2
    thumbnail_check_px: Annotated[int, Field(gt=0)] = 160
    title_band: Annotated[float, Field(gt=0.1, lt=0.6)] = 0.3  # górna część przodu na tytuł
    subtitle_scale: Annotated[float, Field(gt=0, le=1)] = 0.45  # podtytuł względem tytułu
    title_font_pt: Annotated[float, Field(gt=0)] = 64
    spine_font_min_pt: Annotated[float, Field(gt=0)] = 7
    seam_band_in: Annotated[float, Field(ge=0)] = 0.1
    seam_max_delta_e: Annotated[float, Field(gt=0)] = 12
    horizon_tolerance: Annotated[float, Field(gt=0, lt=1)] = 0.03
    # Największe przesunięcie wierszy tyłu przy dopasowaniu do przodu (ułamek wysokości); 0 wyłącza.
    seam_align_max: Annotated[float, Field(ge=0, lt=0.5)] = 0.2
    max_retries: Annotated[int, Field(ge=0, le=MAX_QA_RETRIES)] = 2
    back_text: bool = False
    title_font: str = "assets/fonts/Fredoka-Variable.ttf"
    title_font_variation: str | None = "Bold"
    title_fill_rgb: tuple[int, int, int] = (255, 255, 255)
    subtitle_fill_rgb: tuple[int, int, int] = (255, 230, 120)
    title_outline_pt: Annotated[float, Field(ge=0)] = 3.0
    thumbnail_min_text_px: Annotated[float, Field(gt=0)] = 6.0
    title_min_contrast: Annotated[float, Field(ge=1, le=21)] = 3.0
    colorize: bool = True  # etap 2: model koloruje szkic przodu (--color/--no-color)
    color_prompt: Annotated[str, Field(min_length=1)] = (
        "Color this black-and-white coloring book page as the front cover of a children's "
        "coloring book. Keep every black outline exactly where it is: do not move, redraw, "
        "remove or add lines. Fill all shapes with vivid but print-friendly colors (no neon, "
        "no fluorescent colors). Fill the empty band at the top with a calm, simple background "
        "such as sky or a soft gradient that continues the scene, with no objects in it. "
        "Extend the background to all four edges of the image. No text, no letters, no title, "
        "no logos, no frame, no border."
    )
    contour_match_min: Annotated[float, Field(ge=0, le=1)] = 0.85
    contour_search_in: Annotated[float, Field(gt=0)] = 0.02
    # Pas tytułu ma zostać spokojnym tłem; więcej krawędzi (udział pikseli) to napis albo obiekt
    # z modelu, który program przykryłby swoim tytułem: ponowienie kolorowania.
    title_band_max_edges: Annotated[float, Field(gt=0, lt=1)] = 0.01
    # Etap 3: wybór stron modelem z wizją, tło tyłu i grzbietu z modelu, QA okładki.
    select_pages: bool = True  # --select-pages/--no-select-pages
    qa: bool = False  # --qa/--no-qa
    in_generate: bool = False  # generate --cover/--no-cover: okładka jako ostatni krok
    back_prompt: Annotated[str, Field(min_length=1)] = DEFAULT_BACK_PROMPT
    # Tył jako dorysowanie przodu (płótno z pasem przodu i maska); bez pasującej proporcji
    # modelu albo z `outpaint: false` tył powstaje z back_prompt (przód tylko jako referencja).
    outpaint: bool = True
    outpaint_overlap_min: Annotated[float, Field(gt=0, le=1)] = 0.2  # część szerokości przodu
    outpaint_prompt: Annotated[str, Field(min_length=1)] = DEFAULT_OUTPAINT_PROMPT
    seam_bands: Annotated[int, Field(ge=2, le=32)] = 8  # pasy poziome kontroli styku
    back_text_pt: Annotated[float, Field(gt=0)] = 16
    back_text_min_pt: Annotated[float, Field(gt=0)] = 10
    back_text_max_height: Annotated[float, Field(gt=0, lt=0.6)] = 0.3  # część strefy tyłu
    cmyk: CmykSettings = CmykSettings()
    template_colors: TemplateColors = TemplateColors()
    template_tolerance_in: Annotated[float, Field(gt=0)] = 0.01

    @property
    def title_font_path(self) -> Path:
        path = Path(self.title_font)
        return path if path.is_absolute() else REPO_ROOT / path

    @model_validator(mode="after")
    def _back_prompt_fields(self) -> Self:
        try:
            self.back_prompt.format(**BACK_PROMPT_FIELDS)
        except (KeyError, IndexError, ValueError) as e:
            names = ", ".join("{" + k + "}" for k in BACK_PROMPT_FIELDS)
            raise ValueError(f"cover.back_prompt: nieznane pole {e}; dozwolone: {names}") from e
        try:
            self.outpaint_prompt.format(**OUTPAINT_PROMPT_FIELDS)
        except (KeyError, IndexError, ValueError) as e:
            names = ", ".join("{" + k + "}" for k in OUTPAINT_PROMPT_FIELDS)
            raise ValueError(f"cover.outpaint_prompt: nieznane pole {e}; dozwolone: {names}") from e
        if self.back_text_min_pt > self.back_text_pt:
            raise ValueError("cover.back_text_min_pt nie może być większy niż back_text_pt")
        return self


# --- A+ Content (FR-24) ------------------------------------------------------------------

AplusModuleName = Literal[
    "logo", "header_fan", "header_pages", "overlay_facts", "features", "comparison"
]
APLUS_MAX_MODULES = 5  # edytor A+: najwyżej 5 modułów na stronie
APLUS_CHART_MAX_BOOKS = 6  # Comparison Chart: 2–6 produktów z własnego konta


class AplusHeaderLimits(_Strict):
    headline: Annotated[int, Field(gt=0)] = 200
    body: Annotated[int, Field(gt=0)] = 6000


class AplusColumnLimits(_Strict):
    module_headline: Annotated[int, Field(gt=0)] = 200
    headline: Annotated[int, Field(gt=0)] = 160
    body: Annotated[int, Field(gt=0)] = 1000


class AplusOverlayLimits(_Strict):
    headline: Annotated[int, Field(gt=0)] = 60
    body: Annotated[int, Field(gt=0)] = 300


class AplusLimits(_Strict):
    """Limity znaków pól modułów, odczytane w edytorze A+ (24.11.2026)."""

    header: AplusHeaderLimits = AplusHeaderLimits()
    columns: AplusColumnLimits = AplusColumnLimits()
    overlay: AplusOverlayLimits = AplusOverlayLimits()


class AplusBackground(_Strict):
    """Tło mockupów: kandydat najdalszy (ΔE) od brzegów okładek, nie bliżej niż `min_delta_e`."""

    candidates: dict[str, tuple[int, int, int]] = {
        "beż": (226, 212, 190),
        "szałwia": (200, 212, 190),
        "pudrowy róż": (232, 206, 200),
        "szaroniebieski": (200, 210, 222),
        "ciepły szary": (214, 208, 200),
    }
    min_delta_e: Annotated[float, Field(ge=0)] = 15
    percentile: Annotated[float, Field(ge=0, le=100)] = 5  # odporne na pojedyncze piksele
    border: Annotated[float, Field(gt=0, lt=0.5)] = 0.04  # pas brzegowy okładki (ułamek boku)
    darken_step: Annotated[float, Field(gt=0, lt=1)] = 0.05  # gdy żaden kandydat nie przejdzie
    gradient: Annotated[float, Field(ge=0, lt=0.5)] = 0.04  # jaśniej u góry, ciemniej na dole

    @model_validator(mode="after")
    def _candidates(self) -> Self:
        if not self.candidates:
            raise ValueError("aplus.header_fan.background.candidates: podaj co najmniej 1 kolor")
        for name, rgb in self.candidates.items():
            if any(not 0 <= v <= 255 for v in rgb):
                raise ValueError(f"aplus.header_fan.background.candidates.{name}: RGB 0–255")
        return self


class AplusShadow(_Strict):
    blur: Annotated[float, Field(ge=0)] = 0.022  # względem boku okładki
    offset: tuple[float, float] = (0.016, 0.024)  # w prawo i w dół, względem boku
    opacity: Annotated[float, Field(ge=0, le=1)] = 0.4


class AplusFan(_Strict):
    """Wachlarz okładek pod banerem (Standard Image Header With Text, 970 × 600)."""

    front_angle_deg: float = 7  # przód obrócony w lewo, na wierzchu
    back_angle_deg: float = -9  # tył obrócony w prawo, pod spodem
    back_offset: Annotated[float, Field(ge=0)] = 0.62  # przesunięcie tyłu w bokach okładki
    size: Annotated[float, Field(gt=0, le=1)] = 0.83  # bok okładki względem wysokości grafiki
    left: Annotated[float, Field(ge=0, lt=1)] = 0.04  # lewy brzeg przodu względem szerokości
    page_edge: Annotated[float, Field(gt=0, lt=0.1)] = 1 / 120  # blok kartek względem boku
    spine_shade: Annotated[float, Field(gt=0, le=1)] = 0.85  # grzbiet tyłu lekko w cieniu
    shadow: AplusShadow = AplusShadow()
    background: AplusBackground = AplusBackground()


class AplusPages(_Strict):
    """Drugi mockup (bez tabeli porównawczej): kilka stron wnętrza w wachlarzu."""

    count: Annotated[int, Field(ge=2, le=4)] = 3
    angles_deg: list[float] = [8, 0, -8]
    size: Annotated[float, Field(gt=0, le=1)] = 0.78  # wysokość strony względem grafiki


class AplusFeatures(_Strict):
    columns: Literal[3, 4] = 3  # Standard Three albo Four Images & Text
    margin: Annotated[float, Field(ge=0, lt=0.5)] = 0.06  # biały margines wokół strony w kwadracie


class AplusComparisonBook(_Strict):
    asin: Annotated[str, Field(pattern=r"^[A-Z0-9]{10}$")]
    book: str  # katalog książki (z manifest.json), względny wobec katalogu roboczego


class AplusComparison(_Strict):
    books: Annotated[list[AplusComparisonBook], Field(max_length=APLUS_CHART_MAX_BOOKS)] = []


class AplusSettings(_Strict):
    """A+ Content (FR-24): moduły, limity znaków, grafiki i teksty."""

    modules: list[AplusModuleName] = [
        "logo",
        "header_fan",
        "overlay_facts",
        "features",
        "comparison",
    ]
    logo: str | None = None  # baner 600 × 180 przygotowany poza programem
    image_format: Literal["jpg", "png"] = "jpg"
    jpeg_quality: Annotated[int, Field(ge=50, le=100)] = 90
    scale: Annotated[int, Field(ge=1, le=4)] = 2  # obrazy w wielokrotności proporcji z edytora
    max_file_mb: Annotated[float, Field(gt=0)] = 2.0  # limit A+ na plik
    color_page: bool = False  # --color-page: pokolorowana strona z modelu (płatna)
    limits: AplusLimits = AplusLimits()
    header_fan: AplusFan = AplusFan()
    header_pages: AplusPages = AplusPages()
    features: AplusFeatures = AplusFeatures()
    comparison: AplusComparison = AplusComparison()

    @property
    def logo_path(self) -> Path | None:
        return None if self.logo is None else _repo_path(self.logo)

    @model_validator(mode="after")
    def _modules(self) -> Self:
        if not self.modules:
            raise ValueError("aplus.modules: podaj co najmniej jeden moduł")
        if len(self.modules) > APLUS_MAX_MODULES:
            raise ValueError(
                f"aplus.modules: edytor A+ przyjmuje najwyżej {APLUS_MAX_MODULES} modułów "
                f"(podano {len(self.modules)})"
            )
        if len(set(self.modules)) != len(self.modules):
            raise ValueError("aplus.modules: moduł powtórzony")
        if len(self.header_pages.angles_deg) < self.header_pages.count:
            raise ValueError("aplus.header_pages.angles_deg: podaj kąt dla każdej strony")
        return self


class Settings(_Strict):
    front_matter: FrontMatterSettings = FrontMatterSettings()  # FR-23
    interior: InteriorSettings = InteriorSettings()  # FR-22
    publisher: PublisherSettings = PublisherSettings()
    title_page: TitlePageSettings = TitlePageSettings()
    instructions: InstructionsSettings = InstructionsSettings()
    reserve_ratio: Annotated[float, Field(ge=0, le=1)] = 0.2
    default_market: Annotated[str, Field(min_length=1)] = "US"  # FR-19, klucz z markets.yaml
    providers: ProviderSettings = ProviderSettings()
    models: ModelSettings = ModelSettings()
    image_quality: ImageQuality = "medium"
    concurrency: Annotated[int, Field(ge=1, le=MAX_CONCURRENCY)] = 4
    kdp_margins: KdpMargins = KdpMargins()
    review_ideas: bool = True
    diversity: DiversitySettings = DiversitySettings()
    qa: bool = False
    qa_max_retries: Annotated[int, Field(ge=0, le=MAX_QA_RETRIES)] = 2  # na pomysł
    qa_max_ideas: Annotated[int, Field(ge=1, le=MAX_QA_IDEAS)] = 2  # na stronę, z zapasowymi
    log_level: LogLevel = "info"
    belongs_to_page: BelongsToSettings = BelongsToSettings()
    kdp_cover: KdpCover = KdpCover()
    cover: CoverSettings = CoverSettings()
    aplus: AplusSettings = AplusSettings()  # FR-24
    api_pricing: ApiPricing = ApiPricing()
    max_cost_usd: Annotated[float, Field(gt=0)] = DEFAULT_MAX_COST_USD


# --- Rynki (FR-19) i dane cenowe (FR-16): config/markets.yaml ---------------------------------

Money = Annotated[Decimal, Field(ge=0)]  # kwoty z tabel KDP; FR-16 liczy na Decimal


class PrintingTrim(_Strict):
    """Koszt druku jednego rozmiaru: stały do progu stron, potem stały + strony × per_page."""

    fixed_only: Money
    fixed: Money
    per_page: Money


class PrintingCost(_Strict):
    fixed_only_max_pages: Annotated[int, Field(gt=0)]
    regular: PrintingTrim
    large: PrintingTrim


class Royalty(_Strict):
    rate_50_max_price: Money  # stawka 50% do tej ceny włącznie
    rate_60_min_price: Money  # stawka 60% od tej ceny
    max_price: Money

    @model_validator(mode="after")
    def _ordered(self) -> Self:
        if not self.rate_50_max_price < self.rate_60_min_price <= self.max_price:
            raise ValueError("royalty: wymagane rate_50_max_price < rate_60_min_price ≤ max_price")
        return self


class MarketPricing(_Strict):
    currency: Annotated[str, Field(min_length=3, max_length=3)]
    printing_cost: PrintingCost
    royalty: Royalty
    # FR-16: ceny netto do tabeli tantiem `price` (obok ceny minimalnej i progów).
    candidate_prices: list[Money] = []
    vat: bool = False  # klient płaci cenę z VAT doliczonym do ceny z KDP

    @model_validator(mode="after")
    def _candidates_in_range(self) -> Self:
        over = [str(p) for p in self.candidate_prices if p > self.royalty.max_price]
        if over:
            raise ValueError(f"candidate_prices powyżej max_price: {', '.join(over)}")
        return self


class MarketTerms(_Strict):
    """Stałe teksty rynku, które wpisuje program (FR-14, FR-15) i wskazuje modelowi (FR-03)."""

    coloring_book: Annotated[str, Field(min_length=1)]
    belongs_to: Annotated[str, Field(min_length=1)]
    ages: Annotated[str, Field(min_length=1)]  # z polami {min} i {max}
    adults: Annotated[str, Field(min_length=1)]

    @model_validator(mode="after")
    def _ages_fields(self) -> Self:
        try:
            filled = self.ages.format(min=0, max=0)
        except (KeyError, IndexError, ValueError) as e:
            raise ValueError(f"terms.ages: nieznane pole {e}; dozwolone: {{min}}, {{max}}") from e
        if filled == self.ages:
            raise ValueError("terms.ages: brak pól {min} i {max}")
        return self

    def age_phrase(self, age_range: tuple[int, int] | None) -> str:
        """Wzór wieku dla profilu, np. „for Kids Ages 3–5”; bez zakresu wieku: `adults`."""
        if age_range is None:
            return self.adults
        return self.ages.format(min=age_range[0], max=age_range[1])


class MarketProfile(_Strict):
    name: Annotated[str, Field(min_length=1)]
    domain: Annotated[str, Field(min_length=1)]
    locale: Annotated[str, Field(min_length=2)]
    language: Annotated[str, Field(min_length=1)]  # odmiana języka do promptu, po angielsku
    currency: Annotated[str, Field(min_length=3, max_length=3)] | None = None
    printing_cost: PrintingCost | None = None
    royalty: Royalty | None = None
    pricing_group: str | None = None  # wspólne tabele KDP (np. EU) zamiast własnych liczb
    candidate_prices: list[Money] | None = None  # FR-16, jak w MarketPricing
    vat: bool | None = None
    terms: MarketTerms
    # Pisownia rynku: słowo innej odmiany języka → poprawne (np. color → colour na UK).
    spelling: dict[Annotated[str, Field(min_length=1)], Annotated[str, Field(min_length=1)]] = {}
    alphabet: str = ""  # znaki języka spoza ASCII, które muszą mieć czcionki napisów
    # Czcionka napisów programu na tym rynku (strona FR-14, tytuł okładki), względna wobec repo;
    # ma pierwszeństwo przed belongs_to_page.font i cover.title_font. None: czcionki z settings.
    font: str | None = None

    @property
    def description(self) -> str:
        return f"{self.language}, {self.locale}."

    @model_validator(mode="after")
    def _pricing_source(self) -> Self:
        own = (self.currency, self.printing_cost, self.royalty)
        extra = (self.candidate_prices, self.vat)
        if self.pricing_group is not None and any(v is not None for v in own + extra):
            raise ValueError(
                "pricing_group wyklucza własne currency, printing_cost, royalty, "
                "candidate_prices i vat"
            )
        if self.pricing_group is None and any(v is None for v in own):
            raise ValueError("podaj pricing_group albo currency, printing_cost i royalty")
        return self

    def required_chars(self) -> str:
        """Znaki, które czcionki napisów muszą mieć dla tego rynku (FR-19): stałe teksty
        i alfabet języka."""
        terms = self.terms
        texts = [terms.coloring_book, terms.belongs_to, terms.age_phrase((0, 0)), terms.adults]
        return "".join(sorted(set("".join(texts) + self.alphabet) - set(" 0123456789")))


class LargeTrim(_Strict):
    width_over_in: Annotated[float, Field(gt=0)]
    height_over_in: Annotated[float, Field(gt=0)]


class FrontTexts(_Strict):
    """Teksty stron wstępnych w jednym języku (FR-23), po scaleniu odmiany z językiem."""

    language: str  # klucz z `texts`, z którego pochodzą (np. en-GB albo en)
    copyright: dict[str, str]  # minimal, short, full
    instructions: dict[str, str]  # heading, intro, section, body
    listing: dict[str, str] = {}  # zdania opisu KDP (FR-03), klucze LISTING_FIELDS


def _merge_texts(
    base: dict[str, dict[str, str]], over: dict[str, dict[str, str]]
) -> dict[str, dict[str, str]]:
    merged = {section: dict(values) for section, values in base.items()}
    for section, values in over.items():
        merged.setdefault(section, {}).update(values)
    return merged


class AplusOccasion(_Strict):
    """Święto jako termin albo okazja do zakupu: `phrases` zawsze, `holidays` tylko w pobliżu
    słowa z `context` (termin, zakup, prezent). Samo święto jako temat przechodzi."""

    phrases: list[str] = []
    holidays: list[str] = []
    context: list[str] = []
    window: Annotated[int, Field(ge=1, le=10)] = 3  # słów między świętem a kontekstem


class AplusBanned(_Strict):
    """Zakazane sformułowania A+ (FR-24) w jednym języku."""

    time: list[str] = []  # nacisk czasem: now, new, latest…
    occasion: AplusOccasion = AplusOccasion()
    claims: list[str] = []  # przechwałki: best, perfect, #1…
    sales: list[str] = []  # ceny, rabaty, wezwania do zakupu


APLUS_CHART_ROWS = ("age", "pages", "size")


class AplusTexts(_Strict):
    """Teksty A+ w jednym języku: zakazane sformułowania i etykiety wierszy tabeli."""

    banned: AplusBanned = AplusBanned()
    chart: dict[str, str] = {}  # etykiety wierszy Comparison Chart: APLUS_CHART_ROWS

    @model_validator(mode="after")
    def _chart(self) -> Self:
        missing = [k for k in APLUS_CHART_ROWS if not self.chart.get(k, "").strip()]
        if missing:
            raise ValueError(f"chart: brak {', '.join(missing)}")
        extra = set(self.chart) - set(APLUS_CHART_ROWS)
        if extra:
            raise ValueError(f"chart: nieznane klucze {', '.join(sorted(extra))}")
        return self


class MarketsConfig(_Strict):
    sources: dict[str, str]
    checked: date
    # FR-16: starsze dane cenowe dają ostrzeżenie z linkami do stron KDP w `sources`.
    stale_after_days: Annotated[int, Field(gt=0)] = 180
    large_trim: LargeTrim
    pricing_groups: dict[str, MarketPricing] = {}
    markets: dict[str, MarketProfile]
    # FR-23: teksty stron wstępnych według języka (`en`) albo odmiany (`en-GB`, tylko różnice).
    texts: dict[str, dict[str, dict[str, str]]] = {}
    # FR-24: zakazane sformułowania A+ i etykiety tabeli według języka (`en`) albo odmiany.
    aplus_texts: dict[str, AplusTexts] = {}

    def aplus_for(self, locale: str) -> AplusTexts | None:
        """Teksty A+ dla `locale`: odmiana, a bez niej język; None, gdy brak obu."""
        return self.aplus_texts.get(locale) or self.aplus_texts.get(locale.split("-")[0])

    def texts_for(self, locale: str) -> FrontTexts | None:
        """Teksty dla `locale` rynku: odmiana scalona z językiem, sam język albo None."""
        language = locale.split("-")[0]
        if locale in self.texts:
            data = _merge_texts(self.texts.get(language, {}), self.texts[locale])
            key = locale
        elif language in self.texts:
            data, key = self.texts[language], language
        else:
            return None
        return FrontTexts(
            language=key,
            copyright=data.get("copyright", {}),
            instructions=data.get("instructions", {}),
            listing=data.get("listing", {}),
        )

    @model_validator(mode="after")
    def _texts_complete(self) -> Self:
        variants = set(get_args(CopyrightVariant))
        for key in self.texts:
            texts = self.texts_for(key)
            assert texts is not None
            where = f"texts.{key}"
            if set(texts.copyright) != variants:
                raise ValueError(
                    f"{where}.copyright: wymagane warianty {', '.join(sorted(variants))} "
                    f"(są: {', '.join(sorted(texts.copyright)) or '-'})"
                )
            for variant, text in texts.copyright.items():
                try:
                    text.format(**COPYRIGHT_FIELDS)
                except (KeyError, IndexError, ValueError) as e:
                    raise ValueError(
                        f"{where}.copyright.{variant}: nieznane pole {e}; dozwolone: "
                        "{year}, {owner}"
                    ) from e
            missing = [k for k in INSTRUCTION_KEYS if not texts.instructions.get(k, "").strip()]
            if missing:
                raise ValueError(f"{where}.instructions: brak {', '.join(missing)}")
            extra = set(texts.instructions) - set(INSTRUCTION_KEYS)
            if extra:
                unknown = ", ".join(sorted(extra))
                raise ValueError(f"{where}.instructions: nieznane klucze {unknown}")
            for name, text in texts.instructions.items():
                if "{" in text or "}" in text:
                    raise ValueError(f"{where}.instructions.{name}: tekst nie ma wstawek {{…}}")
            missing = [k for k in LISTING_FIELDS if not texts.listing.get(k, "").strip()]
            if missing:
                raise ValueError(f"{where}.listing: brak {', '.join(missing)}")
            extra = set(texts.listing) - set(LISTING_FIELDS)
            if extra:
                raise ValueError(f"{where}.listing: nieznane klucze {', '.join(sorted(extra))}")
            for name, text in texts.listing.items():
                fields = LISTING_FIELDS[name]
                try:
                    text.format(**fields)
                except (KeyError, IndexError, ValueError) as e:
                    allowed = ", ".join("{" + f + "}" for f in fields) or "brak wstawek"
                    raise ValueError(
                        f"{where}.listing.{name}: nieznane pole {e}; dozwolone: {allowed}"
                    ) from e
        return self

    @model_validator(mode="after")
    def _groups_exist(self) -> Self:
        if not self.markets:
            raise ValueError("brak rynków w markets.yaml")
        for key, market in self.markets.items():
            if market.pricing_group is not None and market.pricing_group not in self.pricing_groups:
                raise ValueError(
                    f"rynek '{key}': nieznana pricing_group '{market.pricing_group}' "
                    f"(dostępne: {', '.join(self.pricing_groups) or '-'})"
                )
        return self

    def pricing(self, key: str) -> MarketPricing:
        """Dane cenowe FR-16 rynku: własne albo z jego grupy."""
        market = self.markets[key]
        if market.pricing_group is not None:
            return self.pricing_groups[market.pricing_group]
        assert market.currency and market.printing_cost and market.royalty
        return MarketPricing(
            currency=market.currency,
            printing_cost=market.printing_cost,
            royalty=market.royalty,
            candidate_prices=market.candidate_prices or [],
            vat=bool(market.vat),
        )


class AppConfig(_Strict):
    ages: dict[str, AgeProfile]
    styles: dict[str, StyleProfile]
    formats: dict[str, FormatProfile]
    settings: Settings
    markets: MarketsConfig

    @model_validator(mode="after")
    def _references_exist(self) -> Self:
        for kind, profiles in (
            ("ages", self.ages),
            ("styles", self.styles),
            ("formats", self.formats),
        ):
            if not profiles:
                raise ValueError(f"brak profili w {kind}.yaml")
        outside_min = self.settings.kdp_margins.outside_min_in
        for key, fmt in self.formats.items():
            if fmt.safe_margin_in < outside_min:
                raise ValueError(
                    f"format '{key}': safe_margin_in {fmt.safe_margin_in} < "
                    f"kdp_margins.outside_min_in {outside_min}"
                )
        for key, style in self.styles.items():
            unknown = [a for a in style.allowed_ages or [] if a not in self.ages]
            if unknown:
                raise ValueError(f"styl '{key}': allowed_ages zawiera nieznany wiek {unknown}")
        if self.settings.default_market not in self.markets.markets:
            raise ValueError(
                f"default_market '{self.settings.default_market}' nie ma w markets.yaml "
                f"(dostępne: {', '.join(self.markets.markets)})"
            )
        return self

    def belongs_to_text(self, market: str) -> str:
        """Napis strony FR-14: ręczny z settings.yaml albo z `terms` rynku książki (FR-19)."""
        text = self.settings.belongs_to_page.text
        return text if text is not None else self.markets.markets[market].terms.belongs_to

    def belongs_to_settings(self, market: str) -> BelongsToSettings:
        """Ustawienia strony FR-14 z napisem i czcionką ustalonymi dla rynku książki."""
        return self.for_market(market).settings.belongs_to_page

    def for_market(self, market: str) -> AppConfig:
        """Konfiguracja dla książki na danym rynku (FR-19): napis strony FR-14 z `terms`
        i czcionka rynku (`font`) zamiast czcionek strony FR-14 i tytułu okładki."""
        profile = self.markets.markets[market]
        page_update: dict[str, Any] = {"text": self.belongs_to_text(market)}
        cover_update: dict[str, Any] = {}
        if profile.font is not None:
            page_update["font"] = profile.font
            cover_update["title_font"] = profile.font
        settings = self.settings.model_copy(
            update={
                "belongs_to_page": self.settings.belongs_to_page.model_copy(update=page_update),
                "cover": self.settings.cover.model_copy(update=cover_update),
            }
        )
        return self.model_copy(update={"settings": settings})


def resolve_config_dir(config_dir: Path | None = None) -> Path:
    if config_dir is not None:
        return config_dir
    env = os.environ.get(CONFIG_DIR_ENV)
    return Path(env) if env else DEFAULT_CONFIG_DIR


def _read_yaml(path: Path) -> Any:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise ConfigError(f"brak pliku konfiguracji: {path}") from None
    except OSError as e:
        raise ConfigError(f"nie można odczytać {path}: {e}") from e
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as e:
        raise ConfigError(f"niepoprawny YAML w {path}: {e}") from e
    return {} if data is None else data


def load_config(config_dir: Path | None = None) -> AppConfig:
    """Wczytuje ages/styles/formats/settings/markets.yaml i waliduje ich schemat."""
    directory = resolve_config_dir(config_dir)
    raw = {
        name: _read_yaml(directory / f"{name}.yaml")
        for name in ("ages", "styles", "formats", "settings", "markets")
    }
    try:
        return AppConfig.model_validate(raw)
    except ValidationError as e:
        details = "\n".join(
            f"  {'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in e.errors()
        )
        raise ConfigError(f"niepoprawna konfiguracja w {directory}:\n{details}") from e
