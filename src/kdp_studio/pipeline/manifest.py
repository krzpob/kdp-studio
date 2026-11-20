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
from kdp_studio.book_input import BookInput, ConfigFileInfo
from kdp_studio.config import CopyrightVariant
from kdp_studio.pipeline.belongs_to import FRONT_NAME, BelongsToOutcome, Layout
from kdp_studio.pipeline.cost import COST_DIGITS
from kdp_studio.pipeline.cover_vision import CoverQAResult
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
BookStatus = Literal[
    "ideas_ready", "raw_ready", "completed", "partial", "failed", "budget_exceeded", "running"
]
# pending: brak surowej grafiki, raw_ok: surowa grafika gotowa, ok: gotowa strona do Canvy.
PageStatus = Literal["pending", "raw_ok", "ok", "failed"]
PageAction = Literal["regenerate"]
# Strony wstępne z grafiką (FR-14, FR-23): klucz wpisu w `front_matter`.
FrontKind = Literal["belongs_to", "title", "instructions"]


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


class ManifestInput(BookInput):
    """Skuteczne parametry książki (FR-20): ten sam schemat co plik `--config-file`, z polami
    wymaganymi i domyślnymi dla starych manifestów, plus pola, których plik nie ma."""

    theme: str
    age: str
    style: str
    format: str
    pages: int
    front_matter_pages: int
    market: str = "US"  # FR-19; stara książka bez tego pola to US
    single_sided: bool = True  # FR-22; stara książka: druk jednostronny jak w D8
    # FR-23; stara książka bez tych pól nie ma stron praw autorskich ani instrukcji.
    copyright: CopyrightVariant = "short"
    concurrency: int
    review_ideas: bool
    qa: bool = False
    config_file: ConfigFileInfo | None = None  # FR-20: użyty plik parametrów
    overrides: list[str] = Field(default_factory=list)  # FR-20: klucze nadpisane flagami


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
    cost_usd: float = 0.0  # FR-10: pomysły, weryfikacja i --redo, wszystkie uruchomienia


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
    cost_usd: float | None = None  # FR-10: grafiki i QA tej strony, wszystkie uruchomienia
    usage: Usage | None = None
    qa_usage: Usage | None = None
    duration_s: float | None = None
    error: str | None = None
    files: PageFilesInfo = Field(default_factory=PageFilesInfo)
    rejected: list[ManifestRejected] = []


class FrontPage(_Model):
    """Strona „This book belongs to…” (FR-14): pola jak wpis strony plus wybrany układ."""

    name: str = FRONT_NAME
    status: PageStatus = "pending"
    action: PageAction | None = None
    attempts: int = 0
    provider: str
    model: str
    quality: str | None = None
    prompt: str
    prompt_sha256: str | None = None
    raw_sha256: str | None = None
    final: FinalInfo | None = None
    layout: Layout | None = None  # frame: ramka modelu; fallback: grafika strony + napis
    fallback_source: str | None = None  # strona książki, której grafika jest w układzie zapasowym
    elements: list[str] = []  # elementy motywu w prompcie
    qa: QAResult | None = None
    cost_usd: float | None = None
    usage: Usage | None = None
    qa_usage: Usage | None = None
    duration_s: float | None = None
    error: str | None = None
    files: PageFilesInfo = Field(default_factory=PageFilesInfo)
    rejected: list[ManifestRejected] = []


class CopyrightPage(_Model):
    """Strona praw autorskich (FR-23): tekst z `texts` rynku, wpisany przez program."""

    name: str = "front_copyright"
    status: PageStatus = "pending"
    language: str  # klucz tłumaczenia z markets.yaml (np. en-GB albo en)
    variant: str
    owner: str
    year: int
    text_sha256: str | None = None
    final: FinalInfo | None = None
    files: PageFilesInfo = Field(default_factory=PageFilesInfo)
    error: str | None = None


class FrontMatter(_Model):
    belongs_to: FrontPage | None = None  # strona 1 „This book belongs to…” (FR-14)
    title: FrontPage | None = None  # strona 1 tytułowa do kolorowania (FR-23)
    copyright: CopyrightPage | None = None  # strona 2 (FR-23)
    instructions: FrontPage | None = None  # strona 3 (FR-23)

    def pages(self) -> list[FrontPage | CopyrightPage]:
        return [p for p in (self.belongs_to, self.title, self.copyright, self.instructions) if p]


class CoverTemplateInfo(_Model):
    file: str
    problems: list[str] = []


class CoverCmykInfo(_Model):
    profile: str  # opis profilu ICC
    profile_file: str | None = None
    profile_sha256: str | None = None
    rendering_intent: str
    black_point_compensation: bool
    max_total_ink_limit_pct: int
    max_total_ink_pct: float  # w gotowym pliku
    ink_limited_pct: float  # odsetek pikseli z ograniczoną sumą farb
    gamut_warn_delta_e: float
    gamut_area_pct: float  # powierzchnia ze zmianą koloru > gamut_warn_delta_e
    title_gamut_warning: bool


class CoverFiles(_Model):
    pdf: str
    png: str
    front: str
    proof: str
    gamut: str
    preview: str


class CoverFrontInfo(_Model):
    """Przód okładki: kolorowanie modelem (etap 2) i czytelność tytułu."""

    colorized: bool
    provider: str | None = None
    model: str | None = None
    quality: str | None = None
    aspect: str | None = None
    prompt: str | None = None
    attempts: int = 0
    raw_files: list[str] = []
    errors: list[str] = []
    usage: Usage | None = None
    contour_match: float | None = None  # zgodność konturów modelu ze szkicem
    contours_overlay: bool = True  # nałożono ostre kontury 300 DPI (K100)
    register_cc: float | None = None  # obraz modelu dopasowany do szkicu (zgodność ECC)
    title_band_edges: list[float] = []  # krawędzie w pasie tytułu w kolejnych próbach
    title_thumb_px: float = 0.0  # wysokość liter tytułu w miniaturze (thumbnail_check_px)
    title_contrast: float = 0.0  # kontrast WCAG tytułu z tłem


class CoverSeamInfo(_Model):
    """Kontrola styku grzbiet/przód jednej próby tyłu (etap 3)."""

    max_delta_e: float
    horizon_front: float | None = None
    horizon_back: float | None = None
    align_shift: float | None = None  # największe przesunięcie wierszy tyłu do przodu (ułamek)
    register_cc: float | None = None  # dorysowanie: zgodność pasa przodu po rejestracji (ECC)
    passed: bool


class CoverSceneInfo(_Model):
    """Ocena przodu modelem z wizją: horyzont i kolory tła przy lewej krawędzi."""

    horizon: float | None = None
    band_colors: list[str] = []
    background: str = ""
    usage: Usage | None = None


class CoverBackInfo(_Model):
    """Tło tyłu i grzbietu z modelu (etap 3)."""

    painted: bool
    provider: str | None = None
    model: str | None = None
    quality: str | None = None
    aspect: str | None = None
    mode: str | None = None  # outpaint: dorysowanie przodu z maską; reference: przód jako wzór
    overlap_px: int | None = None  # pas przodu na płótnie do dorysowania (piksele okładki)
    prompt: str | None = None
    attempts: int = 0
    chosen_attempt: int | None = None
    raw_files: list[str] = []
    errors: list[str] = []
    usage: Usage | None = None
    scene: CoverSceneInfo | None = None
    scene_error: str | None = None
    edge_colors: list[str] = []  # próbki pikseli lewej krawędzi przodu, od góry
    seams: list[CoverSeamInfo] = []
    seam_passed: bool | None = None


class CoverSelectionInfo(_Model):
    """Propozycja stron modelem z wizją (arkusz kontaktowy, etap 3)."""

    model: str
    reason: str
    contact_sheet: str
    usage: Usage
    warnings: list[str] = []


class CoverInfo(_Model):
    """Okładka paperback (FR-15, `kdp-studio cover`)."""

    # qa_failed: pliki zapisane, ale QA (`--qa`) odrzuciła okładkę albo się nie udała
    status: Literal["ok", "failed", "qa_failed"] = "ok"
    created_at: str = Field(default_factory=_now)
    geometry: dict[str, object]
    front_page: str
    thumbnails: list[str]
    selection: Literal["manual", "default", "vision"]
    selection_info: CoverSelectionInfo | None = None
    title: str
    subtitle: str
    spine_text: bool
    placements: dict[str, tuple[int, int, int, int]] = {}  # px, kontrola rozmieszczenia
    template: CoverTemplateInfo | None = None
    front: CoverFrontInfo | None = None
    back: CoverBackInfo | None = None
    back_text: bool = False
    qa: CoverQAResult | None = None
    qa_error: str | None = None
    qa_usage: Usage | None = None
    cmyk: CoverCmykInfo | None = None
    files: CoverFiles | None = None
    warnings: list[str] = []
    cost_usd: float = 0.0
    error: str | None = None


class DescriptionInfo(_Model):
    """Opis do KDP (FR-03) złożony przez program: `description.html`."""

    file: str = "description.html"
    chars: int  # długość ze znacznikami HTML, jak liczy KDP (limit 4000)
    sha256: str
    language: str | None  # tłumaczenie faktów i nagłówków z `texts`; None: opis bez faktów
    created_at: str = Field(default_factory=_now)


class InteriorInfo(_Model):
    """Gotowe wnętrze `interior.pdf` (FR-22, krok 3)."""

    file: str = "interior.pdf"
    pages: int  # liczba stron PDF; od niej `cover` liczy grzbiet
    single_sided: bool
    sha256: str
    inputs_sha256: str  # kolejność i hashe plików stron: zmiana wymusza nowy PDF
    order: list[str | None]  # strona PDF → plik strony bez .png; None to pusta strona
    created_at: str = Field(default_factory=_now)


class Manifest(_Model):
    tool: str = "kdp-studio"
    version: str = __version__
    created_at: str = Field(default_factory=_now)
    updated_at: str = Field(default_factory=_now)
    status: BookStatus = "running"
    error: str | None = None
    cost_usd: float = 0.0  # FR-10: łączny koszt API książki ze wszystkich uruchomień
    input: ManifestInput
    providers: ManifestProviders
    layout: ManifestLayout
    ideas: ManifestIdeas
    pages: list[ManifestPage]
    front_matter: FrontMatter = Field(default_factory=FrontMatter)
    cover: CoverInfo | None = None  # FR-15
    interior: InteriorInfo | None = None  # FR-22
    description: DescriptionInfo | None = None  # FR-03: opis do KDP
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
            cost_usd=ideas.cost_usd,
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

    def add_ideas_cost(self, usage: Usage, cost_usd: float) -> None:
        """Kolejne wywołania modelu tekstowego dla pomysłów (`--redo`, FR-17)."""
        ideas = self.manifest.ideas
        ideas.usage += usage
        ideas.cost_usd = round(ideas.cost_usd + cost_usd, COST_DIGITS)
        self.manifest.cost_usd = round(self.manifest.cost_usd + cost_usd, COST_DIGITS)
        self.save()

    def record_raw(
        self,
        outcome: PageOutcome,
        *,
        provider: str,
        model: str,
        quality: str,
        cost_usd: float = 0.0,
    ) -> None:
        """Wynik kroku 2 dla jednej strony: surowa grafika (raw_ok) albo błąd (failed).

        `cost_usd` (grafiki i QA tego uruchomienia) dolicza się do strony i książki.
        """
        page = self.page(outcome.page)
        page.cost_usd = round((page.cost_usd or 0.0) + cost_usd, COST_DIGITS)
        self.manifest.cost_usd = round(self.manifest.cost_usd + cost_usd, COST_DIGITS)
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

    @property
    def front(self) -> FrontPage | None:
        return self.manifest.front_matter.belongs_to

    def front_page(self, kind: FrontKind) -> FrontPage | None:
        page: FrontPage | None = getattr(self.manifest.front_matter, kind)
        return page

    def set_front(self, front: FrontPage | None, kind: FrontKind = "belongs_to") -> None:
        setattr(self.manifest.front_matter, kind, front)
        self.save()

    def set_copyright(self, page: CopyrightPage | None) -> None:
        self.manifest.front_matter.copyright = page
        self.save()

    def record_copyright(
        self, page: CopyrightPage, *, png: Path | None, final: FinalInfo, error: str | None
    ) -> None:
        """Strona praw autorskich po `finalize` (FR-23); `final` zostaje po błędzie."""
        page.status = "ok" if error is None else "failed"
        page.error = error
        page.final = final
        page.files = PageFilesInfo(png=_relative(png, self.book_dir) if error is None else None)
        self.manifest.front_matter.copyright = page
        self.save()

    def record_front_raw(
        self,
        outcome: BelongsToOutcome,
        *,
        provider: str,
        model: str,
        quality: str,
        cost_usd: float = 0.0,
        kind: FrontKind = "belongs_to",
    ) -> None:
        """Grafika strony wstępnej z modelu (albo układ zapasowy) i jej koszt, albo błąd."""
        front = self.front_page(kind)
        assert front is not None
        ok = outcome.status == "ok" and outcome.raw_file is not None
        front.status = "raw_ok" if ok else "failed"
        front.prompt = outcome.prompt
        front.prompt_sha256 = sha256_text(outcome.prompt) if ok else None
        front.raw_sha256 = sha256_file(outcome.raw_file) if ok and outcome.raw_file else None
        front.layout = outcome.layout
        front.fallback_source = outcome.fallback_source
        front.action = None
        front.final = None
        front.provider, front.model, front.quality = provider, model, quality
        front.attempts += outcome.attempts
        front.duration_s = round(outcome.duration_s, 2)
        front.usage = outcome.usage
        front.qa = outcome.qa
        front.qa_usage = outcome.qa_usage if outcome.qa is not None else None
        front.error = outcome.error
        front.cost_usd = round((front.cost_usd or 0.0) + cost_usd, COST_DIGITS)
        self.manifest.cost_usd = round(self.manifest.cost_usd + cost_usd, COST_DIGITS)
        front.rejected += [
            ManifestRejected(
                attempt=r.attempt,
                idea_id=r.idea_id,
                file=_relative(r.file, self.book_dir) or "",
                issues=r.issues,
            )
            for r in outcome.rejected
        ]
        front.files = PageFilesInfo(raw=_relative(outcome.raw_file, self.book_dir))
        self.save()

    def record_front_final(
        self,
        *,
        png: Path | None,
        svg: Path | None,
        final: FinalInfo,
        error: str | None,
        kind: FrontKind = "belongs_to",
    ) -> None:
        """Gotowa strona wstępna z napisem; jak w record_final, `final` zostaje po błędzie."""
        front = self.front_page(kind)
        assert front is not None
        front.status = "ok" if error is None else "failed"
        front.error = error
        front.final = final
        front.files = PageFilesInfo(
            png=_relative(png, self.book_dir) if error is None else None,
            svg=_relative(svg, self.book_dir) if error is None else None,
            raw=front.files.raw,
        )
        self.save()

    def update_status(
        self, fatal_error: str | None = None, *, budget_error: str | None = None
    ) -> BookStatus:
        """Stan książki z wyników stron; `fatal_error` z kroku 2 daje `failed`,
        a przekroczony limit kosztu (FR-10) `budget_exceeded`."""
        manifest = self.manifest
        statuses = {p.status for p in manifest.pages}
        for front in manifest.front_matter.pages():  # strony wstępne liczą się jak strony
            statuses.add(front.status)
        manifest.error = fatal_error or budget_error
        if fatal_error is not None:
            manifest.status = "failed"
        elif budget_error is not None:
            manifest.status = "budget_exceeded"
        elif statuses == {"ok"}:
            manifest.status = "completed"
        elif statuses & {"pending", "failed"}:
            manifest.status = "partial"
        else:
            manifest.status = "raw_ready"
        self.save()
        return manifest.status
