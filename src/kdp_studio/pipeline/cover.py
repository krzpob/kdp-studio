"""FR-15: układ okładki paperback — przód, tył z miniaturami, grzbiet i podgląd stref.

Wszystkie elementy rozmieszcza program, więc kontrola rozmieszczenia to asercja: tytuł,
podtytuł i grafika przodu w strefie `key_margin_in` przodu, miniatury w strefie tyłu
i poza polem kodu kreskowego, tekst grzbietu w strefie bezpiecznej grzbietu.

Przód: szkic z czarno-białą grafiką wybranej strony w dolnej części i pustym pasem u góry.
Etap 2: model koloruje szkic (`colorize`), program nakłada na kolor ostre kontury 300 DPI,
jeśli kontury modelu się zgadzają, a na końcu wpisuje tytuł (wypełnienie w kolorze, obrys
czarny K100) i sprawdza jego czytelność w miniaturze. Bez `colorize` przód zostaje szkicem na
białym tle. Tło tyłu i grzbietu z modelu to etap 3.
"""

from __future__ import annotations

from collections.abc import Callable
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
CONTOUR_DARK = 110  # piksel obrazu modelu ciemniejszy niż to liczy się jako kontur
CONTOUR_CHECK_PX = 800  # szerokość, przy której porównuje się kontury


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
    colorized: bool = False  # przód pokolorowany przez model (etap 2)
    contour_match: float | None = None  # zgodność konturów modelu ze szkicem
    contours_overlay: bool = True  # nałożono ostre kontury 300 DPI
    title_thumb_px: float = 0.0  # wysokość liter tytułu w miniaturze thumbnail_check_px
    title_contrast: float = 0.0  # kontrast WCAG tytułu z tłem


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


def place_front_art(
    layers: CoverLayers, geometry: CoverGeometry, settings: CoverSettings, page: Image.Image
) -> RectPx:
    """Grafika wybranej strony w strefie przodu pod pasem tytułu (czarne kontury K100)."""
    left, top, right, bottom = geometry.px(geometry.key_front)
    band = top + round((bottom - top) * settings.title_band)
    gap = round(GAP_IN * geometry.dpi)
    art = page.convert("L").crop(art_bbox(page))
    rect = fit(art.size, (left, band + gap, right, bottom))
    _paste_line_art(layers, art, rect)
    return rect


@dataclass(frozen=True)
class _Text:
    ink: np.ndarray  # True = litera
    outline: np.ndarray  # True = litera albo obrys
    letter_height: int  # wysokość liter bez obrysu (kontrola czytelności)


def _outlined(text: str, font: ImageFont.FreeTypeFont, radius: int) -> _Text:
    mask = _text_mask(text, font)
    ink = np.pad(np.asarray(mask) == BLACK, radius)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * radius + 1, 2 * radius + 1))
    outline = cv2.dilate(ink.astype(np.uint8), kernel) > 0 if radius else ink
    return _Text(ink=ink, outline=np.asarray(outline), letter_height=mask.height)


def _resized(text: _Text, scale: float) -> _Text:
    def shrink(mask: np.ndarray) -> np.ndarray:
        h, w = mask.shape
        size = (max(1, round(w * scale)), max(1, round(h * scale)))
        return np.asarray(
            cv2.resize(mask.astype(np.uint8), size, interpolation=cv2.INTER_NEAREST) > 0
        )

    return _Text(shrink(text.ink), shrink(text.outline), max(1, round(text.letter_height * scale)))


def _paste_text(
    layers: CoverLayers, text: _Text, origin: tuple[int, int], fill: tuple[int, int, int]
) -> RectPx:
    """Obrys do warstwy K100, wnętrze liter w kolorze `fill` do warstwy koloru."""
    x, y = origin
    h, w = text.outline.shape
    rect = (x, y, x + w, y + h)
    black = np.asarray(layers.black.crop(rect)).copy()
    black[text.outline] = BLACK
    black[text.ink] = WHITE
    layers.black.paste(Image.fromarray(black), (x, y))
    color = np.asarray(layers.color.crop(rect)).copy()
    color[text.ink] = fill
    layers.color.paste(Image.fromarray(color), (x, y))
    return rect


@dataclass(frozen=True)
class TitleInfo:
    placements: dict[str, RectPx]
    letter_height_px: int  # najmniejsza wysokość liter tytułu na okładce


def place_titles(
    layers: CoverLayers,
    geometry: CoverGeometry,
    settings: CoverSettings,
    title: str,
    subtitle: str,
) -> TitleInfo:
    """Tytuł i podtytuł w pasie u góry przodu: wypełnienie `title_fill_rgb`, obrys czarny K100."""
    left, top, right, bottom = geometry.px(geometry.key_front)
    band = top + round((bottom - top) * settings.title_band)
    width = right - left
    size = round(settings.title_font_pt / POINTS_PER_INCH * geometry.dpi)
    radius = round(settings.title_outline_pt / POINTS_PER_INCH * geometry.dpi)

    lines = _title_lines(settings, title, size, width - 2 * radius)
    if min(f.size for _, f in lines) < size * MIN_TITLE_SCALE:
        raise CoverError("tytuł nie mieści się na przodzie okładki (za długi)")
    texts = [_outlined(line, font, radius) for line, font in lines]
    sub_text = None
    if subtitle:
        sub_radius = max(1, round(radius * settings.subtitle_scale))
        sub_font = _fit_font(
            settings, subtitle, round(size * settings.subtitle_scale), width - 2 * sub_radius
        )
        sub_text = _outlined(subtitle, sub_font, sub_radius)
    line_gap = round(0.1 * lines[0][1].size)

    def total() -> int:
        height = sum(t.outline.shape[0] for t in texts) + line_gap * (len(texts) - 1)
        if sub_text is not None:
            height += line_gap * 2 + sub_text.outline.shape[0]
        return int(height)

    scale = min(1.0, (band - top) / total())
    if scale < 1.0:  # pas za niski: zmniejsz wszystko proporcjonalnie
        texts = [_resized(t, scale) for t in texts]
        sub_text = _resized(sub_text, scale) if sub_text is not None else None
        line_gap = round(line_gap * scale)

    placements: dict[str, RectPx] = {}
    y = top + (band - top - total()) // 2
    rects = []
    fill = settings.title_fill_rgb
    for text in texts:
        w = text.outline.shape[1]
        rects.append(_paste_text(layers, text, (left + (width - w) // 2, y), fill))
        y += text.outline.shape[0] + line_gap
    placements["title"] = (
        min(r[0] for r in rects),
        rects[0][1],
        max(r[2] for r in rects),
        rects[-1][3],
    )
    if sub_text is not None:
        y += line_gap
        w = sub_text.outline.shape[1]
        placements["subtitle"] = _paste_text(
            layers, sub_text, (left + (width - w) // 2, y), settings.subtitle_fill_rgb
        )
    return TitleInfo(placements=placements, letter_height_px=min(t.letter_height for t in texts))


# --- Kolor przodu (etap 2) -------------------------------------------------------------------


def front_sketch(layers: CoverLayers, geometry: CoverGeometry) -> Image.Image:
    """Szkic przodu ze spadem dla modelu: kontury na białym tle, pusty pas na tytuł."""
    return layers.black.crop(geometry.px(geometry.front_panel)).convert("RGB")


def contour_match(line_art: np.ndarray, colored: Image.Image, radius: int) -> float:
    """Udział konturów szkicu, przy których obraz modelu ma ciemny piksel (w promieniu)."""
    if not line_art.any():
        return 1.0
    dark = (np.asarray(colored.convert("L")) < CONTOUR_DARK).astype(np.uint8)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * radius + 1, 2 * radius + 1))
    near = cv2.dilate(dark, kernel) > 0
    return float(near[line_art].mean())


def apply_front_color(
    layers: CoverLayers,
    geometry: CoverGeometry,
    settings: CoverSettings,
    colored: Image.Image,
) -> tuple[float, bool]:
    """Kolor przodu z modelu: (zgodność konturów, czy nałożono kontury 300 DPI).

    Przy zgodności ≥ `contour_match_min` zostają ostre kontury K100 ze szkicu (mnożenie
    przez czerń). Przy przesunięciu program używa samego powiększonego obrazu modelu.
    """
    rect = geometry.px(geometry.front_panel)
    size = (rect[2] - rect[0], rect[3] - rect[1])
    colored = colored.convert("RGB").resize(size, Image.Resampling.LANCZOS)
    # Porównanie w mniejszej skali: szybciej, a promień wyszukiwania i tak jest w calach.
    scale = min(1.0, CONTOUR_CHECK_PX / size[0])
    small = (max(1, round(size[0] * scale)), max(1, round(size[1] * scale)))
    sketch = layers.black.crop(rect).resize(small, Image.Resampling.BILINEAR)
    line_art = np.asarray(sketch) < 128
    radius = max(1, round(settings.contour_search_in * geometry.dpi * scale))
    match = contour_match(line_art, colored.resize(small, Image.Resampling.BILINEAR), radius)
    overlay = match >= settings.contour_match_min
    if not overlay:
        layers.black.paste(Image.new("L", size, WHITE), rect[:2])
    layers.color.paste(colored, rect[:2])
    return round(match, 3), overlay


def _luminance(rgb: np.ndarray) -> np.ndarray:
    channels = rgb.astype(np.float64) / 255
    linear = np.where(channels <= 0.03928, channels / 12.92, ((channels + 0.055) / 1.055) ** 2.4)
    return np.asarray(linear @ np.array([0.2126, 0.7152, 0.0722]))


def contrast_ratio(first: np.ndarray, second: np.ndarray) -> float:
    """Kontrast WCAG między dwoma kolorami RGB (1–21)."""
    a, b = float(_luminance(first)), float(_luminance(second))
    return (max(a, b) + 0.05) / (min(a, b) + 0.05)


def title_contrast(layers: CoverLayers, rect: RectPx, fill: tuple[int, int, int]) -> float:
    """Kontrast tytułu z tłem: lepszy z (wypełnienie, czarny obrys) wobec średniego tła."""
    color = np.asarray(layers.color.crop(rect)).reshape(-1, 3)
    black = np.asarray(layers.black.crop(rect)).reshape(-1)
    background_px = color[(black == WHITE) & np.any(color != fill, axis=1)]
    if background_px.size == 0:
        return 21.0
    background = background_px.mean(axis=0)
    return max(contrast_ratio(np.array(fill), background), contrast_ratio(np.zeros(3), background))


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


Colorize = Callable[[Image.Image], Image.Image]


def build_cover(
    geometry: CoverGeometry,
    settings: CoverSettings,
    front_page: Path,
    thumbnails: list[Path],
    title: str,
    subtitle: str,
    colorize: Colorize | None = None,
) -> CoverBuild:
    """Okładka w warstwach. `colorize(szkic przodu) -> obraz RGB` to kolor z modelu (etap 2);
    bez niego przód zostaje szkicem na białym tle."""
    layers = CoverLayers.blank(geometry.size_px)
    with Image.open(front_page) as img:
        front = img.convert("L")
    pages = []
    for path in thumbnails:
        with Image.open(path) as img:
            pages.append(img.convert("L"))
    build = CoverBuild(layers=layers)
    build.placements["front_art"] = place_front_art(layers, geometry, settings, front)
    build.placements.update(place_back(layers, geometry, settings, pages))
    spine, warning = place_spine(layers, geometry, settings, title)
    if spine is not None:
        build.placements["spine_text"] = spine
        build.spine_text = True
    if warning is not None:
        build.warnings.append(warning)

    if colorize is not None:
        colored = colorize(front_sketch(layers, geometry))
        build.contour_match, build.contours_overlay = apply_front_color(
            layers, geometry, settings, colored
        )
        build.colorized = True
        if not build.contours_overlay:
            build.warnings.append(
                f"kontury z modelu przesunięte (zgodność {build.contour_match:.0%}); "
                "przód bez nałożonych konturów 300 DPI"
            )

    titles = place_titles(layers, geometry, settings, title, subtitle)
    build.placements.update(titles.placements)
    check_readability(build, geometry, settings, titles)
    check_placements(build, geometry)
    return build


def check_readability(
    build: CoverBuild, geometry: CoverGeometry, settings: CoverSettings, titles: TitleInfo
) -> None:
    """Czytelność tytułu w miniaturze `thumbnail_check_px` (wyniki Amazon) i jego kontrast."""
    left, _, right, _ = geometry.px(geometry.front_panel)
    scale = settings.thumbnail_check_px / (right - left)
    build.title_thumb_px = round(titles.letter_height_px * scale, 1)
    build.title_contrast = round(
        title_contrast(build.layers, titles.placements["title"], settings.title_fill_rgb), 2
    )
    if build.title_thumb_px < settings.thumbnail_min_text_px:
        build.warnings.append(
            f"tytuł w miniaturze {settings.thumbnail_check_px} px ma litery wysokości "
            f"{build.title_thumb_px:g} px (zalecane ≥ {settings.thumbnail_min_text_px:g} px): "
            "skróć tytuł albo zwiększ title_font_pt"
        )
    if build.title_contrast < settings.title_min_contrast:
        build.warnings.append(
            f"słaby kontrast tytułu z tłem ({build.title_contrast:g}:1, "
            f"zalecane ≥ {settings.title_min_contrast:g}:1)"
        )


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
