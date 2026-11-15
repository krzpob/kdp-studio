"""Interfejs wiersza poleceń (spec §9)."""

from __future__ import annotations

import sys
from collections.abc import Sequence
from enum import IntEnum
from pathlib import Path
from typing import Annotated

import typer
from dotenv import load_dotenv

from kdp_studio.config import MAX_CONCURRENCY, ConfigError, load_config
from kdp_studio.models import BookIdeas
from kdp_studio.pipeline.canva import CANVA_FILE, render_canva_md
from kdp_studio.pipeline.idea_review import IdeaReviewer
from kdp_studio.pipeline.ideas import IdeaGenerator
from kdp_studio.pipeline.manifest import (
    AI_DISCLOSURE,
    ImageProviderInfo,
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
    SVG_DIR,
    book_dir,
    write_bytes_atomic,
    write_json_atomic,
)
from kdp_studio.pipeline.postprocess import PageGeometry, PagePostprocessor, page_margin_in
from kdp_studio.pipeline.prompts import PromptBuilder
from kdp_studio.pipeline.worker import PageOutcome, PageWorker, page_jobs
from kdp_studio.profiles import PROFILE_KINDS, ProfileKind, format_profiles
from kdp_studio.providers.base import ProviderError
from kdp_studio.providers.registry import create_image_provider, create_text_provider
from kdp_studio.validation import InputValidationError, plural, validate_book_spec


class ExitCode(IntEnum):
    """Kody wyjścia (spec §9.3)."""

    OK = 0
    VALIDATION_ERROR = 1
    PARTIAL = 2
    BUDGET_EXCEEDED = 3
    PROVIDER_ERROR = 4


DEFAULT_FORMAT = "letter"

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


@app.command()
def generate(
    theme: Annotated[
        str | None, typer.Option(help="Tematyka lub roboczy tytuł kolorowanki.")
    ] = None,
    age: Annotated[str | None, typer.Option(help="Profil wieku z config/ages.yaml.")] = None,
    style: Annotated[str | None, typer.Option(help="Profil stylu z config/styles.yaml.")] = None,
    format_: Annotated[
        str, typer.Option("--format", help="Profil formatu z config/formats.yaml.")
    ] = DEFAULT_FORMAT,
    pages: Annotated[int, typer.Option(help="Liczba grafik (stron kolorowanki), 1–200.")] = 30,
    strict: Annotated[
        bool, typer.Option("--strict", help="Za mało stron dla KDP to błąd, nie ostrzeżenie.")
    ] = False,
    output_dir: Annotated[
        Path, typer.Option(help="Katalog, w którym powstaje katalog książki.")
    ] = Path("output"),
    concurrency: Annotated[
        int | None,
        typer.Option(
            help=f"Grafiki generowane równolegle, 1–{MAX_CONCURRENCY}. Domyślnie z settings.yaml."
        ),
    ] = None,
    image_provider: Annotated[
        str | None,
        typer.Option(help="Dostawca grafik z rejestru. Domyślnie z settings.yaml."),
    ] = None,
    review_ideas: Annotated[
        bool | None,
        typer.Option(
            "--review-ideas/--no-review-ideas",
            help="Weryfikacja pomysłów przed grafikami (FR-03a). Domyślnie z settings.yaml.",
        ),
    ] = None,
) -> None:
    """Generuje kolorowankę: pomysły, prompty, strony do druku, manifest i canva.md."""
    try:
        config = load_config()
    except ConfigError as e:
        raise _fail([str(e)]) from e

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
    settings = config.settings
    workers = settings.concurrency if concurrency is None else concurrency
    if not 1 <= workers <= MAX_CONCURRENCY:
        raise _fail([f"--concurrency: musi być w zakresie 1–{MAX_CONCURRENCY} (podano {workers})"])

    _warn(result.warnings)
    spec = result.spec
    typer.echo(
        f"Parametry poprawne: '{spec.theme}', wiek {spec.age}, styl {spec.style}, "
        f"format {spec.format}, {plural(spec.pages, 'grafika', 'grafiki', 'grafik')} "
        f"({plural(spec.pages_in_book, 'strona', 'strony', 'stron')} książki)."
    )

    target = book_dir(output_dir, spec)
    if (target / IDEAS_FILE).exists():
        raise _fail(
            [
                f"{target / IDEAS_FILE} już istnieje. Usuń katalog albo wybierz inny "
                "--output-dir (wznawianie --resume to FR-09, jeszcze niezaimplementowane)"
            ]
        )

    aspect = config.formats[spec.format].aspect
    try:
        provider = create_text_provider(settings.providers.text, settings.models.text)
        images = create_image_provider(
            image_provider or settings.providers.image, settings.models.image
        )
    except ConfigError as e:
        raise _fail([str(e)]) from e
    if aspect not in images.supported_aspects():
        raise _fail(
            [
                f"dostawca grafik '{images.name}' nie obsługuje proporcji {aspect} "
                f"formatu {spec.format}. Obsługiwane: {', '.join(images.supported_aspects())}"
            ]
        )

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
    do_review = settings.review_ideas if review_ideas is None else review_ideas
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

    fmt = config.formats[spec.format]
    margin_in = page_margin_in(fmt, settings.kdp_margins, spec.pages_in_book)
    gutter_in = settings.kdp_margins.gutter_in(spec.pages_in_book)
    assert gutter_in is not None  # FR-02 odrzuca książki grubsze niż tabela marginesów
    typer.echo(
        f'Strona {fmt.page_px[0]}×{fmt.page_px[1]} px ({fmt.dpi} DPI), margines {margin_in:g}" '
        f'z każdej strony (grzbiet KDP dla {spec.pages_in_book} stron: {gutter_in:g}").'
    )
    postprocessor = PagePostprocessor(
        book_dir=target,
        geometry=PageGeometry.for_format(fmt, margin_in),
        params=config.ages[spec.age].postprocess,
    )

    jobs = page_jobs(prompts, spec.pages)
    manifest = ManifestWriter.start(
        target,
        jobs=jobs,
        input=ManifestInput(
            theme=spec.theme,
            age=spec.age,
            style=spec.style,
            format=spec.format,
            pages=spec.pages,
            front_matter_pages=spec.front_matter_pages,
            concurrency=workers,
            review_ideas=do_review,
        ),
        providers=ManifestProviders(
            text=ProviderInfo(provider=provider.name, model=provider.model),
            image=ImageProviderInfo(
                provider=images.name,
                model=images.model,
                quality=settings.image_quality,
                aspect=aspect,
            ),
        ),
        layout=ManifestLayout(
            trim_in=fmt.trim_in,
            page_px=fmt.page_px,
            dpi=fmt.dpi,
            pages_in_book=spec.pages_in_book,
            gutter_in=gutter_in,
            margin_in=margin_in,
        ),
        ideas=ManifestIdeas(
            count=len(ideas.pages), reserve=reserve, reviewed=do_review, usage=ideas_usage
        ),
    )
    typer.echo(
        f"Generuję {plural(len(jobs), 'grafikę', 'grafiki', 'grafik')} ({images.name}, "
        f"{images.model}, jakość {settings.image_quality}, równolegle {workers})…"
    )
    done = 0

    def report(outcome: PageOutcome) -> None:
        nonlocal done
        done += 1
        if outcome.status == "ok":
            line = f"{outcome.name}: ok ({outcome.duration_s:.1f} s)"
        else:
            line = f"{outcome.name}: nieudana: {outcome.error}"
        typer.echo(f"[{done}/{len(jobs)}] {line}")
        manifest.record(outcome)

    worker = PageWorker(
        provider=images,
        book_dir=target,
        aspect=aspect,
        quality=settings.image_quality,
        concurrency=workers,
        postprocessor=postprocessor,
    )
    images_result = worker.run(jobs, on_done=report)
    image_usage = images_result.usage
    typer.echo(
        f"Strony: {len(images_result.ok)}/{len(jobs)} ok, tokeny: "
        f"{image_usage.input_tokens} wejście / {image_usage.output_tokens} wyjście.\n"
        f"Gotowe strony do Canvy: {target}/page_*.png (wektory: {target / SVG_DIR}, "
        f"surowe: {target / RAW_DIR})"
    )
    status = manifest.finish(images_result.fatal_error)
    typer.echo(f"Manifest: {manifest.path} (status: {status})")
    if images_result.fatal_error is not None:
        raise _fail([images_result.fatal_error], ExitCode.PROVIDER_ERROR)

    canva = target / CANVA_FILE
    write_bytes_atomic(canva, render_canva_md(manifest.manifest, ideas.book.title).encode("utf-8"))
    typer.echo(f"Instrukcja składania w Canvie: {canva}")
    typer.echo(f"Pamiętaj: {AI_DISCLOSURE}")
    if images_result.failed:
        failed = ", ".join(o.name for o in images_result.failed)
        raise _fail([f"nieudane strony: {failed}"], ExitCode.PARTIAL)


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
