from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from kdp_studio import cli
from kdp_studio.cli import ExitCode, main
from kdp_studio.config import DEFAULT_CONFIG_DIR
from kdp_studio.providers.base import ImageRequest, ProviderError, TextProvider
from kdp_studio.providers.fake import FakeImageProvider, FakeTextProvider
from tests.conftest import ConfigDirFactory, llm_ideas_response

BASE = ["generate", "--theme", "Dinozaury", "--age", "przedszkole", "--style", "kawaii"]
BOOK_DIR = Path("output/dinozaury_przedszkole_kawaii_letter")


TEST_DPI = 30


@pytest.fixture(autouse=True)
def fake_text_provider(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, config_dir: ConfigDirFactory
) -> FakeTextProvider:
    """Bez sieci i bez zapisu w repo: fałszywi dostawcy i katalog roboczy w tmp_path.

    Formaty mają te same wymiary w calach, ale 30 DPI zamiast 300, żeby obróbka
    setek stron w testach CLI trwała ułamek sekundy. Pełną rozdzielczość sprawdza
    tests/test_postprocess.py.
    """
    formats = yaml.safe_load((DEFAULT_CONFIG_DIR / "formats.yaml").read_text(encoding="utf-8"))
    for fmt in formats.values():
        fmt["dpi"] = TEST_DPI
        fmt["page_px"] = [round(side * TEST_DPI) for side in fmt["trim_in"]]
    monkeypatch.setenv("KDP_STUDIO_CONFIG_DIR", str(config_dir(formats=formats)))
    provider = FakeTextProvider([llm_ideas_response(300)])

    def create(name: str, model: str) -> TextProvider:
        return provider

    monkeypatch.setattr(cli, "create_text_provider", create)
    monkeypatch.setattr(cli, "create_image_provider", lambda name, model: FakeImageProvider())
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


def test_generate_writes_prompts_json(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([*BASE, "--pages", "30"]) == ExitCode.OK
    prompts = json.loads((BOOK_DIR / "prompts.json").read_text(encoding="utf-8"))
    ideas = json.loads((BOOK_DIR / "ideas.json").read_text(encoding="utf-8"))
    assert [p["idea_id"] for p in prompts["pages"]] == [i["id"] for i in ideas["pages"]]
    first = prompts["pages"][0]["prompt"]
    assert first == f"Scene: {ideas['pages'][0]['scene']}.\n{prompts['style_block']}"
    assert "no multiple panels" in prompts["style_block"]
    assert "Prompty obrazu: 36." in capsys.readouterr().out


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


@pytest.mark.parametrize(
    ("pages", "summary"),
    [
        ("12", "Pomysły: 15 (12 stron + 3 zapasowe)"),
        ("22", "Pomysły: 27 (22 strony + 5 zapasowych)"),
        ("1", "Pomysły: 2 (1 strona + 1 zapasowy)"),
    ],
)
def test_summary_uses_polish_plurals(
    pages: str, summary: str, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main([*BASE, "--pages", pages]) == ExitCode.OK
    assert summary in capsys.readouterr().out


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


# --- FR-05 ---------------------------------------------------------------------------


def _image_provider(monkeypatch: pytest.MonkeyPatch, provider: FakeImageProvider) -> list[str]:
    names: list[str] = []

    def create(name: str, model: str) -> FakeImageProvider:
        names.append(name)
        return provider

    monkeypatch.setattr(cli, "create_image_provider", create)
    return names


def test_generate_writes_raw_pages(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([*BASE, "--pages", "12", "--format", "square"]) == ExitCode.OK
    book = Path("output/dinozaury_przedszkole_kawaii_square")
    assert sorted(p.name for p in (book / "raw").iterdir()) == [
        f"page_{i:02d}.png" for i in range(1, 13)
    ]
    out = capsys.readouterr().out
    assert "Generuję 12 grafik (fake, fake-image, jakość medium, równolegle 4)" in out
    assert "page_07: ok (" in out
    assert "Strony: 12/12 ok" in out
    assert sorted(p.name for p in book.glob("*.png")) == [f"page_{i:02d}.png" for i in range(1, 13)]
    assert sorted(p.name for p in (book / "svg").iterdir()) == [
        f"page_{i:02d}.svg" for i in range(1, 13)
    ]
    assert 'margines 0.5" z każdej strony (grzbiet KDP dla 26 stron: 0.375")' in out


def test_generate_sends_page_prompts_and_aspect(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = FakeImageProvider()
    _image_provider(monkeypatch, provider)
    assert main([*BASE, "--pages", "12"]) == ExitCode.OK
    prompts = json.loads((BOOK_DIR / "prompts.json").read_text(encoding="utf-8"))["pages"]
    assert sorted(r.prompt for r in provider.requests) == sorted(p["prompt"] for p in prompts[:12])
    assert {r.aspect for r in provider.requests} == {"3:4"}  # letter


def test_page_failure_exits_2(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def fail(req: ImageRequest) -> ProviderError | None:
        return ProviderError("moderacja", fatal=False) if "number 2 " in req.prompt else None

    _image_provider(monkeypatch, FakeImageProvider(fail=fail))
    assert main([*BASE, "--pages", "12"]) == ExitCode.PARTIAL
    captured = capsys.readouterr()
    assert "Strony: 11/12 ok" in captured.out
    assert not (BOOK_DIR / "page_02.png").exists()
    assert "page_02: nieudana: moderacja" in captured.out
    assert "Błąd: nieudane strony: page_02" in captured.err


def test_fatal_image_error_exits_4(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def fail(req: ImageRequest) -> ProviderError:
        return ProviderError("brak środków na koncie OpenAI API")

    _image_provider(monkeypatch, FakeImageProvider(fail=fail))
    assert main([*BASE, "--pages", "12"]) == ExitCode.PROVIDER_ERROR
    assert "Błąd: brak środków na koncie OpenAI API" in capsys.readouterr().err
    assert (BOOK_DIR / "ideas.json").is_file()  # pomysły i prompty zostają


@pytest.mark.parametrize("value", ["0", "17"])
def test_concurrency_out_of_range_skips_api(
    value: str, fake_text_provider: FakeTextProvider, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main([*BASE, "--concurrency", value]) == ExitCode.VALIDATION_ERROR
    assert f"--concurrency: musi być w zakresie 1–16 (podano {value})" in capsys.readouterr().err
    assert fake_text_provider.calls == []


def test_concurrency_option(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([*BASE, "--pages", "12", "--concurrency", "2"]) == ExitCode.OK
    assert "równolegle 2" in capsys.readouterr().out


def test_image_provider_option(monkeypatch: pytest.MonkeyPatch) -> None:
    names = _image_provider(monkeypatch, FakeImageProvider())
    assert main([*BASE, "--pages", "12", "--image-provider", "openai"]) == ExitCode.OK
    assert names == ["openai"]


def test_unsupported_aspect_skips_api(
    monkeypatch: pytest.MonkeyPatch,
    fake_text_provider: FakeTextProvider,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _image_provider(monkeypatch, FakeImageProvider(aspects=["1:1"]))
    assert main(BASE) == ExitCode.VALIDATION_ERROR
    assert "nie obsługuje proporcji 3:4 formatu letter" in capsys.readouterr().err
    assert fake_text_provider.calls == []
