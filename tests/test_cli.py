from __future__ import annotations

import json
from pathlib import Path

import pytest

from kdp_studio import cli
from kdp_studio.cli import ExitCode, main
from kdp_studio.providers.base import ProviderError, TextProvider
from kdp_studio.providers.fake import FakeTextProvider
from tests.conftest import ConfigDirFactory, llm_ideas_response

BASE = ["generate", "--theme", "Dinozaury", "--age", "przedszkole", "--style", "kawaii"]
BOOK_DIR = Path("output/dinozaury_przedszkole_kawaii_letter")


@pytest.fixture(autouse=True)
def fake_text_provider(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> FakeTextProvider:
    """Bez sieci i bez zapisu w repo: fałszywy dostawca i katalog roboczy w tmp_path."""
    provider = FakeTextProvider([llm_ideas_response(300)])

    def create(name: str, model: str) -> TextProvider:
        return provider

    monkeypatch.setattr(cli, "create_text_provider", create)
    monkeypatch.chdir(tmp_path)
    return provider


def test_valid_input_exits_ok(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([*BASE, "--format", "square", "--pages", "30"]) == ExitCode.OK
    out, err = capsys.readouterr()
    assert "Parametry poprawne" in out
    assert "30 grafik (62 strony książki)" in out
    assert err == ""


def test_defaults_are_letter_and_30_pages(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(BASE) == ExitCode.OK
    assert "format letter, 30 grafik" in capsys.readouterr().out


def test_validation_errors_exit_1_and_go_to_stderr(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["generate", "--age", "x", "--format", "a4"]) == ExitCode.VALIDATION_ERROR
    out, err = capsys.readouterr()
    assert out == ""
    assert "Błąd: --theme" in err
    assert "Błąd: --age: nieznana wartość 'x'" in err
    assert "Błąd: --style: parametr wymagany" in err
    assert "Dozwolone wartości: letter, square" in err


def test_kdp_minimum_warning_keeps_exit_ok(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([*BASE, "--pages", "10"]) == ExitCode.OK
    _, err = capsys.readouterr()
    assert "Ostrzeżenie: książka będzie miała 22 strony" in err


def test_kdp_minimum_with_strict_exits_1(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([*BASE, "--pages", "10", "--strict"]) == ExitCode.VALIDATION_ERROR
    assert "(--strict)" in capsys.readouterr().err


@pytest.mark.parametrize(
    "args",
    [
        [*BASE, "--pages", "abc"],
        [*BASE, "--unknown-flag"],
        [*BASE, "--pages"],
        ["no-such-command"],
    ],
)
def test_usage_errors_exit_1_not_2(args: list[str], capsys: pytest.CaptureFixture[str]) -> None:
    assert main(args) == ExitCode.VALIDATION_ERROR
    assert capsys.readouterr().err


def test_no_args_shows_help(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == ExitCode.OK
    assert "generate" in capsys.readouterr().out


def test_config_error_exits_1(
    config_dir: ConfigDirFactory,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    directory = config_dir()
    (directory / "ages.yaml").unlink()
    monkeypatch.setenv("KDP_STUDIO_CONFIG_DIR", str(directory))
    assert main(BASE) == ExitCode.VALIDATION_ERROR
    assert "Błąd: brak pliku konfiguracji" in capsys.readouterr().err


# --- FR-03 ---------------------------------------------------------------------------


def test_generate_writes_ideas_json(
    fake_text_provider: FakeTextProvider, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main([*BASE, "--pages", "30"]) == ExitCode.OK
    data = json.loads((BOOK_DIR / "ideas.json").read_text(encoding="utf-8"))
    assert data["book"]["title"] == "Dino Friends"
    assert len(data["pages"]) == 36  # 30 + ceil(30 * 0.2)
    assert data["pages"][0]["id"] == "idea_01"
    assert len(fake_text_provider.calls) == 1
    out = capsys.readouterr().out
    assert "Pomysły: 36 (30 stron + 6 zapasowych)" in out
    assert "1 próba" in out


def test_output_dir_option(tmp_path: Path) -> None:
    assert main([*BASE, "--output-dir", str(tmp_path / "books")]) == ExitCode.OK
    assert (tmp_path / "books" / BOOK_DIR.name / "ideas.json").is_file()


def test_existing_ideas_json_is_not_overwritten(
    fake_text_provider: FakeTextProvider, capsys: pytest.CaptureFixture[str]
) -> None:
    BOOK_DIR.mkdir(parents=True)
    (BOOK_DIR / "ideas.json").write_text("{}", encoding="utf-8")
    assert main(BASE) == ExitCode.VALIDATION_ERROR
    assert (BOOK_DIR / "ideas.json").read_text(encoding="utf-8") == "{}"
    assert fake_text_provider.calls == []
    assert "już istnieje" in capsys.readouterr().err


def test_provider_error_exits_4(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def broken(system: str, user: str) -> object:
        raise ProviderError("OpenAI zwróciło HTTP 503: overloaded")

    monkeypatch.setattr(cli, "create_text_provider", lambda name, model: FakeTextProvider([broken]))
    assert main(BASE) == ExitCode.PROVIDER_ERROR
    assert "Błąd: OpenAI zwróciło HTTP 503" in capsys.readouterr().err
    assert not BOOK_DIR.exists()


def test_missing_api_key_exits_1_before_any_call(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from kdp_studio.providers.registry import create_text_provider

    monkeypatch.setattr(cli, "create_text_provider", create_text_provider)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert main(BASE) == ExitCode.VALIDATION_ERROR
    assert "brak OPENAI_API_KEY" in capsys.readouterr().err


def test_validation_error_skips_llm(fake_text_provider: FakeTextProvider) -> None:
    assert main([*BASE, "--pages", "0"]) == ExitCode.VALIDATION_ERROR
    assert fake_text_provider.calls == []


# --- FR-12 ---------------------------------------------------------------------------


def test_profiles_lists_everything(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["profiles"]) == ExitCode.OK
    out = capsys.readouterr().out
    for header in ("Wiek (--age)", "Styl (--style)", "Format (--format)"):
        assert header in out
    assert "  dorosli" in out
    assert "  fantasy" in out
    assert 'Letter (8.5" × 11"): Pionowa strona, postać lub scena w pionie. Domyślny.' in out


@pytest.mark.parametrize(
    ("kind", "header", "absent"),
    [("age", "Wiek (--age)", "kawaii"), ("style", "Styl (--style)", "przedszkole")],
)
def test_profiles_single_kind(
    kind: str, header: str, absent: str, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["profiles", kind]) == ExitCode.OK
    out = capsys.readouterr().out
    assert out.startswith(header)
    assert absent not in out
    assert "Format (--format)" not in out


def test_profiles_unknown_kind(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["profiles", "colour"]) == ExitCode.VALIDATION_ERROR
    assert (
        "Błąd: nieznany rodzaj profili 'colour'. Dozwolone: age, style, format"
        in capsys.readouterr().err
    )


def test_profiles_config_error(
    config_dir: ConfigDirFactory,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    directory = config_dir()
    (directory / "styles.yaml").unlink()
    monkeypatch.setenv("KDP_STUDIO_CONFIG_DIR", str(directory))
    assert main(["profiles", "age"]) == ExitCode.VALIDATION_ERROR
    assert "brak pliku konfiguracji" in capsys.readouterr().err
