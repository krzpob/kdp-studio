"""FR-15 (etap 1): geometria okładki, szablon KDP, układ, CMYK, PDF i komenda `cover`."""

from __future__ import annotations

import json
import re
import shutil
import zlib
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from PIL import Image, ImageCms, ImageDraw

from kdp_studio import cli
from kdp_studio.cli import ExitCode, main
from kdp_studio.config import AppConfig, CmykSettings, KdpCover
from kdp_studio.pipeline.cmyk import (
    BLACK_K100,
    CmykError,
    IccConverter,
    NaiveConverter,
    compose_cmyk,
    delta_e,
    gamut_map,
    limit_ink,
    rgb_preview,
)
from kdp_studio.pipeline.cover import (
    CoverBuild,
    CoverError,
    CoverLayers,
    build_cover,
    check_placements,
    front_crop,
    line_width_px,
    preview,
    thumbnail_grid,
)
from kdp_studio.pipeline.cover_geometry import (
    CoverGeometry,
    check_template_name,
    compare_template,
    measure_template,
)
from kdp_studio.pipeline.pdf import cmyk_pdf
from kdp_studio.providers.base import ProviderError
from kdp_studio.providers.fake import FakeImageProvider, FakeVisionProvider
from tests.conftest import CoverVision
from tests.test_cli import fake_text_provider  # noqa: F401  (autouse: fałszywi dostawcy)

TEMPLATES = Path(__file__).parent / "fixtures" / "kdp_templates"
SQUARE = TEMPLATES / "PAPERBACK_8.500x8.500_104_BW_WHITE_en_US.jpg"
LETTER = TEMPLATES / "PAPERBACK_8.500x11.000_104_BW_WHITE_en_US.jpg"
MAC_CMYK = Path("/System/Library/ColorSync/Profiles/Generic CMYK Profile.icc")
GENERATE = ["generate", "--theme", "Dinozaury", "--age", "przedszkole", "--style", "kawaii"]
BOOK = Path("output/dinozaury_przedszkole_kawaii_letter")
ARG = str(BOOK)


def _geometry(trim: tuple[float, float], pages: int, dpi: int = 300) -> CoverGeometry:
    return CoverGeometry(
        trim_in=trim, pages_in_book=pages, kdp=KdpCover(), key_margin_in=0.375, dpi=dpi
    )


# --- Geometria ----------------------------------------------------------------------------


def test_spec_example_letter_62_pages() -> None:
    geometry = _geometry((8.5, 11), 62)
    assert geometry.spine_in == pytest.approx(0.139624)
    assert geometry.size_in == pytest.approx((17.389624, 11.25))
    assert geometry.size_px == (5217, 3375)


@pytest.mark.parametrize("template", [SQUARE, LETTER], ids=["square", "letter"])
def test_geometry_matches_kdp_template_values(template: Path) -> None:
    data = json.loads(template.with_suffix(".expected.json").read_text(encoding="utf-8"))
    geometry = _geometry(tuple(data["input"]["trim_in"]), data["input"]["pages_in_book"])
    expected = data["expected"]

    def box(values: dict[str, float]) -> tuple[float, ...]:
        return tuple(values[k] for k in ("left", "top", "right", "bottom"))

    assert geometry.spine_in == pytest.approx(expected["spine_in"])
    assert geometry.size_in == pytest.approx(tuple(expected["cover_in"]))
    assert geometry.trim_box == pytest.approx(box(expected["trim_box_in"]))
    assert geometry.folds_x == pytest.approx(tuple(expected["folds_x_in"]))
    live = expected["live_area_in"]
    assert geometry.live_back == pytest.approx(box(live["back"]))
    assert geometry.live_front == pytest.approx(box(live["front"]))
    assert (geometry.live_spine[0], geometry.live_spine[2]) == pytest.approx(
        (live["spine"]["left"], live["spine"]["right"])
    )
    assert geometry.barcode == pytest.approx(box(expected["barcode_in"]))


# --- Szablon KDP --------------------------------------------------------------------------


@pytest.mark.parametrize(("template", "trim"), [(SQUARE, (8.5, 8.5)), (LETTER, (8.5, 11.0))])
def test_template_matches_computed_geometry(
    template: Path, trim: tuple[float, float], repo_config: AppConfig
) -> None:
    geometry = _geometry(trim, 104)
    colors = repo_config.settings.cover.template_colors
    measure = measure_template(template, geometry, colors)
    assert measure.px_per_in == pytest.approx(457.5, abs=0.1)
    assert compare_template(measure, geometry, 0.01) == []
    assert check_template_name(template, geometry) == []


def test_template_for_other_page_count_is_rejected(tmp_path: Path, repo_config: AppConfig) -> None:
    geometry = _geometry((8.5, 8.5), 140)
    renamed = tmp_path / "szablon.jpg"  # nazwa spoza wzoru KDP: liczy się tylko pomiar
    shutil.copyfile(SQUARE, renamed)
    measure = measure_template(renamed, geometry, repo_config.settings.cover.template_colors)
    problems = compare_template(measure, geometry, 0.01)
    assert any(p.startswith("linie zgięcia") for p in problems)
    assert check_template_name(renamed, geometry) == []
    assert check_template_name(SQUARE, geometry) == ["szablon dla 104 stron, a książka ma 140"]


@pytest.mark.parametrize(
    ("name", "problem"),
    [
        ("HARDCOVER_8.500x8.500_104_BW_WHITE_en_US.png", "szablon binding = HARDCOVER"),
        ("PAPERBACK_8.500x8.500_104_COLOR_WHITE_en_US.png", "szablon ink = COLOR"),
        ("PAPERBACK_8.500x8.500_104_BW_CREAM_en_US.png", "szablon paper = CREAM"),
        ("PAPERBACK_8.500x11.000_104_BW_WHITE_en_US.png", 'szablon dla formatu 8.5" × 11"'),
    ],
)
def test_template_name_parameters(name: str, problem: str) -> None:
    problems = check_template_name(Path(name), _geometry((8.5, 8.5), 104))
    assert len(problems) == 1 and problems[0].startswith(problem)


# --- CMYK ---------------------------------------------------------------------------------


def test_limit_ink_reduces_cmy_and_keeps_k() -> None:
    pixels = np.array([[[255, 255, 255, 255], [100, 50, 0, 10]]], dtype=np.uint8)
    fixed, before, share = limit_ink(pixels, 300)
    assert before == pytest.approx(400)
    assert share == 50.0
    assert fixed[0, 0, 3] == 255
    assert int(fixed[0, 0].astype(int).sum()) <= 3 * 255
    assert fixed[0, 1].tolist() == [100, 50, 0, 10]


def test_compose_forces_k100_black_and_paper_white() -> None:
    color = Image.new("RGB", (4, 1), (200, 30, 40))
    black = Image.new("L", (4, 1), 255)
    paper = Image.new("L", (4, 1), 255)
    black.putpixel((0, 0), 0)
    paper.putpixel((1, 0), 0)
    result = compose_cmyk(color, black, paper, NaiveConverter(), 240)
    pixels = np.asarray(result.image)
    assert tuple(pixels[0, 0]) == BLACK_K100
    assert tuple(pixels[0, 1]) == (0, 0, 0, 0)
    assert pixels[0, 2].astype(int).sum() <= 240 / 100 * 255 + 1
    assert 100 <= result.max_total_ink_pct <= 240
    preview_px = np.asarray(rgb_preview(color, black, paper))
    assert tuple(preview_px[0, 0]) == (0, 0, 0) and tuple(preview_px[0, 1]) == (255, 255, 255)


def test_delta_e_and_gamut_map() -> None:
    white = Image.new("RGB", (2, 2), (255, 255, 255))
    red = Image.new("RGB", (2, 2), (255, 0, 0))
    assert float(delta_e(white, white).max()) == pytest.approx(0, abs=0.5)
    assert float(delta_e(white, red).min()) > 50
    image, mask = gamut_map(white, red, 10)
    assert mask.all() and image.getpixel((0, 0)) == (255, 0, 160)


def test_missing_profile_is_a_config_error(tmp_path: Path) -> None:
    with pytest.raises(CmykError, match="brak profilu CMYK"):
        IccConverter(CmykSettings())
    with pytest.raises(CmykError, match="brak profilu CMYK"):
        IccConverter(CmykSettings(profile=str(tmp_path / "missing.icc")))


def test_rgb_profile_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "srgb.icc"
    path.write_bytes(ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes())
    with pytest.raises(CmykError, match="nie jest profilem CMYK"):
        IccConverter(CmykSettings(profile=str(path)))


@pytest.mark.skipif(not MAC_CMYK.is_file(), reason="profil CMYK z macOS")
def test_icc_conversion_round_trip() -> None:
    converter = IccConverter(CmykSettings(profile=str(MAC_CMYK)))
    assert converter.sha256 is not None and converter.name
    rgb = Image.new("RGB", (2, 1), (150, 120, 100))  # kolor w gamucie druku
    cmyk_img = converter.to_cmyk(rgb)
    assert cmyk_img.mode == "CMYK"
    assert float(delta_e(rgb, converter.to_rgb(cmyk_img)).max()) < 10


# --- PDF ----------------------------------------------------------------------------------


def test_pdf_is_cmyk_flate_with_trim_and_bleed_boxes() -> None:
    image = Image.new("CMYK", (30, 20), (0, 0, 0, 255))
    data = cmyk_pdf(image, (17.484208, 8.75), 0.125)
    assert data.startswith(b"%PDF-1.4") and data.rstrip().endswith(b"%%EOF")
    assert b"/ColorSpace /DeviceCMYK" in data and b"/Filter /FlateDecode" in data
    assert b"/MediaBox [0 0 1258.863 630]" in data
    assert b"/BleedBox [0 0 1258.863 630]" in data
    assert b"/TrimBox [9 9 1249.863 621]" in data
    assert b"/OutputIntent" not in data and b"ICCBased" not in data and b"DCTDecode" not in data
    match = re.search(rb"/Length (\d+) >>\nstream\n", data)
    assert match is not None
    start = match.end()
    stream = data[start : start + int(match[1])]
    assert zlib.decompress(stream) == image.tobytes()
    xref = int(data.rsplit(b"startxref\n", 1)[1].split(b"\n")[0])
    assert data[xref:].startswith(b"xref")


def test_pdf_rejects_rgb() -> None:
    with pytest.raises(ValueError, match="CMYK"):
        cmyk_pdf(Image.new("RGB", (2, 2)), (1, 1), 0.125)


# --- Układ --------------------------------------------------------------------------------


def _page(size: int = 600, stroke: int = 8) -> Image.Image:
    img = Image.new("L", (size, size), 255)
    draw = ImageDraw.Draw(img)
    draw.ellipse((100, 100, size - 100, size - 100), outline=0, width=stroke)
    draw.line((150, size // 2, size - 150, size // 2), fill=0, width=stroke)
    return img


def test_line_width_measures_strokes() -> None:
    assert line_width_px(_page(stroke=8)) == pytest.approx(8, abs=2)
    assert line_width_px(_page(stroke=20)) == pytest.approx(20, abs=3)


def test_thumbnail_grid_fits_area() -> None:
    area = (0, 0, 1000, 600)
    rects = thumbnail_grid(area, 3, 1.0, 20)
    assert len(rects) == 3
    for rect in rects:
        assert rect[0] >= 0 and rect[1] >= 0 and rect[2] <= 1000 and rect[3] <= 600
        assert rect[2] - rect[0] == pytest.approx(rect[3] - rect[1], abs=1)
    assert rects[0][1] == rects[1][1] == rects[2][1]  # jeden rząd na szerokim pasie


def _pages(tmp_path: Path, count: int) -> list[Path]:
    paths = []
    for i in range(count):
        path = tmp_path / f"page_{i + 1:02d}.png"
        _page().save(path)
        paths.append(path)
    return paths


@pytest.mark.parametrize(("pages", "spine"), [(62, False), (120, True)])
def test_build_cover_places_everything_in_zones(
    tmp_path: Path, repo_config: AppConfig, pages: int, spine: bool
) -> None:
    geometry = _geometry((8.5, 8.5), pages, dpi=100)
    paths = _pages(tmp_path, 4)
    build = build_cover(
        geometry, repo_config.settings.cover, paths[0], paths[1:], "Dino Friends", "For Kids"
    )
    assert build.spine_text is spine
    assert {"title", "subtitle", "front_art", "thumbnail_1", "thumbnail_3"} <= set(build.placements)
    assert build.layers.black.size == geometry.size_px
    left, top, right, bottom = build.placements["title"]
    assert (np.asarray(build.layers.black)[top:bottom, left:right] == 0).any()
    barcode = geometry.px(geometry.barcode)
    paper = np.asarray(build.layers.paper)
    assert (paper[barcode[1] : barcode[3], barcode[0] : barcode[2]] == 255).all()
    black = np.asarray(build.layers.black)
    assert (black[barcode[1] : barcode[3], barcode[0] : barcode[2]] == 255).all()


def test_spine_text_skipped_when_too_small(tmp_path: Path, repo_config: AppConfig) -> None:
    settings = repo_config.settings.cover.model_copy(update={"spine_font_min_pt": 40})
    paths = _pages(tmp_path, 4)
    build = build_cover(_geometry((8.5, 8.5), 120, dpi=100), settings, paths[0], paths[1:], "T", "")
    assert not build.spine_text
    assert build.warnings and "grzbiet bez tekstu" in build.warnings[0]


def test_long_title_that_cannot_fit_is_an_error(tmp_path: Path, repo_config: AppConfig) -> None:
    paths = _pages(tmp_path, 4)
    with pytest.raises(CoverError, match="tytuł nie mieści się"):
        build_cover(
            _geometry((8.5, 8.5), 62, dpi=100),
            repo_config.settings.cover,
            paths[0],
            paths[1:],
            "Supercalifragilisticexpialidocious" * 4,
            "",
        )


def test_placement_check_catches_barcode_overlap() -> None:
    geometry = _geometry((8.5, 8.5), 62, dpi=100)
    build = CoverBuild(layers=CoverLayers.blank(geometry.size_px))
    build.placements["thumbnail_1"] = geometry.px(geometry.barcode)
    with pytest.raises(CoverError, match="pole kodu kreskowego"):
        check_placements(build, geometry)


def test_preview_and_front_crop(repo_config: AppConfig) -> None:
    geometry = _geometry((8.5, 8.5), 104, dpi=50)
    cover = Image.new("RGB", geometry.size_px, (255, 255, 255))
    img = preview(cover, geometry, SQUARE)
    assert img.size == geometry.size_px
    x, y = geometry.px(geometry.barcode)[:2]
    assert img.getpixel((x + 5, y + 5)) != (255, 255, 255)
    front = front_crop(cover, geometry)
    assert front.size == (round(8.5 * 50), round(8.5 * 50))


# --- CLI ----------------------------------------------------------------------------------


@pytest.fixture
def naive_cmyk(monkeypatch: pytest.MonkeyPatch) -> CoverVision:
    """Konwerter CMYK bez profilu ICC i model z wizją dla okładki (etap 3)."""
    monkeypatch.setattr(cli, "cmyk_converter", lambda settings: NaiveConverter())
    responder = CoverVision()
    vision = FakeVisionProvider(responder)
    monkeypatch.setattr(cli, "create_vision_provider", lambda name, model: vision)
    return responder


def _book(pages: int = 6) -> None:
    assert main([*GENERATE, "--pages", str(pages)]) == ExitCode.OK


def _cover() -> dict[str, Any]:
    data = json.loads((BOOK / "manifest.json").read_text(encoding="utf-8"))
    cover = data["cover"]
    assert isinstance(cover, dict)
    return cover


@pytest.mark.usefixtures("naive_cmyk")
def test_cover_command_writes_all_files(capsys: pytest.CaptureFixture[str]) -> None:
    _book()
    assert main(["cover", ARG, "--no-select-pages"]) == ExitCode.OK
    out = capsys.readouterr().out
    assert 'Okładka: 17.282" × 11.250"' in out  # letter, 14 stron: grzbiet 0.0315"
    assert "Przód: page_01; miniatury: page_02, page_04, page_06 (domyślny wybór" in out
    assert "Tekst na grzbiecie: nie (od 100 stron)." in out
    assert "egzemplarz próbny" in out
    for name in ("cover.pdf", "cover.png", "front.png", "cover_proof.png", "cover_gamut.png",
                 "cover_preview.png"):  # fmt: skip
        assert (BOOK / "cover" / name).is_file()
    assert (BOOK / "cover" / "cover.pdf").read_bytes().startswith(b"%PDF")
    cover = _cover()
    assert cover["front_page"] == "page_01" and cover["selection"] == "default"
    assert cover["geometry"]["pages_in_book"] == 14
    assert cover["cmyk"]["profile"].startswith("naive")
    assert cover["cmyk"]["max_total_ink_pct"] <= 300
    assert cover["files"]["pdf"] == "cover/cover.pdf"
    assert cover["title"] == "Dino Friends"


@pytest.mark.usefixtures("naive_cmyk")
def test_cover_with_chosen_pages() -> None:
    _book()
    assert main(["cover", ARG, "--cover-page", "page_03", "--thumbnails", "1,2,6"]) == 0
    cover = _cover()
    assert (cover["front_page"], cover["thumbnails"], cover["selection"]) == (
        "page_03",
        ["page_01", "page_02", "page_06"],
        "manual",
    )


@pytest.mark.usefixtures("naive_cmyk")
@pytest.mark.parametrize(
    ("args", "message"),
    [
        (["--cover-page", "99"], "książka ma strony 1–6"),
        (["--cover-page", "abc"], "podaj numer"),
        (["--thumbnails", "02,02,03"], "strony muszą być różne"),
        (["--thumbnails", "02,03"], "podaj 3 albo 4 strony"),
        (["--cover-page", "02", "--thumbnails", "02,03,04"], "inne niż przód"),
        (["--template", str(SQUARE)], "szablon dla 104 stron, a książka ma 14"),
        (["--template", "missing.png"], "brak pliku szablonu"),
    ],
)
def test_cover_argument_errors(
    args: list[str], message: str, capsys: pytest.CaptureFixture[str]
) -> None:
    _book()
    assert main(["cover", ARG, *args]) == ExitCode.VALIDATION_ERROR
    assert message in capsys.readouterr().err
    assert not (BOOK / "cover").exists()


def test_cover_without_profile_explains_where_to_get_it(
    capsys: pytest.CaptureFixture[str],
) -> None:
    _book()
    assert main(["cover", ARG]) == ExitCode.VALIDATION_ERROR
    err = capsys.readouterr().err
    assert "brak profilu CMYK" in err and "SWOP" in err


@pytest.mark.usefixtures("naive_cmyk")
def test_cover_uses_only_ready_pages(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    provider = FakeImageProvider(
        fail=lambda req: ProviderError("x", fatal=False) if "number 2 " in req.prompt else None
    )
    monkeypatch.setattr(cli, "create_image_provider", lambda name, model: provider)
    assert main([*GENERATE, "--pages", "6"]) == ExitCode.PARTIAL
    assert main(["cover", ARG, "--cover-page", "02"]) == ExitCode.VALIDATION_ERROR
    assert "page_02 nie jest gotowa" in capsys.readouterr().err
    assert main(["cover", ARG]) == ExitCode.OK
    assert "page_02" not in [_cover()["front_page"], *_cover()["thumbnails"]]
    assert "książka nie jest gotowa" in capsys.readouterr().err


@pytest.mark.usefixtures("naive_cmyk")
def test_images_warns_when_cover_pages_change(capsys: pytest.CaptureFixture[str]) -> None:
    _book()
    assert main(["cover", ARG]) == ExitCode.OK
    data = json.loads((BOOK / "manifest.json").read_text(encoding="utf-8"))
    data["pages"][0]["action"] = "regenerate"
    (BOOK / "manifest.json").write_text(json.dumps(data), encoding="utf-8")
    capsys.readouterr()
    assert main(["images", ARG]) == ExitCode.OK
    assert "okładka używa stron wygenerowanych ponownie (page_01)" in capsys.readouterr().err
