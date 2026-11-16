"""FR-05, FR-07, FR-17 krok 2: grafika na stronę (jedno wywołanie ImageProvider.generate()) i QA.

Strony są generowane równolegle (`concurrency` wątków). Błąd jednej strony
(moderacja, przeciążenie po ponowieniach) oznacza ją jako nieudaną, a reszta idzie
dalej. Błąd krytyczny (zły klucz, brak środków, nieznany model) przerywa przebieg:
nowe strony nie startują, a te w toku kończą się normalnie.

Worker zapisuje tylko surowe grafiki w `raw/`; gotowe strony robi krok 3 (FR-17). Z QA
(FR-07) grafika przechodzi tymczasową obróbkę (`preview`, katalog tymczasowy), bo kontrola
jest skalibrowana na tym, co idzie do druku. Odrzucona surowa grafika trafia do `rejected/`,
a pozycja jest generowana ponownie z kolejnego zapasowego pomysłu (wspólna pula dla
wszystkich stron), najwyżej `max_retries` razy.
"""

from __future__ import annotations

import tempfile
import threading
import time
from collections.abc import Callable, Sequence
from concurrent.futures import CancelledError, Future, ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Literal

from kdp_studio.models import BookPrompts, PagePrompt
from kdp_studio.pipeline.output import RAW_DIR, REJECTED_DIR, page_name, write_bytes_atomic
from kdp_studio.pipeline.postprocess import PagePostprocessor, PostprocessError
from kdp_studio.pipeline.qa import QAChecker, QAIssue, QAResult
from kdp_studio.providers.base import ImageProvider, ImageRequest, ProviderError, Usage
from kdp_studio.validation import plural

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
class RejectedAttempt:
    """Próba odrzucona przez QA (FR-07); surowa grafika leży w `rejected/`."""

    attempt: int
    idea_id: str
    file: Path
    issues: list[QAIssue]


@dataclass(frozen=True)
class PageOutcome:
    page: int
    name: str
    idea_id: str  # pomysł ostatniej próby: po odrzuceniu przez QA to pomysł zapasowy
    status: PageStatus
    duration_s: float
    raw_file: Path | None = None  # None, gdy strona nieudana (odrzucona grafika jest w rejected/)
    width: int | None = None
    height: int | None = None
    error: str | None = None
    usage: Usage = field(default_factory=Usage)  # grafiki ze wszystkich prób
    prompt: str | None = None  # prompt ostatniej próby
    attempts: int = 1
    qa: QAResult | None = None  # wynik QA ostatniej próby; None bez QA
    qa_usage: Usage = field(default_factory=Usage)
    rejected: list[RejectedAttempt] = field(default_factory=list)


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

    @property
    def qa_usage(self) -> Usage:
        total = Usage()
        for outcome in self.outcomes:
            total += outcome.qa_usage
        return total

    @property
    def rejected(self) -> int:
        return sum(len(o.rejected) for o in self.outcomes)


def page_jobs(prompts: BookPrompts, pages: int) -> list[PageJob]:
    """Pierwsze `pages` promptów to strony książki; reszta to zapas dla QA (FR-07)."""
    return [
        PageJob(page=i, name=page_name(i, pages), idea_id=p.idea_id, prompt=p.prompt)
        for i, p in enumerate(prompts.pages[:pages], start=1)
    ]


class ReservePool:
    """Zapasowe pomysły (FR-03, FR-07) wydawane po kolei stronom odrzuconym przez QA."""

    def __init__(self, prompts: Sequence[PagePrompt]) -> None:
        self._prompts = list(prompts)
        self._next = 0
        self._lock = threading.Lock()

    @classmethod
    def from_prompts(cls, prompts: BookPrompts, pages: int) -> ReservePool:
        return cls(prompts.pages[pages:])

    def take(self) -> PagePrompt | None:
        with self._lock:
            if self._next >= len(self._prompts):
                return None
            self._next += 1
            return self._prompts[self._next - 1]

    @property
    def used(self) -> int:
        return self._next

    @property
    def remaining(self) -> int:
        return len(self._prompts) - self._next


@dataclass(frozen=True)
class _Render:
    """Wynik jednej próby: surowa grafika, bez QA."""

    raw_file: Path | None = None
    width: int | None = None
    height: int | None = None
    usage: Usage = field(default_factory=Usage)
    error: str | None = None


@dataclass
class PageWorker:
    provider: ImageProvider
    book_dir: Path
    aspect: str
    quality: str
    concurrency: int = 4
    qa: QAChecker | None = None  # FR-07; None: bez kontroli jakości
    # Obróbka na potrzeby QA (FR-17): wynik trafia do katalogu tymczasowego, nie do książki.
    # None: QA ocenia surową grafikę.
    preview: PagePostprocessor | None = None
    reserve: ReservePool | None = None  # zapasowe pomysły dla stron odrzuconych przez QA
    max_retries: int = 2  # ponowienia na pozycję po odrzuceniu przez QA
    clock: Callable[[], float] = time.monotonic
    _stop: threading.Event = field(default_factory=threading.Event, init=False, repr=False)

    def _render(self, name: str, prompt: str) -> _Render:
        """Surowa grafika. ProviderError z fatal=True przechodzi wyżej."""
        try:
            result = self.provider.generate(
                ImageRequest(prompt=prompt, aspect=self.aspect, quality=self.quality)
            )
        except ProviderError as e:
            if e.fatal:
                raise
            return _Render(error=str(e))
        raw = self.book_dir / RAW_DIR / f"{name}.png"
        write_bytes_atomic(raw, result.png_bytes)
        return _Render(raw_file=raw, width=result.width, height=result.height, usage=result.usage)

    def _checked_image(self, raw: Path, name: str) -> bytes:
        """Obraz dla QA: strona po tymczasowej obróbce albo surowa grafika bez `preview`.

        PostprocessError przechodzi wyżej.
        """
        if self.preview is None:
            return raw.read_bytes()
        with tempfile.TemporaryDirectory(prefix="kdp-studio-qa-") as tmp:
            files = replace(self.preview, book_dir=Path(tmp)).process(raw, name)
            return files.page.read_bytes()

    def _reject(self, raw: Path, name: str, attempt: int) -> Path:
        """Przenosi odrzuconą surową grafikę do `rejected/`. Pusty slot w `raw/` oznacza dla
        kolejnego `kdp-studio images`, że stronę trzeba wygenerować ponownie (FR-17)."""
        target = self.book_dir / REJECTED_DIR / f"{name}_try{attempt}.png"
        target.parent.mkdir(parents=True, exist_ok=True)
        raw.replace(target)
        return target

    def generate_page(self, job: PageJob) -> PageOutcome:
        """Jedna pozycja w książce, z ponowieniami po QA. ProviderError z fatal=True
        przechodzi wyżej i przerywa przebieg."""
        started = self.clock()
        idea_id, prompt = job.idea_id, job.prompt
        usage = qa_usage = Usage()
        rejected: list[RejectedAttempt] = []
        attempt = 0

        def outcome(
            render: _Render, error: str | None, qa: QAResult | None = None, *, moved: bool = False
        ) -> PageOutcome:
            # Po odrzuceniu surowa grafika leży już w rejected/.
            return PageOutcome(
                page=job.page,
                name=job.name,
                idea_id=idea_id,
                status="ok" if error is None else "failed",
                duration_s=self.clock() - started,
                raw_file=None if moved else render.raw_file,
                width=render.width,
                height=render.height,
                error=error,
                usage=usage,
                prompt=prompt,
                attempts=attempt,
                qa=qa,
                qa_usage=qa_usage,
                rejected=rejected,
            )

        while True:
            attempt += 1
            render = self._render(job.name, prompt)
            usage += render.usage
            if render.error is not None or self.qa is None:
                return outcome(render, render.error)

            raw = render.raw_file
            assert raw is not None
            try:
                checked = self._checked_image(raw, job.name)
            except PostprocessError as e:
                self._reject(raw, job.name, attempt)
                return outcome(render, f"obróbka: {e}", moved=True)
            try:
                verdict, used = self.qa.check(checked, idea_id)
            except ProviderError as e:
                if e.fatal:
                    raise
                return outcome(render, f"kontrola jakości: {e}")
            qa_usage += used
            if verdict.passed:
                return outcome(render, None, verdict)

            moved = self._reject(raw, job.name, attempt)
            rejected.append(RejectedAttempt(attempt, idea_id, moved, verdict.issues))
            tries = plural(attempt, "próbę", "próby", "prób")
            reason = f"QA odrzuciło {tries}, ostatnio: {verdict.summary()}"
            if attempt > self.max_retries:
                return outcome(render, reason, verdict, moved=True)
            replacement = self.reserve.take() if self.reserve is not None else None
            if replacement is None:
                return outcome(render, f"{reason} (brak zapasowych pomysłów)", verdict, moved=True)
            if self._stop.is_set():
                return outcome(
                    render, f"{reason} (przerwano po błędzie krytycznym)", verdict, moved=True
                )
            idea_id, prompt = replacement.idea_id, replacement.prompt

    def run(
        self,
        jobs: Sequence[PageJob],
        on_done: Callable[[PageOutcome], None] | None = None,
    ) -> ImagesResult:
        outcomes: list[PageOutcome] = []
        fatal_error: str | None = None
        # Ustawiana w wątku roboczym: wolny wątek mógłby wziąć kolejną stronę, zanim
        # główny wątek zdąży anulować kolejkę, i wysłać zbędne zapytanie.
        stop = self._stop = threading.Event()

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
