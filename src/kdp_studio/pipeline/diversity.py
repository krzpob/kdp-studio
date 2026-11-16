"""FR-03b: różnorodność pomysłów w skali całej książki.

Weryfikacja (FR-03a) ocenia każdy pomysł osobno, a rozkład to cecha całej książki. Model
przy każdym pomyśle podaje cechy sceny (liczba postaci, czynność, miejsce akcji), a ten
moduł liczy rozkład i porównuje go z limitami z konfiguracji: model słabo liczy w kilkudziesięciu
scenach naraz, kod robi to dokładnie. Pierwsza naprawa to zamiana stron z zapasem (bez API).
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Literal

from kdp_studio.config import AppConfig
from kdp_studio.models import BookSpec, DiversityReport, PageIdea

Kind = Literal["characters", "action", "setting", "element"]
TOP_VALUES = 6  # tyle najczęstszych wartości trafia do raportu


@dataclass(frozen=True)
class DiversityLimits:
    multi_subject_share: float  # minimum; 0 wyłącza
    max_action_share: float
    max_setting_share: float
    max_element_share: float
    # Motywy tematu (BookIdeas.theme_anchors): wartości bez limitu.
    exempt: frozenset[str] = field(default_factory=frozenset)

    @classmethod
    def from_config(
        cls, spec: BookSpec, config: AppConfig, theme_anchors: Iterable[str] = ()
    ) -> DiversityLimits:
        limits = config.settings.diversity
        exempt = {
            key
            for anchor in theme_anchors
            for key in (" ".join(anchor.casefold().split()), noun(anchor))
        }
        return cls(
            multi_subject_share=config.ages[spec.age].multi_subject_share,
            max_action_share=limits.max_action_share,
            max_setting_share=limits.max_setting_share,
            max_element_share=limits.max_element_share,
            exempt=frozenset(exempt - {""}),
        )


@dataclass(frozen=True)
class Issue:
    """Jeden problem rozkładu; `ids` to pomysły, których zmiana go zmniejsza."""

    kind: Kind
    value: str | None
    count: int
    limit: int
    pages: int
    ids: tuple[str, ...]

    @property
    def excess(self) -> int:
        """O ile stron rozkład mija się z limitem."""
        if self.kind == "characters":
            return self.limit - self.count
        return self.count - self.limit

    def message(self) -> str:
        """Opis po polsku dla użytkownika."""
        if self.kind == "characters":
            return (
                f"sceny z kilkoma postaciami: {self.count} z {self.pages} stron, "
                f"wymagane co najmniej {self.limit}"
            )
        what = {"action": "czynność", "setting": "miejsce akcji", "element": "przedmiot"}
        return (
            f"{what[self.kind]} „{self.value}” na {self.count} z {self.pages} stron, "
            f"najwyżej {self.limit}"
        )

    def instruction(self) -> str:
        """Opis po angielsku dla modelu, który poprawia pomysły."""
        if self.kind == "characters":
            return (
                f"Only {self.count} of {self.pages} pages show two or three characters doing "
                f"something together; at least {self.limit} should. Turn {self.excess} "
                f"single-character ideas into scenes with two or three characters."
            )
        what = {"action": "the action", "setting": "the setting", "element": "the object"}
        return (
            f'{self.count} of {self.pages} pages use {what[self.kind]} "{self.value}"; at most '
            f"{self.limit} may. Change it in {self.excess} of these ideas to something not "
            f"common in the book yet."
        )


def noun(text: str) -> str:
    """Rdzeń nazwy przedmiotu: ostatnie słowo w liczbie pojedynczej ("decorated trees" → tree)."""
    words = text.casefold().split()
    word = words[-1].strip(".,;:!?\"'()") if words else ""
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        word = word[:-1]
    return word


def element_keys(idea: PageIdea) -> set[str]:
    """Przedmioty w scenie bez głównej postaci (kotek jest na każdej stronie z założenia)."""
    keys = {noun(e) for e in idea.elements} - {""}
    if idea.subject:
        keys.discard(noun(idea.subject))
    return keys


def _over_limit(
    kind: Kind, values: dict[str, list[str]], share: float, pages: int, exempt: frozenset[str]
) -> list[Issue]:
    limit = max(1, math.floor(share * pages))
    return [
        Issue(kind, value, len(ids), limit, pages, tuple(ids))
        for value, ids in values.items()
        if len(ids) > limit and value not in exempt
    ]


def measure(pages: Sequence[PageIdea], limits: DiversityLimits) -> list[Issue]:
    """Problemy rozkładu na stronach książki (bez zapasu), od największego."""
    n = len(pages)
    if n == 0:
        return []
    issues: list[Issue] = []

    counted = [p for p in pages if p.characters is not None]
    if limits.multi_subject_share > 0 and counted:
        required = math.ceil(limits.multi_subject_share * n)
        multi = [p for p in counted if (p.characters or 0) >= 2]
        if len(multi) < required:
            single = tuple(p.id for p in counted if (p.characters or 0) < 2)
            issues.append(Issue("characters", None, len(multi), required, n, single))

    actions: dict[str, list[str]] = {}
    settings: dict[str, list[str]] = {}
    elements: dict[str, list[str]] = {}
    for page in pages:
        if page.action:
            actions.setdefault(page.action, []).append(page.id)
        if page.setting:
            settings.setdefault(page.setting, []).append(page.id)
        for key in element_keys(page):
            elements.setdefault(key, []).append(page.id)
    issues += _over_limit("action", actions, limits.max_action_share, n, limits.exempt)
    issues += _over_limit("setting", settings, limits.max_setting_share, n, limits.exempt)
    issues += _over_limit("element", elements, limits.max_element_share, n, limits.exempt)
    return sorted(issues, key=lambda i: -i.excess)


def total_excess(issues: Sequence[Issue]) -> int:
    return sum(issue.excess for issue in issues)


def swap_with_reserve(
    pages: Sequence[PageIdea], reserve: Sequence[PageIdea], limits: DiversityLimits
) -> tuple[list[PageIdea], list[PageIdea], int]:
    """Zamienia strony z zapasem, dopóki każda zamiana zmniejsza problemy rozkładu.

    Zwraca nowe strony, nowy zapas i liczbę zamian. Bez wywołań API.
    """
    pages, reserve = list(pages), list(reserve)
    best = total_excess(measure(pages, limits))
    moves = 0
    while best > 0:
        choice: tuple[int, int] | None = None
        for i in range(len(pages)):
            for j, candidate in enumerate(reserve):
                score = total_excess(measure([*pages[:i], candidate, *pages[i + 1 :]], limits))
                if score < best:
                    best, choice = score, (i, j)
        if choice is None:
            break
        i, j = choice
        pages[i], reserve[j] = reserve[j], pages[i]
        moves += 1
    return pages, reserve, moves


def _top(counter: Counter[str]) -> dict[str, int]:
    return dict(counter.most_common(TOP_VALUES))


def diversity_report(
    pages: Sequence[PageIdea],
    limits: DiversityLimits,
    *,
    moved_from_reserve: int = 0,
    revised: int = 0,
) -> DiversityReport:
    characters = Counter(str(p.characters) for p in pages if p.characters is not None)
    return DiversityReport(
        pages=len(pages),
        characters=dict(sorted(characters.items(), key=lambda kv: int(kv[0]))),
        actions=_top(Counter(p.action for p in pages if p.action)),
        settings=_top(Counter(p.setting for p in pages if p.setting)),
        elements=_top(Counter(key for p in pages for key in element_keys(p))),
        issues=[issue.message() for issue in measure(pages, limits)],
        moved_from_reserve=moved_from_reserve,
        revised=revised,
    )
