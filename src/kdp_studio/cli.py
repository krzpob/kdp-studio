"""Interfejs wiersza poleceń (spec §9)."""

from __future__ import annotations

import logging
import sys
import time
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from enum import IntEnum
from functools import partial
from pathlib import Path
from typing import Annotated, Literal, get_args

import typer
from dotenv import load_dotenv
from PIL import Image

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
from kdp_studio.pipeline import cmyk
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
from kdp_studio.pipeline.cover import CoverBuild, CoverError, build_cover, front_crop, preview
from kdp_studio.pipeline.cover_back import BackPainter
from kdp_studio.pipeline.cover_front import (
    CoverBudgetError,
    CoverColorError,
    FrontColorizer,
    book_style,
    color_prompt,
)
from kdp_studio.pipeline.cover_geometry import (
    CoverGeometry,
    check_template_name,
    compare_template,
    measure_template,
)
from kdp_studio.pipeline.cover_vision import (
    CoverQAResult,
    FrontScene,
    analyze_front,
    check_cover,
    contact_sheet,
    png_bytes,
    propose_pages,
    select_instructions,
)
from kdp_studio.pipeline.cover_vision import qa_instructions as cover_qa_instructions
from kdp_studio.pipeline.diversity import DiversityLimits, diversity_report
from kdp_studio.pipeline.fonts import FontError
from kdp_studio.pipeline.idea_review import IdeaReviewer
from kdp_studio.pipeline.ideas import IdeaGenerator
from kdp_studio.pipeline.manifest import (
    AI_DISCLOSURE,
    CoverBackInfo,
    CoverCmykInfo,
    CoverFiles,
    CoverFrontInfo,
    CoverInfo,
    CoverSceneInfo,
    CoverSeamInfo,
    CoverSelectionInfo,
    CoverTemplateInfo,
    FinalInfo,
    FrontPage,
    ImageProviderInfo,
    Manifest,
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
from kdp_studio.pipeline.pdf import write_cmyk_pdf
from kdp_studio.pipeline.postprocess import (
    PageGeometry,
    PagePostprocessor,
    PostprocessError,
    page_margin_in,
)
from kdp_studio.pipeline.prompts import PromptBuilder
from kdp_studio.pipeline.qa import QAChecker
from kdp_studio.pipeline.worker import (
    PageOutcome,
    PageWorker,
    ReservePool,
    page_jobs,
)
from kdp_studio.profiles import PROFILE_KINDS, ProfileKind, format_profiles
from kdp_studio.providers.base import (
    ImageProvider,
    ProviderError,
    TextProvider,
    Usage,
    VisionProvider,
)
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
    "belongs-to": "strona „belongs to”",
    "cover": "okładka",
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
GenerateCoverOpt = Annotated[
    bool | None,
    typer.Option(
        "--cover/--no-cover",
        help="Okładka (FR-15) jako ostatni krok, gdy wszystkie strony są gotowe: strony wybiera "
        "model z wizją, reszta ustawień z settings.yaml (cover). Liczy się do --max-cost. "
        "Domyślnie cover.in_generate.",
    ),
]
BookArg = Annotated[Path, typer.Argument(help="Katalog książki (z kroku kdp-studio ideas).")]
BelongsToOpt = Annotated[
    bool | None,
    typer.Option(
        "--belongs-to-page/--no-belongs-to-page",
        help="Strona „This book belongs to…” w motywie książki (FR-14) jako krok po images, "
        "jak kdp-studio belongs-to: ramka z modelu obrazu, napis wpisuje program. "
        "Domyślnie belongs_to_page.enabled z settings.yaml.",
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
    """`generate --belongs-to-page` z flagą albo z settings.yaml; włączony wymaga czcionki."""
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
    config: AppConfig, fmt: str, image_provider: str | None, need_vision: bool
) -> tuple[ImageProvider, VisionProvider | None]:
    """Dostawcy kroku 2 (i okładki w generate), tworzeni przed pierwszym wywołaniem API."""
    settings = config.settings
    aspect = config.formats[fmt].aspect
    vision: VisionProvider | None = None
    try:
        images = create_image_provider(
            image_provider or settings.providers.image, settings.models.image
        )
        if need_vision:
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
    with _locked(target, level), _timed(timer, "ideas", costs):
        _step_ideas(config, spec, target, provider, do_review, costs)
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
    with progress_bar("Grafiki", len(jobs)) as advance:
        result = worker.run(jobs, on_done=lambda outcome: report(outcome, advance))
    usage = result.usage
    fatal_error = result.fatal_error
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
    skipped = len(jobs) - len(result.outcomes)
    budget_error = None
    if result.budget_exceeded:
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
    regenerated = {o.name for o in result.ok}
    cover = manifest.cover
    if cover is not None:
        redone = sorted(regenerated & {cover.front_page, *cover.thumbnails})
        if redone:
            _warn(
                [
                    f"okładka używa stron wygenerowanych ponownie ({', '.join(redone)}); "
                    f"odśwież ją: kdp-studio cover {target}"
                ]
            )
    front = writer.front
    if front is not None and front.layout == "fallback" and front.fallback_source in regenerated:
        _warn(
            [
                f"{FRONT_NAME} używa grafiki {front.fallback_source} sprzed ponownego "
                f"generowania; odśwież ją: kdp-studio belongs-to {target}"
            ]
        )
    if result.failed:
        failed = ", ".join(o.name for o in result.failed)
        _warn([f"nieudane strony: {failed}; ponów: kdp-studio images {target}"])
        return ExitCode.PARTIAL
    return ExitCode.OK


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
    """Ramka strony „This book belongs to…” z modelu albo układ zapasowy (FR-14); False, gdy
    się nie udała. ProviderError z fatal=True przechodzi wyżej (kod 4).
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
    with _locked(book, level), _timed(StepTimer(), "images", costs):
        code = _step_images(config, book, images_provider, vision, workers, quality, costs)
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
    if not todo:
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
    if missing:
        _warn([f"brakujące strony: {', '.join(missing)}; ponów: kdp-studio images {target}"])
    front = writer.front
    if front is not None and front.status != "ok":
        _warn([f"brakuje strony {FRONT_NAME}; ponów: kdp-studio belongs-to {target}"])
    elif front is not None and front_needs_finalize(
        target, front, _front_params_sha256(config, spec, geometry, front.layout)
    ):
        _warn(
            [
                f"{FRONT_NAME} nie odpowiada obecnym ustawieniom (obróbka, napis albo czcionka); "
                f"odśwież ją bez nowej grafiki: kdp-studio belongs-to {target}"
            ]
        )
    if missing or (front is not None and front.status != "ok"):
        return ExitCode.PARTIAL
    return ExitCode.OK


def _front_params_sha256(
    config: AppConfig, spec: BookSpec, geometry: PageGeometry, layout: str | None
) -> str:
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
    return postprocess_sha256("|".join(parts), geometry) + f"|{layout}"


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
    params_sha = _front_params_sha256(config, spec, geometry, front.layout)
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


# --- Strona „This book belongs to…” (FR-14) ----------------------------------------------------


def _belongs_to_blocker(target: Path, manifest: Manifest) -> str | None:
    """Powód, dla którego strony FR-14 nie da się zrobić: brak gotowych surowych grafik stron
    (układ zapasowy używa pierwszej z nich)."""
    if never_generated(manifest) or fallback_art(target, manifest) is None:
        return f"brak gotowych surowych grafik stron książki: najpierw kdp-studio images {target}"
    return None


def _step_belongs_to(
    config: AppConfig,
    target: Path,
    images: ImageProvider,
    vision: VisionProvider | None,
    quality: str,
    costs: CostTracker,
    *,
    refresh_canva: bool,
) -> ExitCode:
    """Cała strona „This book belongs to…” (FR-14): ramka z modelu, gdy jej brakuje albo jest
    nieaktualna, potem napis i kontrola druku. Zmiana napisu czy czcionki nie kosztuje grafiki."""
    writer = _open_book(target)
    manifest = writer.manifest
    spec = spec_from_manifest(manifest)
    try:
        ideas = load_ideas(target)
    except BookError as e:
        raise _fail(e.errors) from e
    prompt, elements = belongs_to_prompt(spec, config, ideas)
    front = writer.front
    if front is None:
        front = _new_front(config, spec, ideas, images.name, images.model)
        writer.set_front(front)
        typer.echo(
            f"Strona „This book belongs to…”: nowy wpis w manifeście (elementy motywu: "
            f"{', '.join(elements) or '-'})."
        )
    front.elements = elements
    reason = plan_front(target, front, prompt)
    if reason is not None:
        if costs.over_budget():
            message = (
                f"przekroczony limit kosztu {format_usd(costs.limit_usd)} (wydano "
                f"{format_usd(costs.spent)}), pominięto {FRONT_NAME}"
            )
            writer.update_status(budget_error=message)
            _fail_lines(
                [message, f"z wyższym limitem: kdp-studio belongs-to {target} --max-cost …"]
            )
            return ExitCode.BUDGET_EXCEEDED
        checker = None if vision is None else QAChecker(vision, spec, config, ideas)
        try:
            _step_front(
                config, spec, writer, target, images, quality, costs, checker, prompt, reason
            )
        except ProviderError as e:
            writer.update_status(str(e))
            _fail_lines([str(e), f"po usunięciu przyczyny: kdp-studio belongs-to {target}"])
            return ExitCode.PROVIDER_ERROR
    _, geometry = _layout(config, spec)
    rendered = _finalize_front(config, spec, writer, target, geometry)
    if reason is None and not rendered:
        typer.echo(f"{FRONT_NAME} jest aktualna, nic do zrobienia.")
    canva = target / CANVA_FILE
    if refresh_canva and canva.is_file():
        write_bytes_atomic(canva, render_canva_md(manifest, ideas.book.title).encode("utf-8"))
        typer.echo(f"Odświeżono instrukcję składania w Canvie: {canva}")
    status = writer.update_status()
    typer.echo(f"Manifest: {writer.path} (status: {status})")
    if front.status != "ok":
        _warn([f"nieudana strona {FRONT_NAME}: {front.error}"])
        return ExitCode.PARTIAL
    return ExitCode.OK


def _remove_front(target: Path) -> None:
    """`belongs-to --remove`: strona znika z książki i z canva.md, surowa grafika zostaje."""
    writer = _open_book(target)
    if writer.front is None:
        typer.echo("Książka nie ma strony „This book belongs to…”, nic do usunięcia.")
        return
    writer.set_front(None)
    for path in (target / f"{FRONT_NAME}.png", target / SVG_DIR / f"{FRONT_NAME}.svg"):
        path.unlink(missing_ok=True)
    typer.echo(
        f"Usunięto stronę „This book belongs to…” ({FRONT_NAME}.png i wpis w manifeście); "
        f"surowa grafika zostaje w {front_raw_path(target)}."
    )
    canva = target / CANVA_FILE
    if canva.is_file():
        try:
            title = load_ideas(target).book.title
        except BookError as e:
            raise _fail(e.errors) from e
        write_bytes_atomic(canva, render_canva_md(writer.manifest, title).encode("utf-8"))
        typer.echo(f"Odświeżono instrukcję składania w Canvie: {canva}")
    status = writer.update_status()
    typer.echo(f"Manifest: {writer.path} (status: {status})")


@app.command("belongs-to")
def belongs_to(
    book: Annotated[Path, typer.Argument(help="Katalog książki po kroku kdp-studio images.")],
    image_quality: QualityOpt = None,
    qa: QaOpt = None,
    remove: Annotated[
        bool,
        typer.Option(
            "--remove",
            help=f"Usuwa stronę z książki: {FRONT_NAME}.png i wpis w manifeście (surowa "
            "grafika zostaje).",
        ),
    ] = False,
    max_cost: MaxCostOpt = None,
    log_level: LogLevelOpt = None,
) -> None:
    """Strona „This book belongs to…” w motywie książki (FR-14): ramka z modelu obrazu, napis
    i miejsce na imię wpisuje program. Po kroku images; po finalize odświeża też canva.md."""
    config = _config()
    level = _log_level(config, log_level)
    if remove:
        if image_quality is not None or qa is not None or max_cost is not None:
            raise _fail(["--remove nie łączy się z --image-quality, --qa ani --max-cost"])
        with _locked(book, level):
            _remove_front(book)
        return
    _check_font(config)
    writer = _open_book(book)
    blocker = _belongs_to_blocker(book, writer.manifest)
    if blocker is not None:
        raise _fail([blocker])
    quality = _quality(config, image_quality)
    do_qa = config.settings.qa if qa is None else qa
    manifest = writer.manifest
    images_provider, vision = _image_providers(
        config, manifest.input.format, manifest.providers.image.provider, do_qa
    )
    costs = _cost_tracker(config, max_cost, _models(images_provider, vision))
    with _locked(book, level), _timed(StepTimer(), "belongs-to", costs):
        code = _step_belongs_to(
            config, book, images_provider, vision, quality, costs, refresh_canva=True
        )
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
    cover_: GenerateCoverOpt = None,
    max_cost: MaxCostOpt = None,
    log_level: LogLevelOpt = None,
) -> None:
    """Generuje kolorowankę: kroki ideas, images i finalize po kolei (FR-17), opcjonalnie
    stronę „This book belongs to…” przed finalize (FR-14) i okładkę na końcu (FR-15)."""
    timer = StepTimer()
    config = _config()
    level = _log_level(config, log_level)
    spec = _book_spec(config, theme, age, style, format_, pages, strict)
    workers = _workers(config, concurrency)
    quality = _quality(config, image_quality)
    target = _new_book_dir(output_dir, spec)
    do_qa = config.settings.qa if qa is None else qa
    do_review = config.settings.review_ideas if review_ideas is None else review_ideas
    do_cover = config.settings.cover.in_generate if cover_ is None else cover_
    cover_setup = _generate_cover_setup(config, spec) if do_cover else None
    # Wszyscy dostawcy przed pierwszym wywołaniem API: zły klucz albo proporcja wychodzą od razu.
    provider = _text_provider(config)
    need_vision = do_qa or (cover_setup is not None and cover_setup.needs_vision)
    images_provider, vision = _image_providers(config, spec.format, image_provider, need_vision)
    costs = _cost_tracker(config, max_cost, [provider.model, *_models(images_provider, vision)])
    belongs = _belongs(config, belongs_to_page)

    with _locked(target, level):
        log_event(_log, logging.INFO, "run_start", command="generate", book=str(target))
        with _timed(timer, "ideas", costs):
            _step_ideas(config, spec, target, provider, do_review, costs)
        if costs.over_budget():
            code = _stop_after_ideas(target, costs)
        else:
            with _timed(timer, "images", costs):
                code = _step_images(
                    config,
                    target,
                    images_provider,
                    vision if do_qa else None,
                    workers,
                    quality,
                    costs,
                )
        if belongs and code not in (ExitCode.PROVIDER_ERROR, ExitCode.BUDGET_EXCEEDED):
            code = max(
                code,
                _generate_belongs_to(
                    config,
                    target,
                    images_provider,
                    vision if do_qa else None,
                    quality,
                    costs,
                    timer,
                ),
            )
        # Po błędzie krytycznym albo przekroczonym limicie krok 3 czeka na dokończenie kroku 2.
        if code not in (ExitCode.PROVIDER_ERROR, ExitCode.BUDGET_EXCEEDED):
            with _timed(timer, "finalize"):
                code = max(code, _step_finalize(config, target))
        if cover_setup is not None:
            cover_code = _step_cover(
                config, target, cover_setup, images_provider, vision, costs, timer
            )
            code = code if cover_code is None else max(code, cover_code)
        _report_summary(target, timer, costs, ExitCode(code))
    raise typer.Exit(code)


def _generate_belongs_to(
    config: AppConfig,
    target: Path,
    images: ImageProvider,
    vision: VisionProvider | None,
    quality: str,
    costs: CostTracker,
    timer: StepTimer,
) -> ExitCode:
    """`generate --belongs-to-page`: krok między images a finalize; canva.md pisze finalize."""
    blocker = _belongs_to_blocker(target, _open_book(target).manifest)
    if blocker is not None:
        _warn([f"strona „This book belongs to…” pominięta: {blocker}"])
        return ExitCode.PARTIAL
    with _timed(timer, "belongs-to", costs):
        return _step_belongs_to(config, target, images, vision, quality, costs, refresh_canva=False)


def _generate_cover_setup(config: AppConfig, spec: BookSpec) -> _CoverSetup:
    """`generate --cover`: kontrole okładki przed pierwszym wywołaniem API. Strony wybiera
    model z wizją (cover.select_pages), więc nie ma tu --cover-page ani --thumbnails."""
    count = config.settings.cover.thumbnails
    if spec.pages <= count:
        raise _fail(
            [f"--cover: okładka potrzebuje co najmniej {count + 1} stron (przód i miniatury)"]
        )
    return _cover_setup(config, None, None, None, None, _quality(config, None))


def _step_cover(
    config: AppConfig,
    target: Path,
    setup: _CoverSetup,
    images: ImageProvider,
    vision: VisionProvider | None,
    costs: CostTracker,
    timer: StepTimer,
) -> ExitCode | None:
    """Ostatni krok `generate --cover`. Tylko gdy wszystkie strony są `ok`; inaczej pominięty
    z komunikatem (None: kod wyjścia zostaje z poprzednich kroków)."""
    writer = _open_book(target)
    manifest = writer.manifest
    missing = [p.name for p in manifest.pages if p.status != "ok"]
    if missing:
        shown = ", ".join(missing[:5]) + (", …" if len(missing) > 5 else "")
        _warn(
            [
                f"okładka pominięta: nie wszystkie strony są gotowe ({shown})",
                f"po dokończeniu książki: kdp-studio cover {target}",
            ]
        )
        return None
    try:
        pick = _cover_pages(target, manifest, None, None, config.settings.cover.thumbnails)
        run = _cover_run(
            target,
            writer,
            config,
            _cover_geometry(config, manifest),
            setup,
            pick,
            images if setup.color else None,
            vision if setup.needs_vision else None,
            costs,
        )
        with _timed(timer, "cover", costs):
            return _make_cover(run)
    except typer.Exit as e:  # błąd okładki już wypisany; podsumowanie generate i tak powstaje
        return ExitCode(e.exit_code)


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


# --- Okładka (FR-15) ---------------------------------------------------------------------------

COVER_DIR = "cover"
cmyk_converter = cmyk.converter_from  # testy podmieniają na konwerter bez profilu ICC


def _page_ref(value: str, manifest: Manifest) -> ManifestPage:
    """`7`, `07` albo `page_07` → strona książki."""
    raw = value.strip().removeprefix("page_")
    if not raw.isdigit():
        raise _fail([f"nie ma strony {value!r}: podaj numer, np. 07 albo page_07"])
    number = int(raw)
    if not 1 <= number <= len(manifest.pages):
        raise _fail([f"nie ma strony {value!r}: książka ma strony 1–{len(manifest.pages)}"])
    return manifest.pages[number - 1]


@dataclass
class _CoverPick:
    """Strony okładki: przód i miniatury tyłu (tylko gotowe strony)."""

    front: ManifestPage
    thumbs: list[ManifestPage]
    selection: Literal["manual", "default", "vision"]
    available: list[ManifestPage]
    manual_front: bool
    manual_thumbs: bool


def _cover_pages(
    target: Path,
    manifest: Manifest,
    cover_page: str | None,
    thumbnails: str | None,
    count: int,
) -> _CoverPick:
    """Strona na przód i miniatury tyłu; tylko gotowe strony (`ok` z plikiem PNG)."""

    def ready(page: ManifestPage) -> bool:
        return page.status == "ok" and (target / f"{page.name}.png").is_file()

    available = [p for p in manifest.pages if ready(p)]
    errors = []
    if cover_page:
        front = _page_ref(cover_page, manifest)
    elif available:
        front = available[0]
    else:
        raise _fail([f"brak gotowych stron: najpierw kdp-studio finalize {target}"])
    if not ready(front):
        errors.append(f"{front.name} nie jest gotowa (status {front.status})")
    if thumbnails:
        thumbs = [_page_ref(v, manifest) for v in thumbnails.split(",") if v.strip()]
        if not 3 <= len(thumbs) <= 4:
            errors.append("--thumbnails: podaj 3 albo 4 strony, np. 03,12,21")
        names = [p.name for p in thumbs]
        if len(set(names)) != len(names) or front.name in names:
            errors.append("--thumbnails: strony muszą być różne i inne niż przód")
        errors += [f"{p.name} nie jest gotowa (status {p.status})" for p in thumbs if not ready(p)]
    else:
        rest = [p for p in available if p.name != front.name]
        if len(rest) < count:
            errors.append(f"za mało gotowych stron na {count} miniatury")
        step = len(rest) / max(count, 1)
        thumbs = [rest[int(step * i + step / 2)] for i in range(count)] if rest else []
    if errors:
        raise _fail(errors)
    selection: Literal["manual", "default"] = "manual" if cover_page or thumbnails else "default"
    return _CoverPick(front, thumbs, selection, available, bool(cover_page), bool(thumbnails))


def _cover_template(
    template: Path, geometry: CoverGeometry, config: AppConfig
) -> CoverTemplateInfo:
    """Kontrola szablonu KDP; rozbieżność to błąd walidacji (kod 1)."""
    if not template.is_file():
        raise _fail([f"brak pliku szablonu {template}"])
    settings = config.settings.cover
    problems = check_template_name(template, geometry)
    if not problems:  # nazwa już mówi, że szablon jest dla innej książki: bez pomiaru
        try:
            measure = measure_template(template, geometry, settings.template_colors)
        except OSError as e:
            raise _fail([f"nie można odczytać szablonu {template}: {e}"]) from e
        problems = compare_template(measure, geometry, settings.template_tolerance_in)
    if problems:
        raise _fail([f"szablon KDP {template.name} nie pasuje do książki:", *problems])
    return CoverTemplateInfo(file=str(template))


@dataclass
class _CoverRun:
    """Wszystko, czego potrzebuje `_make_cover`; dostawcy tworzeni przed pierwszym wywołaniem."""

    target: Path
    writer: ManifestWriter
    geometry: CoverGeometry
    config: AppConfig
    converter: cmyk.CmykConverter
    pick: _CoverPick
    ideas: BookIdeas
    spec: BookSpec
    template: Path | None = None
    template_info: CoverTemplateInfo | None = None
    colorizer: FrontColorizer | None = None
    painter: BackPainter | None = None
    vision: VisionProvider | None = None
    select: bool = False  # propozycja stron modelem z wizją
    qa: bool = False
    back_text: bool = False
    costs: CostTracker | None = None
    cost_start: float = 0.0  # wydatki uruchomienia przed okładką (generate --cover)


@dataclass
class _CoverSetup:
    """Ustawienia okładki sprawdzane przed pierwszym wywołaniem API (czcionka, profil CMYK)."""

    converter: cmyk.CmykConverter
    color: bool
    select: bool
    qa: bool
    back_text: bool
    quality: str

    @property
    def needs_vision(self) -> bool:
        """Model z wizją: ocena przodu do tła tyłu (przy kolorze), wybór stron, QA."""
        return self.color or self.select or self.qa


def _cover_setup(
    config: AppConfig,
    color: bool | None,
    select_pages: bool | None,
    qa: bool | None,
    back_text: bool | None,
    quality: str,
    manual: bool = False,
) -> _CoverSetup:
    """Flagi okładki (domyślnie z settings.yaml) i kontrole bez wywołań API."""
    settings = config.settings.cover
    if not settings.title_font_path.is_file():
        raise _fail([f"brak czcionki tytułu {settings.title_font_path} (cover.title_font)"])
    try:
        converter = cmyk_converter(settings.cmyk)
    except cmyk.CmykError as e:
        raise _fail([str(e)]) from e
    return _CoverSetup(
        converter=converter,
        color=settings.colorize if color is None else color,
        select=(settings.select_pages if select_pages is None else select_pages) and not manual,
        qa=settings.qa if qa is None else qa,
        back_text=settings.back_text if back_text is None else back_text,
        quality=quality,
    )


def _cover_geometry(config: AppConfig, manifest: Manifest) -> CoverGeometry:
    layout = manifest.layout
    return CoverGeometry(
        trim_in=layout.trim_in,
        pages_in_book=layout.pages_in_book,
        kdp=config.settings.kdp_cover,
        key_margin_in=config.settings.cover.key_margin_in,
        dpi=layout.dpi,
    )


def _cover_run(
    target: Path,
    writer: ManifestWriter,
    config: AppConfig,
    geometry: CoverGeometry,
    setup: _CoverSetup,
    pick: _CoverPick,
    images: ImageProvider | None,
    vision: VisionProvider | None,
    costs: CostTracker | None,
    template: Path | None = None,
    template_info: CoverTemplateInfo | None = None,
) -> _CoverRun:
    """Złożenie okładki z gotowymi (opakowanymi w log) dostawcami; bez wywołań API."""
    settings = config.settings
    try:
        ideas = load_ideas(target)
    except BookError as e:
        raise _fail(e.errors) from e
    spec = spec_from_manifest(writer.manifest)
    run = _CoverRun(
        target=target,
        writer=writer,
        geometry=geometry,
        config=config,
        converter=setup.converter,
        pick=pick,
        ideas=ideas,
        spec=spec,
        template=template,
        template_info=template_info,
        vision=vision,
        select=setup.select,
        qa=setup.qa,
        back_text=setup.back_text,
        costs=costs,
        cost_start=costs.spent if costs is not None else 0.0,
    )
    if images is not None and costs is not None:
        raw_dir = target / COVER_DIR / RAW_DIR
        spend = partial(_spend, costs, images.model)
        run.colorizer = FrontColorizer(
            provider=images,
            quality=setup.quality,
            prompt=color_prompt(spec, config),
            settings=settings.cover,
            raw_dir=raw_dir,
            over_budget=costs.over_budget,
            spend=spend,
        )
        assert vision is not None
        run.painter = BackPainter(
            provider=images,
            quality=setup.quality,
            style=book_style(spec, config),
            settings=settings.cover,
            geometry=geometry,
            raw_dir=raw_dir,
            analyze=partial(_analyze_front, vision, settings.cover.seam_bands, costs),
            over_budget=costs.over_budget,
            spend=spend,
        )
    return run


SelectPagesOpt = Annotated[
    bool | None,
    typer.Option(
        "--select-pages/--no-select-pages",
        help="Bez --cover-page i --thumbnails strony proponuje model z wizją na podstawie "
        "arkusza kontaktowego; --no-select-pages: pierwsza strona i strony rozłożone po książce. "
        "Domyślnie z settings.yaml (cover.select_pages).",
    ),
]
CoverQaOpt = Annotated[
    bool | None,
    typer.Option(
        "--qa/--no-qa",
        help="Model z wizją sprawdza gotową okładkę: brak tekstu poza napisami programu, przód "
        "z wybraną stroną, tył w stylu przodu. Odrzucenie to kod 2. Domyślnie cover.qa.",
    ),
]
BackTextOpt = Annotated[
    bool | None,
    typer.Option(
        "--back-text/--no-back-text",
        help="Opis książki z metadanych na tyle, nad miniaturami. Domyślnie cover.back_text.",
    ),
]


@app.command()
def cover(
    book: BookArg,
    cover_page: Annotated[
        str | None,
        typer.Option(help="Strona na przód, np. 07. Domyślnie propozycja modelu z wizją."),
    ] = None,
    thumbnails: Annotated[
        str | None,
        typer.Option(
            help="3–4 strony na miniatury tyłu, np. 03,12,21. Domyślnie propozycja modelu z wizją."
        ),
    ] = None,
    template: Annotated[
        Path | None,
        typer.Option(help="Szablon z kalkulatora okładek KDP (PNG/JPEG) do kontroli wymiarów."),
    ] = None,
    color: Annotated[
        bool | None,
        typer.Option(
            "--color/--no-color",
            help="Kolorowanie przodu i tło tyłu z grzbietem z modelu obrazu (płatne); "
            "--no-color: szkic bez koloru. Domyślnie z settings.yaml (cover.colorize).",
        ),
    ] = None,
    select_pages: SelectPagesOpt = None,
    qa: CoverQaOpt = None,
    back_text: BackTextOpt = None,
    image_provider: ImageProviderOpt = None,
    image_quality: QualityOpt = None,
    max_cost: MaxCostOpt = None,
    log_level: LogLevelOpt = None,
) -> None:
    """Okładka paperback do KDP: cover.pdf w CMYK, podglądy i strefy (FR-15)."""
    config = _config()
    level = _log_level(config, log_level)
    settings = config.settings
    writer = _open_book(book)
    manifest = writer.manifest
    geometry = _cover_geometry(config, manifest)
    previous = manifest.cover
    pages_in_book = manifest.layout.pages_in_book
    if previous is not None and previous.geometry.get("pages_in_book") != pages_in_book:
        _warn(
            [
                f"poprzednia okładka była dla {previous.geometry.get('pages_in_book')} stron, "
                f"a książka ma {pages_in_book}: powstaje nowa"
            ]
        )
    pick = _cover_pages(book, manifest, cover_page, thumbnails, settings.cover.thumbnails)
    template_info = _cover_template(template, geometry, config) if template else None
    setup = _cover_setup(
        config,
        color,
        select_pages,
        qa,
        back_text,
        _quality(config, image_quality),
        manual=bool(cover_page and thumbnails),
    )
    if manifest.status != "completed":
        _warn([f"książka nie jest gotowa (status {manifest.status}); okładka z gotowych stron"])

    images: ImageProvider | None = None
    vision: VisionProvider | None = None
    try:
        if setup.color:
            images = create_image_provider(
                image_provider or settings.providers.image, settings.models.image
            )
        if setup.needs_vision:
            vision = create_vision_provider(settings.providers.vision, settings.models.vision)
    except ConfigError as e:
        raise _fail([str(e)]) from e
    models = [p.model for p in (images, vision) if p is not None]
    costs = _cost_tracker(config, max_cost, models) if models else None
    prices = settings.api_pricing.models
    run = _cover_run(
        book,
        writer,
        config,
        geometry,
        setup,
        pick,
        None if images is None else LoggedImageProvider(images, prices.get(images.model)),
        None if vision is None else LoggedVisionProvider(vision, prices.get(vision.model)),
        costs,
        template,
        template_info,
    )

    with _locked(book, level), _timed(StepTimer(), "cover", run.costs):
        code = _make_cover(run)
    raise typer.Exit(code)


def _analyze_front(
    vision: VisionProvider, bands: int, costs: CostTracker, front: Image.Image
) -> FrontScene:
    scene = analyze_front(vision, front, bands)
    costs.add("qa", vision.model, scene.usage)
    return scene


def _propose_cover_pages(run: _CoverRun) -> CoverSelectionInfo | None:
    """Propozycja stron modelem z wizją; strony podane ręcznie zostają. Błąd niekrytyczny:
    wybór domyślny z ostrzeżeniem (None)."""
    assert run.vision is not None and run.costs is not None
    pick, target = run.pick, run.target
    numbers = {p.name: i for i, p in enumerate(run.writer.manifest.pages, start=1)}
    by_number = {i: p for i, p in enumerate(run.writer.manifest.pages, start=1)}
    excluded = {p.name for p in pick.thumbs} if pick.manual_thumbs else set()
    on_sheet = [p for p in pick.available if p.name not in excluded]
    settings = run.config.settings.cover
    sheet = contact_sheet(
        [(numbers[p.name], target / f"{p.name}.png") for p in on_sheet], settings.title_font_path
    )
    path = target / COVER_DIR / RAW_DIR / "contact_sheet.png"
    write_bytes_atomic(path, png_bytes(sheet))
    if run.costs.over_budget():
        raise CoverBudgetError("przekroczony limit kosztu przed wyborem stron okładki")
    count = 0 if pick.manual_thumbs else len(pick.thumbs)
    fixed_front = numbers[pick.front.name] if pick.manual_front else None
    typer.echo(f"Wybieram strony okładki ({run.vision.name}, {run.vision.model})…")
    try:
        choice = propose_pages(
            run.vision,
            sheet,
            select_instructions(run.spec, run.config, run.ideas.book.title, count, fixed_front),
            [numbers[p.name] for p in on_sheet],
            count,
            fixed_front,
            numbers[pick.front.name],
            [] if pick.manual_thumbs else [numbers[p.name] for p in pick.thumbs],
        )
    except ProviderError as e:
        if e.fatal:
            raise
        _warn([f"propozycja stron modelem z wizją nie powiodła się ({e}); wybór domyślny"])
        return None
    run.costs.add("qa", run.vision.model, choice.usage)
    pick.front = by_number[choice.front]
    if not pick.manual_thumbs:
        pick.thumbs = [by_number[n] for n in choice.thumbnails]
    pick.selection = "vision"
    return CoverSelectionInfo(
        model=run.vision.model,
        reason=choice.reason,
        contact_sheet=path.relative_to(target).as_posix(),
        usage=choice.usage,
        warnings=choice.warnings,
    )


def _cover_qa(
    run: _CoverRun, rgb: Image.Image, build: CoverBuild
) -> tuple[CoverQAResult | None, str | None, Usage | None, ExitCode]:
    """QA gotowej okładki (`--qa`): (wynik, błąd, zużycie, kod wyjścia)."""
    assert run.vision is not None and run.costs is not None
    if run.costs.over_budget():
        return None, "przekroczony limit kosztu przed QA okładki", None, ExitCode.BUDGET_EXCEEDED
    ideas = {idea.id: idea for idea in run.ideas.pages}
    book = run.ideas.book
    instructions = cover_qa_instructions(
        book.title,
        book.subtitle,
        build.spine_text,
        build.back_text,
        ideas.get(run.pick.front.idea_id),
    )
    typer.echo("Sprawdzam okładkę (QA)…")
    try:
        result, usage = check_cover(run.vision, rgb, instructions)
    except ProviderError as e:
        return None, str(e), None, ExitCode.PROVIDER_ERROR if e.fatal else ExitCode.PARTIAL
    run.costs.add("qa", run.vision.model, usage)
    return result, None, usage, ExitCode.OK if result.passed else ExitCode.PARTIAL


def _make_cover(run: _CoverRun) -> ExitCode:
    target, writer, geometry, config = run.target, run.writer, run.geometry, run.config
    colorizer, painter, costs, pick = run.colorizer, run.painter, run.costs, run.pick
    settings = config.settings.cover
    title, subtitle = run.ideas.book.title, run.ideas.book.subtitle
    width_in, height_in = geometry.size_in
    width_px, height_px = geometry.size_px
    typer.echo(
        f'Okładka: {width_in:.3f}" × {height_in:.3f}" ({width_px} × {height_px} px, '
        f'{geometry.dpi} DPI), grzbiet {geometry.spine_in:.4f}" '
        f"({plural(geometry.pages_in_book, 'strona', 'strony', 'stron')})."
    )
    selection_info = None
    try:
        if run.select:
            selection_info = _propose_cover_pages(run)
        if colorizer is not None:
            typer.echo(
                f"Koloruję przód ({colorizer.provider.name}, {colorizer.provider.model}, jakość "
                f"{colorizer.quality}, limit {format_usd(costs.limit_usd if costs else 0)})…"
            )
        build = build_cover(
            geometry,
            settings,
            target / f"{pick.front.name}.png",
            [target / f"{p.name}.png" for p in pick.thumbs],
            title,
            subtitle,
            colorize=colorizer,
            paint_back=painter,
            back_text=run.ideas.book.description if run.back_text else None,
        )
    except (CoverColorError, CoverBudgetError, ProviderError) as e:
        code = (
            ExitCode.BUDGET_EXCEEDED
            if isinstance(e, CoverBudgetError)
            else ExitCode.PROVIDER_ERROR
            if isinstance(e, ProviderError)
            else ExitCode.PARTIAL
        )
        cost = costs.spent - run.cost_start if costs is not None else 0.0
        writer.manifest.cover = CoverInfo(
            status="failed",
            error=str(e),
            geometry=geometry.summary(),
            front_page=pick.front.name,
            thumbnails=[p.name for p in pick.thumbs],
            selection=pick.selection,
            selection_info=selection_info,
            title=title,
            subtitle=subtitle,
            spine_text=False,
            front=_front_info(target, colorizer, None),
            back=_back_info(target, painter, None),
            cost_usd=round(cost, 6),
        )
        writer.manifest.cost_usd = round(writer.manifest.cost_usd + cost, 6)
        writer.save()
        _fail_lines([f"okładka: {e}", f"spróbuj ponownie: kdp-studio cover {target}"])
        return code
    except (CoverError, FontError) as e:
        raise _fail([f"okładka: {e}"]) from e
    out = target / COVER_DIR
    out.mkdir(exist_ok=True)
    rgb = cmyk.rgb_preview(build.layers.color, build.layers.black, build.layers.paper)
    qa_result, qa_error, qa_usage, code = None, None, None, ExitCode.OK
    if run.qa:
        qa_result, qa_error, qa_usage, code = _cover_qa(run, rgb, build)
    result = cmyk.compose_cmyk(
        build.layers.color,
        build.layers.black,
        build.layers.paper,
        run.converter,
        settings.cmyk.max_total_ink_pct,
    )
    proof = run.converter.to_rgb(result.image)
    gamut, changed = cmyk.gamut_map(rgb, proof, settings.cmyk.gamut_warn_delta_e)
    area_pct = round(float(changed.mean() * 100), 2)
    left, top, right, bottom = build.placements["title"]
    title_changed = float(changed[top:bottom, left:right].mean() * 100) if right > left else 0.0
    warnings = list(build.warnings)
    if selection_info is not None:
        warnings += selection_info.warnings
    if painter is not None:
        warnings += painter.warnings
    if area_pct > settings.cmyk.gamut_warn_area_pct:
        warnings.append(
            f"kolory zmienią się w druku na {area_pct:g}% powierzchni "
            f"(ΔE > {settings.cmyk.gamut_warn_delta_e:g}); obejrzyj {COVER_DIR}/cover_gamut.png"
        )
    if title_changed > 1.0:
        warnings.append("kolory tytułu zmienią się w druku; obejrzyj cover_gamut.png")
    if qa_result is not None and not qa_result.passed:
        warnings.append(f"QA odrzuciła okładkę: {qa_result.summary()}")
    if qa_error is not None:
        warnings.append(f"QA okładki nie powiodła się: {qa_error}")

    files = CoverFiles(
        pdf=f"{COVER_DIR}/cover.pdf",
        png=f"{COVER_DIR}/cover.png",
        front=f"{COVER_DIR}/front.png",
        proof=f"{COVER_DIR}/cover_proof.png",
        gamut=f"{COVER_DIR}/cover_gamut.png",
        preview=f"{COVER_DIR}/cover_preview.png",
    )
    dpi = (geometry.dpi, geometry.dpi)
    write_cmyk_pdf(target / files.pdf, result.image, geometry.size_in, geometry.bleed)
    rgb.save(target / files.png, dpi=dpi)
    front_crop(rgb, geometry).save(target / files.front, dpi=dpi)
    proof.save(target / files.proof, dpi=dpi)
    gamut.save(target / files.gamut, dpi=dpi)
    preview(rgb, geometry, run.template).save(target / files.preview, dpi=dpi)

    cmyk_settings = settings.cmyk
    profile_path = cmyk_settings.profile_path
    info = CoverInfo(
        status="ok" if code == ExitCode.OK else "qa_failed",
        geometry=geometry.summary(),
        front_page=pick.front.name,
        thumbnails=[p.name for p in pick.thumbs],
        selection=pick.selection,
        selection_info=selection_info,
        title=title,
        subtitle=subtitle,
        spine_text=build.spine_text,
        placements=build.placements,
        template=run.template_info,
        front=_front_info(target, colorizer, build),
        back=_back_info(target, painter, build),
        back_text=build.back_text,
        qa=qa_result,
        qa_error=qa_error,
        qa_usage=qa_usage,
        cmyk=CoverCmykInfo(
            profile=run.converter.name,
            profile_file=str(profile_path) if profile_path is not None else None,
            profile_sha256=run.converter.sha256,
            rendering_intent=cmyk_settings.rendering_intent,
            black_point_compensation=cmyk_settings.black_point_compensation,
            max_total_ink_limit_pct=cmyk_settings.max_total_ink_pct,
            max_total_ink_pct=result.max_total_ink_pct,
            ink_limited_pct=result.ink_limited_pct,
            gamut_warn_delta_e=cmyk_settings.gamut_warn_delta_e,
            gamut_area_pct=area_pct,
            title_gamut_warning=title_changed > 1.0,
        ),
        files=files,
        warnings=warnings,
        cost_usd=round(costs.spent - run.cost_start, 6) if costs is not None else 0.0,
    )
    writer.manifest.cover = info
    writer.manifest.cost_usd = round(writer.manifest.cost_usd + info.cost_usd, 6)
    writer.save()
    log_event(
        _log,
        logging.INFO,
        "cover_done",
        front_page=pick.front.name,
        thumbnails=info.thumbnails,
        selection=pick.selection,
        spine_text=build.spine_text,
        geometry=info.geometry,
        max_total_ink_pct=result.max_total_ink_pct,
        gamut_area_pct=area_pct,
        warnings=warnings,
        colorized=build.colorized,
        contour_match=build.contour_match,
        back_painted=build.back_painted,
        seam_passed=info.back.seam_passed if info.back is not None else None,
        qa_pass=qa_result.passed if qa_result is not None else None,
        cost_usd=info.cost_usd,
    )

    how = {
        "default": "domyślny wybór; inne strony: --cover-page i --thumbnails",
        "manual": "wybór ręczny",
        "vision": "propozycja modelu z wizją"
        + (f": {selection_info.reason}" if selection_info and selection_info.reason else ""),
    }[pick.selection]
    typer.echo(f"Przód: {pick.front.name}; miniatury: {', '.join(info.thumbnails)} ({how}).")
    minimum = max(settings.spine_text_min_pages, geometry.kdp.spine_text_kdp_min_pages)
    spine = "tak" if build.spine_text else f"nie (od {minimum} stron)"
    typer.echo(f"Tekst na grzbiecie: {spine}.")
    if build.colorized and colorizer is not None:
        contours = "nałożone kontury 300 DPI" if build.contours_overlay else "kontury z modelu"
        typer.echo(
            f"Przód pokolorowany ({plural(colorizer.attempts, 'próba', 'próby', 'prób')}, "
            f"zgodność konturów {build.contour_match:.0%}, {contours})."
        )
    else:
        typer.echo("Przód: szkic bez koloru (--no-color).")
    if build.back_painted and painter is not None and painter.chosen is not None:
        seam = painter.seams[-1] if painter.seams else None
        used = next((s for s in painter.seams if s.passed), seam)
        seam_text = (
            f", styk z przodem ΔE {used.max_delta_e:g} (próg {settings.seam_max_delta_e:g})"
            if used is not None
            else ""
        )
        typer.echo(
            f"Tył i grzbiet z modelu ({plural(painter.attempts, 'próba', 'próby', 'prób')}"
            f"{seam_text})."
        )
    if costs is not None:
        typer.echo(f"Koszt okładki: {format_usd(info.cost_usd)}.")
    typer.echo(
        f"Tytuł w miniaturze {settings.thumbnail_check_px} px: litery {build.title_thumb_px:g} px, "
        f"kontrast {build.title_contrast:g}:1."
    )
    if run.template_info is not None:
        typer.echo(f"Szablon KDP {run.template.name if run.template else ''}: zgodny z geometrią.")
    typer.echo(
        f"CMYK: {run.converter.name} ({cmyk_settings.rendering_intent}), suma farb maks. "
        f"{result.max_total_ink_pct:g}% (limit {cmyk_settings.max_total_ink_pct}%), "
        f"zmiana koloru w druku na {area_pct:g}% powierzchni."
    )
    if qa_result is not None and qa_result.passed:
        typer.echo("QA okładki: zaakceptowana.")
    _warn(warnings)
    typer.echo(f"Okładka do KDP: {target / files.pdf}")
    typer.echo(
        f"Podglądy: {target / files.preview} (strefy), {target / files.proof} (symulacja druku), "
        f"{target / files.gamut} (zmiany kolorów), {target / files.front} (przód)."
    )
    typer.echo(
        "Pamiętaj: druk różni się od ekranu, więc ostateczną kontrolą kolorów jest egzemplarz "
        "próbny zamówiony w KDP."
    )
    return code


def _spend(costs: CostTracker, model: str, usage: Usage) -> None:
    costs.add("images", model, usage)


def _front_info(
    target: Path, colorizer: FrontColorizer | None, build: CoverBuild | None
) -> CoverFrontInfo:
    info = CoverFrontInfo(colorized=build.colorized if build is not None else False)
    if colorizer is not None:
        info.provider, info.model = colorizer.provider.name, colorizer.provider.model
        info.quality, info.aspect, info.prompt = (
            colorizer.quality,
            colorizer.aspect,
            colorizer.prompt,
        )
        info.attempts, info.errors, info.usage = (
            colorizer.attempts,
            colorizer.errors,
            colorizer.usage,
        )
        info.raw_files = [p.relative_to(target).as_posix() for p in colorizer.raw_files]
    if build is not None:
        info.contour_match, info.contours_overlay = build.contour_match, build.contours_overlay
        info.title_thumb_px, info.title_contrast = build.title_thumb_px, build.title_contrast
    return info


def _back_info(
    target: Path, painter: BackPainter | None, build: CoverBuild | None
) -> CoverBackInfo | None:
    if painter is None:
        return None
    scene = painter.scene
    return CoverBackInfo(
        painted=build.back_painted if build is not None else False,
        provider=painter.provider.name,
        model=painter.provider.model,
        quality=painter.quality,
        aspect=painter.aspect,
        prompt=painter.prompt,
        attempts=painter.attempts,
        chosen_attempt=painter.chosen,
        raw_files=[p.relative_to(target).as_posix() for p in painter.raw_files],
        errors=painter.errors,
        usage=painter.usage,
        scene=CoverSceneInfo(
            horizon=scene.horizon,
            band_colors=scene.band_colors,
            background=scene.background,
            usage=scene.usage,
        )
        if scene is not None
        else None,
        scene_error=painter.scene_error,
        edge_colors=painter.edge_colors,
        seams=[
            CoverSeamInfo(
                max_delta_e=s.max_delta_e,
                horizon_front=s.horizon_front,
                horizon_back=s.horizon_back,
                align_shift=s.align_shift,
                passed=s.passed,
            )
            for s in painter.seams
        ],
        seam_passed=any(s.passed for s in painter.seams) if painter.seams else None,
    )


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
