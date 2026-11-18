"""FR-22: wnętrze książki `interior.pdf` w kroku 3, bez wywołań API.

Kolejność stron: strony wstępne FR-23 (parzysta liczba, więc pierwsza kolorowanka trafia na
stronę nieparzystą, czyli prawą), potem grafiki; przy druku jednostronnym każda z pustym
tyłem (D8), przy dwustronnym jedna po drugiej, z pustą stroną na końcu, gdy liczba stron jest
nieparzysta. `interior_layout()` to czysta funkcja manifestu; zapis idzie przez `pdf.py`.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from kdp_studio.pipeline.belongs_to import FRONT_NAME
from kdp_studio.pipeline.front_matter import COPYRIGHT_NAME, INSTRUCTIONS_NAME, TITLE_NAME
from kdp_studio.pipeline.manifest import InteriorInfo, Manifest, sha256_bytes, sha256_file
from kdp_studio.pipeline.output import write_bytes_atomic
from kdp_studio.pipeline.pdf import bilevel_pdf, read_bilevel_pages
from kdp_studio.validation import KDP_MIN_BOOK_PAGES, plural

INTERIOR_FILE = "interior.pdf"
# KDP: najwyżej 4 puste strony z rzędu na początku i w środku pliku, 10 na końcu.
MAX_BLANK_RUN = 4
MAX_BLANK_RUN_END = 10
SIZE_TOLERANCE_IN = 0.001


class InteriorError(Exception):
    """`interior.pdf` nie powstał albo nie przeszedł kontroli po zapisie (FR-22)."""

    def __init__(self, errors: list[str]) -> None:
        super().__init__("; ".join(errors))
        self.errors = errors


def front_matter_files(manifest: Manifest) -> list[str | None]:
    """Strony wstępne FR-23 w kolejności druku: plik albo None dla pustej strony."""
    matter = manifest.front_matter
    first = FRONT_NAME if matter.belongs_to is not None else TITLE_NAME
    files: list[str | None] = [first, COPYRIGHT_NAME]
    if manifest.input.front_matter_pages >= 4:
        files += [INSTRUCTIONS_NAME, None]
    return files


def interior_layout(manifest: Manifest) -> list[str | None]:
    """Strony `interior.pdf` po kolei: nazwa pliku strony (bez .png) albo None dla pustej."""
    order = front_matter_files(manifest)
    for page in manifest.pages:
        order.append(page.name)
        if manifest.input.single_sided:
            order.append(None)
    if len(order) % 2:
        order.append(None)
    return order


def blank_run_problems(order: list[str | None]) -> list[str]:
    """Ciągi pustych stron dłuższe niż pozwala KDP (numery stron od 1)."""
    problems = []
    start = 0
    while start < len(order):
        if order[start] is not None:
            start += 1
            continue
        end = start
        while end < len(order) and order[end] is None:
            end += 1
        limit = MAX_BLANK_RUN_END if end == len(order) else MAX_BLANK_RUN
        if end - start > limit:
            problems.append(
                f"strony {start + 1}–{end}: {end - start} pustych z rzędu (KDP pozwala na {limit})"
            )
        start = end
    return problems


def layout_problems(manifest: Manifest, order: list[str | None]) -> list[str]:
    """Kontrola układu (jak NFR-07): liczba stron parzysta, ≥ 24 i równa `pages_in_book`,
    pierwsza kolorowanka na stronie nieparzystej, limity pustych stron."""
    problems = []
    count = len(order)
    if count % 2:
        problems.append(f"nieparzysta liczba stron ({count})")
    if count < KDP_MIN_BOOK_PAGES:
        problems.append(
            f"{plural(count, 'strona', 'strony', 'stron')}, a minimum KDP to {KDP_MIN_BOOK_PAGES}"
        )
    expected = manifest.layout.pages_in_book
    if count != expected:
        problems.append(f"{count} stron w PDF, a manifest liczy {expected} (pages_in_book)")
    if manifest.pages:
        first = order.index(manifest.pages[0].name) + 1
        if first % 2 == 0:
            problems.append(f"pierwsza kolorowanka na stronie parzystej ({first})")
    return problems + blank_run_problems(order)


def missing_pages(book_dir: Path, manifest: Manifest, order: list[str | None]) -> list[str]:
    """Strony bez statusu `ok` albo bez pliku: bez nich `interior.pdf` nie powstaje."""
    status = {p.name: p.status for p in manifest.pages}
    status.update({p.name: p.status for p in manifest.front_matter.pages()})
    return [
        name
        for name in order
        if name is not None
        and (status.get(name) != "ok" or not (book_dir / f"{name}.png").is_file())
    ]


def inputs_sha256(book_dir: Path, order: list[str | None]) -> str:
    """Hash kolejności i zawartości stron: ten sam znaczy, że PDF jest aktualny."""
    parts = [
        "-" if name is None else f"{name}:{sha256_file(book_dir / f'{name}.png')}" for name in order
    ]
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class InteriorResult:
    info: InteriorInfo
    written: bool  # False: plik był aktualny


def _images(
    book_dir: Path, order: list[str | None], page_px: tuple[int, int]
) -> Iterator[Image.Image | None]:
    for name in order:
        if name is None:
            yield None
            continue
        with Image.open(book_dir / f"{name}.png") as image:
            if image.size != page_px or image.mode != "L":
                raise InteriorError(
                    [
                        f"{name}.png: {image.size[0]}×{image.size[1]} px w trybie {image.mode}, "
                        f"a strona ma {page_px[0]}×{page_px[1]} px w trybie L"
                    ]
                )
            image.load()
            yield image


def verify_interior(data: bytes, order: list[str | None], trim_in: tuple[float, float]) -> None:
    """Kontrola zapisanego pliku: liczba stron, wymiary każdej strony, puste tam, gdzie
    układ ma pustą stronę."""
    try:
        pages = read_bilevel_pages(data)
    except ValueError as e:
        raise InteriorError([f"{INTERIOR_FILE}: {e}"]) from e
    errors = []
    if len(pages) != len(order):
        errors.append(f"{INTERIOR_FILE}: {len(pages)} stron, a układ ma {len(order)}")
    for number, ((width, height, has_image), name) in enumerate(
        zip(pages, order, strict=False), start=1
    ):
        if abs(width - trim_in[0]) > SIZE_TOLERANCE_IN or abs(height - trim_in[1]) > (
            SIZE_TOLERANCE_IN
        ):
            errors.append(f"strona {number}: {width:g}×{height:g} in zamiast formatu")
        if has_image != (name is not None):
            errors.append(f"strona {number}: {'obraz' if has_image else 'brak obrazu'} w PDF")
    if errors:
        raise InteriorError(errors)


def write_interior(book_dir: Path, manifest: Manifest) -> InteriorResult:
    """Składa `interior.pdf`, gdy wszystkie strony są gotowe, i sprawdza go po zapisie.

    `InteriorError` z listą brakujących stron albo problemów; plik jest wtedy usunięty, żeby
    nie wgrać do KDP nieaktualnego wnętrza."""
    path = book_dir / INTERIOR_FILE
    order = interior_layout(manifest)
    missing = missing_pages(book_dir, manifest, order)
    if missing:
        path.unlink(missing_ok=True)
        raise InteriorError([f"brakujące strony: {', '.join(missing)}"])
    problems = layout_problems(manifest, order)
    if problems:
        path.unlink(missing_ok=True)
        raise InteriorError(problems)
    inputs = inputs_sha256(book_dir, order)
    previous = manifest.interior
    if (
        previous is not None
        and previous.inputs_sha256 == inputs
        and path.is_file()
        and sha256_file(path) == previous.sha256
    ):
        return InteriorResult(previous, written=False)
    layout = manifest.layout
    try:
        data = bilevel_pdf(_images(book_dir, order, layout.page_px), layout.trim_in)
        verify_interior(data, order, layout.trim_in)
    except InteriorError:
        path.unlink(missing_ok=True)
        raise
    write_bytes_atomic(path, data)
    info = InteriorInfo(
        file=INTERIOR_FILE,
        pages=len(order),
        single_sided=manifest.input.single_sided,
        sha256=sha256_bytes(data),
        inputs_sha256=inputs,
        order=order,
    )
    return InteriorResult(info, written=True)
