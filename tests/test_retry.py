from __future__ import annotations

import pytest

from kdp_studio.providers.retry import RetryPolicy, call_with_retries


class Flaky:
    def __init__(self, failures: int) -> None:
        self.failures = failures
        self.calls = 0

    def __call__(self) -> str:
        self.calls += 1
        if self.calls <= self.failures:
            raise ConnectionError(f"failure {self.calls}")
        return "ok"


def test_succeeds_after_transient_failures() -> None:
    sleeps: list[float] = []
    flaky = Flaky(failures=2)
    assert call_with_retries(flaky, retry_after=lambda e: True, sleep=sleeps.append) == "ok"
    assert flaky.calls == 3
    assert sleeps == [1.0, 2.0]


def test_gives_up_after_max_attempts() -> None:
    sleeps: list[float] = []
    flaky = Flaky(failures=10)
    with pytest.raises(ConnectionError, match="failure 3"):
        call_with_retries(flaky, retry_after=lambda e: True, sleep=sleeps.append)
    assert flaky.calls == 3
    assert sleeps == [1.0, 2.0]


def test_permanent_error_is_not_retried() -> None:
    sleeps: list[float] = []
    flaky = Flaky(failures=10)
    with pytest.raises(ConnectionError, match="failure 1"):
        call_with_retries(flaky, retry_after=lambda e: False, sleep=sleeps.append)
    assert flaky.calls == 1
    assert sleeps == []


def test_server_suggested_delay_is_used() -> None:
    sleeps: list[float] = []
    call_with_retries(Flaky(failures=1), retry_after=lambda e: 7.5, sleep=sleeps.append)
    assert sleeps == [7.5]


@pytest.mark.parametrize(
    ("failed", "suggested", "expected"),
    [
        (1, None, 1.0),
        (2, None, 2.0),
        (3, None, 4.0),
        (10, None, 20.0),
        (1, 0.0, 0.0),
        (1, 99.0, 1.0),
    ],
)
def test_delay(failed: int, suggested: float | None, expected: float) -> None:
    assert RetryPolicy().delay(failed, suggested) == expected
