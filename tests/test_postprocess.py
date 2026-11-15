from __future__ import annotations

import io
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from kdp_studio.config import AppConfig, PostprocessParams
from kdp_studio.models import pages_in_book
from kdp_studio.pipeline.postprocess import (
    Despeckle,
    Grayscale,
    PageContext,
    PageGeometry,
    PagePostprocessor,
    PostprocessError,
    Threshold,
    page_margin_in,
    save_page_png,
    verify_page,
)
from kdp_studio.providers.fake import make_png

FIXTURE = Path(__file__).parent / "fixtures" / "line_art_bear.png"  # prawdziwy wynik modelu


def _params(config: AppConfig, **overrides: object) -> PostprocessParams:
    return config.ages["przedszkole"].postprocess.model_copy(update=overrides)


def _ctx(config: AppConfig, tmp_path: Path, **overrides: object) -> PageContext:
    geometry = PageGeometry.for_format(config.formats["letter"], 0.5)
    return PageContext(geometry, _params(config, **overrides), tmp_path / "svg" / "p.svg")


def _process(config: AppConfig, tmp_path: Path, png: bytes, fmt: str = "letter") -> Path:
    raw = tmp_path / "raw" / "page_01.png"
    raw.parent.mkdir(parents=True, exist_ok=True)
    raw.write_bytes(png)
    geometry = PageGeometry.for_format(config.formats[fmt], 0.5)
    pp = PagePostprocessor(tmp_path, geometry, _params(config))
    return pp.process(raw, "page_01").page


# --- Marginesy (FR-06, §7.4) ----------------------------------------------------------


@pytest.mark.parametrize(
    ("pages", "book_pages", "gutter", "margin"),
    [(30, 62, 0.375, 0.5), (100, 202, 0.5, 0.5), (200, 402, 0.625, 0.625)],
)
def test_margin_table_from_spec(
    repo_config: AppConfig, pages: int, book_pages: int, gutter: float, margin: float
) -> None:
    margins = repo_config.settings.kdp_margins
    assert pages_in_book(pages, 2) == book_pages
    assert margins.gutter_in(book_pages) == gutter
    assert page_margin_in(repo_config.formats["letter"], margins, book_pages) == margin


def test_margin_above_table_is_an_error(repo_config: AppConfig) -> None:
    with pytest.raises(ValueError, match="829 stron przekracza tabelę marginesów KDP"):
        page_margin_in(repo_config.formats["letter"], repo_config.settings.kdp_margins, 829)


def test_geometry_fits_and_centers(repo_config: AppConfig) -> None:
    geometry = PageGeometry.for_format(repo_config.formats["letter"], 0.5)
    assert geometry.margin_px == 150
    assert geometry.content_box == (150, 150, 2400, 3150)
    scale, dx, dy = geometry.fit(1152, 1536)  # 3:4 wypełnia obszar 2250×3000
    assert (scale, dx, dy) == pytest.approx((2250 / 1152, 150, 150))
    scale, dx, dy = geometry.fit(1000, 1000)  # kwadrat na stronie pionowej: wyśrodkowany w pionie
    assert scale == pytest.approx(2.25)
    assert dx == pytest.approx(150)
    assert dy == pytest.approx(150 + (3000 - 2250) / 2)


# --- Kroki ---------------------------------------------------------------------------


def test_grayscale_flattens_transparency_on_white(repo_config: AppConfig, tmp_path: Path) -> None:
    rgba = Image.new("RGBA", (4, 4), (0, 0, 0, 0))  # przezroczysta czerń
    rgba.putpixel((0, 0), (0, 0, 0, 255))
    gray = Grayscale().process(rgba, _ctx(repo_config, tmp_path))
    assert gray.mode == "L"
    assert gray.getpixel((0, 0)) == 0
    assert gray.getpixel((3, 3)) == 255


@pytest.mark.parametrize(
    ("threshold", "expected"), [("otsu", [0, 0, 255, 255]), (80, [0, 255, 255, 255])]
)
def test_threshold(
    repo_config: AppConfig, tmp_path: Path, threshold: str | int, expected: list[int]
) -> None:
    img = Image.fromarray(np.array([[10, 90, 200, 250]], dtype=np.uint8), mode="L")
    out = Threshold().process(img, _ctx(repo_config, tmp_path, threshold=threshold))
    assert list(np.asarray(out)[0]) == expected


def test_despeckle_removes_small_specks_only(repo_config: AppConfig, tmp_path: Path) -> None:
    pixels = np.full((40, 40), 255, dtype=np.uint8)
    pixels[5:15, 5:15] = 0  # 100 px: zostaje
    pixels[30:32, 30:32] = 0  # 4 px: plamka
    pixels[20, 35] = 0  # 1 px: plamka
    out = Despeckle().process(
        Image.fromarray(pixels, mode="L"), _ctx(repo_config, tmp_path, min_speck_area=24)
    )
    result = np.asarray(out)
    assert (result[5:15, 5:15] == 0).all()
    assert (result == 0).sum() == 100


# --- Cała strona ---------------------------------------------------------------------


def _black_bbox(path: Path) -> tuple[int, int, int, int]:
    pixels = np.asarray(Image.open(path))
    ys, xs = np.nonzero(pixels == 0)
    return int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())


def test_real_line_art_becomes_print_ready_page(repo_config: AppConfig, tmp_path: Path) -> None:
    page = _process(repo_config, tmp_path, FIXTURE.read_bytes())
    geometry = PageGeometry.for_format(repo_config.formats["letter"], 0.5)
    assert verify_page(page, geometry) == []

    with Image.open(page) as img:
        assert img.size == (2550, 3300)
        assert img.mode == "L"
        assert img.info["dpi"] == pytest.approx((300, 300), abs=0.5)
        values = set(np.unique(np.asarray(img)).tolist())
    assert values == {0, 255}
    left, top, right, bottom = _black_bbox(page)
    assert left >= 150 and top >= 150 and right < 2400 and bottom < 3150

    svg = (tmp_path / "svg" / "page_01.svg").read_text(encoding="utf-8")
    assert svg.startswith('<svg xmlns="http://www.w3.org/2000/svg" version="1.1" width="576"')
    assert 'fill-rule="evenodd"' in svg


def test_square_page_and_centering(repo_config: AppConfig, tmp_path: Path) -> None:
    page = _process(repo_config, tmp_path, make_png(96, 128, frame=True), fmt="square")
    assert verify_page(page, PageGeometry.for_format(repo_config.formats["square"], 0.5)) == []
    left, top, right, bottom = _black_bbox(page)
    assert abs(left - (2549 - right)) <= 2  # wyśrodkowana poziomo
    assert abs(top - (2549 - bottom)) <= 2  # i pionowo


def test_blank_image_is_rejected(repo_config: AppConfig, tmp_path: Path) -> None:
    with pytest.raises(PostprocessError, match="pusta po progowaniu"):
        _process(repo_config, tmp_path, make_png(96, 128))


def test_unreadable_raw_is_rejected(repo_config: AppConfig, tmp_path: Path) -> None:
    with pytest.raises(PostprocessError, match="nie można odczytać"):
        _process(repo_config, tmp_path, b"not an image")


# --- Kontrola NFR-07 -----------------------------------------------------------------


def _page(tmp_path: Path, pixels: np.ndarray, dpi: int | None = 300, mode: str = "L") -> Path:
    path = tmp_path / "check.png"
    img = Image.fromarray(pixels, mode="L").convert(mode)
    if dpi is None:
        buffer = io.BytesIO()
        img.save(buffer, format="PNG")
        path.write_bytes(buffer.getvalue())
    else:
        save_page_png(img, path, dpi)
    return path


GEOMETRY = PageGeometry(page_px=(100, 120), dpi=300, margin_in=0.05)  # margines 15 px


def _ok_pixels() -> np.ndarray:
    pixels = np.full((120, 100), 255, dtype=np.uint8)
    pixels[40:60, 40:60] = 0
    return pixels


def test_verify_accepts_valid_page(tmp_path: Path) -> None:
    assert verify_page(_page(tmp_path, _ok_pixels()), GEOMETRY) == []


@pytest.mark.parametrize(
    ("change", "problem"),
    [
        ("gray", "wartości pikseli inne niż 0 i 255"),
        ("margin", "czarne piksele poza obszarem treści"),
        ("blank", "strona nie ma czarnych pikseli"),
        ("size", "wymiary"),
        ("dpi", "DPI"),
        ("rgb", "tryb RGB"),
    ],
)
def test_verify_reports_problems(tmp_path: Path, change: str, problem: str) -> None:
    pixels = _ok_pixels()
    kwargs: dict[str, object] = {}
    if change == "gray":
        pixels[45, 45] = 128
    elif change == "margin":
        pixels[5, 50] = 0
    elif change == "blank":
        pixels[:] = 255
    elif change == "size":
        pixels = pixels[:110]
    elif change == "dpi":
        kwargs["dpi"] = None
    elif change == "rgb":
        kwargs["mode"] = "RGB"
    problems = verify_page(_page(tmp_path, pixels, **kwargs), GEOMETRY)  # type: ignore[arg-type]
    assert any(problem in p for p in problems), problems
