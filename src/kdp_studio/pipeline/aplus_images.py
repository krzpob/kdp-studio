"""FR-24: grafiki modułów A+ Content składane przez program z okładki i stron, bez modelu.

Obrazy nie mają napisów od programu (teksty idą do pól modułów). Wachlarz okładek (nagłówek pod
banerem) odtwarza prototyp `docs/aplus/mockup_prototype.py`: dwie książeczki leżą płasko jedna
na drugiej, przód na wierzchu obrócony w lewo, tył pod spodem obrócony w prawo, z blokiem kartek,
grzbietem tyłu i miękkimi cieniami, na tle wybranym tak, żeby okładki się z nim nie zlewały.
"""

from __future__ import annotations

import io
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from kdp_studio.config import AplusBackground, AplusFan, AplusPages, AplusSettings
from kdp_studio.pipeline.output import write_bytes_atomic

# Rozmiary pól obrazów w edytorze A+ (sprawdzone 24.11.2026); program renderuje je `scale` razy.
HEADER_SIZE = (970, 600)  # Standard Image Header With Text
OVERLAY_SIZE = (970, 300)  # Standard Image with Dark/Light Overlay (co najmniej)
LOGO_SIZE = (600, 180)  # Standard Company Logo
COLUMN_SIDE = {3: 300, 4: 220}  # Standard Three/Four Images & Text
PAGE_BLOCK_RGB = (232, 228, 220)  # blok kartek pod okładką
PAGE_LINE_RGB = (205, 200, 192)  # linie kartek
SHADOW_RGB = (40, 30, 25)
MAX_DARKEN_STEPS = 12
LOGO_ASPECT_TOLERANCE = 0.02


class AplusImageError(Exception):
    """Grafika A+ nie spełnia wymagań (rozmiar pliku, tryb, proporcja)."""


@dataclass(frozen=True)
class SavedImage:
    path: Path
    width: int
    height: int
    bytes: int


@dataclass(frozen=True)
class BackgroundChoice:
    """Tło mockupów: kandydat, kolor po ewentualnym przyciemnieniu i jego odległość od okładek."""

    name: str
    rgb: tuple[int, int, int]
    delta_e: float
    darkened_steps: int
    scores: dict[str, float]


# --- Kolor -----------------------------------------------------------------------------------


def to_lab(rgb: np.ndarray) -> np.ndarray:
    """Piksele RGB (N × 3, 0–255) w Lab (L 0–100), do odległości ΔE76."""
    values = np.asarray(rgb, np.float32).reshape(-1, 1, 3) / 255.0
    return np.asarray(cv2.cvtColor(values, cv2.COLOR_RGB2LAB)).reshape(-1, 3)


def border_pixels(image: Image.Image, fraction: float) -> np.ndarray:
    """Piksele pasa brzegowego obrazu (po zmniejszeniu do 200 × 200), N × 3 RGB."""
    small = np.asarray(image.convert("RGB").resize((200, 200), Image.Resampling.BOX))
    k = max(1, int(200 * fraction))
    parts = [small[:k], small[-k:], small[:, :k], small[:, -k:]]
    return np.concatenate([p.reshape(-1, 3) for p in parts])


def _score(edges: np.ndarray, rgb: Sequence[float] | np.ndarray, percentile: float) -> float:
    distances = np.linalg.norm(edges - to_lab(np.array([rgb])), axis=1)
    return float(np.percentile(distances, percentile))


def pick_background(covers: Sequence[Image.Image], settings: AplusBackground) -> BackgroundChoice:
    """Kandydat najdalszy od kolorów brzegów okładek (percentyl ΔE). Gdy żaden nie osiąga
    `min_delta_e`, najlepszy jest przyciemniany krokami `darken_step`, aż osiągnie próg."""
    edges = to_lab(np.concatenate([border_pixels(c, settings.border) for c in covers]))
    scores = {
        name: round(_score(edges, rgb, settings.percentile), 2)
        for name, rgb in settings.candidates.items()
    }
    best = max(scores, key=lambda name: scores[name])
    base = np.array(settings.candidates[best], float)
    rgb, score, steps = base, scores[best], 0
    while score < settings.min_delta_e and steps < MAX_DARKEN_STEPS:
        steps += 1
        rgb = np.clip(base * (1 - settings.darken_step * steps), 0, 255)
        score = _score(edges, rgb, settings.percentile)
    final = (round(float(rgb[0])), round(float(rgb[1])), round(float(rgb[2])))
    return BackgroundChoice(best, final, round(score, 2), steps, scores)


def background(size: tuple[int, int], rgb: tuple[int, int, int], gradient: float) -> Image.Image:
    """Tło z lekkim pionowym gradientem: jaśniej u góry, ciemniej na dole."""
    width, height = size
    y = np.linspace(0, 1, height)[:, None, None]
    values = np.clip(np.array(rgb, float) * (1 + gradient - 2 * gradient * y), 0, 255)
    return Image.fromarray(np.broadcast_to(values, (height, width, 3)).astype(np.uint8), "RGB")


# --- Wachlarz okładek ------------------------------------------------------------------------


def cover_faces(cover: Image.Image, geometry: dict[str, object]) -> tuple[Image.Image, Image.Image]:
    """(tył, grzbiet) wycięte z `cover.png` według `manifest.cover.geometry` (cale, bez spadu)."""
    dpi = float(geometry["dpi"])  # type: ignore[arg-type]
    folds = geometry["folds_x_in"]
    trim = geometry["trim_box_in"]
    assert isinstance(folds, list) and isinstance(trim, list)

    def px(value: float) -> int:
        return round(value * dpi)

    left, top, _, bottom = (float(v) for v in trim)
    fold_back, fold_front = (float(v) for v in folds)
    back = cover.crop((px(left), px(top), px(fold_back), px(bottom)))
    spine = cover.crop((px(fold_back), px(top), px(fold_front), px(bottom)))
    return back.convert("RGB"), spine.convert("RGB")


def flat_book(
    face: Image.Image,
    height: int,
    angle: float,
    edge_ratio: float,
    spine: Image.Image | None = None,
    spine_shade: float = 0.85,
) -> Image.Image:
    """Książeczka leżąca płasko (RGBA): okładka, pod nią blok kartek widoczny przy dolnej
    i prawej krawędzi, obrót w płaszczyźnie. Leżąca tyłem do góry (`spine`) ma przy prawej
    krawędzi grzbiet: pasek w kolorze tła grzbietu, lekko w cieniu, bez napisu."""
    width = round(height * face.width / face.height)
    edge = max(4, round(height * edge_ratio))
    resized = face.convert("RGB").resize((width, height), Image.Resampling.LANCZOS)
    book = Image.new("RGBA", (width + edge, height + edge), (0, 0, 0, 0))
    draw = ImageDraw.Draw(book)
    draw.rectangle((edge, edge, width + edge - 1, height + edge - 1), fill=(*PAGE_BLOCK_RGB, 255))
    for i in range(0, edge, 2):
        draw.line((edge, height + i, width + edge - 1, height + i), fill=(*PAGE_LINE_RGB, 255))
        draw.line((width + i, edge, width + i, height + edge - 1), fill=(*PAGE_LINE_RGB, 255))
    if spine is not None:
        # Kolor tła grzbietu: pas uśredniony w poziomie (bez ściśniętego napisu), w cieniu.
        strip = spine.resize((1, height), Image.Resampling.BOX).resize((edge, height))
        strip = Image.eval(strip, lambda v: int(v * spine_shade))
        book.paste(strip, (width, edge))
    book.paste(resized, (0, 0))
    return book.rotate(angle, resample=Image.Resampling.BICUBIC, expand=True)


def drop_shadow(image: Image.Image, blur: float, opacity: float) -> tuple[Image.Image, int]:
    """Cień kształtu obrazu RGBA z zapasem 3 × `blur` wokół, żeby rozmycie nie urywało się na
    brzegu. Zwraca cień i ten zapas (o tyle trzeba go przesunąć w lewo i w górę)."""
    pad = max(1, round(blur * 3))
    alpha = Image.new("L", (image.width + 2 * pad, image.height + 2 * pad), 0)
    alpha.paste(image.getchannel("A"), (pad, pad))
    if blur > 0:
        alpha = alpha.filter(ImageFilter.GaussianBlur(blur))
    shadow = Image.new("RGBA", alpha.size, (*SHADOW_RGB, 0))
    shadow.putalpha(alpha.point(lambda v: int(v * opacity)))
    return shadow, pad


def _place(
    canvas: Image.Image, item: Image.Image, xy: tuple[int, int], fan: AplusFan, side: int
) -> None:
    shadow, pad = drop_shadow(item, fan.shadow.blur * side, fan.shadow.opacity)
    dx, dy = (round(v * side) for v in fan.shadow.offset)
    canvas.alpha_composite(shadow, (xy[0] + dx - pad, xy[1] + dy - pad))
    canvas.alpha_composite(item, xy)


def fan_header(
    front: Image.Image,
    back: Image.Image,
    spine: Image.Image,
    rgb: tuple[int, int, int],
    fan: AplusFan,
    size: tuple[int, int],
) -> Image.Image:
    """Nagłówek pod banerem: wachlarz okładek (referencja `docs/aplus/…referencja.jpg`)."""
    width, height = size
    canvas = background(size, rgb, fan.background.gradient).convert("RGBA")
    face_height = round(height * fan.size)
    back_img = flat_book(
        back, face_height, fan.back_angle_deg, fan.page_edge, spine, fan.spine_shade
    )
    front_img = flat_book(front, face_height, fan.front_angle_deg, fan.page_edge)
    face_width = round(face_height * front.width / front.height)
    fx = round(width * fan.left)
    fy = (height - front_img.height) // 2
    bx = fx + round(face_width * fan.back_offset)
    by = (height - back_img.height) // 2 + round(face_height * 0.02)
    _place(canvas, back_img, (bx, by), fan, face_height)
    _place(canvas, front_img, (fx, fy), fan, face_height)
    return canvas.convert("RGB")


# --- Strony wnętrza --------------------------------------------------------------------------


def ink_box(page: Image.Image, pad: float = 0.03) -> tuple[int, int, int, int]:
    """Prostokąt z rysunkiem strony (bez białego marginesu), z małym zapasem."""
    gray = page.convert("L")
    box = Image.eval(gray, lambda v: 255 - v).getbbox() or (0, 0, gray.width, gray.height)
    margin = round(max(gray.size) * pad)
    left, top, right, bottom = box
    return (
        max(0, left - margin),
        max(0, top - margin),
        min(gray.width, right + margin),
        min(gray.height, bottom + margin),
    )


def _fit(image: Image.Image, box: tuple[int, int]) -> Image.Image:
    scale = min(box[0] / image.width, box[1] / image.height)
    size = (max(1, round(image.width * scale)), max(1, round(image.height * scale)))
    return image.resize(size, Image.Resampling.LANCZOS)


def column_square(page: Image.Image, side: int, margin: float) -> Image.Image:
    """Kwadrat kolumny: rysunek strony (bez marginesu strony) na białym tle."""
    art = page.convert("RGB").crop(ink_box(page))
    inner = round(side * (1 - 2 * margin))
    fitted = _fit(art, (inner, inner))
    square = Image.new("RGB", (side, side), (255, 255, 255))
    square.paste(fitted, ((side - fitted.width) // 2, (side - fitted.height) // 2))
    return square


def _sheet(page: Image.Image, height: int, angle: float) -> Image.Image:
    """Kartka strony (RGBA) z cienką szarą krawędzią, obrócona."""
    sheet = _fit(page.convert("RGB"), (height * 4, height))
    draw = ImageDraw.Draw(sheet)
    draw.rectangle((0, 0, sheet.width - 1, sheet.height - 1), outline=PAGE_LINE_RGB, width=2)
    return sheet.convert("RGBA").rotate(angle, resample=Image.Resampling.BICUBIC, expand=True)


def _sheet_row(
    canvas: Image.Image,
    pages: Sequence[Image.Image],
    angles: Sequence[float],
    region: tuple[int, int, int, int],
    overlap: float,
    fan: AplusFan,
) -> None:
    """Kartki stron w rzędzie (zachodzą na siebie o `overlap` szerokości), zmniejszone tak,
    żeby razem z obrotem i cieniem zmieściły się w `region` (lewo, góra, prawo, dół)."""
    left, top, right, bottom = region
    height = bottom - top
    for _ in range(4):
        sheets = [_sheet(p, height, a) for p, a in zip(pages, angles, strict=False)]
        widest = max(s.width for s in sheets)
        step = round(widest * (1 - overlap))
        span = step * (len(sheets) - 1) + widest
        tallest = max(s.height for s in sheets)
        factor = min((right - left) / span, (bottom - top) / tallest)
        if factor >= 1:
            break
        height = max(1, int(height * factor * 0.98))
    x = left + (right - left - span) // 2
    for sheet in sheets:
        cx = x + widest // 2
        cy = top + (bottom - top) // 2
        _place(canvas, sheet, (cx - sheet.width // 2, cy - sheet.height // 2), fan, height)
        x += step


def pages_header(
    pages: Sequence[Image.Image],
    rgb: tuple[int, int, int],
    settings: AplusPages,
    fan: AplusFan,
    size: tuple[int, int],
) -> Image.Image:
    """Drugi mockup: kilka stron wnętrza obok siebie, zachodzących na siebie, z cieniami."""
    width, height = size
    canvas = background(size, rgb, fan.background.gradient).convert("RGBA")
    margin_y = round(height * (1 - settings.size) / 2)
    region = (round(width * 0.05), margin_y, round(width * 0.95), height - margin_y)
    _sheet_row(canvas, pages, settings.angles_deg, region, 0.3, fan)
    return canvas.convert("RGB")


def overlay_strip(
    pages: Sequence[Image.Image],
    rgb: tuple[int, int, int],
    fan: AplusFan,
    size: tuple[int, int],
) -> Image.Image:
    """Tło nakładki z faktami: jasna wersja tła, rząd stron po prawej; lewa część zostaje
    spokojna, bo tam Amazon kładzie tekst nakładki."""
    width, height = size
    light = tuple(round(v + (255 - v) * 0.45) for v in rgb)
    canvas = background(size, (light[0], light[1], light[2]), fan.background.gradient)
    canvas = canvas.convert("RGBA")
    margin_y = round(height * 0.12)
    region = (round(width * 0.47), margin_y, round(width * 0.97), height - margin_y)
    angles = [-3 if i % 2 == 0 else 3 for i in range(len(pages))]
    _sheet_row(canvas, pages, angles, region, 0.15, fan)
    return canvas.convert("RGB")


# --- Zapis -----------------------------------------------------------------------------------


def encode(image: Image.Image, image_format: str, quality: int) -> bytes:
    buffer = io.BytesIO()
    rgb = image.convert("RGB")
    if image_format == "jpg":
        rgb.save(buffer, "JPEG", quality=quality, optimize=True, dpi=(72, 72))
    else:
        rgb.save(buffer, "PNG", optimize=True, dpi=(72, 72))
    return buffer.getvalue()


def save_image(image: Image.Image, path: Path, settings: AplusSettings) -> SavedImage:
    """Obraz A+: RGB, JPG albo PNG, poniżej `max_file_mb`. JPG zbyt duży przy `jpeg_quality`
    dostaje niższą jakość (do 60); dalej za duży albo za duży PNG to błąd."""
    limit = round(settings.max_file_mb * 1024 * 1024)
    quality = settings.jpeg_quality
    data = encode(image, settings.image_format, quality)
    while settings.image_format == "jpg" and len(data) >= limit and quality > 60:
        quality -= 5
        data = encode(image, settings.image_format, quality)
    if len(data) >= limit:
        raise AplusImageError(
            f"{path.name}: {len(data) / 1024 / 1024:.1f} MB, a A+ przyjmuje pliki poniżej "
            f"{settings.max_file_mb:g} MB"
        )
    write_bytes_atomic(path, data)
    check_image(path, image.size, limit)
    return SavedImage(path, image.width, image.height, len(data))


def check_image(path: Path, size: tuple[int, int], limit: int) -> None:
    """Kontrola po zapisie: wymiary, tryb RGB, format JPG/PNG, rozmiar pliku."""
    with Image.open(path) as image:
        problems = []
        if image.size != size:
            problems.append(f"{image.size[0]}×{image.size[1]} px zamiast {size[0]}×{size[1]}")
        if image.mode != "RGB":
            problems.append(f"tryb {image.mode} zamiast RGB")
        if image.format not in ("JPEG", "PNG"):
            problems.append(f"format {image.format}")
    if path.stat().st_size >= limit:
        problems.append("plik za duży")
    if problems:
        raise AplusImageError(f"{path.name}: {'; '.join(problems)}")


def prepare_logo(
    source: Path, target: Path, settings: AplusSettings
) -> tuple[SavedImage, list[str]]:
    """Baner wydawcy (Company Logo 600 × 180) z pliku przygotowanego poza programem: kontrola
    proporcji, zapis w RGB w formacie A+. Zwraca plik i ostrzeżenia."""
    warnings = []
    with Image.open(source) as image:
        logo = image.convert("RGB")
    aspect = LOGO_SIZE[0] / LOGO_SIZE[1]
    if abs(logo.width / logo.height - aspect) > aspect * LOGO_ASPECT_TOLERANCE:
        warnings.append(
            f"baner {source.name} ma {logo.width}×{logo.height} px, a moduł oczekuje proporcji "
            f"{LOGO_SIZE[0]}:{LOGO_SIZE[1]}"
        )
    if logo.width < LOGO_SIZE[0] or logo.height < LOGO_SIZE[1]:
        warnings.append(f"baner {source.name} jest mniejszy niż {LOGO_SIZE[0]}×{LOGO_SIZE[1]} px")
    return save_image(logo, target, settings), warnings


def scaled(size: tuple[int, int], scale: int) -> tuple[int, int]:
    return size[0] * scale, size[1] * scale
