"""FR-15 etap 2: kolorowanie szkicu przodu modelem obrazu z obrazem referencyjnym.

Program wysyła szkic przodu (kontury wybranej strony, pusty pas na tytuł) jako
`reference_image`, w proporcjach obsługiwanych przez dostawcę najbliższych przodowi
ze spadem. Wynik wraca w rozdzielczości modelu (ok. 1–1.5k px); `cover.apply_front_color`
skaluje go do 300 DPI i nakłada ostre kontury. Model nigdy nie rysuje tekstu.
"""

from __future__ import annotations

import io
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from kdp_studio.config import AppConfig, CoverSettings
from kdp_studio.models import BookSpec
from kdp_studio.pipeline.cover import CoverError
from kdp_studio.pipeline.output import write_bytes_atomic
from kdp_studio.providers.base import ImageProvider, ImageRequest, ProviderError, Usage

REFERENCE_WIDTH = 1024  # szerokość szkicu wysyłanego do modelu


class CoverColorError(CoverError):
    """Model nie pokolorował przodu po wszystkich próbach (kod wyjścia 2)."""


class CoverBudgetError(CoverError):
    """Limit kosztu nie pozwala na kolejną próbę (kod wyjścia 3)."""


def book_style(spec: BookSpec, config: AppConfig) -> str:
    """Fragment promptu stylu książki w jednej linii, bez kropki na końcu."""
    return " ".join(config.styles[spec.style].prompt_fragment.split()).rstrip(" .")


def color_prompt(spec: BookSpec, config: AppConfig, scene: str | None = None) -> str:
    """Prompt kolorowania: polecenie z `cover.color_prompt`, styl książki i scena strony.

    Same kontury nie mówią, czy brzeg jest pod śniegiem, czy to plaża: bez sceny model
    pokolorował zimową stronę („snowy shore, winter waves, ice”) jak letnią plażę. Tytułu
    książki prompt nie zawiera: z linią „Book title” model dopisał go nad rysunkiem, mimo
    zakazu tekstu.
    """
    lines = [" ".join(config.settings.cover.color_prompt.split())]
    lines.append(f"Style of the book: {book_style(spec, config)}.")
    if scene:
        lines.append(
            f"The picture shows: {scene.strip().rstrip('.')}. Choose colors that fit this "
            "description (place, season, weather, time of day), not a different setting."
        )
    return "\n".join(lines)


TITLE_BAND_CHECK_PX = 800  # szerokość, przy której liczy się krawędzie w pasie tytułu
TITLE_BAND_GAP = 0.02  # odstęp pasa od góry rysunku (ułamek wysokości)


def title_band_edges(sketch: Image.Image, colored: Image.Image) -> float:
    """Udział pikseli krawędzi (Canny) w obrazie modelu nad rysunkiem szkicu, czyli w pasie,
    który ma zostać spokojnym tłem pod tytuł programu. Napis z modelu daje ok. 7%, gładkie
    niebo ok. 0,2% (próby z 17.11). 0, gdy szkic nie ma pustego pasu u góry."""
    size = (TITLE_BAND_CHECK_PX, round(TITLE_BAND_CHECK_PX * sketch.height / sketch.width))
    ink = np.asarray(sketch.convert("L").resize(size, Image.Resampling.BILINEAR)) < 128
    rows = np.nonzero(ink.any(axis=1))[0]
    band = (rows.min() if len(rows) else size[1]) - round(TITLE_BAND_GAP * size[1])
    if band <= 0:
        return 0.0
    gray = np.asarray(colored.convert("L").resize(size, Image.Resampling.BILINEAR))
    edges = cv2.Canny(gray, 80, 160)
    return round(float((edges[:band] > 0).mean()), 4)


def model_aspect(size: tuple[int, int], aspects: list[str]) -> str:
    """Proporcje dostawcy najbliższe proporcjom przodu (np. 1:1 dla kwadratu, 3:4 dla letter)."""

    def ratio(aspect: str) -> float:
        width, height = aspect.split(":")
        return float(width) / float(height)

    target = size[0] / size[1]
    return min(aspects, key=lambda a: abs(ratio(a) - target) / target)


def reference_png(sketch: Image.Image, aspect: str) -> bytes:
    """Szkic rozciągnięty do proporcji modelu; wynik modelu rozciąga się z powrotem do przodu,
    więc położenie konturów się zgadza."""
    width, height = (float(v) for v in aspect.split(":"))
    size = (REFERENCE_WIDTH, round(REFERENCE_WIDTH * height / width))
    buffer = io.BytesIO()
    sketch.convert("RGB").resize(size, Image.Resampling.LANCZOS).save(buffer, format="PNG")
    return buffer.getvalue()


@dataclass
class FrontColorizer:
    """Wywołanie `colorize` dla `cover.build_cover`; zapisuje próby w `raw_dir`."""

    provider: ImageProvider
    quality: str
    prompt: str
    settings: CoverSettings
    raw_dir: Path
    over_budget: Callable[[], bool] | None = None
    spend: Callable[[Usage], None] | None = None  # koszt każdej próby od razu do licznika
    attempts: int = 0
    usage: Usage = field(default_factory=Usage)
    raw_files: list[Path] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    aspect: str | None = None
    band_edges: list[float] = field(default_factory=list)  # krawędzie w pasie tytułu, próby

    def __call__(self, sketch: Image.Image) -> Image.Image:
        self.aspect = model_aspect(sketch.size, self.provider.supported_aspects())
        reference = reference_png(sketch, self.aspect)
        write_bytes_atomic(self.raw_dir / "front_sketch.png", reference)
        best: tuple[float, Image.Image] | None = None
        limit = self.settings.title_band_max_edges
        for _ in range(1 + self.settings.max_retries):
            if self.over_budget is not None and self.over_budget():
                raise CoverBudgetError("przekroczony limit kosztu przed kolorowaniem przodu")
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
            path = self.raw_dir / f"front_color_try{self.attempts}.png"
            write_bytes_atomic(path, result.png_bytes)
            self.raw_files.append(path)
            try:
                with Image.open(io.BytesIO(result.png_bytes)) as img:
                    colored = img.convert("RGB")
            except OSError as e:
                self.errors.append(f"niepoprawny obraz z modelu: {e}")
                continue
            edges = title_band_edges(sketch, colored)
            self.band_edges.append(edges)
            if best is None or edges < best[0]:
                best = (edges, colored)
            if edges <= limit:
                return colored
            self.errors.append(
                f"próba {self.attempts}: napis albo obiekt w pasie tytułu (krawędzie "
                f"{edges:.1%}, próg {limit:.1%})"
            )
        if best is None:
            raise CoverColorError(
                "model nie pokolorował przodu: " + ("; ".join(self.errors) or "brak wyniku")
            )
        self.warnings.append(
            f"w pasie tytułu przodu zostało coś z modelu (krawędzie {best[0]:.1%} po "
            f"{self.attempts} próbach); tytuł programu może na to nachodzić, obejrzyj cover.png"
        )
        return best[1]
