"""PDF składany ręcznie, bez nowej zależności: okładka (FR-15) i wnętrze (FR-22).

`cover.pdf`: jedna strona, obraz w DeviceCMYK, kompresja bezstratna. Pillow zapisuje CMYK do
PDF jako JPEG (stratnie), więc plik składa się tutaj ręcznie: obraz Flate w `DeviceCMYK`,
`MediaBox` = `BleedBox` (cała okładka ze spadem) i `TrimBox` (okładka po przycięciu). Bez
profilu ICC i bez `OutputIntent`: KDP usuwa profile przed publikacją i ich nie zaleca, więc
to nie jest PDF/X-1a.

`interior.pdf`: wiele stron formatu bez spadu, każda z jednym obrazem 1-bit DeviceGray Flate
(strony mają tylko 0 i 255) albo pusta. Bez adnotacji, zakładek i metadanych (brak `/Info`),
które KDP wymienia wśród powodów odrzucenia pliku. Napisy są w obrazach, więc w żadnym
pliku nie ma czcionek do osadzania.
"""

from __future__ import annotations

import re
import zlib
from collections.abc import Iterable
from pathlib import Path

from PIL import Image

from kdp_studio.pipeline.output import write_bytes_atomic

POINTS_PER_INCH = 72


def _number(value: float) -> str:
    text = f"{value:.4f}".rstrip("0").rstrip(".")
    return text or "0"


def _serialize(objects: list[bytes]) -> bytes:
    """Plik PDF z obiektów numerowanych od 1 (obiekt 1 to katalog), z tablicą xref."""
    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode("ascii") + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode("ascii")
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode("ascii")
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n"
    ).encode("ascii")
    return bytes(out)


def _stream(header: str, data: bytes) -> bytes:
    return f"<< {header} /Length {len(data)} >>\nstream\n".encode("ascii") + data + b"\nendstream"


def cmyk_pdf(image: Image.Image, size_in: tuple[float, float], bleed_in: float) -> bytes:
    """Bajty PDF: obraz CMYK rozciągnięty na stronę `size_in` (cale), z polami przycięcia."""
    if image.mode != "CMYK":
        raise ValueError(f"okładka musi być w CMYK, a jest w {image.mode}")
    width_pt = size_in[0] * POINTS_PER_INCH
    height_pt = size_in[1] * POINTS_PER_INCH
    bleed_pt = bleed_in * POINTS_PER_INCH
    media = f"[0 0 {_number(width_pt)} {_number(height_pt)}]"
    trim = (
        f"[{_number(bleed_pt)} {_number(bleed_pt)} "
        f"{_number(width_pt - bleed_pt)} {_number(height_pt - bleed_pt)}]"
    )
    pixels = zlib.compress(image.tobytes(), level=9)
    content = f"q {_number(width_pt)} 0 0 {_number(height_pt)} 0 0 cm /Im0 Do Q".encode("ascii")

    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            f"<< /Type /Page /Parent 2 0 R /MediaBox {media} /BleedBox {media} "
            f"/TrimBox {trim} /Resources << /XObject << /Im0 4 0 R >> >> /Contents 5 0 R >>"
        ).encode("ascii"),
        (
            f"<< /Type /XObject /Subtype /Image /Width {image.width} /Height {image.height} "
            f"/ColorSpace /DeviceCMYK /BitsPerComponent 8 /Filter /FlateDecode "
            f"/Length {len(pixels)} >>\nstream\n"
        ).encode("ascii")
        + pixels
        + b"\nendstream",
        f"<< /Length {len(content)} >>\nstream\n".encode("ascii") + content + b"\nendstream",
    ]
    return _serialize(objects)


def write_cmyk_pdf(
    path: Path, image: Image.Image, size_in: tuple[float, float], bleed_in: float
) -> None:
    write_bytes_atomic(path, cmyk_pdf(image, size_in, bleed_in))


def bilevel_pdf(pages: Iterable[Image.Image | None], size_in: tuple[float, float]) -> bytes:
    """Bajty wielostronicowego PDF (FR-22): każda strona ma wymiary `size_in` (MediaBox =
    TrimBox, bez spadu) i obraz rozciągnięty na całą stronę albo nic (None: pusta strona).

    Obrazy są w trybie L z samymi 0 i 255; zapisuje je jako 1-bit DeviceGray Flate. `pages`
    może być generatorem: obraz jest potrzebny tylko do kompresji, więc w pamięci jest
    naraz jedna strona."""
    width_pt = _number(size_in[0] * POINTS_PER_INCH)
    height_pt = _number(size_in[1] * POINTS_PER_INCH)
    box = f"[0 0 {width_pt} {height_pt}]"
    content = f"q {width_pt} 0 0 {height_pt} 0 0 cm /Im0 Do Q".encode("ascii")
    objects: list[bytes] = [b"<< /Type /Catalog /Pages 2 0 R >>", b""]
    kids: list[int] = []
    for image in pages:
        page_number = len(objects) + 1
        kids.append(page_number)
        head = f"<< /Type /Page /Parent 2 0 R /MediaBox {box} /TrimBox {box}"
        if image is None:
            objects.append(f"{head} /Resources << >> >>".encode("ascii"))
            continue
        if image.mode != "L":
            raise ValueError(f"strona wnętrza musi być w trybie L, a jest w {image.mode}")
        bits = image.convert("1", dither=Image.Dither.NONE).tobytes()  # 1 = biały
        objects.append(
            (
                f"{head} /Resources << /XObject << /Im0 {page_number + 1} 0 R >> >> "
                f"/Contents {page_number + 2} 0 R >>"
            ).encode("ascii")
        )
        objects.append(
            _stream(
                f"/Type /XObject /Subtype /Image /Width {image.width} /Height {image.height} "
                "/ColorSpace /DeviceGray /BitsPerComponent 1 /Filter /FlateDecode",
                zlib.compress(bits, level=9),
            )
        )
        objects.append(_stream("", content))
    refs = " ".join(f"{n} 0 R" for n in kids)
    objects[1] = f"<< /Type /Pages /Kids [{refs}] /Count {len(kids)} >>".encode("ascii")
    return _serialize(objects)


_PAGE = re.compile(
    rb"\d+ 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox \[0 0 ([\d.]+) ([\d.]+)\]"
    rb" /TrimBox \[0 0 ([\d.]+) ([\d.]+)\] /Resources << (/XObject)?"
)
_COUNT = re.compile(rb"<< /Type /Pages /Kids \[[^\]]*\] /Count (\d+) >>")


def read_bilevel_pages(data: bytes) -> list[tuple[float, float, bool]]:
    """Strony PDF z `bilevel_pdf`: (szerokość, wysokość w calach, czy ma obraz). Do kontroli
    po zapisie (FR-22); `ValueError`, gdy plik nie ma tej budowy."""
    if not data.startswith(b"%PDF-") or not data.rstrip().endswith(b"%%EOF"):
        raise ValueError("to nie jest kompletny plik PDF")
    if b"/Info" in data.rsplit(b"trailer", 1)[-1]:
        raise ValueError("PDF ma metadane (/Info)")
    count = _COUNT.search(data)
    pages = [
        (
            float(m[1]) / POINTS_PER_INCH,
            float(m[2]) / POINTS_PER_INCH,
            m[5] is not None,
        )
        for m in _PAGE.finditer(data)
        if (m[1], m[2]) == (m[3], m[4])
    ]
    if count is None or int(count[1]) != len(pages):
        raise ValueError("liczba stron PDF nie zgadza się z drzewem stron")
    return pages
