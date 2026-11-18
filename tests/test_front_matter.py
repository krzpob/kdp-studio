"""FR-23: strony wstępne: strona 1, prawa autorskie, instrukcja."""

from __future__ import annotations

import copy
import io
import json
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pytest
import yaml
from PIL import Image, ImageDraw

from kdp_studio import cli
from kdp_studio.cli import ExitCode, main
from kdp_studio.config import DEFAULT_CONFIG_DIR, AppConfig, ConfigError, load_config
from kdp_studio.pipeline.front_matter import (
    FrontMatterError,
    book_year,
    copyright_paragraphs,
    front_texts,
    render_copyright,
)
from kdp_studio.pipeline.postprocess import PageGeometry, PostprocessError, verify_page
from kdp_studio.providers.base import ImageRequest, ImageResult, ProviderError, Usage
from kdp_studio.providers.fake import FakeImageProvider
from tests.conftest import ConfigDirFactory, fake_settings
from tests.test_belongs_to import _formats
from tests.test_cli import fake_text_provider  # noqa: F401  (autouse: fałszywi dostawcy)

IDEAS = ["ideas", "--theme", "Dinozaury", "--age", "przedszkole", "--style", "kawaii"]
GENERATE = ["generate", *IDEAS[1:]]
BOOK = Path("output/dinozaury_przedszkole_kawaii_letter")
ARG = str(BOOK)


def _manifest() -> dict[str, Any]:
    data = json.loads((BOOK / "manifest.json").read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def _png(draw: Any, size: tuple[int, int] = (96, 128)) -> bytes:
    img = Image.new("L", size, 255)
    draw(ImageDraw.Draw(img), size)
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    return buffer.getvalue()


def _scene_low(d: ImageDraw.ImageDraw, size: tuple[int, int]) -> None:
    """Scena w dolnej części: górny pas zostaje pusty na tytuł."""
    w, h = size
    d.rectangle((8, h // 2, w - 9, h - 9), outline=0, width=4)


def _scene_full(d: ImageDraw.ImageDraw, size: tuple[int, int]) -> None:
    w, h = size
    d.rectangle((4, 4, w - 5, h - 5), outline=0, width=4)


@dataclass
class FrontMatterProvider:
    """Strony jak FakeImageProvider; strona tytułowa i ilustracja instrukcji z FR-23."""

    title_blank: bool = True
    instructions_error: ProviderError | None = None
    name: str = "fake"
    model: str = "fake-image"
    pages: FakeImageProvider = field(default_factory=FakeImageProvider)
    title_requests: list[ImageRequest] = field(default_factory=list)
    instructions_requests: list[ImageRequest] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def supported_aspects(self) -> list[str]:
        return self.pages.supported_aspects()

    def generate(self, req: ImageRequest) -> ImageResult:
        usage = Usage(input_tokens=10, output_tokens=100)
        if "the title will be added later" in req.prompt:
            with self._lock:
                self.title_requests.append(req)
            png = _png(_scene_low if self.title_blank else _scene_full)
            return ImageResult(png, 96, 128, usage)
        if "slips a blank sheet" in req.prompt:
            with self._lock:
                self.instructions_requests.append(req)
            if self.instructions_error is not None:
                raise self.instructions_error
            return ImageResult(_png(_scene_full, (128, 96)), 128, 96, usage)
        return self.pages.generate(req)


@pytest.fixture
def provider(monkeypatch: pytest.MonkeyPatch) -> FrontMatterProvider:
    fake = FrontMatterProvider()
    monkeypatch.setattr(cli, "create_image_provider", lambda name, model: fake)
    return fake


def _settings(config_dir: ConfigDirFactory, **front_matter: Any) -> None:
    settings = fake_settings()
    settings["front_matter"].update(front_matter)
    config_dir(formats=_formats(), settings=settings)


# --- Teksty --------------------------------------------------------------------------------


def test_texts_follow_the_market_locale(repo_config: AppConfig) -> None:
    us, uk, ca = (front_texts(repo_config, m) for m in ("US", "UK", "CA"))
    assert (us.language, uk.language, ca.language) == ("en", "en-GB", "en")
    assert "coloring journey" in us.instructions["intro"]
    assert "colouring journey" in uk.instructions["intro"]  # en-GB: tylko różnice z en
    assert uk.copyright == us.copyright  # prawa autorskie wspólne z en
    assert "colouring" in ca.instructions["body"]  # pisownia rynku (FR-19) w tekstach
    assert front_texts(repo_config, "PL").instructions["heading"] == "ZANIM ZACZNIESZ"
    assert front_texts(repo_config, "DE").language == "de"
    with pytest.raises(FrontMatterError, match=r"brak tekstów stron wstępnych.*rynku FR"):
        front_texts(repo_config, "FR")


@pytest.mark.parametrize("variant", ["minimal", "short", "full"])
def test_copyright_variants(repo_config: AppConfig, variant: str) -> None:
    texts = front_texts(repo_config, "PL")
    paragraphs = copyright_paragraphs(texts, variant, 2026, "  Kasia K.  ")
    assert paragraphs[0] == "© 2026 Kasia K.. Wszelkie prawa zastrzeżone."
    assert len(paragraphs) == (1 if variant == "minimal" else 2)
    assert book_year("2026-11-18T10:00:00+00:00") == 2026


def _markets_yaml() -> dict[str, Any]:
    data = yaml.safe_load((DEFAULT_CONFIG_DIR / "markets.yaml").read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda d: d["texts"]["pl"]["copyright"].pop("full"), "wymagane warianty"),
        (
            lambda d: d["texts"]["pl"]["copyright"].update(minimal="© {rok} {owner}"),
            "nieznane pole 'rok'",
        ),
        (lambda d: d["texts"]["de"]["instructions"].pop("section"), "brak section"),
        (lambda d: d["texts"]["en"]["instructions"].update(extra="x"), "nieznane klucze extra"),
        (lambda d: d["texts"]["en"]["instructions"].update(body="x {owner}"), "nie ma wstawek"),
    ],
)
def test_bad_texts_are_a_config_error(
    config_dir: ConfigDirFactory, change: Any, message: str
) -> None:
    data = copy.deepcopy(_markets_yaml())
    change(data)
    with pytest.raises(ConfigError, match=message):
        load_config(config_dir(markets=data))


# --- Strona praw autorskich ------------------------------------------------------------------


def _geometry() -> PageGeometry:
    return PageGeometry(page_px=(850, 1100), dpi=100, margin_in=0.5)  # letter, 100 DPI


def test_copyright_sits_above_the_bottom_margin(repo_config: AppConfig, tmp_path: Path) -> None:
    texts = front_texts(repo_config, "US")
    paragraphs = copyright_paragraphs(texts, "full", 2026, "Test Owner")
    geometry = _geometry()
    path = render_copyright(tmp_path, geometry, repo_config.settings.front_matter, paragraphs)
    assert verify_page(path, geometry) == []
    with Image.open(path) as img:
        ys, xs = np.nonzero(np.asarray(img) == 0)
    left, top, _right, bottom = geometry.content_box
    assert ys.max() > bottom - 0.08 * (bottom - top)  # blok stoi na dole obszaru treści
    assert ys.min() > top + (bottom - top) / 2
    assert xs.min() >= left


def test_copyright_shrinks_then_fails(repo_config: AppConfig, tmp_path: Path) -> None:
    settings = repo_config.settings.front_matter
    long = ["Lorem ipsum dolor sit amet " * 40] * 6
    geometry = _geometry()
    path = render_copyright(
        tmp_path, geometry, settings.model_copy(update={"copyright_pt": 30}), long[:1]
    )
    assert verify_page(path, geometry) == []
    with pytest.raises(PostprocessError, match="nie mieści się"):
        render_copyright(tmp_path, geometry, settings, long * 6)


# --- CLI: ideas, generate, finalize ----------------------------------------------------------


def test_new_book_needs_a_copyright_owner(
    config_dir: ConfigDirFactory, capsys: pytest.CaptureFixture[str]
) -> None:
    settings = fake_settings()
    settings["publisher"]["copyright_owner"] = None
    config_dir(settings=settings)
    assert main([*IDEAS, "--pages", "12"]) == ExitCode.VALIDATION_ERROR
    assert "brak właściciela praw autorskich" in capsys.readouterr().err
    assert not BOOK.exists()  # przed pierwszym wywołaniem API
    args = [*IDEAS, "--pages", "12", "--copyright-owner", "Kasia K.", "--copyright", "full"]
    assert main(args) == ExitCode.OK
    data = _manifest()["input"]
    assert (data["copyright_owner"], data["copyright"]) == ("Kasia K.", "full")
    assert main([*IDEAS, "--pages", "12", "--copyright", "long"]) == ExitCode.VALIDATION_ERROR


def test_finalize_makes_title_only_page_and_copyright(
    provider: FrontMatterProvider, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main([*GENERATE, "--pages", "3"]) == ExitCode.OK  # bez kroku front-matter
    out = capsys.readouterr().out
    assert "Strona 1 bez modelu: sam tytuł (front_title.png)" in out
    matter = _manifest()["front_matter"]
    assert (matter["title"]["layout"], matter["title"]["status"]) == ("text_only", "ok")
    assert matter["copyright"]["status"] == "ok" and matter["copyright"]["language"] == "en"
    assert matter["instructions"] is None
    assert (BOOK / "front_title.png").is_file() and (BOOK / "front_copyright.png").is_file()
    assert provider.title_requests == []
    canva = (BOOK / "canva.md").read_text(encoding="utf-8")
    assert "| 1 | `front_title.png` |" in canva and "| 2 | `front_copyright.png` |" in canva
    # Drugi finalize: wszystko aktualne, bez ponownej obróbki stron wstępnych.
    assert main(["finalize", ARG]) == ExitCode.OK
    assert "front_copyright: ok" not in capsys.readouterr().out


def test_generate_with_front_matter_and_instructions(
    provider: FrontMatterProvider, config_dir: ConfigDirFactory
) -> None:
    _settings(config_dir, instructions=True, in_generate=True)
    assert main([*GENERATE, "--pages", "3", "--first-page", "title"]) == ExitCode.OK
    data = _manifest()
    assert data["input"]["front_matter_pages"] == 4
    assert data["layout"]["pages_in_book"] == 3 * 2 + 4
    matter = data["front_matter"]
    assert (matter["title"]["layout"], matter["title"]["status"]) == ("frame", "ok")
    assert (matter["instructions"]["layout"], matter["instructions"]["status"]) == ("frame", "ok")
    assert matter["belongs_to"] is None and matter["copyright"]["status"] == "ok"
    assert len(provider.title_requests) == 1 and len(provider.instructions_requests) == 1
    assert "a friendly dinosaur slips a blank sheet" in provider.instructions_requests[0].prompt
    for name in ("front_title", "front_copyright", "front_instructions"):
        assert (BOOK / f"{name}.png").is_file()
    canva = (BOOK / "canva.md").read_text(encoding="utf-8")
    assert "| 3 | `front_instructions.png` |" in canva and "| 4 | pusta |" in canva
    assert "| 5 | `page_01.png` |" in canva
    assert data["status"] == "completed"


def test_instructions_fall_back_to_the_svg(
    provider: FrontMatterProvider, config_dir: ConfigDirFactory
) -> None:
    provider.instructions_error = ProviderError("moderacja", fatal=False)
    _settings(config_dir, instructions=True, in_generate=True)
    assert main([*GENERATE, "--pages", "3"]) == ExitCode.OK
    instructions = _manifest()["front_matter"]["instructions"]
    assert (instructions["layout"], instructions["fallback_source"]) == (
        "fallback",
        "instructions.svg",
    )
    assert len(provider.instructions_requests) == 3  # 1 + max_retries
    assert (BOOK / "front_instructions.png").is_file()


def test_front_matter_command_switches_pages(
    provider: FrontMatterProvider, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main([*GENERATE, "--pages", "3"]) == ExitCode.OK
    assert main(["front-matter", ARG, "--first-page", "title", "--instructions"]) == ExitCode.OK
    data = _manifest()
    assert data["input"]["front_matter_pages"] == 4
    assert data["front_matter"]["title"]["layout"] == "frame"
    assert data["front_matter"]["instructions"]["status"] == "ok"
    assert main(["finalize", ARG]) == ExitCode.OK
    assert _manifest()["layout"]["pages_in_book"] == 3 * 2 + 4
    # Bez instrukcji: 2 strony wstępne, plik instrukcji znika z książki.
    capsys.readouterr()
    assert main(["front-matter", ARG, "--no-instructions"]) == ExitCode.OK
    assert "Strony wstępne: 2" in capsys.readouterr().out
    data = _manifest()
    assert data["input"]["front_matter_pages"] == 2 and data["front_matter"]["instructions"] is None
    assert not (BOOK / "front_instructions.png").exists()
    assert len(provider.title_requests) == 1  # strona tytułowa aktualna, bez nowej grafiki
    # belongs-to jako strona 1 usuwa tytułową.
    assert main(["front-matter", ARG, "--first-page", "belongs-to"]) == ExitCode.OK
    matter = _manifest()["front_matter"]
    assert matter["title"] is None and matter["belongs_to"]["status"] == "ok"


def test_owner_change_rerenders_copyright_without_api(
    provider: FrontMatterProvider, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main([*GENERATE, "--pages", "3"]) == ExitCode.OK
    before = (BOOK / "front_copyright.png").read_bytes()
    data = _manifest()
    data["input"]["copyright_owner"] = "Inna Firma Sp. z o.o."
    (BOOK / "manifest.json").write_text(json.dumps(data), encoding="utf-8")
    requests = len(provider.pages.requests)
    capsys.readouterr()
    assert main(["finalize", ARG]) == ExitCode.OK
    assert "front_copyright: ok (en, short)" in capsys.readouterr().out
    assert (BOOK / "front_copyright.png").read_bytes() != before
    assert _manifest()["front_matter"]["copyright"]["owner"] == "Inna Firma Sp. z o.o."
    assert len(provider.pages.requests) == requests


def test_front_matter_needs_raw_pages(
    provider: FrontMatterProvider, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main([*IDEAS, "--pages", "12"]) == ExitCode.OK
    assert main(["front-matter", ARG]) == ExitCode.VALIDATION_ERROR
    assert "najpierw kdp-studio images" in capsys.readouterr().err
    assert provider.title_requests == []


def test_qa_criteria_for_title_and_instructions(repo_config: AppConfig) -> None:
    from kdp_studio.models import BookSpec
    from kdp_studio.pipeline.qa import instructions_page_instructions, title_page_instructions

    spec = BookSpec(
        theme="T", age="przedszkole", style="kawaii", format="square", pages=3,
        front_matter_pages=4,
    )  # fmt: skip
    title = title_page_instructions(spec, repo_config, ["dinosaur"], "Dino Friends")
    assert '"Dino Friends" at the top of the page, which the program adds on purpose' in title
    instructions = instructions_page_instructions(spec, repo_config, "dinosaur")
    assert "printed instructions at the top of the page" in instructions
    assert "slips a blank sheet of thick paper" in instructions
