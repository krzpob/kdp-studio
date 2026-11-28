"""FR-24: dane A+ Content wspólne dla tekstów, podglądu i manifestu (bez zależności od nich)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# Moduły edytora A+ (nazwy jak w edytorze, sprawdzone 24.11.2026) dla nazw z `aplus.modules`.
EDITOR_MODULES: dict[str, str] = {
    "logo": "Standard Company Logo",
    "header_fan": "Standard Image Header With Text",
    "header_pages": "Standard Image Header With Text",
    "overlay_facts": "Standard Image with Dark/Light Overlay",
    "features": "Standard Three Images & Text",
    "comparison": "Standard Comparison Chart",
}
FOUR_COLUMNS = "Standard Four Images & Text"


class _Copy(BaseModel):
    model_config = ConfigDict(extra="forbid")


class HeaderCopy(_Copy):
    """Standard Image Header With Text: nagłówek nad obrazem, nagłówek i tekst pod nim."""

    headline: str = ""
    subheadline: str = ""
    body: str = ""


class OverlayCopy(_Copy):
    """Nakładka: nagłówek i fakty z manifestu jako lista numerowana (wiersz = punkt)."""

    headline: str = ""
    items: list[str] = []


class ColumnCopy(_Copy):
    headline: str = ""
    body: str = ""


class FeaturesCopy(_Copy):
    headline: str = ""
    columns: list[ColumnCopy] = []


class AplusCopy(_Copy):
    """Teksty pól modułów, zapisywane w `aplus/texts.yaml`; ręczne poprawki zostają."""

    header_fan: HeaderCopy | None = None
    header_pages: HeaderCopy | None = None
    overlay_facts: OverlayCopy | None = None
    features: FeaturesCopy | None = None
    # Tekst alternatywny grafik według `alt_key()`: header_fan, features_2, chart_1…
    alt: dict[str, str] = {}


def alt_key(module: str, index: int = 1) -> str:
    """Klucz tekstu alternatywnego grafiki: nazwa modułu, a dla kolumn i tabeli z numerem."""
    if module == "features":
        return f"features_{index}"
    if module == "comparison":
        return f"chart_{index}"
    return module


class ChartColumn(_Copy):
    """Kolumna tabeli porównawczej: książka z własnego konta KDP i jej cechy z manifestu."""

    asin: str | None = None  # None: ta książka, jeszcze bez ASIN
    book: str
    title: str
    rows: dict[str, str]  # etykieta wiersza (język rynku) → wartość


class AplusFileInfo(_Copy):
    path: str  # względem katalogu książki
    width: int
    height: int
    bytes: int


class AplusModuleInfo(_Copy):
    name: str  # klucz z `aplus.modules`
    editor: str  # nazwa modułu w edytorze A+
    files: list[AplusFileInfo] = []
    pages: list[str] = []  # strony książki użyte w grafice
    skipped: str | None = None  # dlaczego moduł wypadł (np. brak banera)


class AplusBackgroundInfo(_Copy):
    name: str
    rgb: tuple[int, int, int]
    delta_e: float
    darkened_steps: int = 0
    scores: dict[str, float] = {}


class AplusColorPage(_Copy):
    """Pokolorowana strona z modelu obrazu (`--color-page`)."""

    page: str
    prompt: str
    raw: str  # aplus/raw/<strona>_color.png
    page_sha256: str  # z jakiej strony powstała
    model: str
    quality: str


class AplusFeatureImage(_Copy):
    """Grafika kolumny z modelu obrazu (motyw z profilu wieku, `aplus.features.source`)."""

    column: int  # od 1
    theme: str  # klucz motywu z aplus_features
    page: str  # strona książki w referencji
    prompt: str
    raw: str  # aplus/raw/features_<kolumna>.png
    inputs_sha256: str  # prompt, strona, model, jakość: inny = nowa grafika
    model: str
    quality: str


class AplusInfo(_Copy):
    """Wpis `aplus` w manifeście (FR-24)."""

    status: Literal["ok", "partial", "failed"] = "ok"
    created_at: str
    modules: list[AplusModuleInfo]
    background: AplusBackgroundInfo | None = None
    texts_file: str = "aplus/texts.yaml"
    texts: AplusCopy = Field(default_factory=AplusCopy)
    texts_sha256: str | None = None  # pliku zapisanego przez program: inny = poprawiony ręcznie
    texts_inputs_sha256: str | None = None  # metadanych i faktów: inny = nowe teksty
    texts_edited: bool = False
    images_sha256: str | None = None  # okładki, stron i ustawień: inny = nowe grafiki
    chart: list[ChartColumn] = []
    color_page: AplusColorPage | None = None
    feature_images: list[AplusFeatureImage] = []
    preview: str = "aplus.html"
    warnings: list[str] = []
    cost_usd: float = 0.0
    error: str | None = None
