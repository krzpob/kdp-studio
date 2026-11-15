from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path

import pytest

from kdp_studio.models import BookPrompts
from kdp_studio.pipeline.worker import PageJob, PageOutcome, PageWorker, page_jobs
from kdp_studio.providers.base import ImageRequest, ProviderError, Usage, png_dimensions
from kdp_studio.providers.fake import FakeImageProvider


def _jobs(count: int) -> list[PageJob]:
    return [
        PageJob(page=i, name=f"page_{i:02d}", idea_id=f"idea_{i:02d}", prompt=f"prompt {i}")
        for i in range(1, count + 1)
    ]


def _worker(tmp_path: Path, provider: FakeImageProvider, concurrency: int = 4) -> PageWorker:
    return PageWorker(
        provider=provider,
        book_dir=tmp_path,
        aspect="3:4",
        quality="medium",
        concurrency=concurrency,
    )


def _fail_on(pages: set[int], *, fatal: bool) -> Callable[[ImageRequest], ProviderError | None]:
    def fail(req: ImageRequest) -> ProviderError | None:
        page = int(req.prompt.split()[-1])
        return ProviderError(f"boom {page}", fatal=fatal) if page in pages else None

    return fail


def test_page_jobs_take_first_pages_only() -> None:
    prompts = BookPrompts.model_validate(
        {
            "style_block": "S",
            "pages": [{"idea_id": f"idea_{i:02d}", "prompt": f"p{i}"} for i in range(1, 6)],
        }
    )
    jobs = page_jobs(prompts, 3)
    assert [(j.page, j.name, j.idea_id, j.prompt) for j in jobs] == [
        (1, "page_01", "idea_01", "p1"),
        (2, "page_02", "idea_02", "p2"),
        (3, "page_03", "idea_03", "p3"),
    ]


def test_page_names_are_padded_to_the_largest_number() -> None:
    prompts = BookPrompts.model_validate(
        {
            "style_block": "S",
            "pages": [{"idea_id": f"idea_{i:03d}", "prompt": f"p{i}"} for i in range(1, 121)],
        }
    )
    names = [j.name for j in page_jobs(prompts, 120)]
    assert names[0] == "page_001" and names[-1] == "page_120"
    assert names == sorted(names)


def test_all_pages_ok(tmp_path: Path) -> None:
    provider = FakeImageProvider(size=(48, 64))
    seen: list[PageOutcome] = []
    result = _worker(tmp_path, provider).run(_jobs(5), on_done=seen.append)

    assert [o.page for o in result.outcomes] == [1, 2, 3, 4, 5]
    assert len(seen) == 5
    assert result.failed == []
    assert result.fatal_error is None
    for outcome in result.outcomes:
        assert outcome.raw_file == tmp_path / "raw" / f"page_{outcome.page:02d}.png"
        assert png_dimensions(outcome.raw_file.read_bytes()) == (48, 64)
        assert (outcome.width, outcome.height) == (48, 64)
    assert result.usage == Usage(input_tokens=50, output_tokens=500)
    assert {r.prompt for r in provider.requests} == {f"prompt {i}" for i in range(1, 6)}
    assert {(r.aspect, r.quality) for r in provider.requests} == {("3:4", "medium")}


def test_page_failure_does_not_stop_others(tmp_path: Path) -> None:
    provider = FakeImageProvider(fail=_fail_on({2}, fatal=False))
    result = _worker(tmp_path, provider).run(_jobs(4))

    assert [o.page for o in result.ok] == [1, 3, 4]
    [failed] = result.failed
    assert (failed.page, failed.error, failed.raw_file) == (2, "boom 2", None)
    assert result.fatal_error is None
    assert not (tmp_path / "raw" / "page_02.png").exists()


def test_fatal_error_stops_new_pages(tmp_path: Path) -> None:
    provider = FakeImageProvider(fail=_fail_on({2}, fatal=True))
    result = _worker(tmp_path, provider, concurrency=1).run(_jobs(5))

    assert result.fatal_error == "boom 2"
    assert [o.page for o in result.outcomes] == [1]
    assert len(provider.requests) == 2  # strony 3–5 nie wystartowały


def test_pages_run_in_parallel(tmp_path: Path) -> None:
    barrier = threading.Barrier(3, timeout=5)

    def wait_for_all(req: ImageRequest) -> ProviderError | None:
        barrier.wait()  # przejdzie tylko, gdy 3 strony generują się naraz
        return None

    provider = FakeImageProvider(fail=wait_for_all)
    result = _worker(tmp_path, provider, concurrency=3).run(_jobs(3))
    assert len(result.ok) == 3


def test_duration_is_measured(tmp_path: Path) -> None:
    ticks = iter([10.0, 12.5])
    worker = _worker(tmp_path, FakeImageProvider(), concurrency=1)
    worker.clock = lambda: next(ticks)
    [outcome] = worker.run(_jobs(1)).outcomes
    assert outcome.duration_s == pytest.approx(2.5)
