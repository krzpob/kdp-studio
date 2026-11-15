from __future__ import annotations

import json
from pathlib import Path

import pytest

from kdp_studio.pipeline.canva import render_canva_md
from kdp_studio.pipeline.manifest import (
    AI_DISCLOSURE,
    ImageProviderInfo,
    ManifestIdeas,
    ManifestInput,
    ManifestLayout,
    ManifestProviders,
    ManifestWriter,
    ProviderInfo,
)
from kdp_studio.pipeline.worker import PageJob, PageOutcome
from kdp_studio.providers.base import Usage


def _jobs(count: int) -> list[PageJob]:
    return [
        PageJob(page=i, name=f"page_{i:02d}", idea_id=f"idea_{i:02d}", prompt=f"Scene: {i}.")
        for i in range(1, count + 1)
    ]


def _writer(tmp_path: Path, pages: int = 3, front: int = 2) -> ManifestWriter:
    return ManifestWriter.start(
        tmp_path,
        jobs=_jobs(pages),
        input=ManifestInput(
            theme="Świąteczne kotki",
            age="wczesnoszkolne",
            style="cozy",
            format="letter",
            pages=pages,
            front_matter_pages=front,
            concurrency=4,
            review_ideas=True,
        ),
        providers=ManifestProviders(
            text=ProviderInfo(provider="openai", model="gpt-6-luna"),
            image=ImageProviderInfo(
                provider="openai", model="gpt-image-2.6-flare", quality="medium", aspect="3:4"
            ),
        ),
        layout=ManifestLayout(
            trim_in=(8.5, 11),
            page_px=(2550, 3300),
            dpi=300,
            pages_in_book=pages * 2 + front,
            gutter_in=0.375,
            margin_in=0.5,
        ),
        ideas=ManifestIdeas(count=pages + 1, reserve=1, reviewed=True, usage=Usage(input_tokens=5)),
    )


def _ok(tmp_path: Path, page: int) -> PageOutcome:
    name = f"page_{page:02d}"
    return PageOutcome(
        page=page,
        name=name,
        idea_id=f"idea_{page:02d}",
        status="ok",
        duration_s=12.345,
        raw_file=tmp_path / "raw" / f"{name}.png",
        page_file=tmp_path / f"{name}.png",
        svg_file=tmp_path / "svg" / f"{name}.svg",
        usage=Usage(input_tokens=150, output_tokens=800),
    )


def _failed(page: int) -> PageOutcome:
    return PageOutcome(
        page=page,
        name=f"page_{page:02d}",
        idea_id=f"idea_{page:02d}",
        status="failed",
        duration_s=1.0,
        error="moderacja",
    )


def _read(writer: ManifestWriter) -> dict[str, object]:
    data = json.loads(writer.path.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def test_start_writes_pending_pages(tmp_path: Path) -> None:
    writer = _writer(tmp_path)
    data = _read(writer)
    assert writer.path == tmp_path / "manifest.json"
    assert data["status"] == "running"
    assert data["tool"] == "kdp-studio" and data["version"]
    assert data["input"]["theme"] == "Świąteczne kotki"  # type: ignore[index]
    assert data["layout"]["margin_in"] == 0.5  # type: ignore[index]
    assert data["layout"]["pages_in_book"] == 8  # type: ignore[index]
    assert data["providers"]["image"]["model"] == "gpt-image-2.6-flare"  # type: ignore[index]
    assert data["ai_disclosure"] == AI_DISCLOSURE
    pages = data["pages"]
    assert isinstance(pages, list)
    assert [(p["page"], p["status"], p["attempts"]) for p in pages] == [
        (1, "pending", 0),
        (2, "pending", 0),
        (3, "pending", 0),
    ]
    assert pages[0]["prompt"] == "Scene: 1."
    assert pages[0]["qa"] is None and pages[0]["cost_usd"] is None


def test_record_saves_after_every_page(tmp_path: Path) -> None:
    writer = _writer(tmp_path)
    writer.record(_ok(tmp_path, 2))
    page = _read(writer)["pages"][1]  # type: ignore[index]
    assert page["status"] == "ok"
    assert page["attempts"] == 1
    assert page["duration_s"] == 12.35
    assert page["usage"] == {"input_tokens": 150, "output_tokens": 800}
    assert page["files"] == {
        "png": "page_02.png",
        "svg": "svg/page_02.svg",
        "raw": "raw/page_02.png",
    }
    assert _read(writer)["pages"][0]["status"] == "pending"  # type: ignore[index]


@pytest.mark.parametrize(
    ("outcomes", "fatal", "status"),
    [
        ([1, 2, 3], None, "completed"),
        ([1, -2, 3], None, "partial"),
        ([1], "brak środków", "failed"),
    ],
)
def test_finish_status(tmp_path: Path, outcomes: list[int], fatal: str | None, status: str) -> None:
    writer = _writer(tmp_path)
    for page in outcomes:
        writer.record(_ok(tmp_path, page) if page > 0 else _failed(-page))
    assert writer.finish(fatal) == status
    data = _read(writer)
    assert data["status"] == status
    assert data["error"] == fatal


def test_no_api_key_in_manifest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-SECRET-should-never-appear")
    writer = _writer(tmp_path)
    writer.record(_ok(tmp_path, 1))
    writer.finish()
    assert "sk-SECRET" not in writer.path.read_text(encoding="utf-8")


# --- canva.md ------------------------------------------------------------------------


def test_canva_md_follows_spec(tmp_path: Path) -> None:
    writer = _writer(tmp_path, pages=3)
    for page in (1, 2, 3):
        writer.record(_ok(tmp_path, page))
    text = render_canva_md(writer.manifest, "Cozy Christmas Kittens")
    assert text.startswith("# Składanie w Canvie: Cozy Christmas Kittens\n")
    assert "3 grafiki, 8 stron książki (druk jednostronny), format letter 8.5 × 11 in." in text
    assert "1. Utwórz projekt o wymiarach własnych **8.5 × 11 in**." in text
    assert "2. Strony wstępne: **2**" in text
    assert "`page_01.png` … `page_03.png` naraz" in text
    assert "(0.5 in z każdej strony, zgodnie z tabelą KDP dla 8 stron)" in text
    assert "Razem **8** stron." in text
    assert "**PDF Print** z zaznaczonym **Flatten PDF**" in text
    assert f"7. {AI_DISCLOSURE}" in text
    assert "Uwaga" not in text
    order = [line for line in text.splitlines() if line.startswith("| ") and "Strona" not in line]
    assert order == [
        "| 1–2 | strony wstępne |",
        "| 3 | `page_01.png` |",
        "| 4 | pusta |",
        "| 5 | `page_02.png` |",
        "| 6 | pusta |",
        "| 7 | `page_03.png` |",
        "| 8 | pusta |",
    ]


def test_canva_md_warns_about_missing_pages(tmp_path: Path) -> None:
    writer = _writer(tmp_path, pages=3, front=1)
    writer.record(_ok(tmp_path, 1))
    writer.record(_failed(2))
    text = render_canva_md(writer.manifest, "T")
    assert "> **Uwaga:** brakuje 2 stron: `page_02.png`, `page_03.png`." in text
    assert "| 1 | strona wstępna |" in text
