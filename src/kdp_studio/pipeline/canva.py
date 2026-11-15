"""FR-08, §10.1: `canva.md`, instrukcja składania tej konkretnej książki w Canvie (D9)."""

from __future__ import annotations

from kdp_studio.pipeline.manifest import AI_DISCLOSURE, Manifest
from kdp_studio.validation import plural

CANVA_FILE = "canva.md"


def _inches(value: float) -> str:
    return f"{value:g}"


def _page_order(manifest: Manifest) -> list[str]:
    """Kolejność stron książki: strony wstępne, potem grafika i pusta strona (D8)."""
    front = manifest.input.front_matter_pages
    lines = []
    if front:
        lines.append(f"| 1–{front} | strony wstępne |" if front > 1 else "| 1 | strona wstępna |")
    number = front
    for page in manifest.pages:
        number += 2
        lines.append(f"| {number - 1} | `{page.name}.png` |")
        lines.append(f"| {number} | pusta |")
    return lines


def render_canva_md(manifest: Manifest, title: str) -> str:
    """Treść `canva.md` według spec §10.1, z wartościami tej książki."""
    layout = manifest.layout
    width, height = layout.trim_in
    names = [p.name for p in manifest.pages]
    missing = [p.name for p in manifest.pages if p.status != "ok"]
    count = len(names)
    front = manifest.input.front_matter_pages
    pages_in_book = layout.pages_in_book

    lines = [
        f"# Składanie w Canvie: {title}",
        "",
        f"Książka: {plural(count, 'grafika', 'grafiki', 'grafik')}, "
        f"{plural(pages_in_book, 'strona', 'strony', 'stron')} książki "
        f"(druk jednostronny), format {manifest.input.format} "
        f"{_inches(width)} × {_inches(height)} in.",
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
        f"2. Strony wstępne: **{front}** (domyślnie strona tytułowa i „This book belongs to…”).",
        f"3. Prześlij wszystkie pliki `{names[0]}.png` … `{names[-1]}.png` naraz "
        "(kolejność alfabetyczna to kolejność stron).",
        "4. Każdą grafikę wstaw na osobną stronę i rozciągnij na całą stronę. Marginesy "
        f"({_inches(layout.margin_in)} in z każdej strony, zgodnie z tabelą KDP dla "
        f"{pages_in_book} stron) są już w pliku, więc niczego nie skaluj ani nie przycinaj.",
        "5. Po każdej grafice dodaj pustą stronę (druk jednostronny). "
        f"Razem **{pages_in_book}** stron.",
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
