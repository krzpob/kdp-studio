"""Fałszywi dostawcy do testów, bez sieci (NFR-03)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from kdp_studio.providers.base import SchemaT, Usage

Responder = Callable[[str, str], Any]


@dataclass
class TextCall:
    system: str
    user: str
    schema: type[Any]


@dataclass
class FakeTextProvider:
    """Zwraca kolejne przygotowane odpowiedzi (dict albo funkcja `(system, user) -> dict`).

    Po wyczerpaniu listy powtarza ostatnią odpowiedź. Każde wywołanie trafia do `calls`.
    """

    responses: list[Any | Responder]
    name: str = "fake"
    model: str = "fake-text"
    usage_per_call: Usage = field(default_factory=lambda: Usage(input_tokens=100, output_tokens=50))
    calls: list[TextCall] = field(default_factory=list)

    def complete_json(self, system: str, user: str, schema: type[SchemaT]) -> tuple[SchemaT, Usage]:
        self.calls.append(TextCall(system, user, schema))
        response = self.responses[min(len(self.calls), len(self.responses)) - 1]
        data = response(system, user) if callable(response) else response
        return schema.model_validate(data), self.usage_per_call
