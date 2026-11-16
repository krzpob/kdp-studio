"""FR-17: generowanie krokowe (ideas → images → finalize) z ręczną weryfikacją."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest
import yaml

from kdp_studio import cli
from kdp_studio.cli import ExitCode, main
from kdp_studio.pipeline.book import LOCK_FILE
from kdp_studio.providers.base import ImageRequest, ProviderError
from kdp_studio.providers.fake import FakeImageProvider, FakeTextProvider, make_png
from tests.conftest import scene_tags
from tests.test_cli import _vision, fake_text_provider  # noqa: F401  (autouse: fałszywi dostawcy)

IDEAS = ["ideas", "--theme", "Dinozaury", "--age", "przedszkole", "--style", "kawaii"]
BOOK = Path("output/dinozaury_przedszkole_kawaii_letter")
ARG = str(BOOK)


@pytest.fixture
def images(monkeypatch: pytest.MonkeyPatch) -> FakeImageProvider:
    provider = FakeImageProvider()
    monkeypatch.setattr(cli, "create_image_provider", lambda name, model: provider)
    return provider


def _manifest() -> dict[str, Any]:
    data = json.loads((BOOK / "manifest.json").read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def _save_manifest(data: dict[str, Any]) -> None:
    (BOOK / "manifest.json").write_text(json.dumps(data), encoding="utf-8")


def _ideas() -> dict[str, Any]:
    data = json.loads((BOOK / "ideas.json").read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def _save_ideas(data: dict[str, Any]) -> None:
    (BOOK / "ideas.json").write_text(json.dumps(data), encoding="utf-8")


def _statuses() -> list[str]:
    return [p["status"] for p in _manifest()["pages"]]


def _book(pages: int = 3) -> None:
    """Kroki 1–3 dla małej książki."""
    assert main([*IDEAS, "--pages", str(pages)]) == ExitCode.OK
    assert main(["images", ARG]) == ExitCode.OK
    assert main(["finalize", ARG]) == ExitCode.OK


# --- Krok 1 --------------------------------------------------------------------------


def test_ideas_step_makes_no_images(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def no_images(name: str, model: str) -> FakeImageProvider:
        raise AssertionError("krok 1 nie tworzy dostawcy grafik")

    monkeypatch.setattr(cli, "create_image_provider", no_images)
    assert main([*IDEAS, "--pages", "3"]) == ExitCode.OK
    out = capsys.readouterr().out
    assert f"a potem: kdp-studio images {ARG}" in out
    manifest = _manifest()
    assert manifest["status"] == "ideas_ready"
    assert _statuses() == ["pending"] * 3
    assert (BOOK / "ideas.json").is_file() and (BOOK / "prompts.json").is_file()
    assert not (BOOK / "raw").exists()
    assert not (BOOK / LOCK_FILE).exists()


def test_ideas_step_refuses_existing_book(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([*IDEAS, "--pages", "3"]) == ExitCode.OK
    assert main([*IDEAS, "--pages", "3"]) == ExitCode.VALIDATION_ERROR
    assert f"kdp-studio images {ARG}" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (["ideas", ARG], "z katalogiem książki podaj --redo"),
        (["ideas", "--redo", "idea_01"], "--redo wymaga katalogu książki"),
        (["ideas", ARG, "--redo", "idea_01", "--theme", "X"], "nie podawaj --theme"),
        (["ideas", ARG, "--redo", " , "], "podaj id pomysłów"),
    ],
)
def test_ideas_argument_errors(
    args: list[str], message: str, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(args) == ExitCode.VALIDATION_ERROR
    assert message in capsys.readouterr().err


# --- Kroki 2 i 3 -----------------------------------------------------------------------


def test_steps_build_the_book(
    images: FakeImageProvider, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main([*IDEAS, "--pages", "3"]) == ExitCode.OK
    assert main(["images", ARG, "--image-quality", "low"]) == ExitCode.OK
    assert _manifest()["status"] == "raw_ready"
    assert _statuses() == ["raw_ok"] * 3
    assert not list(BOOK.glob("page_*.png"))  # gotowe strony dopiero w kroku 3
    assert not (BOOK / "canva.md").exists()
    assert {r.quality for r in images.requests} == {"low"}
    page = _manifest()["pages"][0]
    assert page["quality"] == "low" and page["raw_sha256"] and page["prompt_sha256"]
    assert f"a potem: kdp-studio finalize {ARG}" in capsys.readouterr().out

    assert main(["finalize", ARG]) == ExitCode.OK
    assert _manifest()["status"] == "completed"
    assert _statuses() == ["ok"] * 3
    assert sorted(p.name for p in BOOK.glob("page_*.png")) == [
        "page_01.png",
        "page_02.png",
        "page_03.png",
    ]
    assert (BOOK / "canva.md").is_file()
    assert _manifest()["pages"][0]["final"]["postprocess_sha256"]


def test_reruns_do_nothing(images: FakeImageProvider, capsys: pytest.CaptureFixture[str]) -> None:
    _book()
    requests = len(images.requests)
    capsys.readouterr()
    assert main(["images", ARG]) == ExitCode.OK
    assert main(["finalize", ARG]) == ExitCode.OK
    out = capsys.readouterr().out
    assert len(images.requests) == requests
    assert "Surowe grafiki są aktualne" in out
    assert "Gotowe strony są aktualne" in out
    assert _manifest()["status"] == "completed"


def test_finalize_needs_raw_images(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([*IDEAS, "--pages", "3"]) == ExitCode.OK
    assert main(["finalize", ARG]) == ExitCode.VALIDATION_ERROR
    assert f"najpierw kdp-studio images {ARG}" in capsys.readouterr().err


def test_steps_need_a_book_dir(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["images", "output/nic"]) == ExitCode.VALIDATION_ERROR
    assert "to nie jest katalog książki" in capsys.readouterr().err


def test_invalid_image_quality(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([*IDEAS, "--pages", "3"]) == ExitCode.OK
    assert main(["images", ARG, "--image-quality", "ultra"]) == ExitCode.VALIDATION_ERROR
    assert "--image-quality: dozwolone low, medium, high, auto" in capsys.readouterr().err


# --- Ręczna weryfikacja po kroku 2 -----------------------------------------------------


def test_action_regenerate(images: FakeImageProvider) -> None:
    _book()
    data = _manifest()
    data["pages"][1]["action"] = "regenerate"
    _save_manifest(data)
    images.requests.clear()
    assert main(["images", ARG]) == ExitCode.OK
    assert len(images.requests) == 1
    page = _manifest()["pages"][1]
    assert (page["action"], page["status"], page["attempts"]) == (None, "raw_ok", 2)
    assert not (BOOK / "page_02.png").exists()  # nieaktualna strona usunięta
    assert _manifest()["status"] == "raw_ready"
    assert main(["finalize", ARG]) == ExitCode.OK
    assert (BOOK / "page_02.png").exists()


def test_changed_idea_id_uses_the_reserve_idea(images: FakeImageProvider) -> None:
    _book()
    data = _manifest()
    data["pages"][0]["idea_id"] = "idea_04"
    _save_manifest(data)
    images.requests.clear()
    assert main(["images", ARG]) == ExitCode.OK
    assert [r.prompt.splitlines()[0] for r in images.requests] == [
        "Scene: A friendly dinosaur number 4 standing in a meadow."
    ]
    assert _manifest()["pages"][0]["idea_id"] == "idea_04"


def test_same_idea_on_two_pages_is_an_error(
    images: FakeImageProvider, capsys: pytest.CaptureFixture[str]
) -> None:
    _book()
    data = _manifest()
    data["pages"][0]["idea_id"] = "idea_02"
    data["pages"][2]["idea_id"] = "idea_99"
    _save_manifest(data)
    images.requests.clear()
    assert main(["images", ARG]) == ExitCode.VALIDATION_ERROR
    err = capsys.readouterr().err
    assert "page_02: pomysł idea_02 jest już na stronie page_01" in err
    assert "page_03: pomysłu idea_99 nie ma w ideas.json" in err
    assert images.requests == []


def test_edited_scene_regenerates_the_page(images: FakeImageProvider) -> None:
    _book()
    ideas = _ideas()
    ideas["pages"][2]["scene"] = "A dinosaur rides a bike"
    _save_ideas(ideas)
    images.requests.clear()
    assert main(["images", ARG]) == ExitCode.OK
    assert [r.prompt.splitlines()[0] for r in images.requests] == [
        "Scene: A dinosaur rides a bike."
    ]
    prompts = json.loads((BOOK / "prompts.json").read_text(encoding="utf-8"))
    assert prompts["pages"][2]["prompt"].startswith("Scene: A dinosaur rides a bike.")


def test_deleted_raw_file_is_generated_again(images: FakeImageProvider) -> None:
    _book()
    (BOOK / "raw" / "page_03.png").unlink()
    images.requests.clear()
    assert main(["images", ARG]) == ExitCode.OK
    assert len(images.requests) == 1


def test_users_own_raw_file_is_kept(
    images: FakeImageProvider, capsys: pytest.CaptureFixture[str]
) -> None:
    _book()
    (BOOK / "raw" / "page_01.png").write_bytes(make_png(96, 128, frame=True) + b"")
    custom = make_png(80, 120, frame=True)
    (BOOK / "raw" / "page_01.png").write_bytes(custom)
    images.requests.clear()
    assert main(["images", ARG]) == ExitCode.OK
    assert images.requests == []
    page = _manifest()["pages"][0]
    assert (page["edited_by_user"], page["status"]) == (True, "raw_ok")
    assert "page_01: własna wersja surowej grafiki, zostaje." in capsys.readouterr().out
    assert main(["finalize", ARG]) == ExitCode.OK
    assert _manifest()["pages"][0]["status"] == "ok"
    # Kolejne uruchomienie nadal jej nie rusza.
    assert main(["images", ARG]) == ExitCode.OK
    assert images.requests == []


def test_finalize_detects_users_raw_file_too(images: FakeImageProvider) -> None:
    _book()
    (BOOK / "raw" / "page_02.png").write_bytes(make_png(80, 120, frame=True))
    assert main(["finalize", ARG]) == ExitCode.OK
    page = _manifest()["pages"][1]
    assert page["edited_by_user"] and page["status"] == "ok"


# --- Ręczna weryfikacja po kroku 1 -----------------------------------------------------


def test_reordered_ideas_set_the_pages(images: FakeImageProvider) -> None:
    assert main([*IDEAS, "--pages", "3"]) == ExitCode.OK
    ideas = _ideas()
    ideas["pages"] = [ideas["pages"][3], *ideas["pages"][1:3]]  # bez idea_01, idea_04 na start
    _save_ideas(ideas)
    assert main(["images", ARG]) == ExitCode.OK
    assert [p["idea_id"] for p in _manifest()["pages"]] == ["idea_04", "idea_02", "idea_03"]


def test_broken_ideas_json_stops_before_images(
    images: FakeImageProvider, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main([*IDEAS, "--pages", "3"]) == ExitCode.OK
    ideas = _ideas()
    ideas["pages"][0]["scene"] = ""
    ideas["pages"][1]["id"] = ideas["pages"][2]["id"]
    _save_ideas(ideas)
    assert main(["images", ARG]) == ExitCode.VALIDATION_ERROR
    assert "ideas.json: pages.0.scene" in capsys.readouterr().err
    assert images.requests == []


def test_too_few_ideas(images: FakeImageProvider, capsys: pytest.CaptureFixture[str]) -> None:
    assert main([*IDEAS, "--pages", "3"]) == ExitCode.OK
    ideas = _ideas()
    ideas["pages"] = ideas["pages"][:2]
    ideas["pages"][1]["id"] = "idea_01"
    _save_ideas(ideas)
    assert main(["images", ARG]) == ExitCode.VALIDATION_ERROR
    err = capsys.readouterr().err
    assert "2 pomysłów, a książka ma 3 stron" in err
    assert "powtórzone id: idea_01" in err


def test_redo_replaces_ideas_with_the_same_ids(
    fake_text_provider: FakeTextProvider,  # noqa: F811
    images: FakeImageProvider,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _book()
    fake_text_provider.routes["_LLMMoreIdeas"] = {
        "pages": [
            {
                "title": "Bike",
                "scene": "A dinosaur rides a bike",
                "elements": ["dinosaur", "bike"],
                **scene_tags(),
            }
        ]
    }
    assert main(["ideas", ARG, "--redo", "idea_02"]) == ExitCode.OK
    out = capsys.readouterr().out
    assert "idea_02: Bike: A dinosaur rides a bike" in out
    assert "Strony z nowymi pomysłami (page_02)" in out
    ideas = _ideas()
    assert ideas["pages"][1]["id"] == "idea_02"
    assert ideas["pages"][1]["scene"] == "A dinosaur rides a bike"
    assert ideas["review"]["rejected"][-1]["reason"] == "zastąpiony (--redo)"
    images.requests.clear()
    assert main(["images", ARG]) == ExitCode.OK
    assert [r.prompt.splitlines()[0] for r in images.requests] == [
        "Scene: A dinosaur rides a bike."
    ]


def test_redo_unknown_idea(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([*IDEAS, "--pages", "3"]) == ExitCode.OK
    assert main(["ideas", ARG, "--redo", "idea_77"]) == ExitCode.VALIDATION_ERROR
    assert "nie ma pomysłów idea_77" in capsys.readouterr().err


def test_redo_fails_when_no_new_ideas(
    fake_text_provider: FakeTextProvider,  # noqa: F811
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main([*IDEAS, "--pages", "3"]) == ExitCode.OK
    fake_text_provider.routes["_LLMMoreIdeas"] = {"pages": []}
    assert main(["ideas", ARG, "--redo", "idea_01"]) == ExitCode.PROVIDER_ERROR
    assert "udało się wymyślić 0 z 1" in capsys.readouterr().err


# --- Krok 3 po zmianie profilu ---------------------------------------------------------


def test_changed_postprocess_params_reprocess_all_pages(
    images: FakeImageProvider, capsys: pytest.CaptureFixture[str]
) -> None:
    _book()
    ages_file = Path(os.environ["KDP_STUDIO_CONFIG_DIR"]) / "ages.yaml"
    ages = yaml.safe_load(ages_file.read_text(encoding="utf-8"))
    ages["przedszkole"]["postprocess"]["min_speck_area"] += 1
    ages_file.write_text(yaml.safe_dump(ages, allow_unicode=True), encoding="utf-8")
    capsys.readouterr()
    assert main(["finalize", ARG]) == ExitCode.OK
    assert "Obrabiam 3 strony" in capsys.readouterr().out


# --- QA, błędy i blokada ---------------------------------------------------------------


def test_qa_in_step_2_keeps_only_raw_files(
    monkeypatch: pytest.MonkeyPatch, images: FakeImageProvider
) -> None:
    _vision(monkeypatch, "Dinosaur 2")
    assert main([*IDEAS, "--pages", "3"]) == ExitCode.OK
    assert main(["images", ARG, "--qa"]) == ExitCode.OK
    assert not list(BOOK.glob("page_*.png"))  # tymczasowa obróbka nie zostaje w książce
    assert not (BOOK / "svg").exists()
    assert (BOOK / "rejected" / "page_02_try1.png").is_file()  # surowa odrzucona grafika
    page = _manifest()["pages"][1]
    assert (page["idea_id"], page["status"]) == ("idea_04", "raw_ok")
    assert _manifest()["input"]["qa"] is True
    # Odrzucony wcześniej idea_02 nie wraca jako zapas: przy kolejnym odrzuceniu zapasu brak.
    _vision(monkeypatch, "Dinosaur 2", "Dinosaur 4")
    data = _manifest()
    data["pages"][1]["action"] = "regenerate"
    _save_manifest(data)
    assert main(["images", ARG, "--qa"]) == ExitCode.PARTIAL
    page = _manifest()["pages"][1]
    assert page["status"] == "failed"
    assert "brak zapasowych pomysłów" in page["error"]
    assert not (BOOK / "raw" / "page_02.png").exists()


def test_fatal_error_then_resume(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def fail_third(req: ImageRequest) -> ProviderError | None:
        return ProviderError("brak środków") if "number 3 " in req.prompt else None

    broken = FakeImageProvider(fail=fail_third)
    monkeypatch.setattr(cli, "create_image_provider", lambda name, model: broken)
    args = [*IDEAS, "--pages", "3", "--concurrency", "1"]
    args[0] = "generate"
    assert main(args) == ExitCode.PROVIDER_ERROR
    err = capsys.readouterr().err
    assert f"po usunięciu przyczyny: kdp-studio images {ARG}" in err
    assert _manifest()["status"] == "failed"
    assert not (BOOK / LOCK_FILE).exists()

    fixed = FakeImageProvider()
    monkeypatch.setattr(cli, "create_image_provider", lambda name, model: fixed)
    assert main(["images", ARG]) == ExitCode.OK
    assert [r.prompt.split(".")[0] for r in fixed.requests] == [
        "Scene: A friendly dinosaur number 3 standing in a meadow"
    ]
    assert main(["finalize", ARG]) == ExitCode.OK
    assert _manifest()["status"] == "completed"


def test_lock_blocks_a_second_run(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([*IDEAS, "--pages", "3"]) == ExitCode.OK
    (BOOK / LOCK_FILE).write_text("pid 1", encoding="utf-8")
    assert main(["images", ARG]) == ExitCode.VALIDATION_ERROR
    assert "jest używany przez inne uruchomienie" in capsys.readouterr().err
    assert (BOOK / LOCK_FILE).exists()  # cudzej blokady nie usuwamy


def test_failed_page_is_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    def moderate(req: ImageRequest) -> ProviderError | None:
        return ProviderError("moderacja", fatal=False) if "number 2 " in req.prompt else None

    monkeypatch.setattr(
        cli, "create_image_provider", lambda name, model: FakeImageProvider(fail=moderate)
    )
    assert main([*IDEAS, "--pages", "3"]) == ExitCode.OK
    assert main(["images", ARG]) == ExitCode.PARTIAL
    assert _manifest()["status"] == "partial"
    assert main(["finalize", ARG]) == ExitCode.PARTIAL
    assert _statuses() == ["ok", "failed", "ok"]

    fixed = FakeImageProvider()
    monkeypatch.setattr(cli, "create_image_provider", lambda name, model: fixed)
    assert main(["images", ARG]) == ExitCode.OK
    assert len(fixed.requests) == 1
    assert main(["finalize", ARG]) == ExitCode.OK
    assert _statuses() == ["ok"] * 3
