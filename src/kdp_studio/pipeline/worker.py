"""FR-05/FR-06: grafika na stronę (jedno wywołanie ImageProvider.generate()) i jej obróbka.

Strony są generowane równolegle (`concurrency` wątków). Błąd jednej strony
(moderacja, przeciążenie po ponowieniach) oznacza ją jako nieudaną, a reszta idzie
dalej. Błąd krytyczny (zły klucz, brak środków, nieznany model) przerywa przebieg:
nowe strony nie startują, a te w toku kończą się normalnie.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Sequence
from concurrent.futures import CancelledError, Future, ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from kdp_studio.models import BookPrompts
from kdp_studio.pipeline.output import RAW_DIR, page_name, write_bytes_atomic
from kdp_studio.pipeline.postprocess import PagePostprocessor, PostprocessError
from kdp_studio.providers.base import ImageProvider, ImageRequest, ProviderError, Usage

PageStatus = Literal["ok", "failed"]


class _Skipped(Exception):
    """Strona nie wystartowała, bo wcześniej wystąpił błąd krytyczny."""


@dataclass(frozen=True)
class PageJob:
    page: int  # numer strony w książce, od 1
    name: str  # page_07 albo page_007 (FR-08)
    idea_id: str
    prompt: str


@dataclass(frozen=True)
class PageOutcome:
    page: int
    name: str
    idea_id: str
    status: PageStatus
    duration_s: float
    raw_file: Path | None = None
    page_file: Path | None = None  # gotowa strona (FR-06); None bez obróbki
    svg_file: Path | None = None
    width: int | None = None
    height: int | None = None
    error: str | None = None
    usage: Usage = field(default_factory=Usage)


@dataclass(frozen=True)
class ImagesResult:
    outcomes: list[PageOutcome]  # tylko strony, które wystartowały, posortowane po numerze
    fatal_error: str | None = None

    @property
    def ok(self) -> list[PageOutcome]:
        return [o for o in self.outcomes if o.status == "ok"]

    @property
    def failed(self) -> list[PageOutcome]:
        return [o for o in self.outcomes if o.status == "failed"]

    @property
    def usage(self) -> Usage:
        total = Usage()
        for outcome in self.outcomes:
            total += outcome.usage
        return total


def page_jobs(prompts: BookPrompts, pages: int) -> list[PageJob]:
    """Pierwsze `pages` promptów to strony książki; reszta to zapas dla QA (FR-07)."""
    return [
        PageJob(page=i, name=page_name(i, pages), idea_id=p.idea_id, prompt=p.prompt)
        for i, p in enumerate(prompts.pages[:pages], start=1)
    ]


@dataclass
class PageWorker:
    provider: ImageProvider
    book_dir: Path
    aspect: str
    quality: str
    concurrency: int = 4
    postprocessor: PagePostprocessor | None = None  # FR-06; None zostawia tylko raw/
    clock: Callable[[], float] = time.monotonic

    def generate_page(self, job: PageJob) -> PageOutcome:
        """Jedna strona. ProviderError z fatal=True przechodzi wyżej i przerywa przebieg."""
        started = self.clock()
        try:
            result = self.provider.generate(
                ImageRequest(prompt=job.prompt, aspect=self.aspect, quality=self.quality)
            )
        except ProviderError as e:
            if e.fatal:
                raise
            return PageOutcome(
                page=job.page,
                name=job.name,
                idea_id=job.idea_id,
                status="failed",
                duration_s=self.clock() - started,
                error=str(e),
            )
        raw = self.book_dir / RAW_DIR / f"{job.name}.png"
        write_bytes_atomic(raw, result.png_bytes)

        page_file = svg_file = None
        error = None
        if self.postprocessor is not None:
            try:
                files = self.postprocessor.process(raw, job.name)
                page_file, svg_file = files.page, files.svg
            except PostprocessError as e:
                error = f"obróbka: {e}"
        return PageOutcome(
            page=job.page,
            name=job.name,
            idea_id=job.idea_id,
            status="ok" if error is None else "failed",
            duration_s=self.clock() - started,
            raw_file=raw,
            page_file=page_file,
            svg_file=svg_file,
            width=result.width,
            height=result.height,
            error=error,
            usage=result.usage,
        )

    def run(
        self,
        jobs: Sequence[PageJob],
        on_done: Callable[[PageOutcome], None] | None = None,
    ) -> ImagesResult:
        outcomes: list[PageOutcome] = []
        fatal_error: str | None = None
        # Ustawiana w wątku roboczym: wolny wątek mógłby wziąć kolejną stronę, zanim
        # główny wątek zdąży anulować kolejkę, i wysłać zbędne zapytanie.
        stop = threading.Event()

        def run_job(job: PageJob) -> PageOutcome:
            if stop.is_set():
                raise _Skipped
            try:
                return self.generate_page(job)
            except ProviderError:
                stop.set()
                raise

        pool = ThreadPoolExecutor(max_workers=self.concurrency, thread_name_prefix="page")
        futures: list[Future[PageOutcome]] = [pool.submit(run_job, j) for j in jobs]
        try:
            for future in as_completed(futures):
                try:
                    outcome = future.result()
                except (CancelledError, _Skipped):
                    continue
                except ProviderError as e:
                    if fatal_error is None:
                        fatal_error = str(e)
                        for pending in futures:
                            pending.cancel()
                    continue
                outcomes.append(outcome)
                if on_done is not None:
                    on_done(outcome)
        except BaseException:
            # Ctrl+C: nie czekamy na kolejne strony, tylko na te już wysłane.
            pool.shutdown(wait=False, cancel_futures=True)
            raise
        pool.shutdown(wait=True)
        outcomes.sort(key=lambda o: o.page)
        return ImagesResult(outcomes=outcomes, fatal_error=fatal_error)
