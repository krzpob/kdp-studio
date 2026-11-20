"""Opis do KDP (FR-03): części od modelu, fakty z manifestu i HTML składany przez program."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from kdp_studio.cli import ExitCode, main
from kdp_studio.config import AppConfig
from kdp_studio.models import BookMetadata
from kdp_studio.pipeline.front_matter import front_texts
from kdp_studio.pipeline.listing import (
    BookFacts,
    content_issues,
    fact_lines,
    plain_text,
    render_description,
    sanitize_inline,
)
from tests.test_cli import BASE, BOOK_DIR, fake_text_provider  # noqa: F401  (autouse)

FACTS = BookFacts(
    pages=30,
    single_sided=True,
    trim_in=(8.5, 8.5),
    first_page="belongs-to",
    instructions=True,
    adults=False,
)


def _book(**overrides: Any) -> BookMetadata:
    data: dict[str, Any] = {
        "title": "Christmas Kittens",
        "subtitle": "A Coloring Book for Kids Ages 6–8",
        "description": "Cozy kittens. Thirty scenes.",
        "keywords": [],
        "headline": "Cozy <b>Christmas</b> kittens",
        "about": "Kittens bake, skate and decorate the tree.",
        "benefits": ["Calm, screen-free time", "Builds fine motor skills"],
        "closing": "A sweet gift for young cat lovers.",
        **overrides,
    }
    return BookMetadata(**data)


# --- Znaczniki od modelu --------------------------------------------------------------


def test_sanitize_keeps_only_inline_tags() -> None:
    text = 'Big <b>dinos</b> & <i>more</i><script>x</script> <a href="u">link</a> <h4>H</h4>'
    clean, problems = sanitize_inline(text)
    assert clean == "Big <b>dinos</b> &amp; <i>more</i>x link H"
    assert problems == [
        "niedozwolony znacznik <script>",
        "niedozwolony znacznik </script>",
        "niedozwolony znacznik <a>",
        "niedozwolony znacznik </a>",
        "niedozwolony znacznik <h4>",
        "niedozwolony znacznik </h4>",
    ]


def test_sanitize_closes_and_drops_attributes() -> None:
    assert sanitize_inline('<b class="x">bold <i>both</b> plain')[0] == (
        "<b>bold <i>both</i></b> plain"
    )
    clean, problems = sanitize_inline("<u>open </i>stray")
    assert clean == "<u>open stray</u>"
    assert problems == ["</i> bez otwarcia", "<u> bez zamknięcia"]
    assert sanitize_inline('<b class="x">a</b>')[1] == ["atrybuty w <b>"]


def test_plain_text() -> None:
    assert plain_text("Big <b>dinos</b> &amp; more") == "Big dinos & more"


@pytest.mark.parametrize(
    ("text", "issue"),
    [
        ("Fun for kids 🎄", "emoji"),
        ("Visit www.example.com", "adres strony albo e-mail"),
        ("Write to me@example.com", "adres strony albo e-mail"),
        ("Only $9.99", "cena"),
        ("Please leave a review", "słowa sprzedażowe albo prośba o recenzję: review"),
        ("Zostaw opinię!", "słowa sprzedażowe albo prośba o recenzję: opinię"),
    ],
)
def test_content_issues(text: str, issue: str) -> None:
    assert content_issues([text]) == [issue]


def test_screen_free_is_not_a_sales_word() -> None:
    assert content_issues(["Calm, screen-free time", "A gift-free idea"]) == []


# --- Fakty i składanie ------------------------------------------------------------------


def test_fact_lines_follow_the_book(repo_config: AppConfig) -> None:
    en = front_texts(repo_config, "US").listing
    assert fact_lines(FACTS, en) == [
        "30 single-sided coloring pages, so markers won't bleed onto the next picture",
        "Large 8.5 × 8.5 in pages, printed on white paper",
        'A "This book belongs to" page to sign',
        "A tips page where you can test your crayons and markers first",
    ]
    double = BookFacts(30, False, (8.5, 11.0), "title", False, False)
    assert fact_lines(double, en) == [
        "30 coloring pages",
        "Large 8.5 × 11 in pages, printed on white paper",
        "A title page to color",
    ]
    pl = front_texts(repo_config, "PL").listing
    assert fact_lines(FACTS, pl)[1] == "Duży format 21,6 × 21,6 cm, biały papier"


def test_uk_spelling_in_facts(repo_config: AppConfig) -> None:
    uk = front_texts(repo_config, "UK").listing
    assert fact_lines(FACTS, uk)[0].startswith("30 single-sided colouring pages")


def test_render_description_structure(repo_config: AppConfig) -> None:
    html = render_description(_book(), FACTS, front_texts(repo_config, "US"))
    assert html.splitlines() == [
        "<b>Christmas Kittens</b>",
        "<h4>Cozy <b>Christmas</b> kittens</h4>",
        "<p>Kittens bake, skate and decorate the tree.</p>",
        "<ul><li>30 single-sided coloring pages, so markers won't bleed onto the next "
        "picture</li><li>Large 8.5 × 8.5 in pages, printed on white paper</li>"
        '<li>A "This book belongs to" page to sign</li>'
        "<li>A tips page where you can test your crayons and markers first</li></ul>",
        "<h5>Why kids and parents love it</h5>",
        "<ul><li>Calm, screen-free time</li><li>Builds fine motor skills</li></ul>",
        "<p>A sweet gift for young cat lovers.</p>",
    ]


def test_render_description_for_adults_and_without_texts(repo_config: AppConfig) -> None:
    adults = BookFacts(30, True, (8.5, 11.0), None, False, True)
    html = render_description(_book(), adults, front_texts(repo_config, "US"))
    assert "<h5>Why you'll love it</h5>" in html
    bare = render_description(_book(), FACTS, None)
    assert "<li>30 single-sided" not in bare and "<h5>" not in bare
    assert "<ul><li>Calm, screen-free time</li>" in bare


def test_old_book_uses_plain_description(repo_config: AppConfig) -> None:
    old = _book(headline=None, about=None, benefits=[], closing=None, description="A & B")
    html = render_description(old, FACTS, front_texts(repo_config, "US"))
    assert html.splitlines()[:2] == ["<b>Christmas Kittens</b>", "<p>A &amp; B</p>"]
    assert "<h4>" not in html and "<h5>" not in html


# --- CLI --------------------------------------------------------------------------------


def _manifest() -> dict[str, Any]:
    data: dict[str, Any] = json.loads((BOOK_DIR / "manifest.json").read_text(encoding="utf-8"))
    return data


def test_generate_writes_description(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([*BASE, "--pages", "12"]) == ExitCode.OK
    html = (BOOK_DIR / "description.html").read_text(encoding="utf-8")
    assert html.startswith("<b>Dino Friends</b>\n<h4>Big, friendly <b>dinosaurs</b>")
    assert "12 single-sided coloring pages" in html
    info = _manifest()["description"]
    assert info["chars"] == len(html.strip()) and info["language"] == "en"
    assert "Opis do KDP:" in capsys.readouterr().out
    ideas = json.loads((BOOK_DIR / "ideas.json").read_text(encoding="utf-8"))
    assert ideas["book"]["description"] == (
        "Big, friendly dinosaurs for little hands Simple dinosaur scenes with thick lines to color."
    )


def test_finalize_rebuilds_description_after_sided_change() -> None:
    assert main([*BASE, "--pages", "12"]) == ExitCode.OK
    assert main(["finalize", str(BOOK_DIR), "--double-sided"]) == ExitCode.OK
    html = (BOOK_DIR / "description.html").read_text(encoding="utf-8")
    assert "<li>12 coloring pages</li>" in html and "single-sided" not in html


def test_finalize_writes_description_for_an_old_book(tmp_path: Path) -> None:
    assert main([*BASE, "--pages", "12"]) == ExitCode.OK
    path = BOOK_DIR / "ideas.json"
    ideas = json.loads(path.read_text(encoding="utf-8"))
    for key in ("headline", "about", "benefits", "closing"):
        ideas["book"].pop(key)
    path.write_text(json.dumps(ideas), encoding="utf-8")
    (BOOK_DIR / "description.html").unlink()
    assert main(["finalize", str(BOOK_DIR)]) == ExitCode.OK
    html = (BOOK_DIR / "description.html").read_text(encoding="utf-8")
    assert "<p>Big, friendly dinosaurs for little hands Simple" in html
