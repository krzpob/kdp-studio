"""FR-14: strona „This book belongs to…” w motywie książki."""

from __future__ import annotations

import io
import json
import shutil
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

import numpy as np
import pytest
import yaml
from PIL import Image, ImageDraw
from pydantic import ValidationError

from kdp_studio import cli
from kdp_studio.cli import ExitCode, main
from kdp_studio.config import (
    DEFAULT_CONFIG_DIR,
    AppConfig,
    BelongsToAge,
    BelongsToSettings,
    TextBox,
)
from kdp_studio.models import BookIdeas, BookSpec
from kdp_studio.pipeline.belongs_to import (
    FRONT_NAME,
    BelongsToMaker,
    BelongsToRenderer,
    belongs_to_prompt,
    draw_text_block,
    ink_ratio,
    theme_elements,
)
from kdp_studio.pipeline.postprocess import PageGeometry, PostprocessError, verify_page
from kdp_studio.pipeline.prompts import FIXED_CONSTRAINTS, FRAME_CONSTRAINTS, PromptBuilder
from kdp_studio.pipeline.qa import QAChecker, QAIssue, QAResult, belongs_to_instructions
from kdp_studio.providers.base import ImageRequest, ImageResult, ProviderError, Usage
from kdp_studio.providers.fake import FakeImageProvider, make_png
from tests.conftest import FAKE_IMAGE_COST, fake_settings, llm_ideas_response, scene_tags
from tests.test_cli import TEST_DPI, _vision, fake_text_provider  # noqa: F401  (autouse)

GENERATE = ["generate", "--theme", "Dinozaury", "--age", "przedszkole", "--style", "kawaii"]
BOOK = Path("output/dinozaury_przedszkole_kawaii_letter")
ARG = str(BOOK)
FRONT_PNG = BOOK / f"{FRONT_NAME}.png"


def ring_png(width: int = 96, height: int = 128, *, center: bool = False) -> bytes:
    """Ramka przy brzegach obrazu; `center=True` dorysowuje plamę na środku (napis modelu)."""
    img = Image.new("L", (width, height), 255)
    draw = ImageDraw.Draw(img)
    draw.rectangle((4, 4, width - 5, height - 5), outline=0, width=4)
    if center:
        draw.rectangle((width // 3, height // 2 - 6, 2 * width // 3, height // 2 + 6), fill=0)
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    return buffer.getvalue()


@dataclass
class FrontAwareProvider:
    """Strony jak FakeImageProvider; ramka FR-14 z pustym albo zajętym polem na imię."""

    front_blank: list[bool] = field(default_factory=lambda: [True])  # kolejne próby ramki
    front_error: ProviderError | None = None
    name: str = "fake"
    model: str = "fake-image"
    pages: FakeImageProvider = field(default_factory=FakeImageProvider)
    front_requests: list[ImageRequest] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def supported_aspects(self) -> list[str]:
        return self.pages.supported_aspects()

    def generate(self, req: ImageRequest) -> ImageResult:
        if "empty blank plaque" not in req.prompt:
            return self.pages.generate(req)
        with self._lock:
            self.front_requests.append(req)
            attempt = len(self.front_requests)
        if self.front_error is not None:
            raise self.front_error
        blank = self.front_blank[min(attempt, len(self.front_blank)) - 1]
        return ImageResult(
            ring_png(center=not blank), 96, 128, Usage(input_tokens=10, output_tokens=100)
        )


@pytest.fixture
def provider(monkeypatch: pytest.MonkeyPatch) -> FrontAwareProvider:
    fake = FrontAwareProvider()
    monkeypatch.setattr(cli, "create_image_provider", lambda name, model: fake)
    return fake


def _manifest() -> dict[str, Any]:
    data = json.loads((BOOK / "manifest.json").read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def _front() -> dict[str, Any]:
    front = _manifest()["front_matter"]["belongs_to"]
    assert isinstance(front, dict)
    return front


# --- Prompt -------------------------------------------------------------------------------


def _ideas(count: int = 6) -> BookIdeas:
    data = llm_ideas_response(count)
    for i, page in enumerate(data["pages"]):
        page["id"] = f"idea_{i + 1:02d}"
        page.update(scene_tags(subject="dinosaur"))
        page["elements"] = ["Volcano", "palm tree"] if i % 2 else ["volcano", "egg"]
    return BookIdeas.model_validate({"book": data["book"], "pages": data["pages"]})


def _spec(pages: int = 4) -> BookSpec:
    return BookSpec(
        theme="Dinozaury",
        age="przedszkole",
        style="kawaii",
        format="letter",
        pages=pages,
        front_matter_pages=2,
    )


def test_theme_elements_take_subject_and_common_elements() -> None:
    ideas = _ideas()
    assert theme_elements(ideas, 4) == ["dinosaur", "volcano", "egg"]
    assert theme_elements(ideas, 4, count=2) == ["dinosaur", "volcano"]


def test_prompt_uses_book_style_block_without_no_frame(repo_config: AppConfig) -> None:
    spec = _spec()
    prompt, elements = belongs_to_prompt(spec, repo_config, _ideas())
    assert elements == ["dinosaur", "volcano", "egg"]
    assert prompt.startswith("Scene: a decorative frame made of theme elements around a large")
    assert "decorated with dinosaur, volcano, egg." in prompt
    assert "coloring book about dino friends" in prompt
    assert "no text" in prompt and "no frame" not in prompt
    style = PromptBuilder(spec, repo_config).style_block
    assert prompt.endswith(style.replace(FIXED_CONSTRAINTS, FRAME_CONSTRAINTS))


# --- Pole na tekst i napis ----------------------------------------------------------------


SETTINGS = BelongsToSettings()
AGE = BelongsToAge(font_pt=40, name_line_height_in=0.8, outline_text=False)


def test_ink_ratio() -> None:
    img = Image.new("L", (100, 100), 255)
    ImageDraw.Draw(img).rectangle((0, 0, 9, 9), fill=0)
    assert ink_ratio(img, (0, 0, 20, 20)) == 0.25
    assert ink_ratio(img, (50, 50, 100, 100)) == 0


@pytest.mark.parametrize("outline", [False, True])
def test_text_block_is_black_and_white_inside_the_box(outline: bool) -> None:
    img = Image.new("L", (2550, 3300), 255)
    rect = (500, 1200, 2050, 1900)
    age = AGE.model_copy(update={"outline_text": outline})
    out = draw_text_block(img, rect, SETTINGS, age, 300)
    pixels = np.asarray(out)
    assert set(np.unique(pixels).tolist()) == {0, 255}
    ys, xs = np.nonzero(pixels == 0)
    assert xs.min() >= rect[0] and xs.max() < rect[2]
    assert ys.min() >= rect[1] and ys.max() < rect[3]


def test_outline_text_leaves_letters_white() -> None:
    img = Image.new("L", (2550, 3300), 255)
    rect = (500, 1200, 2050, 1900)
    filled = draw_text_block(img, rect, SETTINGS, AGE, 300)
    outlined = draw_text_block(
        img, rect, SETTINGS, AGE.model_copy(update={"outline_text": True}), 300
    )
    assert ink_ratio(outlined, rect) < ink_ratio(filled, rect)


def test_text_shrinks_to_fit_and_fails_when_box_is_tiny() -> None:
    img = Image.new("L", (2550, 3300), 255)
    narrow = (1000, 1200, 1700, 1900)
    out = draw_text_block(img, narrow, SETTINGS, AGE, 300)
    xs = np.nonzero(np.asarray(out) == 0)[1]
    assert xs.min() >= narrow[0] and xs.max() < narrow[2]
    with pytest.raises(PostprocessError, match="nie mieści się"):
        draw_text_block(img, (1000, 1200, 1100, 1250), SETTINGS, AGE, 300)


def test_text_box_must_fit_in_content_area() -> None:
    with pytest.raises(ValidationError, match="text_box wychodzi poza"):
        TextBox(x=0.5, y=0.1, width=0.6, height=0.2)


# --- Renderer -----------------------------------------------------------------------------


def _renderer(repo_config: AppConfig, tmp_path: Path) -> BelongsToRenderer:
    age = repo_config.ages["przedszkole"]
    return BelongsToRenderer(
        book_dir=tmp_path,
        geometry=PageGeometry(page_px=(850, 1100), dpi=100, margin_in=0.5),  # letter, 100 DPI
        params=age.postprocess,
        settings=repo_config.settings.belongs_to_page,
        age=age.belongs_to,
    )


def _raw(tmp_path: Path, data: bytes, name: str = "raw.png") -> Path:
    path = tmp_path / name
    path.write_bytes(data)
    return path


def test_render_frame_page(repo_config: AppConfig, tmp_path: Path) -> None:
    renderer = _renderer(repo_config, tmp_path)
    raw = _raw(tmp_path, ring_png())
    assert renderer.text_box_ink(raw) == 0
    files = renderer.render(raw, "frame")
    assert files.page == tmp_path / f"{FRONT_NAME}.png"
    assert files.svg.is_file()
    assert verify_page(files.page, renderer.geometry) == []
    with Image.open(files.page) as img:
        assert ink_ratio(img, renderer.text_rect("frame")) > 0.005  # napis i linia


def test_render_fallback_page_puts_art_on_top(repo_config: AppConfig, tmp_path: Path) -> None:
    renderer = _renderer(repo_config, tmp_path)
    files = renderer.render(_raw(tmp_path, make_png(96, 128, frame=True)), "fallback")
    assert verify_page(files.page, renderer.geometry) == []
    _, top, _, bottom = renderer.geometry.content_box
    split = top + round((bottom - top) * renderer.settings.fallback_art_height)
    with Image.open(files.page) as img:
        pixels = np.asarray(img)
    assert (pixels[top:split] == 0).any()  # grafika u góry
    assert (pixels[split:bottom] == 0).any()  # napis pod nią


def test_center_ink_is_detected(repo_config: AppConfig, tmp_path: Path) -> None:
    renderer = _renderer(repo_config, tmp_path)
    assert renderer.text_box_ink(_raw(tmp_path, ring_png(center=True))) > 0.005


# --- Maker (krok 2) -----------------------------------------------------------------------


def _maker(
    repo_config: AppConfig, tmp_path: Path, provider: FrontAwareProvider, **kwargs: Any
) -> BelongsToMaker:
    return BelongsToMaker(
        provider=provider,
        book_dir=tmp_path,
        aspect="3:4",
        quality="low",
        renderer=_renderer(repo_config, tmp_path),
        elements=["dinosaur"],
        **kwargs,
    )


PROMPT = "Scene: a frame around a large empty blank plaque."


def test_maker_accepts_blank_frame(repo_config: AppConfig, tmp_path: Path) -> None:
    outcome = _maker(repo_config, tmp_path, FrontAwareProvider()).make(PROMPT, None)
    assert (outcome.status, outcome.layout, outcome.attempts) == ("ok", "frame", 1)
    assert outcome.raw_file == tmp_path / "raw" / f"{FRONT_NAME}.png"
    assert outcome.usage.output_tokens == 100


def test_maker_retries_then_falls_back(repo_config: AppConfig, tmp_path: Path) -> None:
    provider = FrontAwareProvider(front_blank=[False])
    art = _raw(tmp_path, make_png(96, 128, frame=True), "page_01.png")
    outcome = _maker(repo_config, tmp_path, provider).make(PROMPT, ("page_01", art))
    assert (outcome.status, outcome.layout, outcome.fallback_source) == (
        "ok",
        "fallback",
        "page_01",
    )
    assert outcome.attempts == 3  # 1 + max_retries
    assert [r.file.name for r in outcome.rejected] == [
        f"{FRONT_NAME}_try{i}.png" for i in (1, 2, 3)
    ]
    assert "pole na imię nie jest puste" in outcome.rejected[0].issues[0].detail
    assert outcome.raw_file is not None and outcome.raw_file.read_bytes() == art.read_bytes()


def test_maker_second_try_succeeds(repo_config: AppConfig, tmp_path: Path) -> None:
    provider = FrontAwareProvider(front_blank=[False, True])
    outcome = _maker(repo_config, tmp_path, provider).make(PROMPT, None)
    assert (outcome.status, outcome.layout, outcome.attempts) == ("ok", "frame", 2)
    assert len(outcome.rejected) == 1


def test_maker_fails_without_fallback_art(repo_config: AppConfig, tmp_path: Path) -> None:
    outcome = _maker(repo_config, tmp_path, FrontAwareProvider(front_blank=[False])).make(
        PROMPT, None
    )
    assert outcome.status == "failed"
    assert outcome.error is not None and "brak gotowej strony książki" in outcome.error


def test_maker_fatal_error_propagates(repo_config: AppConfig, tmp_path: Path) -> None:
    provider = FrontAwareProvider(front_error=ProviderError("zły klucz", fatal=True))
    with pytest.raises(ProviderError, match="zły klucz"):
        _maker(repo_config, tmp_path, provider).make(PROMPT, None)


def test_maker_non_fatal_error_falls_back(repo_config: AppConfig, tmp_path: Path) -> None:
    provider = FrontAwareProvider(front_error=ProviderError("moderacja", fatal=False))
    art = _raw(tmp_path, make_png(96, 128, frame=True), "page_01.png")
    outcome = _maker(repo_config, tmp_path, provider).make(PROMPT, ("page_01", art))
    assert (outcome.status, outcome.layout, outcome.attempts) == ("ok", "fallback", 3)


def test_maker_stops_over_budget(repo_config: AppConfig, tmp_path: Path) -> None:
    provider = FrontAwareProvider(front_blank=[False])
    outcome = _maker(
        repo_config, tmp_path, provider, over_budget=lambda: len(provider.front_requests) >= 1
    ).make(PROMPT, None)
    assert outcome.status == "failed" and outcome.budget_exceeded
    assert outcome.attempts == 1


class _RejectingQA:
    def __init__(self) -> None:
        self.calls = 0

    def check_belongs_to(self, image: bytes, elements: list[str]) -> tuple[QAResult, Usage]:
        self.calls += 1
        if self.calls == 1:
            issue = QAIssue(criterion="text", detail="dodatkowy napis")
            return QAResult(passed=False, issues=[issue]), Usage(input_tokens=5)
        return QAResult(passed=True), Usage(input_tokens=5)


def test_maker_qa_rejects_then_accepts(repo_config: AppConfig, tmp_path: Path) -> None:
    qa = _RejectingQA()
    outcome = _maker(repo_config, tmp_path, FrontAwareProvider(), qa=cast(QAChecker, qa)).make(
        PROMPT, None
    )
    assert (outcome.status, outcome.attempts, qa.calls) == ("ok", 2, 2)
    assert outcome.rejected[0].issues[0].detail == "dodatkowy napis"
    assert outcome.qa is not None and outcome.qa.passed
    assert outcome.qa_usage.input_tokens == 10


def test_qa_instructions_allow_the_program_text(repo_config: AppConfig) -> None:
    text = belongs_to_instructions(_spec(), repo_config, ["dinosaur", "volcano"])
    assert '"This book belongs to:"' in text
    assert "which the program adds on purpose" in text
    assert "Key elements: dinosaur, volcano" in text
    assert "- text: any letters, words, numbers, signatures, logos or watermarks.\n" not in text


# --- CLI: generate --belongs-to-page ------------------------------------------------------


def test_generate_with_belongs_to_page(
    provider: FrontAwareProvider, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main([*GENERATE, "--pages", "3", "--belongs-to-page"]) == ExitCode.OK
    out = capsys.readouterr().out
    assert "Strona „This book belongs to…”: nowy wpis w manifeście" in out
    assert f"{FRONT_NAME}: ok, ramka (1 próba" in out
    assert f"{FRONT_NAME}: ok (ramka, " in out
    assert "Czas kroku (strona „belongs to”)" in out
    # Krok między images a finalize; canva.md pisze dopiero finalize.
    assert out.index("Surowe grafiki:") < out.index(f"{FRONT_NAME}: ok, ramka")
    assert out.index(f"{FRONT_NAME}: ok (ramka") < out.index("Gotowe strony:")
    assert "Odświeżono instrukcję" not in out
    assert FRONT_PNG.is_file() and (BOOK / "svg" / f"{FRONT_NAME}.svg").is_file()
    assert len(provider.front_requests) == 1
    front = _front()
    assert (front["status"], front["layout"], front["attempts"]) == ("ok", "frame", 1)
    assert front["files"]["png"] == f"{FRONT_NAME}.png"
    assert front["cost_usd"] == pytest.approx(FAKE_IMAGE_COST)
    assert front["elements"][0] == "dinosaur"
    data = _manifest()
    assert data["status"] == "completed"
    canva = (BOOK / "canva.md").read_text(encoding="utf-8")
    assert f"| 2 | `{FRONT_NAME}.png` |" in canva and "| 1 | strona wstępna |" in canva
    assert "wstaw ją jako stronę wstępną nr 2" in canva


def test_fallback_layout_after_busy_plaques(
    provider: FrontAwareProvider, capsys: pytest.CaptureFixture[str]
) -> None:
    provider.front_blank = [False]
    assert main([*GENERATE, "--pages", "3", "--belongs-to-page"]) == ExitCode.OK
    out = capsys.readouterr().out
    assert "układ zapasowy: grafika page_01 i napis pod nią" in out
    front = _front()
    assert (front["layout"], front["fallback_source"]) == ("fallback", "page_01")
    assert len(front["rejected"]) == 3
    assert FRONT_PNG.is_file()


def test_no_front_page_by_default(provider: FrontAwareProvider) -> None:
    assert main([*GENERATE, "--pages", "3"]) == ExitCode.OK
    assert _manifest()["front_matter"]["belongs_to"] is None
    assert not FRONT_PNG.exists() and provider.front_requests == []
    assert "front_belongs_to" not in (BOOK / "canva.md").read_text(encoding="utf-8")


def test_generate_skips_front_page_without_ready_pages(
    provider: FrontAwareProvider, capsys: pytest.CaptureFixture[str]
) -> None:
    provider.pages.fail = lambda req: ProviderError("moderacja", fatal=False)
    assert main([*GENERATE, "--pages", "3", "--belongs-to-page"]) == ExitCode.PARTIAL
    err = capsys.readouterr().err
    assert "strona „This book belongs to…” pominięta: brak gotowych surowych grafik" in err
    assert _manifest()["front_matter"]["belongs_to"] is None
    assert provider.front_requests == []


def test_fatal_error_on_front_page_exits_4(provider: FrontAwareProvider) -> None:
    provider.front_error = ProviderError("brak środków", fatal=True)
    assert main([*GENERATE, "--pages", "3", "--belongs-to-page"]) == ExitCode.PROVIDER_ERROR
    assert _manifest()["status"] == "failed"
    assert not FRONT_PNG.exists()
    assert not (BOOK / "canva.md").exists()  # finalize czeka na usunięcie przyczyny


def test_front_page_over_budget_exits_3(
    provider: FrontAwareProvider, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main([*GENERATE, "--pages", "3"]) == ExitCode.OK
    book_cost = _manifest()["cost_usd"]
    shutil.rmtree(BOOK)
    # Limit starcza na wszystkie strony, ale po nich jest już wyczerpany.
    limit = f"{book_cost - 1e-6:.7f}"
    code = main([*GENERATE, "--pages", "3", "--belongs-to-page", "--max-cost", limit])
    assert code == ExitCode.BUDGET_EXCEEDED
    assert f"pominięto {FRONT_NAME}" in capsys.readouterr().err
    assert _manifest()["status"] == "budget_exceeded"
    assert provider.front_requests == []


def test_qa_checks_front_page_with_its_own_criteria(
    provider: FrontAwareProvider, monkeypatch: pytest.MonkeyPatch
) -> None:
    vision = _vision(monkeypatch)
    assert main([*GENERATE, "--pages", "3", "--belongs-to-page", "--qa"]) == ExitCode.OK
    front_calls = [c for c in vision.calls if "which the program adds on purpose" in c]
    assert len(front_calls) == 1
    assert _front()["qa"] == {"pass": True, "issues": []}


def test_missing_font_fails_before_api_calls(
    monkeypatch: pytest.MonkeyPatch,
    config_dir: Any,
    provider: FrontAwareProvider,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _use_settings(monkeypatch, config_dir, font="assets/fonts/missing.ttf")
    assert main([*GENERATE, "--pages", "3", "--belongs-to-page"]) == ExitCode.VALIDATION_ERROR
    assert "brak czcionki" in capsys.readouterr().err
    assert not BOOK.exists()


@pytest.mark.parametrize("command", [["ideas", "--theme", "Dinozaury"], ["images", ARG]])
def test_only_generate_takes_the_flag(command: list[str]) -> None:
    assert main([*command, "--belongs-to-page"]) == ExitCode.VALIDATION_ERROR


# --- CLI: kdp-studio belongs-to -----------------------------------------------------------


def _use_settings(monkeypatch: pytest.MonkeyPatch, config_dir: Any, **belongs_to: Any) -> None:
    settings = fake_settings()
    settings["belongs_to_page"].update(belongs_to)
    monkeypatch.setenv(
        "KDP_STUDIO_CONFIG_DIR", str(config_dir(formats=_formats(), settings=settings))
    )


def _formats() -> dict[str, Any]:
    formats = yaml.safe_load((DEFAULT_CONFIG_DIR / "formats.yaml").read_text(encoding="utf-8"))
    for fmt in formats.values():
        fmt["dpi"] = TEST_DPI
        fmt["page_px"] = [round(side * TEST_DPI) for side in fmt["trim_in"]]
    assert isinstance(formats, dict)
    return formats


def test_belongs_to_adds_page_to_finished_book(
    provider: FrontAwareProvider, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main([*GENERATE, "--pages", "3"]) == ExitCode.OK
    capsys.readouterr()
    assert main(["belongs-to", ARG]) == ExitCode.OK
    out = capsys.readouterr().out
    assert f"{FRONT_NAME}: ok, ramka (1 próba" in out
    assert f"Odświeżono instrukcję składania w Canvie: {BOOK / 'canva.md'}" in out
    assert "Czas kroku (strona „belongs to”)" in out
    assert len(provider.pages.requests) == 3  # strony bez zmian
    assert FRONT_PNG.is_file() and _front()["status"] == "ok"
    assert _manifest()["status"] == "completed"
    assert f"`{FRONT_NAME}.png`" in (BOOK / "canva.md").read_text(encoding="utf-8")
    # Drugie uruchomienie nic nie robi i nic nie kosztuje.
    assert main(["belongs-to", ARG]) == ExitCode.OK
    assert f"{FRONT_NAME} jest aktualna, nic do zrobienia." in capsys.readouterr().out
    assert len(provider.front_requests) == 1


def test_belongs_to_before_finalize_leaves_canva_to_finalize(
    provider: FrontAwareProvider,
) -> None:
    assert main(["ideas", *GENERATE[1:], "--pages", "3"]) == ExitCode.OK
    assert main(["images", ARG]) == ExitCode.OK
    assert main(["belongs-to", ARG]) == ExitCode.OK
    assert FRONT_PNG.is_file() and not (BOOK / "canva.md").exists()
    assert _manifest()["status"] == "raw_ready"
    assert main(["finalize", ARG]) == ExitCode.OK
    assert f"`{FRONT_NAME}.png`" in (BOOK / "canva.md").read_text(encoding="utf-8")
    assert _manifest()["status"] == "completed"


def test_belongs_to_needs_raw_pages(
    provider: FrontAwareProvider, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["ideas", *GENERATE[1:], "--pages", "3"]) == ExitCode.OK
    assert main(["belongs-to", ARG]) == ExitCode.VALIDATION_ERROR
    assert f"najpierw kdp-studio images {BOOK}" in capsys.readouterr().err
    assert provider.front_requests == []
    assert _manifest()["front_matter"]["belongs_to"] is None


def test_belongs_to_remove(
    provider: FrontAwareProvider, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main([*GENERATE, "--pages", "3", "--belongs-to-page"]) == ExitCode.OK
    capsys.readouterr()
    assert main(["belongs-to", ARG, "--remove"]) == ExitCode.OK
    assert "Usunięto stronę „This book belongs to…”" in capsys.readouterr().out
    assert _manifest()["front_matter"]["belongs_to"] is None
    assert not FRONT_PNG.exists() and not (BOOK / "svg" / f"{FRONT_NAME}.svg").exists()
    assert (BOOK / "raw" / f"{FRONT_NAME}.png").is_file()  # surowa grafika zostaje
    assert "front_belongs_to" not in (BOOK / "canva.md").read_text(encoding="utf-8")
    assert _manifest()["status"] == "completed"
    assert main(["belongs-to", ARG, "--remove"]) == ExitCode.OK
    assert "nic do usunięcia" in capsys.readouterr().out


def test_remove_takes_no_generation_options(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["belongs-to", ARG, "--remove", "--qa"]) == ExitCode.VALIDATION_ERROR
    assert "--remove nie łączy się" in capsys.readouterr().err


def test_regenerate_front_page(provider: FrontAwareProvider) -> None:
    assert main([*GENERATE, "--pages", "3", "--belongs-to-page"]) == ExitCode.OK
    data = _manifest()
    data["front_matter"]["belongs_to"]["action"] = "regenerate"
    (BOOK / "manifest.json").write_text(json.dumps(data), encoding="utf-8")
    assert main(["images", ARG]) == ExitCode.OK  # images nie rusza strony FR-14
    assert len(provider.front_requests) == 1
    assert main(["belongs-to", ARG]) == ExitCode.OK
    assert len(provider.front_requests) == 2
    front = _front()
    assert (front["status"], front["action"], front["attempts"]) == ("ok", None, 2)
    assert FRONT_PNG.is_file()
    assert front["cost_usd"] == pytest.approx(2 * FAKE_IMAGE_COST)


def test_text_change_rerenders_without_new_frame(
    provider: FrontAwareProvider,
    monkeypatch: pytest.MonkeyPatch,
    config_dir: Any,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main([*GENERATE, "--pages", "3", "--belongs-to-page"]) == ExitCode.OK
    before = FRONT_PNG.read_bytes()
    _use_settings(monkeypatch, config_dir, text="Ta książka należy do:")
    capsys.readouterr()
    assert main(["finalize", ARG]) == ExitCode.OK  # finalize tylko przypomina
    assert "nie odpowiada obecnym ustawieniom" in capsys.readouterr().err
    assert FRONT_PNG.read_bytes() == before
    assert main(["belongs-to", ARG]) == ExitCode.OK
    assert FRONT_PNG.read_bytes() != before
    assert len(provider.front_requests) == 1  # bez nowej grafiki


def test_failed_text_is_not_retried_with_a_new_frame(
    provider: FrontAwareProvider,
    monkeypatch: pytest.MonkeyPatch,
    config_dir: Any,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main([*GENERATE, "--pages", "3"]) == ExitCode.OK
    _use_settings(monkeypatch, config_dir, text="This book belongs to " * 20)
    assert main(["belongs-to", ARG]) == ExitCode.PARTIAL
    err = capsys.readouterr().err
    assert f"nieudana strona {FRONT_NAME}: obróbka:" in err
    assert _front()["status"] == "failed" and _manifest()["status"] == "partial"
    assert main(["belongs-to", ARG]) == ExitCode.PARTIAL
    assert len(provider.front_requests) == 1  # napis nie zależy od ramki
    assert main(["finalize", ARG]) == ExitCode.PARTIAL
    assert f"ponów: kdp-studio belongs-to {BOOK}" in capsys.readouterr().err


def test_images_warns_when_fallback_art_was_regenerated(
    provider: FrontAwareProvider, capsys: pytest.CaptureFixture[str]
) -> None:
    provider.front_blank = [False]
    assert main([*GENERATE, "--pages", "3", "--belongs-to-page"]) == ExitCode.OK
    data = _manifest()
    data["pages"][0]["action"] = "regenerate"
    (BOOK / "manifest.json").write_text(json.dumps(data), encoding="utf-8")
    capsys.readouterr()
    assert main(["images", ARG]) == ExitCode.OK
    err = capsys.readouterr().err
    assert f"{FRONT_NAME} używa grafiki page_01 sprzed ponownego generowania" in err
    assert f"kdp-studio belongs-to {BOOK}" in err


def test_belongs_to_missing_font(
    monkeypatch: pytest.MonkeyPatch,
    config_dir: Any,
    provider: FrontAwareProvider,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main([*GENERATE, "--pages", "3"]) == ExitCode.OK
    _use_settings(monkeypatch, config_dir, font="assets/fonts/missing.ttf")
    assert main(["belongs-to", ARG]) == ExitCode.VALIDATION_ERROR
    assert "brak czcionki" in capsys.readouterr().err
    assert provider.front_requests == []
