"""NFR-02: pipeline i kontrakty dostawców nie importują SDK dostawców."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

import kdp_studio

PACKAGE = Path(kdp_studio.__file__).parent
VENDOR_SDKS = {"openai", "google", "anthropic", "firefly"}
VENDOR_FREE = [
    *sorted((PACKAGE / "pipeline").glob("*.py")),
    PACKAGE / "providers" / "base.py",
    PACKAGE / "providers" / "registry.py",
]


def _imported_roots(path: Path) -> set[str]:
    roots: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            roots |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            roots.add(node.module.split(".")[0])
    return roots


@pytest.mark.parametrize("path", VENDOR_FREE, ids=lambda p: f"{p.parent.name}/{p.name}")
def test_no_vendor_sdk_imports(path: Path) -> None:
    assert not _imported_roots(path) & VENDOR_SDKS
