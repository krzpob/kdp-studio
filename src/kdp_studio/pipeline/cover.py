"""FR-15: układ okładki paperback — przód, tył z miniaturami, grzbiet i podgląd stref.

Wszystkie elementy rozmieszcza program, więc kontrola rozmieszczenia to asercja: tytuł,
podtytuł i grafika przodu w strefie `key_margin_in` przodu, miniatury w strefie tyłu
i poza polem kodu kreskowego, tekst grzbietu w strefie bezpiecznej grzbietu.

Etap 1 (bez modelu obrazu): przód to szkic z czarno-białą grafiką wybranej strony
w dolnej części i tytułem w pasie u góry; tło jest białe. Kolorowanie przodu i tło tyłu
dochodzą w kolejnych etapach, na warstwie `color`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from kdp_studio.config import CoverSettings
from kdp_studio.pipeline.cover_geometry import CoverGeometry, RectPx
from kdp_studio.pipeline.fonts import load_font

WHITE = 255
BLACK = 0
POINTS_PER_INCH = 72
GAP_IN = 0.15  # odstęp między elementami (tytuł/grafika, miniatury, nad polem kodu)
MIN_TITLE_SCALE = 0.35  # tytuł nie mniejszy niż 35% rozmiaru z konfiguracji


class CoverError(Exception):
    """Okładki nie da się złożyć (np. tytuł się nie mieści); kod wyjścia 1."""


@dataclass
class CoverLayers:
    """Warstwy okładki w pikselach 300 DPI (patrz `pipeline/cmyk.py`)."""

    color: Image.Image  # RGB, przez profil ICC
    black: Image.Image  # L, 0 = czerń K100
    paper: Image.Image  # L, 0 = sam papier K0

    @classmethod
    def blank(cls, size: tuple[int, int]) -> CoverLayers:
        return cls(
            color=Image.new("RGB", size, (255, 255, 255)),
            black=Image.new("L", size, WHITE),
            paper=Image.new("L", size, WHITE),
        )


@dataclass
class CoverBuild:
    layers: CoverLayers
    placements: dict[str, RectPx] = field(default_factory=dict)  # element → prostokąt
    spine_text: bool = False
    warnings: list[str] = field(default_factory=list)


# --- Pomocnicze ----------------------------------------------------------------------------


def _inside(inner: RectPx, outer: RectPx) -> bool:
    return (
        inner[0] >= outer[0]
        and inner[1] >= outer[1]
        and inner[2] <= outer[2]
        and inner[3] <= outer[3]
    )


def _overlaps(a: RectPx, b: RectPx) -> bool:
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def fit(size: tuple[int, int], rect: RectPx) -> RectPx:
    """Prostokąt o proporcjach `size` wpasowany w `rect` i wyśrodkowany."""
    width, height = size
    left, top, right, bottom = rect
    scale = min((right - left) / width, (bottom - top) / height)
    w, h = max(1, round(width * scale)), max(1, round(height * scale))
    x = left + (right - left - w) // 2
    y = top + (bottom - top - h) // 2
    return x, y, x + w, y + h


def art_bbox(page: Image.Image) -> tuple[int, int, int, int]:
    """Prostokąt z czarnymi pikselami strony (grafika bez białych marginesów)."""
    pixels = np.asarray(page.convert("L")) < 128
    ys, xs = np.nonzero(pixels)
    if xs.size == 0:
        raise CoverError("strona nie ma czarnych pikseli")
    return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1


def line_width_px(page: Image.Image) -> float:
    """Typowa grubość konturów strony w pikselach: mediana grzbietów transformaty odległości."""
    black = (np.asarray(page.convert("L")) < 128).astype(np.uint8)
    if not black.any():
        return 1.0
    dist = cv2.distanceTransform(black, cv2.DIST_L2, 3)
    ridge = (dist >= cv2.dilate(dist, np.ones((3, 3), np.uint8))) & (dist > 0)
    return float(np.median(dist[ridge]) * 2) if ridge.any() else 1.0


def _paste_line_art(layers: CoverLayers, art: Image.Image, rect: RectPx) -> None:
    """Czarno-biała grafika przeskalowana do `rect`; czarne piksele trafiają do warstwy K100."""
    left, top, right, bottom = rect
    scaled = art.convert("L").resize((right - left, bottom - top), Image.Resampling.LANCZOS)
    ink = scaled.point(lambda v: BLACK if v < 128 else WHITE, mode="L")
    region = layers.black.crop(rect)
    layers.black.paste(Image.fromarray(np.minimum(np.asarray(region), np.asarray(ink))), rect[:2])


def _text_mask(text: str, font: ImageFont.FreeTypeFont) -> Image.Image:
    """Napis jako maska L (0 = tusz) przycięta do liter."""
    x0, y0, x1, y1 = font.getbbox(text)
    mask = Image.new("L", (max(1, round(x1 - x0)), max(1, round(y1 - y0))), WHITE)
    draw = ImageDraw.Draw(mask)
    draw.fontmode = "1"
    draw.text((-x0, -y0), text, font=font, fill=BLACK)
    return mask


def _paste_mask(layers: CoverLayers, mask: Image.Image, origin: tuple[int, int]) -> RectPx:
    x, y = origin
    rect = (x, y, x + mask.width, y + mask.height)
    region = np.asarray(layers.black.crop(rect))
    layers.black.paste(Image.fromarray(np.minimum(region, np.asarray(mask))), (x, y))
    return rect


# --- Przód ---------------------------------------------------------------------------------


def _fit_font(
    settings: CoverSettings, text: str, size: int, max_width: int
) -> ImageFont.FreeTypeFont:
    font = load_font(settings.title_font_path, size, settings.title_font_variation)
    width = font.getbbox(text)[2] - font.getbbox(text)[0]
    if width > max_width:
        font = load_font(
            settings.title_font_path,
            max(1, int(size * max_width / width)),
            settings.title_font_variation,
        )
    return font


def _title_lines(
    settings: CoverSettings, title: str, size: int, max_width: int
) -> list[tuple[str, ImageFont.FreeTypeFont]]:
    """Tytuł w jednej linii, a gdy wyszedłby za mały, w dwóch (podział przy spacji)."""
    one = _fit_font(settings, title, size, max_width)
    words = title.split()
    if one.size >= size * 0.7 or len(words) < 2:
        return [(title, one)]
    best: list[tuple[str, ImageFont.FreeTypeFont]] = []
    best_size = 0
    colon = next((i + 1 for i, w in enumerate(words[:-1]) if w.endswith(":")), None)
    for cut in range(1, len(words)):
        lines = [" ".join(words[:cut]), " ".join(words[cut:])]
        fonts = [_fit_font(settings, line, size, max_width) for line in lines]
        smallest = int(min(f.size for f in fonts))
        if cut == colon:  # podział po dwukropku czyta się naturalnie: lekka premia
            smallest = int(smallest * 1.15)
        if smallest > best_size:
            best_size = smallest
            real = int(min(f.size for f in fonts))
            uniform = load_font(settings.title_font_path, real, settings.title_font_variation)
            best = [(line, uniform) for line in lines]
    return best if best_size > one.size else [(title, one)]


def place_front(
    layers: CoverLayers,
    geometry: CoverGeometry,
    settings: CoverSettings,
    page: Image.Image,
    title: str,
    subtitle: str,
) -> dict[str, RectPx]:
    """Szkic przodu: tytuł i podtytuł w pasie u góry, grafika strony pod nimi."""
    key = geometry.px(geometry.key_front)
    left, top, right, bottom = key
    band = top + round((bottom - top) * settings.title_band)
    gap = round(GAP_IN * geometry.dpi)
    width = right - left
    size = round(settings.title_font_pt / POINTS_PER_INCH * geometry.dpi)

    lines = _title_lines(settings, title, size, width)
    if min(f.size for _, f in lines) < size * MIN_TITLE_SCALE:
        raise CoverError("tytuł nie mieści się na przodzie okładki (za długi)")
    masks = [_text_mask(text, font) for text, font in lines]
    sub_mask = None
    if subtitle:
        sub_font = _fit_font(settings, subtitle, round(size * settings.subtitle_scale), width)
        sub_mask = _text_mask(subtitle, sub_font)
    line_gap = round(0.15 * lines[0][1].size)
    total = sum(m.height for m in masks) + line_gap * (len(masks) - 1)
    if sub_mask is not None:
        total += line_gap * 2 + sub_mask.height
    scale = min(1.0, (band - top) / total)
    if scale < 1.0:  # pas za niski: zmniejsz wszystko proporcjonalnie
        masks = [
            m.resize((max(1, round(m.width * scale)), max(1, round(m.height * scale))))
            for m in masks
        ]
        if sub_mask is not None:
            sub_mask = sub_mask.resize(
                (max(1, round(sub_mask.width * scale)), max(1, round(sub_mask.height * scale)))
            )
        line_gap = round(line_gap * scale)
        total = sum(m.height for m in masks) + line_gap * (len(masks) - 1)
        if sub_mask is not None:
            total += line_gap * 2 + sub_mask.height

    placements: dict[str, RectPx] = {}
    y = top + (band - top - total) // 2
    title_rects = []
    for mask in masks:
        title_rects.append(_paste_mask(layers, mask, (left + (width - mask.width) // 2, y)))
        y += mask.height + line_gap
    placements["title"] = (
        min(r[0] for r in title_rects),
        title_rects[0][1],
        max(r[2] for r in title_rects),
        title_rects[-1][3],
    )
    if sub_mask is not None:
        y += line_gap
        placements["subtitle"] = _paste_mask(
            layers, sub_mask, (left + (width - sub_mask.width) // 2, y)
        )

    art = page.convert("L").crop(art_bbox(page))
    art_rect = fit(art.size, (left, band + gap, right, bottom))
    _paste_line_art(layers, art, art_rect)
    placements["front_art"] = art_rect
    return placements


# --- Tył -----------------------------------------------------------------------------------


def thumbnail_grid(area: RectPx, count: int, aspect: float, gap: int) -> list[RectPx]:
    """Największe jednakowe miniatury (szerokość/wysokość = `aspect`) w siatce w `area`."""
    left, top, right, bottom = area
    width, height = right - left, bottom - top
    best: list[RectPx] = []
    best_w = 0.0
    for cols in range(1, count + 1):
        rows = -(-count // cols)
        cell_w = (width - gap * (cols - 1)) / cols
        cell_h = (height - gap * (rows - 1)) / rows
        if cell_w <= 0 or cell_h <= 0:
            continue
        thumb_w = min(cell_w, cell_h * aspect)
        if thumb_w <= best_w:
            continue
        best_w = thumb_w
        thumb_h = thumb_w / aspect
        grid_w = cols * thumb_w + gap * (cols - 1)
        grid_h = rows * thumb_h + gap * (rows - 1)
        x0 = left + (width - grid_w) / 2
        y0 = top + (height - grid_h) / 2
        best = []
        for index in range(count):
            row, col = divmod(index, cols)
            in_row = min(cols, count - row * cols)  # ostatni rząd wyśrodkowany
            row_x0 = x0 + (cols - in_row) * (thumb_w + gap) / 2
            x = row_x0 + col * (thumb_w + gap)
            y = y0 + row * (thumb_h + gap)
            best.append((round(x), round(y), round(x + thumb_w), round(y + thumb_h)))
    return best


def place_back(
    layers: CoverLayers,
    geometry: CoverGeometry,
    settings: CoverSettings,
    pages: list[Image.Image],
) -> dict[str, RectPx]:
    """Miniatury stron w ramkach, w strefie tyłu nad polem kodu kreskowego."""
    key = geometry.px(geometry.key_back)
    barcode = geometry.px(geometry.barcode)
    gap = round(GAP_IN * geometry.dpi)
    area = (key[0], key[1], key[2], min(key[3], barcode[1] - gap))
    first = pages[0]
    rects = thumbnail_grid(area, len(pages), first.width / first.height, gap)
    if len(rects) != len(pages):
        raise CoverError("miniatury nie mieszczą się na tylnej okładce")
    placements: dict[str, RectPx] = {}
    min_frame = settings.thumbnail_frame_min_pt / POINTS_PER_INCH * geometry.dpi
    for index, (page, rect) in enumerate(zip(pages, rects, strict=True), start=1):
        scale = (rect[2] - rect[0]) / page.width
        frame = max(
            round(min_frame), round(settings.thumbnail_frame_ratio * line_width_px(page) * scale)
        )
        paper = Image.new("L", (rect[2] - rect[0], rect[3] - rect[1]), BLACK)
        layers.paper.paste(paper, rect[:2])
        inner = (rect[0] + frame, rect[1] + frame, rect[2] - frame, rect[3] - frame)
        _paste_line_art(layers, page, inner)
        draw = ImageDraw.Draw(layers.black)
        draw.rectangle((rect[0], rect[1], rect[2] - 1, rect[3] - 1), outline=BLACK, width=frame)
        placements[f"thumbnail_{index}"] = rect
    return placements


# --- Grzbiet -------------------------------------------------------------------------------


def place_spine(
    layers: CoverLayers, geometry: CoverGeometry, settings: CoverSettings, title: str
) -> tuple[RectPx | None, str | None]:
    """Tytuł na grzbiecie czytany z góry na dół; (prostokąt albo None, ostrzeżenie)."""
    minimum = max(settings.spine_text_min_pages, geometry.kdp.spine_text_kdp_min_pages)
    if geometry.pages_in_book < minimum:
        return None, None
    live = geometry.px(geometry.live_spine)
    width, height = live[2] - live[0], live[3] - live[1]
    size = round(settings.title_font_pt / POINTS_PER_INCH * geometry.dpi)
    font = load_font(settings.title_font_path, size, settings.title_font_variation)
    x0, y0, x1, y1 = font.getbbox(title)
    scale = min(1.0, width / (y1 - y0), height / (x1 - x0))
    size = int(size * scale)
    min_px = settings.spine_font_min_pt / POINTS_PER_INCH * geometry.dpi
    if size < min_px:
        return None, (
            f"tytuł nie mieści się na grzbiecie w rozmiarze ≥ {settings.spine_font_min_pt:g} pt; "
            "grzbiet bez tekstu"
        )
    while True:  # zaokrąglenia obrysu liter: zmniejszaj, aż napis zmieści się w strefie
        font = load_font(settings.title_font_path, size, settings.title_font_variation)
        mask = _text_mask(title, font).rotate(-90, expand=True, fillcolor=WHITE)
        if mask.width <= width and mask.height <= height:
            break
        size -= 1
        if size < min_px:
            return None, "tytuł nie mieści się na grzbiecie; grzbiet bez tekstu"
    x = live[0] + (width - mask.width) // 2
    y = live[1] + (height - mask.height) // 2
    return _paste_mask(layers, mask, (x, y)), None


# --- Całość --------------------------------------------------------------------------------


def build_cover(
    geometry: CoverGeometry,
    settings: CoverSettings,
    front_page: Path,
    thumbnails: list[Path],
    title: str,
    subtitle: str,
) -> CoverBuild:
    layers = CoverLayers.blank(geometry.size_px)
    with Image.open(front_page) as img:
        front = img.convert("L")
    pages = []
    for path in thumbnails:
        with Image.open(path) as img:
            pages.append(img.convert("L"))
    build = CoverBuild(layers=layers)
    build.placements.update(place_front(layers, geometry, settings, front, title, subtitle))
    build.placements.update(place_back(layers, geometry, settings, pages))
    spine, warning = place_spine(layers, geometry, settings, title)
    if spine is not None:
        build.placements["spine_text"] = spine
        build.spine_text = True
    if warning is not None:
        build.warnings.append(warning)
    check_placements(build, geometry)
    return build


def check_placements(build: CoverBuild, geometry: CoverGeometry) -> None:
    """Asercja rozmieszczenia (FR-15): elementy w swoich strefach, nic w polu kodu."""
    front = geometry.px(geometry.key_front)
    back = geometry.px(geometry.key_back)
    spine = geometry.px(geometry.live_spine)
    barcode = geometry.px(geometry.barcode)
    problems = []
    for name, rect in build.placements.items():
        zone = spine if name == "spine_text" else back if name.startswith("thumbnail") else front
        if not _inside(rect, zone):
            problems.append(f"{name} poza swoją strefą")
        if _overlaps(rect, barcode):
            problems.append(f"{name} wchodzi w pole kodu kreskowego")
    if problems:
        raise CoverError("; ".join(problems))


# --- Podgląd -------------------------------------------------------------------------------


def preview(
    cover: Image.Image, geometry: CoverGeometry, template: Path | None = None
) -> Image.Image:
    """`cover_preview.png`: linie cięcia i zgięcia, strefy, pole kodu, opcjonalnie szablon KDP."""
    img = cover.convert("RGB")
    if template is not None:
        with Image.open(template) as tpl:
            overlay = tpl.convert("RGB").resize(img.size, Image.Resampling.BILINEAR)
        img = Image.blend(img, overlay, 0.35)
    draw = ImageDraw.Draw(img, "RGBA")
    line = max(2, geometry.dpi // 100)
    barcode = geometry.px(geometry.barcode)
    draw.rectangle(barcode, fill=(255, 230, 0, 140), outline=(200, 160, 0, 255), width=line)
    for rect, color in (
        (geometry.px(geometry.trim_box), (0, 0, 0, 255)),
        (geometry.px(geometry.live_back), (0, 160, 0, 255)),
        (geometry.px(geometry.live_front), (0, 160, 0, 255)),
        (geometry.px(geometry.live_spine), (0, 160, 0, 255)),
        (geometry.px(geometry.key_back), (255, 120, 0, 255)),
        (geometry.px(geometry.key_front), (255, 120, 0, 255)),
    ):
        if rect[2] > rect[0] and rect[3] > rect[1]:
            draw.rectangle(rect, outline=color, width=line)
    height = img.height
    dash = geometry.dpi // 10
    for fold in geometry.folds_x:
        x = round(fold * geometry.dpi)
        for y in range(0, height, dash * 2):
            draw.line((x, y, x, min(height, y + dash)), fill=(18, 6, 220, 255), width=line)
    return img


def front_crop(cover: Image.Image, geometry: CoverGeometry) -> Image.Image:
    """Sam przód po przycięciu (`front.png`, np. do reklam)."""
    _, top, right, bottom = geometry.trim_box
    return cover.crop(geometry.px((geometry.folds_x[1], top, right, bottom)))
