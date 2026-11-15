"""Interfejs wiersza poleceń (spec §9)."""

from __future__ import annotations

import sys
from collections.abc import Sequence
from enum import IntEnum
from typing import Annotated

import typer

from kdp_studio.config import ConfigError, load_config
from kdp_studio.validation import InputValidationError, plural, validate_book_spec


class ExitCode(IntEnum):
    """Kody wyjścia (spec §9.3)."""

    OK = 0
    VALIDATION_ERROR = 1
    PARTIAL = 2
    BUDGET_EXCEEDED = 3
    PROVIDER_ERROR = 4


app = typer.Typer(
    name="kdp-studio",
    help="Generator kolorowanek pod Amazon KDP.",
    no_args_is_help=True,
    add_completion=False,
)


@app.callback()
def _root() -> None:
    """Generator kolorowanek pod Amazon KDP."""


def _fail(lines: Sequence[str]) -> typer.Exit:
    for line in lines:
        typer.echo(f"Błąd: {line}", err=True)
    return typer.Exit(ExitCode.VALIDATION_ERROR)


@app.command()
def generate(
    theme: Annotated[
        str | None, typer.Option(help="Tematyka lub roboczy tytuł kolorowanki.")
    ] = None,
    age: Annotated[str | None, typer.Option(help="Profil wieku z config/ages.yaml.")] = None,
    style: Annotated[str | None, typer.Option(help="Profil stylu z config/styles.yaml.")] = None,
    format_: Annotated[
        str, typer.Option("--format", help="Profil formatu z config/formats.yaml.")
    ] = "letter",
    pages: Annotated[int, typer.Option(help="Liczba grafik (stron kolorowanki), 1–200.")] = 30,
    strict: Annotated[
        bool, typer.Option("--strict", help="Za mało stron dla KDP to błąd, nie ostrzeżenie.")
    ] = False,
) -> None:
    """Generuje kolorowankę. Na razie tylko walidacja wejścia (FR-01, FR-02)."""
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

    for warning in result.warnings:
        typer.echo(f"Ostrzeżenie: {warning}", err=True)

    spec = result.spec
    typer.echo(
        f"Parametry poprawne: '{spec.theme}', wiek {spec.age}, styl {spec.style}, "
        f"format {spec.format}, {plural(spec.pages, 'grafika', 'grafiki', 'grafik')} "
        f"({plural(spec.pages_in_book, 'strona', 'strony', 'stron')} książki)."
    )
    typer.echo("Generowanie (FR-03 i dalej) nie jest jeszcze zaimplementowane.")


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
    sys.exit(main())
