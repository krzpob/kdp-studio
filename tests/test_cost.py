"""FR-10: koszt wywołań API z cennika i limit budżetu (--max-cost)."""

from __future__ import annotations

import json
import re
import threading
from pathlib import Path
from typing import Any, cast

import pytest

from kdp_studio import cli
from kdp_studio.cli import ExitCode, main
from kdp_studio.config import ApiPricing, AppConfig, ModelPrice
from kdp_studio.models import PagePrompt
from kdp_studio.pipeline.cost import CostTracker, format_usd, missing_prices, usage_cost
from kdp_studio.pipeline.output import LOG_FILE
from kdp_studio.pipeline.qa import QAChecker, QAIssue, QAResult
from kdp_studio.pipeline.worker import PageJob, PageWorker, ReservePool
from kdp_studio.providers.base import Usage
from kdp_studio.providers.fake import FakeImageProvider, FakeTextProvider
from tests.conftest import FAKE_IMAGE_COST
from tests.test_cli import fake_text_provider  # noqa: F401  (autouse: fałszywi dostawcy)

IDEAS = ["ideas", "--theme", "Dinozaury", "--age", "przedszkole", "--style", "kawaii"]
GENERATE = ["generate", *IDEAS[1:]]
BOOK = Path("output/dinozaury_przedszkole_kawaii_letter")
ARG = str(BOOK)
TEXT_CALL = 0.0002  # FakeTextProvider: 100 + 50 tokenów po $1 i $2 za 1M


@pytest.fixture
def images(monkeypatch: pytest.MonkeyPatch) -> FakeImageProvider:
    provider = FakeImageProvider()
    monkeypatch.setattr(cli, "create_image_provider", lambda name, model: provider)
    return provider


def _manifest() -> dict[str, Any]:
    data = json.loads((BOOK / "manifest.json").read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


# --- Cennik i licznik ---------------------------------------------------------------------


def test_usage_cost_per_million_tokens() -> None:
    price = ModelPrice(input_per_1m=5.0, output_per_1m=30.0)
    usage = Usage(input_tokens=200, output_tokens=1500)
    assert usage_cost(price, usage) == pytest.approx(0.046)
    assert usage_cost(price, Usage()) == 0


@pytest.mark.parametrize(
    ("amount", "text"), [(0, "$0.00"), (0.0042, "$0.0042"), (0.046, "$0.05"), (2.273, "$2.27")]
)
def test_format_usd(amount: float, text: str) -> None:
    assert format_usd(amount) == text


def test_missing_prices() -> None:
    pricing = ApiPricing(models={"a": ModelPrice(input_per_1m=1, output_per_1m=1)})
    assert missing_prices(pricing, ["a", "b", "b", "c"]) == ["b", "c"]


def test_repo_pricing_covers_default_models(repo_config: AppConfig) -> None:
    settings = repo_config.settings
    models = settings.models
    assert missing_prices(settings.api_pricing, [models.text, models.image, models.vision]) == []
    assert settings.api_pricing.source.startswith("https://")
    assert settings.max_cost_usd == 5.0


def test_cost_tracker_sums_kinds_and_checks_limit() -> None:
    pricing = ApiPricing(models={"m": ModelPrice(input_per_1m=0, output_per_1m=1_000_000)})
    costs = CostTracker(pricing, limit_usd=3.0)
    assert costs.add("images", "m", Usage(output_tokens=1)) == 1.0
    costs.add("qa", "m", Usage(output_tokens=1))
    assert not costs.over_budget()
    costs.add("images", "m", Usage(output_tokens=1))
    assert costs.by_kind == {"images": 2.0, "qa": 1.0}
    assert costs.spent == 3.0
    assert costs.over_budget()


# --- Worker -------------------------------------------------------------------------------


def _jobs(count: int) -> list[PageJob]:
    return [
        PageJob(page=i, name=f"page_{i:02d}", idea_id=f"idea_{i:02d}", prompt=f"prompt {i}")
        for i in range(1, count + 1)
    ]


def test_worker_stops_starting_pages_over_budget(tmp_path: Path) -> None:
    provider = FakeImageProvider()
    spent: list[int] = []
    worker = PageWorker(
        provider=provider,
        book_dir=tmp_path,
        aspect="3:4",
        quality="low",
        concurrency=1,
        over_budget=lambda: len(spent) >= 2,
        on_spent=lambda o: spent.append(o.page),
    )
    result = worker.run(_jobs(5))
    assert [o.page for o in result.outcomes] == [1, 2]
    assert result.budget_exceeded
    assert result.fatal_error is None
    assert len(provider.requests) == 2


def test_worker_without_limit_runs_everything(tmp_path: Path) -> None:
    worker = PageWorker(
        provider=FakeImageProvider(), book_dir=tmp_path, aspect="3:4", quality="low"
    )
    result = worker.run(_jobs(3))
    assert len(result.ok) == 3 and not result.budget_exceeded


class _RejectAll:
    """QA, które odrzuca każdą grafikę (FR-07)."""

    def __init__(self) -> None:
        self.lock = threading.Lock()

    def check(self, image: bytes, idea_id: str) -> tuple[QAResult, Usage]:
        return QAResult(passed=False, issues=[QAIssue(criterion="text", detail="napis")]), Usage()


def test_worker_takes_no_reserve_idea_over_budget(tmp_path: Path) -> None:
    provider = FakeImageProvider()
    worker = PageWorker(
        provider=provider,
        book_dir=tmp_path,
        aspect="3:4",
        quality="low",
        concurrency=1,
        qa=cast(QAChecker, _RejectAll()),
        reserve=ReservePool([PagePrompt(idea_id="idea_09", prompt="prompt 9")]),
        over_budget=lambda: len(provider.requests) >= 1,
    )
    result = worker.run(_jobs(1))
    (outcome,) = result.outcomes
    assert outcome.status == "failed"
    assert outcome.error is not None and "przekroczony limit kosztu" in outcome.error
    assert len(provider.requests) == 1  # bez grafiki z zapasowego pomysłu
    assert result.budget_exceeded


# --- CLI ----------------------------------------------------------------------------------


def test_generate_reports_and_records_costs(
    images: FakeImageProvider, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main([*GENERATE, "--pages", "3"]) == ExitCode.OK
    out = capsys.readouterr().out
    assert "Koszt pomysłów: $0.0004." in out  # generowanie + weryfikacja
    assert "Limit kosztu: $5.00 (wydano $0.0004)." in out
    assert re.search(r"\[1/3\] page_0\d: ok \([\d.]+ s\), \$0\.01\n", out)
    assert "Czas kroku (grafiki): " in out and ", koszt $0.03." in out
    assert "Strony: 3/3 gotowe, 0 nieudanych." in out
    assert "Koszt: pomysły $0.0004, grafiki $0.03; razem $0.03 z limitu $5.00." in out
    data = _manifest()
    assert data["ideas"]["cost_usd"] == pytest.approx(2 * TEXT_CALL)
    assert [p["cost_usd"] for p in data["pages"]] == [FAKE_IMAGE_COST] * 3
    assert data["cost_usd"] == pytest.approx(2 * TEXT_CALL + 3 * FAKE_IMAGE_COST)
    end = json.loads((BOOK / LOG_FILE).read_text(encoding="utf-8").splitlines()[-1])
    assert end["event"] == "run_end"
    assert end["cost_usd"] == pytest.approx(data["cost_usd"])
    assert end["max_cost_usd"] == 5.0


def test_images_stops_at_limit_and_resumes(
    images: FakeImageProvider, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main([*IDEAS, "--pages", "6"]) == ExitCode.OK
    args = ["images", ARG, "--concurrency", "1"]
    assert main([*args, "--max-cost", "0.02"]) == ExitCode.BUDGET_EXCEEDED
    err = capsys.readouterr().err
    assert "Błąd: przekroczony limit kosztu $0.02 (wydano $0.02), pominięto 4 strony" in err
    assert f"kdp-studio images {ARG} --max-cost" in err
    data = _manifest()
    assert data["status"] == "budget_exceeded"
    assert "przekroczony limit kosztu" in data["error"]
    assert [p["status"] for p in data["pages"]] == ["raw_ok"] * 2 + ["pending"] * 4
    assert len(images.requests) == 2

    assert main(args) == ExitCode.OK  # domyślny limit z settings.yaml
    data = _manifest()
    assert data["status"] == "raw_ready" and data["error"] is None
    assert len(images.requests) == 6
    assert data["cost_usd"] == pytest.approx(2 * TEXT_CALL + 6 * FAKE_IMAGE_COST)


def test_regenerated_page_cost_accumulates(images: FakeImageProvider) -> None:
    assert main([*IDEAS, "--pages", "3"]) == ExitCode.OK
    assert main(["images", ARG]) == ExitCode.OK
    data = _manifest()
    data["pages"][0]["action"] = "regenerate"
    (BOOK / "manifest.json").write_text(json.dumps(data), encoding="utf-8")
    assert main(["images", ARG]) == ExitCode.OK
    costs = [p["cost_usd"] for p in _manifest()["pages"]]
    assert costs == pytest.approx([2 * FAKE_IMAGE_COST, FAKE_IMAGE_COST, FAKE_IMAGE_COST])


def test_generate_stops_before_images_when_ideas_use_the_budget(
    images: FakeImageProvider, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main([*GENERATE, "--pages", "3", "--max-cost", "0.0001"]) == ExitCode.BUDGET_EXCEEDED
    out, err = capsys.readouterr()
    assert "już po pomysłach" in err
    assert images.requests == []
    assert _manifest()["status"] == "budget_exceeded"
    assert "Czas kroku (grafiki)" not in out
    assert "Koszt: pomysły $0.0004; razem $0.0004 z limitu $0.0001." in out


def test_generate_skips_finalize_after_budget_stop(images: FakeImageProvider) -> None:
    args = [*GENERATE, "--pages", "4", "--concurrency", "1", "--max-cost", "0.015"]
    assert main(args) == ExitCode.BUDGET_EXCEEDED
    assert len(images.requests) == 2
    assert not list(BOOK.glob("page_*.png"))
    assert _manifest()["status"] == "budget_exceeded"


def test_missing_price_fails_before_any_api_call(
    monkeypatch: pytest.MonkeyPatch,
    fake_text_provider: FakeTextProvider,  # noqa: F811
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        cli, "create_image_provider", lambda name, model: FakeImageProvider(model="unpriced")
    )
    assert main([*GENERATE, "--pages", "3"]) == ExitCode.VALIDATION_ERROR
    assert "brak ceny modelu unpriced w config/settings.yaml" in capsys.readouterr().err
    assert fake_text_provider.calls == []
    assert not BOOK.exists()


def test_max_cost_must_be_positive(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([*GENERATE, "--max-cost", "0"]) == ExitCode.VALIDATION_ERROR
    assert "--max-cost: musi być większy od 0 (podano 0)" in capsys.readouterr().err


def test_redo_adds_text_cost(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([*IDEAS, "--pages", "3"]) == ExitCode.OK
    before = _manifest()["ideas"]["cost_usd"]
    assert main(["ideas", ARG, "--redo", "idea_02"]) == ExitCode.OK
    data = _manifest()
    assert data["ideas"]["cost_usd"] > before
    assert data["cost_usd"] == pytest.approx(data["ideas"]["cost_usd"])
    assert "koszt $0.0" in capsys.readouterr().out


def test_debug_log_has_cost_per_call(images: FakeImageProvider) -> None:
    assert main([*GENERATE, "--pages", "3", "--log-level", "debug"]) == ExitCode.OK
    lines = (BOOK / LOG_FILE).read_text(encoding="utf-8").splitlines()
    calls = [e for e in map(json.loads, lines) if e["event"] == "api_call"]
    image_costs = [c["cost_usd"] for c in calls if c["kind"] == "image"]
    assert image_costs == [pytest.approx(FAKE_IMAGE_COST)] * 3
    assert all(c["cost_usd"] == pytest.approx(TEXT_CALL) for c in calls if c["kind"] == "text")
