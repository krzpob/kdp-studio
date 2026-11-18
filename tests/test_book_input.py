"""FR-20: plik parametrów książki --config-file."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from kdp_studio import cli
from kdp_studio.book_input import (
    BookInput,
    BookInputError,
    load_book_file,
    resolve_input,
)
from kdp_studio.cli import ExitCode, main
from kdp_studio.config import AppConfig
from kdp_studio.pipeline.manifest import ManifestWriter
from kdp_studio.providers.fake import FakeImageProvider
from tests.test_cli import (
    BOOK_DIR,
    fake_text_provider,  # noqa: F401  (autouse: fałszywi dostawcy)
)

BOOK = {"theme": "Dinozaury", "age": "przedszkole", "style": "kawaii", "pages": 12}


def _write(path: Path, data: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return path


# --- Scalanie ------------------------------------------------------------------------------


def test_flag_beats_file_beats_settings(repo_config: AppConfig, tmp_path: Path) -> None:
    file = load_book_file(_write(tmp_path / "kotki.yaml", {**BOOK, "qa": True, "concurrency": 2}))
    resolved = resolve_input(BookInput(pages=13), file, repo_config)
    inp = resolved.input
    assert inp.pages == 13  # flaga
    assert inp.qa is True and inp.concurrency == 2  # plik
    assert inp.review_ideas is repo_config.settings.review_ideas  # settings.yaml
    assert inp.format == "letter"  # domyślnie w kodzie
    assert resolved.source("pages") == "--pages"
    assert resolved.source("qa") == "kotki.yaml"
    assert resolved.source("review_ideas") == "settings.yaml"
    assert resolved.overrides == ["pages"]


def test_flag_list_replaces_file_list(repo_config: AppConfig, tmp_path: Path) -> None:
    file = load_book_file(_write(tmp_path / "k.yaml", {"cover": {"thumbnails": [1, 2, 3, 4]}}))
    cli = BookInput.model_validate({"cover": {"thumbnails": ["05,06,07"]}})
    resolved = resolve_input(cli, file, repo_config)
    assert resolved.input.cover is not None
    assert resolved.input.cover.thumbnails == ["05,06,07"]


def test_cover_true_is_shorthand(tmp_path: Path) -> None:
    book = load_book_file(_write(tmp_path / "k.yaml", {"cover": True})).input
    assert book.cover is not None and book.cover.enabled is True


def test_unknown_key_and_bad_type_name_the_key_path(tmp_path: Path) -> None:
    path = _write(tmp_path / "kotki.yaml", {"pagse": 3, "cover": {"thumbnails": [1, {"x": 1}]}})
    with pytest.raises(BookInputError) as exc:
        load_book_file(path)
    errors = exc.value.errors
    assert any(e == "kotki.yaml: pagse: nieznany klucz (literówka?)" for e in errors)
    assert any(e.startswith("kotki.yaml: cover.thumbnails[1]") for e in errors)


def test_secrets_are_not_accepted(tmp_path: Path) -> None:
    with pytest.raises(BookInputError, match="openai_api_key"):
        load_book_file(_write(tmp_path / "k.yaml", {"openai_api_key": "sk-test"}))


def test_relative_paths_follow_the_file(tmp_path: Path) -> None:
    path = _write(
        tmp_path / "ksiazki" / "k.yaml", {"output_dir": "../wyniki", "cover": {"template": "t.png"}}
    )
    book = load_book_file(path).input
    assert book.output_dir == str(tmp_path / "ksiazki" / "../wyniki")
    assert book.cover is not None and book.cover.template == str(tmp_path / "ksiazki" / "t.png")


# --- Polecenia -----------------------------------------------------------------------------


def test_generate_from_file_records_effective_input(capsys: pytest.CaptureFixture[str]) -> None:
    path = _write(Path("ksiazki/kotki.yaml"), {**BOOK, "output_dir": "../output", "qa": False})
    assert main(["generate", "--config-file", str(path), "--pages", "13"]) == ExitCode.OK
    assert f"Plik parametrów książki: {path}" in capsys.readouterr().out
    data = ManifestWriter.load(BOOK_DIR).manifest.input
    assert data.pages == 13 and data.theme == "Dinozaury"
    assert data.config_file is not None and data.config_file.path == str(path)
    assert data.overrides == ["pages"]
    # Skuteczne wartości wszystkich kluczy, nie tylko podane
    assert data.image_quality == "medium" and data.max_cost == 5.0
    assert data.output_dir == str(Path("output").resolve())
    assert data.cover is not None and data.cover.enabled is False


def test_validation_error_names_the_file(capsys: pytest.CaptureFixture[str]) -> None:
    path = _write(Path("kotki.yaml"), {**BOOK, "pages": 300})
    assert main(["ideas", "--config-file", str(path)]) == ExitCode.VALIDATION_ERROR
    assert "kotki.yaml: pages: musi być w zakresie 1–200 (podano 300)" in capsys.readouterr().err


def test_flag_error_keeps_the_flag_name(capsys: pytest.CaptureFixture[str]) -> None:
    path = _write(Path("kotki.yaml"), BOOK)
    assert main(["ideas", "--config-file", str(path), "--pages", "0"]) == 1
    assert "--pages: musi być w zakresie 1–200 (podano 0)" in capsys.readouterr().err


def test_bad_file_fails_before_any_api_call(capsys: pytest.CaptureFixture[str]) -> None:
    path = _write(Path("kotki.yaml"), {**BOOK, "cover": {"qa": "maybe"}})
    assert main(["generate", "--config-file", str(path)]) == ExitCode.VALIDATION_ERROR
    assert "kotki.yaml: cover.qa: oczekiwano true albo false (podano 'maybe')" in (
        capsys.readouterr().err
    )
    assert not Path("output").exists()


def test_manifest_seeds_a_new_book() -> None:
    assert main(["generate", "--config-file", str(_write(Path("k.yaml"), BOOK))]) == ExitCode.OK
    manifest = BOOK_DIR / "manifest.json"
    args = ["ideas", "--config-file", str(manifest), "--theme", "Dinozaury w ogrodzie"]
    assert main(args) == ExitCode.OK
    seeded = ManifestWriter.load(Path("output/dinozaury_w_ogrodzie_przedszkole_kawaii_letter"))
    data = seeded.manifest.input
    assert (data.theme, data.pages, data.style) == ("Dinozaury w ogrodzie", 12, "kawaii")
    assert data.overrides == ["theme"]
    assert data.config_file is not None and data.config_file.path == str(manifest)


def test_images_refuses_a_file_for_another_book(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["ideas", "--config-file", str(_write(Path("k.yaml"), BOOK))]) == ExitCode.OK
    other = _write(Path("inna.yaml"), {**BOOK, "pages": 20, "style": "cartoon"})
    capsys.readouterr()
    assert main(["images", str(BOOK_DIR), "--config-file", str(other)]) == 1
    err = capsys.readouterr().err
    assert "inna.yaml: style: 'cartoon', a książka ma 'kawaii'" in err
    assert "inna.yaml: pages: 20, a książka ma 12" in err


def test_images_takes_its_settings_from_the_file(monkeypatch: pytest.MonkeyPatch) -> None:
    assert main(["ideas", "--config-file", str(_write(Path("k.yaml"), BOOK))]) == ExitCode.OK
    fake = FakeImageProvider()
    monkeypatch.setattr(cli, "create_image_provider", lambda name, model: fake)
    path = _write(Path("k.yaml"), {**BOOK, "image_quality": "low"})
    assert main(["images", str(BOOK_DIR), "--config-file", str(path)]) == ExitCode.OK
    assert {r.quality for r in fake.requests} == {"low"}


def test_out_of_range_value_in_file_names_the_key(capsys: pytest.CaptureFixture[str]) -> None:
    path = _write(Path("k.yaml"), {**BOOK, "concurrency": 99})
    assert main(["ideas", "--config-file", str(path)]) == ExitCode.VALIDATION_ERROR
    err = capsys.readouterr().err
    assert "k.yaml: concurrency: wartość musi być najwyżej 16 (podano 99)" in err


def test_no_secret_reaches_the_manifest(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-secret-value-123")
    assert main(["generate", "--config-file", str(_write(Path("k.yaml"), BOOK))]) == ExitCode.OK
    text = (BOOK_DIR / "manifest.json").read_text(encoding="utf-8")
    assert "sk-secret-value-123" not in text
    assert "api_key" not in json.loads(text)["input"]
