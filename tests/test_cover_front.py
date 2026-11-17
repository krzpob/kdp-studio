"""FR-15 etap 2: kolorowanie przodu modelem, kontury 300 DPI, tytuł i czytelność."""

from __future__ import annotations

import io
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from PIL import Image, ImageDraw

from kdp_studio import cli
from kdp_studio.cli import ExitCode, main
from kdp_studio.config import AppConfig, KdpCover
from kdp_studio.models import BookSpec
from kdp_studio.pipeline.cmyk import NaiveConverter
from kdp_studio.pipeline.cover import (
    CoverLayers,
    apply_front_color,
    build_cover,
    contour_match,
    contrast_ratio,
    front_sketch,
    place_front_art,
)
from kdp_studio.pipeline.cover_front import (
    CoverBudgetError,
    CoverColorError,
    FrontColorizer,
    color_prompt,
    model_aspect,
    reference_png,
)
from kdp_studio.pipeline.cover_geometry import CoverGeometry
from kdp_studio.providers.base import ImageRequest, ImageResult, ProviderError, Usage
from tests.conftest import FAKE_PRICES
from tests.test_cli import fake_text_provider  # noqa: F401  (autouse: fałszywi dostawcy)

GENERATE = ["generate", "--theme", "Dinozaury", "--age", "przedszkole", "--style", "kawaii"]
BOOK = Path("output/dinozaury_przedszkole_kawaii_letter")
ARG = str(BOOK)


def _geometry(trim: tuple[float, float] = (8.5, 8.5), pages: int = 62) -> CoverGeometry:
    return CoverGeometry(
        trim_in=trim, pages_in_book=pages, kdp=KdpCover(), key_margin_in=0.375, dpi=100
    )


def _page(path: Path) -> Path:
    img = Image.new("L", (600, 600), 255)
    draw = ImageDraw.Draw(img)
    draw.ellipse((100, 100, 500, 500), outline=0, width=10)
    draw.line((150, 300, 450, 300), fill=0, width=10)
    img.save(path)
    return path


def _tinted(sketch: Image.Image) -> Image.Image:
    """„Model”, który koloruje tło na niebiesko i zostawia kontury na miejscu."""
    gray = np.asarray(sketch.convert("L"), dtype=np.float64)[..., None] / 255
    sky = np.array([110.0, 170.0, 240.0])
    return Image.fromarray((gray * sky).astype(np.uint8), mode="RGB")


def _png(img: Image.Image) -> bytes:
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    return buffer.getvalue()


@dataclass
class ColoringProvider:
    """Odpowiada pokolorowaną referencją; `fail` i `junk` symulują błędy."""

    fail: list[ProviderError | None] = field(default_factory=list)
    junk: bool = False
    name: str = "fake"
    model: str = "fake-image"
    requests: list[ImageRequest] = field(default_factory=list)

    def supported_aspects(self) -> list[str]:
        return ["1:1", "3:4"]

    def generate(self, req: ImageRequest) -> ImageResult:
        self.requests.append(req)
        error = self.fail[len(self.requests) - 1] if len(self.requests) <= len(self.fail) else None
        if error is not None:
            raise error
        usage = Usage(input_tokens=10, output_tokens=100)
        if self.junk:
            return ImageResult(b"not a png", 1, 1, usage)
        assert req.reference_image is not None
        with Image.open(io.BytesIO(req.reference_image)) as ref:
            colored = _tinted(ref)
        return ImageResult(_png(colored), colored.width, colored.height, usage)


# --- Kolorowanie -------------------------------------------------------------------------


def test_model_aspect_picks_closest() -> None:
    aspects = ["1:1", "3:4", "4:3"]
    assert model_aspect((863, 875), aspects) == "1:1"  # kwadrat ze spadem
    assert model_aspect((863, 1125), aspects) == "3:4"  # letter ze spadem


def test_reference_png_has_model_aspect() -> None:
    data = reference_png(Image.new("RGB", (863, 1125), "white"), "3:4")
    with Image.open(io.BytesIO(data)) as img:
        assert img.size == (1024, 1365)


def test_color_prompt_has_style_and_no_text(repo_config: AppConfig) -> None:
    spec = BookSpec(
        theme="T", age="przedszkole", style="kawaii", format="square", pages=3,
        front_matter_pages=2,
    )  # fmt: skip
    prompt = color_prompt(spec, repo_config)
    assert "Keep every black outline exactly where it is" in prompt
    assert "No text, no letters, no title" in prompt
    assert prompt.splitlines()[-1].startswith("Style of the book: ")


def _colorizer(
    tmp_path: Path, repo_config: AppConfig, provider: ColoringProvider, **kwargs: Any
) -> FrontColorizer:
    return FrontColorizer(
        provider=provider,
        quality="low",
        prompt="color it",
        settings=repo_config.settings.cover,
        raw_dir=tmp_path / "raw",
        **kwargs,
    )


def test_colorizer_sends_reference_and_keeps_raw(tmp_path: Path, repo_config: AppConfig) -> None:
    provider = ColoringProvider()
    spent: list[Usage] = []
    colorizer = _colorizer(tmp_path, repo_config, provider, spend=spent.append)
    result = colorizer(Image.new("RGB", (863, 875), "white"))
    assert result.mode == "RGB"
    (req,) = provider.requests
    assert (req.aspect, req.quality, req.prompt) == ("1:1", "low", "color it")
    assert req.reference_image is not None
    assert (tmp_path / "raw" / "front_sketch.png").is_file()
    assert [p.name for p in colorizer.raw_files] == ["front_color_try1.png"]
    assert spent == [Usage(input_tokens=10, output_tokens=100)]
    assert colorizer.attempts == 1


def test_colorizer_retries_non_fatal_errors(tmp_path: Path, repo_config: AppConfig) -> None:
    provider = ColoringProvider(fail=[ProviderError("moderacja", fatal=False)])
    colorizer = _colorizer(tmp_path, repo_config, provider)
    colorizer(Image.new("RGB", (100, 100), "white"))
    assert colorizer.attempts == 2 and colorizer.errors == ["moderacja"]


def test_colorizer_gives_up(tmp_path: Path, repo_config: AppConfig) -> None:
    provider = ColoringProvider(fail=[ProviderError("moderacja", fatal=False)] * 3)
    with pytest.raises(CoverColorError, match="moderacja"):
        _colorizer(tmp_path, repo_config, provider)(Image.new("RGB", (100, 100), "white"))
    assert len(provider.requests) == 3


def test_colorizer_fatal_error_propagates(tmp_path: Path, repo_config: AppConfig) -> None:
    provider = ColoringProvider(fail=[ProviderError("zły klucz", fatal=True)])
    with pytest.raises(ProviderError, match="zły klucz"):
        _colorizer(tmp_path, repo_config, provider)(Image.new("RGB", (100, 100), "white"))


def test_colorizer_stops_over_budget(tmp_path: Path, repo_config: AppConfig) -> None:
    provider = ColoringProvider(junk=True)
    spent: list[Usage] = []
    colorizer = _colorizer(
        tmp_path, repo_config, provider, spend=spent.append, over_budget=lambda: bool(spent)
    )
    with pytest.raises(CoverBudgetError):
        colorizer(Image.new("RGB", (100, 100), "white"))
    assert len(provider.requests) == 1


# --- Kontury, tytuł, czytelność --------------------------------------------------------------


def test_contour_match_detects_shift() -> None:
    art = np.zeros((100, 100), dtype=bool)
    art[50, 10:90] = True
    same = Image.new("L", (100, 100), 255)
    ImageDraw.Draw(same).line((10, 50, 89, 50), fill=0, width=1)
    shifted = Image.new("L", (100, 100), 255)
    ImageDraw.Draw(shifted).line((10, 70, 89, 70), fill=0, width=1)
    assert contour_match(art, same, 2) == 1.0
    assert contour_match(art, shifted, 2) == 0.0


def _layers_with_art(repo_config: AppConfig, tmp_path: Path) -> tuple[CoverLayers, CoverGeometry]:
    geometry = _geometry()
    layers = CoverLayers.blank(geometry.size_px)
    with Image.open(_page(tmp_path / "p.png")) as page:
        place_front_art(layers, geometry, repo_config.settings.cover, page.convert("L"))
    return layers, geometry


def test_aligned_color_keeps_k100_contours(repo_config: AppConfig, tmp_path: Path) -> None:
    layers, geometry = _layers_with_art(repo_config, tmp_path)
    colored = _tinted(front_sketch(layers, geometry))
    match, overlay = apply_front_color(layers, geometry, repo_config.settings.cover, colored)
    assert match >= 0.85 and overlay
    rect = geometry.px(geometry.front_panel)
    assert (np.asarray(layers.black.crop(rect)) == 0).any()
    assert layers.color.getpixel((rect[0] + 2, rect[1] + 2)) != (255, 255, 255)


def test_shifted_color_drops_overlay(repo_config: AppConfig, tmp_path: Path) -> None:
    layers, geometry = _layers_with_art(repo_config, tmp_path)
    sketch = front_sketch(layers, geometry)
    shifted = _tinted(sketch).transform(sketch.size, Image.Transform.AFFINE, (1, 0, 40, 0, 1, 40))
    match, overlay = apply_front_color(layers, geometry, repo_config.settings.cover, shifted)
    assert match < 0.85 and not overlay
    rect = geometry.px(geometry.front_panel)
    assert (np.asarray(layers.black.crop(rect)) == 255).all()


def test_contrast_ratio() -> None:
    assert contrast_ratio(np.zeros(3), np.full(3, 255.0)) == pytest.approx(21, abs=0.01)
    assert contrast_ratio(np.full(3, 255.0), np.full(3, 255.0)) == pytest.approx(1)


def test_title_has_colored_fill_and_black_outline(repo_config: AppConfig, tmp_path: Path) -> None:
    page = _page(tmp_path / "p.png")
    build = build_cover(
        _geometry(), repo_config.settings.cover, page, [page] * 3, "Dino Fun", "Kids",
        colorize=_tinted,
    )  # fmt: skip
    assert build.colorized and build.contours_overlay
    left, top, right, bottom = build.placements["title"]
    black = np.asarray(build.layers.black)[top:bottom, left:right]
    color = np.asarray(build.layers.color)[top:bottom, left:right]
    fill = repo_config.settings.cover.title_fill_rgb
    letters = (black == 255) & np.all(color == fill, axis=2)
    assert letters.any() and (black == 0).any()
    assert build.title_contrast >= 3
    assert build.title_thumb_px > 0


def test_readability_warnings(repo_config: AppConfig, tmp_path: Path) -> None:
    settings = repo_config.settings.cover.model_copy(
        update={"title_font_pt": 10, "thumbnail_min_text_px": 20, "title_min_contrast": 25}
    )
    page = _page(tmp_path / "p.png")
    build = build_cover(_geometry(), settings, page, [page] * 3, "Dino", "")
    assert any("w miniaturze" in w for w in build.warnings)
    assert any("słaby kontrast" in w for w in build.warnings)


# --- CLI ----------------------------------------------------------------------------------


@pytest.fixture
def coloring(monkeypatch: pytest.MonkeyPatch) -> ColoringProvider:
    monkeypatch.setattr(cli, "cmyk_converter", lambda settings: NaiveConverter())
    provider = ColoringProvider()
    assert main([*GENERATE, "--pages", "6"]) == ExitCode.OK
    monkeypatch.setattr(cli, "create_image_provider", lambda name, model: provider)
    return provider


def _manifest() -> dict[str, Any]:
    data = json.loads((BOOK / "manifest.json").read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def test_cover_colorizes_front(
    coloring: ColoringProvider, capsys: pytest.CaptureFixture[str]
) -> None:
    before = _manifest()["cost_usd"]
    capsys.readouterr()
    assert main(["cover", ARG, "--image-quality", "low"]) == ExitCode.OK
    out = capsys.readouterr().out
    assert "Koloruję przód (fake, fake-image, jakość low, limit $5.00)" in out
    assert "Przód pokolorowany (1 próba, zgodność konturów 100%, nałożone kontury 300 DPI)" in out
    assert "Tytuł w miniaturze 160 px: litery " in out
    (req,) = coloring.requests
    assert req.reference_image is not None and req.aspect == "3:4"
    data = _manifest()
    cover = data["cover"]
    front = cover["front"]
    assert (front["colorized"], front["attempts"], front["contours_overlay"]) == (True, 1, True)
    assert front["raw_files"] == ["cover/raw/front_color_try1.png"]
    assert front["quality"] == "low" and front["aspect"] == "3:4"
    price = FAKE_PRICES["fake-image"]
    expected = (10 * price["input_per_1m"] + 100 * price["output_per_1m"]) / 1e6
    assert cover["cost_usd"] == pytest.approx(expected)
    assert data["cost_usd"] == pytest.approx(before + expected)
    assert (BOOK / "cover" / "raw" / "front_sketch.png").is_file()


def test_no_color_makes_a_sketch_without_api(
    coloring: ColoringProvider, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def no_provider(name: str, model: str) -> ColoringProvider:
        raise AssertionError("--no-color nie tworzy dostawcy obrazu")

    monkeypatch.setattr(cli, "create_image_provider", no_provider)
    assert main(["cover", ARG, "--no-color"]) == ExitCode.OK
    assert "Przód: szkic bez koloru (--no-color)." in capsys.readouterr().out
    cover = _manifest()["cover"]
    assert cover["front"]["colorized"] is False and cover["cost_usd"] == 0


def test_cover_color_failure_exits_2(
    coloring: ColoringProvider, capsys: pytest.CaptureFixture[str]
) -> None:
    coloring.fail = [ProviderError("moderacja", fatal=False)] * 3
    assert main(["cover", ARG]) == ExitCode.PARTIAL
    assert "model nie pokolorował przodu: moderacja" in capsys.readouterr().err
    cover = _manifest()["cover"]
    assert cover["status"] == "failed" and cover["files"] is None
    assert cover["front"]["attempts"] == 3
    assert not (BOOK / "cover" / "cover.pdf").exists()


def test_cover_fatal_error_exits_4(coloring: ColoringProvider) -> None:
    coloring.fail = [ProviderError("brak środków", fatal=True)]
    assert main(["cover", ARG]) == ExitCode.PROVIDER_ERROR
    assert _manifest()["cover"]["status"] == "failed"


def test_cover_budget_exits_3(coloring: ColoringProvider) -> None:
    coloring.junk = True
    assert main(["cover", ARG, "--max-cost", "0.001"]) == ExitCode.BUDGET_EXCEEDED
    assert len(coloring.requests) == 1
    assert "limit kosztu" in _manifest()["cover"]["error"]
