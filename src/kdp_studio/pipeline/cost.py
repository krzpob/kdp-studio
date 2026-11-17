"""FR-10: koszt wywołań API z cennika w konfiguracji i limit budżetu.

Koszt liczy się z tokenów, które zwraca API (`Usage`), i cen z `settings.yaml` (`api_pricing`).
Limit (`--max-cost`) dotyczy całej książki, razem z poprawkami w kolejnych uruchomieniach
(zmiana z 17.11.2026; wcześniej jednego uruchomienia): `CostTracker` zaczyna od kosztu, który
książka już ma w manifeście (`spent_before`), i sumuje koszt kroków tego uruchomienia, a worker
przed każdą nową grafiką pyta, czy suma nie przekroczyła limitu. Łączny koszt książki posłuży
też do policzenia, ile egzemplarzy go zwróci (FR-16).
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field

from kdp_studio.config import ApiPricing, ModelPrice
from kdp_studio.providers.base import Usage

COST_DIGITS = 6  # dokładność zapisu w manifeście i logu (USD)


def usage_cost(price: ModelPrice, usage: Usage) -> float:
    return round(
        (usage.input_tokens * price.input_per_1m + usage.output_tokens * price.output_per_1m)
        / 1_000_000,
        COST_DIGITS,
    )


def missing_prices(pricing: ApiPricing, models: list[str]) -> list[str]:
    """Modele bez ceny w cenniku, w kolejności podania, bez powtórzeń."""
    return [m for m in dict.fromkeys(models) if m not in pricing.models]


def format_usd(amount: float) -> str:
    """`$1.26`; kwoty poniżej centa z czterema miejscami (`$0.0042`), żeby nie znikały."""
    if 0 < amount < 0.01:
        return f"${amount:.4f}"
    return f"${amount:.2f}"


@dataclass
class CostTracker:
    """Koszt jednego uruchomienia komendy według rodzaju wywołań i limit budżetu książki.

    `spent` to koszt tego uruchomienia, `total` razem z tym, co książka wydała wcześniej.
    `add()` woła wątek główny, `over_budget()` także wątki workera; odczyt i zapis pod blokadą.
    """

    pricing: ApiPricing
    limit_usd: float
    spent_before: float = 0.0  # koszt książki z manifestu przed tym uruchomieniem
    by_kind: dict[str, float] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def cost(self, model: str, usage: Usage) -> float:
        return usage_cost(self.pricing.models[model], usage)

    def add(self, kind: str, model: str, usage: Usage) -> float:
        """Dolicza koszt wywołań `kind` (np. `ideas`, `images`, `qa`); zwraca ich koszt."""
        amount = self.cost(model, usage)
        with self._lock:
            self.by_kind[kind] = round(self.by_kind.get(kind, 0.0) + amount, COST_DIGITS)
        return amount

    @property
    def spent(self) -> float:
        with self._lock:
            return round(sum(self.by_kind.values()), COST_DIGITS)

    @property
    def total(self) -> float:
        """Koszt książki: wcześniejsze uruchomienia i to."""
        return round(self.spent_before + self.spent, COST_DIGITS)

    def over_budget(self) -> bool:
        return self.total >= self.limit_usd
