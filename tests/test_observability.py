"""NFR-09: logi strukturalne, pasek postępu i czasy kroków."""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel
from rich.console import Console

from kdp_studio.cli import ExitCode, main
from kdp_studio.observability import (
    JsonFormatter,
    LoggedImageProvider,
    LoggedTextProvider,
    LoggedVisionProvider,
    StepTimer,
    book_log,
    format_duration,
    log_event,
    progress_bar,
)
from kdp_studio.pipeline.output import LOG_FILE
from kdp_studio.providers.base import ImageRequest, ProviderError
from kdp_studio.providers.fake import FakeImageProvider, FakeTextProvider, FakeVisionProvider
from kdp_studio.providers.retry import call_with_retries
from tests.test_cli import fake_text_provider  # noqa: F401  (autouse: fałszywi dostawcy)

GENERATE = [
    "generate",
    "--theme",
    "Dinozaury",
    "--age",
    "przedszkole",
    "--style",
    "kawaii",
    "--pages",
    "3",
]
BOOK = Path("output/dinozaury_przedszkole_kawaii_letter")
log = logging.getLogger("kdp_studio.test")


def _events(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


@pytest.mark.parametrize(
    ("seconds", "text"),
    [
        (0.42, "0.4 s"),
        (9.94, "9.9 s"),
        (42.4, "42 s"),
        (59.6, "1 min 00 s"),
        (185, "3 min 05 s"),
        (3725, "1 h 02 min"),
    ],
)
def test_format_duration(seconds: float, text: str) -> None:
    assert format_duration(seconds) == text


def test_json_formatter_writes_event_and_fields() -> None:
    record = logging.makeLogRecord(
        {
            "name": "kdp_studio.x",
            "levelno": logging.INFO,
            "levelname": "INFO",
            "msg": "page_raw",
            "fields": {"page": 3, "issues": ["tekst"]},
        }
    )
    data = json.loads(JsonFormatter().format(record))
    assert data["event"] == "page_raw"
    assert (data["level"], data["logger"]) == ("info", "kdp_studio.x")
    assert (data["page"], data["issues"]) == (3, ["tekst"])
    assert data["ts"].endswith("+00:00")


def test_book_log_levels_and_cleanup(tmp_path: Path) -> None:
    with book_log(tmp_path, "info") as path:
        log_event(log, logging.INFO, "visible", n=1)
        log_event(log, logging.DEBUG, "hidden")
    log_event(log, logging.INFO, "after_close")
    with book_log(tmp_path, "debug"):
        log_event(log, logging.DEBUG, "detail")
    assert path == tmp_path / LOG_FILE
    assert [e["event"] for e in _events(path)] == ["visible", "detail"]
    assert _events(path)[0]["n"] == 1


def test_no_log_file_means_no_output(capsys: pytest.CaptureFixture[str]) -> None:
    log_event(log, logging.ERROR, "nowhere")
    assert capsys.readouterr() == ("", "")


def test_step_timer_records_steps_and_outcome(tmp_path: Path) -> None:
    ticks = iter([0.0, 1.0, 4.5, 5.0, 6.0, 10.0])
    timer = StepTimer(clock=lambda: next(ticks))
    with book_log(tmp_path, "info") as path:
        with timer.step("ideas", log):
            pass
        with pytest.raises(RuntimeError), timer.step("images", log):
            raise RuntimeError
    assert timer.steps == [("ideas", 3.5), ("images", 1.0)]
    assert timer.total == 10.0
    ends = [e for e in _events(path) if e["event"] == "step_end"]
    assert [(e["step"], e["duration_s"], e["outcome"]) for e in ends] == [
        ("ideas", 3.5, "ok"),
        ("images", 1.0, "error"),
    ]


def test_progress_bar_is_silent_outside_terminal(capsys: pytest.CaptureFixture[str]) -> None:
    with progress_bar("Grafiki", 3) as advance:
        for _ in range(3):
            advance()
    assert capsys.readouterr() == ("", "")


class _Answer(BaseModel):
    passed: bool = True
    issues: list[str] = []


def test_logged_providers_write_api_calls_at_debug(tmp_path: Path) -> None:
    text = LoggedTextProvider(FakeTextProvider([{}]))
    image = LoggedImageProvider(FakeImageProvider())
    vision = LoggedVisionProvider(FakeVisionProvider())
    assert (text.name, image.model, vision.model) == ("fake", "fake-image", "fake-vision")
    with book_log(tmp_path, "debug") as path:
        text.complete_json("s", "u", _Answer)
        image.generate(ImageRequest(prompt="Scene: a dragon.", aspect="3:4", quality="low"))
        vision.assess(b"png", "instr", _Answer)
    calls = [e for e in _events(path) if e["event"] == "api_call"]
    assert [c["kind"] for c in calls] == ["text", "image", "vision"]
    assert calls[0]["schema"] == "_Answer"
    assert calls[0]["input_tokens"] == 100
    assert calls[1]["prompt"] == "Scene: a dragon."
    assert calls[1]["quality"] == "low"
    assert calls[2]["input_tokens"] == 1000
    assert all(c["duration_s"] >= 0 for c in calls)


def test_logged_provider_error_is_warning_and_reraised(tmp_path: Path) -> None:
    def refuse(image_png: bytes, instructions: str) -> dict[str, Any]:
        raise ProviderError("odmowa modelu", fatal=False)

    vision = LoggedVisionProvider(FakeVisionProvider(refuse))
    with book_log(tmp_path, "info") as path, pytest.raises(ProviderError):
        vision.assess(b"png", "instr", _Answer)
    (event,) = _events(path)
    assert (event["event"], event["level"]) == ("api_error", "warning")
    assert (event["fatal"], event["error"]) == (False, "odmowa modelu")


def test_retry_logs_error_type_only(tmp_path: Path) -> None:
    attempts = iter([ConnectionError("sk-SECRET in message"), None])

    def flaky() -> str:
        error = next(attempts)
        if error is not None:
            raise error
        return "ok"

    with book_log(tmp_path, "info") as path:
        call_with_retries(flaky, retry_after=lambda e: True, sleep=lambda s: None)
    (event,) = _events(path)
    assert (event["event"], event["error"], event["attempt"]) == ("retry", "ConnectionError", 1)
    assert "sk-SECRET" not in path.read_text(encoding="utf-8")


# --- CLI -------------------------------------------------------------------------------------


def test_generate_reports_step_times_and_total(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(GENERATE) == ExitCode.OK
    out = capsys.readouterr().out
    for label in ("pomysły", "grafiki", "obróbka"):
        assert f"Czas kroku ({label}): " in out
    summary = [line for line in out.splitlines() if line.startswith("Czas: ")]
    assert len(summary) == 1
    assert "pomysły " in summary[0] and "grafiki " in summary[0] and "; razem " in summary[0]
    assert "[1/3] page_01: ok (" in out  # czas obróbki strony


def test_generate_writes_structured_log(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-SECRET-should-never-appear")
    assert main(GENERATE) == ExitCode.OK
    path = BOOK / LOG_FILE
    events = _events(path)
    names = [e["event"] for e in events]
    assert names[0] == "run_start" and names[-1] == "run_end"
    assert [e["step"] for e in events if e["event"] == "step_end"] == [
        "ideas",
        "images",
        "finalize",
    ]
    assert names.count("page_raw") == 3 and names.count("page_final") == 3
    assert "api_call" not in names  # debug tylko z --log-level debug
    end = events[-1]
    assert end["exit_code"] == 0
    assert set(end["steps"]) == {"ideas", "images", "finalize"}
    assert end["duration_s"] >= sum(end["steps"].values()) - 0.01
    assert "sk-SECRET" not in path.read_text(encoding="utf-8")


def test_log_level_debug_adds_api_calls() -> None:
    assert main([*GENERATE, "--log-level", "debug"]) == ExitCode.OK
    calls = [e for e in _events(BOOK / LOG_FILE) if e["event"] == "api_call"]
    assert {c["kind"] for c in calls} == {"text", "image"}
    assert sum(c["kind"] == "image" for c in calls) == 3


def test_steps_append_to_the_same_log(capsys: pytest.CaptureFixture[str]) -> None:
    ideas = ["ideas", *GENERATE[1:]]
    assert main(ideas) == ExitCode.OK
    assert main(["images", str(BOOK)]) == ExitCode.OK
    assert main(["finalize", str(BOOK)]) == ExitCode.OK
    out = capsys.readouterr().out
    assert "Czas: " not in out  # podsumowanie całości tylko w generate
    assert out.count("Czas kroku (") == 3
    steps = [e["step"] for e in _events(BOOK / LOG_FILE) if e["event"] == "step_end"]
    assert steps == ["ideas", "images", "finalize"]


def test_warnings_and_errors_reach_the_log() -> None:
    assert main(["ideas", *GENERATE[1:]]) == ExitCode.OK  # 3 grafiki < minimum KDP: ostrzeżenie
    assert main(["finalize", str(BOOK)]) == ExitCode.VALIDATION_ERROR  # brak surowych grafik
    events = _events(BOOK / LOG_FILE)
    levels = {(e["event"], e["level"]) for e in events}
    assert ("error", "error") in levels
    errors = [e["message"] for e in events if e["event"] == "error"]
    assert any("brak surowych grafik" in m for m in errors)


def test_bad_log_level_exits_1(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([*GENERATE, "--log-level", "trace"]) == ExitCode.VALIDATION_ERROR
    assert "--log-level: dozwolone info, debug (podano 'trace')" in capsys.readouterr().err
    assert not BOOK.exists()


def test_progress_bar_draws_in_terminal(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(Console, "is_terminal", property(lambda self: True))
    with progress_bar("Obróbka", 2) as advance:
        advance()
        advance()
    assert "Obróbka" in capsys.readouterr().err


def test_json_formatter_keeps_exception() -> None:
    try:
        raise ValueError("zła wartość")
    except ValueError:
        record = log.makeRecord(log.name, logging.ERROR, "f", 1, "crash", (), sys.exc_info())
    data = json.loads(JsonFormatter().format(record))
    assert data["event"] == "crash"
    assert "ValueError: zła wartość" in data["exception"]
