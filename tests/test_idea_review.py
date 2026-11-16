from __future__ import annotations

from typing import Any

import pytest

from kdp_studio.config import AppConfig
from kdp_studio.models import BookIdeas, BookSpec
from kdp_studio.pipeline.idea_review import IdeaReviewer, build_review_prompts
from kdp_studio.pipeline.ideas import THEME_RULE, IdeaGenerator, build_prompts
from kdp_studio.providers.base import ProviderError, Usage
from kdp_studio.providers.fake import FakeTextProvider
from tests.conftest import approve_all, llm_ideas_response, review_response, scene_tags


def _spec(pages: int = 10) -> BookSpec:
    return BookSpec(
        theme="Świąteczne kotki",
        age="wczesnoszkolne",
        style="cozy",
        format="square",
        pages=pages,
        front_matter_pages=2,
    )


def _ideas(config: AppConfig, count: int = 12) -> BookIdeas:
    provider = FakeTextProvider([llm_ideas_response(count)])
    return IdeaGenerator(provider, config).generate(_spec()).ideas


def _more(start: int, count: int) -> dict[str, Any]:
    return {
        "pages": [
            {
                "title": f"New idea {i}",
                "scene": f"A kitten hanging ornament {i}",
                "elements": ["kitten"],
                **scene_tags(subject="kitten", characters=2),
            }
            for i in range(start, start + count)
        ]
    }


def _review(
    config: AppConfig, review: Any, more: list[Any] | None = None, count: int = 12
) -> tuple[Any, FakeTextProvider]:
    ideas = _ideas(config, count)
    provider = FakeTextProvider(more or [_more(100, 10)], routes={"_Review": review})
    generator = IdeaGenerator(provider, config)
    result = IdeaReviewer(provider, config).review(_spec(), ideas, generator)
    return result, provider


# --- Prompty -------------------------------------------------------------------------


def test_theme_rule_is_in_generation_and_review_prompts(repo_config: AppConfig) -> None:
    system, _ = build_prompts(_spec(), repo_config)
    assert THEME_RULE in system
    assert '"holiday" or "festive" do not count' in THEME_RULE
    assert "snowmen, sleds" in THEME_RULE  # motywy typowe dla tematu się liczą
    review_system, review_user = build_review_prompts(
        _spec(), repo_config, _ideas(repo_config).pages[:2], []
    )
    assert THEME_RULE in review_system
    assert "Write `reason` in Polish" in review_system
    assert "Do not polish ideas that already pass" in review_system
    assert "vary the added theme elements" in review_system
    assert "Świąteczne kotki" in review_user
    assert "idea_01 | Dinosaur 1 | A friendly dinosaur number 1" in review_user
    assert (
        "Already accepted ideas (do not judge; use only to spot duplicates):\n(none)" in review_user
    )


# --- Werdykty ------------------------------------------------------------------------


def test_all_ok_keeps_ideas_and_ids(repo_config: AppConfig) -> None:
    result, provider = _review(repo_config, approve_all)
    assert [p.id for p in result.ideas.pages] == [f"idea_{i:02d}" for i in range(1, 13)]
    assert result.ideas.review is not None
    assert result.ideas.review.rejected == []
    assert result.ideas.review.rounds == 1
    assert result.warnings == []
    assert result.usage == Usage(input_tokens=100, output_tokens=50)
    assert [c.schema.__name__ for c in provider.calls] == ["_Review"]


def test_revise_replaces_scene_and_keeps_trail(repo_config: AppConfig) -> None:
    def revise(system: str, user: str) -> dict[str, Any]:
        return review_response(
            user,
            idea_03={
                "verdict": "revise",
                "reason": "brak elementu świątecznego",
                "revised_title": "Gingerbread Baker",
                "revised_scene": "A kitten in an apron cutting gingerbread cookies",
                "revised_elements": ["kitten", "gingerbread cookies", " "],
            },
        )

    result, _ = _review(repo_config, revise)
    page = result.ideas.pages[2]
    assert (page.id, page.title) == ("idea_03", "Gingerbread Baker")
    assert page.scene == "A kitten in an apron cutting gingerbread cookies"
    assert page.elements == ["kitten", "gingerbread cookies"]
    assert result.ideas.review is not None
    [trail] = result.ideas.review.revised
    assert (trail.id, trail.original_title, trail.reason) == (
        "idea_03",
        "Dinosaur 3",
        "brak elementu świątecznego",
    )


def test_revise_without_scene_counts_as_reject(repo_config: AppConfig) -> None:
    result, _ = _review(
        repo_config,
        lambda s, u: review_response(u, idea_01={"verdict": "revise", "reason": "?"}),
        count=11,
    )
    assert "Dinosaur 1" not in [p.title for p in result.ideas.pages]


def test_rejected_ideas_are_recorded_with_reasons(repo_config: AppConfig) -> None:
    def reject_two(system: str, user: str) -> dict[str, Any]:
        if "Dinosaur" not in user.split("Ideas to review:", 1)[1]:
            return review_response(user)
        return review_response(
            user,
            idea_02={"verdict": "reject", "reason": "tort urodzinowy"},
            idea_05={"verdict": "reject", "reason": "herbatka bez świąt"},
        )

    result, _ = _review(repo_config, reject_two)
    review = result.ideas.review
    assert review is not None
    titles = [p.title for p in result.ideas.pages]
    assert len(titles) == 12  # zapas uzupełniony nowymi pomysłami
    assert "Dinosaur 2" not in titles and "Dinosaur 5" not in titles
    assert [r.reason for r in review.rejected] == ["tort urodzinowy", "herbatka bez świąt"]
    assert review.added == 2


def test_missing_reserve_is_topped_up_and_reviewed(repo_config: AppConfig) -> None:
    def reject_first_round(system: str, user: str) -> dict[str, Any]:
        pending = user.split("Ideas to review:", 1)[1]
        if "Dinosaur" in pending:
            return review_response(
                user,
                idea_01={"verdict": "reject", "reason": "x"},
                idea_02={"verdict": "reject", "reason": "y"},
            )
        return review_response(user)

    result, provider = _review(repo_config, reject_first_round)
    names = [c.schema.__name__ for c in provider.calls]
    assert names == ["_Review", "_LLMMoreIdeas", "_Review"]
    titles = [p.title for p in result.ideas.pages]
    assert len(titles) == 12
    assert titles[-2:] == ["New idea 100", "New idea 101"]
    assert [p.id for p in result.ideas.pages] == [f"idea_{i:02d}" for i in range(1, 13)]
    assert result.ideas.review.added == 2
    assert result.ideas.review.rounds == 2
    more_prompt = provider.calls[1].user
    assert "Return exactly 2 NEW page ideas" in more_prompt
    assert "- Dinosaur 1: A friendly dinosaur number 1" in more_prompt  # odrzucone też unikamy


def test_short_reserve_after_topups_is_a_warning(repo_config: AppConfig) -> None:
    def reject_reserve(system: str, user: str) -> dict[str, Any]:
        pending = user.split("Ideas to review:", 1)[1]
        if "Dinosaur" in pending:
            return review_response(user, idea_12={"verdict": "reject", "reason": "x"})
        return review_response(
            user, **{f"idea_{i}": {"verdict": "reject", "reason": "y"} for i in range(13, 40)}
        )

    result, _ = _review(repo_config, reject_reserve, more=[_more(200, 1)])
    assert len(result.ideas.pages) == 11
    assert result.warnings == ["po weryfikacji zapas na odrzucone strony to 1 zamiast 2"]


def test_too_few_ideas_after_review_is_an_error(repo_config: AppConfig) -> None:
    def reject_most(system: str, user: str) -> dict[str, Any]:
        return review_response(
            user, **{f"idea_{i:02d}": {"verdict": "reject", "reason": "z"} for i in range(1, 99)}
        )

    with pytest.raises(ProviderError, match="po weryfikacji zostało 0 dobrych pomysłów"):
        _review(repo_config, reject_most, more=[{"pages": []}])


def test_duplicate_after_revision_is_rejected(repo_config: AppConfig) -> None:
    def make_duplicate(system: str, user: str) -> dict[str, Any]:
        return review_response(
            user,
            idea_04={
                "verdict": "revise",
                "reason": "r",
                "revised_title": "T",
                "revised_scene": "A friendly dinosaur number 1 standing in a meadow",
                "revised_elements": [],
            },
        )

    result, _ = _review(repo_config, make_duplicate, count=13)
    scenes = [p.scene for p in result.ideas.pages]
    assert len(scenes) == len(set(scenes)) == 12
    assert result.ideas.review.rejected[0].reason == "duplikat"
