"""NFR-09: logi strukturalne, pasek postępu i czasy kroków.

Konsola zostaje czytelna dla człowieka (komunikaty po polsku). Logi strukturalne idą do
pliku `kdp-studio.log` w katalogu książki, po jednym obiekcie JSON w wierszu, dopisywane przy
każdym kroku, więc plik zbiera całą historię książki. Poziom `info` zapisuje kroki, strony
i ich czasy; `debug` dodatkowo każde wywołanie API (czas, tokeny) i prompty.

Plik dostaje tylko logger `kdp_studio`: logi bibliotek (SDK dostawców, HTTP) do niego nie
trafiają, więc nie wycieknie z nich klucz API (NFR-10).
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, get_args

from rich.console import Console
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)

from kdp_studio.config import LogLevel
from kdp_studio.pipeline.output import LOG_FILE
from kdp_studio.providers.base import (
    ImageProvider,
    ImageRequest,
    ImageResult,
    ProviderError,
    SchemaT,
    TextProvider,
    Usage,
    VisionProvider,
)

ROOT_LOGGER = "kdp_studio"
LOG_LEVELS: tuple[str, ...] = get_args(LogLevel)

# Bez pliku logu (np. błąd walidacji przed blokadą) zdarzenia przepadają, zamiast trafiać
# przez logging.lastResort na stderr obok komunikatów konsoli.
logging.getLogger(ROOT_LOGGER).addHandler(logging.NullHandler())

_RESERVED = set(vars(logging.makeLogRecord({})))


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


def log_event(logger: logging.Logger, level: int, event: str, **fields: Any) -> None:
    """Zdarzenie z polami, które formatter JSON zapisze obok `event`."""
    logger.log(level, event, extra={"fields": fields})


class JsonFormatter(logging.Formatter):
    """Jeden obiekt JSON na wiersz: czas UTC, poziom, logger, zdarzenie i jego pola."""

    def format(self, record: logging.LogRecord) -> str:
        data: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname.lower(),
            "logger": record.name,
            "event": record.getMessage(),
        }
        fields = getattr(record, "fields", None)
        if isinstance(fields, dict):
            data.update(fields)
        data.update({k: v for k, v in vars(record).items() if k not in _RESERVED | {"fields"}})
        if record.exc_info:
            data["exception"] = self.formatException(record.exc_info)
        return json.dumps(data, ensure_ascii=False, default=str)


@contextmanager
def book_log(book_dir: Path, level: LogLevel) -> Iterator[Path]:
    """Dopisuje logi pakietu do `<katalog książki>/kdp-studio.log` na czas kroku."""
    path = book_dir / LOG_FILE
    handler = logging.FileHandler(path, encoding="utf-8")
    handler.setFormatter(JsonFormatter())
    logger = logging.getLogger(ROOT_LOGGER)
    previous = logger.level
    logger.setLevel(logging.DEBUG if level == "debug" else logging.INFO)
    logger.addHandler(handler)
    try:
        yield path
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous)
        handler.close()


# --- Czas ----------------------------------------------------------------------------------


def format_duration(seconds: float) -> str:
    """Czas dla człowieka: `0.4 s`, `42 s`, `3 min 05 s`, `1 h 02 min`."""
    if seconds < 10:
        return f"{seconds:.1f} s"
    total = round(seconds)
    if total < 60:
        return f"{total} s"
    minutes, secs = divmod(total, 60)
    if minutes < 60:
        return f"{minutes} min {secs:02d} s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours} h {minutes:02d} min"


@dataclass
class StepTimer:
    """Czasy kolejnych kroków (FR-17) i całości, do podsumowania i logu."""

    clock: Callable[[], float] = time.monotonic
    steps: list[tuple[str, float]] = field(default_factory=list)
    started: float = field(init=False)

    def __post_init__(self) -> None:
        self.started = self.clock()

    @contextmanager
    def step(self, name: str, logger: logging.Logger) -> Iterator[None]:
        log_event(logger, logging.INFO, "step_start", step=name)
        start = self.clock()
        outcome = "error"
        try:
            yield
            outcome = "ok"
        finally:
            duration = self.clock() - start
            self.steps.append((name, duration))
            log_event(
                logger,
                logging.INFO,
                "step_end",
                step=name,
                duration_s=round(duration, 2),
                outcome=outcome,
            )

    @property
    def total(self) -> float:
        return self.clock() - self.started


# --- Pasek postępu ------------------------------------------------------------------------


@contextmanager
def progress_bar(label: str, total: int) -> Iterator[Callable[[], None]]:
    """Pasek postępu na stderr; zwraca funkcję `advance()`.

    Rysowany tylko w terminalu. Komunikaty wypisywane w trakcie pojawiają się nad paskiem,
    a po zakończeniu pasek znika (podsumowanie kroku i tak podaje wynik). Poza terminalem
    (przekierowanie do pliku, CI, testy) nie wypisuje nic.
    """
    console = Console(stderr=True)
    if not console.is_terminal:
        yield lambda: None
        return
    bar = Progress(
        TextColumn("{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
        TextColumn("zostało"),
        TimeRemainingColumn(),
        console=console,
        transient=True,
    )
    with bar:
        task = bar.add_task(label, total=total)
        yield lambda: bar.advance(task)


# --- Wywołania API w logu (debug) ------------------------------------------------------------


def _usage_fields(usage: Usage) -> dict[str, int]:
    return {"input_tokens": usage.input_tokens, "output_tokens": usage.output_tokens}


@contextmanager
def _api_call(
    logger: logging.Logger, kind: str, provider: str, model: str, **fields: Any
) -> Iterator[dict[str, Any]]:
    """Loguje jedno wywołanie API: czas, a po błędzie typ błędu i jego zasięg.

    Komunikat ProviderError jest już bezpieczny (adapter usuwa z niego treść błędu 401).
    """
    result: dict[str, Any] = {}
    start = time.monotonic()
    try:
        yield result
    except ProviderError as e:
        log_event(
            logger,
            logging.WARNING,
            "api_error",
            kind=kind,
            provider=provider,
            model=model,
            duration_s=round(time.monotonic() - start, 2),
            fatal=e.fatal,
            error=str(e),
            **fields,
        )
        raise
    log_event(
        logger,
        logging.DEBUG,
        "api_call",
        kind=kind,
        provider=provider,
        model=model,
        duration_s=round(time.monotonic() - start, 2),
        **fields,
        **result,
    )


_api_log = logging.getLogger(f"{ROOT_LOGGER}.api")


class LoggedTextProvider:
    """TextProvider, który zapisuje w logu każde wywołanie (debug) i błąd (warning)."""

    def __init__(self, inner: TextProvider) -> None:
        self.inner = inner
        self.name = inner.name
        self.model = inner.model

    def complete_json(self, system: str, user: str, schema: type[SchemaT]) -> tuple[SchemaT, Usage]:
        with _api_call(_api_log, "text", self.name, self.model, schema=schema.__name__) as out:
            parsed, usage = self.inner.complete_json(system, user, schema)
            out.update(_usage_fields(usage))
        return parsed, usage


class LoggedImageProvider:
    """ImageProvider z logiem wywołań; prompt trafia do logu na poziomie debug."""

    def __init__(self, inner: ImageProvider) -> None:
        self.inner = inner
        self.name = inner.name
        self.model = inner.model

    def supported_aspects(self) -> list[str]:
        return self.inner.supported_aspects()

    def generate(self, req: ImageRequest) -> ImageResult:
        with _api_call(
            _api_log,
            "image",
            self.name,
            self.model,
            aspect=req.aspect,
            quality=req.quality,
            prompt=req.prompt,
        ) as out:
            result = self.inner.generate(req)
            out.update(_usage_fields(result.usage), width=result.width, height=result.height)
        return result


class LoggedVisionProvider:
    """VisionProvider z logiem wywołań."""

    def __init__(self, inner: VisionProvider) -> None:
        self.inner = inner
        self.name = inner.name
        self.model = inner.model

    def assess(
        self, image_png: bytes, instructions: str, schema: type[SchemaT]
    ) -> tuple[SchemaT, Usage]:
        with _api_call(_api_log, "vision", self.name, self.model, schema=schema.__name__) as out:
            parsed, usage = self.inner.assess(image_png, instructions, schema)
            out.update(_usage_fields(usage))
        return parsed, usage
