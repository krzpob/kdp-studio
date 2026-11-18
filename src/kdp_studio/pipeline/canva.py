"""FR-08, §10.1: `canva.md`, instrukcja składania tej konkretnej książki w Canvie (D9).

Od FR-22 wnętrze składa program (`interior.pdf`); Canva zostaje ręczną drogą."""

from __future__ import annotations

from kdp_studio.pipeline.belongs_to import FRONT_NAME
from kdp_studio.pipeline.interior import INTERIOR_FILE, interior_layout
from kdp_studio.pipeline.manifest import AI_DISCLOSURE, Manifest
from kdp_studio.validation import plural

CANVA_FILE = "canva.md"


def _inches(value: float) -> str:
    return f"{value:g}"


def belongs_to_position(manifest: Manifest) -> int | None:
    """Numer strony wstępnej dla `front_belongs_to.png` (FR-14): druga, po tytułowej."""
    if manifest.front_matter.belongs_to is None or manifest.input.front_matter_pages == 0:
        return None
    return min(2, manifest.input.front_matter_pages)


def _fr23(manifest: Manifest) -> bool:
    """Książka ze stronami wstępnymi FR-23 (ma właściciela praw autorskich)."""
    return manifest.input.copyright_owner is not None


def _page_order(manifest: Manifest) -> list[str]:
    """Kolejność stron książki: strony wstępne, potem grafika i pusta strona (D8)."""
    if _fr23(manifest):
        return [
            f"| {number} | `{name}.png` |" if name else f"| {number} | pusta |"
            for number, name in enumerate(interior_layout(manifest), start=1)
        ]
    front = manifest.input.front_matter_pages
    belongs = belongs_to_position(manifest)
    lines = []
    for number in range(1, front + 1):
        if number == belongs:
            lines.append(f"| {number} | `{FRONT_NAME}.png` |")
        elif belongs is None and number == 1:
            lines.append(
                f"| 1–{front} | strony wstępne |" if front > 1 else "| 1 | strona wstępna |"
            )
        elif belongs is not None:
            lines.append(f"| {number} | strona wstępna |")
    number = front
    for page in manifest.pages:
        number += 1
        lines.append(f"| {number} | `{page.name}.png` |")
        if manifest.input.single_sided:
            number += 1
            lines.append(f"| {number} | pusta |")
    if number % 2:
        lines.append(f"| {number + 1} | pusta |")
    return lines


def render_canva_md(manifest: Manifest, title: str) -> str:
    """Treść `canva.md` według spec §10.1, z wartościami tej książki."""
    layout = manifest.layout
    width, height = layout.trim_in
    names = [p.name for p in manifest.pages]
    missing = [p.name for p in manifest.pages if p.status != "ok"]
    belongs = belongs_to_position(manifest)
    for front_page in reversed(manifest.front_matter.pages()):
        if front_page.status != "ok":
            missing.insert(0, front_page.name)
    count = len(names)
    front = manifest.input.front_matter_pages
    pages_in_book = layout.pages_in_book

    single = manifest.input.single_sided
    mode = "druk jednostronny" if single else "druk dwustronny"
    lines = [
        f"# Składanie w Canvie: {title}",
        "",
        f"Książka: {plural(count, 'grafika', 'grafiki', 'grafik')}, "
        f"{plural(pages_in_book, 'strona', 'strony', 'stron')} książki "
        f"({mode}), format {manifest.input.format} "
        f"{_inches(width)} × {_inches(height)} in.",
        "",
    ]
    if manifest.interior is not None:
        lines += [
            f"**Gotowe wnętrze: `{INTERIOR_FILE}`** "
            f"({plural(manifest.interior.pages, 'strona', 'strony', 'stron')}, {mode}). "
            "Wgraj je w KDP jako manuscript; kroki niżej to ręczna droga, gdyby trzeba było "
            "coś poprawić w Canvie.",
            "",
        ]
    elif _fr23(manifest):
        lines += [
            f"`{INTERIOR_FILE}` jeszcze nie powstał: finalize składa go, gdy wszystkie strony "
            "są gotowe. Do tego czasu możesz złożyć wnętrze w Canvie.",
            "",
        ]
    if missing:
        lines += [
            f"> **Uwaga:** brakuje {plural(len(missing), 'strony', 'stron', 'stron')}: "
            f"{', '.join(f'`{n}.png`' for n in missing)}. Wygeneruj je ponownie przed składaniem.",
            "",
        ]
    lines += [
        "## Kroki",
        "",
        f"1. Utwórz projekt o wymiarach własnych **{_inches(width)} × {_inches(height)} in**.",
        (
            f"2. Strony wstępne: **{front}**, gotowe pliki `front_*.png` (strona 1, prawa "
            "autorskie"
            + (", instrukcja i pusta strona za nią" if front >= 4 else "")
            + "). Wstaw je w kolejności z tabeli niżej, nie alfabetycznej, i rozciągnij na "
            "całą stronę jak grafiki."
            if _fr23(manifest)
            else f"2. Strony wstępne: **{front}** (domyślnie strona tytułowa i „This book "
            "belongs to…”)."
            + (
                f" Gotowa strona „This book belongs to…” to `{FRONT_NAME}.png`: wstaw ją jako "
                f"stronę wstępną nr {belongs}."
                if belongs is not None
                else ""
            )
        ),
        f"3. Prześlij wszystkie pliki `{names[0]}.png` … `{names[-1]}.png` naraz "
        "(kolejność alfabetyczna to kolejność stron)"
        + (f"; `{FRONT_NAME}.png` będzie pierwszy na liście." if belongs is not None else "."),
        "4. Każdą grafikę wstaw na osobną stronę i rozciągnij na całą stronę. Marginesy "
        f"({_inches(layout.margin_in)} in z każdej strony, zgodnie z tabelą KDP dla "
        f"{pages_in_book} stron) są już w pliku, więc niczego nie skaluj ani nie przycinaj.",
        (
            "5. Po każdej grafice dodaj pustą stronę (druk jednostronny). "
            if single
            else "5. Grafiki idą jedna po drugiej, bez pustych stron (druk dwustronny); "
            "przy nieparzystej liczbie stron dodaj pustą na końcu. "
        )
        + f"Razem **{pages_in_book}** stron.",
        "6. Pobierz jako **PDF Print** z zaznaczonym **Flatten PDF**. Bez spadu (bleed).",
        f"7. {AI_DISCLOSURE}",
        "",
        "## Kolejność stron",
        "",
        "| Strona | Zawartość |",
        "|---|---|",
        *_page_order(manifest),
        "",
    ]
    return "\n".join(lines)
