"""FR-15: `generate --cover`, okładka jako ostatni krok generowania książki."""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from kdp_studio import cli
from kdp_studio.cli import ExitCode, main
from kdp_studio.config import AppConfig, ConfigError
from kdp_studio.pipeline.cmyk import NaiveConverter
from kdp_studio.providers.base import ImageRequest, ImageResult, ProviderError
from kdp_studio.providers.fake import FakeImageProvider, FakeVisionProvider
from tests.conftest import ConfigDirFactory, CoverVision, fake_settings
from tests.test_cli import fake_text_provider  # noqa: F401  (autouse: fałszywi dostawcy)
from tests.test_cover_front import ColoringProvider

GENERATE = ["generate", "--theme", "Dinozaury", "--age", "przedszkole", "--style", "kawaii"]
BOOK = Path("output/dinozaury_przedszkole_kawaii_letter")


@dataclass
class PagesAndCover:
    """Strony z FakeImageProvider, okładka (zapytania z reference_image) z ColoringProvider."""

    pages: FakeImageProvider = field(default_factory=FakeImageProvider)
    cover: ColoringProvider = field(default_factory=ColoringProvider)
    name: str = "fake"
    model: str = "fake-image"

    def supported_aspects(self) -> list[str]:
        return self.pages.supported_aspects()

    def generate(self, req: ImageRequest) -> ImageResult:
        if req.reference_image is None:
            return self.pages.generate(req)
        return self.cover.generate(req)


@pytest.fixture
def providers(monkeypatch: pytest.MonkeyPatch) -> tuple[PagesAndCover, CoverVision]:
    monkeypatch.setattr(cli, "cmyk_converter", lambda settings: NaiveConverter())
    images = PagesAndCover()
    monkeypatch.setattr(cli, "create_image_provider", lambda name, model: images)
    responder = CoverVision()
    vision = FakeVisionProvider(responder)
    monkeypatch.setattr(cli, "create_vision_provider", lambda name, model: vision)
    return images, responder


def _manifest() -> dict[str, Any]:
    data = json.loads((BOOK / "manifest.json").read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def test_generate_cover_runs_cover_last(
    providers: tuple[PagesAndCover, CoverVision], capsys: pytest.CaptureFixture[str]
) -> None:
    images, responder = providers
    assert main([*GENERATE, "--pages", "6", "--cover"]) == ExitCode.OK
    out = capsys.readouterr().out
    # Wybór stron modelem z wizją, kolorowy przód i tył z grzbietem dorysowany do przodu.
    assert responder.calls == ["select"]
    assert len(images.cover.requests) == 2
    data = _manifest()
    cover = data["cover"]
    assert cover["status"] == "ok"
    assert cover["selection"] == "vision"
    assert cover["front_page"] == "page_03"
    assert cover["thumbnails"] == ["page_01", "page_05", "page_06"]
    assert (BOOK / "cover" / "cover.pdf").is_file()
    # Koszt okładki to tylko jej część wydatków uruchomienia; manifest ma sumę wszystkiego.
    pages_cost = sum(p["cost_usd"] for p in data["pages"])
    assert 0 < cover["cost_usd"] < data["cost_usd"]
    assert data["cost_usd"] == pytest.approx(
        data["ideas"]["cost_usd"] + pages_cost + cover["cost_usd"], abs=1e-5
    )
    assert "Czas kroku (okładka)" in out
    assert "okładka" in out.split("Czas: ")[-1]
    assert out.index("Okładka do KDP:") < out.index("Strony: 6/6 gotowe")


def test_generate_without_cover_flag_makes_no_cover(
    providers: tuple[PagesAndCover, CoverVision],
) -> None:
    _, responder = providers
    assert main([*GENERATE, "--pages", "6"]) == ExitCode.OK
    assert _manifest().get("cover") is None
    assert not (BOOK / "cover").exists()
    assert responder.calls == []


def _settings_with_cover(config_dir: ConfigDirFactory, **cover: Any) -> None:
    settings = fake_settings()
    settings["cover"].update(cover)
    config_dir(settings=settings)


def test_generate_cover_default_from_settings(
    providers: tuple[PagesAndCover, CoverVision], config_dir: ConfigDirFactory
) -> None:
    _settings_with_cover(config_dir, in_generate=True)
    assert main([*GENERATE, "--pages", "6"]) == ExitCode.OK
    assert _manifest()["cover"]["status"] == "ok"
    shutil.rmtree(BOOK)
    assert main([*GENERATE, "--pages", "6", "--no-cover"]) == ExitCode.OK
    assert _manifest().get("cover") is None


def test_generate_cover_uses_cover_settings(
    providers: tuple[PagesAndCover, CoverVision], config_dir: ConfigDirFactory
) -> None:
    images, responder = providers
    _settings_with_cover(config_dir, colorize=False, select_pages=False)
    assert main([*GENERATE, "--pages", "6", "--cover"]) == ExitCode.OK
    cover = _manifest()["cover"]
    assert cover["selection"] == "default"
    assert images.cover.requests == [] and responder.calls == []


def test_generate_cover_skipped_when_pages_failed(
    providers: tuple[PagesAndCover, CoverVision], capsys: pytest.CaptureFixture[str]
) -> None:
    images, responder = providers
    images.pages.fail = lambda req: (
        ProviderError("x", fatal=False) if "number 2 " in req.prompt else None
    )
    assert main([*GENERATE, "--pages", "6", "--cover"]) == ExitCode.PARTIAL
    err = capsys.readouterr().err
    assert "okładka pominięta: nie wszystkie strony są gotowe (page_02)" in err
    assert f"kdp-studio cover {BOOK}" in err
    assert _manifest().get("cover") is None
    assert responder.calls == []


def test_generate_cover_creates_vision_before_any_api_call(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli, "cmyk_converter", lambda settings: NaiveConverter())

    def no_vision(name: str, model: str) -> FakeVisionProvider:
        raise ConfigError("brak klucza modelu z wizją")

    monkeypatch.setattr(cli, "create_vision_provider", no_vision)
    assert main([*GENERATE, "--pages", "6", "--cover"]) == ExitCode.VALIDATION_ERROR
    assert "brak klucza modelu z wizją" in capsys.readouterr().err
    assert not BOOK.exists()


def test_generate_cover_needs_enough_pages(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([*GENERATE, "--pages", "3", "--cover"]) == ExitCode.VALIDATION_ERROR
    assert "okładka potrzebuje co najmniej 4 stron" in capsys.readouterr().err
    assert not BOOK.exists()


def test_generate_cover_checks_cmyk_profile_before_api_call(
    capsys: pytest.CaptureFixture[str], config_dir: ConfigDirFactory, tmp_path: Path
) -> None:
    settings = fake_settings()
    settings["cover"].setdefault("cmyk", {})["profile"] = str(tmp_path / "brak.icc")
    config_dir(settings=settings)
    assert main([*GENERATE, "--pages", "6", "--cover"]) == ExitCode.VALIDATION_ERROR
    assert "brak profilu CMYK" in capsys.readouterr().err
    assert not BOOK.exists()


def test_generate_cover_counts_toward_max_cost(
    providers: tuple[PagesAndCover, CoverVision], capsys: pytest.CaptureFixture[str]
) -> None:
    assert main([*GENERATE, "--pages", "6"]) == ExitCode.OK
    book_cost = _manifest()["cost_usd"]
    shutil.rmtree(BOOK)
    # Limit starcza na książkę i wybór stron, ale nie na kolorowanie przodu.
    limit = f"{book_cost + 0.0001:.6f}"
    code = main([*GENERATE, "--pages", "6", "--cover", "--max-cost", limit])
    assert code == ExitCode.BUDGET_EXCEEDED
    cover = _manifest()["cover"]
    assert cover["status"] == "failed"
    assert "limit" in cover["error"]
    assert not (BOOK / "cover" / "cover.pdf").exists()
    assert "Strony: 6/6 gotowe" in capsys.readouterr().out


def test_generate_cover_is_off_by_default(repo_config: AppConfig) -> None:
    assert repo_config.settings.cover.in_generate is False
