"""FR-08, FR-17: `manifest.json` zapisywany przyrostowo po każdej stronie (NFR-04, NFR-08).

Manifest powstaje w kroku 1 (`kdp-studio ideas`) i jest stanem generowania krokowego:
parametry wejściowe, dostawców i modele, geometrię strony oraz pomysł, prompt, sumy
kontrolne, status i pliki każdej strony. Kroki 2 i 3 czytają go, wykonują tylko brakującą
pracę i zapisują wynik. Nie zawiera kluczy API (NFR-10). Ścieżki są względne do katalogu
książki.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

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

# FR-17: ideas_ready (po kroku 1) → raw_ready (po kroku 2) → completed (po kroku 3);
# partial: brakuje stron, failed: błąd krytyczny. "running" tylko w manifestach sprzed FR-17.
BookStatus = Literal["ideas_ready", "raw_ready", "completed", "partial", "failed", "running"]
# pending: brak surowej grafiki, raw_ok: surowa grafika gotowa, ok: gotowa strona do Canvy.
PageStatus = Literal["pending", "raw_ok", "ok", "failed"]
PageAction = Literal["regenerate"]


class ManifestError(Exception):
    """Brak albo niepoprawny `manifest.json` (kod wyjścia 1)."""


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


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


class FinalInfo(_Model):
    """Z czego powstała gotowa strona (FR-17 krok 3); zmiana któregoś wymusza ponowną obróbkę."""

    raw_sha256: str
    postprocess_sha256: str  # parametry obróbki z profilu wieku i geometria strony


class ManifestRejected(_Model):
    """Próba odrzucona przez QA; plik w `rejected/` (spec §10)."""

    attempt: int
    idea_id: str
    file: str
    issues: list[QAIssue]


class ManifestPage(_Model):
    page: int
    name: str
    idea_id: str  # użytkownik może go zmienić, np. na pomysł z zapasu (FR-17)
    status: PageStatus = "pending"
    action: PageAction | None = None  # ustawia użytkownik; program czyści po wykonaniu
    edited_by_user: bool = False  # surowa grafika podmieniona przez użytkownika
    attempts: int = 0
    provider: str
    model: str
    quality: str | None = None  # jakość modelu obrazu użyta dla surowej grafiki
    prompt: str
    prompt_sha256: str | None = None  # prompt, z którego powstała surowa grafika
    raw_sha256: str | None = None  # surowa grafika przyjęta przez program
    final: FinalInfo | None = None
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

    def __init__(self, book_dir: Path, manifest: Manifest, *, save: bool = True) -> None:
        self.book_dir = book_dir
        self.path = book_dir / MANIFEST_FILE
        self.manifest = manifest
        self._index = {p.page: i for i, p in enumerate(manifest.pages)}
        if save:
            self.save()

    @classmethod
    def load(cls, book_dir: Path) -> ManifestWriter:
        path = book_dir / MANIFEST_FILE
        if not path.is_file():
            raise ManifestError(
                f"brak {path}: to nie jest katalog książki (najpierw kdp-studio ideas)"
            )
        try:
            manifest = Manifest.model_validate_json(path.read_bytes())
        except ValidationError as e:
            problems = "; ".join(
                f"{'.'.join(str(x) for x in err['loc'])}: {err['msg']}" for err in e.errors()
            )
            raise ManifestError(f"niepoprawny {path}: {problems}") from e
        return cls(book_dir, manifest, save=False)

    def page(self, number: int) -> ManifestPage:
        return self.manifest.pages[self._index[number]]

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
            status="ideas_ready",
            input=input,
            providers=providers,
            layout=layout,
            ideas=ideas,
            pages=pages,
        )
        return cls(book_dir, manifest)

    def save(self) -> None:
        self.manifest.updated_at = _now()
        write_json_atomic(self.path, self.manifest)

    def record_raw(self, outcome: PageOutcome, *, provider: str, model: str, quality: str) -> None:
        """Wynik kroku 2 dla jednej strony: surowa grafika (raw_ok) albo błąd (failed)."""
        page = self.page(outcome.page)
        ok = outcome.status == "ok" and outcome.raw_file is not None
        page.status = "raw_ok" if ok else "failed"
        page.idea_id = outcome.idea_id  # po odrzuceniu przez QA: pomysł zapasowy
        if outcome.prompt is not None:
            page.prompt = outcome.prompt
        page.prompt_sha256 = sha256_text(page.prompt) if ok else None
        page.raw_sha256 = sha256_file(outcome.raw_file) if ok and outcome.raw_file else None
        page.action = None
        page.edited_by_user = False
        page.final = None
        page.provider, page.model, page.quality = provider, model, quality
        page.attempts += outcome.attempts
        page.duration_s = round(outcome.duration_s, 2)
        page.usage = outcome.usage
        page.qa = outcome.qa
        page.qa_usage = outcome.qa_usage if outcome.qa is not None else None
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
        page.files = PageFilesInfo(raw=_relative(outcome.raw_file, self.book_dir))
        self.save()

    def mark_edited(self, number: int, raw_sha256: str) -> None:
        """Użytkownik podmienił surową grafikę: program jej nie generuje ponownie (FR-17)."""
        page = self.page(number)
        page.edited_by_user = True
        page.raw_sha256 = raw_sha256
        page.status = "raw_ok"
        page.final = None
        page.error = None
        page.files = PageFilesInfo(raw=f"raw/{page.name}.png")
        self.save()

    def record_final(
        self,
        number: int,
        *,
        png: Path | None,
        svg: Path | None,
        final: FinalInfo | None,
        error: str | None,
    ) -> None:
        """Wynik kroku 3 dla jednej strony: gotowa strona (ok) albo błąd obróbki (failed)."""
        page = self.page(number)
        page.status = "ok" if error is None else "failed"
        page.error = error
        # Także po błędzie: te same wejścia dałyby ten sam błąd, więc krok 3 ich nie powtarza.
        page.final = final
        page.files = PageFilesInfo(
            png=_relative(png, self.book_dir) if error is None else None,
            svg=_relative(svg, self.book_dir) if error is None else None,
            raw=page.files.raw,
        )
        self.save()

    def update_status(self, fatal_error: str | None = None) -> BookStatus:
        """Stan książki z wyników stron; `fatal_error` z kroku 2 daje `failed`."""
        manifest = self.manifest
        statuses = {p.status for p in manifest.pages}
        manifest.error = fatal_error
        if fatal_error is not None:
            manifest.status = "failed"
        elif statuses == {"ok"}:
            manifest.status = "completed"
        elif statuses & {"pending", "failed"}:
            manifest.status = "partial"
        else:
            manifest.status = "raw_ready"
        self.save()
        return manifest.status
