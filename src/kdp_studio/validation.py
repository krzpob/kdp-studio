"""Walidacja parametrów wejściowych przed pierwszym wywołaniem API (FR-01, FR-02, §7.2)."""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass, field

from kdp_studio.config import AppConfig
from kdp_studio.models import PAGES_MAX, PAGES_MIN, BookSpec, pages_in_book, pages_per_image

KDP_MIN_BOOK_PAGES = 24  # minimum KDP dla paperbacka


class InputValidationError(Exception):
    """Błędy walidacji wejścia (kod wyjścia 1). Zbiera wszystkie błędy naraz."""

    def __init__(self, errors: list[str]) -> None:
        super().__init__("\n".join(errors))
        self.errors = errors


@dataclass(frozen=True)
class ValidationResult:
    spec: BookSpec
    warnings: list[str] = field(default_factory=list)


def min_pages_for_kdp(front_matter_pages: int, single_sided: bool = True) -> int:
    """Najmniejsza liczba grafik, przy której książka ma co najmniej 24 strony."""
    per_image = pages_per_image(single_sided)
    return max(PAGES_MIN, math.ceil((KDP_MIN_BOOK_PAGES - front_matter_pages) / per_image))


def check_page_count(
    pages: int, front: int, single_sided: bool, config: AppConfig
) -> tuple[list[str], list[str]]:
    """FR-02: błędy i ostrzeżenia o liczbie stron książki (minimum KDP, tabela marginesów).
    Komunikat o minimum zwraca jako ostrzeżenie; `--strict` robi z niego błąd."""
    errors: list[str] = []
    warnings: list[str] = []
    total = pages_in_book(pages, front, single_sided)
    if total < KDP_MIN_BOOK_PAGES:
        per_image = pages_per_image(single_sided)
        mode = "druku jednostronnym" if single_sided else "druku dwustronnym"
        warnings.append(
            f"książka będzie miała {plural(total, 'stronę', 'strony', 'stron')} "
            f"({plural(pages, 'grafika', 'grafiki', 'grafik')} × {per_image} przy {mode} + "
            f"{plural(front, 'strona wstępna', 'strony wstępne', 'stron wstępnych')}), "
            f"a minimum KDP to {KDP_MIN_BOOK_PAGES}. "
            f"Ustaw --pages na co najmniej {min_pages_for_kdp(front, single_sided)}"
        )
    max_pages = config.settings.kdp_margins.max_pages
    if total > max_pages:
        errors.append(
            f"--pages: książka miałaby {plural(total, 'stronę', 'strony', 'stron')}, a tabela "
            f"marginesów KDP (kdp_margins w settings.yaml) kończy się na {max_pages}"
        )
    return errors, warnings


def plural(n: int, one: str, few: str, many: str) -> str:
    """Polska odmiana rzeczownika po liczebniku: 1 strona, 2 strony, 5 stron, 22 strony."""
    if n == 1:
        return f"{n} {one}"
    if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14):
        return f"{n} {few}"
    return f"{n} {many}"


def _allowed(keys: Iterable[str]) -> str:
    return ", ".join(keys)


def _check_key(option: str, value: str | None, keys: list[str], errors: list[str]) -> bool:
    if value is None:
        errors.append(f"{option}: parametr wymagany. Dozwolone wartości: {_allowed(keys)}")
        return False
    if value not in keys:
        errors.append(f"{option}: nieznana wartość '{value}'. Dozwolone wartości: {_allowed(keys)}")
        return False
    return True


def validate_book_spec(
    *,
    theme: str | None,
    age: str | None,
    style: str | None,
    format: str | None,
    pages: int,
    strict: bool,
    config: AppConfig,
    market: str | None = None,
    instructions: bool | None = None,
    single_sided: bool | None = None,
) -> ValidationResult:
    """Sprawdza wszystkie parametry i zwraca BookSpec z ostrzeżeniami.

    Zgłasza `InputValidationError` z listą wszystkich błędów, jeśli którykolwiek
    parametr jest niepoprawny albo `strict` zamienia ostrzeżenie FR-02 w błąd.
    """
    errors: list[str] = []
    warnings: list[str] = []

    if theme is None or not theme.strip():
        errors.append("--theme: parametr wymagany, temat nie może być pusty")

    age_ok = _check_key("--age", age, list(config.ages), errors)
    style_ok = _check_key("--style", style, list(config.styles), errors)
    _check_key("--format", format, list(config.formats), errors)
    market = config.settings.default_market if market is None else market
    _check_key("--market", market, list(config.markets.markets), errors)

    pages_ok = PAGES_MIN <= pages <= PAGES_MAX
    if not pages_ok:
        errors.append(f"--pages: musi być w zakresie {PAGES_MIN}–{PAGES_MAX} (podano {pages})")

    if age_ok and style_ok:
        assert age is not None and style is not None
        style_profile = config.styles[style]
        if not style_profile.allows(age):
            warnings.append(
                f"styl '{style}' nie jest przewidziany dla wieku '{age}' "
                f"(dozwolone: {_allowed(style_profile.allowed_ages or [])})"
            )

    # FR-23: strona 1 i prawa autorskie, z instrukcją także instrukcja i pusta strona za nią.
    front_matter = config.settings.front_matter
    front = front_matter.pages if instructions is None else (4 if instructions else 2)
    if single_sided is None:
        single_sided = config.settings.interior.single_sided
    if pages_ok:
        count_errors, count_warnings = check_page_count(pages, front, single_sided, config)
        errors += count_errors
        for message in count_warnings:
            if strict:
                errors.append(f"--pages: {message} (--strict)")
            else:
                warnings.append(message)

    if errors:
        raise InputValidationError(errors)

    assert theme is not None and age is not None and style is not None and format is not None
    spec = BookSpec(
        theme=theme,
        age=age,
        style=style,
        format=format,
        pages=pages,
        front_matter_pages=front,
        market=market,
        single_sided=single_sided,
    )
    return ValidationResult(spec=spec, warnings=warnings)
