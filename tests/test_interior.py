"""FR-22: interior.pdf, druk jednostronny i dwustronny."""

from __future__ import annotations

import json
import re
import zlib
from typing import Any

import pytest
from PIL import Image

from kdp_studio import cli
from kdp_studio.cli import ExitCode, main
from kdp_studio.config import load_config
from kdp_studio.pipeline.interior import (
    INTERIOR_FILE,
    InteriorError,
    blank_run_problems,
    interior_layout,
    write_interior,
)
from kdp_studio.pipeline.manifest import InteriorInfo, Manifest, ManifestWriter
from kdp_studio.pipeline.pdf import bilevel_pdf, read_bilevel_pages
from tests.test_cli import (
    BASE,
    BOOK_DIR,
    fake_text_provider,  # noqa: F401  (autouse: fałszywi dostawcy)
)

ARG = str(BOOK_DIR)


def _manifest() -> Manifest:
    return ManifestWriter.load(BOOK_DIR).manifest


def _pages(count: int, *, blank_after: bool) -> list[str | None]:
    order: list[str | None] = []
    for i in range(1, count + 1):
        order.append(f"page_{i:02d}")
        if blank_after:
            order.append(None)
    return order


# --- Kolejność stron -----------------------------------------------------------------------


def test_single_sided_book_gets_interior_pdf(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([*BASE, "--pages", "12"]) == ExitCode.OK
    out = capsys.readouterr().out
    manifest = _manifest()
    interior = manifest.interior
    assert interior is not None
    assert interior.pages == manifest.layout.pages_in_book == 26
    assert interior.single_sided
    assert interior.order == ["front_title", "front_copyright", *_pages(12, blank_after=True)]
    assert f"Wnętrze do KDP: {BOOK_DIR / INTERIOR_FILE} (zapisano; 26 stron" in out
    pages = read_bilevel_pages((BOOK_DIR / INTERIOR_FILE).read_bytes())
    assert len(pages) == 26
    assert all((w, h) == pytest.approx((8.5, 11)) for w, h, _ in pages)
    assert [has_image for _, _, has_image in pages] == [name is not None for name in interior.order]


def test_double_sided_pads_to_even_page_count() -> None:
    assert main([*BASE, "--pages", "23", "--double-sided"]) == ExitCode.OK
    manifest = _manifest()
    assert not manifest.input.single_sided
    assert manifest.layout.pages_in_book == 26  # 2 + 23 = 25 → 26
    assert interior_layout(manifest) == [
        "front_title",
        "front_copyright",
        *_pages(23, blank_after=False),
        None,
    ]
    assert manifest.interior is not None and manifest.interior.pages == 26


def test_instructions_page_is_followed_by_a_blank_page() -> None:
    assert main([*BASE, "--pages", "11", "--instructions"]) == ExitCode.OK
    order = interior_layout(_manifest())
    assert order[:5] == ["front_title", "front_copyright", "front_instructions", None, "page_01"]
    assert len(order) == 4 + 22


def test_belongs_to_page_comes_first(monkeypatch: pytest.MonkeyPatch) -> None:
    assert main([*BASE, "--pages", "11"]) == ExitCode.OK
    manifest = _manifest()
    title = manifest.front_matter.title
    assert title is not None
    manifest.front_matter.belongs_to = title.model_copy(update={"name": "front_belongs_to"})
    assert interior_layout(manifest)[:2] == ["front_belongs_to", "front_copyright"]


def test_blank_page_runs_follow_kdp_limits() -> None:
    assert blank_run_problems(["a", None, None, None, None, "b", *[None] * 10]) == []
    assert blank_run_problems([None] * 5 + ["a"]) == [
        "strony 1–5: 5 pustych z rzędu (KDP pozwala na 4)"
    ]
    assert blank_run_problems(["a", *[None] * 11]) == [
        "strony 2–12: 11 pustych z rzędu (KDP pozwala na 10)"
    ]


# --- Plik PDF ------------------------------------------------------------------------------


def test_bilevel_pdf_keeps_black_and_white_pixels() -> None:
    image = Image.new("L", (16, 2), 255)
    image.putpixel((0, 0), 0)
    image.putpixel((15, 1), 0)
    data = bilevel_pdf([image, None], (1.0, 2.0))
    assert b"/Info" not in data and b"/Annots" not in data and b"/Outlines" not in data
    assert read_bilevel_pages(data) == [(1.0, 2.0, True), (1.0, 2.0, False)]
    match = re.search(rb"/BitsPerComponent 1 /Filter /FlateDecode /Length (\d+) >>\nstream\n", data)
    assert match is not None
    stream = data[match.end() : match.end() + int(match[1])]
    # 1 = biały; wiersz to 2 bajty, piksel 0 to najstarszy bit.
    assert zlib.decompress(stream) == bytes([0x7F, 0xFF, 0xFF, 0xFE])


def test_bilevel_pdf_rejects_color_pages() -> None:
    with pytest.raises(ValueError, match="trybie L"):
        bilevel_pdf([Image.new("RGB", (4, 4))], (1.0, 1.0))


def test_missing_page_removes_stale_interior() -> None:
    assert main([*BASE, "--pages", "12"]) == ExitCode.OK
    manifest = _manifest()
    manifest.pages[2].status = "failed"
    with pytest.raises(InteriorError) as exc:
        write_interior(BOOK_DIR, manifest)
    assert exc.value.errors == ["brakujące strony: page_03"]
    assert not (BOOK_DIR / INTERIOR_FILE).exists()


def test_unchanged_pages_keep_the_pdf(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([*BASE, "--pages", "12"]) == ExitCode.OK
    before = _manifest().interior
    capsys.readouterr()
    assert main(["finalize", ARG]) == ExitCode.OK
    assert "(aktualny; 26 stron" in capsys.readouterr().out
    assert _manifest().interior == before


def test_book_without_front_matter_gets_no_pdf(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([*BASE, "--pages", "12"]) == ExitCode.OK
    path = BOOK_DIR / "manifest.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["input"]["copyright_owner"] = None
    data["interior"] = None
    path.write_text(json.dumps(data), encoding="utf-8")
    (BOOK_DIR / INTERIOR_FILE).unlink()
    capsys.readouterr()
    assert main(["finalize", ARG]) == ExitCode.OK
    assert "nie ma stron wstępnych FR-23" in capsys.readouterr().out
    assert not (BOOK_DIR / INTERIOR_FILE).exists()


# --- Zmiana trybu w finalize ---------------------------------------------------------------


def _add_cover(pages_in_book: int) -> None:
    path = BOOK_DIR / "manifest.json"
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    data["cover"] = {
        "geometry": {"pages_in_book": pages_in_book},
        "front_page": "page_01",
        "thumbnails": [],
        "selection": "default",
        "title": "Dino Friends",
        "subtitle": "",
        "spine_text": False,
    }
    path.write_text(json.dumps(data), encoding="utf-8")


def test_finalize_switches_to_double_sided(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([*BASE, "--pages", "30"]) == ExitCode.OK
    _add_cover(62)
    capsys.readouterr()
    assert main(["finalize", ARG, "--double-sided"]) == ExitCode.OK
    captured = capsys.readouterr()
    assert "Tryb druku: dwustronny" in captured.out
    assert "Gotowe strony są aktualne" in captured.out  # grzbiet 0.375" bez zmian
    assert "okładka jest dla 62 stron, a książka ma 32" in captured.err
    manifest = _manifest()
    assert not manifest.input.single_sided
    assert manifest.layout.pages_in_book == 32
    assert manifest.interior is not None and manifest.interior.pages == 32
    assert len(read_bilevel_pages((BOOK_DIR / INTERIOR_FILE).read_bytes())) == 32


def test_print_mode_change_reprocesses_pages_when_margin_changes(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # 150 × 2 + 2 = 302 strony: grzbiet 0.625" większy niż margines formatu 0.5"
    assert main([*BASE, "--pages", "150"]) == ExitCode.OK
    assert _manifest().layout.margin_in == 0.625
    capsys.readouterr()
    assert main(["finalize", ARG, "--double-sided"]) == ExitCode.OK  # 152 strony: 0.5"
    assert "Obrabiam 150 stron" in capsys.readouterr().out
    layout = _manifest().layout
    assert (layout.pages_in_book, layout.margin_in) == (152, 0.5)


def test_too_thin_double_sided_book_gets_no_pdf(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([*BASE, "--pages", "12"]) == ExitCode.OK
    capsys.readouterr()
    assert main(["finalize", ARG, "--double-sided"]) == ExitCode.OK
    err = capsys.readouterr().err
    assert "książka będzie miała 14 stron" in err
    assert "interior.pdf nie powstał: 14 stron, a minimum KDP to 24" in err
    assert not (BOOK_DIR / INTERIOR_FILE).exists()
    assert _manifest().interior is None


def test_redo_refuses_print_mode() -> None:
    assert main(["ideas", ARG, "--redo", "idea_01", "--single-sided"]) == ExitCode.VALIDATION_ERROR


# --- Okładka -------------------------------------------------------------------------------


def test_cover_spine_uses_interior_page_count() -> None:
    assert main([*BASE, "--pages", "12"]) == ExitCode.OK
    manifest = _manifest()
    config = load_config()
    assert cli._cover_geometry(config, manifest).pages_in_book == 26
    manifest.interior = InteriorInfo(
        pages=28, single_sided=True, sha256="x", inputs_sha256="y", order=[]
    )
    assert cli._cover_geometry(config, manifest).pages_in_book == 28


def test_canva_points_to_interior_pdf() -> None:
    assert main([*BASE, "--pages", "23", "--double-sided"]) == ExitCode.OK
    text = (BOOK_DIR / "canva.md").read_text(encoding="utf-8")
    assert "**Gotowe wnętrze: `interior.pdf`** (26 stron, druk dwustronny)" in text
    assert "Grafiki idą jedna po drugiej" in text
    assert "| 25 | `page_23.png` |" in text
    assert "| 26 | pusta |" in text
    assert text.count("| pusta |") == 1
