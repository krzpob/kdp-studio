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


def color_prompt(spec: BookSpec, config: AppConfig) -> str:
    """Prompt kolorowania: polecenie z `cover.color_prompt` i styl książki."""
    style = book_style(spec, config)
    return f"{' '.join(config.settings.cover.color_prompt.split())}\nStyle of the book: {style}."


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
    aspect: str | None = None

    def __call__(self, sketch: Image.Image) -> Image.Image:
        self.aspect = model_aspect(sketch.size, self.provider.supported_aspects())
        reference = reference_png(sketch, self.aspect)
        write_bytes_atomic(self.raw_dir / "front_sketch.png", reference)
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
                    return img.convert("RGB")
            except OSError as e:
                self.errors.append(f"niepoprawny obraz z modelu: {e}")
        raise CoverColorError(
            "model nie pokolorował przodu: " + ("; ".join(self.errors) or "brak wyniku")
        )
