"""FR-15 etap 3: tło tyłu i grzbietu z modelu, dopasowane do przodu.

Tył i grzbiet powstają razem, jednym wywołaniem, z gotowym przodem jako referencją. Prompt
narzuca horyzont i kolory lewej krawędzi przodu (z oceny modelem z wizją, uzupełnionej
próbkami pikseli). Program porównuje potem pasy poziome po obu stronach zgięcia grzbiet/przód
(ΔE w Lab) i położenie horyzontu; przekroczenie progu to ponowienie. Na końcu w pasie
`seam_band_in` po stronie grzbietu tło płynnie przechodzi w kolory lewej krawędzi przodu,
a sam przód zostaje nienaruszony.
"""

from __future__ import annotations

import io
from collections.abc import Callable
from dataclasses import dataclass, field
from itertools import pairwise
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from kdp_studio.config import CoverSettings
from kdp_studio.pipeline.cover_front import (
    CoverBudgetError,
    CoverColorError,
    model_aspect,
    reference_png,
)
from kdp_studio.pipeline.cover_geometry import CoverGeometry
from kdp_studio.pipeline.cover_vision import FrontScene
from kdp_studio.pipeline.output import write_bytes_atomic
from kdp_studio.providers.base import ImageProvider, ImageRequest, ProviderError, Usage

EDGE_STRIP_IN = 0.05  # szerokość pasa próbek przy linii zgięcia
HORIZON_MIN_DELTA_E = 15.0  # słabsza zmiana koloru w pionie to nie horyzont
SPINE_SLACK_IN = 0.25  # zapas obok grzbietu, który też ma być samym tłem
BLEND_SMOOTH_IN = 0.1  # wygładzenie kolorów krawędzi przodu w pionie przed przejściem


# --- Próbki pikseli --------------------------------------------------------------------------


def _lab(rgb: np.ndarray) -> np.ndarray:
    """sRGB (0–255) → Lab (L 0–100)."""
    data = np.asarray(rgb, dtype=np.float32).reshape(-1, 1, 3) / 255
    return np.asarray(cv2.cvtColor(data, cv2.COLOR_RGB2Lab)).reshape(np.shape(rgb))


def band_colors(strip: np.ndarray, bands: int, rows: np.ndarray | None = None) -> np.ndarray:
    """Mediana koloru w `bands` pasach poziomych pasa pikseli (H × W × 3) → bands × 3.

    `rows` (maska H): tylko te wiersze; pas bez żadnego wiersza dostaje NaN."""
    keep = np.ones(strip.shape[0], bool) if rows is None else rows
    edges = np.linspace(0, strip.shape[0], bands + 1).round().astype(int)
    out = np.full((bands, 3), np.nan)
    for index, (a, b) in enumerate(pairwise(edges)):
        band = strip[a:b][keep[a:b]]
        if band.size:
            out[index] = np.median(band.reshape(-1, 3), axis=0)
    return out


def hex_color(rgb: np.ndarray) -> str:
    r, g, b = (round(float(v)) for v in rgb)
    return f"#{r:02X}{g:02X}{b:02X}"


def pixel_horizon(strip: np.ndarray) -> float | None:
    """Wysokość najsilniejszej zmiany koloru w pionie (ułamek od góry) albo None.

    Profil to mediana koloru w każdym wierszu pasa; horyzont to wiersz, w którym kolor nad
    nim i pod nim (w oknie 4% wysokości) różni się najbardziej, o ile ΔE ≥ HORIZON_MIN_DELTA_E.
    """
    height = strip.shape[0]
    if height < 20:
        return None
    profile = _lab(np.median(strip, axis=1))  # H × 3
    window = max(2, round(height * 0.04))
    margin = max(window, round(height * 0.05))  # krawędzie spadu pomijamy
    best, best_row = 0.0, -1
    for row in range(margin, height - margin):
        above = profile[row - window : row].mean(axis=0)
        below = profile[row : row + window].mean(axis=0)
        diff = float(np.sqrt(((above - below) ** 2).sum()))
        if diff > best:
            best, best_row = diff, row
    return round(best_row / height, 3) if best >= HORIZON_MIN_DELTA_E else None


# --- Kontrola i wygładzenie styku ------------------------------------------------------------


@dataclass(frozen=True)
class SeamCheck:
    max_delta_e: float  # największa różnica pasów po obu stronach zgięcia grzbiet/przód
    horizon_front: float | None
    horizon_back: float | None
    horizon_ok: bool
    passed: bool

    @property
    def score(self) -> float:
        """Do wyboru najlepszej próby, gdy żadna nie przeszła: przesunięty horyzont to kara."""
        return self.max_delta_e + (0.0 if self.horizon_ok else 100.0)


def seam_check(
    back: np.ndarray, front: np.ndarray, strip_px: int, settings: CoverSettings
) -> SeamCheck:
    """Porównuje prawy pas tyłu z grzbietem (przy zgięciu) z lewym pasem przodu.

    Horyzont porównuje się tylko, gdy da się go wskazać po obu stronach; brak horyzontu po
    jednej stronie wychwytuje porównanie pasów.
    """
    back_strip = back[:, -strip_px:]
    front_strip = front[:, :strip_px]
    h_front, h_back = pixel_horizon(front_strip), pixel_horizon(back_strip)
    # Wiersze przy horyzoncie pomija porównanie kolorów: przesunięcie w granicach tolerancji
    # zamieniłoby w pasie niebo na ziemię. Położenie horyzontu sprawdza osobny warunek.
    height = front_strip.shape[0]
    y = np.arange(height) / height
    rows = np.ones(height, bool)
    for level in (h_front, h_back):
        if level is not None:
            rows &= np.abs(y - level) > settings.horizon_tolerance
    back_bands = band_colors(back_strip, settings.seam_bands, rows)
    front_bands = band_colors(front_strip, settings.seam_bands, rows)
    valid = ~(np.isnan(back_bands).any(axis=1) | np.isnan(front_bands).any(axis=1))
    diff = _lab(back_bands[valid]) - _lab(front_bands[valid])
    max_de = round(float(np.sqrt((diff**2).sum(axis=1)).max()), 2) if valid.any() else 0.0
    horizon_ok = (
        h_front is None or h_back is None or abs(h_front - h_back) <= settings.horizon_tolerance
    )
    passed = max_de <= settings.seam_max_delta_e and horizon_ok
    return SeamCheck(max_de, h_front, h_back, horizon_ok, passed)


def blend_seam(back: np.ndarray, front: np.ndarray, band_px: int, smooth_px: int) -> np.ndarray:
    """W ostatnich `band_px` kolumnach tło tyłu płynnie przechodzi w lewą krawędź przodu."""
    band_px = min(band_px, back.shape[1])
    if band_px <= 0:
        return back
    edge = np.median(front[:, : max(1, band_px // 4)], axis=1).astype(np.float32)  # H × 3
    kernel = max(1, smooth_px) | 1
    edge = cv2.blur(edge.reshape(-1, 1, 3), (1, kernel)).reshape(-1, 3)
    out = back.astype(np.float32).copy()
    alpha = np.linspace(0, 1, band_px + 1, dtype=np.float32)[1:]  # ostatnia kolumna = przód
    region = out[:, -band_px:]
    out[:, -band_px:] = (
        region * (1 - alpha[None, :, None]) + edge[:, None, :] * alpha[None, :, None]
    )
    return np.asarray(out.round().clip(0, 255).astype(np.uint8))


# --- Prompt ----------------------------------------------------------------------------------


def back_prompt(
    settings: CoverSettings,
    style: str,
    geometry: CoverGeometry,
    scene: FrontScene | None,
    edge: list[str],
    horizon: float | None,
) -> str:
    """Prompt tyłu z grzbietem: horyzont, kolory lewej krawędzi przodu i strefy kompozycji."""
    width = geometry.folds_x[1]
    spine_pct = round((geometry.spine_in + SPINE_SLACK_IN) / width * 100)
    margin_pct = max(1, round(settings.key_margin_in / width * 100))
    level = scene.horizon if scene is not None and scene.horizon is not None else horizon
    if level is not None:
        horizon_text = (
            f"Put the horizon at exactly {round(level * 100)}% of the image height from the "
            "top, the same height as on the front cover."
        )
    else:
        horizon_text = "The front cover has no horizon line; continue its background as it is."
    colors = scene.band_colors if scene is not None and scene.band_colors else edge
    if scene is not None and scene.background:
        horizon_text = f"Background of the front cover: {scene.background}. {horizon_text}"
    text = " ".join(settings.back_prompt.split()).format(
        horizon=horizon_text,
        colors=", ".join(colors),
        spine_pct=spine_pct,
        margin_pct=margin_pct,
    )
    return f"{text}\nStyle of the book: {style}."


# --- Malowanie --------------------------------------------------------------------------------


@dataclass
class BackPainter:
    """Tył z grzbietem z modelu: ponowienia przy błędach niekrytycznych i nieudanym styku.

    `analyze(przód) -> FrontScene` to ocena przodu modelem z wizją (None: same próbki pikseli).
    """

    provider: ImageProvider
    quality: str
    style: str
    settings: CoverSettings
    geometry: CoverGeometry
    raw_dir: Path
    analyze: Callable[[Image.Image], FrontScene] | None = None
    over_budget: Callable[[], bool] | None = None
    spend: Callable[[Usage], None] | None = None
    attempts: int = 0
    usage: Usage = field(default_factory=Usage)
    raw_files: list[Path] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    aspect: str | None = None
    prompt: str | None = None
    scene: FrontScene | None = None
    scene_error: str | None = None
    edge_colors: list[str] = field(default_factory=list)
    seams: list[SeamCheck] = field(default_factory=list)
    chosen: int | None = None  # numer użytej próby (1…)

    def _check_budget(self) -> None:
        if self.over_budget is not None and self.over_budget():
            raise CoverBudgetError("przekroczony limit kosztu przed malowaniem tyłu okładki")

    def __call__(self, front: Image.Image) -> Image.Image:
        """`front`: gotowy przód ze spadem (RGB, bez tytułu). Zwraca tył z grzbietem (RGB)."""
        geometry, settings = self.geometry, self.settings
        left, top, right, bottom = geometry.px((0.0, 0.0, geometry.folds_x[1], geometry.size_in[1]))
        size = (right - left, bottom - top)
        front_px = np.asarray(front.convert("RGB"))
        strip_px = max(2, round(EDGE_STRIP_IN * geometry.dpi))
        edge = band_colors(front_px[:, :strip_px], settings.seam_bands)
        self.edge_colors = [hex_color(c) for c in edge]
        if self.analyze is not None:
            self._check_budget()
            try:
                self.scene = self.analyze(front)
            except ProviderError as e:
                if e.fatal:
                    raise
                self.scene_error = str(e)
                self.warnings.append(
                    f"ocena przodu modelem z wizją nie powiodła się ({e}); "
                    "tył według próbek pikseli"
                )
        self.aspect = model_aspect(size, self.provider.supported_aspects())
        self.prompt = back_prompt(
            settings,
            self.style,
            geometry,
            self.scene,
            self.edge_colors,
            pixel_horizon(front_px[:, :strip_px]),
        )
        reference = reference_png(front, front_aspect(front.size))
        best: tuple[float, np.ndarray, int] | None = None
        for _ in range(1 + settings.max_retries):
            self._check_budget()
            self.attempts += 1
            try:
                result = self.provider.generate(
                    ImageRequest(
                        prompt=self.prompt,
                        aspect=self.aspect,
                        quality=self.quality,
                        reference_image=reference,
                    )
                )
            except ProviderError as e:
                if e.fatal:
                    raise
                self.errors.append(str(e))
                continue
            self.usage += result.usage
            if self.spend is not None:
                self.spend(result.usage)
            path = self.raw_dir / f"back_try{self.attempts}.png"
            write_bytes_atomic(path, result.png_bytes)
            self.raw_files.append(path)
            try:
                with Image.open(io.BytesIO(result.png_bytes)) as img:
                    painted = img.convert("RGB").resize(size, Image.Resampling.LANCZOS)
            except OSError as e:
                self.errors.append(f"niepoprawny obraz z modelu: {e}")
                continue
            back = np.asarray(painted)
            seam = seam_check(back, front_px, strip_px, settings)
            self.seams.append(seam)
            if best is None or seam.score < best[0]:
                best = (seam.score, back, self.attempts)
            if seam.passed:
                break
        if best is None:
            raise CoverColorError(
                "model nie namalował tyłu okładki: " + ("; ".join(self.errors) or "brak wyniku")
            )
        _, back, self.chosen = best
        if not any(s.passed for s in self.seams):
            worst = min(self.seams, key=lambda s: s.score)
            self.warnings.append(
                f"styk grzbietu z przodem po {self.attempts} próbach: ΔE {worst.max_delta_e:g} "
                f"(próg {settings.seam_max_delta_e:g}); przejście wygładzone, obejrzyj cover.png"
            )
        band = round(settings.seam_band_in * geometry.dpi)
        smooth = round(BLEND_SMOOTH_IN * geometry.dpi)
        return Image.fromarray(blend_seam(back, front_px, band, smooth), mode="RGB")


def front_aspect(size: tuple[int, int]) -> str:
    """Proporcje referencji przodu: jej własne, w liczbach całkowitych."""
    width, height = size
    return f"{width}:{height}"
