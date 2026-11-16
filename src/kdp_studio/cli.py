"""Interfejs wiersza poleceń (spec §9)."""

from __future__ import annotations

import sys
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from enum import IntEnum
from pathlib import Path
from typing import Annotated, get_args

import typer
from dotenv import load_dotenv

from kdp_studio.config import MAX_CONCURRENCY, AppConfig, ConfigError, ImageQuality, load_config
from kdp_studio.models import BookIdeas, BookSpec
from kdp_studio.pipeline.book import (
    BookError,
    BookLock,
    check_assignment,
    load_ideas,
    never_generated,
    plan_finalize,
    plan_images,
    postprocess_sha256,
    spec_from_manifest,
    sync_order,
    user_edits,
)
from kdp_studio.pipeline.canva import CANVA_FILE, render_canva_md
from kdp_studio.pipeline.diversity import DiversityLimits, diversity_report
from kdp_studio.pipeline.idea_review import IdeaReviewer
from kdp_studio.pipeline.ideas import IdeaGenerator
from kdp_studio.pipeline.manifest import (
    AI_DISCLOSURE,
    FinalInfo,
    ImageProviderInfo,
    ManifestError,
    ManifestIdeas,
    ManifestInput,
    ManifestLayout,
    ManifestProviders,
    ManifestWriter,
    ProviderInfo,
)
from kdp_studio.pipeline.output import (
    IDEAS_FILE,
    PROMPTS_FILE,
    RAW_DIR,
    REJECTED_DIR,
    SVG_DIR,
    book_dir,
    write_bytes_atomic,
    write_json_atomic,
)
from kdp_studio.pipeline.postprocess import (
    PageGeometry,
    PagePostprocessor,
    PostprocessError,
    page_margin_in,
)
from kdp_studio.pipeline.prompts import PromptBuilder
from kdp_studio.pipeline.qa import QAChecker
from kdp_studio.pipeline.worker import PageOutcome, PageWorker, ReservePool, page_jobs
from kdp_studio.profiles import PROFILE_KINDS, ProfileKind, format_profiles
from kdp_studio.providers.base import ImageProvider, ProviderError, TextProvider, VisionProvider
from kdp_studio.providers.registry import (
    create_image_provider,
    create_text_provider,
    create_vision_provider,
)
from kdp_studio.validation import InputValidationError, plural, validate_book_spec


class ExitCode(IntEnum):
    """Kody wyjścia (spec §9.3)."""

    OK = 0
    VALIDATION_ERROR = 1
    PARTIAL = 2
    BUDGET_EXCEEDED = 3
    PROVIDER_ERROR = 4


DEFAULT_FORMAT = "letter"
IMAGE_QUALITIES: tuple[str, ...] = get_args(ImageQuality)

app = typer.Typer(
    name="kdp-studio",
    help="Generator kolorowanek pod Amazon KDP.",
    no_args_is_help=True,
    add_completion=False,
)


@app.callback()
def _root() -> None:
    """Generator kolorowanek pod Amazon KDP."""


def _fail(lines: Sequence[str], code: ExitCode = ExitCode.VALIDATION_ERROR) -> typer.Exit:
    for line in lines:
        typer.echo(f"Błąd: {line}", err=True)
    return typer.Exit(code)


def _warn(lines: Sequence[str]) -> None:
    for line in lines:
        typer.echo(f"Ostrzeżenie: {line}", err=True)


def _fail_lines(lines: Sequence[str]) -> None:
    for line in lines:
        typer.echo(f"Błąd: {line}", err=True)


@contextmanager
def _locked(target: Path) -> Iterator[None]:
    """Blokada katalogu książki na czas kroku (FR-17); zajęty katalog to kod 1."""
    lock = BookLock(target)
    try:
        lock.acquire()
    except BookError as e:
        raise _fail(e.errors) from e
    try:
        yield
    finally:
        lock.release()


# --- Wspólne opcje ----------------------------------------------------------------------

ThemeOpt = Annotated[str | None, typer.Option(help="Tematyka lub roboczy tytuł kolorowanki.")]
AgeOpt = Annotated[str | None, typer.Option(help="Profil wieku z config/ages.yaml.")]
StyleOpt = Annotated[str | None, typer.Option(help="Profil stylu z config/styles.yaml.")]
FormatOpt = Annotated[str, typer.Option("--format", help="Profil formatu z config/formats.yaml.")]
PagesOpt = Annotated[int, typer.Option(help="Liczba grafik (stron kolorowanki), 1–200.")]
StrictOpt = Annotated[
    bool, typer.Option("--strict", help="Za mało stron dla KDP to błąd, nie ostrzeżenie.")
]
OutputDirOpt = Annotated[Path, typer.Option(help="Katalog, w którym powstaje katalog książki.")]
ReviewOpt = Annotated[
    bool | None,
    typer.Option(
        "--review-ideas/--no-review-ideas",
        help="Weryfikacja pomysłów przed grafikami (FR-03a). Domyślnie z settings.yaml.",
    ),
]
ConcurrencyOpt = Annotated[
    int | None,
    typer.Option(
        help=f"Grafiki generowane równolegle, 1–{MAX_CONCURRENCY}. Domyślnie z settings.yaml."
    ),
]
ImageProviderOpt = Annotated[
    str | None, typer.Option(help="Dostawca grafik z rejestru. Domyślnie z settings.yaml.")
]
QualityOpt = Annotated[
    str | None,
    typer.Option(
        "--image-quality",
        help=f"Jakość modelu obrazu: {', '.join(IMAGE_QUALITIES)}. Domyślnie z settings.yaml.",
    ),
]
QaOpt = Annotated[
    bool | None,
    typer.Option(
        "--qa/--no-qa",
        help="Kontrola jakości stron modelem z wizją; odrzucone strony są generowane "
        "ponownie z zapasowych pomysłów (FR-07). Domyślnie z settings.yaml.",
    ),
]
BookArg = Annotated[Path, typer.Argument(help="Katalog książki (z kroku kdp-studio ideas).")]


def _config() -> AppConfig:
    try:
        return load_config()
    except ConfigError as e:
        raise _fail([str(e)]) from e


def _book_spec(
    config: AppConfig,
    theme: str | None,
    age: str | None,
    style: str | None,
    format_: str,
    pages: int,
    strict: bool,
) -> BookSpec:
    try:
        result = validate_book_spec(
            theme=theme,
            age=age,
            style=style,
            format=format_,
            pages=pages,
            strict=strict,
            config=config,
        )
    except InputValidationError as e:
        raise _fail(e.errors) from e
    _warn(result.warnings)
    spec = result.spec
    typer.echo(
        f"Parametry poprawne: '{spec.theme}', wiek {spec.age}, styl {spec.style}, "
        f"format {spec.format}, {plural(spec.pages, 'grafika', 'grafiki', 'grafik')} "
        f"({plural(spec.pages_in_book, 'strona', 'strony', 'stron')} książki)."
    )
    return spec


def _new_book_dir(output_dir: Path, spec: BookSpec) -> Path:
    target = book_dir(output_dir, spec)
    if (target / IDEAS_FILE).exists():
        raise _fail(
            [
                f"{target / IDEAS_FILE} już istnieje. Kontynuuj krokami "
                f"`kdp-studio images {target}` i `kdp-studio finalize {target}` "
                f"(albo `kdp-studio ideas {target} --redo …`), usuń katalog "
                "albo wybierz inny --output-dir"
            ]
        )
    return target


def _workers(config: AppConfig, concurrency: int | None) -> int:
    workers = config.settings.concurrency if concurrency is None else concurrency
    if not 1 <= workers <= MAX_CONCURRENCY:
        raise _fail([f"--concurrency: musi być w zakresie 1–{MAX_CONCURRENCY} (podano {workers})"])
    return workers


def _quality(config: AppConfig, quality: str | None) -> str:
    value = config.settings.image_quality if quality is None else quality
    if value not in IMAGE_QUALITIES:
        raise _fail([f"--image-quality: dozwolone {', '.join(IMAGE_QUALITIES)} (podano '{value}')"])
    return value


def _text_provider(config: AppConfig) -> TextProvider:
    settings = config.settings
    try:
        return create_text_provider(settings.providers.text, settings.models.text)
    except ConfigError as e:
        raise _fail([str(e)]) from e


def _image_providers(
    config: AppConfig, fmt: str, image_provider: str | None, do_qa: bool
) -> tuple[ImageProvider, VisionProvider | None]:
    """Dostawcy kroku 2, tworzeni przed pierwszym wywołaniem API."""
    settings = config.settings
    aspect = config.formats[fmt].aspect
    vision: VisionProvider | None = None
    try:
        images = create_image_provider(
            image_provider or settings.providers.image, settings.models.image
        )
        if do_qa:
            vision = create_vision_provider(settings.providers.vision, settings.models.vision)
    except ConfigError as e:
        raise _fail([str(e)]) from e
    if aspect not in images.supported_aspects():
        raise _fail(
            [
                f"dostawca grafik '{images.name}' nie obsługuje proporcji {aspect} "
                f"formatu {fmt}. Obsługiwane: {', '.join(images.supported_aspects())}"
            ]
        )
    return images, vision


def _open_book(target: Path) -> ManifestWriter:
    try:
        return ManifestWriter.load(target)
    except ManifestError as e:
        raise _fail([str(e)]) from e


def _layout(config: AppConfig, spec: BookSpec) -> tuple[ManifestLayout, PageGeometry]:
    settings = config.settings
    fmt = config.formats[spec.format]
    margin_in = page_margin_in(fmt, settings.kdp_margins, spec.pages_in_book)
    gutter_in = settings.kdp_margins.gutter_in(spec.pages_in_book)
    assert gutter_in is not None  # FR-02 odrzuca książki grubsze niż tabela marginesów
    layout = ManifestLayout(
        trim_in=fmt.trim_in,
        page_px=fmt.page_px,
        dpi=fmt.dpi,
        pages_in_book=spec.pages_in_book,
        gutter_in=gutter_in,
        margin_in=margin_in,
    )
    return layout, PageGeometry.for_format(fmt, margin_in)


# --- Krok 1: pomysły ---------------------------------------------------------------------


def _step_ideas(
    config: AppConfig, spec: BookSpec, target: Path, provider: TextProvider, do_review: bool
) -> BookIdeas:
    """Pomysły, weryfikacja, prompty i manifest ze stronami `pending` (FR-17 krok 1)."""
    settings = config.settings
    typer.echo(f"Generuję pomysły ({provider.name}, {provider.model})…")
    generator = IdeaGenerator(provider, config)
    try:
        ideas_result = generator.generate(spec)
    except ProviderError as e:
        raise _fail([str(e)], ExitCode.PROVIDER_ERROR) from e
    _warn(ideas_result.warnings)
    ideas = ideas_result.ideas
    usage = ideas_result.usage
    typer.echo(
        f"Tytuł: {ideas.book.title}\n"
        f"Pomysły: {len(ideas.pages)}, tokeny: {usage.input_tokens} wejście / "
        f"{usage.output_tokens} wyjście, {plural(ideas_result.attempts, 'próba', 'próby', 'prób')}."
    )

    ideas_usage = usage
    if do_review:
        typer.echo("Weryfikuję pomysły…")
        try:
            reviewed = IdeaReviewer(provider, config).review(spec, ideas, generator)
        except ProviderError as e:
            raise _fail([str(e)], ExitCode.PROVIDER_ERROR) from e
        _warn(reviewed.warnings)
        ideas = reviewed.ideas
        ideas_usage += reviewed.usage
        _report_review(ideas, reviewed.usage.input_tokens, reviewed.usage.output_tokens)
    else:
        # Bez weryfikacji tylko pomiar: rozkład trafia do ideas.json i do ostrzeżeń (FR-03b).
        diversity = diversity_report(
            ideas.pages[: spec.pages],
            DiversityLimits.from_config(spec, config, ideas.theme_anchors),
        )
        ideas = ideas.model_copy(update={"diversity": diversity})
        _warn([f"różnorodność: {issue}" for issue in diversity.issues])
    _report_diversity(ideas)

    write_json_atomic(target / IDEAS_FILE, ideas)
    reserve = len(ideas.pages) - spec.pages
    typer.echo(
        f"Pomysły do książki: {plural(spec.pages, 'strona', 'strony', 'stron')} + "
        f"{plural(reserve, 'zapasowy', 'zapasowe', 'zapasowych')}. "
        f"Zapisano: {target / IDEAS_FILE}"
    )
    prompts = PromptBuilder(spec, config).build(ideas)
    write_json_atomic(target / PROMPTS_FILE, prompts)
    typer.echo(f"Prompty obrazu: {len(prompts.pages)}. Zapisano: {target / PROMPTS_FILE}")

    layout, _ = _layout(config, spec)
    fmt = config.formats[spec.format]
    manifest = ManifestWriter.start(
        target,
        jobs=page_jobs(prompts, spec.pages),
        input=ManifestInput(
            theme=spec.theme,
            age=spec.age,
            style=spec.style,
            format=spec.format,
            pages=spec.pages,
            front_matter_pages=spec.front_matter_pages,
            concurrency=settings.concurrency,
            review_ideas=do_review,
            qa=settings.qa,
        ),
        providers=ManifestProviders(
            text=ProviderInfo(provider=provider.name, model=provider.model),
            image=ImageProviderInfo(
                provider=settings.providers.image,
                model=settings.models.image,
                quality=settings.image_quality,
                aspect=fmt.aspect,
            ),
        ),
        layout=layout,
        ideas=ManifestIdeas(
            count=len(ideas.pages), reserve=reserve, reviewed=do_review, usage=ideas_usage
        ),
    )
    typer.echo(f"Manifest: {manifest.path} (status: {manifest.manifest.status})")
    return ideas


def _step_redo(config: AppConfig, target: Path, ids: list[str], review: bool | None) -> None:
    """`ideas <katalog> --redo`: nowe pomysły w miejsce wskazanych, z tymi samymi id."""
    writer = _open_book(target)
    spec = spec_from_manifest(writer.manifest)
    try:
        ideas = load_ideas(target)
    except BookError as e:
        raise _fail(e.errors) from e
    known = {idea.id for idea in ideas.pages}
    unknown = [i for i in ids if i not in known]
    if unknown:
        raise _fail([f"--redo: nie ma pomysłów {', '.join(unknown)} w {IDEAS_FILE}"])
    do_review = writer.manifest.input.review_ideas if review is None else review
    provider = _text_provider(config)
    typer.echo(
        f"Wymyślam {plural(len(ids), 'nowy pomysł', 'nowe pomysły', 'nowych pomysłów')} "
        f"w miejsce {', '.join(ids)} ({provider.name}, {provider.model})…"
    )
    generator = IdeaGenerator(provider, config)
    try:
        result = IdeaReviewer(provider, config).replace(
            spec, ideas, ids, generator, review=do_review
        )
    except ProviderError as e:
        raise _fail([str(e)], ExitCode.PROVIDER_ERROR) from e
    _warn(result.warnings)
    ideas = result.ideas
    by_id = {idea.id: idea for idea in ideas.pages}
    for idea_id in ids:
        typer.echo(f"  {idea_id}: {by_id[idea_id].title}: {by_id[idea_id].scene}")
    write_json_atomic(target / IDEAS_FILE, ideas)
    prompts = PromptBuilder(spec, config).build(ideas)
    write_json_atomic(target / PROMPTS_FILE, prompts)
    writer.manifest.ideas.usage += result.usage
    writer.save()
    pages = [p for p in writer.manifest.pages if p.idea_id in ids]
    usage = result.usage
    typer.echo(
        f"Zapisano: {target / IDEAS_FILE}, tokeny: {usage.input_tokens} wejście / "
        f"{usage.output_tokens} wyjście."
    )
    redone = [p.name for p in pages if p.raw_sha256 is not None or p.attempts > 0]
    fresh = [p.name for p in pages if p.name not in redone]
    if redone:
        typer.echo(
            f"Strony z nowymi pomysłami ({', '.join(redone)}) zostaną wygenerowane ponownie "
            f"przy `kdp-studio images {target}`."
        )
    if fresh:
        typer.echo(
            f"Nowe pomysły trafią na strony {', '.join(fresh)} przy `kdp-studio images {target}`."
        )


@app.command()
def ideas(
    book: Annotated[
        Path | None,
        typer.Argument(help="Katalog istniejącej książki; tylko z --redo."),
    ] = None,
    theme: ThemeOpt = None,
    age: AgeOpt = None,
    style: StyleOpt = None,
    format_: FormatOpt = DEFAULT_FORMAT,
    pages: PagesOpt = 30,
    strict: StrictOpt = False,
    output_dir: OutputDirOpt = Path("output"),
    review_ideas: ReviewOpt = None,
    redo: Annotated[
        str | None,
        typer.Option(
            help="Id pomysłów do zastąpienia nowymi, po przecinku (np. idea_07,idea_19); "
            "wymaga katalogu książki."
        ),
    ] = None,
) -> None:
    """Krok 1: pomysły, prompty i manifest, bez grafik (FR-17). Tani podgląd książki."""
    config = _config()
    if book is not None:
        if redo is None:
            raise _fail(["z katalogiem książki podaj --redo idea_XX,…"])
        if theme is not None or age is not None or style is not None:
            raise _fail(["--redo działa na istniejącej książce: nie podawaj --theme/--age/--style"])
        ids = [i.strip() for i in redo.split(",") if i.strip()]
        if not ids:
            raise _fail(["--redo: podaj id pomysłów, np. idea_07,idea_19"])
        with _locked(book):
            _step_redo(config, book, list(dict.fromkeys(ids)), review_ideas)
        return
    if redo is not None:
        raise _fail(["--redo wymaga katalogu książki: kdp-studio ideas <katalog> --redo …"])

    spec = _book_spec(config, theme, age, style, format_, pages, strict)
    target = _new_book_dir(output_dir, spec)
    provider = _text_provider(config)
    do_review = config.settings.review_ideas if review_ideas is None else review_ideas
    with _locked(target):
        _step_ideas(config, spec, target, provider, do_review)
    typer.echo(f"Przejrzyj {target / IDEAS_FILE}, a potem: kdp-studio images {target}")


# --- Krok 2: surowe grafiki ----------------------------------------------------------------


def _step_images(
    config: AppConfig,
    target: Path,
    images: ImageProvider,
    vision: VisionProvider | None,
    workers: int,
    quality: str,
) -> ExitCode:
    """Surowe grafiki stron, których brakuje albo które trzeba wygenerować ponownie."""
    settings = config.settings
    writer = _open_book(target)
    manifest = writer.manifest
    spec = spec_from_manifest(manifest)
    try:
        ideas = load_ideas(target)
    except BookError as e:
        raise _fail(e.errors) from e
    if never_generated(manifest):
        sync_order(manifest, ideas)
    errors = check_assignment(manifest, ideas)
    if errors:
        raise _fail(errors)

    prompts = PromptBuilder(spec, config).build(ideas)
    write_json_atomic(target / PROMPTS_FILE, prompts)
    plan = plan_images(target, manifest, ideas, prompts)
    for number, digest in plan.edited:
        writer.mark_edited(number, digest)
        typer.echo(f"{writer.page(number).name}: własna wersja surowej grafiki, zostaje.")

    aspect = config.formats[spec.format].aspect
    manifest.input.concurrency = workers
    manifest.input.qa = vision is not None
    manifest.providers.image = ImageProviderInfo(
        provider=images.name, model=images.model, quality=quality, aspect=aspect
    )
    manifest.providers.vision = (
        None if vision is None else ProviderInfo(provider=vision.name, model=vision.model)
    )
    jobs = plan.jobs
    if not jobs:
        status = writer.update_status()
        typer.echo(f"Surowe grafiki są aktualne, nic do zrobienia (status: {status}).")
        return ExitCode.OK

    for job in jobs:  # nieaktualne gotowe strony nie mogą trafić do Canvy
        (target / f"{job.name}.png").unlink(missing_ok=True)
        (target / SVG_DIR / f"{job.name}.svg").unlink(missing_ok=True)
    reasons: dict[str, int] = {}
    for reason in plan.reasons.values():
        reasons[reason] = reasons.get(reason, 0) + 1
    typer.echo(
        f"Generuję {plural(len(jobs), 'grafikę', 'grafiki', 'grafik')} ({images.name}, "
        f"{images.model}, jakość {quality}, równolegle {workers}): "
        + ", ".join(f"{reason} {count}" for reason, count in reasons.items())
        + "…"
    )
    pool = ReservePool(plan.reserve)
    checker = preview = None
    if vision is not None:
        checker = QAChecker(vision, spec, config, ideas)
        _, geometry = _layout(config, spec)
        preview = PagePostprocessor(
            book_dir=target, geometry=geometry, params=config.ages[spec.age].postprocess
        )
        typer.echo(
            f"Kontrola jakości: {vision.name}, {vision.model}; najwyżej "
            f"{plural(settings.qa_max_retries, 'ponowienie', 'ponowienia', 'ponowień')} "
            f"na stronę, zapasowe pomysły: {pool.remaining}."
        )
    done = 0

    def report(outcome: PageOutcome) -> None:
        nonlocal done
        done += 1
        if outcome.status == "ok":
            line = f"{outcome.name}: ok ({outcome.duration_s:.1f} s)"
            if outcome.rejected:
                line += (
                    f", {plural(outcome.attempts, 'próba', 'próby', 'prób')}, "
                    f"użyto {outcome.idea_id}"
                )
        else:
            line = f"{outcome.name}: nieudana: {outcome.error}"
        typer.echo(f"[{done}/{len(jobs)}] {line}")
        for rejected in outcome.rejected:
            issues = "; ".join(f"{i.criterion}: {i.detail}" for i in rejected.issues)
            typer.echo(f"  QA odrzuciło próbę {rejected.attempt} ({rejected.idea_id}): {issues}")
        writer.record_raw(outcome, provider=images.name, model=images.model, quality=quality)

    worker = PageWorker(
        provider=images,
        book_dir=target,
        aspect=aspect,
        quality=quality,
        concurrency=workers,
        qa=checker,
        preview=preview,
        reserve=pool,
        max_retries=settings.qa_max_retries,
    )
    result = worker.run(jobs, on_done=report)
    usage = result.usage
    typer.echo(
        f"Surowe grafiki: {len(result.ok)}/{len(jobs)} ok, tokeny: "
        f"{usage.input_tokens} wejście / {usage.output_tokens} wyjście. "
        f"Zapisano: {target / RAW_DIR}"
    )
    if checker is not None:
        qa_usage = result.qa_usage
        typer.echo(
            f"QA: odrzucono {plural(result.rejected, 'grafikę', 'grafiki', 'grafik')} "
            f"(w {target / REJECTED_DIR}), "
            f"zapasowe pomysły: użyto {pool.used}/{pool.used + pool.remaining}, "
            f"tokeny: {qa_usage.input_tokens} wejście / {qa_usage.output_tokens} wyjście."
        )
    status = writer.update_status(result.fatal_error)
    typer.echo(f"Manifest: {writer.path} (status: {status})")
    if result.fatal_error is not None:
        _fail_lines([result.fatal_error, f"po usunięciu przyczyny: kdp-studio images {target}"])
        return ExitCode.PROVIDER_ERROR
    if result.failed:
        failed = ", ".join(o.name for o in result.failed)
        _warn([f"nieudane strony: {failed}; ponów: kdp-studio images {target}"])
        return ExitCode.PARTIAL
    return ExitCode.OK


@app.command()
def images(
    book: BookArg,
    concurrency: ConcurrencyOpt = None,
    image_provider: ImageProviderOpt = None,
    image_quality: QualityOpt = None,
    qa: QaOpt = None,
) -> None:
    """Krok 2: surowe grafiki stron, których brakuje albo trzeba je odnowić (FR-17)."""
    config = _config()
    workers = _workers(config, concurrency)
    quality = _quality(config, image_quality)
    writer = _open_book(book)
    do_qa = config.settings.qa if qa is None else qa
    providers = _image_providers(config, writer.manifest.input.format, image_provider, do_qa)
    with _locked(book):
        code = _step_images(config, book, *providers, workers, quality)
    if code == ExitCode.OK and _open_book(book).manifest.status != "completed":
        typer.echo(f"Przejrzyj {book / RAW_DIR}, a potem: kdp-studio finalize {book}")
    raise typer.Exit(code)


# --- Krok 3: gotowe strony -------------------------------------------------------------------


def _step_finalize(config: AppConfig, target: Path) -> ExitCode:
    """Gotowe strony do Canvy z aktualnych surowych grafik, canva.md (FR-17 krok 3)."""
    writer = _open_book(target)
    manifest = writer.manifest
    if manifest.status == "ideas_ready" or never_generated(manifest):
        raise _fail([f"brak surowych grafik: najpierw kdp-studio images {target}"])
    try:
        ideas = load_ideas(target)
    except BookError as e:
        raise _fail(e.errors) from e
    for number, digest in user_edits(target, manifest):
        writer.mark_edited(number, digest)
        typer.echo(f"{writer.page(number).name}: własna wersja surowej grafiki.")

    spec = spec_from_manifest(manifest)
    layout, geometry = _layout(config, spec)
    manifest.layout = layout
    params = config.ages[spec.age].postprocess
    params_sha = postprocess_sha256(params.model_dump_json(), geometry)
    todo = plan_finalize(target, manifest, params_sha)
    typer.echo(
        f"Strona {layout.page_px[0]}×{layout.page_px[1]} px ({layout.dpi} DPI), margines "
        f'{layout.margin_in:g}" z każdej strony (grzbiet KDP dla {layout.pages_in_book} '
        f'stron: {layout.gutter_in:g}").'
    )
    postprocessor = PagePostprocessor(book_dir=target, geometry=geometry, params=params)
    if todo:
        typer.echo(f"Obrabiam {plural(len(todo), 'stronę', 'strony', 'stron')}…")
    for i, page in enumerate(todo, start=1):
        assert page.raw_sha256 is not None
        final = FinalInfo(raw_sha256=page.raw_sha256, postprocess_sha256=params_sha)
        try:
            files = postprocessor.process(target / RAW_DIR / f"{page.name}.png", page.name)
        except PostprocessError as e:
            writer.record_final(page.page, png=None, svg=None, final=final, error=f"obróbka: {e}")
            typer.echo(f"[{i}/{len(todo)}] {page.name}: nieudana: obróbka: {e}")
            continue
        writer.record_final(page.page, png=files.page, svg=files.svg, final=final, error=None)
        typer.echo(f"[{i}/{len(todo)}] {page.name}: ok")
    if not todo:
        typer.echo("Gotowe strony są aktualne, nic do obróbki.")

    status = writer.update_status()
    ok = len(manifest.ok_pages)
    typer.echo(
        f"Gotowe strony: {ok}/{len(manifest.pages)}. Do Canvy: {target}/page_*.png "
        f"(wektory: {target / SVG_DIR}, surowe: {target / RAW_DIR})"
    )
    typer.echo(f"Manifest: {writer.path} (status: {status})")
    canva = target / CANVA_FILE
    write_bytes_atomic(canva, render_canva_md(manifest, ideas.book.title).encode("utf-8"))
    typer.echo(f"Instrukcja składania w Canvie: {canva}")
    typer.echo(f"Pamiętaj: {AI_DISCLOSURE}")
    missing = [p.name for p in manifest.pages if p.status != "ok"]
    if missing:
        _warn([f"brakujące strony: {', '.join(missing)}; ponów: kdp-studio images {target}"])
        return ExitCode.PARTIAL
    return ExitCode.OK


@app.command()
def finalize(book: BookArg) -> None:
    """Krok 3: gotowe strony do Canvy, wektory i canva.md, bez wywołań API (FR-17)."""
    config = _config()
    with _locked(book):
        code = _step_finalize(config, book)
    raise typer.Exit(code)


# --- Wszystkie kroki -----------------------------------------------------------------------


@app.command()
def generate(
    theme: ThemeOpt = None,
    age: AgeOpt = None,
    style: StyleOpt = None,
    format_: FormatOpt = DEFAULT_FORMAT,
    pages: PagesOpt = 30,
    strict: StrictOpt = False,
    output_dir: OutputDirOpt = Path("output"),
    concurrency: ConcurrencyOpt = None,
    image_provider: ImageProviderOpt = None,
    image_quality: QualityOpt = None,
    review_ideas: ReviewOpt = None,
    qa: QaOpt = None,
) -> None:
    """Generuje kolorowankę: kroki ideas, images i finalize po kolei (FR-17)."""
    config = _config()
    spec = _book_spec(config, theme, age, style, format_, pages, strict)
    workers = _workers(config, concurrency)
    quality = _quality(config, image_quality)
    target = _new_book_dir(output_dir, spec)
    do_qa = config.settings.qa if qa is None else qa
    do_review = config.settings.review_ideas if review_ideas is None else review_ideas
    # Wszyscy dostawcy przed pierwszym wywołaniem API: zły klucz albo proporcja wychodzą od razu.
    provider = _text_provider(config)
    images_provider, vision = _image_providers(config, spec.format, image_provider, do_qa)

    with _locked(target):
        _step_ideas(config, spec, target, provider, do_review)
        code = _step_images(config, target, images_provider, vision, workers, quality)
        if code == ExitCode.PROVIDER_ERROR:
            raise typer.Exit(code)
        final_code = _step_finalize(config, target)
    raise typer.Exit(max(code, final_code))


def _counts(values: dict[str, int], suffix: str = " ") -> str:
    return ", ".join(f"{value}{suffix}{count}" for value, count in values.items()) or "-"


def _report_diversity(ideas: BookIdeas) -> None:
    report = ideas.diversity
    if report is None:
        return
    fixes = ""
    if report.moved_from_reserve or report.revised:
        fixes = (
            f" Wyrównanie: zamieniono z zapasem {report.moved_from_reserve}, "
            f"poprawiono {report.revised}."
        )
    typer.echo(
        f"Różnorodność ({plural(report.pages, 'strona', 'strony', 'stron')}): "
        f"postacie {_counts(report.characters, '×')}; "
        f"czynności {_counts(report.actions)}; miejsca {_counts(report.settings)}; "
        f"przedmioty {_counts(report.elements)}.{fixes}"
    )
    if ideas.theme_anchors:
        typer.echo(f"  motywy tematu bez limitu: {', '.join(ideas.theme_anchors)}")


def _report_review(ideas: BookIdeas, input_tokens: int, output_tokens: int) -> None:
    review = ideas.review
    if review is None:
        return
    typer.echo(
        f"Weryfikacja: odrzucono {len(review.rejected)}, poprawiono {len(review.revised)}, "
        f"dogenerowano {review.added} ({plural(review.rounds, 'runda', 'rundy', 'rund')}), "
        f"tokeny: {input_tokens} wejście / {output_tokens} wyjście."
    )
    for rejected in review.rejected:
        typer.echo(f"  odrzucony: {rejected.title} ({rejected.reason})")
    for revised in review.revised:
        typer.echo(f"  poprawiony: {revised.original_title} → {revised.id} ({revised.reason})")


@app.command()
def profiles(
    kind: Annotated[
        str | None,
        typer.Argument(help="Rodzaj profili: age, style albo format. Domyślnie wszystkie."),
    ] = None,
) -> None:
    """Wypisuje dostępne profile wieku, stylu i formatu z opisami (FR-12)."""
    if kind is not None and kind not in PROFILE_KINDS:
        raise _fail([f"nieznany rodzaj profili '{kind}'. Dozwolone: {', '.join(PROFILE_KINDS)}"])
    try:
        config = load_config()
    except ConfigError as e:
        raise _fail([str(e)]) from e

    kinds: tuple[ProfileKind, ...] = PROFILE_KINDS if kind is None else (kind,)
    for line in format_profiles(config, kinds, default_format=DEFAULT_FORMAT):
        typer.echo(line)


def main(argv: Sequence[str] | None = None) -> int:
    """Uruchamia CLI i zwraca kod wyjścia.

    Typer domyślnie kończy błędy użycia (zły typ, nieznana opcja) kodem 2,
    który w spec §9.3 oznacza częściowy wynik. Tu mapujemy je na 1.
    """
    args = list(sys.argv[1:] if argv is None else argv) or ["--help"]
    try:
        result = app(args=args, prog_name="kdp-studio", standalone_mode=False)
    except typer.TyperException as e:
        show = getattr(e, "show", None)
        if callable(show):
            show()
        else:
            typer.echo(f"Error: {e.format_message()}", err=True)
        return ExitCode.VALIDATION_ERROR
    except typer.Abort:
        typer.echo("Przerwano.", err=True)
        return 130  # konwencja dla SIGINT
    return result if isinstance(result, int) else ExitCode.OK


def run() -> None:
    load_dotenv()  # sekrety z .env (spec §9.2); zmienne środowiskowe mają pierwszeństwo
    sys.exit(main())
