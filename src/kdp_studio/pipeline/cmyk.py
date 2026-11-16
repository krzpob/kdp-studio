"""FR-15: okładka w CMYK — konwersja przez profil ICC, czerń K100, limit farb, podgląd druku.

Praca odbywa się w RGB, a do CMYK trafia gotowa warstwa kolorowa, jednym przekształceniem
przez profil (Pillow ImageCms, czyli LittleCMS z kół Pillow, bez bibliotek natywnych).
Elementy czarne (kontury, ramki miniatur, czarny tekst) program wpisuje bezpośrednio jako
C0 M0 Y0 K100, a białe tło miniatur jako C0 M0 Y0 K0 (sam papier), z pominięciem profilu.

Warstwy okładki:
- `color`: RGB, wszystko, co przechodzi przez profil;
- `black`: L, 0 tam, gdzie ma być czysta czerń K100;
- `paper`: L, 0 tam, gdzie ma być sam papier (K0).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Protocol

import numpy as np
from PIL import Image, ImageCms

from kdp_studio.config import CmykSettings

BLACK_K100 = (0, 0, 0, 255)
INK_SCALE = 255  # kanał 255 = 100% farby


class CmykError(Exception):
    """Brak albo zły profil ICC; błąd konfiguracji (kod 1)."""


class CmykConverter(Protocol):
    name: str  # opis profilu do manifestu
    sha256: str | None  # suma pliku profilu

    def to_cmyk(self, rgb: Image.Image) -> Image.Image: ...

    def to_rgb(self, cmyk: Image.Image) -> Image.Image:
        """Symulacja druku na ekranie (ten sam profil z powrotem do sRGB)."""
        ...


_INTENTS = {
    "perceptual": ImageCms.Intent.PERCEPTUAL,
    "relative_colorimetric": ImageCms.Intent.RELATIVE_COLORIMETRIC,
}


class IccConverter:
    """sRGB → CMYK przez profil ICC z konfiguracji (`cover.cmyk.profile`)."""

    def __init__(self, settings: CmykSettings) -> None:
        path = settings.profile_path
        if path is None or not path.is_file():
            raise CmykError(
                "brak profilu CMYK (cover.cmyk.profile w config/settings.yaml"
                + (f": {path}" if path is not None else "")
                + "). KDP żadnego nie wskazuje; zwykle używa się U.S. Web Coated (SWOP) v2 "
                "z pakietu profili ICC Adobe (pobierz go sam, licencja nie pozwala go dołączyć). "
                "Do prób na macOS: /System/Library/ColorSync/Profiles/Generic CMYK Profile.icc"
            )
        try:
            profile = ImageCms.getOpenProfile(str(path))
        except (OSError, ImageCms.PyCMSError) as e:
            raise CmykError(f"nie można odczytać profilu {path}: {e}") from e
        if profile.profile.xcolor_space.strip() != "CMYK":
            raise CmykError(f"{path} nie jest profilem CMYK ({profile.profile.xcolor_space})")
        srgb = ImageCms.createProfile("sRGB")
        intent = _INTENTS[settings.rendering_intent]
        flags = (
            ImageCms.Flags.BLACKPOINTCOMPENSATION
            if settings.black_point_compensation
            else ImageCms.Flags.NONE
        )
        self._to_cmyk = ImageCms.buildTransform(srgb, profile, "RGB", "CMYK", intent, flags)
        self._to_rgb = ImageCms.buildTransform(profile, srgb, "CMYK", "RGB", intent, flags)
        self.name = (ImageCms.getProfileDescription(profile) or path.name).strip()
        self.sha256: str | None = hashlib.sha256(path.read_bytes()).hexdigest()

    def to_cmyk(self, rgb: Image.Image) -> Image.Image:
        return _applied(ImageCms.applyTransform(rgb.convert("RGB"), self._to_cmyk))

    def to_rgb(self, cmyk: Image.Image) -> Image.Image:
        return _applied(ImageCms.applyTransform(cmyk, self._to_rgb))


def _applied(result: Image.Image | None) -> Image.Image:
    """applyTransform zwraca None tylko przy inPlace=True."""
    assert result is not None
    return result


class NaiveConverter:
    """Wzór bez profilu (K = 1 - max(R, G, B)); tylko do testów i prób bez pliku ICC."""

    name = "naive (bez profilu ICC)"
    sha256: str | None = None

    def to_cmyk(self, rgb: Image.Image) -> Image.Image:
        return _naive_cmyk(rgb)

    def to_rgb(self, cmyk: Image.Image) -> Image.Image:
        return cmyk.convert("RGB")


def _naive_cmyk(rgb: Image.Image) -> Image.Image:
    values = np.asarray(rgb.convert("RGB"), dtype=np.float64) / 255
    k = 1 - values.max(axis=2)
    room = np.where(k < 1, 1 - k, 1)
    cmy = (1 - values - k[..., None]) / room[..., None]
    out = np.dstack([cmy, k]) * 255
    return Image.fromarray(np.round(out).astype(np.uint8), mode="CMYK")


@dataclass(frozen=True)
class CmykResult:
    image: Image.Image  # CMYK
    max_total_ink_pct: float  # po ograniczeniu
    ink_limited_pct: float  # odsetek pikseli, w których zmniejszono C, M i Y
    max_ink_before_pct: float


def limit_ink(cmyk: np.ndarray, max_pct: int) -> tuple[np.ndarray, float, float]:
    """Zmniejsza C, M i Y proporcjonalnie tam, gdzie suma farb przekracza limit; K bez zmian.

    Zwraca (piksele, maks. suma przed, odsetek poprawionych pikseli).
    """
    values = cmyk.astype(np.float64)
    total = values.sum(axis=2)
    limit = max_pct / 100 * INK_SCALE
    over = total > limit
    before = float(total.max()) / INK_SCALE * 100 if total.size else 0.0
    if not over.any():
        return cmyk, before, 0.0
    cmy = values[..., :3]
    k = values[..., 3]
    cmy_sum = cmy.sum(axis=2)
    room = np.clip(limit - k, 0, None)
    scale = np.where(cmy_sum > 0, np.minimum(1.0, room / np.maximum(cmy_sum, 1e-9)), 1.0)
    fixed = values.copy()
    fixed[..., :3] = np.where(over[..., None], np.floor(cmy * scale[..., None]), cmy)
    return fixed.astype(np.uint8), before, float(over.mean() * 100)


def compose_cmyk(
    color: Image.Image,
    black: Image.Image,
    paper: Image.Image,
    converter: CmykConverter,
    max_ink_pct: int,
) -> CmykResult:
    """Warstwa kolorowa przez profil, limit farb, potem papier K0 i czerń K100."""
    pixels = np.asarray(converter.to_cmyk(color)).copy()
    pixels, before, fixed = limit_ink(pixels, max_ink_pct)
    pixels[np.asarray(paper) == 0] = (0, 0, 0, 0)
    pixels[np.asarray(black) == 0] = BLACK_K100
    total = pixels.astype(np.uint16).sum(axis=2)
    return CmykResult(
        image=Image.fromarray(pixels, mode="CMYK"),
        max_total_ink_pct=round(float(total.max()) / INK_SCALE * 100, 1),
        ink_limited_pct=round(fixed, 3),
        max_ink_before_pct=round(before, 1),
    )


def rgb_preview(color: Image.Image, black: Image.Image, paper: Image.Image) -> Image.Image:
    """Okładka w RGB przed konwersją (cover.png): papier biały, czerń czarna."""
    pixels = np.asarray(color.convert("RGB")).copy()
    pixels[np.asarray(paper) == 0] = (255, 255, 255)
    pixels[np.asarray(black) == 0] = (0, 0, 0)
    return Image.fromarray(pixels, mode="RGB")


# --- Gamut ---------------------------------------------------------------------------------


def _lab(rgb: Image.Image) -> np.ndarray:
    transform = ImageCms.buildTransform(
        ImageCms.createProfile("sRGB"), ImageCms.createProfile("LAB"), "RGB", "LAB"
    )
    lab = np.asarray(
        _applied(ImageCms.applyTransform(rgb.convert("RGB"), transform)), dtype=np.float64
    )
    lab[..., 0] *= 100 / 255  # L w Pillow ma zakres 0–255
    lab[..., 1:] = np.where(lab[..., 1:] > 127, lab[..., 1:] - 256, lab[..., 1:])
    return lab


def delta_e(first: Image.Image, second: Image.Image) -> np.ndarray:
    """ΔE76 (CIE Lab) piksel po pikselu."""
    return np.asarray(np.sqrt(((_lab(first) - _lab(second)) ** 2).sum(axis=2)))


def gamut_map(
    preview: Image.Image, proof: Image.Image, warn: float
) -> tuple[Image.Image, np.ndarray]:
    """Mapa zmian kolorów (cover_gamut.png): miejsca z ΔE > `warn` na różowo na wyblakłym tle."""
    mask = delta_e(preview, proof) > warn
    faded = (np.asarray(preview.convert("RGB"), dtype=np.float64) * 0.35 + 255 * 0.65).astype(
        np.uint8
    )
    faded[mask] = (255, 0, 160)
    return Image.fromarray(faded, mode="RGB"), mask


def converter_from(settings: CmykSettings) -> CmykConverter:
    return IccConverter(settings)
