"""Koszt druku, cena minimalna i tantiemy paperbacka z tabel KDP (FR-16).

Wszystko na `Decimal`: kwoty z `config/markets.yaml` przychodzą jako `Decimal`, a połówki
centa zaokrągla się `ROUND_HALF_UP`, jak kalkulator KDP (sprawdzone 16.11.2026). Koszt druku
zostaje niezaokrąglony: cenę minimalną i tantiemę liczy się z dokładnego kosztu, a zaokrągla
dopiero wynik (202 strony: 4.434 / 0.5 = 8.868 → 8.87, a z kosztu 4.43 wyszłoby 8.86).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

from kdp_studio.config import LargeTrim, MarketPricing, Royalty
from kdp_studio.models import pages_in_book

TrimClass = Literal["regular", "large"]

RATE_50 = Decimal("0.5")
RATE_60 = Decimal("0.6")
# Waluty bez części ułamkowej: cena i tantiema w pełnych jednostkach.
WHOLE_UNIT_CURRENCIES = frozenset({"JPY"})


def trim_class(trim_in: tuple[float, float], large: LargeTrim) -> TrimClass:
    """Format duży: ponad 6.12" szerokości albo ponad 9" wysokości (oba nasze formaty)."""
    width, height = trim_in
    if width > large.width_over_in or height > large.height_over_in:
        return "large"
    return "regular"


def money(value: Decimal, currency: str) -> Decimal:
    """Zaokrąglenie do grosza (albo pełnej jednostki, np. jena) jak w kalkulatorze KDP."""
    quantum = Decimal(1) if currency in WHOLE_UNIT_CURRENCIES else Decimal("0.01")
    result = value.quantize(quantum, rounding=ROUND_HALF_UP)
    return abs(result) if result == 0 else result  # bez „-0.00”


def printing_cost(pricing: MarketPricing, trim: TrimClass, pages: int) -> Decimal:
    """Dokładny koszt druku: stały do progu stron, potem stały + strony × koszt strony."""
    table = pricing.printing_cost
    row = table.large if trim == "large" else table.regular
    if pages <= table.fixed_only_max_pages:
        return row.fixed_only
    return row.fixed + pages * row.per_page


def royalty_rate(royalty: Royalty, price: Decimal) -> Decimal:
    """Stawka 60% od ceny progowej, poniżej 50%. Cena między progami (PLN: 39–40, gdzie KDP
    nie podaje stawki) liczy się ostrożnie jako 50%."""
    return RATE_60 if price >= royalty.rate_60_min_price else RATE_50


def royalty_at(pricing: MarketPricing, cost: Decimal, price: Decimal) -> Decimal:
    """Tantiema za egzemplarz przy cenie netto `price`: stawka × cena - dokładny koszt druku."""
    return money(royalty_rate(pricing.royalty, price) * price - cost, pricing.currency)


def min_price(pricing: MarketPricing, cost: Decimal) -> Decimal:
    """Cena minimalna KDP (koszt / stawka). Gdy koszt / 0.5 przekracza próg 50%, a koszt / 0.6
    wypada poniżej ceny progowej 60%, minimum to sama cena progowa (letter, 258 stron → $9.99)."""
    royalty = pricing.royalty
    at_50 = money(cost / RATE_50, pricing.currency)
    if at_50 <= royalty.rate_50_max_price:
        return at_50
    return max(money(cost / RATE_60, pricing.currency), royalty.rate_60_min_price)


def equal_royalty_price(pricing: MarketPricing) -> Decimal:
    """Cena przy stawce 50%, która dałaby tantiemę taką jak cena progowa przy 60%
    (Amazon.com: 0.6 × 9.99 / 0.5 = 11.988 → 11.99, czyli już powyżej progu)."""
    threshold = pricing.royalty.rate_60_min_price
    return money(RATE_60 * threshold / RATE_50, pricing.currency)


def payback_copies(book_cost: Decimal, royalty: Decimal) -> int | None:
    """Egzemplarze, po których tantiemy pokryją koszt generowania; None bez tantiemy."""
    if royalty <= 0:
        return None
    return max(math.ceil(book_cost / royalty), 0)


def images_without_extra_cost(
    pricing: MarketPricing, images: int, front: int, single_sided: bool
) -> int:
    """Ile grafik zmieści się jeszcze bez wzrostu kosztu druku (koszt stały do progu stron)."""
    limit = pricing.printing_cost.fixed_only_max_pages
    extra = 0
    while pages_in_book(images + extra + 1, front, single_sided) <= limit:
        extra += 1
    return extra


@dataclass(frozen=True)
class PriceRow:
    price: Decimal
    rate: Decimal
    royalty: Decimal
    label: str = ""  # np. „cena minimalna”, „próg 60%”, „--price”


@dataclass(frozen=True)
class MarketQuote:
    """Wynik FR-16 dla jednego rynku i jednej liczby stron."""

    market: str
    currency: str
    trim: TrimClass
    pages_in_book: int
    cost: Decimal  # dokładny
    min_price: Decimal
    threshold_price: Decimal  # najniższa cena ze stawką 60% (próg albo cena minimalna)
    max_price: Decimal
    rows: list[PriceRow] = field(default_factory=list)

    @property
    def cost_display(self) -> Decimal:
        return money(self.cost, self.currency)

    @property
    def threshold_royalty(self) -> Decimal:
        return next(r.royalty for r in self.rows if r.price == self.threshold_price)


def price_errors(pricing: MarketPricing, cost: Decimal, price: Decimal, market: str) -> list[str]:
    """`--price` poniżej ceny minimalnej albo powyżej maksymalnej (kod 1)."""
    lowest = min_price(pricing, cost)
    if price < lowest:
        return [f"--price {price} {pricing.currency}: poniżej ceny minimalnej {market} ({lowest})"]
    if price > pricing.royalty.max_price:
        return [
            f"--price {price} {pricing.currency}: powyżej ceny maksymalnej {market} "
            f"({pricing.royalty.max_price})"
        ]
    return []


def quote(
    market: str,
    pricing: MarketPricing,
    trim: TrimClass,
    pages: int,
    price: Decimal | None = None,
) -> MarketQuote:
    """Koszt druku, cena minimalna i tabela tantiem: cena minimalna, ceny z `candidate_prices`
    rynku, ostatnia cena przed progiem, cena progowa i cena z `--price`."""
    cost = printing_cost(pricing, trim, pages)
    lowest = min_price(pricing, cost)
    royalty = pricing.royalty
    labels: dict[Decimal, str] = {}
    for value in pricing.candidate_prices:
        labels.setdefault(value, "")
    labels[royalty.rate_50_max_price] = "ostatnia przed progiem"
    labels[royalty.rate_60_min_price] = "próg 60%"
    labels[lowest] = "cena minimalna"
    if price is not None:
        labels[price] = "--price"
    cur = pricing.currency
    rows = [
        PriceRow(
            price=money(value, cur),
            rate=royalty_rate(royalty, value),
            royalty=royalty_at(pricing, cost, value),
            label=labels[value],
        )
        for value in sorted(labels)
        if lowest <= value <= royalty.max_price
    ]
    return MarketQuote(
        market=market,
        currency=pricing.currency,
        trim=trim,
        pages_in_book=pages,
        cost=cost,
        min_price=lowest,
        # Najniższa dozwolona cena ze stawką 60%: próg albo cena minimalna, gdy jest wyższa.
        threshold_price=max(money(royalty.rate_60_min_price, cur), lowest),
        max_price=money(royalty.max_price, cur),
        rows=rows,
    )


def below_threshold_note(pricing: MarketPricing, result: MarketQuote) -> str | None:
    """Ostrzeżenie o cenach tuż pod progiem: przy stawce 50% tantiema jest niższa niż przy
    cenie progowej, a taką samą dałaby dopiero cena powyżej progu. None, gdy strefy 50% nie ma
    (cena minimalna już w stawce 60%)."""
    cur = pricing.currency
    last_50 = money(pricing.royalty.rate_50_max_price, cur)
    if result.min_price > last_50:
        return None
    last = royalty_at(pricing, result.cost, last_50)
    return (
        f"ceny od {result.min_price} do {last_50} {cur} mają stawkę 50%: tantiema przy "
        f"{last_50} to {last}, a przy cenie progowej {result.threshold_price} już "
        f"{result.threshold_royalty}. Tyle co próg stawka 50% dałaby dopiero przy "
        f"{equal_royalty_price(pricing)}, czyli powyżej progu."
    )


def stale(checked: date, today: date, max_days: int) -> bool:
    """Dane z tabel KDP starsze niż `stale_after_days`: ostrzeżenie z linkami do aktualizacji."""
    return (today - checked).days > max_days
