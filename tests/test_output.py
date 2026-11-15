from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import BaseModel

from kdp_studio.models import BookSpec
from kdp_studio.pipeline.output import book_dir, slugify, write_json_atomic


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Dinozaury", "dinozaury"),
        ("Zwierzęta Leśne!", "zwierzeta_lesne"),
        ("Łódź i żółw", "lodz_i_zolw"),
        ("  Space -- Cats  ", "space_cats"),
        ("!!!", "kolorowanka"),
    ],
)
def test_slugify(text: str, expected: str) -> None:
    assert slugify(text) == expected


def test_book_dir() -> None:
    spec = BookSpec(
        theme="Dinozaury",
        age="przedszkole",
        style="kawaii",
        format="square",
        pages=30,
        front_matter_pages=2,
    )
    assert book_dir(Path("output"), spec) == Path("output/dinozaury_przedszkole_kawaii_square")


class Doc(BaseModel):
    name: str


def test_write_json_atomic(tmp_path: Path) -> None:
    target = tmp_path / "nested" / "doc.json"
    write_json_atomic(target, Doc(name="żółw"))
    assert target.read_text(encoding="utf-8") == '{\n  "name": "żółw"\n}\n'
    write_json_atomic(target, Doc(name="b"))
    assert '"b"' in target.read_text(encoding="utf-8")
    assert [p.name for p in target.parent.iterdir()] == ["doc.json"]
