"""FR-19: rynek docelowy Amazona (--market) i config/markets.yaml."""

from __future__ import annotations

import copy
import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
import yaml

from kdp_studio import cli
from kdp_studio.cli import ExitCode, main
from kdp_studio.config import DEFAULT_CONFIG_DIR, AppConfig, ConfigError, load_config
from kdp_studio.models import BookMetadata, BookSpec
from kdp_studio.pipeline.book import spec_from_manifest
from kdp_studio.pipeline.cmyk import NaiveConverter
from kdp_studio.pipeline.fonts import missing_chars
from kdp_studio.pipeline.ideas import apply_spelling
from kdp_studio.pipeline.manifest import Manifest
from kdp_studio.pipeline.qa import belongs_to_instructions
from kdp_studio.providers.fake import FakeTextProvider
from tests.conftest import ConfigDirFactory, approve_all, fake_settings, llm_ideas_response
from tests.test_belongs_to import FrontAwareProvider
from tests.test_cli import fake_text_provider  # noqa: F401  (autouse: fałszywi dostawcy)

IDEAS = ["ideas", "--theme", "Dinozaury", "--age", "przedszkole", "--style", "kawaii"]
GENERATE = ["generate", *IDEAS[1:]]
MARKETS = ["US", "UK", "DE", "FR", "ES", "IT", "NL", "PL", "SE", "JP", "CA", "AU"]


def _markets_yaml() -> dict[str, Any]:
    data = yaml.safe_load((DEFAULT_CONFIG_DIR / "markets.yaml").read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def _manifest(book: Path) -> dict[str, Any]:
    data = json.loads((book / "manifest.json").read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


# --- Konfiguracja ------------------------------------------------------------------------


def test_repo_markets_cover_the_spec(repo_config: AppConfig) -> None:
    markets = repo_config.markets
    assert sorted(markets.markets) == sorted(MARKETS)
    assert repo_config.settings.default_market == "US"
    # Strefa euro ma wspólne tabele KDP; pozostałe rynki własne.
    for key in ("DE", "FR", "ES", "IT", "NL"):
        assert markets.pricing(key).currency == "EUR"
    us = markets.pricing("US")
    assert (us.currency, us.printing_cost.large.fixed_only) == ("USD", Decimal("2.84"))
    assert markets.pricing("AU").printing_cost.fixed_only_max_pages == 108
    assert markets.pricing("JP").royalty.rate_60_min_price == Decimal("1000")
    assert str(markets.checked) == "2026-11-18"


def test_terms_give_the_age_phrase(repo_config: AppConfig) -> None:
    markets = repo_config.markets.markets
    kids = repo_config.ages["wczesnoszkolne"].age_range
    assert markets["US"].terms.age_phrase(kids) == "for Kids Ages 6–8"
    assert markets["PL"].terms.age_phrase(kids) == "dla dzieci w wieku 6–8 lat"
    assert markets["DE"].terms.age_phrase(repo_config.ages["dorosli"].age_range) == (
        "für Erwachsene"
    )
    assert markets["UK"].terms.coloring_book == "Colouring Book"


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (lambda d: d["markets"]["DE"].update(pricing_group="XX"), "nieznana pricing_group"),
        (lambda d: d["markets"]["DE"].update(currency="EUR"), "pricing_group wyklucza"),
        (lambda d: d["markets"]["US"]["terms"].update(ages="for Kids {lat}"), "terms.ages"),
        (lambda d: d["markets"]["US"]["terms"].update(ages="for Kids"), "brak pól"),
        (
            lambda d: d["markets"]["US"]["royalty"].update(rate_60_min_price=9.0),
            "rate_50_max_price < rate_60_min_price",
        ),
    ],
)
def test_bad_markets_yaml_is_a_config_error(
    config_dir: ConfigDirFactory, change: Any, message: str
) -> None:
    data = copy.deepcopy(_markets_yaml())
    change(data)
    with pytest.raises(ConfigError, match=message):
        load_config(config_dir(markets=data))


def test_default_market_must_exist(config_dir: ConfigDirFactory) -> None:
    settings = yaml.safe_load((DEFAULT_CONFIG_DIR / "settings.yaml").read_text(encoding="utf-8"))
    settings["default_market"] = "XX"
    with pytest.raises(ConfigError, match="default_market 'XX'"):
        load_config(config_dir(settings=settings))


# --- Pisownia metadanych -------------------------------------------------------------------


def test_spelling_follows_the_market(repo_config: AppConfig) -> None:
    book = BookMetadata(
        title="Winter Coloring Book",
        subtitle="Fun COLORING pages",
        description="Kids color their favorite ponies.",
        keywords=["coloring book", "colouring book"],
    )
    uk, changes = apply_spelling(book, repo_config.markets.markets["UK"].spelling)
    assert uk.title == "Winter Colouring Book" and uk.subtitle == "Fun COLOURING pages"
    assert uk.description == "Kids colour their favourite ponies."
    assert uk.keywords == ["colouring book"]  # po poprawce dwa słowa kluczowe to jedno
    assert "Coloring → Colouring" in changes
    us, back = apply_spelling(uk, repo_config.markets.markets["US"].spelling)
    assert us.title == "Winter Coloring Book" and back
    same, none = apply_spelling(book, repo_config.markets.markets["DE"].spelling)
    assert same == book and none == []


# --- CLI: --market -------------------------------------------------------------------------


def test_market_goes_to_manifest_and_book_dir(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([*IDEAS, "--pages", "12", "--market", "UK"]) == ExitCode.OK
    book = Path("output/dinozaury_przedszkole_kawaii_letter_uk")
    data = _manifest(book)
    assert data["input"]["market"] == "UK"
    ideas = json.loads((book / "ideas.json").read_text(encoding="utf-8"))
    # Odpowiedź fałszywego modelu ma „Coloring”: program poprawia pisownię brytyjską.
    assert ideas["book"]["subtitle"] == "A Colouring Book for Kids Ages 3–5"
    assert "pisownia rynku UK w metadanych: Coloring → Colouring" in capsys.readouterr().err
    # Domyślny rynek (US): katalog bez przyrostka, jak dotąd.
    assert main([*IDEAS, "--pages", "12"]) == ExitCode.OK
    assert _manifest(Path("output/dinozaury_przedszkole_kawaii_letter"))["input"]["market"] == "US"


def test_unknown_market_lists_the_available_ones(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([*IDEAS, "--pages", "12", "--market", "XX"]) == ExitCode.VALIDATION_ERROR
    err = capsys.readouterr().err
    assert "--market: nieznana wartość 'XX'" in err and "US" in err and "PL" in err
    assert not Path("output").exists()


def test_market_from_settings(config_dir: ConfigDirFactory) -> None:
    config_dir(settings=fake_settings(default_market="CA"))
    assert main([*IDEAS, "--pages", "12"]) == ExitCode.OK
    data = _manifest(Path("output/dinozaury_przedszkole_kawaii_letter_ca"))
    assert data["input"]["market"] == "CA"


def test_redo_takes_the_market_from_the_manifest(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([*IDEAS, "--pages", "12"]) == ExitCode.OK
    args = ["ideas", "output/dinozaury_przedszkole_kawaii_letter", "--redo", "idea_01"]
    assert main([*args, "--market", "UK"]) == ExitCode.VALIDATION_ERROR
    assert "rynek książki jest w manifeście" in capsys.readouterr().err


def test_old_manifest_without_market_is_us(repo_config: AppConfig, tmp_path: Path) -> None:
    assert main([*IDEAS, "--pages", "12"]) == ExitCode.OK
    data = _manifest(Path("output/dinozaury_przedszkole_kawaii_letter"))
    del data["input"]["market"]
    assert spec_from_manifest(Manifest.model_validate(data)).market == "US"


def test_profiles_lists_markets(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["profiles", "market"]) == ExitCode.OK
    out = capsys.readouterr().out
    assert out.startswith("Rynek (--market)")
    assert "Amazon.co.uk (Wielka Brytania): British English, en-GB." in out
    assert "Amazon.com (USA): American English, en-US. Domyślny." in out


# --- Napis FR-14 i czcionki -------------------------------------------------------------


def test_belongs_to_text_comes_from_the_market(repo_config: AppConfig) -> None:
    spec = BookSpec(
        theme="T", age="przedszkole", style="kawaii", format="square", pages=3,
        front_matter_pages=2, market="DE",
    )  # fmt: skip
    assert repo_config.belongs_to_text("DE") == "Dieses Buch gehört:"
    assert '"Dieses Buch gehört:"' in belongs_to_instructions(spec, repo_config, ["dino"])
    manual = repo_config.settings.belongs_to_page.model_copy(update={"text": "Mine:"})
    config = repo_config.model_copy(
        update={"settings": repo_config.settings.model_copy(update={"belongs_to_page": manual})}
    )
    assert config.belongs_to_text("DE") == "Mine:"  # ręczny napis ma pierwszeństwo


def test_market_font_replaces_fredoka_outside_us_and_uk(repo_config: AppConfig) -> None:
    us, pl = repo_config.for_market("US"), repo_config.for_market("PL")
    assert us.settings.belongs_to_page.font_path.name == "Fredoka-Variable.ttf"
    assert us.settings.cover.title_font_path.name == "Fredoka-Variable.ttf"
    assert pl.settings.belongs_to_page.font_path.name == "Baloo2-Variable.ttf"
    assert pl.settings.cover.title_font_path.name == "Baloo2-Variable.ttf"
    assert pl.settings.belongs_to_page.text == "Ta książka należy do:"
    assert repo_config.belongs_to_settings("PL") == pl.settings.belongs_to_page
    assert pl.for_market("PL") == pl  # ponowne ustalenie niczego nie zmienia


def test_every_market_but_japan_has_its_letters(repo_config: AppConfig) -> None:
    fredoka = repo_config.settings.belongs_to_page.font_path
    assert missing_chars(fredoka, "Ta książka należy do:") == "ąż"  # stąd Baloo 2 poza US i UK
    for key, market in repo_config.markets.markets.items():
        font = repo_config.for_market(key).settings.belongs_to_page.font_path
        missing = missing_chars(font, market.required_chars())
        assert bool(missing) == (key == "JP"), (key, missing)


def test_polish_book_gets_the_belongs_to_page(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = FrontAwareProvider()
    monkeypatch.setattr(cli, "create_image_provider", lambda name, model: provider)
    args = [*GENERATE, "--pages", "3", "--market", "PL", "--belongs-to-page"]
    assert main(args) == ExitCode.OK
    book = Path("output/dinozaury_przedszkole_kawaii_letter_pl")
    assert (book / "front_belongs_to.png").is_file()
    assert _manifest(book)["front_matter"]["belongs_to"]["status"] == "ok"


def test_japanese_needs_a_font_with_its_characters(repo_config: AppConfig) -> None:
    problems = cli._glyph_problems(repo_config, "JP", "belongs_to")
    assert problems and "Baloo2-Variable.ttf" in problems[0]
    assert "albo font rynku JP w markets.yaml" in problems[0]
    assert "rynku JP (Amazon.co.jp (Japonia))" in problems[0]


def test_new_book_warns_only_when_fonts_lack_letters(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([*IDEAS, "--pages", "12", "--market", "PL"]) == ExitCode.OK
    assert "nie ma znaków" not in capsys.readouterr().err
    # JP: brak tłumaczenia stron wstępnych (FR-23) to kod 1 jeszcze przed czcionkami.
    assert main([*IDEAS, "--pages", "12", "--market", "JP"]) == ExitCode.VALIDATION_ERROR
    assert "brak tekstów stron wstępnych" in capsys.readouterr().err


def test_cover_checks_the_title_letters(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # Rynek US, ale tytuł z polskimi literami (np. poprawiony ręcznie w ideas.json).
    provider = FakeTextProvider(
        [llm_ideas_response(300, title="Gęsi i dinozaury")], routes={"_Review": approve_all}
    )
    monkeypatch.setattr(cli, "create_text_provider", lambda name, model: provider)
    monkeypatch.setattr(cli, "cmyk_converter", lambda settings: NaiveConverter())
    assert main([*GENERATE, "--pages", "6"]) == ExitCode.OK
    capsys.readouterr()
    book = "output/dinozaury_przedszkole_kawaii_letter"
    assert main(["cover", book, "--no-color", "--no-select-pages"]) == ExitCode.VALIDATION_ERROR
    err = capsys.readouterr().err
    assert (
        "czcionka Fredoka-Variable.ttf (cover.title_font w settings.yaml) nie ma znaków „ę”" in err
    )
    assert _manifest(Path(book)).get("cover") is None
