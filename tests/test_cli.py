from __future__ import annotations

import pytest

from kdp_studio.cli import ExitCode, main
from tests.conftest import ConfigDirFactory

BASE = ["generate", "--theme", "Dinozaury", "--age", "przedszkole", "--style", "kawaii"]


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
