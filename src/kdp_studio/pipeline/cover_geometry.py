"""FR-15, D10: geometria okładki paperback liczona wzorami KDP i kontrola szablonu KDP.

Wymiary nie pochodzą z modelu ani z OCR: pomyłka w jednej cyfrze odrzuca plik w KDP,
a wzór jest jednoznaczny. Szablon z kalkulatora KDP (opcjonalny) program czyta tylko po
kolorach pikseli i porównuje z wyliczeniami.

Współrzędne: cale od lewego górnego rogu całej okładki ze spadem; prostokąty to
(left, top, right, bottom).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from kdp_studio.config import KdpCover, TemplateColor, TemplateColors

RectIn = tuple[float, float, float, float]
RectPx = tuple[int, int, int, int]


@dataclass(frozen=True)
class CoverGeometry:
    trim_in: tuple[float, float]  # format książki (szerokość, wysokość)
    pages_in_book: int
    kdp: KdpCover
    key_margin_in: float
    dpi: int = 300

    @property
    def bleed(self) -> float:
        return self.kdp.bleed_in

    @property
    def spine_in(self) -> float:
        return self.pages_in_book * self.kdp.paper_factor_in

    @property
    def size_in(self) -> tuple[float, float]:
        width, height = self.trim_in
        return 2 * self.bleed + 2 * width + self.spine_in, height + 2 * self.bleed

    @property
    def size_px(self) -> tuple[int, int]:
        width, height = self.size_in
        return round(width * self.dpi), round(height * self.dpi)

    @property
    def trim_box(self) -> RectIn:
        width, height = self.size_in
        return self.bleed, self.bleed, width - self.bleed, height - self.bleed

    @property
    def folds_x(self) -> tuple[float, float]:
        back_fold = self.bleed + self.trim_in[0]
        return back_fold, back_fold + self.spine_in

    # --- Panele (ze spadem) ---

    @property
    def back_panel(self) -> RectIn:
        return 0.0, 0.0, self.folds_x[0], self.size_in[1]

    @property
    def spine_panel(self) -> RectIn:
        x1, x2 = self.folds_x
        return x1, 0.0, x2, self.size_in[1]

    @property
    def front_panel(self) -> RectIn:
        width, height = self.size_in
        return self.folds_x[1], 0.0, width, height

    # --- Strefy ---

    def _inset(self, margin: float) -> tuple[RectIn, RectIn]:
        """(tył, przód): strefa `margin` od linii cięcia i od linii zgięcia."""
        left, top, right, bottom = self.trim_box
        x1, x2 = self.folds_x
        back = (left + margin, top + margin, x1 - margin, bottom - margin)
        front = (x2 + margin, top + margin, right - margin, bottom - margin)
        return back, front

    @property
    def live_back(self) -> RectIn:
        return self._inset(self.kdp.safe_in)[0]

    @property
    def live_front(self) -> RectIn:
        return self._inset(self.kdp.safe_in)[1]

    @property
    def live_spine(self) -> RectIn:
        """Tekst grzbietu: `spine_safe_in` od zgięć, `safe_in` od cięcia u góry i dołu.

        Przy grzbiecie węższym niż 2 × `spine_safe_in` strefa ma zerową szerokość.
        """
        x1, x2 = self.folds_x
        _, top, _, bottom = self.trim_box
        safe = self.kdp.spine_safe_in
        left, right = x1 + safe, x2 - safe
        if left > right:  # cienki grzbiet: strefy na tekst nie ma
            left = right = (x1 + x2) / 2
        return left, top + self.kdp.safe_in, right, bottom - self.kdp.safe_in

    @property
    def key_back(self) -> RectIn:
        return self._inset(self.key_margin_in)[0]

    @property
    def key_front(self) -> RectIn:
        return self._inset(self.key_margin_in)[1]

    @property
    def barcode(self) -> RectIn:
        box = self.kdp.barcode
        right = self.folds_x[0] - box.from_spine_in
        bottom = self.trim_box[3] - box.from_bottom_in
        return right - box.width_in, bottom - box.height_in, right, bottom

    def px(self, rect: RectIn) -> RectPx:
        left, top, right, bottom = rect
        return (
            round(left * self.dpi),
            round(top * self.dpi),
            round(right * self.dpi),
            round(bottom * self.dpi),
        )

    def summary(self) -> dict[str, object]:
        """Geometria do manifestu (cale, zaokrąglone do 0.000001")."""

        def r(values: tuple[float, ...]) -> list[float]:
            return [round(v, 6) for v in values]

        return {
            "pages_in_book": self.pages_in_book,
            "trim_in": r(self.trim_in),
            "spine_in": round(self.spine_in, 6),
            "cover_in": r(self.size_in),
            "cover_px": list(self.size_px),
            "dpi": self.dpi,
            "bleed_in": self.bleed,
            "folds_x_in": r(self.folds_x),
            "trim_box_in": r(self.trim_box),
            "barcode_in": r(self.barcode),
        }


# --- Szablon KDP ---------------------------------------------------------------------------

TEMPLATE_NAME = re.compile(
    r"^(?P<binding>[A-Z]+)_(?P<width>\d+(?:\.\d+)?)x(?P<height>\d+(?:\.\d+)?)_"
    r"(?P<pages>\d+)_(?P<ink>[A-Z]+)_(?P<paper>[A-Z]+)(?:_|\.|$)"
)


def check_template_name(path: Path, geometry: CoverGeometry) -> list[str]:
    """Parametry zapisane w nazwie pliku KDP porównane z książką; nazwa spoza wzoru nic nie mówi."""
    match = TEMPLATE_NAME.match(path.name)
    if match is None:
        return []
    problems = []
    expected = {"binding": "PAPERBACK", "ink": "BW", "paper": "WHITE"}
    for key, value in expected.items():
        if match[key] != value:
            problems.append(f"szablon {key} = {match[key]}, a okładki są zawsze {value}")
    width, height = float(match["width"]), float(match["height"])
    if abs(width - geometry.trim_in[0]) > 0.001 or abs(height - geometry.trim_in[1]) > 0.001:
        problems.append(
            f'szablon dla formatu {width:g}" × {height:g}", a książka ma '
            f'{geometry.trim_in[0]:g}" × {geometry.trim_in[1]:g}"'
        )
    if int(match["pages"]) != geometry.pages_in_book:
        problems.append(
            f"szablon dla {match['pages']} stron, a książka ma {geometry.pages_in_book}"
        )
    return problems


@dataclass(frozen=True)
class TemplateMeasure:
    """Położenie linii, stref i pola kodu zmierzone na szablonie, w calach."""

    px_per_in: float
    folds_x: list[float]
    trim_x: list[float]
    trim_y: list[float]
    live_x: list[float]  # granice białych stref w wierszu przez środek okładki
    live_y: list[float]  # górna i dolna granica strefy w kolumnie przez środek przodu
    barcode: RectIn | None


def _mask(pixels: np.ndarray, color: TemplateColor) -> np.ndarray:
    """Piksele, których każdy kanał różni się od wzorca najwyżej o `tolerance`."""
    rgb = np.array(color.rgb, dtype=np.int16)
    lower = np.clip(rgb - color.tolerance, 0, 255).astype(np.uint8)
    upper = np.clip(rgb + color.tolerance, 0, 255).astype(np.uint8)
    return np.asarray(cv2.inRange(pixels, lower, upper) > 0)


def _line_centers(counts: np.ndarray, minimum: float) -> list[float]:
    """Środki grup sąsiednich kolumn (albo wierszy), w których jest dużo pikseli koloru."""
    hits = np.flatnonzero(counts >= minimum)
    centers: list[float] = []
    if hits.size == 0:
        return centers
    start = prev = int(hits[0])
    for index in [*hits[1:].tolist(), None]:
        if index is not None and index == prev + 1:
            prev = index
            continue
        centers.append((start + prev) / 2 + 0.5)
        if index is not None:
            start = prev = index
    return centers


def _runs(flags: np.ndarray, min_len: int) -> list[tuple[int, int]]:
    """Ciągi True o długości ≥ `min_len` jako (początek, koniec wyłącznie)."""
    padded = np.concatenate(([False], flags, [False])).astype(np.int8)
    edges = np.flatnonzero(np.diff(padded))
    return [
        (int(a), int(b)) for a, b in zip(edges[::2], edges[1::2], strict=True) if b - a >= min_len
    ]


def measure_template(
    path: Path, geometry: CoverGeometry, colors: TemplateColors
) -> TemplateMeasure:
    """Odczyt szablonu po kolorach pikseli (PNG albo JPEG z artefaktami kompresji)."""
    with Image.open(path) as img:
        pixels = np.asarray(img.convert("RGB"))
    height, width = pixels.shape[:2]
    ppi = width / geometry.size_in[0]

    blue = _mask(pixels, colors.fold_blue)
    folds = _line_centers(blue.sum(axis=0), 0.3 * height)
    black = _mask(pixels, colors.trim_black)
    trim_x = _line_centers(black.sum(axis=0), 0.4 * height)
    trim_y = _line_centers(black.sum(axis=1), 0.4 * width)

    pink = _mask(pixels, colors.live_bleed_pink)
    min_run = max(2, round(0.05 * ppi))
    mid_row = pink[height // 2]
    live_x = [edge for run in _runs(~mid_row, min_run) for edge in run]
    front_col = round((geometry.front_panel[0] + geometry.front_panel[2]) / 2 * ppi)
    live_y = [edge for run in _runs(~pink[:, min(front_col, width - 1)], min_run) for edge in run]

    yellow = _mask(pixels, colors.barcode_yellow).astype(np.uint8)
    count, _labels, stats, _ = cv2.connectedComponentsWithStats(yellow, connectivity=8)
    barcode = None
    if count > 1:
        biggest = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
        x, y, w, h = (int(stats[biggest, k]) for k in range(4))
        barcode = (x / ppi, y / ppi, (x + w) / ppi, (y + h) / ppi)

    def inches(values: list[float] | list[int]) -> list[float]:
        return [v / ppi for v in values]

    return TemplateMeasure(
        px_per_in=ppi,
        folds_x=inches(folds),
        trim_x=inches(trim_x),
        trim_y=inches(trim_y),
        live_x=inches(live_x),
        live_y=inches(live_y),
        barcode=barcode,
    )


def compare_template(
    measure: TemplateMeasure, geometry: CoverGeometry, tolerance_in: float
) -> list[str]:
    """Różnice między szablonem a wyliczoną geometrią (pusta lista: zgodne)."""
    problems: list[str] = []

    def check(name: str, measured: list[float], expected: list[float]) -> None:
        if len(measured) != len(expected):
            problems.append(
                f"{name}: na szablonie {len(measured)} zamiast {len(expected)} "
                f"({', '.join(f'{v:.3f}' for v in measured) or 'brak'})"
            )
            return
        for got, want in zip(measured, expected, strict=True):
            if abs(got - want) > tolerance_in:
                problems.append(f'{name}: {got:.3f}" na szablonie, wyliczone {want:.3f}"')

    left, top, right, bottom = geometry.trim_box
    back, front, spine = geometry.live_back, geometry.live_front, geometry.live_spine
    check("linie zgięcia", measure.folds_x, list(geometry.folds_x))
    check("linie cięcia (pion)", measure.trim_x, [left, right])
    check("linie cięcia (poziom)", measure.trim_y, [top, bottom])
    check(
        "strefy bezpieczne (poziomo)",
        measure.live_x,
        [back[0], back[2], spine[0], spine[2], front[0], front[2]],
    )
    check("strefa bezpieczna przodu (pionowo)", measure.live_y, [front[1], front[3]])
    if measure.barcode is None:
        problems.append("pole kodu kreskowego: brak żółtego prostokąta na szablonie")
    else:
        check("pole kodu kreskowego", list(measure.barcode), list(geometry.barcode))
    return problems
