"""Katalog wyjściowy książki i zapis plików (FR-08, NFR-04)."""

from __future__ import annotations

import os
import re
import tempfile
import unicodedata
from pathlib import Path

from pydantic import BaseModel

from kdp_studio.models import BookSpec

IDEAS_FILE = "ideas.json"
PROMPTS_FILE = "prompts.json"
RAW_DIR = "raw"
SVG_DIR = "svg"
REJECTED_DIR = "rejected"  # strony odrzucone przez QA (FR-07)
LOG_FILE = "kdp-studio.log"  # logi strukturalne (NFR-09)

# Litery, których NFKD nie rozkłada na literę bazową i znak diakrytyczny.
_TRANSLITERATE = str.maketrans({"ł": "l", "Ł": "L", "ß": "ss", "ø": "o", "Ø": "O"})


def slugify(text: str, fallback: str = "kolorowanka") -> str:
    """'Zwierzęta Leśne!' -> 'zwierzeta_lesne'."""
    ascii_text = (
        unicodedata.normalize("NFKD", text.translate(_TRANSLITERATE))
        .encode("ascii", "ignore")
        .decode("ascii")
    )
    slug = re.sub(r"[^a-z0-9]+", "_", ascii_text.lower()).strip("_")
    return slug or fallback


def book_dir(output_dir: Path, spec: BookSpec) -> Path:
    """`<output-dir>/<slug-tematu>_<age>_<style>_<format>/` (FR-08)."""
    return output_dir / f"{slugify(spec.theme)}_{spec.age}_{spec.style}_{spec.format}"


def write_bytes_atomic(path: Path, data: bytes) -> None:
    """Zapis przez plik tymczasowy i zmianę nazwy, żeby przerwanie nie zostawiło połowy pliku."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def write_json_atomic(path: Path, model: BaseModel) -> None:
    write_bytes_atomic(path, (model.model_dump_json(indent=2) + "\n").encode("utf-8"))


def page_name(page: int, total: int) -> str:
    """`page_07` albo `page_007`: numer dopełniony do długości największego numeru, min. 2 cyfry.

    Kolejność alfabetyczna = kolejność stron, więc paczka plików trafia do Canvy po kolei (FR-08).
    """
    return f"page_{page:0{max(2, len(str(total)))}d}"
