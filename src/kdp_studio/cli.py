"""Interfejs wiersza poleceń (spec §9)."""

from __future__ import annotations

import sys
from collections.abc import Sequence
from enum import IntEnum
from pathlib import Path
from typing import Annotated

import typer
from dotenv import load_dotenv

from kdp_studio.config import ConfigError, load_config
from kdp_studio.pipeline.ideas import IdeaGenerator
from kdp_studio.pipeline.output import IDEAS_FILE, PROMPTS_FILE, book_dir, write_json_atomic
from kdp_studio.pipeline.prompts import PromptBuilder
from kdp_studio.profiles import PROFILE_KINDS, ProfileKind, format_profiles
from kdp_studio.providers.base import ProviderError
from kdp_studio.providers.registry import create_text_provider
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
) -> None:
    """Generuje kolorowankę. Na razie walidacja, pomysły i prompty obrazu (FR-01–FR-04)."""
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

    settings = config.settings
    try:
        provider = create_text_provider(settings.providers.text, settings.models.text)
    except ConfigError as e:
        raise _fail([str(e)]) from e

    typer.echo(f"Generuję pomysły ({provider.name}, {provider.model})…")
    try:
        ideas_result = IdeaGenerator(provider, config).generate(spec)
    except ProviderError as e:
        raise _fail([str(e)], ExitCode.PROVIDER_ERROR) from e
    _warn(ideas_result.warnings)

    write_json_atomic(target / IDEAS_FILE, ideas_result.ideas)
    ideas = ideas_result.ideas
    reserve = len(ideas.pages) - spec.pages
    usage = ideas_result.usage
    typer.echo(
        f"Tytuł: {ideas.book.title}\n"
        f"Pomysły: {len(ideas.pages)} ({plural(spec.pages, 'strona', 'strony', 'stron')} + "
        f"{plural(reserve, 'zapasowy', 'zapasowe', 'zapasowych')}), "
        f"tokeny: {usage.input_tokens} wejście / {usage.output_tokens} wyjście, "
        f"{plural(ideas_result.attempts, 'próba', 'próby', 'prób')}.\n"
        f"Zapisano: {target / IDEAS_FILE}"
    )

    prompts = PromptBuilder(spec, config).build(ideas)
    write_json_atomic(target / PROMPTS_FILE, prompts)
    typer.echo(
        f"Prompty obrazu: {len(prompts.pages)}. Zapisano: {target / PROMPTS_FILE}\n"
        "Generowanie grafik (FR-05 i dalej) nie jest jeszcze zaimplementowane."
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
