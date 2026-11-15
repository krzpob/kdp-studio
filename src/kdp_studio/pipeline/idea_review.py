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
from kdp_studio.pipeline.ideas import THEME_RULE, IdeaGenerator, profile_prompt, reserve_count
from kdp_studio.providers.base import ProviderError, TextProvider, Usage

DEFAULT_MAX_TOPUPS = 2


class _Verdict(BaseModel):
    id: str = Field(description="Idea id exactly as given, e.g. idea_07.")
    verdict: Literal["ok", "revise", "reject"]
    reason: str = Field(description="Short reason in Polish; empty when the verdict is ok.")
    revised_title: str = Field(description="Only for revise; otherwise empty.")
    revised_scene: str = Field(description="Only for revise: the full corrected scene, English.")
    revised_elements: list[str] = Field(description="Only for revise; otherwise empty.")


class _Review(BaseModel):
    verdicts: list[_Verdict]


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


def _listing(ideas: Sequence[PageIdea]) -> str:
    lines = [
        f"{idea.id} | {idea.title} | {idea.scene} | elements: {', '.join(idea.elements)}"
        for idea in ideas
    ]
    return "\n".join(lines) or "(none)"


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
                    )
                if _key(final.scene) in seen:
                    rejected.append(
                        RejectedIdea(title=idea.title, scene=idea.scene, reason="duplikat")
                    )
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
        warnings: list[str] = []
        if len(accepted) < expected:
            warnings.append(
                f"po weryfikacji zapas na odrzucone strony to {len(accepted) - spec.pages} "
                f"zamiast {expected - spec.pages}"
            )

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
            }
        )
        return ReviewResult(ideas=result, usage=usage, warnings=warnings)
