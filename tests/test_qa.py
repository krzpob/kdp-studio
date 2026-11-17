from __future__ import annotations

import re
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import pytest

from kdp_studio.config import AppConfig
from kdp_studio.models import (
    BookIdeas,
    BookMetadata,
    BookPrompts,
    BookSpec,
    PageIdea,
    PagePrompt,
)
from kdp_studio.pipeline.postprocess import PageFiles, PagePostprocessor, PostprocessError
from kdp_studio.pipeline.qa import (
    QAChecker,
    QAIssue,
    QAResult,
    belongs_to_instructions,
    book_theme,
    qa_instructions,
)
from kdp_studio.pipeline.worker import PageJob, PageWorker, ReservePool
from kdp_studio.providers.base import ProviderError, Usage
from kdp_studio.providers.fake import FakeImageProvider, FakeVisionProvider

SPEC = BookSpec(
    theme="Świąteczne kotki",
    age="wczesnoszkolne",
    style="cozy",
    format="square",
    pages=3,
    front_matter_pages=2,
)
SCENE = re.compile(r"^Page scene: Idea (\d+)\.", re.MULTILINE)


def _ideas(count: int) -> BookIdeas:
    return BookIdeas(
        book=BookMetadata(title="Cozy Kittens", subtitle="", description="d", keywords=[]),
        pages=[
            PageIdea(
                id=f"idea_{i:02d}",
                title=f"Idea {i}",
                scene=f"A kitten number {i} by the tree",
                elements=["kitten", "tree"],
            )
            for i in range(1, count + 1)
        ],
    )


def _reject(numbers: set[int]) -> Callable[[bytes, str], dict[str, Any]]:
    """Odrzuca strony pomysłów o podanych numerach (z instrukcji QA)."""

    def respond(image_png: bytes, instructions: str) -> dict[str, Any]:
        match = SCENE.search(instructions)
        assert match is not None
        if int(match.group(1)) in numbers:
            return {"passed": False, "issues": [{"criterion": "text", "detail": "napis u dołu"}]}
        return {"passed": True, "issues": []}

    return respond


def _checker(repo_config: AppConfig, vision: FakeVisionProvider, ideas: int = 5) -> QAChecker:
    return QAChecker(vision, SPEC, repo_config, _ideas(ideas))


# --- QAChecker -----------------------------------------------------------------------


def test_instructions_carry_criteria_age_profile_and_scene(repo_config: AppConfig) -> None:
    idea = _ideas(1).pages[0]
    text = qa_instructions(SPEC, repo_config, idea)
    age = repo_config.ages["wczesnoszkolne"]
    for criterion in ("panels", "shading", "text", "open_contours", "detail_level"):
        assert f"- {criterion}:" in text
    assert "- scene_mismatch:" in text
    assert age.name in text
    assert f"line weight {age.line}; subjects {age.subjects}" in text
    assert "Page scene: Idea 1. A kitten number 1 by the tree" in text
    assert "Key elements: kitten, tree" in text
    assert "in Polish" in text


def test_instructions_ask_whether_the_theme_shows_without_colors(repo_config: AppConfig) -> None:
    ideas = _ideas(1).model_copy(update={"theme_anchors": ["kittens", "christmas"]})
    assert book_theme(ideas) == "Cozy Kittens (kittens, christmas)"
    assert book_theme(_ideas(1)) == "Cozy Kittens"
    text = qa_instructions(SPEC, repo_config, ideas.pages[0], book_theme(ideas))
    assert "- theme_unclear: from the black-and-white line art alone" in text
    assert "Theme of the book: Cozy Kittens (kittens, christmas)" in text
    assert "One clearly drawn hint of the theme is enough" in text
    # Strona FR-14 ma temat w scene_mismatch; theme_unclear jej nie dotyczy.
    front = belongs_to_instructions(SPEC, repo_config, ["kitten"])
    assert "- theme_unclear: not used for this page" in front


def test_checker_sends_the_book_theme(repo_config: AppConfig) -> None:
    seen: list[str] = []

    def respond(image_png: bytes, instructions: str) -> dict[str, Any]:
        seen.append(instructions)
        return {"passed": True, "issues": []}

    _checker(repo_config, FakeVisionProvider(respond)).check(b"png", "idea_01")
    assert "Theme of the book: Cozy Kittens" in seen[0]
    verdict = QAResult.model_validate(
        {"pass": False, "issues": [{"criterion": "theme_unclear", "detail": "brzeg jak plaża"}]}
    )
    assert verdict.summary() == "theme_unclear: brzeg jak plaża"


def test_check_returns_verdict_and_usage(repo_config: AppConfig) -> None:
    vision = FakeVisionProvider(_reject({2}))
    checker = _checker(repo_config, vision)
    ok, usage = checker.check(b"png", "idea_01")
    assert ok == QAResult(passed=True, issues=[])
    assert usage == Usage(input_tokens=1000, output_tokens=20)
    bad, _ = checker.check(b"png", "idea_02")
    assert not bad.passed
    assert bad.issues == [QAIssue(criterion="text", detail="napis u dołu")]
    assert bad.summary() == "text: napis u dołu"


def test_rejection_without_issues_gets_a_reason(repo_config: AppConfig) -> None:
    vision = FakeVisionProvider(lambda png, text: {"passed": False, "issues": []})
    result, _ = _checker(repo_config, vision).check(b"png", "idea_01")
    assert not result.passed
    assert [i.criterion for i in result.issues] == ["other"]


def test_result_is_stored_as_pass_and_issues() -> None:
    result = QAResult(passed=False, issues=[QAIssue(criterion="panels", detail="siatka")])
    assert result.model_dump(mode="json") == {
        "pass": False,
        "issues": [{"criterion": "panels", "detail": "siatka"}],
    }
    assert QAResult.model_validate({"pass": True, "issues": []}).passed


# --- PageWorker z QA (FR-07) ---------------------------------------------------------


def _jobs(count: int) -> list[PageJob]:
    return [
        PageJob(page=i, name=f"page_{i:02d}", idea_id=f"idea_{i:02d}", prompt=f"prompt {i}")
        for i in range(1, count + 1)
    ]


def _pool(first: int, last: int) -> ReservePool:
    return ReservePool(
        [PagePrompt(idea_id=f"idea_{i:02d}", prompt=f"prompt {i}") for i in range(first, last + 1)]
    )


def _worker(
    tmp_path: Path,
    repo_config: AppConfig,
    vision: FakeVisionProvider,
    *,
    images: FakeImageProvider | None = None,
    reserve: ReservePool | None = None,
    max_retries: int = 2,
    max_ideas: int = 2,
    concurrency: int = 1,
) -> PageWorker:
    return PageWorker(
        provider=images or FakeImageProvider(),
        book_dir=tmp_path,
        aspect="1:1",
        quality="low",
        concurrency=concurrency,
        qa=_checker(repo_config, vision),
        reserve=reserve if reserve is not None else _pool(4, 5),
        max_retries=max_retries,
        max_ideas=max_ideas,
    )


def test_rejected_page_tries_same_idea_then_reserve(tmp_path: Path, repo_config: AppConfig) -> None:
    images = FakeImageProvider()
    reserve = _pool(4, 5)
    worker = _worker(tmp_path, repo_config, FakeVisionProvider(_reject({2})), images=images)
    worker.reserve = reserve
    result = worker.run(_jobs(3))

    assert [o.status for o in result.outcomes] == ["ok", "ok", "ok"]
    page = result.outcomes[1]
    # Pomysł 2: próba i dwa ponowienia, potem zapasowy pomysł 4.
    assert (page.idea_id, page.prompt, page.attempts) == ("idea_04", "prompt 4", 4)
    assert page.qa is not None and page.qa.passed
    assert page.usage == Usage(input_tokens=40, output_tokens=400)  # cztery grafiki
    assert page.qa_usage == Usage(input_tokens=4000, output_tokens=80)
    assert [(r.attempt, r.idea_id) for r in page.rejected] == [
        (1, "idea_02"),
        (2, "idea_02"),
        (3, "idea_02"),
    ]
    assert [r.file.name for r in page.rejected] == [f"page_02_try{i}.png" for i in (1, 2, 3)]
    assert all(r.file.exists() for r in page.rejected)
    assert page.rejected[0].issues[0].criterion == "text"
    assert (tmp_path / "raw" / "page_02.png").exists()
    assert [r.prompt for r in images.requests] == [
        "prompt 1",
        *["prompt 2"] * 3,
        "prompt 4",
        "prompt 3",
    ]
    assert (reserve.used, reserve.remaining) == (1, 1)
    assert result.rejected == 3
    assert result.outcomes[0].attempts == 1 and result.outcomes[0].rejected == []


def test_retry_of_the_same_idea_can_pass(tmp_path: Path, repo_config: AppConfig) -> None:
    calls: list[str] = []

    def respond(image_png: bytes, instructions: str) -> dict[str, Any]:
        match = SCENE.search(instructions)
        assert match is not None
        calls.append(match.group(1))
        if calls.count("1") == 1 and match.group(1) == "1":  # tylko pierwsza próba
            issue = {"criterion": "theme_unclear", "detail": "brzeg jak letnia plaża"}
            return {"passed": False, "issues": [issue]}
        return {"passed": True, "issues": []}

    reserve = _pool(4, 5)
    worker = _worker(tmp_path, repo_config, FakeVisionProvider(respond), reserve=reserve)
    [page] = worker.run(_jobs(1)).outcomes
    assert (page.status, page.idea_id, page.attempts) == ("ok", "idea_01", 2)
    assert page.rejected[0].issues[0].criterion == "theme_unclear"
    assert reserve.used == 0


def test_page_fails_after_retries_on_every_idea(tmp_path: Path, repo_config: AppConfig) -> None:
    vision = FakeVisionProvider(_reject({1, 4, 5}))
    result = _worker(tmp_path, repo_config, vision, max_retries=1).run(_jobs(1))
    [page] = result.outcomes
    assert page.status == "failed"
    assert page.attempts == 4  # 2 pomysły × (1 + 1 ponowienie)
    assert page.error is not None and page.error.startswith("QA odrzuciło 4 próby, ostatnio: text")
    assert [r.file.name for r in page.rejected] == [f"page_01_try{i}.png" for i in (1, 2, 3, 4)]
    assert [r.idea_id for r in page.rejected] == ["idea_01", "idea_01", "idea_04", "idea_04"]
    assert page.raw_file is None  # odrzucona surowa grafika jest w rejected/
    assert page.qa is not None and not page.qa.passed


def test_page_fails_when_reserve_runs_out(tmp_path: Path, repo_config: AppConfig) -> None:
    vision = FakeVisionProvider(_reject({1}))
    result = _worker(tmp_path, repo_config, vision, reserve=_pool(4, 3)).run(_jobs(1))
    [page] = result.outcomes
    assert page.status == "failed" and page.attempts == 3
    assert page.error is not None and "brak zapasowych pomysłów" in page.error


def test_one_idea_per_page_never_touches_reserve(tmp_path: Path, repo_config: AppConfig) -> None:
    reserve = _pool(4, 5)
    vision = FakeVisionProvider(_reject({1}))
    worker = _worker(tmp_path, repo_config, vision, reserve=reserve, max_ideas=1)
    [page] = worker.run(_jobs(1)).outcomes
    assert page.status == "failed" and page.attempts == 3
    assert reserve.used == 0


def test_zero_retries_go_straight_to_reserve(tmp_path: Path, repo_config: AppConfig) -> None:
    reserve = _pool(4, 5)
    vision = FakeVisionProvider(_reject({1}))
    worker = _worker(tmp_path, repo_config, vision, reserve=reserve, max_retries=0)
    [page] = worker.run(_jobs(1)).outcomes
    assert (page.status, page.idea_id, page.attempts) == ("ok", "idea_04", 2)
    assert reserve.used == 1


def test_reserve_is_shared_between_pages(tmp_path: Path, repo_config: AppConfig) -> None:
    vision = FakeVisionProvider(_reject({1, 2, 3}))
    reserve = _pool(4, 5)
    worker = _worker(tmp_path, repo_config, vision, reserve=reserve, concurrency=3)
    result = worker.run(_jobs(3))
    assert sorted(o.status for o in result.outcomes) == ["failed", "ok", "ok"]
    assert sorted(o.idea_id for o in result.ok) == ["idea_04", "idea_05"]
    assert reserve.remaining == 0


def test_qa_error_fails_only_that_page(tmp_path: Path, repo_config: AppConfig) -> None:
    def respond(image_png: bytes, instructions: str) -> dict[str, Any]:
        if "Idea 2." in instructions:
            raise ProviderError("odmowa", fatal=False)
        return {"passed": True, "issues": []}

    result = _worker(tmp_path, repo_config, FakeVisionProvider(respond)).run(_jobs(3))
    assert [o.status for o in result.outcomes] == ["ok", "failed", "ok"]
    assert result.outcomes[1].error == "kontrola jakości: odmowa"
    assert result.fatal_error is None


def test_fatal_qa_error_stops_the_run(tmp_path: Path, repo_config: AppConfig) -> None:
    def respond(image_png: bytes, instructions: str) -> dict[str, Any]:
        raise ProviderError("brak środków")

    images = FakeImageProvider()
    result = _worker(tmp_path, repo_config, FakeVisionProvider(respond), images=images).run(
        _jobs(5)
    )
    assert result.fatal_error == "brak środków"
    assert result.outcomes == []
    assert len(images.requests) == 1


def test_qa_sees_the_finished_page(tmp_path: Path, repo_config: AppConfig) -> None:
    seen: list[bytes] = []

    def respond(image_png: bytes, instructions: str) -> dict[str, Any]:
        seen.append(image_png)
        return {"passed": True, "issues": []}

    worker = _worker(tmp_path, repo_config, FakeVisionProvider(respond))
    [page] = worker.run(_jobs(1)).outcomes
    assert page.raw_file is not None
    assert seen == [page.raw_file.read_bytes()]  # bez obróbki QA widzi surową grafikę


def test_reserve_pool_is_thread_safe() -> None:
    pool = _pool(1, 100)
    taken: list[str] = []
    lock = threading.Lock()

    def take_all() -> None:
        while (prompt := pool.take()) is not None:
            with lock:
                taken.append(prompt.idea_id)

    threads = [threading.Thread(target=take_all) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(taken) == sorted(f"idea_{i:02d}" for i in range(1, 101))
    assert (pool.used, pool.remaining) == (100, 0)


@pytest.mark.parametrize("pages", [3, 5])
def test_reserve_pool_starts_after_book_pages(pages: int) -> None:
    prompts = BookPrompts(
        style_block="s",
        pages=[PagePrompt(idea_id=f"idea_{i:02d}", prompt=f"p {i}") for i in range(1, 7)],
    )
    pool = ReservePool.from_prompts(prompts, pages)
    assert pool.remaining == 6 - pages
    first = pool.take()
    assert first is not None and first.idea_id == f"idea_{pages + 1:02d}"


@dataclass(frozen=True)
class _BrokenPreview:
    """Obróbka podglądu dla QA, która zawsze zawodzi (np. pusta strona)."""

    book_dir: Path

    def process(self, raw: Path, name: str) -> PageFiles:
        raise PostprocessError("pusta strona")


def test_preview_error_moves_raw_to_rejected(tmp_path: Path, repo_config: AppConfig) -> None:
    worker = _worker(tmp_path, repo_config, FakeVisionProvider())
    worker.preview = cast(PagePostprocessor, _BrokenPreview(tmp_path))
    [page] = worker.run(_jobs(1)).outcomes
    assert (page.status, page.error, page.raw_file) == ("failed", "obróbka: pusta strona", None)
    assert (tmp_path / "rejected" / "page_01_try1.png").is_file()
    assert not (tmp_path / "raw" / "page_01.png").exists()
