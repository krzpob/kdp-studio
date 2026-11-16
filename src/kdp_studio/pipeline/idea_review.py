"""FR-03a: weryfikacja pomysłów przed generowaniem grafik.

Osobne wywołanie LLM z listą kontrolną ocenia każdy pomysł: `ok`, `revise` (drobna
poprawka, np. dodanie elementu tematu, zamiast zużywania zapasu) albo `reject`.
Odrzucone zastępuje zapas; gdy zapasu brakuje, generator dogenerowuje nowe pomysły,
które też przechodzą weryfikację. Tańsze niż wyrzucenie gotowej grafiki (FR-07).
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, Field

from kdp_studio.config import AppConfig
from kdp_studio.models import BookIdeas, BookSpec, IdeaReview, PageIdea, RejectedIdea, RevisedIdea
from kdp_studio.pipeline.diversity import (
    DiversityLimits,
    Issue,
    diversity_report,
    measure,
    swap_with_reserve,
    total_excess,
)
from kdp_studio.pipeline.ideas import (
    ACTION_HELP,
    CHARACTERS_HELP,
    SETTING_HELP,
    SUBJECT_HELP,
    THEME_RULE,
    IdeaGenerator,
    profile_prompt,
    reserve_count,
    tag,
)
from kdp_studio.providers.base import ProviderError, TextProvider, Usage

DEFAULT_MAX_TOPUPS = 2


class _Verdict(BaseModel):
    id: str = Field(description="Idea id exactly as given, e.g. idea_07.")
    verdict: Literal["ok", "revise", "reject"]
    reason: str = Field(description="Short reason in Polish; empty when the verdict is ok.")
    revised_title: str = Field(description="Only for revise; otherwise empty.")
    revised_scene: str = Field(description="Only for revise: the full corrected scene, English.")
    revised_elements: list[str] = Field(description="Only for revise; otherwise empty.")
    revised_subject: str = Field(description="Only for revise; otherwise empty. " + SUBJECT_HELP)
    revised_characters: int = Field(description="Only for revise; otherwise 0. " + CHARACTERS_HELP)
    revised_action: str = Field(description="Only for revise; otherwise empty. " + ACTION_HELP)
    revised_setting: str = Field(description="Only for revise; otherwise empty. " + SETTING_HELP)


class _Review(BaseModel):
    verdicts: list[_Verdict]


# FR-03b: poprawki dla różnorodności całej książki.
class _BalancedIdea(BaseModel):
    id: str = Field(description="Id of the changed idea exactly as given, e.g. idea_07.")
    title: str
    scene: str = Field(description="The full new scene in English, only what is visible.")
    elements: list[str] = Field(description="Main objects visible in the scene.")
    subject: str = Field(description=SUBJECT_HELP)
    characters: int = Field(description=CHARACTERS_HELP)
    action: str = Field(description=ACTION_HELP)
    setting: str = Field(description=SETTING_HELP)
    reason: str = Field(description="Short reason in Polish.")


class _Balance(BaseModel):
    ideas: list[_BalancedIdea]


REVIEW_SYSTEM = """\
You review page ideas for a coloring book before any picture is drawn. Pictures are \
expensive, so catch ideas that do not fit now. Judge every idea against this checklist:

1. Theme. {theme_rule}
2. Distinct: not a near-duplicate of another idea in the list or of an already accepted idea. \
For near-duplicates, keep the first one and reject the later one.
3. Audience: the number of subjects and the complexity fit the target audience.
4. Format: the composition fits the page format.
5. Drawable: one single scene that works as black-and-white line art, with no text, letters, \
numbers, signs or speech bubbles in the picture.
6. Legal: no copyrighted or trademarked characters, franchises, brands or logos.

Verdicts:
- ok: the idea passes every point.
- revise: the idea is good but needs a small change to pass, most often adding a concrete \
theme element (e.g. a kitten baker becomes a kitten baking gingerbread cookies). Return the \
full corrected title, scene (English, only what is visible) and elements.
- reject: the idea fails at its core (off-theme subject, duplicate, needs text, protected \
character, wrong audience) and a small change would not fix it.

Return exactly one verdict for every idea id under "Ideas to review". Write `reason` in Polish.

Calibration:
- Most ideas in a decent list are ok. Do not polish ideas that already pass: return ok \
without changes.
- Revise or reject only ideas that clearly fail a point, above all scenes that would look the \
same on any other day or belong to a different occasion.
- When you revise several ideas, vary the added theme elements instead of adding the same \
object (for example a decorated tree) to all of them; variety across pages matters.
"""

REVIEW_USER = """\
{profile}
Already accepted ideas (do not judge; use only to spot duplicates):
{accepted}

Ideas to review:
{pending}
"""


BALANCE_SYSTEM = """\
You improve the variety of a coloring book. Its page ideas are good one by one, but the book \
as a whole repeats itself. A program counted the problems below; trust its numbers.

Rules:
- Change at most {budget} ideas, and only ideas listed as candidates of a problem.
- A changed idea must still pass every check: {theme_rule} It fits the audience and the page \
format, is one single scene for black-and-white line art with no text, letters or numbers, \
has no copyrighted characters or brands, and differs from every other idea in the book.
- Fix a problem without creating another: do not replace a repeated action, place or object \
with one that is already common in the book.
- Keep the spirit of the idea where you can, e.g. the same activity with a second character, \
or the same character in a new place.
- Return each changed idea in full, with its tags. Write `reason` in Polish.
"""

BALANCE_USER = """\
{profile}
Problems:
{problems}

Book pages (reserve ideas are not shown):
{pages}
"""


def _listing(ideas: Sequence[PageIdea], *, tags: bool = False) -> str:
    lines = []
    for idea in ideas:
        line = f"{idea.id} | {idea.title} | {idea.scene} | elements: {', '.join(idea.elements)}"
        if tags:
            line += (
                f" | subject: {idea.subject}, characters: {idea.characters}, "
                f"action: {idea.action}, setting: {idea.setting}"
            )
        lines.append(line)
    return "\n".join(lines) or "(none)"


def build_balance_prompts(
    spec: BookSpec,
    config: AppConfig,
    pages: Sequence[PageIdea],
    issues: Sequence[Issue],
    budget: int,
) -> tuple[str, str]:
    system = BALANCE_SYSTEM.format(budget=budget, theme_rule=THEME_RULE)
    problems = "\n".join(
        f"- {issue.instruction()} Candidates: {', '.join(issue.ids)}." for issue in issues
    )
    user = BALANCE_USER.format(
        profile=profile_prompt(spec, config), problems=problems, pages=_listing(pages, tags=True)
    )
    return system, user


def build_review_prompts(
    spec: BookSpec, config: AppConfig, pending: Sequence[PageIdea], accepted: Sequence[PageIdea]
) -> tuple[str, str]:
    system = REVIEW_SYSTEM.format(theme_rule=THEME_RULE)
    user = REVIEW_USER.format(
        profile=profile_prompt(spec, config),
        accepted=_listing(accepted),
        pending=_listing(pending),
    )
    return system, user


def _key(text: str) -> str:
    return re.sub(r"[\W_]+", " ", text.casefold()).strip()


@dataclass(frozen=True)
class ReviewResult:
    ideas: BookIdeas  # z ostateczną numeracją i śladem w `review`
    usage: Usage
    warnings: list[str] = field(default_factory=list)


@dataclass
class IdeaReviewer:
    provider: TextProvider
    config: AppConfig
    max_topups: int = DEFAULT_MAX_TOPUPS

    def _judge(
        self, spec: BookSpec, pending: Sequence[PageIdea], accepted: Sequence[PageIdea]
    ) -> tuple[dict[str, _Verdict], Usage]:
        system, user = build_review_prompts(spec, self.config, pending, accepted)
        review, usage = self.provider.complete_json(system, user, _Review)
        return {v.id.strip(): v for v in review.verdicts}, usage

    @staticmethod
    def _apply(
        pending: Sequence[PageIdea],
        verdicts: dict[str, _Verdict],
        accepted: list[PageIdea],
        rejected: list[RejectedIdea],
        revised: list[tuple[PageIdea, RevisedIdea]],
        seen: set[str],
    ) -> None:
        """Werdykty jednej rundy: przyjęte i poprawione do `accepted`, reszta do `rejected`."""
        for idea in pending:
            verdict = verdicts.get(idea.id)  # brak werdyktu: pomysł zostaje
            final = idea
            if verdict is not None and verdict.verdict == "reject":
                rejected.append(
                    RejectedIdea(title=idea.title, scene=idea.scene, reason=verdict.reason)
                )
                continue
            if verdict is not None and verdict.verdict == "revise":
                if not verdict.revised_scene.strip():
                    rejected.append(
                        RejectedIdea(title=idea.title, scene=idea.scene, reason=verdict.reason)
                    )
                    continue
                final = PageIdea(
                    id=idea.id,
                    title=verdict.revised_title.strip() or idea.title,
                    scene=verdict.revised_scene,
                    elements=[e.strip() for e in verdict.revised_elements if e.strip()]
                    or list(idea.elements),
                    subject=tag(verdict.revised_subject) or idea.subject,
                    characters=verdict.revised_characters or idea.characters,
                    action=tag(verdict.revised_action) or idea.action,
                    setting=tag(verdict.revised_setting) or idea.setting,
                )
            if _key(final.scene) in seen:
                rejected.append(RejectedIdea(title=idea.title, scene=idea.scene, reason="duplikat"))
                continue
            seen.add(_key(final.scene))
            accepted.append(final)
            if final is not idea:
                revised.append(
                    (
                        final,
                        RevisedIdea(
                            id=idea.id,
                            original_title=idea.title,
                            original_scene=idea.scene,
                            reason=verdict.reason if verdict else "",
                        ),
                    )
                )

    def _balance(
        self, spec: BookSpec, pages: list[PageIdea], limits: DiversityLimits
    ) -> tuple[list[PageIdea], list[tuple[PageIdea, RevisedIdea]], Usage]:
        """Jedno wywołanie LLM poprawiające pomysły, które psują rozkład (FR-03b).

        Poprawka przechodzi tylko wtedy, gdy zmniejsza problemy rozkładu, więc model nie
        może ich pogorszyć. Zwraca strony, ślad poprawek i zużycie.
        """
        issues = measure(pages, limits)
        if not issues:
            return pages, [], Usage()
        budget = total_excess(issues)
        candidates = {idea_id for issue in issues for idea_id in issue.ids}
        system, user = build_balance_prompts(spec, self.config, pages, issues, budget)
        response, usage = self.provider.complete_json(system, user, _Balance)

        pages = list(pages)
        index = {idea.id: i for i, idea in enumerate(pages)}
        changed: list[tuple[PageIdea, RevisedIdea]] = []
        current = budget
        for proposal in response.ideas:
            idea_id = proposal.id.strip()
            done = {note.id for _, note in changed}
            if len(changed) >= budget or idea_id not in candidates - done or idea_id not in index:
                continue
            i = index[idea_id]
            original = pages[i]
            if not proposal.scene.strip():
                continue
            scenes = {_key(p.scene) for j, p in enumerate(pages) if j != i}
            if _key(proposal.scene) in scenes:
                continue
            new = PageIdea(
                id=idea_id,
                title=proposal.title.strip() or original.title,
                scene=proposal.scene,
                elements=[e.strip() for e in proposal.elements if e.strip()],
                subject=tag(proposal.subject),
                characters=max(proposal.characters, 0),
                action=tag(proposal.action),
                setting=tag(proposal.setting),
            )
            trial = [*pages[:i], new, *pages[i + 1 :]]
            score = total_excess(measure(trial, limits))
            if score >= current:
                continue
            pages, current = trial, score
            changed.append(
                (
                    new,
                    RevisedIdea(
                        id=idea_id,
                        original_title=original.title,
                        original_scene=original.scene,
                        reason=f"różnorodność: {proposal.reason}".rstrip(": "),
                    ),
                )
            )
        return pages, changed, usage

    def review(self, spec: BookSpec, ideas: BookIdeas, generator: IdeaGenerator) -> ReviewResult:
        expected = spec.pages + reserve_count(spec.pages, self.config.settings.reserve_ratio)
        accepted: list[PageIdea] = []
        rejected: list[RejectedIdea] = []
        revised: list[tuple[PageIdea, RevisedIdea]] = []  # (poprawiony pomysł, ślad)
        seen: set[str] = set()
        usage = Usage()
        pending = list(ideas.pages)
        next_number = len(pending) + 1
        added = rounds = 0

        while True:
            rounds += 1
            verdicts, call_usage = self._judge(spec, pending, accepted)
            usage += call_usage
            self._apply(pending, verdicts, accepted, rejected, revised, seen)

            missing = expected - len(accepted)
            if missing <= 0 or rounds > self.max_topups:
                break
            known = accepted + [
                PageIdea(id="idea_00", title=r.title, scene=r.scene, elements=[]) for r in rejected
            ]
            pending, call_usage = generator.generate_more(spec, missing, known, next_number)
            usage += call_usage
            next_number += len(pending)
            added += len(pending)
            if not pending:
                break

        if len(accepted) < spec.pages:
            raise ProviderError(
                f"po weryfikacji zostało {len(accepted)} dobrych pomysłów, a potrzeba "
                f"{spec.pages} (odrzucono {len(rejected)}, dogenerowano {added})"
            )
        # FR-03b: wyrównanie rozkładu na stronach książki, najpierw zamianą z zapasem (bez API),
        # potem jednym wywołaniem LLM dla tego, czego zapas nie naprawił.
        limits = DiversityLimits.from_config(spec, self.config, ideas.theme_anchors)
        book, reserve, moved = swap_with_reserve(
            accepted[: spec.pages], accepted[spec.pages : expected], limits
        )
        book, balanced, call_usage = self._balance(spec, book, limits)
        usage += call_usage
        revised += balanced
        accepted = book + reserve
        diversity = diversity_report(book, limits, moved_from_reserve=moved, revised=len(balanced))

        warnings: list[str] = []
        if len(accepted) < expected:
            warnings.append(
                f"po weryfikacji zapas na odrzucone strony to {len(accepted) - spec.pages} "
                f"zamiast {expected - spec.pages}"
            )
        warnings += [f"różnorodność: {issue}" for issue in diversity.issues]

        # Ostateczna numeracja idea_01… w kolejności przyjęcia.
        final_ids = {
            idea.id: f"idea_{i:02d}" for i, idea in enumerate(accepted[:expected], start=1)
        }
        pages = [idea.model_copy(update={"id": final_ids[idea.id]}) for idea in accepted[:expected]]
        trail = [
            note.model_copy(update={"id": final_ids[idea.id]})
            for idea, note in revised
            if idea.id in final_ids
        ]
        result = ideas.model_copy(
            update={
                "pages": pages,
                "review": IdeaReview(rejected=rejected, revised=trail, added=added, rounds=rounds),
                "diversity": diversity,
            }
        )
        return ReviewResult(ideas=result, usage=usage, warnings=warnings)

    def replace(
        self,
        spec: BookSpec,
        ideas: BookIdeas,
        ids: Sequence[str],
        generator: IdeaGenerator,
        *,
        review: bool = True,
    ) -> ReviewResult:
        """FR-17 `--redo`: nowe pomysły w miejsce `ids`, z tymi samymi id.

        Nowe pomysły różnią się od wszystkich w książce, także od zastępowanych, i przechodzą
        weryfikację (gdy `review`). Zastąpione trafiają do śladu `review.rejected`.
        """
        targets = list(dict.fromkeys(ids))
        by_id = {idea.id: idea for idea in ideas.pages}
        others = [idea for idea in ideas.pages if idea.id not in targets]
        fresh: list[PageIdea] = []
        rejected: list[RejectedIdea] = [
            RejectedIdea(title=by_id[i].title, scene=by_id[i].scene, reason="zastąpiony (--redo)")
            for i in targets
        ]
        revised: list[tuple[PageIdea, RevisedIdea]] = []
        seen = {_key(idea.scene) for idea in ideas.pages}
        usage = Usage()
        next_number = max((int(i.id.split("_")[1]) for i in ideas.pages), default=0) + 1
        added = rounds = 0

        while len(fresh) < len(targets) and rounds <= self.max_topups:
            rounds += 1
            known = [
                *ideas.pages,
                *fresh,
                *(
                    PageIdea(id="idea_00", title=r.title, scene=r.scene, elements=[])
                    for r in rejected
                ),
            ]
            pending, call_usage = generator.generate_more(
                spec, len(targets) - len(fresh), known, next_number
            )
            usage += call_usage
            next_number += len(pending)
            added += len(pending)
            if not pending:
                break
            verdicts: dict[str, _Verdict] = {}
            if review:
                verdicts, call_usage = self._judge(spec, pending, others + fresh)
                usage += call_usage
            self._apply(pending, verdicts, fresh, rejected, revised, seen)

        if len(fresh) < len(targets):
            raise ProviderError(
                f"udało się wymyślić {len(fresh)} z {len(targets)} nowych pomysłów "
                f"(odrzucono {len(rejected) - len(targets)})"
            )
        new_ids = {idea.id: target for idea, target in zip(fresh, targets, strict=False)}
        replacements = {
            new_ids[idea.id]: idea.model_copy(update={"id": new_ids[idea.id]})
            for idea in fresh[: len(targets)]
        }
        pages = [replacements.get(idea.id, idea) for idea in ideas.pages]
        trail = [
            note.model_copy(update={"id": new_ids[idea.id]})
            for idea, note in revised
            if idea.id in new_ids
        ]
        old = ideas.review or IdeaReview(rounds=0)
        history = IdeaReview(
            rejected=[*old.rejected, *rejected],
            revised=[*old.revised, *trail],
            added=old.added + added,
            rounds=old.rounds + rounds,
        )
        limits = DiversityLimits.from_config(spec, self.config, ideas.theme_anchors)
        diversity = diversity_report(pages[: spec.pages], limits)
        result = ideas.model_copy(
            update={"pages": pages, "review": history, "diversity": diversity}
        )
        warnings = [f"różnorodność: {issue}" for issue in diversity.issues]
        return ReviewResult(ideas=result, usage=usage, warnings=warnings)
