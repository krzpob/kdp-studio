"""FR-06: obróbka surowej grafiki do pełnej strony PNG gotowej do importu w Canvie.

Łańcuch `PostProcessor`ów: skala szarości → progowanie (Otsu albo stały próg) →
usunięcie plamek → wektoryzacja potrace (archiwum `svg/page_XX.svg`) i render na
pełną stronę `page_px` z symetrycznym marginesem → ponowne progowanie po
antyaliasingu. Zapis: 8-bit grayscale bez alfy, tylko 0 i 255, 300 DPI (NFR-07).
"""

from __future__ import annotations

import io
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import cv2
import numpy as np
import potrace
import resvg_py
from PIL import Image

from kdp_studio.config import FormatProfile, KdpMargins, PostprocessParams
from kdp_studio.pipeline.output import SVG_DIR, write_bytes_atomic

BLACK = 0
WHITE = 255
RETHRESHOLD = 128  # po renderze: piksel ciemniejszy niż połowa szarości staje się czarny


class PostprocessError(Exception):
    """Obróbka strony się nie udała albo wynik nie spełnia NFR-07. Dotyczy jednej strony."""


# --- Geometria strony ----------------------------------------------------------------


def page_margin_in(fmt: FormatProfile, margins: KdpMargins, pages_in_book: int) -> float:
    """`max(safe_margin_in, outside_min_in, gutter_in(pages_in_book))`, raz na książkę (FR-06)."""
    gutter = margins.gutter_in(pages_in_book)
    if gutter is None:
        raise ValueError(
            f"{pages_in_book} stron przekracza tabelę marginesów KDP ({margins.max_pages})"
        )
    return max(fmt.safe_margin_in, margins.outside_min_in, gutter)


@dataclass(frozen=True)
class PageGeometry:
    """Pełna strona `page_px` i obszar treści pomniejszony o margines z każdej strony."""

    page_px: tuple[int, int]
    dpi: int
    margin_in: float

    @classmethod
    def for_format(cls, fmt: FormatProfile, margin_in: float) -> PageGeometry:
        return cls(page_px=fmt.page_px, dpi=fmt.dpi, margin_in=margin_in)

    @property
    def margin_px(self) -> int:
        return round(self.margin_in * self.dpi)

    @property
    def content_box(self) -> tuple[int, int, int, int]:
        """(left, top, right, bottom) w pikselach; right/bottom wyłącznie."""
        width, height = self.page_px
        m = self.margin_px
        return m, m, width - m, height - m

    def fit(self, width: float, height: float) -> tuple[float, float, float]:
        """Skala i przesunięcie, które wpasowują grafikę w obszar treści i ją centrują."""
        left, top, right, bottom = self.content_box
        box_w, box_h = right - left, bottom - top
        scale = min(box_w / width, box_h / height)
        return scale, left + (box_w - width * scale) / 2, top + (box_h - height * scale) / 2


@dataclass(frozen=True)
class PageContext:
    geometry: PageGeometry
    params: PostprocessParams
    svg_path: Path


class PostProcessor(Protocol):
    def process(self, img: Image.Image, ctx: PageContext) -> Image.Image: ...


# --- Kroki ---------------------------------------------------------------------------


def _on_white(img: Image.Image) -> Image.Image:
    """Spłaszcza przezroczystość na białe tło (KDP wymaga spłaszczenia)."""
    if img.mode in ("RGBA", "LA", "PA") or "transparency" in img.info:
        rgba = img.convert("RGBA")
        background = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
        return Image.alpha_composite(background, rgba)
    return img


class Grayscale:
    def process(self, img: Image.Image, ctx: PageContext) -> Image.Image:
        return _on_white(img).convert("L")


class Threshold:
    """Krok pośredni przed wektoryzacją: Otsu albo stały próg z profilu wieku."""

    def process(self, img: Image.Image, ctx: PageContext) -> Image.Image:
        pixels = np.asarray(img, dtype=np.uint8)
        threshold = ctx.params.threshold
        if threshold == "otsu":
            _, bw = cv2.threshold(pixels, 0, WHITE, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        else:
            bw = np.where(pixels > threshold, WHITE, BLACK).astype(np.uint8)
        return Image.fromarray(bw, mode="L")


class Despeckle:
    """Usuwa czarne plamki o powierzchni mniejszej niż `min_speck_area` pikseli."""

    def process(self, img: Image.Image, ctx: PageContext) -> Image.Image:
        min_area = ctx.params.min_speck_area
        if min_area <= 1:
            return img
        black = (np.asarray(img) == BLACK).astype(np.uint8)
        _count, labels, stats, _ = cv2.connectedComponentsWithStats(black, connectivity=8)
        small = np.flatnonzero(stats[:, cv2.CC_STAT_AREA] < min_area)
        small = small[small != 0]  # etykieta 0 to tło
        if small.size == 0:
            return img
        cleaned = np.asarray(img).copy()
        cleaned[np.isin(labels, small)] = WHITE
        return Image.fromarray(cleaned, mode="L")


class VectorizeAndRender:
    """Wektoryzacja potrace → `svg/page_XX.svg` (archiwum) → render na pełną stronę."""

    def process(self, img: Image.Image, ctx: PageContext) -> Image.Image:
        width, height = img.size
        white = np.asarray(img) != BLACK  # potracer śledzi piksele False po odwróceniu
        params = ctx.params.potrace
        curves = potrace.Bitmap(white).trace(
            turdsize=params.turdsize,
            alphamax=params.alphamax,
            opttolerance=params.opttolerance,
        )
        data = path_data(curves)
        if not data:
            raise PostprocessError("grafika jest pusta po progowaniu (brak konturów)")

        write_bytes_atomic(ctx.svg_path, archive_svg(data, width, height).encode("utf-8"))

        geometry = ctx.geometry
        scale, dx, dy = geometry.fit(width, height)
        png = resvg_py.svg_to_bytes(svg_string=page_svg(data, geometry, scale, dx, dy))
        return _on_white(Image.open(io.BytesIO(bytes(png)))).convert("L")


class Rethreshold:
    """Usuwa szarości z antyaliasingu: zostają tylko wartości 0 i 255."""

    def process(self, img: Image.Image, ctx: PageContext) -> Image.Image:
        return img.point(lambda v: BLACK if v < RETHRESHOLD else WHITE, mode="L")


DEFAULT_CHAIN: tuple[PostProcessor, ...] = (
    Grayscale(),
    Threshold(),
    Despeckle(),
    VectorizeAndRender(),
    Rethreshold(),
)


# --- SVG -----------------------------------------------------------------------------


def path_data(curves: Sequence[potrace.Curve]) -> str:
    """Atrybut `d` jednej ścieżki ze wszystkimi konturami (dziury przez evenodd)."""
    parts: list[str] = []
    for curve in curves:
        start = curve.start_point
        parts.append(f"M{start.x:.2f},{start.y:.2f}")
        for seg in curve.segments:
            end = seg.end_point
            if seg.is_corner:
                parts.append(f"L{seg.c.x:.2f},{seg.c.y:.2f}L{end.x:.2f},{end.y:.2f}")
            else:
                parts.append(
                    f"C{seg.c1.x:.2f},{seg.c1.y:.2f} {seg.c2.x:.2f},{seg.c2.y:.2f} "
                    f"{end.x:.2f},{end.y:.2f}"
                )
        parts.append("Z")
    return "".join(parts)


def archive_svg(data: str, width: int, height: int) -> str:
    """SVG 1.1 w wymiarach surowej grafiki, do ręcznych poprawek (nie do Canvy, D9)."""
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" version="1.1" '
        f'width="{width}" height="{height}" viewBox="0 0 {width} {height}">'
        f'<rect width="{width}" height="{height}" fill="#fff"/>'
        f'<path fill="#000" fill-rule="evenodd" d="{data}"/></svg>'
    )


def page_svg(data: str, geometry: PageGeometry, scale: float, dx: float, dy: float) -> str:
    """Pełna strona: grafika wpasowana w obszar treści i do niego przycięta.

    Krzywe potrace potrafią wyjść ułamek piksela poza obraz źródłowy; po skalowaniu
    to kilka pikseli w marginesie, więc render jest przycinany do obszaru treści.
    """
    width, height = geometry.page_px
    left, top, right, bottom = geometry.content_box
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="{width}" height="{height}" viewBox="0 0 {width} {height}">'
        f'<defs><clipPath id="content"><rect x="{left}" y="{top}" '
        f'width="{right - left}" height="{bottom - top}"/></clipPath></defs>'
        f'<rect width="{width}" height="{height}" fill="#fff"/>'
        '<g clip-path="url(#content)">'
        f'<g transform="translate({dx:.4f} {dy:.4f}) scale({scale:.6f})">'
        f'<path fill="#000" fill-rule="evenodd" d="{data}"/></g></g></svg>'
    )


# --- Zapis i kontrola NFR-07 ---------------------------------------------------------


def save_page_png(img: Image.Image, path: Path, dpi: int) -> None:
    buffer = io.BytesIO()
    img.save(buffer, format="PNG", dpi=(dpi, dpi), optimize=True)
    write_bytes_atomic(path, buffer.getvalue())


def verify_page(path: Path, geometry: PageGeometry) -> list[str]:
    """Problemy z NFR-07; pusta lista oznacza stronę gotową do druku."""
    problems: list[str] = []
    with Image.open(path) as img:
        img.load()
        if img.size != geometry.page_px:
            problems.append(f"wymiary {img.size} zamiast {geometry.page_px}")
        if img.mode != "L" or "transparency" in img.info:
            problems.append(f"tryb {img.mode} zamiast 8-bit grayscale bez alfy")
        dpi = img.info.get("dpi")
        if dpi is None or any(abs(float(d) - geometry.dpi) > 0.5 for d in dpi):
            problems.append(f"DPI {dpi} zamiast {geometry.dpi}")
        pixels = np.asarray(img.convert("L"))
    values = set(np.unique(pixels).tolist())
    if not values <= {BLACK, WHITE}:
        problems.append(f"wartości pikseli inne niż 0 i 255 ({len(values - {BLACK, WHITE})})")
    ys, xs = np.nonzero(pixels == BLACK)
    if xs.size == 0:
        problems.append("strona nie ma czarnych pikseli")
    else:
        left, top, right, bottom = geometry.content_box
        if xs.min() < left or ys.min() < top or xs.max() >= right or ys.max() >= bottom:
            problems.append("czarne piksele poza obszarem treści (margines)")
    return problems


# --- Strona --------------------------------------------------------------------------


@dataclass(frozen=True)
class PageFiles:
    page: Path
    svg: Path


@dataclass(frozen=True)
class PagePostprocessor:
    """Obróbka jednej strony: `raw/page_XX.png` → `svg/page_XX.svg` i `page_XX.png`."""

    book_dir: Path
    geometry: PageGeometry
    params: PostprocessParams
    chain: tuple[PostProcessor, ...] = DEFAULT_CHAIN

    def process(self, raw: Path, name: str) -> PageFiles:
        files = PageFiles(
            page=self.book_dir / f"{name}.png", svg=self.book_dir / SVG_DIR / f"{name}.svg"
        )
        ctx = PageContext(geometry=self.geometry, params=self.params, svg_path=files.svg)
        try:
            with Image.open(raw) as source:
                img: Image.Image = source.copy()
        except OSError as e:
            raise PostprocessError(f"nie można odczytać {raw.name}: {e}") from e
        for step in self.chain:
            img = step.process(img, ctx)
        save_page_png(img, files.page, self.geometry.dpi)
        problems = verify_page(files.page, self.geometry)
        if problems:
            raise PostprocessError("; ".join(problems))
        return files
