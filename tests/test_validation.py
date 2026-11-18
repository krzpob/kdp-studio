from __future__ import annotations

from typing import Any

import pytest

from kdp_studio.config import AppConfig
from kdp_studio.validation import (
    InputValidationError,
    ValidationResult,
    min_pages_for_kdp,
    plural,
    validate_book_spec,
)

VALID: dict[str, Any] = {
    "theme": "Dinozaury",
    "age": "przedszkole",
    "style": "kawaii",
    "format": "square",
    "pages": 30,
    "strict": False,
    "instructions": False,  # 2 strony wstępne (FR-23 bez instrukcji)
}


def _validate(config: AppConfig, **overrides: Any) -> ValidationResult:
    return validate_book_spec(**{**VALID, **overrides}, config=config)


def _errors(config: AppConfig, **overrides: Any) -> list[str]:
    with pytest.raises(InputValidationError) as exc:
        _validate(config, **overrides)
    return exc.value.errors


# --- FR-01 ---------------------------------------------------------------------------


def test_valid_input(repo_config: AppConfig) -> None:
    result = _validate(repo_config, theme="  Dinozaury  ")
    assert result.warnings == []
    assert result.spec.theme == "Dinozaury"
    assert result.spec.pages_in_book == 62


@pytest.mark.parametrize(
    ("option", "value", "allowed"),
    [
        ("age", "niemowleta", "przedszkole, wczesnoszkolne, szkolne, nastolatki, dorosli"),
        ("style", "pixel-art", "kawaii, cartoon, realistic"),
        ("format", "a4", "letter, square"),
    ],
)
def test_unknown_profile_lists_allowed_values(
    repo_config: AppConfig, option: str, value: str, allowed: str
) -> None:
    [error] = _errors(repo_config, **{option: value})
    assert error.startswith(f"--{option}: nieznana wartość '{value}'")
    assert allowed in error


@pytest.mark.parametrize("option", ["age", "style"])
def test_missing_required_profile(repo_config: AppConfig, option: str) -> None:
    [error] = _errors(repo_config, **{option: None})
    assert error.startswith(f"--{option}: parametr wymagany. Dozwolone wartości:")


@pytest.mark.parametrize("theme", [None, "", "   "])
def test_missing_or_blank_theme(repo_config: AppConfig, theme: str | None) -> None:
    assert _errors(repo_config, theme=theme) == [
        "--theme: parametr wymagany, temat nie może być pusty"
    ]


@pytest.mark.parametrize("pages", [0, -5, 201])
def test_pages_out_of_range(repo_config: AppConfig, pages: int) -> None:
    assert _errors(repo_config, pages=pages) == [
        f"--pages: musi być w zakresie 1–200 (podano {pages})"
    ]


@pytest.mark.parametrize("pages", [1, 200])
def test_pages_range_bounds_are_inclusive(repo_config: AppConfig, pages: int) -> None:
    assert _validate(repo_config, pages=pages).spec.pages == pages


def test_all_errors_reported_at_once(repo_config: AppConfig) -> None:
    errors = _errors(repo_config, theme="", age="x", style="y", format="z", pages=0)
    assert [e.split(":")[0] for e in errors] == [
        "--theme",
        "--age",
        "--style",
        "--format",
        "--pages",
    ]


# --- §7.2: dozwolone połączenia wiek × styl ---------------------------------------------


def test_disallowed_style_for_age_is_a_warning(repo_config: AppConfig) -> None:
    result = _validate(repo_config, age="przedszkole", style="zentangle")
    assert result.warnings == [
        "styl 'zentangle' nie jest przewidziany dla wieku 'przedszkole' "
        "(dozwolone: nastolatki, dorosli)"
    ]


def test_disallowed_style_for_age_stays_a_warning_with_strict(repo_config: AppConfig) -> None:
    result = _validate(repo_config, age="przedszkole", style="fantasy", strict=True)
    assert len(result.warnings) == 1


# --- FR-02 ---------------------------------------------------------------------------


def test_exactly_kdp_minimum_has_no_warning(repo_config: AppConfig) -> None:
    result = _validate(repo_config, pages=11)  # 11 × 2 + 2 = 24
    assert result.warnings == []
    assert result.spec.pages_in_book == 24


def test_below_kdp_minimum_warns_with_minimal_page_count(repo_config: AppConfig) -> None:
    result = _validate(repo_config, pages=10)  # 10 × 2 + 2 = 22
    assert result.warnings == [
        "książka będzie miała 22 strony (10 grafik × 2 przy druku jednostronnym + "
        "2 strony wstępne), a minimum KDP to 24. Ustaw --pages na co najmniej 11"
    ]


def test_double_sided_counts_one_page_per_image(repo_config: AppConfig) -> None:
    result = _validate(repo_config, pages=21, single_sided=False)  # 2 + 21 = 23 → 24
    assert result.warnings == []
    assert result.spec.pages_in_book == 24
    assert not result.spec.single_sided


def test_double_sided_below_kdp_minimum(repo_config: AppConfig) -> None:
    result = _validate(repo_config, pages=12, single_sided=False)  # 2 + 12 = 14
    assert result.warnings == [
        "książka będzie miała 14 stron (12 grafik × 1 przy druku dwustronnym + "
        "2 strony wstępne), a minimum KDP to 24. Ustaw --pages na co najmniej 22"
    ]


def test_print_mode_defaults_to_settings(repo_config: AppConfig) -> None:
    assert _validate(repo_config, pages=12).spec.single_sided is True


def test_below_kdp_minimum_with_strict_is_an_error(repo_config: AppConfig) -> None:
    [error] = _errors(repo_config, pages=10, strict=True)
    assert error.startswith("--pages: książka będzie miała 22 strony")
    assert error.endswith("Ustaw --pages na co najmniej 11 (--strict)")


def test_instructions_add_two_front_matter_pages(repo_config: AppConfig) -> None:
    # FR-23: z instrukcją 4 strony wstępne (strona 1, prawa, instrukcja, pusta).
    assert _validate(repo_config, pages=10, instructions=True).warnings == []
    [warning] = _validate(repo_config, pages=9, instructions=True).warnings
    assert "co najmniej 10" in warning and "4 strony wstępne" in warning
    assert _validate(repo_config, instructions=True).spec.front_matter_pages == 4
    # Bez flagi: front_matter.instructions z settings.yaml (domyślnie tak).
    assert _validate(repo_config, instructions=None).spec.front_matter_pages == 4


def test_no_kdp_warning_for_invalid_pages(repo_config: AppConfig) -> None:
    errors = _errors(repo_config, pages=0, strict=True)
    assert errors == ["--pages: musi być w zakresie 1–200 (podano 0)"]


@pytest.mark.parametrize(
    ("front_matter", "expected"),
    [(0, 12), (1, 12), (2, 11), (3, 11), (22, 1), (24, 1), (40, 1)],
)
def test_min_pages_for_kdp(front_matter: int, expected: int) -> None:
    assert min_pages_for_kdp(front_matter) == expected
    assert expected * 2 + front_matter >= 24
    if expected > 1:
        assert (expected - 1) * 2 + front_matter < 24


@pytest.mark.parametrize(
    ("n", "expected"),
    [(1, "1 strona"), (2, "2 strony"), (5, "5 stron"), (12, "12 stron"), (22, "22 strony")],
)
def test_plural(n: int, expected: str) -> None:
    assert plural(n, "strona", "strony", "stron") == expected


def test_book_above_kdp_margin_table_is_an_error(repo_config: AppConfig) -> None:
    margins = repo_config.settings.kdp_margins.model_copy(
        update={"gutter_by_pages": repo_config.settings.kdp_margins.gutter_by_pages[:1]}
    )
    settings = repo_config.settings.model_copy(update={"kdp_margins": margins})
    config = repo_config.model_copy(update={"settings": settings})
    assert _validate(config, pages=74).spec.pages_in_book == 150
    [error] = _errors(config, pages=75)
    assert error == (
        "--pages: książka miałaby 152 strony, a tabela marginesów KDP "
        "(kdp_margins w settings.yaml) kończy się na 150"
    )
