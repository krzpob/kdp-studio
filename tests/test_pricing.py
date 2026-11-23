"""Koszt druku, cena minimalna i tantiemy z tabel KDP (FR-16)."""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal

import pytest

from kdp_studio.cli import ExitCode, main
from kdp_studio.config import DEFAULT_CONFIG_DIR, LargeTrim, MarketPricing, load_config
from kdp_studio.pipeline.pricing import (
    below_threshold_note,
    images_without_extra_cost,
    min_price,
    money,
    payback_copies,
    price_errors,
    printing_cost,
    quote,
    royalty_at,
    stale,
    trim_class,
)
from tests.test_cli import BASE, BOOK_DIR, fake_text_provider  # noqa: F401  (autouse)

D = Decimal


def _us() -> MarketPricing:
    """Amazon.com, czarny atrament, papier biały: tabele KDP sprawdzone 16.11.2026."""
    return MarketPricing.model_validate(
        {
            "currency": "USD",
            "printing_cost": {
                "fixed_only_max_pages": 110,
                "regular": {"fixed_only": "2.30", "fixed": "1.00", "per_page": "0.012"},
                "large": {"fixed_only": "2.84", "fixed": "1.00", "per_page": "0.017"},
            },
            "royalty": {"rate_50_max_price": "9.98", "rate_60_min_price": "9.99", "max_price": 250},
            "candidate_prices": ["6.99", "7.99", "8.99", "12.99", "14.99"],
        }
    )


def test_our_formats_are_large_trim() -> None:
    large = LargeTrim(width_over_in=6.12, height_over_in=9.0)
    assert trim_class((8.5, 11.0), large) == "large"
    assert trim_class((8.5, 8.5), large) == "large"
    assert trim_class((6.0, 9.0), large) == "regular"


def test_printing_cost_letter_104_pages() -> None:
    assert printing_cost(_us(), "large", 104) == D("2.84")  # kalkulator KDP: $2.84


@pytest.mark.parametrize(
    ("pages", "expected"),
    [
        (202, "8.87"),  # 4.434 / 0.5 = 8.868; z zaokrąglonego kosztu 4.43 wyszłoby 8.86
        (258, "9.99"),  # przypadek graniczny: 5.386 / 0.6 = 8.98 < próg, więc cena progowa
        (402, "13.06"),  # 7.834 / 0.6 = 13.057; z kosztu 7.83 wyszłoby 13.05
    ],
)
def test_min_price_matches_kdp_calculator(pages: int, expected: str) -> None:
    pricing = _us()
    assert min_price(pricing, printing_cost(pricing, "large", pages)) == D(expected)


@pytest.mark.parametrize(
    ("pages", "cost", "royalty"),
    [
        (115, "2.96", "5.45"),  # tantiema 5.445 w górę: ROUND_HALF_UP, nie bankierskie
        (125, "3.13", "5.28"),  # koszt 3.125 w górę; z kosztu 3.13 tantiema byłaby 5.27
    ],
)
def test_cost_and_royalty_at_14_round_half_up(pages: int, cost: str, royalty: str) -> None:
    pricing = _us()
    exact = printing_cost(pricing, "large", pages)
    assert money(exact, "USD") == D(cost)
    assert royalty_at(pricing, exact, D("14.00")) == D(royalty)


@pytest.mark.parametrize(
    ("pages", "cost", "minimum", "at_999", "at_1299"),
    [
        (62, "2.84", "5.68", "3.15", "4.95"),  # 30 grafik
        (110, "2.84", "5.68", "3.15", "4.95"),  # 54 grafiki: ten sam koszt stały
        (122, "3.07", "6.15", "2.92", "4.72"),  # 60 grafik
        (202, "4.43", "8.87", "1.56", "3.36"),  # 100 grafik
    ],
)
def test_spec_example_table(pages: int, cost: str, minimum: str, at_999: str, at_1299: str) -> None:
    result = quote("US", _us(), "large", pages)
    rows = {row.price: row.royalty for row in result.rows}
    assert result.cost_display == D(cost)
    assert result.min_price == D(minimum)
    assert rows[D("9.99")] == D(at_999)
    assert rows[D("12.99")] == D(at_1299)


def test_repo_market_data_matches_spec() -> None:
    """Liczby Amazon.com w config/markets.yaml dają przykłady ze specyfikacji."""
    config = load_config(DEFAULT_CONFIG_DIR)
    pricing = config.markets.pricing("US")
    assert printing_cost(pricing, "large", 104) == D("2.84")
    assert min_price(pricing, printing_cost(pricing, "large", 258)) == D("9.99")
    for key in config.markets.markets:
        assert config.markets.pricing(key).candidate_prices, key
    assert config.markets.pricing("DE").vat and not config.markets.pricing("US").vat


def test_quote_rows_cover_min_threshold_and_price() -> None:
    result = quote("US", _us(), "large", 104, price=D("11.49"))
    labels = {row.price: row.label for row in result.rows}
    assert labels[D("5.68")] == "cena minimalna"
    assert labels[D("9.98")] == "ostatnia przed progiem"
    assert labels[D("9.99")] == "próg 60%"
    assert labels[D("11.49")] == "--price"
    assert [r.price for r in result.rows] == sorted(r.price for r in result.rows)
    assert {r.rate for r in result.rows if r.price < D("9.99")} == {D("0.5")}


def test_quote_drops_candidates_below_min_price() -> None:
    result = quote("US", _us(), "large", 258)  # cena minimalna 9.99
    assert result.rows[0].price == D("9.99")
    assert below_threshold_note(_us(), result) is None  # brak strefy 50%


def test_below_threshold_note_names_equal_royalty_price() -> None:
    note = below_threshold_note(_us(), quote("US", _us(), "large", 104))
    assert note is not None
    assert "2.15" in note and "3.15" in note and "11.99" in note


def test_price_outside_min_and_max_is_error() -> None:
    pricing = _us()
    cost = printing_cost(pricing, "large", 104)
    assert price_errors(pricing, cost, D("5.67"), "US")
    assert price_errors(pricing, cost, D("250.01"), "US")
    assert not price_errors(pricing, cost, D("5.68"), "US")


def test_images_without_extra_cost() -> None:
    # spec: 2 strony wstępne, druk jednostronny: do 110 stron mieści się 54 grafiki
    assert images_without_extra_cost(_us(), 30, 2, True) == 24
    assert images_without_extra_cost(_us(), 54, 2, True) == 0
    assert images_without_extra_cost(_us(), 50, 4, True) == 3
    assert images_without_extra_cost(_us(), 100, 4, False) == 6


def test_payback_and_yen_rounding() -> None:
    assert payback_copies(D("3.15"), D("3.15")) == 1
    assert payback_copies(D("3.16"), D("3.15")) == 2
    assert payback_copies(D("1"), D("0")) is None
    assert money(D("817.5"), "JPY") == D("818")
    assert str(money(D("-0.001"), "USD")) == "0.00"


def test_stale_after_days() -> None:
    assert not stale(date(2026, 11, 16), date(2027, 5, 15), 180)
    assert stale(date(2026, 11, 16), date(2027, 5, 16), 180)


# --- CLI -------------------------------------------------------------------------------------


def test_price_before_generation(capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["price", "--format", "letter", "--pages", "30", "--market", "us,pl"])
    assert code == ExitCode.OK
    out, err = capsys.readouterr()
    assert "Amazon.com (USA), USD: 30 grafik, 62 strony książki" in out
    assert "Koszt druku: 2.84 USD (koszt stały). Cena minimalna: 5.68 USD." in out
    assert "Amazon.pl (Polska), PLN" in out
    assert "VAT" in out  # PL: ceny netto
    assert "royalty-calculator" in out
    assert "stawkę 50%" in err


def test_price_validation_errors(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["price", "--pages", "30", "--price", "3"]) == ExitCode.VALIDATION_ERROR
    assert main(["price", "--pages", "30", "--market", "XX"]) == ExitCode.VALIDATION_ERROR
    assert main(["price", "--pages", "30", "--price", "abc"]) == ExitCode.VALIDATION_ERROR
    assert main(["price", "--format", "nope"]) == ExitCode.VALIDATION_ERROR
    err = capsys.readouterr().err
    assert "poniżej ceny minimalnej US (5.68)" in err
    assert "nieznany rynek" in err


def test_finalize_records_pricing_and_price_reads_book(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([*BASE, "--pages", "12"]) == ExitCode.OK
    out = capsys.readouterr().out
    assert "Cena (amazon.com): koszt druku 2.84 USD, cena minimalna 5.68 USD" in out
    manifest = json.loads((BOOK_DIR / "manifest.json").read_text(encoding="utf-8"))
    pricing = manifest["pricing"]
    assert pricing["market"] == "US" and pricing["pages_in_book"] == 26
    assert pricing["printing_cost"] == "2.84" and pricing["royalty_at_threshold"] == "3.15"

    assert main(["price", str(BOOK_DIR), "--price", "12.99"]) == ExitCode.OK
    out = capsys.readouterr().out
    assert "12 grafik, 26 stron książki" in out
    assert "zwróci się po 1 egzemplarzu przy cenie 12.99 USD" in out
    assert main(["price", str(BOOK_DIR), "--pages", "40"]) == ExitCode.VALIDATION_ERROR


def test_threshold_is_min_price_when_book_is_expensive() -> None:
    result = quote("US", _us(), "large", 402)  # cena minimalna 13.06 > 9.99
    assert result.threshold_price == D("13.06")
    assert result.threshold_royalty == D("0.00")
