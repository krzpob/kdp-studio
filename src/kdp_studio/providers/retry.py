"""Ponawianie wywołań API z wykładniczym odczekiwaniem (FR-05, NFR-04).

Niezależne od dostawcy: adapter decyduje, które błędy są przejściowe.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass

DEFAULT_MAX_ATTEMPTS = 3  # spec FR-05: maks. 3 próby na wywołanie

_log = logging.getLogger(__name__)


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = DEFAULT_MAX_ATTEMPTS
    initial_delay_s: float = 1.0
    max_delay_s: float = 20.0

    def delay(self, failed_attempts: int, suggested_s: float | None = None) -> float:
        """Opóźnienie po `failed_attempts` nieudanych próbach (1, 2, …)."""
        if suggested_s is not None and 0 <= suggested_s <= self.max_delay_s:
            return suggested_s
        return float(min(self.initial_delay_s * 2 ** (failed_attempts - 1), self.max_delay_s))


def call_with_retries[T](
    call: Callable[[], T],
    *,
    retry_after: Callable[[Exception], float | bool],
    policy: RetryPolicy = RetryPolicy(),
    sleep: Callable[[float], None] = time.sleep,
) -> T:
    """Wywołuje `call`, ponawiając błędy, dla których `retry_after(e)` nie zwraca False.

    `retry_after` zwraca False (nie ponawiaj), True (ponów z backoffem) albo liczbę
    sekund sugerowaną przez serwer (np. nagłówek Retry-After).
    """
    for attempt in range(1, policy.max_attempts + 1):
        try:
            return call()
        except Exception as e:
            decision = retry_after(e)
            if decision is False or attempt == policy.max_attempts:
                raise
            suggested = None if isinstance(decision, bool) else decision
            delay = policy.delay(attempt, suggested)
            # Tylko typ błędu: treść błędu dostawcy bywa niebezpieczna (NFR-10).
            _log.warning(
                "retry",
                extra={"fields": {"attempt": attempt, "delay_s": delay, "error": type(e).__name__}},
            )
            sleep(delay)
    raise AssertionError("unreachable")  # pragma: no cover
