"""Interfejs wiersza poleceń (spec §9)."""

from __future__ import annotations

import logging
import sys
import time
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from enum import IntEnum
from pathlib import Path
from typing import Annotated, get_args

import typer
from dotenv import load_dotenv

from kdp_studio.config import (
    MAX_CONCURRENCY,
    AppConfig,
    ConfigError,
    ImageQuality,
    LogLevel,
    load_config,
)
from kdp_studio.models import BookIdeas, BookSpec
from kdp_studio.observability import (
    LOG_LEVELS,
    LoggedImageProvider,
    LoggedTextProvider,
    LoggedVisionProvider,
    StepTimer,
    book_log,
    format_duration,
    log_event,
    progress_bar,
)
from kdp_studio.pipeline.belongs_to import (
    FRONT_NAME,
    BelongsToMaker,
    BelongsToOutcome,
    BelongsToRenderer,
    belongs_to_prompt,
)
from kdp_studio.pipeline.book import (
    BookError,
    BookLock,
    check_assignment,
    fallback_art,
    front_needs_finalize,
    front_raw_path,
    load_ideas,
    never_generated,
    plan_finalize,
    plan_front,
    plan_images,
    postprocess_sha256,
    spec_from_manifest,
    sync_order,
    user_edits,
)
from kdp_studio.pipeline.canva import CANVA_FILE, render_canva_md
from kdp_studio.pipeline.cost import CostTracker, format_usd, missing_prices
from kdp_studio.pipeline.diversity import DiversityLimits, diversity_report
from kdp_studio.pipeline.idea_review import IdeaReviewer
from kdp_studio.pipeline.ideas import IdeaGenerator
from kdp_studio.pipeline.manifest import (
    AI_DISCLOSURE,
    FinalInfo,
    FrontPage,
    ImageProviderInfo,
    ManifestError,
    ManifestIdeas,
    ManifestInput,
    ManifestLayout,
    ManifestPage,
    ManifestProviders,
    ManifestWriter,
    ProviderInfo,
    sha256_bytes,
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
from kdp_studio.pipeline.worker import (
    ImagesResult,
    PageOutcome,
    PageWorker,
    ReservePool,
    page_jobs,
)
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
STEP_LABELS = {
    "ideas": "pomysły",
    "redo": "nowe pomysły",
    "images": "grafiki",
    "finalize": "obróbka",
}
COST_LABELS = {"ideas": "pomysły", "images": "grafiki", "qa": "QA"}

_log = logging.getLogger("kdp_studio.cli")

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
    _fail_lines(lines)
    return typer.Exit(code)


def _warn(lines: Sequence[str]) -> None:
    for line in lines:
        typer.echo(f"Ostrzeżenie: {line}", err=True)
        log_event(_log, logging.WARNING, "warning", message=line)


def _fail_lines(lines: Sequence[str]) -> None:
    for line in lines:
        typer.echo(f"Błąd: {line}", err=True)
        log_event(_log, logging.ERROR, "error", message=line)


@contextmanager
def _locked(target: Path, log_level: LogLevel) -> Iterator[None]:
    """Blokada katalogu książki na czas kroku (FR-17); zajęty katalog to kod 1.

    Na ten sam czas logi trafiają do `kdp-studio.log` w katalogu książki (NFR-09).
    """
    lock = BookLock(target)
    try:
        lock.acquire()
    except BookError as e:
        raise _fail(e.errors) from e
    try:
        with book_log(target, log_level):
            yield
    finally:
        lock.release()


@contextmanager
def _timed(timer: StepTimer, step: str, costs: CostTracker | None = None) -> Iterator[None]:
    """Krok z pomiarem czasu: zdarzenia step_start/step_end w logu, czas i koszt w konsoli."""
    spent = 0.0 if costs is None else costs.spent
    with timer.step(step, _log):
        yield
    line = f"Czas kroku ({STEP_LABELS[step]}): {format_duration(timer.steps[-1][1])}"
    if costs is not None:
        line += f", koszt {format_usd(costs.spent - spent)}"
    typer.echo(f"{line}.")


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
BelongsToOpt = Annotated[
    bool | None,
    typer.Option(
        "--belongs-to-page/--no-belongs-to-page",
        help="Strona „This book belongs to…” w motywie książki (FR-14): ramka z modelu obrazu, "
        "napis wpisuje program. Domyślnie z settings.yaml (ideas, generate) albo z manifestu "
        "(images).",
    ),
]
MaxCostOpt = Annotated[
    float | None,
    typer.Option(
        help="Limit kosztu API tego uruchomienia w USD (FR-10); po przekroczeniu nowe grafiki "
        "nie startują, a program kończy się kodem 3. Domyślnie z settings.yaml.",
    ),
]
LogLevelOpt = Annotated[
    str | None,
    typer.Option(
        help=f"Poziom logu kdp-studio.log w katalogu książki: {', '.join(LOG_LEVELS)} "
        "(debug zapisuje też każde wywołanie API). Domyślnie z settings.yaml.",
    ),
]


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


def _log_level(config: AppConfig, level: str | None) -> LogLevel:
    value = config.settings.log_level if level is None else level
    if value == "debug":
        return "debug"
    if value == "info":
        return "info"
    raise _fail([f"--log-level: dozwolone {', '.join(LOG_LEVELS)} (podano '{value}')"])


def _belongs(config: AppConfig, flag: bool | None) -> bool:
    """Przełącznik FR-14 z flagą albo z settings.yaml; włączony wymaga czcionki."""
    belongs = config.settings.belongs_to_page.enabled if flag is None else flag
    if belongs:
        _check_font(config)
    return belongs


def _check_font(config: AppConfig) -> None:
    """FR-14: czcionka napisu musi istnieć, zanim program wyda pieniądze na grafiki."""
    settings = config.settings.belongs_to_page
    if not settings.font_path.is_file():
        raise _fail([f"brak czcionki {settings.font_path} (belongs_to_page.font w settings.yaml)"])


def _new_front(
    config: AppConfig, spec: BookSpec, ideas: BookIdeas, provider: str, model: str
) -> FrontPage:
    prompt, elements = belongs_to_prompt(spec, config, ideas)
    return FrontPage(provider=provider, model=model, prompt=prompt, elements=elements)


def _cost_tracker(config: AppConfig, max_cost: float | None, models: list[str]) -> CostTracker:
    """Limit budżetu (FR-10); model bez ceny w cenniku to błąd przed pierwszym wywołaniem API."""
    settings = config.settings
    limit = settings.max_cost_usd if max_cost is None else max_cost
    if limit <= 0:
        raise _fail([f"--max-cost: musi być większy od 0 (podano {limit:g})"])
    missing = missing_prices(settings.api_pricing, models)
    if missing:
        raise _fail(
            [
                f"brak ceny modelu {', '.join(missing)} w config/settings.yaml "
                "(api_pricing.models): bez niej program nie pilnuje limitu kosztu (FR-10)"
            ]
        )
    return CostTracker(settings.api_pricing, limit)


def _text_provider(config: AppConfig) -> TextProvider:
    settings = config.settings
    try:
        provider = create_text_provider(settings.providers.text, settings.models.text)
    except ConfigError as e:
        raise _fail([str(e)]) from e
    return LoggedTextProvider(provider, config.settings.api_pricing.models.get(provider.model))


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
    prices = settings.api_pricing.models
    logged = LoggedImageProvider(images, prices.get(images.model))
    return logged, None if vision is None else LoggedVisionProvider(
        vision, prices.get(vision.model)
    )


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
    config: AppConfig,
    spec: BookSpec,
    target: Path,
    provider: TextProvider,
    do_review: bool,
    costs: CostTracker,
    belongs: bool = False,
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
    log_event(
        _log,
        logging.INFO,
        "ideas_generated",
        title=ideas.book.title,
        count=len(ideas.pages),
        attempts=ideas_result.attempts,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
    )
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
        if ideas.review is not None:
            log_event(
                _log,
                logging.INFO,
                "ideas_reviewed",
                rejected=len(ideas.review.rejected),
                revised=len(ideas.review.revised),
                added=ideas.review.added,
                rounds=ideas.review.rounds,
                input_tokens=reviewed.usage.input_tokens,
                output_tokens=reviewed.usage.output_tokens,
            )
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

    cost = costs.add("ideas", provider.model, ideas_usage)
    typer.echo(f"Koszt pomysłów: {format_usd(cost)}.")
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
            count=len(ideas.pages),
            reserve=reserve,
            reviewed=do_review,
            usage=ideas_usage,
            cost_usd=cost,
        ),
    )
    if belongs:
        front = _new_front(config, spec, ideas, settings.providers.image, settings.models.image)
        manifest.set_front(front)
        typer.echo(
            f"Strona „This book belongs to…”: prompt ramki w manifeście (elementy motywu: "
            f"{', '.join(front.elements) or '-'})."
        )
    typer.echo(f"Manifest: {manifest.path} (status: {manifest.manifest.status})")
    log_event(
        _log,
        logging.INFO,
        "ideas_saved",
        pages=spec.pages,
        reserve=reserve,
        cost_usd=cost,
        diversity_issues=[] if ideas.diversity is None else ideas.diversity.issues,
    )
    return ideas


def _step_redo(
    config: AppConfig,
    target: Path,
    ids: list[str],
    review: bool | None,
    provider: TextProvider,
    costs: CostTracker,
) -> None:
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
    cost = costs.add("ideas", provider.model, result.usage)
    writer.add_ideas_cost(result.usage, cost)
    log_event(
        _log,
        logging.INFO,
        "ideas_redone",
        ids=ids,
        input_tokens=result.usage.input_tokens,
        output_tokens=result.usage.output_tokens,
        cost_usd=cost,
    )
    pages = [p for p in writer.manifest.pages if p.idea_id in ids]
    usage = result.usage
    typer.echo(
        f"Zapisano: {target / IDEAS_FILE}, tokeny: {usage.input_tokens} wejście / "
        f"{usage.output_tokens} wyjście, koszt {format_usd(cost)}."
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
    belongs_to_page: BelongsToOpt = None,
    max_cost: MaxCostOpt = None,
    log_level: LogLevelOpt = None,
) -> None:
    """Krok 1: pomysły, prompty i manifest, bez grafik (FR-17). Tani podgląd książki."""
    config = _config()
    level = _log_level(config, log_level)
    timer = StepTimer()
    if book is not None:
        if redo is None:
            raise _fail(["z katalogiem książki podaj --redo idea_XX,…"])
        if theme is not None or age is not None or style is not None:
            raise _fail(["--redo działa na istniejącej książce: nie podawaj --theme/--age/--style"])
        if belongs_to_page is not None:
            raise _fail(["--belongs-to-page dla istniejącej książki: kdp-studio images <katalog>"])
        ids = [i.strip() for i in redo.split(",") if i.strip()]
        if not ids:
            raise _fail(["--redo: podaj id pomysłów, np. idea_07,idea_19"])
        provider = _text_provider(config)
        costs = _cost_tracker(config, max_cost, [provider.model])
        with _locked(book, level), _timed(timer, "redo", costs):
            _step_redo(config, book, list(dict.fromkeys(ids)), review_ideas, provider, costs)
        return
    if redo is not None:
        raise _fail(["--redo wymaga katalogu książki: kdp-studio ideas <katalog> --redo …"])

    spec = _book_spec(config, theme, age, style, format_, pages, strict)
    target = _new_book_dir(output_dir, spec)
    provider = _text_provider(config)
    costs = _cost_tracker(config, max_cost, [provider.model])
    do_review = config.settings.review_ideas if review_ideas is None else review_ideas
    belongs = _belongs(config, belongs_to_page)
    with _locked(target, level), _timed(timer, "ideas", costs):
        _step_ideas(config, spec, target, provider, do_review, costs, belongs)
    typer.echo(f"Przejrzyj {target / IDEAS_FILE}, a potem: kdp-studio images {target}")


# --- Krok 2: surowe grafiki ----------------------------------------------------------------


def _step_images(
    config: AppConfig,
    target: Path,
    images: ImageProvider,
    vision: VisionProvider | None,
    workers: int,
    quality: str,
    costs: CostTracker,
    belongs: bool | None = None,
) -> ExitCode:
    """Surowe grafiki stron, których brakuje albo które trzeba wygenerować ponownie.

    Po stronach powstaje strona „This book belongs to…” (FR-14), jeśli książka ją ma:
    układ zapasowy potrzebuje gotowej grafiki strony książki.
    """
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
        log_event(_log, logging.INFO, "user_edit", page=number)

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
    front_prompt, front_reason = _sync_front(config, spec, writer, ideas, target, images, belongs)
    if not jobs and front_reason is None:
        status = writer.update_status()
        typer.echo(f"Surowe grafiki są aktualne, nic do zrobienia (status: {status}).")
        return ExitCode.OK

    for job in jobs:  # nieaktualne gotowe strony nie mogą trafić do Canvy
        (target / f"{job.name}.png").unlink(missing_ok=True)
        (target / SVG_DIR / f"{job.name}.svg").unlink(missing_ok=True)
    reasons: dict[str, int] = {}
    for reason in plan.reasons.values():
        reasons[reason] = reasons.get(reason, 0) + 1
    log_event(
        _log,
        logging.INFO,
        "images_plan",
        pages=[job.name for job in jobs],
        reasons=reasons,
        quality=quality,
        concurrency=workers,
        qa=vision is not None,
    )
    if jobs:
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
    typer.echo(f"Limit kosztu: {format_usd(costs.limit_usd)} (wydano {format_usd(costs.spent)}).")

    def spend(outcome: PageOutcome) -> None:
        """W wątku workera, przed następną stroną: koszt liczy się do limitu od razu."""
        costs.add("images", images.model, outcome.usage)
        if vision is not None:
            costs.add("qa", vision.model, outcome.qa_usage)

    def report(outcome: PageOutcome, advance: Callable[[], None]) -> None:
        nonlocal done
        done += 1
        cost = costs.cost(images.model, outcome.usage)
        if vision is not None:
            cost += costs.cost(vision.model, outcome.qa_usage)
        log_event(
            _log,
            logging.INFO,
            "page_raw",
            page=outcome.page,
            name=outcome.name,
            idea_id=outcome.idea_id,
            status=outcome.status,
            duration_s=round(outcome.duration_s, 2),
            attempts=outcome.attempts,
            error=outcome.error,
            input_tokens=outcome.usage.input_tokens,
            output_tokens=outcome.usage.output_tokens,
            cost_usd=round(cost, 6),
        )
        for rejected in outcome.rejected:
            log_event(
                _log,
                logging.INFO,
                "qa_rejected",
                page=outcome.page,
                attempt=rejected.attempt,
                idea_id=rejected.idea_id,
                issues=[f"{i.criterion}: {i.detail}" for i in rejected.issues],
            )
        if outcome.status == "ok":
            line = f"{outcome.name}: ok ({outcome.duration_s:.1f} s)"
            if outcome.rejected:
                line += (
                    f", {plural(outcome.attempts, 'próba', 'próby', 'prób')}, "
                    f"użyto {outcome.idea_id}"
                )
        else:
            line = f"{outcome.name}: nieudana: {outcome.error}"
        typer.echo(f"[{done}/{len(jobs)}] {line}, {format_usd(cost)}")
        for rejected in outcome.rejected:
            issues = "; ".join(f"{i.criterion}: {i.detail}" for i in rejected.issues)
            typer.echo(f"  QA odrzuciło próbę {rejected.attempt} ({rejected.idea_id}): {issues}")
        writer.record_raw(
            outcome, provider=images.name, model=images.model, quality=quality, cost_usd=cost
        )
        advance()

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
        over_budget=costs.over_budget,
        on_spent=spend,
    )
    result = ImagesResult(outcomes=[])
    if jobs:
        with progress_bar("Grafiki", len(jobs)) as advance:
            result = worker.run(jobs, on_done=lambda outcome: report(outcome, advance))
    usage = result.usage
    front_budget = False
    front_failed = False
    fatal_error = result.fatal_error
    if front_reason is not None and fatal_error is None and not result.budget_exceeded:
        if costs.over_budget():
            front_budget = True
        else:
            try:
                front_ok = _step_front(
                    config,
                    spec,
                    writer,
                    target,
                    images,
                    quality,
                    costs,
                    checker,
                    front_prompt,
                    front_reason,
                )
                front_failed = not front_ok
            except ProviderError as e:
                fatal_error = str(e)
    if jobs:
        typer.echo(
            f"Surowe grafiki: {len(result.ok)}/{len(jobs)} ok, tokeny: "
            f"{usage.input_tokens} wejście / {usage.output_tokens} wyjście, "
            f"koszt {format_usd(costs.by_kind.get('images', 0.0))}. Zapisano: {target / RAW_DIR}"
        )
    if checker is not None:
        qa_usage = result.qa_usage
        typer.echo(
            f"QA: odrzucono {plural(result.rejected, 'grafikę', 'grafiki', 'grafik')} "
            f"(w {target / REJECTED_DIR}), "
            f"zapasowe pomysły: użyto {pool.used}/{pool.used + pool.remaining}, "
            f"tokeny: {qa_usage.input_tokens} wejście / {qa_usage.output_tokens} wyjście, "
            f"koszt {format_usd(costs.by_kind.get('qa', 0.0))}."
        )
    skipped = len(jobs) - len(result.outcomes) + int(front_budget)
    budget_error = None
    if result.budget_exceeded or front_budget:
        budget_error = (
            f"przekroczony limit kosztu {format_usd(costs.limit_usd)} (wydano "
            f"{format_usd(costs.spent)}), pominięto "
            f"{plural(skipped, 'stronę', 'strony', 'stron')}"
        )
    status = writer.update_status(fatal_error, budget_error=budget_error)
    typer.echo(f"Manifest: {writer.path} (status: {status})")
    log_event(
        _log,
        logging.INFO,
        "images_done",
        ok=len(result.ok),
        failed=len(result.failed),
        rejected=result.rejected,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        qa_input_tokens=result.qa_usage.input_tokens,
        qa_output_tokens=result.qa_usage.output_tokens,
        status=status,
        fatal_error=fatal_error,
        budget_exceeded=budget_error is not None,
        skipped=skipped,
        cost_usd=costs.spent,
        book_cost_usd=manifest.cost_usd,
    )
    if fatal_error is not None:
        _fail_lines([fatal_error, f"po usunięciu przyczyny: kdp-studio images {target}"])
        return ExitCode.PROVIDER_ERROR
    if budget_error is not None:
        _fail_lines(
            [
                budget_error,
                f"dokończ z wyższym limitem: kdp-studio images {target} --max-cost …",
            ]
        )
        return ExitCode.BUDGET_EXCEEDED
    if result.failed or front_failed:
        failed = ", ".join([FRONT_NAME] * front_failed + [o.name for o in result.failed])
        _warn([f"nieudane strony: {failed}; ponów: kdp-studio images {target}"])
        return ExitCode.PARTIAL
    return ExitCode.OK


def _sync_front(
    config: AppConfig,
    spec: BookSpec,
    writer: ManifestWriter,
    ideas: BookIdeas,
    target: Path,
    images: ImageProvider,
    belongs: bool | None,
) -> tuple[str, str | None]:
    """Wpis strony FR-14 zgodny z przełącznikiem; (prompt ramki, powód generowania albo None)."""
    prompt, elements = belongs_to_prompt(spec, config, ideas)
    front = writer.front
    if belongs is False and front is not None:
        writer.set_front(None)
        for path in (target / f"{FRONT_NAME}.png", target / SVG_DIR / f"{FRONT_NAME}.svg"):
            path.unlink(missing_ok=True)
        typer.echo(f"Bez strony „This book belongs to…”: usunięto {FRONT_NAME}.png z książki.")
        return prompt, None
    if belongs is True and front is None:
        front = _new_front(config, spec, ideas, images.name, images.model)
        writer.set_front(front)
    if front is None:
        return prompt, None
    front.elements = elements
    return prompt, plan_front(target, front, prompt)


def _step_front(
    config: AppConfig,
    spec: BookSpec,
    writer: ManifestWriter,
    target: Path,
    images: ImageProvider,
    quality: str,
    costs: CostTracker,
    checker: QAChecker | None,
    prompt: str,
    reason: str,
) -> bool:
    """Strona „This book belongs to…” w kroku 2 (FR-14); False, gdy się nie udała.

    ProviderError z fatal=True przechodzi wyżej (kod 4).
    """
    front = writer.front
    assert front is not None
    for path in (target / f"{FRONT_NAME}.png", target / SVG_DIR / f"{FRONT_NAME}.svg"):
        path.unlink(missing_ok=True)  # nieaktualna strona nie może trafić do Canvy
    front_raw_path(target).unlink(missing_ok=True)
    typer.echo(f"Strona „This book belongs to…” ({reason}): ramka z motywem książki…")
    maker = BelongsToMaker(
        provider=images,
        book_dir=target,
        aspect=config.formats[spec.format].aspect,
        quality=quality,
        renderer=_front_renderer(config, spec, target),
        elements=front.elements,
        qa=checker,
        over_budget=costs.over_budget,
    )
    outcome = maker.make(prompt, fallback_art(target, writer.manifest))
    cost = costs.add("images", images.model, outcome.usage)
    if checker is not None:
        cost += costs.add("qa", checker.vision.model, outcome.qa_usage)
    writer.record_front_raw(
        outcome, provider=images.name, model=images.model, quality=quality, cost_usd=cost
    )
    _report_front(outcome, cost)
    return outcome.status == "ok"


def _report_front(outcome: BelongsToOutcome, cost: float) -> None:
    for rejected in outcome.rejected:
        issues = "; ".join(f"{i.criterion}: {i.detail}" for i in rejected.issues)
        typer.echo(f"  odrzucona próba {rejected.attempt}: {issues}")
    tries = plural(outcome.attempts, "próba", "próby", "prób")
    if outcome.status == "failed":
        line = f"nieudana: {outcome.error}"
    elif outcome.layout == "frame":
        line = f"ok, ramka ({tries}, {outcome.duration_s:.1f} s)"
    else:
        line = (
            f"ok, układ zapasowy: grafika {outcome.fallback_source} i napis pod nią "
            f"({tries} bez pustego pola na imię)"
        )
    typer.echo(f"{FRONT_NAME}: {line}, {format_usd(cost)}")
    log_event(
        _log,
        logging.INFO,
        "front_raw",
        name=FRONT_NAME,
        status=outcome.status,
        layout=outcome.layout,
        fallback_source=outcome.fallback_source,
        attempts=outcome.attempts,
        duration_s=round(outcome.duration_s, 2),
        error=outcome.error,
        rejected=[
            {"attempt": r.attempt, "issues": [f"{i.criterion}: {i.detail}" for i in r.issues]}
            for r in outcome.rejected
        ],
        cost_usd=round(cost, 6),
    )


def _front_renderer(config: AppConfig, spec: BookSpec, target: Path) -> BelongsToRenderer:
    _, geometry = _layout(config, spec)
    age = config.ages[spec.age]
    return BelongsToRenderer(
        book_dir=target,
        geometry=geometry,
        params=age.postprocess,
        settings=config.settings.belongs_to_page,
        age=age.belongs_to,
    )


@app.command()
def images(
    book: BookArg,
    concurrency: ConcurrencyOpt = None,
    image_provider: ImageProviderOpt = None,
    image_quality: QualityOpt = None,
    qa: QaOpt = None,
    belongs_to_page: BelongsToOpt = None,
    max_cost: MaxCostOpt = None,
    log_level: LogLevelOpt = None,
) -> None:
    """Krok 2: surowe grafiki stron, których brakuje albo trzeba je odnowić (FR-17)."""
    config = _config()
    level = _log_level(config, log_level)
    workers = _workers(config, concurrency)
    quality = _quality(config, image_quality)
    writer = _open_book(book)
    do_qa = config.settings.qa if qa is None else qa
    images_provider, vision = _image_providers(
        config, writer.manifest.input.format, image_provider, do_qa
    )
    costs = _cost_tracker(config, max_cost, _models(images_provider, vision))
    has_front = writer.manifest.front_matter.belongs_to is not None
    if belongs_to_page is True or (belongs_to_page is None and has_front):
        _check_font(config)
    with _locked(book, level), _timed(StepTimer(), "images", costs):
        code = _step_images(
            config, book, images_provider, vision, workers, quality, costs, belongs_to_page
        )
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
        log_event(_log, logging.INFO, "user_edit", page=number)

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
    with progress_bar("Obróbka", len(todo)) as advance:
        for i, page in enumerate(todo, start=1):
            _finalize_page(writer, postprocessor, target, page, params_sha, f"[{i}/{len(todo)}]")
            advance()
    front_done = _finalize_front(config, spec, writer, target, geometry)
    if not todo and not front_done:
        typer.echo("Gotowe strony są aktualne, nic do obróbki.")

    status = writer.update_status()
    ok = len(manifest.ok_pages)
    log_event(_log, logging.INFO, "finalize_done", ok=ok, pages=len(manifest.pages), status=status)
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
    if writer.front is not None and writer.front.status != "ok":
        missing.insert(0, FRONT_NAME)
    if missing:
        _warn([f"brakujące strony: {', '.join(missing)}; ponów: kdp-studio images {target}"])
        return ExitCode.PARTIAL
    return ExitCode.OK


def _front_params_sha256(config: AppConfig, spec: BookSpec, geometry: PageGeometry) -> str:
    """Suma wszystkiego, co zmienia gotową stronę FR-14: obróbka, napis, czcionka, układ."""
    age = config.ages[spec.age]
    settings = config.settings.belongs_to_page
    font = settings.font_path.read_bytes() if settings.font_path.is_file() else b""
    parts = [
        age.postprocess.model_dump_json(),
        age.belongs_to.model_dump_json(),
        settings.model_dump_json(exclude={"enabled", "composition", "max_retries"}),
        sha256_bytes(font),
    ]
    return postprocess_sha256("|".join(parts), geometry)


def _finalize_front(
    config: AppConfig,
    spec: BookSpec,
    writer: ManifestWriter,
    target: Path,
    geometry: PageGeometry,
) -> bool:
    """Gotowa strona „This book belongs to…” z napisem (FR-14); True, gdy była obrabiana."""
    front = writer.front
    if front is None or front.layout is None or front.raw_sha256 is None:
        return False
    params_sha = _front_params_sha256(config, spec, geometry) + f"|{front.layout}"
    if not front_needs_finalize(target, front, params_sha):
        return False
    final = FinalInfo(raw_sha256=front.raw_sha256, postprocess_sha256=params_sha)
    started = time.monotonic()
    error = None
    try:
        files = _front_renderer(config, spec, target).render(front_raw_path(target), front.layout)
    except PostprocessError as e:
        error = f"obróbka: {e}"
        writer.record_front_final(png=None, svg=None, final=final, error=error)
    else:
        writer.record_front_final(png=files.page, svg=files.svg, final=final, error=None)
    duration = time.monotonic() - started
    log_event(
        _log,
        logging.INFO,
        "front_final",
        name=FRONT_NAME,
        layout=front.layout,
        status="ok" if error is None else "failed",
        duration_s=round(duration, 2),
        error=error,
    )
    result = "ok" if error is None else f"nieudana: {error}"
    layout = "ramka" if front.layout == "frame" else "układ zapasowy"
    typer.echo(f"{FRONT_NAME}: {result} ({layout}, {format_duration(duration)})")
    return True


def _finalize_page(
    writer: ManifestWriter,
    postprocessor: PagePostprocessor,
    target: Path,
    page: ManifestPage,
    params_sha: str,
    counter: str,
) -> None:
    """Obróbka jednej strony z wpisem w manifeście, konsoli i logu."""
    assert page.raw_sha256 is not None
    final = FinalInfo(raw_sha256=page.raw_sha256, postprocess_sha256=params_sha)
    started = time.monotonic()
    error = None
    try:
        files = postprocessor.process(target / RAW_DIR / f"{page.name}.png", page.name)
    except PostprocessError as e:
        error = f"obróbka: {e}"
        writer.record_final(page.page, png=None, svg=None, final=final, error=error)
    else:
        writer.record_final(page.page, png=files.page, svg=files.svg, final=final, error=None)
    duration = time.monotonic() - started
    status = "ok" if error is None else "failed"
    log_event(
        _log,
        logging.INFO,
        "page_final",
        page=page.page,
        name=page.name,
        status=status,
        duration_s=round(duration, 2),
        error=error,
    )
    result = "ok" if error is None else f"nieudana: {error}"
    typer.echo(f"{counter} {page.name}: {result} ({format_duration(duration)})")


@app.command()
def finalize(book: BookArg, log_level: LogLevelOpt = None) -> None:
    """Krok 3: gotowe strony do Canvy, wektory i canva.md, bez wywołań API (FR-17)."""
    config = _config()
    level = _log_level(config, log_level)
    with _locked(book, level), _timed(StepTimer(), "finalize"):
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
    belongs_to_page: BelongsToOpt = None,
    max_cost: MaxCostOpt = None,
    log_level: LogLevelOpt = None,
) -> None:
    """Generuje kolorowankę: kroki ideas, images i finalize po kolei (FR-17)."""
    timer = StepTimer()
    config = _config()
    level = _log_level(config, log_level)
    spec = _book_spec(config, theme, age, style, format_, pages, strict)
    workers = _workers(config, concurrency)
    quality = _quality(config, image_quality)
    target = _new_book_dir(output_dir, spec)
    do_qa = config.settings.qa if qa is None else qa
    do_review = config.settings.review_ideas if review_ideas is None else review_ideas
    # Wszyscy dostawcy przed pierwszym wywołaniem API: zły klucz albo proporcja wychodzą od razu.
    provider = _text_provider(config)
    images_provider, vision = _image_providers(config, spec.format, image_provider, do_qa)
    costs = _cost_tracker(config, max_cost, [provider.model, *_models(images_provider, vision)])
    belongs = _belongs(config, belongs_to_page)

    with _locked(target, level):
        log_event(_log, logging.INFO, "run_start", command="generate", book=str(target))
        with _timed(timer, "ideas", costs):
            _step_ideas(config, spec, target, provider, do_review, costs, belongs)
        if costs.over_budget():
            code = _stop_after_ideas(target, costs)
        else:
            with _timed(timer, "images", costs):
                code = _step_images(
                    config, target, images_provider, vision, workers, quality, costs
                )
        # Po błędzie krytycznym albo przekroczonym limicie krok 3 czeka na dokończenie kroku 2.
        if code not in (ExitCode.PROVIDER_ERROR, ExitCode.BUDGET_EXCEEDED):
            with _timed(timer, "finalize"):
                code = max(code, _step_finalize(config, target))
        _report_summary(target, timer, costs, ExitCode(code))
    raise typer.Exit(code)


def _models(images: ImageProvider, vision: VisionProvider | None) -> list[str]:
    return [images.model] + ([] if vision is None else [vision.model])


def _stop_after_ideas(target: Path, costs: CostTracker) -> ExitCode:
    """`generate`: same pomysły zużyły limit (FR-10), więc grafiki nie startują."""
    writer = _open_book(target)
    message = (
        f"przekroczony limit kosztu {format_usd(costs.limit_usd)} już po pomysłach "
        f"(wydano {format_usd(costs.spent)})"
    )
    writer.update_status(budget_error=message)
    _fail_lines([message, f"grafiki z wyższym limitem: kdp-studio images {target} --max-cost …"])
    return ExitCode.BUDGET_EXCEEDED


def _report_summary(target: Path, timer: StepTimer, costs: CostTracker, code: ExitCode) -> None:
    """Podsumowanie `generate` (FR-10, NFR-09): strony, koszt i czas każdego kroku i całości."""
    manifest = _open_book(target).manifest
    ok = len(manifest.ok_pages)
    failed = sum(p.status == "failed" for p in manifest.pages)
    total = timer.total
    steps = ", ".join(f"{STEP_LABELS[name]} {format_duration(s)}" for name, s in timer.steps)
    kinds = ", ".join(
        f"{COST_LABELS[kind]} {format_usd(amount)}" for kind, amount in costs.by_kind.items()
    )
    typer.echo(
        f"Strony: {ok}/{len(manifest.pages)} gotowe, "
        f"{plural(failed, 'nieudana', 'nieudane', 'nieudanych')}."
    )
    typer.echo(
        f"Koszt: {kinds}; razem {format_usd(costs.spent)} z limitu {format_usd(costs.limit_usd)}."
    )
    typer.echo(f"Czas: {steps}; razem {format_duration(total)}.")
    log_event(
        _log,
        logging.INFO,
        "run_end",
        command="generate",
        exit_code=int(code),
        pages_ok=ok,
        pages_failed=failed,
        duration_s=round(total, 2),
        steps={name: round(s, 2) for name, s in timer.steps},
        cost_usd=costs.spent,
        costs=costs.by_kind,
        max_cost_usd=costs.limit_usd,
    )


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
