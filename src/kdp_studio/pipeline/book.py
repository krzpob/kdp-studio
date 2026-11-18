"""FR-17: stan książki między krokami, blokada katalogu i plan pracy kroków 2 i 3.

Każdy krok czyta `manifest.json` i `ideas.json`, sprawdza, co się zmieniło od poprzedniego
uruchomienia, i wykonuje tylko brakującą pracę. Bez zmian ponowne uruchomienie kroku nic
nie robi. Moduł nie woła API: plan liczy się z plików, a wykonuje go CLI.
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from types import TracebackType

from pydantic import ValidationError

from kdp_studio.models import BookIdeas, BookPrompts, BookSpec, PagePrompt
from kdp_studio.pipeline.belongs_to import FRONT_NAME
from kdp_studio.pipeline.manifest import (
    FrontPage,
    Manifest,
    ManifestPage,
    sha256_file,
    sha256_text,
)
from kdp_studio.pipeline.output import IDEAS_FILE, LOG_FILE, RAW_DIR
from kdp_studio.pipeline.postprocess import PageGeometry
from kdp_studio.pipeline.worker import PageJob

LOCK_FILE = ".kdp-studio.lock"


class BookError(Exception):
    """Katalog książki w stanie, który nie pozwala wykonać kroku (kod wyjścia 1)."""

    def __init__(self, errors: Sequence[str]) -> None:
        super().__init__("; ".join(errors))
        self.errors = list(errors)


# --- Blokada ------------------------------------------------------------------------


class BookLock:
    """Plik blokady w katalogu książki: dwa równoczesne uruchomienia psułyby manifest.

    Tworzony atomowo (O_EXCL), usuwany po zakończeniu, także po Ctrl+C. Po twardym
    przerwaniu procesu plik zostaje i użytkownik usuwa go ręcznie (komunikat to mówi).
    """

    def __init__(self, book_dir: Path) -> None:
        self.path = book_dir / LOCK_FILE
        self._created_dir = False

    def __enter__(self) -> BookLock:
        self.acquire()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.release()

    def release(self) -> None:
        self.path.unlink(missing_ok=True)
        # Krok przerwany przed pierwszym plikiem nie zostawia pustego katalogu książki
        # (sam log nieudanego kroku 1 to za mało, żeby katalog został).
        parent = self.path.parent
        if self._created_dir and all(p.name == LOG_FILE for p in parent.iterdir()):
            (parent / LOG_FILE).unlink(missing_ok=True)
            parent.rmdir()

    def acquire(self) -> None:
        self._created_dir = not self.path.parent.exists()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError as e:
            raise BookError(
                [
                    f"katalog {self.path.parent} jest używany przez inne uruchomienie "
                    f"kdp-studio (plik {self.path.name}). Jeśli żadne nie działa, usuń ten plik"
                ]
            ) from e
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(f"pid {os.getpid()}, {datetime.now(UTC).isoformat(timespec='seconds')}\n")


# --- Wczytanie i walidacja ------------------------------------------------------------


def spec_from_manifest(manifest: Manifest) -> BookSpec:
    data = manifest.input
    return BookSpec(
        theme=data.theme,
        age=data.age,
        style=data.style,
        format=data.format,
        pages=data.pages,
        front_matter_pages=data.front_matter_pages,
        market=data.market,
    )


def load_ideas(book_dir: Path) -> BookIdeas:
    """`ideas.json` po ewentualnej ręcznej edycji (FR-17); błąd schematu to BookError."""
    path = book_dir / IDEAS_FILE
    if not path.is_file():
        raise BookError([f"brak {path}"])
    try:
        return BookIdeas.model_validate_json(path.read_bytes())
    except ValidationError as e:
        problems = [
            f"{path.name}: {'.'.join(str(x) for x in err['loc'])}: {err['msg']}"
            for err in e.errors()
        ]
        raise BookError(problems) from e


def check_assignment(manifest: Manifest, ideas: BookIdeas) -> list[str]:
    """Błędy przypisania pomysłów do stron, zanim powstanie jakakolwiek grafika (kod 1)."""
    errors: list[str] = []
    ids = [idea.id for idea in ideas.pages]
    duplicates = sorted({i for i in ids if ids.count(i) > 1})
    if duplicates:
        errors.append(f"{IDEAS_FILE}: powtórzone id: {', '.join(duplicates)}")
    pages = manifest.input.pages
    if len(ids) < pages:
        errors.append(f"{IDEAS_FILE}: {len(ids)} pomysłów, a książka ma {pages} stron")
    known = set(ids)
    used: dict[str, str] = {}
    for page in manifest.pages:
        if page.idea_id not in known:
            errors.append(
                f"{page.name}: pomysłu {page.idea_id} nie ma w {IDEAS_FILE} "
                "(zmień idea_id w manifest.json albo przywróć pomysł)"
            )
        elif page.idea_id in used:
            errors.append(
                f"{page.name}: pomysł {page.idea_id} jest już na stronie {used[page.idea_id]}"
            )
        else:
            used[page.idea_id] = page.name
    return errors


def never_generated(manifest: Manifest) -> bool:
    """Żadna strona nie ma jeszcze grafiki: przypisanie wynika wtedy z kolejności w ideas.json."""
    return all(
        p.status == "pending" and p.raw_sha256 is None and p.attempts == 0 for p in manifest.pages
    )


def sync_order(manifest: Manifest, ideas: BookIdeas) -> None:
    """Przed pierwszą grafiką strony biorą pierwsze `pages` pomysłów z ideas.json, więc
    zmiana kolejności albo usunięcie pomysłu w ideas.json zmienia przypisanie (FR-17)."""
    for page, idea in zip(manifest.pages, ideas.pages, strict=False):
        page.idea_id = idea.id


# --- Krok 2: plan grafik --------------------------------------------------------------


@dataclass(frozen=True)
class ImagesPlan:
    jobs: list[PageJob]
    reasons: dict[str, str]  # nazwa strony → dlaczego trafia do kolejki (po polsku)
    edited: list[tuple[int, str]] = field(default_factory=list)  # (strona, nowa suma raw)
    reserve: list[PagePrompt] = field(default_factory=list)


def raw_path(book_dir: Path, page: ManifestPage) -> Path:
    return book_dir / RAW_DIR / f"{page.name}.png"


def user_edits(book_dir: Path, manifest: Manifest) -> list[tuple[int, str]]:
    """Strony, których surową grafikę użytkownik podmienił (inna suma niż przyjęta)."""
    edited: list[tuple[int, str]] = []
    for page in manifest.pages:
        raw = raw_path(book_dir, page)
        if page.raw_sha256 is None or page.action is not None or not raw.is_file():
            continue
        digest = sha256_file(raw)
        if digest != page.raw_sha256:
            edited.append((page.page, digest))
    return edited


def plan_images(
    book_dir: Path, manifest: Manifest, ideas: BookIdeas, prompts: BookPrompts
) -> ImagesPlan:
    """Strony do wygenerowania w kroku 2 i zapas dla QA. Nie zmienia manifestu."""
    by_id = {p.idea_id: p.prompt for p in prompts.pages}
    edited = dict(user_edits(book_dir, manifest))
    jobs: list[PageJob] = []
    reasons: dict[str, str] = {}
    for page in manifest.pages:
        prompt = by_id[page.idea_id]
        raw = raw_path(book_dir, page)
        reason = None
        if page.action == "regenerate":
            reason = "action: regenerate"
        elif page.page in edited or (page.edited_by_user and raw.is_file()):
            continue  # własna wersja użytkownika
        elif page.raw_sha256 is None or not raw.is_file():
            reason = "nieudana" if page.status == "failed" else "brak grafiki"
        elif page.status == "failed":
            reason = "nieudana"
        elif page.prompt_sha256 != sha256_text(prompt):
            reason = "zmieniony pomysł albo prompt"
        if reason is not None:
            jobs.append(
                PageJob(page=page.page, name=page.name, idea_id=page.idea_id, prompt=prompt)
            )
            reasons[page.name] = reason

    # Zapas: pomysły bez strony, w kolejności z ideas.json, bez tych już odrzuconych przez QA.
    used = {p.idea_id for p in manifest.pages}
    rejected = {r.idea_id for p in manifest.pages for r in p.rejected}
    reserve = [
        PagePrompt(idea_id=idea.id, prompt=by_id[idea.id])
        for idea in ideas.pages
        if idea.id not in used and idea.id not in rejected
    ]
    return ImagesPlan(jobs=jobs, reasons=reasons, edited=list(edited.items()), reserve=reserve)


# --- Krok 3: plan obróbki -------------------------------------------------------------


def postprocess_sha256(params_json: str, geometry: PageGeometry) -> str:
    """Suma parametrów obróbki z profilu wieku i geometrii strony (FR-17 krok 3)."""
    return sha256_text(f"{params_json}|{geometry!r}")


def plan_finalize(book_dir: Path, manifest: Manifest, params_sha256: str) -> list[ManifestPage]:
    """Strony z surową grafiką, których gotowa strona jest nieaktualna albo jej brakuje."""
    todo: list[ManifestPage] = []
    for page in manifest.pages:
        if page.status not in ("raw_ok", "ok", "failed") or page.raw_sha256 is None:
            continue
        if not raw_path(book_dir, page).is_file():
            continue
        final = page.final
        png = book_dir / f"{page.name}.png"
        if (
            page.status == "raw_ok"
            or final is None
            or final.raw_sha256 != page.raw_sha256
            or final.postprocess_sha256 != params_sha256
            or (page.status == "ok" and not png.is_file())
        ):
            todo.append(page)
    return todo


# --- FR-14: strona „This book belongs to…” ------------------------------------------------------


def front_raw_path(book_dir: Path, name: str = FRONT_NAME) -> Path:
    return book_dir / RAW_DIR / f"{name}.png"


def plan_front(
    book_dir: Path, front: FrontPage | None, prompt: str, name: str = FRONT_NAME
) -> str | None:
    """Dlaczego `belongs-to` ma (ponownie) wygenerować ramkę FR-14; None, gdy jest aktualna.

    Nieudany napis przy aktualnej surowej grafice (`failed` z `raw_sha256`) to sprawa obróbki,
    nie modelu: nowa grafika by go nie naprawiła.
    """
    if front is None:
        return None
    if front.action == "regenerate":
        return "action: regenerate"
    if front.raw_sha256 is None or not front_raw_path(book_dir, name).is_file():
        return "nieudana" if front.status == "failed" else "brak grafiki"
    if front.layout == "text_only":  # strona 1 z finalize: model jej jeszcze nie rysował
        return "brak grafiki"
    if front.prompt_sha256 != sha256_text(prompt):
        return "zmieniony prompt"
    return None


def fallback_art(book_dir: Path, manifest: Manifest) -> tuple[str, Path] | None:
    """Grafika do układu zapasowego FR-14: pierwsza strona książki z gotową surową grafiką."""
    for page in manifest.pages:
        raw = raw_path(book_dir, page)
        if page.status in ("raw_ok", "ok") and page.raw_sha256 is not None and raw.is_file():
            return page.name, raw
    return None


def front_needs_finalize(
    book_dir: Path, front: FrontPage | None, params_sha256: str, name: str = FRONT_NAME
) -> bool:
    """Strona wstępna ma surową grafikę, a gotowej strony brakuje albo jest nieaktualna."""
    if front is None or front.raw_sha256 is None or front.layout is None:
        return False
    raw_ok = front_raw_path(book_dir, name).is_file()
    if front.status not in ("raw_ok", "ok", "failed") or not raw_ok:
        return False
    final = front.final
    return (
        front.status == "raw_ok"
        or final is None
        or final.raw_sha256 != front.raw_sha256
        or final.postprocess_sha256 != params_sha256
        or (front.status == "ok" and not (book_dir / f"{name}.png").is_file())
    )
