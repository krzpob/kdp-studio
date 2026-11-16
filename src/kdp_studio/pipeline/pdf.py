"""FR-15: `cover.pdf` — jedna strona, obraz w DeviceCMYK, kompresja bezstratna.

Pillow zapisuje CMYK do PDF jako JPEG (stratnie), więc plik składa się tutaj ręcznie:
obraz Flate w `DeviceCMYK`, `MediaBox` = `BleedBox` (cała okładka ze spadem) i `TrimBox`
(okładka po przycięciu). Bez profilu ICC i bez `OutputIntent`: KDP usuwa profile przed
publikacją i ich nie zaleca, więc to nie jest PDF/X-1a. Napisy są w obrazie, więc nie
ma czcionek do osadzania.
"""

from __future__ import annotations

import zlib
from pathlib import Path

from PIL import Image

from kdp_studio.pipeline.output import write_bytes_atomic

POINTS_PER_INCH = 72


def _number(value: float) -> str:
    text = f"{value:.4f}".rstrip("0").rstrip(".")
    return text or "0"


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


def write_cmyk_pdf(
    path: Path, image: Image.Image, size_in: tuple[float, float], bleed_in: float
) -> None:
    write_bytes_atomic(path, cmyk_pdf(image, size_in, bleed_in))
