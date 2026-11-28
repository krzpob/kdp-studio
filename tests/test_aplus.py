"""FR-24: A+ Content (`kdp-studio aplus`)."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import numpy as np
import pytest
import yaml
from PIL import Image, ImageDraw

from kdp_studio import cli
from kdp_studio.cli import ExitCode, main
from kdp_studio.config import AplusSettings, AppConfig, ConfigError, load_config
from kdp_studio.pipeline import aplus_images as ai
from kdp_studio.pipeline.aplus_models import AplusCopy, ColumnCopy, FeaturesCopy, OverlayCopy
from kdp_studio.pipeline.aplus_text import alt_issues, apply_limits, banned_hits, clip, copy_issues
from kdp_studio.pipeline.cmyk import NaiveConverter
from kdp_studio.providers.fake import FakeImageProvider, FakeTextProvider
from tests.conftest import ConfigDirFactory, fake_settings
from tests.test_cli import (
    BOOK_DIR,
    fake_text_provider,  # noqa: F401  (autouse: fałszywi dostawcy)
)

ARG = str(BOOK_DIR)
GENERATE = ["generate", "--theme", "Dinozaury", "--age", "przedszkole", "--style", "kawaii"]
GOOD: dict[str, Any] = {
    "header": {
        "headline": "Dinosaurs to Color",
        "subheadline": "Big, friendly dinosaurs",
        "body": "Every page shows a cheerful dinosaur.",
    },
    "pages_header": {"headline": "Inside the book", "subheadline": "", "body": ""},
    "overlay_headline": "What's inside",
    "features_headline": "Calm, screen-free fun",
    "columns": [
        {"headline": "Bold lines", "body": "Thick outlines are easy to color."},
        {"headline": "Friendly faces", "body": "Smiling dinosaurs spark stories."},
        {"headline": "Simple shapes", "body": "Large areas suit small hands."},
    ],
    "alt_texts": [
        {"image": "header_fan", "text": "Front and back covers of a dinosaur coloring book"},
        {"image": "overlay_facts", "text": "A row of three dinosaur coloring pages"},
        {"image": "features_1", "text": "Coloring page with a dinosaur by a volcano"},
        {"image": "features_2", "text": "Coloring page with two dinosaurs playing"},
        {"image": "features_3", "text": "Coloring page with a baby dinosaur hatching"},
        {"image": "header_pages", "text": "Three inside pages fanned out"},
    ],
}
BAD = {
    **GOOD,
    "columns": [*GOOD["columns"][:2], {"headline": "Perfect gift", "body": "Order now!"}],
}


@pytest.fixture
def text(fake_text_provider: FakeTextProvider) -> FakeTextProvider:  # noqa: F811
    """Fałszywy model tekstu z autouse fixture; teksty A+ z `GOOD`."""
    fake_text_provider.routes["_AplusTexts"] = GOOD
    return fake_text_provider


@pytest.fixture
def book(monkeypatch: pytest.MonkeyPatch, text: FakeTextProvider) -> Path:
    """Gotowa książka z okładką bez koloru (bez API)."""
    monkeypatch.setattr(cli, "cmyk_converter", lambda settings: NaiveConverter())
    assert main([*GENERATE, "--pages", "10"]) == ExitCode.OK
    assert main(["cover", ARG, "--no-color", "--no-select-pages"]) == ExitCode.OK
    return BOOK_DIR


def _manifest() -> dict[str, Any]:
    data = json.loads((BOOK_DIR / "manifest.json").read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def _aplus_calls(provider: FakeTextProvider) -> int:
    return sum(1 for c in provider.calls if c.schema.__name__ == "_AplusTexts")


# --- Polecenie -----------------------------------------------------------------------------


def test_aplus_needs_the_cover(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([*GENERATE, "--pages", "10"]) == ExitCode.OK
    capsys.readouterr()
    assert main(["aplus", ARG]) == ExitCode.VALIDATION_ERROR
    assert "brak gotowej okładki (FR-15)" in capsys.readouterr().err
    assert not (BOOK_DIR / "aplus").exists()


def test_aplus_writes_images_texts_and_preview(
    book: Path, text: FakeTextProvider, capsys: pytest.CaptureFixture[str]
) -> None:
    before = _manifest()["cost_usd"]
    capsys.readouterr()
    assert main(["aplus", ARG]) == ExitCode.OK
    captured = capsys.readouterr()
    assert "w jej miejscu drugi mockup" in captured.err  # bez książek do tabeli porównawczej
    assert "logo: pominięty (brak banera" in captured.out
    names = sorted(p.name for p in (book / "aplus").iterdir())
    assert names == [
        "02_header_fan.jpg",
        "03_overlay_facts.jpg",
        "04_features_1.jpg",
        "04_features_2.jpg",
        "04_features_3.jpg",
        "05_header_pages.jpg",
        "texts.yaml",
    ]
    sizes = {
        "02_header_fan.jpg": (1940, 1200),
        "03_overlay_facts.jpg": (1940, 600),
        "04_features_1.jpg": (600, 600),
        "05_header_pages.jpg": (1940, 1200),
    }
    for name, size in sizes.items():
        path = book / "aplus" / name
        with Image.open(path) as image:
            assert (image.size, image.mode, image.format) == (size, "RGB", "JPEG")
        assert path.stat().st_size < 2 * 1024 * 1024
    data = _manifest()
    aplus = data["aplus"]
    assert [m["name"] for m in aplus["modules"]] == [
        "logo",
        "header_fan",
        "overlay_facts",
        "features",
        "header_pages",
    ]
    assert aplus["modules"][0]["skipped"].startswith("brak banera")
    assert (
        aplus["background"]["name"] in load_config().settings.aplus.header_fan.background.candidates
    )
    assert aplus["texts"]["features"]["columns"][0]["headline"] == "Bold lines"
    items = aplus["texts"]["overlay_facts"]["items"]
    assert items[0].startswith("10 single-sided coloring pages")  # fakty z manifestu, nie z modelu
    assert aplus["cost_usd"] > 0 and data["cost_usd"] == pytest.approx(before + aplus["cost_usd"])
    assert _aplus_calls(text) == 1
    texts = yaml.safe_load((book / "aplus" / "texts.yaml").read_text(encoding="utf-8"))
    assert texts["header_fan"]["headline"] == "Dinosaurs to Color"
    page = (book / "aplus.html").read_text(encoding="utf-8")
    assert page.count('data-copy="') >= 10 and "aplus/02_header_fan.jpg" in page
    assert "lista numerowaną" not in page and "listę numerowaną" in page


def test_rerun_reuses_images_and_texts(
    book: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["aplus", ARG]) == ExitCode.OK
    first = _manifest()["aplus"]
    capsys.readouterr()

    def no_text_provider(name: str, model: str) -> FakeTextProvider:
        raise AssertionError("bez zmian teksty nie wymagają modelu")

    monkeypatch.setattr(cli, "create_text_provider", no_text_provider)
    assert main(["aplus", ARG]) == ExitCode.OK
    out = capsys.readouterr().out
    assert "(aktualne, bez zmian)" in out and "Teksty A+: zapisane" in out
    second = _manifest()["aplus"]
    assert second["images_sha256"] == first["images_sha256"]
    assert second["cost_usd"] == first["cost_usd"]


def test_hand_edited_texts_are_kept(book: Path, text: FakeTextProvider) -> None:
    assert main(["aplus", ARG]) == ExitCode.OK
    path = book / "aplus" / "texts.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["header_fan"]["headline"] = "My own headline"
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    assert main(["aplus", ARG]) == ExitCode.OK
    aplus = _manifest()["aplus"]
    assert aplus["texts_edited"] is True
    assert aplus["texts"]["header_fan"]["headline"] == "My own headline"
    assert _aplus_calls(text) == 1
    assert "My own headline" in (book / "aplus.html").read_text(encoding="utf-8")


def test_broken_texts_file_is_exit_1(book: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["aplus", ARG]) == ExitCode.OK
    (book / "aplus" / "texts.yaml").write_text("header_fan: {headlien: x}\n", encoding="utf-8")
    capsys.readouterr()
    assert main(["aplus", ARG]) == ExitCode.VALIDATION_ERROR
    assert "zły format tekstów A+" in capsys.readouterr().err


def test_banned_phrases_retry_once(book: Path, text: FakeTextProvider) -> None:
    answers = iter([BAD, GOOD])
    text.routes["_AplusTexts"] = lambda system, user: next(answers)
    assert main(["aplus", ARG]) == ExitCode.OK
    calls = [c for c in text.calls if c.schema.__name__ == "_AplusTexts"]
    assert len(calls) == 2
    assert "broke the A+ rules" in calls[1].user and "„perfect”" in calls[1].user
    assert not any(w.startswith("teksty A+") for w in _manifest()["aplus"]["warnings"])


def test_banned_phrases_twice_are_warnings(
    book: Path, text: FakeTextProvider, capsys: pytest.CaptureFixture[str]
) -> None:
    text.routes["_AplusTexts"] = BAD
    capsys.readouterr()
    assert main(["aplus", ARG]) == ExitCode.OK
    err = capsys.readouterr().err
    assert "teksty A+: przechwałka: „perfect”" in err
    assert "teksty A+: nacisk czasem: „now”" in err
    assert _aplus_calls(text) == 2


def test_alt_text_for_every_image(book: Path, text: FakeTextProvider) -> None:
    assert main(["aplus", ARG]) == ExitCode.OK
    call = next(c for c in text.calls if c.schema.__name__ == "_AplusTexts")
    assert "Image header_fan: The front and back covers" in call.user
    assert "Image features_1: A black-and-white coloring page from the book:" in call.user
    assert "screen readers" in call.system and "alt text 99" in call.system
    texts = yaml.safe_load((book / "aplus" / "texts.yaml").read_text(encoding="utf-8"))
    keys = ["header_fan", "overlay_facts", "features_1", "features_2", "features_3"]
    assert sorted(texts["alt"]) == sorted([*keys, "header_pages"])
    aplus = _manifest()["aplus"]
    assert aplus["texts"]["alt"]["features_1"] == "Coloring page with a dinosaur by a volcano"
    assert not any("tekstu alternatywnego" in w for w in aplus["warnings"])
    page = (book / "aplus.html").read_text(encoding="utf-8")
    assert 'alt="Coloring page with a dinosaur by a volcano"' in page
    assert page.count("Tekst alternatywny") >= 6


def test_missing_alt_text_is_a_warning(
    book: Path, text: FakeTextProvider, capsys: pytest.CaptureFixture[str]
) -> None:
    alts = [a for a in GOOD["alt_texts"] if a["image"] != "features_2"]
    alts.append({"image": "made_up", "text": "Something else"})
    text.routes["_AplusTexts"] = {**GOOD, "alt_texts": alts}
    capsys.readouterr()
    assert main(["aplus", ARG]) == ExitCode.OK
    assert "brak tekstu alternatywnego: features_2" in capsys.readouterr().err
    texts = _manifest()["aplus"]["texts"]["alt"]
    assert "made_up" not in texts and "features_2" not in texts
    assert "Brak tekstu alternatywnego" in (book / "aplus.html").read_text(encoding="utf-8")


def test_logo_alt_text_comes_from_settings(
    book: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    logo = tmp_path / "logo.png"
    Image.new("RGB", (600, 180), (30, 60, 90)).save(logo)
    settings_path = Path(os.environ["KDP_STUDIO_CONFIG_DIR"]) / "settings.yaml"
    settings = yaml.safe_load(settings_path.read_text(encoding="utf-8"))
    settings["aplus"]["logo"] = str(logo)
    settings_path.write_text(yaml.safe_dump(settings, allow_unicode=True), encoding="utf-8")
    capsys.readouterr()
    assert main(["aplus", ARG]) == ExitCode.OK
    assert "brak tekstu alternatywnego: logo (baner: ustaw aplus.logo_alt)" in (
        capsys.readouterr().err
    )
    settings["aplus"]["logo_alt"] = "Mira Blue coloring books logo"
    settings_path.write_text(yaml.safe_dump(settings, allow_unicode=True), encoding="utf-8")
    assert main(["aplus", ARG]) == ExitCode.OK
    aplus = _manifest()["aplus"]
    assert aplus["texts"]["alt"]["logo"] == "Mira Blue coloring books logo"
    assert not any("tekstu alternatywnego" in w for w in aplus["warnings"])
    assert 'alt="Mira Blue coloring books logo"' in (book / "aplus.html").read_text(
        encoding="utf-8"
    )


def test_comparison_chart_from_other_manifests(
    book: Path, text: FakeTextProvider, tmp_path: Path
) -> None:
    other = ["generate", "--theme", "Kotki", "--age", "przedszkole", "--style", "kawaii"]
    assert main([*other, "--pages", "12"]) == ExitCode.OK
    path = tmp_path / "k.yaml"
    entries = [{"asin": "B0TEST0001", "book": "output/kotki_przedszkole_kawaii_letter"}]
    path.write_text(yaml.safe_dump({"aplus": {"comparison": entries}}), encoding="utf-8")
    assert main(["aplus", ARG, "--config-file", str(path)]) == ExitCode.OK
    aplus = _manifest()["aplus"]
    assert [m["name"] for m in aplus["modules"]][-1] == "comparison"
    chart = aplus["chart"]
    assert [c["asin"] for c in chart] == [None, "B0TEST0001"]
    assert chart[1]["rows"]["Coloring pages"] == "12"
    assert "Age" in chart[0]["rows"] and "8.5 × 11 in" in chart[0]["rows"]["Page size"]
    assert "B0TEST0001" in (book / "aplus.html").read_text(encoding="utf-8")


def test_color_page_uses_the_image_model_once(book: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeImageProvider(size=(64, 80))
    monkeypatch.setattr(cli, "create_image_provider", lambda name, model: fake)
    assert main(["aplus", ARG, "--color-page"]) == ExitCode.OK
    assert len(fake.requests) == 1 and fake.requests[0].reference_image is not None
    color = _manifest()["aplus"]["color_page"]
    assert (book / color["raw"]).is_file()
    assert main(["aplus", ARG, "--color-page"]) == ExitCode.OK
    assert len(fake.requests) == 1  # ta sama strona: bez nowego kolorowania


# --- Teksty ----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "hit"),
    [
        ("Christmas coloring book with Santa, reindeer and gingerbread houses", None),
        ("Calm, screen-free fun for kids", None),
        ("Get it in time for Christmas", "święto"),
        ("The perfect Christmas gift for kids", "przechwałka"),
        ("A Christmas present for little artists", "święto"),
        ("Stocking stuffer with dinosaurs", "święto"),
        ("Fun for the holidays", "święto"),
        ("Our best book yet", "przechwałka"),
        ("Available now", "nacisk czasem"),
        ("Bonus pages inside", "sprzedaż"),
    ],
)
def test_banned_phrases(repo_config: AppConfig, text: str, hit: str | None) -> None:
    banned = repo_config.markets.aplus_texts["en"].banned
    hits = banned_hits([text], banned)
    if hit is None:
        assert hits == []
    else:
        assert any(h.startswith(hit) for h in hits), hits


def test_polish_holiday_as_occasion(repo_config: AppConfig) -> None:
    banned = repo_config.markets.aplus_texts["pl"].banned
    assert banned_hits(["Kolorowanka na święta dla dzieci"], banned)
    assert banned_hits(["Kolorowanka z Mikołajem i reniferami"], banned) == []


def test_limits_clip_and_drop_facts(repo_config: AppConfig) -> None:
    limits = repo_config.settings.aplus.limits
    copy = AplusCopy(
        overlay_facts=OverlayCopy(headline="x" * 80, items=["a" * 200, "b" * 90, "c" * 50]),
        features=FeaturesCopy(columns=[ColumnCopy(headline="h", body="word " * 300)]),
    )
    fitted, warnings = apply_limits(copy, limits)
    assert fitted.overlay_facts is not None and fitted.features is not None
    assert len(fitted.overlay_facts.headline) <= 60
    assert fitted.overlay_facts.items == ["a" * 200, "b" * 90]
    assert len(fitted.features.columns[0].body) <= 1000
    assert any("pominięto" in w for w in warnings) and any("przycięto" in w for w in warnings)


def test_alt_texts_are_clipped_checked_and_unique(repo_config: AppConfig) -> None:
    copy = AplusCopy(alt={"header_fan": "word " * 40, "features_1": "Best coloring book ever"})
    fitted, warnings = apply_limits(copy, repo_config.settings.aplus.limits)
    assert len(fitted.alt["header_fan"]) <= 99
    assert any(w.startswith("alt.header_fan:") for w in warnings)
    banned = repo_config.markets.aplus_for("en-US")
    assert banned is not None
    assert any("„best”" in i for i in copy_issues(copy, banned.banned))
    same = AplusCopy(alt={"features_1": "A cat", "features_2": "a cat"})
    assert alt_issues(same, ["features_1", "features_2", "features_3"]) == [
        "brak tekstu alternatywnego: features_3",
        "ten sam tekst alternatywny: features_1 i features_2",
    ]


def test_clip_cuts_at_a_word() -> None:
    assert clip("one two three four", 9) == "one two"
    assert clip("short", 10) == "short"


# --- Grafiki ---------------------------------------------------------------------------------


def _solid(rgb: tuple[int, int, int], size: tuple[int, int] = (300, 300)) -> Image.Image:
    return Image.new("RGB", size, rgb)


def test_background_avoids_the_cover_colors(repo_config: AppConfig) -> None:
    settings = repo_config.settings.aplus.header_fan.background
    rose = settings.candidates["pudrowy róż"]
    choice = ai.pick_background([_solid(rose), _solid(rose)], settings)
    assert choice.name != "pudrowy róż" and choice.darkened_steps == 0
    assert choice.scores["pudrowy róż"] < 1


def test_background_is_darkened_below_threshold(repo_config: AppConfig) -> None:
    settings = repo_config.settings.aplus.header_fan.background.model_copy(
        update={"min_delta_e": 30}
    )
    covers = [_solid(rgb) for rgb in settings.candidates.values()]
    choice = ai.pick_background(covers, settings)
    assert choice.darkened_steps > 0 and choice.delta_e >= 30
    base = settings.candidates[choice.name]
    assert all(c < b for c, b in zip(choice.rgb, base, strict=True))


def test_back_book_has_a_shaded_spine_edge() -> None:
    face = _solid((255, 255, 255), (200, 200))
    spine = _solid((200, 40, 40), (10, 200))
    book = ai.flat_book(face, 200, 0, 0.05, spine, 0.85)
    edge = np.asarray(book)[50:150, 202:208, :3]
    assert np.allclose(edge.mean(axis=(0, 1)), (170, 34, 34), atol=3)
    front = ai.flat_book(face, 200, 0, 0.05)
    page_edge = {tuple(px) for px in np.asarray(front)[100, 201:209, :3].tolist()}
    assert page_edge <= {ai.PAGE_BLOCK_RGB, ai.PAGE_LINE_RGB}  # przód: kartki, nie grzbiet


def test_shadow_is_not_cut_at_the_edge() -> None:
    item = Image.new("RGBA", (100, 100), (255, 255, 255, 255))
    shadow, pad = ai.drop_shadow(item, 10, 0.5)
    alpha = np.asarray(shadow.getchannel("A"))
    assert pad == 30 and alpha.shape == (160, 160)
    assert alpha[0].max() == 0 and alpha[-1].max() == 0 and alpha[:, 0].max() == 0


@pytest.mark.parametrize("side", ["right", "left"])
def test_overlay_strip_leaves_the_text_box_empty(repo_config: AppConfig, side: str) -> None:
    """Na komputerze Amazon kładzie ramkę z tekstem nakładki na obrazie (domyślnie po prawej),
    więc strony trafiają na drugą stronę, a pod ramką jest samo tło."""
    overlay = repo_config.settings.aplus.overlay_facts.model_copy(update={"text_side": side})
    page = Image.new("RGB", (300, 300), "white")
    ImageDraw.Draw(page).rectangle((40, 40, 260, 260), outline="black", width=12)
    strip = ai.overlay_strip(
        [page] * 3, (200, 212, 190), repo_config.settings.aplus.header_fan, (1940, 600), overlay
    )
    gray = np.asarray(strip.convert("L"), dtype=np.int16)
    box = int(1940 * overlay.text_width)
    under_box = gray[:, -box:] if side == "right" else gray[:, :box]
    pages = gray[:, :-box] if side == "right" else gray[:, box:]
    assert under_box.min() > 150  # tylko jasne tło, bez konturów stron
    assert pages.min() < 60  # kontury stron po drugiej stronie
    left, _, right, _ = ai.overlay_region((1940, 600), overlay)
    assert right - left > 1940 * 0.6


def test_fan_header_fills_the_frame(repo_config: AppConfig) -> None:
    fan = repo_config.settings.aplus.header_fan
    front, back = _solid((20, 120, 200)), _solid((40, 160, 60))
    image = ai.fan_header(
        front, back, _solid((40, 160, 60), (8, 300)), (232, 206, 200), fan, (970, 600)
    )
    assert image.size == (970, 600) and image.mode == "RGB"
    pixels = np.asarray(image)
    assert tuple(pixels[5, 960]) != (20, 120, 200)  # prawy górny róg: tło, bez okładki
    assert (np.abs(pixels.astype(int) - (20, 120, 200)).sum(axis=2) < 30).mean() > 0.2


def test_save_image_lowers_jpeg_quality_and_rejects_huge_png(tmp_path: Path) -> None:
    rng = np.random.default_rng(1)
    noise = Image.fromarray(rng.integers(0, 255, (1200, 1940, 3), dtype=np.uint8), "RGB")
    settings = AplusSettings(max_file_mb=1.0)
    saved = ai.save_image(noise, tmp_path / "a.jpg", settings)
    assert saved.bytes < 1024 * 1024
    with pytest.raises(ai.AplusImageError, match="poniżej"):
        ai.save_image(
            noise, tmp_path / "a.png", settings.model_copy(update={"image_format": "png"})
        )


def test_logo_is_converted_and_checked(tmp_path: Path) -> None:
    source = tmp_path / "logo.png"
    Image.new("RGBA", (600, 300), (10, 20, 30, 255)).save(source)
    saved, warnings = ai.prepare_logo(source, tmp_path / "01_logo.jpg", AplusSettings())
    with Image.open(saved.path) as image:
        assert image.mode == "RGB"
    assert any("proporcji" in w for w in warnings)


# --- Konfiguracja ----------------------------------------------------------------------------


SIX_MODULES = ("logo", "header_fan", "overlay_facts", "features", "comparison", "header_pages")


@pytest.mark.parametrize(
    ("aplus", "message"),
    [
        (
            {
                "modules": [
                    "logo",
                    "header_fan",
                    "overlay_facts",
                    "features",
                    "comparison",
                    "header_pages",
                ]
            },
            "najwyżej 5",
        ),
        ({"modules": ["logo", "logo"]}, "powtórzony"),
        ({"modules": ["banner"]}, "modules"),
        (
            {"comparison": {"books": [{"asin": f"B0TEST000{i}", "book": "x"} for i in range(7)]}},
            "comparison",
        ),
        ({"comparison": {"books": [{"asin": "bad", "book": "x"}]}}, "asin"),
    ],
)
def test_aplus_config_validation(
    config_dir: ConfigDirFactory, aplus: dict[str, Any], message: str
) -> None:
    directory = config_dir(settings=fake_settings(aplus=aplus))
    with pytest.raises(ConfigError, match=message):
        load_config(directory)
