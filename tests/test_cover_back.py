"""FR-15 etap 3: tło tyłu i grzbietu, styk z przodem, wybór stron modelem z wizją, QA okładki."""

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
from kdp_studio.config import AppConfig, ConfigError, KdpCover, load_config
from kdp_studio.pipeline.cmyk import NaiveConverter
from kdp_studio.pipeline.cover import build_cover, layout_back_text
from kdp_studio.pipeline.cover_back import (
    BackPainter,
    OutpaintPlan,
    align_to_front,
    back_prompt,
    blend_seam,
    outpaint_canvas,
    outpaint_plan,
    pixel_horizon,
    register_canvas,
    seam_check,
)
from kdp_studio.pipeline.cover_front import CoverBudgetError, CoverColorError
from kdp_studio.pipeline.cover_geometry import CoverGeometry
from kdp_studio.pipeline.cover_vision import (
    FrontScene,
    _LLMSelection,
    choose_pages,
    contact_sheet,
    qa_instructions,
)
from kdp_studio.providers.base import ImageRequest, ImageResult, ProviderError, Usage
from kdp_studio.providers.fake import FakeVisionProvider
from tests.conftest import FAKE_PRICES, ConfigDirFactory, CoverVision, fake_settings
from tests.test_cli import fake_text_provider  # noqa: F401  (autouse: fałszywi dostawcy)

GENERATE = ["generate", "--theme", "Dinozaury", "--age", "przedszkole", "--style", "kawaii"]
BOOK = Path("output/dinozaury_przedszkole_kawaii_letter")
ARG = str(BOOK)
SKY = (120, 180, 240)
GRASS = (80, 170, 60)


def _geometry(trim: tuple[float, float] = (8.5, 8.5), pages: int = 62) -> CoverGeometry:
    return CoverGeometry(
        trim_in=trim, pages_in_book=pages, kdp=KdpCover(), key_margin_in=0.375, dpi=100
    )


def _landscape(size: tuple[int, int], horizon: float) -> np.ndarray:
    """Niebo nad trawą; horyzont na `horizon` wysokości."""
    width, height = size
    img = np.empty((height, width, 3), np.uint8)
    split = round(height * horizon)
    img[:split] = SKY
    img[split:] = GRASS
    return img


def _png(img: Image.Image) -> bytes:
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    return buffer.getvalue()


# --- Próbki pikseli i styk ---------------------------------------------------------------


def test_pixel_horizon_finds_sky_and_grass_split() -> None:
    assert pixel_horizon(_landscape((10, 400), 0.6)) == pytest.approx(0.6, abs=0.01)
    assert pixel_horizon(np.full((400, 10, 3), 200, np.uint8)) is None


def test_seam_check_passes_matching_and_fails_shifted_horizon(repo_config: AppConfig) -> None:
    settings = repo_config.settings.cover
    front = _landscape((100, 400), 0.6)
    same = seam_check(_landscape((100, 400), 0.6), front, 5, settings)
    assert same.passed and same.max_delta_e == 0
    shifted = seam_check(_landscape((100, 400), 0.4), front, 5, settings)
    assert not shifted.passed and not shifted.horizon_ok
    assert shifted.horizon_back == pytest.approx(0.4, abs=0.01)
    other = seam_check(np.full((400, 100, 3), (240, 60, 60), np.uint8), front, 5, settings)
    assert not other.passed and other.max_delta_e > settings.seam_max_delta_e


def test_blend_seam_ends_in_front_colors() -> None:
    back = np.full((50, 40, 3), (200, 0, 0), np.uint8)
    front = np.full((50, 30, 3), (0, 0, 200), np.uint8)
    out = blend_seam(back, front, 10, 3)
    assert tuple(out[25, -1]) == (0, 0, 200)  # ostatnia kolumna = kolor przodu
    assert tuple(out[25, 0]) == (200, 0, 0)  # poza pasem bez zmian
    assert 0 < out[25, -5, 2] < 200  # w pasie przejście


def test_back_prompt_has_horizon_colors_and_zones(repo_config: AppConfig) -> None:
    settings = repo_config.settings.cover
    geometry = _geometry()
    scene = FrontScene(0.62, ["#87CEEB", "#55AA33"], "blue sky above a meadow", Usage())
    prompt = back_prompt(settings, "kawaii style", geometry, scene, ["#000000"], None)
    assert "at exactly 62% of the image height" in prompt
    assert "#87CEEB, #55AA33" in prompt and "#000000" not in prompt
    assert "blue sky above a meadow" in prompt
    assert "Style of the book: kawaii style." in prompt
    assert "{" not in prompt and "No text" in prompt
    flat = back_prompt(settings, "s", geometry, None, ["#FFFFFF"], None)
    assert "no horizon line" in flat and "#FFFFFF" in flat


def test_bad_outpaint_prompt_placeholder_is_a_config_error(config_dir: ConfigDirFactory) -> None:
    settings = fake_settings()
    settings["cover"]["outpaint_prompt"] = "Extend {horizon}"
    with pytest.raises(ConfigError, match="outpaint_prompt"):
        load_config(config_dir(settings=settings))


def test_bad_back_prompt_placeholder_is_a_config_error(config_dir: ConfigDirFactory) -> None:
    settings = fake_settings()
    settings["cover"]["back_prompt"] = "Paint {horizont}"
    with pytest.raises(ConfigError, match="back_prompt"):
        load_config(config_dir(settings=settings))


# --- Malowanie tyłu ----------------------------------------------------------------------


@dataclass
class Painter:
    """Model obrazu dla tyłu: kolejne obrazy z `images` (None = błąd niekrytyczny)."""

    images: list[np.ndarray | None]
    name: str = "fake"
    model: str = "fake-image"
    requests: list[ImageRequest] = field(default_factory=list)

    def supported_aspects(self) -> list[str]:
        return ["1:1", "3:4", "4:3"]

    def generate(self, req: ImageRequest) -> ImageResult:
        self.requests.append(req)
        img = self.images[len(self.requests) - 1]
        if img is None:
            raise ProviderError("przeciążenie", fatal=False)
        data = _png(Image.fromarray(img))
        return ImageResult(data, img.shape[1], img.shape[0], Usage(output_tokens=100))


def _painter(
    repo_config: AppConfig,
    tmp_path: Path,
    provider: Painter,
    *,
    outpaint: bool = False,
    **kwargs: Any,
) -> BackPainter:
    """Domyślnie tył z przodem jako referencją; `outpaint=True` to dorysowanie z maską."""
    return BackPainter(
        provider=provider,
        quality="low",
        style="kawaii",
        settings=repo_config.settings.cover.model_copy(update={"outpaint": outpaint}),
        geometry=_geometry(),
        raw_dir=tmp_path,
        **kwargs,
    )


def _front(geometry: CoverGeometry, horizon: float = 0.6) -> Image.Image:
    left, _, right, bottom = geometry.px(geometry.front_panel)
    return Image.fromarray(_landscape((right - left, bottom), horizon))


def test_back_painter_retries_bad_seam_and_keeps_raw(
    repo_config: AppConfig, tmp_path: Path
) -> None:
    good, bad = _landscape((300, 300), 0.6), _landscape((300, 300), 0.3)
    provider = Painter([None, bad, good])
    scenes: list[Image.Image] = []

    def analyze(front: Image.Image) -> FrontScene:
        scenes.append(front)
        return FrontScene(0.6, ["#78B4F0"], "sky over grass", Usage(input_tokens=5))

    painter = _painter(repo_config, tmp_path, provider, analyze=analyze)
    geometry = _geometry()
    back = painter(_front(geometry))
    assert back.size == (geometry.px(geometry.front_panel)[0], geometry.size_px[1])
    assert painter.attempts == 3 and painter.chosen == 3
    assert [s.passed for s in painter.seams] == [False, True]
    assert painter.errors == ["przeciążenie"]
    assert [p.name for p in painter.raw_files] == ["back_try2.png", "back_try3.png"]
    assert painter.aspect == "1:1" and len(scenes) == 1
    assert painter.prompt is not None and "60%" in painter.prompt
    assert all(r.reference_image is not None for r in provider.requests)
    assert not painter.warnings


def test_back_painter_uses_best_try_with_warning(repo_config: AppConfig, tmp_path: Path) -> None:
    red = np.full((300, 300, 3), (230, 40, 40), np.uint8)
    provider = Painter([red, _landscape((300, 300), 0.62), red])
    painter = _painter(repo_config, tmp_path, provider)
    geometry = _geometry()
    painter(_front(geometry))  # horyzont 0.62 wobec 0.6 mieści się w tolerancji: bez 3. próby
    assert painter.attempts == 2 and painter.chosen == 2

    provider = Painter([red, red, red])
    painter = _painter(repo_config, tmp_path, provider)
    painter(_front(geometry))
    assert painter.attempts == 3 and painter.chosen == 1
    assert any("styk grzbietu z przodem" in w for w in painter.warnings)


CREAM = (245, 230, 200)
WOOD = (200, 120, 60)


def _room(size: tuple[int, int], top: float, bottom: float) -> np.ndarray:
    """Ściana nad listwą (od `top` do `bottom` wysokości) i podłoga pod nią."""
    width, height = size
    img = np.empty((height, width, 3), np.uint8)
    img[: round(height * top)] = SKY
    img[round(height * top) : round(height * bottom)] = CREAM
    img[round(height * bottom) :] = WOOD
    return img


def _edges(column: np.ndarray) -> list[float]:
    """Wysokości zmian koloru w kolumnie pikseli (ułamki od góry)."""
    change = np.nonzero(np.abs(np.diff(column.astype(int), axis=0)).sum(axis=1) > 60)[0]
    return [round((row + 1) / len(column), 2) for row in change]


def test_align_to_front_matches_both_edges_of_a_thicker_baseboard() -> None:
    # Model namalował listwę wyżej i cieńszą niż na przodzie (jak w „Świątecznych kotkach”).
    front = _room((20, 400), 0.68, 0.73)
    back = _room((80, 400), 0.54, 0.59)
    out, shift = align_to_front(back, front, 5, 0.2)
    assert shift == pytest.approx(0.14, abs=0.02)
    for column in (out[:, -1], out[:, 0]):  # ta sama mapa wierszy na całej szerokości
        assert _edges(column) == pytest.approx([0.68, 0.73], abs=0.015)
    assert tuple(out[10, 40]) == SKY and tuple(out[-10, 40]) == WOOD


def test_align_to_front_leaves_a_matching_back_alone() -> None:
    back = _landscape((60, 400), 0.6)
    out, shift = align_to_front(back, _landscape((10, 400), 0.6), 5, 0.2)
    assert shift is None and out is back
    shifted = _landscape((60, 400), 0.4)
    out, shift = align_to_front(shifted, back[:, :10], 5, 0.0)  # seam_align_max 0 wyłącza
    assert shift is None and out is shifted


def test_back_painter_aligns_horizon_the_model_missed(
    repo_config: AppConfig, tmp_path: Path
) -> None:
    # Model namalował horyzont 12% wyżej niż na przodzie: bez dopasowania styk by nie przeszedł.
    provider = Painter([_landscape((300, 300), 0.48)])
    painter = _painter(repo_config, tmp_path, provider)
    geometry = _geometry()
    back = np.asarray(painter(_front(geometry)))
    assert painter.attempts == 1
    (seam,) = painter.seams
    assert seam.passed and seam.align_shift == pytest.approx(0.12, abs=0.02)
    assert pixel_horizon(back[:, -5:]) == pytest.approx(0.6, abs=0.01)
    assert not painter.warnings


def test_shift_beyond_the_limit_is_not_fully_aligned(
    repo_config: AppConfig, tmp_path: Path
) -> None:
    provider = Painter([_landscape((300, 300), 0.48)] * 3)
    painter = _painter(repo_config, tmp_path, provider)
    painter.settings = painter.settings.model_copy(update={"seam_align_max": 0.05})
    painter(_front(_geometry()))
    assert painter.attempts == 3
    assert all(not s.passed and (s.align_shift or 0) <= 0.06 for s in painter.seams)


# --- Dorysowanie tyłu do przodu ------------------------------------------------------------


def test_outpaint_plan_picks_narrowest_strip_that_is_wide_enough() -> None:
    # Kwadratowa książka: tył z grzbietem ~ kwadrat, więc 1:1 nie zostawia miejsca na przód.
    plan = outpaint_plan((886, 875), 875, ["1:1", "4:3", "3:2"], 0.2)
    assert plan == OutpaintPlan("4:3", 281)
    assert outpaint_plan((886, 875), 875, ["1:1"], 0.2) is None
    assert outpaint_plan((886, 875), 875, ["3:1"], 0.2) is None  # więcej niż cały przód


def test_outpaint_canvas_keeps_front_strip_and_masks_the_back() -> None:
    front = _landscape((875, 875), 0.6)
    canvas_png, mask_png = outpaint_canvas(front, (886, 875), OutpaintPlan("4:3", 281))
    with Image.open(io.BytesIO(canvas_png)) as canvas, Image.open(io.BytesIO(mask_png)) as mask:
        assert canvas.size == mask.size and canvas.height == 1024
        assert canvas.width / canvas.height == pytest.approx(4 / 3, abs=0.01)
        pixels = np.asarray(canvas.convert("RGB"))
        alpha = np.asarray(mask)[:, :, 3]
    split = round(886 * 1024 / 875)
    assert (alpha[:, : split - 1] == 0).all() and (alpha[:, split + 1 :] == 255).all()
    assert tuple(pixels[10, 5]) == (255, 255, 255)  # puste miejsce na tył
    assert pixel_horizon(pixels[:, -20:]) == pytest.approx(0.6, abs=0.01)  # pas przodu


def _boards(
    size: tuple[int, int], *, scale: float = 1.0, shift: tuple[float, float] = (0, 0)
) -> np.ndarray:
    """Ściana nad podłogą z desek (poziome deski, pionowe łączenia), opcjonalnie przeskalowana
    i przesunięta, jak przerysowanie przez model z „miękką” maską."""
    width, height = size
    ys, xs = np.mgrid[0:height, 0:width].astype(np.float64)
    y = (ys - shift[1]) / scale
    x = (xs - shift[0]) / scale
    img = np.empty((height, width, 3), np.uint8)
    wall = y < height * 0.45
    board = np.floor((y - height * 0.45) / 37).astype(int)
    joint = ((x + board * 29) % 113) < 4
    seam = ((y - height * 0.45) % 37) < 3
    img[:] = WOOD
    img[(board % 2 == 1) & ~wall] = (185, 105, 50)
    img[(joint | seam) & ~wall] = (110, 60, 30)
    img[wall] = SKY
    img[(y >= height * 0.42) & wall] = CREAM
    return img


def test_register_canvas_undoes_model_shift_and_scale() -> None:
    truth = _boards((600, 360))
    split = 400
    drawn = _boards((600, 360), scale=0.97, shift=(4, 18))  # model przerysował wszystko
    registered = register_canvas(drawn, truth[:, split:], split)
    assert registered is not None
    canvas, cc = registered
    assert cc > 0.9
    # Po rejestracji kolumna tuż przed zgięciem zgadza się z prawdziwą sceną w tym miejscu.
    diff = np.abs(canvas[:, split - 1].astype(int) - truth[:, split - 1].astype(int)).sum(axis=1)
    assert (diff > 60).mean() < 0.05
    before = np.abs(drawn[:, split - 1].astype(int) - truth[:, split - 1].astype(int)).sum(axis=1)
    assert (before > 60).mean() > 0.1  # bez rejestracji deski się rozjeżdżają


def test_register_canvas_gives_up_on_unrelated_strip() -> None:
    truth = _boards((600, 360))
    noise = np.random.default_rng(0).integers(0, 255, (360, 600, 3), dtype=np.uint8)
    assert register_canvas(noise, truth[:, 400:], 400) is None


def test_back_painter_outpaints_and_skips_scene_analysis(
    repo_config: AppConfig, tmp_path: Path
) -> None:
    analyzed: list[Image.Image] = []

    def analyze(front: Image.Image) -> FrontScene:
        analyzed.append(front)
        return FrontScene(0.6, [], "", Usage())

    provider = Painter([_landscape((400, 300), 0.6)])
    painter = _painter(repo_config, tmp_path, provider, outpaint=True, analyze=analyze)
    geometry = _geometry()
    back = painter(_front(geometry))
    assert back.size == (geometry.px(geometry.front_panel)[0], geometry.size_px[1])
    assert (painter.mode, painter.aspect) == ("outpaint", "4:3")
    assert painter.overlap_px is not None and painter.overlap_px > 0
    (req,) = provider.requests
    assert req.mask is not None and req.reference_image is not None and req.aspect == "4:3"
    assert painter.prompt is not None and painter.prompt.startswith("Extend this picture")
    assert "Style of the book: kawaii." in painter.prompt and "{" not in painter.prompt
    assert analyzed == [] and painter.seams[0].passed


def test_back_painter_registers_outpainted_canvas(repo_config: AppConfig, tmp_path: Path) -> None:
    geometry = _geometry()
    left, _, right, bottom = geometry.px(geometry.front_panel)
    scene = _boards((right, bottom))  # tył z grzbietem i przód obok siebie
    front = Image.fromarray(np.ascontiguousarray(scene[:, left:]))
    plan_width = round(bottom * 4 / 3)  # kwadratowa okładka: płótno 4:3
    drawn = _boards((plan_width, bottom), scale=0.97, shift=(4, 9))
    # Płótno z modelu: scena od lewej krawędzi tyłu do pasa przodu, przerysowana z przesunięciem.
    provider = Painter([drawn])
    painter = _painter(repo_config, tmp_path, provider, outpaint=True)
    back = np.asarray(painter(front))
    (seam,) = painter.seams
    assert seam.register_cc is not None and seam.register_cc > 0.9
    assert seam.align_shift is None and seam.passed
    edge = back[:, left - 40]  # przed pasem wygładzenia styku
    diff = np.abs(edge.astype(int) - scene[:, left - 40].astype(int)).sum(axis=1)
    assert (diff > 60).mean() < 0.05


def test_back_painter_falls_back_to_reference_without_fitting_aspect(
    repo_config: AppConfig, tmp_path: Path
) -> None:
    provider = Painter([_landscape((300, 300), 0.6)])
    painter = _painter(repo_config, tmp_path, provider, outpaint=True)
    painter.settings = painter.settings.model_copy(update={"outpaint_overlap_min": 0.9})
    painter(_front(_geometry()))
    assert (painter.mode, painter.aspect, painter.overlap_px) == ("reference", "1:1", None)
    assert provider.requests[0].mask is None


def test_back_painter_gives_up_and_respects_budget(repo_config: AppConfig, tmp_path: Path) -> None:
    geometry = _geometry()
    with pytest.raises(CoverColorError, match="nie namalował tyłu"):
        _painter(repo_config, tmp_path, Painter([None, None, None]))(_front(geometry))
    with pytest.raises(CoverBudgetError):
        _painter(repo_config, tmp_path, Painter([None]), over_budget=lambda: True)(_front(geometry))


def test_failed_front_analysis_falls_back_to_pixels(repo_config: AppConfig, tmp_path: Path) -> None:
    def analyze(front: Image.Image) -> FrontScene:
        raise ProviderError("odmowa", fatal=False)

    provider = Painter([_landscape((300, 300), 0.6)])
    painter = _painter(repo_config, tmp_path, provider, analyze=analyze)
    painter(_front(_geometry()))
    assert painter.scene is None and painter.scene_error == "odmowa"
    assert painter.prompt is not None and "60%" in painter.prompt  # horyzont z pikseli
    assert any("ocena przodu" in w for w in painter.warnings)


def test_build_cover_pastes_back_and_keeps_thumbnails_white(
    repo_config: AppConfig, tmp_path: Path
) -> None:
    page = tmp_path / "p.png"
    img = Image.new("L", (300, 300), 255)
    ImageDraw.Draw(img).ellipse((50, 50, 250, 250), outline=0, width=6)
    img.save(page)
    geometry = _geometry()

    def colorize(sketch: Image.Image) -> Image.Image:
        return Image.new("RGB", sketch.size, SKY)

    def paint(front: Image.Image) -> Image.Image:
        return Image.new("RGB", (10, 10), GRASS)  # program skaluje do tyłu z grzbietem

    build = build_cover(
        geometry, repo_config.settings.cover, page, [page] * 3, "Dino", "",
        colorize=colorize, paint_back=paint,
    )  # fmt: skip
    assert build.back_painted
    color = np.asarray(build.layers.color)
    assert tuple(color[5, 5]) == GRASS
    thumb = build.placements["thumbnail_1"]
    assert (np.asarray(build.layers.paper)[thumb[1] + 20, thumb[0] + 20]) == 0  # papier K0


# --- Opis na tyle ------------------------------------------------------------------------

DESCRIPTION = (
    "Friendly dinosaurs play, explore and have fun on every page. "
    "Simple bold outlines are perfect for little hands. "
    "Each picture is printed on its own page. "
    "A great gift for young dinosaur fans."
)


def test_back_text_fits_sentences_and_moves_thumbnails(
    repo_config: AppConfig, tmp_path: Path
) -> None:
    settings = repo_config.settings.cover
    geometry = _geometry()
    block, warning = layout_back_text(geometry, settings, DESCRIPTION)
    assert block is not None and warning is None and block.sentences >= 1
    key = geometry.px(geometry.key_back)
    assert block.height <= (key[3] - key[1]) * settings.back_text_max_height

    page = tmp_path / "p.png"
    img = Image.new("L", (300, 300), 255)
    ImageDraw.Draw(img).rectangle((40, 40, 260, 260), outline=0, width=6)
    img.save(page)
    build = build_cover(geometry, settings, page, [page] * 3, "Dino", "", back_text=DESCRIPTION)
    assert build.back_text
    text = build.placements["back_text"]
    assert all(build.placements[f"thumbnail_{i}"][1] > text[3] for i in (1, 2, 3))


def test_back_text_that_cannot_fit_is_skipped(repo_config: AppConfig) -> None:
    settings = repo_config.settings.cover.model_copy(update={"back_text_max_height": 0.01})
    block, warning = layout_back_text(_geometry(), settings, DESCRIPTION)
    assert block is None and warning is not None and "tył bez opisu" in warning


# --- Wybór stron -------------------------------------------------------------------------


def test_contact_sheet_has_a_cell_per_page(repo_config: AppConfig, tmp_path: Path) -> None:
    pages = []
    for number in range(1, 8):
        path = tmp_path / f"page_{number:02d}.png"
        Image.new("L", (300, 400), 255).save(path)
        pages.append((number, path))
    sheet = contact_sheet(pages, repo_config.settings.cover.title_font_path)
    assert sheet.mode == "L" and sheet.width > 3 * 220 and sheet.height > 3 * 290
    assert (np.asarray(sheet) < 128).any()  # numery i obramowania


@pytest.mark.parametrize(
    ("answer", "fixed", "expected", "warned"),
    [
        ({"front": 3, "thumbnails": [1, 5, 6]}, None, (3, [1, 5, 6]), False),
        ({"front": 9, "thumbnails": [1, 5, 6]}, None, (1, [5, 6, 2]), True),
        ({"front": 3, "thumbnails": [3, 3, 7]}, None, (3, [2, 4, 6]), True),
        ({"front": 4, "thumbnails": [1, 5, 6]}, 2, (2, [1, 5, 6]), False),
    ],
)
def test_choose_pages_validates_model_answer(
    answer: dict[str, Any], fixed: int | None, expected: tuple[int, list[int]], warned: bool
) -> None:
    selection = _LLMSelection(reason="r", **answer)
    front, thumbs, warnings = choose_pages(selection, [1, 2, 3, 4, 5, 6], 3, fixed, 1, [2, 4, 6])
    assert (front, thumbs) == expected
    assert bool(warnings) == warned


def test_qa_instructions_list_program_texts() -> None:
    text = qa_instructions("Dino Friends", "For kids", True, False, None)
    assert '"Dino Friends" on the front' in text and '"For kids"' in text
    assert '"Dino Friends" on the spine' in text and "description" not in text


# --- CLI ---------------------------------------------------------------------------------


def _cover_book(monkeypatch: pytest.MonkeyPatch) -> CoverVision:
    """Gotowa książka do okładki: fałszywy model z wizją i konwersja CMYK bez profilu."""
    monkeypatch.setattr(cli, "cmyk_converter", lambda settings: NaiveConverter())
    responder = CoverVision()
    provider = FakeVisionProvider(responder)
    monkeypatch.setattr(cli, "create_vision_provider", lambda name, model: provider)
    assert main([*GENERATE, "--pages", "6"]) == ExitCode.OK
    return responder


@pytest.fixture
def vision(monkeypatch: pytest.MonkeyPatch) -> CoverVision:
    return _cover_book(monkeypatch)


def _manifest() -> dict[str, Any]:
    data = json.loads((BOOK / "manifest.json").read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def test_cover_pages_proposed_by_vision(
    vision: CoverVision, capsys: pytest.CaptureFixture[str]
) -> None:
    capsys.readouterr()
    assert main(["cover", ARG, "--no-color"]) == ExitCode.OK
    out = capsys.readouterr().out
    assert vision.calls == ["select"]
    assert (
        "Przód: page_03; miniatury: page_01, page_05, page_06 "
        "(propozycja modelu z wizją: wyraźny motyw na przodzie)."
    ) in out
    cover = _manifest()["cover"]
    assert cover["selection"] == "vision"
    info = cover["selection_info"]
    assert info["reason"] == "wyraźny motyw na przodzie"
    assert info["contact_sheet"] == "cover/raw/contact_sheet.png"
    assert (BOOK / "cover" / "raw" / "contact_sheet.png").is_file()
    vision_price = FAKE_PRICES["fake-vision"]
    expected = (1000 * vision_price["input_per_1m"] + 20 * vision_price["output_per_1m"]) / 1e6
    assert cover["cost_usd"] == pytest.approx(expected)


def test_manual_front_lets_vision_pick_only_thumbnails(vision: CoverVision) -> None:
    vision.selection = {"front": 2, "thumbnails": [2, 4, 5], "reason": "różne sceny"}
    assert main(["cover", ARG, "--no-color", "--cover-page", "02"]) == ExitCode.OK
    cover = _manifest()["cover"]
    assert cover["front_page"] == "page_02"
    assert cover["thumbnails"][:2] == ["page_04", "page_05"]  # 2 odrzucona, uzupełniona
    assert cover["selection_info"]["warnings"]


def test_vision_selection_error_falls_back_to_default(
    vision: CoverVision, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def fail(image_png: bytes, instructions: str) -> dict[str, Any]:
        raise ProviderError("odmowa", fatal=False)

    monkeypatch.setattr(cli, "create_vision_provider", lambda name, model: FakeVisionProvider(fail))
    assert main(["cover", ARG, "--no-color"]) == ExitCode.OK
    assert "propozycja stron modelem z wizją nie powiodła się" in capsys.readouterr().err
    assert _manifest()["cover"]["selection"] == "default"


def test_both_manual_pages_skip_vision(vision: CoverVision) -> None:
    assert main(["cover", ARG, "--no-color", "--cover-page", "2", "--thumbnails", "1,3,4"]) == 0
    assert vision.calls == []
    assert _manifest()["cover"]["selection"] == "manual"


def test_cover_paints_back_and_records_seam(
    vision: CoverVision, capsys: pytest.CaptureFixture[str]
) -> None:
    capsys.readouterr()
    assert main(["cover", ARG, "--no-select-pages", "--image-quality", "low"]) == ExitCode.OK
    out = capsys.readouterr().out
    assert vision.calls == []  # dorysowanie: model widzi przód, opis sceny niepotrzebny
    assert "Tył i grzbiet z modelu, dorysowane do przodu (1 próba, styk z przodem ΔE" in out
    back = _manifest()["cover"]["back"]
    assert back["painted"] and back["attempts"] == 1 and back["chosen_attempt"] == 1
    assert (back["mode"], back["aspect"]) == ("outpaint", "1:1")
    assert back["overlap_px"] > 0
    assert back["raw_files"] == ["cover/raw/back_try1.png"]
    assert back["seam_passed"] is True and back["seams"][0]["passed"]
    assert "align_shift" in back["seams"][0]
    assert back["scene"] is None
    assert len(back["edge_colors"]) == 8
    assert back["prompt"].startswith("Extend this picture to the left")


def test_cover_back_from_reference_without_outpaint(
    monkeypatch: pytest.MonkeyPatch,
    config_dir: ConfigDirFactory,
    capsys: pytest.CaptureFixture[str],
) -> None:
    settings = fake_settings()
    settings["cover"]["outpaint"] = False
    config_dir(settings=settings)
    responder = _cover_book(monkeypatch)
    capsys.readouterr()
    assert main(["cover", ARG, "--no-select-pages", "--image-quality", "low"]) == ExitCode.OK
    assert "Tył i grzbiet z modelu, z przodem jako wzorem (1 próba" in capsys.readouterr().out
    assert responder.calls == ["scene"]
    back = _manifest()["cover"]["back"]
    assert (back["mode"], back["overlap_px"]) == ("reference", None)
    assert back["scene"]["background"] == "plain white background"
    assert back["prompt"].startswith("Paint the back cover")


def test_cover_qa_rejection_exits_2_with_files(
    vision: CoverVision, capsys: pytest.CaptureFixture[str]
) -> None:
    issues = [{"criterion": "text", "detail": "napis na tyle"}]
    vision.verdict = {"passed": False, "issues": issues}
    assert main(["cover", ARG, "--no-color", "--no-select-pages", "--qa"]) == ExitCode.PARTIAL
    assert "QA odrzuciła okładkę: text: napis na tyle" in capsys.readouterr().err
    cover = _manifest()["cover"]
    assert cover["status"] == "qa_failed"
    assert cover["qa"] == {
        "pass": False,
        "issues": [{"criterion": "text", "detail": "napis na tyle"}],
    }
    assert (BOOK / "cover" / "cover.pdf").is_file()
    assert vision.calls == ["qa"]
    with Image.open(io.BytesIO(vision.images[-1])) as img:
        assert img.width <= 2048


def test_cover_qa_pass(vision: CoverVision, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["cover", ARG, "--no-color", "--no-select-pages", "--qa"]) == ExitCode.OK
    assert "QA okładki: zaakceptowana." in capsys.readouterr().out
    cover = _manifest()["cover"]
    assert cover["status"] == "ok" and cover["qa"]["pass"] is True


def test_cover_with_back_text(vision: CoverVision) -> None:
    assert main(["cover", ARG, "--no-color", "--no-select-pages", "--back-text"]) == 0
    cover = _manifest()["cover"]
    assert cover["back_text"] is True and "back_text" in cover["placements"]
