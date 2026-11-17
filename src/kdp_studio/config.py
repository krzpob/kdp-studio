"""Ładowanie i walidacja konfiguracji z katalogu `config/` (spec §7, §9.2)."""

from __future__ import annotations

import os
from itertools import pairwise
from pathlib import Path
from typing import Annotated, Any, Literal, Self

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
    belongs_to: BelongsToAge = BelongsToAge()
    postprocess: PostprocessParams


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

    enabled: bool = False
    text: Annotated[str, Field(min_length=1)] = "This book belongs to:"
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
    """Konwersja okładki do CMYK (FR-15). Profil ICC pobiera użytkownik (licencja profilu)."""

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


class Settings(_Strict):
    front_matter_pages: Annotated[int, Field(ge=0)] = 2
    reserve_ratio: Annotated[float, Field(ge=0, le=1)] = 0.2
    metadata_language: Annotated[str, Field(min_length=1)] = "English"
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
    api_pricing: ApiPricing = ApiPricing()
    max_cost_usd: Annotated[float, Field(gt=0)] = DEFAULT_MAX_COST_USD


class AppConfig(_Strict):
    ages: dict[str, AgeProfile]
    styles: dict[str, StyleProfile]
    formats: dict[str, FormatProfile]
    settings: Settings

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
        return self


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
    """Wczytuje ages/styles/formats/settings.yaml i waliduje ich schemat."""
    directory = resolve_config_dir(config_dir)
    raw = {
        name: _read_yaml(directory / f"{name}.yaml")
        for name in ("ages", "styles", "formats", "settings")
    }
    try:
        return AppConfig.model_validate(raw)
    except ValidationError as e:
        details = "\n".join(
            f"  {'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in e.errors()
        )
        raise ConfigError(f"niepoprawna konfiguracja w {directory}:\n{details}") from e
