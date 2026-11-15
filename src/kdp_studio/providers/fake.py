"""Fałszywi dostawcy do testów, bez sieci (NFR-03)."""

from __future__ import annotations

import struct
import threading
import zlib
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from kdp_studio.providers.base import (
    PNG_SIGNATURE,
    ImageRequest,
    ImageResult,
    ProviderError,
    SchemaT,
    Usage,
)

Responder = Callable[[str, str], Any]


@dataclass
class TextCall:
    system: str
    user: str
    schema: type[Any]


@dataclass
class FakeTextProvider:
    """Zwraca kolejne przygotowane odpowiedzi (dict albo funkcja `(system, user) -> dict`).

    Po wyczerpaniu listy powtarza ostatnią odpowiedź. `routes` (nazwa klasy schematu →
    odpowiedź) ma pierwszeństwo, np. osobna odpowiedź dla weryfikacji pomysłów.
    Każde wywołanie trafia do `calls`.
    """

    responses: list[Any | Responder]
    routes: dict[str, Any | Responder] = field(default_factory=dict)
    name: str = "fake"
    model: str = "fake-text"
    usage_per_call: Usage = field(default_factory=lambda: Usage(input_tokens=100, output_tokens=50))
    calls: list[TextCall] = field(default_factory=list)

    def complete_json(self, system: str, user: str, schema: type[SchemaT]) -> tuple[SchemaT, Usage]:
        self.calls.append(TextCall(system, user, schema))
        if schema.__name__ in self.routes:
            response = self.routes[schema.__name__]
        else:
            calls = sum(1 for c in self.calls if c.schema.__name__ not in self.routes)
            response = self.responses[min(calls, len(self.responses)) - 1]
        data = response(system, user) if callable(response) else response
        return schema.model_validate(data), self.usage_per_call


def make_png(width: int, height: int, value: int = 255, *, frame: bool = False) -> bytes:
    """Minimalny poprawny PNG w skali szarości (8 bit) w kolorze `value`.

    `frame=True` rysuje czarną ramkę wokół środka obrazu: najprostszy „line art”,
    który przechodzi przez obróbkę FR-06 (pusta biała grafika jest odrzucana).
    """

    def chunk(kind: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(kind + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", crc)

    header = struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0)
    if frame:
        thickness = max(2, min(width, height) // 12)
        x0, x1, y0, y1 = width // 4, 3 * width // 4, height // 4, 3 * height // 4
        rows = b""
        for y in range(height):
            row = bytearray([value]) * width
            if y0 <= y < y1:
                band = y < y0 + thickness or y >= y1 - thickness
                cols = (
                    range(x0, x1)
                    if band
                    else [*range(x0, x0 + thickness), *range(x1 - thickness, x1)]
                )
                for x in cols:
                    row[x] = 0
            rows += b"\x00" + bytes(row)
    else:
        rows = (b"\x00" + bytes([value]) * width) * height
    return (
        PNG_SIGNATURE
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(rows))
        + chunk(b"IEND", b"")
    )


@dataclass
class FakeImageProvider:
    """Zwraca przygotowane PNG bez sieci (NFR-03). Bezpieczny dla wielu wątków.

    `fail(req)` może zwrócić ProviderError, który zostanie rzucony dla danego zapytania.
    """

    name: str = "fake"
    model: str = "fake-image"
    aspects: list[str] = field(default_factory=lambda: ["1:1", "3:4"])
    size: tuple[int, int] = (96, 128)
    fail: Callable[[ImageRequest], ProviderError | None] | None = None
    usage_per_call: Usage = field(default_factory=lambda: Usage(input_tokens=10, output_tokens=100))
    requests: list[ImageRequest] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def supported_aspects(self) -> list[str]:
        return list(self.aspects)

    def generate(self, req: ImageRequest) -> ImageResult:
        with self._lock:
            self.requests.append(req)
        error = self.fail(req) if self.fail else None
        if error is not None:
            raise error
        width, height = self.size
        return ImageResult(make_png(width, height, frame=True), width, height, self.usage_per_call)
