"""FR-08: `manifest.json` zapisywany przyrostowo po każdej stronie (NFR-04, NFR-08).

Manifest zawiera wszystko, czego potrzeba, żeby odtworzyć albo wznowić książkę (FR-09):
parametry wejściowe, dostawców i modele, geometrię strony oraz prompt, status i pliki
każdej strony. Nie zawiera kluczy API (NFR-10). Ścieżki są względne do katalogu książki.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from kdp_studio import __version__
from kdp_studio.pipeline.output import write_json_atomic
from kdp_studio.pipeline.qa import QAIssue, QAResult
from kdp_studio.pipeline.worker import PageJob, PageOutcome
from kdp_studio.providers.base import Usage

MANIFEST_FILE = "manifest.json"

# FR-13: w manifeście, w podsumowaniu w konsoli i w canva.md.
AI_DISCLOSURE = (
    "Przy publikacji w KDP zaznacz „AI-generated content” dla obrazów: grafiki w tej "
    "książce wygenerował model AI."
)

BookStatus = Literal["running", "completed", "partial", "failed"]
PageStatus = Literal["pending", "ok", "failed"]


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ManifestInput(_Model):
    theme: str
    age: str
    style: str
    format: str
    pages: int
    front_matter_pages: int
    concurrency: int
    review_ideas: bool
    qa: bool = False


class ProviderInfo(_Model):
    provider: str
    model: str


class ImageProviderInfo(ProviderInfo):
    quality: str
    aspect: str


class ManifestProviders(_Model):
    text: ProviderInfo
    image: ImageProviderInfo
    vision: ProviderInfo | None = None  # tylko z QA (FR-07)


class ManifestLayout(_Model):
    """Geometria strony (FR-06): jedna dla całej książki."""

    trim_in: tuple[float, float]
    page_px: tuple[int, int]
    dpi: int
    pages_in_book: int
    gutter_in: float
    margin_in: float


class ManifestIdeas(_Model):
    file: str = "ideas.json"
    prompts_file: str = "prompts.json"
    count: int
    reserve: int
    reviewed: bool
    usage: Usage


class PageFilesInfo(_Model):
    png: str | None = None
    svg: str | None = None
    raw: str | None = None


class ManifestRejected(_Model):
    """Próba odrzucona przez QA; plik w `rejected/` (spec §10)."""

    attempt: int
    idea_id: str
    file: str
    issues: list[QAIssue]


class ManifestPage(_Model):
    page: int
    name: str
    idea_id: str
    status: PageStatus = "pending"
    attempts: int = 0
    provider: str
    model: str
    prompt: str
    qa: QAResult | None = None  # FR-07, wynik ostatniej próby
    cost_usd: float | None = None  # FR-10
    usage: Usage | None = None
    qa_usage: Usage | None = None
    duration_s: float | None = None
    error: str | None = None
    files: PageFilesInfo = Field(default_factory=PageFilesInfo)
    rejected: list[ManifestRejected] = []


class Manifest(_Model):
    tool: str = "kdp-studio"
    version: str = __version__
    created_at: str = Field(default_factory=_now)
    updated_at: str = Field(default_factory=_now)
    status: BookStatus = "running"
    error: str | None = None
    input: ManifestInput
    providers: ManifestProviders
    layout: ManifestLayout
    ideas: ManifestIdeas
    pages: list[ManifestPage]
    ai_disclosure: str = AI_DISCLOSURE

    @property
    def ok_pages(self) -> list[ManifestPage]:
        return [p for p in self.pages if p.status == "ok"]


def _relative(path: Path | None, root: Path) -> str | None:
    if path is None:
        return None
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


class ManifestWriter:
    """Trzyma manifest w pamięci i zapisuje go atomowo po każdej zmianie.

    Wywoływany tylko z wątku głównego (callback `on_done` workera), więc bez blokad.
    """

    def __init__(self, book_dir: Path, manifest: Manifest) -> None:
        self.book_dir = book_dir
        self.path = book_dir / MANIFEST_FILE
        self.manifest = manifest
        self._index = {p.page: i for i, p in enumerate(manifest.pages)}
        self.save()

    @classmethod
    def start(
        cls,
        book_dir: Path,
        *,
        jobs: list[PageJob],
        input: ManifestInput,
        providers: ManifestProviders,
        layout: ManifestLayout,
        ideas: ManifestIdeas,
    ) -> ManifestWriter:
        image = providers.image
        pages = [
            ManifestPage(
                page=job.page,
                name=job.name,
                idea_id=job.idea_id,
                provider=image.provider,
                model=image.model,
                prompt=job.prompt,
            )
            for job in jobs
        ]
        manifest = Manifest(
            input=input, providers=providers, layout=layout, ideas=ideas, pages=pages
        )
        return cls(book_dir, manifest)

    def save(self) -> None:
        self.manifest.updated_at = _now()
        write_json_atomic(self.path, self.manifest)

    def record(self, outcome: PageOutcome) -> None:
        page = self.manifest.pages[self._index[outcome.page]]
        page.status = outcome.status
        page.idea_id = outcome.idea_id  # po odrzuceniu przez QA: pomysł zapasowy
        if outcome.prompt is not None:
            page.prompt = outcome.prompt
        page.attempts += outcome.attempts
        page.duration_s = round(outcome.duration_s, 2)
        page.usage = outcome.usage
        page.qa = outcome.qa
        page.qa_usage = outcome.qa_usage if self.manifest.input.qa else None
        page.error = outcome.error
        page.rejected += [
            ManifestRejected(
                attempt=r.attempt,
                idea_id=r.idea_id,
                file=_relative(r.file, self.book_dir) or "",
                issues=r.issues,
            )
            for r in outcome.rejected
        ]
        page.files = PageFilesInfo(
            png=_relative(outcome.page_file, self.book_dir),
            svg=_relative(outcome.svg_file, self.book_dir),
            raw=_relative(outcome.raw_file, self.book_dir),
        )
        self.save()

    def finish(self, fatal_error: str | None = None) -> BookStatus:
        manifest = self.manifest
        if fatal_error is not None:
            manifest.status, manifest.error = "failed", fatal_error
        elif all(p.status == "ok" for p in manifest.pages):
            manifest.status = "completed"
        else:
            manifest.status = "partial"
        self.save()
        return manifest.status
