from __future__ import annotations

import json
from typing import Any

from kdp_studio.config import AppConfig
from kdp_studio.models import BookIdeas, BookMetadata, BookSpec, PageIdea
from kdp_studio.pipeline.diversity import (
    DiversityLimits,
    diversity_report,
    element_keys,
    measure,
    noun,
    swap_with_reserve,
    total_excess,
)
from kdp_studio.pipeline.idea_review import IdeaReviewer, build_balance_prompts
from kdp_studio.pipeline.ideas import IdeaGenerator, build_prompts
from kdp_studio.providers.fake import FakeTextProvider
from tests.conftest import approve_all, llm_ideas_response, review_response

LIMITS = DiversityLimits(
    multi_subject_share=0.3, max_action_share=0.3, max_setting_share=0.3, max_element_share=0.35
)


def _idea(
    n: int,
    characters: int | None = 1,
    action: str | None = None,
    setting: str | None = None,
    elements: list[str] | None = None,
) -> PageIdea:
    return PageIdea(
        id=f"idea_{n:02d}",
        title=f"Idea {n}",
        scene=f"A kitten number {n}",
        elements=["kitten", *(elements or [f"thing{n}"])],
        subject="kitten",
        characters=characters,
        action=action,
        setting=setting,
    )


def _spec(pages: int = 10, age: str = "wczesnoszkolne") -> BookSpec:
    return BookSpec(
        theme="Świąteczne kotki",
        age=age,
        style="cozy",
        format="square",
        pages=pages,
        front_matter_pages=2,
    )


# --- Pomiar --------------------------------------------------------------------------


def test_too_few_multi_character_scenes() -> None:
    pages = [_idea(i, characters=2 if i <= 2 else 1) for i in range(1, 11)]
    [issue] = measure(pages, LIMITS)
    assert (issue.kind, issue.count, issue.limit, issue.excess) == ("characters", 2, 3, 1)
    assert issue.ids == tuple(f"idea_{i:02d}" for i in range(3, 11))
    assert issue.message() == ("sceny z kilkoma postaciami: 2 z 10 stron, wymagane co najmniej 3")
    assert "Turn 1 single-character ideas" in issue.instruction()


def test_multi_subject_share_zero_disables_the_check() -> None:
    limits = DiversityLimits(0.0, 0.3, 0.3, 0.35)
    assert measure([_idea(i) for i in range(1, 11)], limits) == []


def test_repeated_action_setting_and_object() -> None:
    pages = [
        _idea(
            i,
            characters=2,
            action="sit" if i <= 4 else f"act{i}",
            setting="living room" if i <= 5 else f"place{i}",
            elements=["decorated trees"] if i <= 4 else [f"thing{i}"],
        )
        for i in range(1, 11)
    ]
    issues = {issue.kind: issue for issue in measure(pages, LIMITS)}
    assert set(issues) == {"action", "setting", "element"}
    assert (issues["action"].value, issues["action"].count, issues["action"].limit) == (
        "sit",
        4,
        3,
    )
    assert issues["setting"].excess == 2
    assert issues["element"].value == "tree"
    assert issues["element"].message() == "przedmiot „tree” na 4 z 10 stron, najwyżej 3"
    assert total_excess(list(issues.values())) == 4
    # Od największego przekroczenia.
    assert measure(pages, LIMITS)[0].kind == "setting"


def test_theme_anchors_are_exempt(repo_config: AppConfig) -> None:
    pages = [
        _idea(i, characters=2, setting="kitchen", elements=["Mixing Bowls"]) for i in range(1, 11)
    ]
    plain = DiversityLimits.from_config(_spec(), repo_config)
    assert {i.kind for i in measure(pages, plain)} == {"setting", "element"}
    anchored = DiversityLimits.from_config(_spec(), repo_config, ["Kitchen", "mixing bowl"])
    assert anchored.exempt == {"kitchen", "mixing bowl", "bowl"}
    assert measure(pages, anchored) == []


def test_generator_keeps_theme_anchors(repo_config: AppConfig) -> None:
    response = llm_ideas_response(12)
    response["theme_anchors"] = ["Kitchen", "kitchen ", " "]
    ideas = IdeaGenerator(FakeTextProvider([response]), repo_config).generate(_spec()).ideas
    assert ideas.theme_anchors == ["kitchen"]


def test_untagged_ideas_are_ignored() -> None:
    pages = [_idea(i, characters=None) for i in range(1, 11)]
    assert measure(pages, LIMITS) == []


def test_element_keys_skip_the_main_character() -> None:
    idea = _idea(1, elements=["two kittens", "Christmas Trees", "glass", "bus"])
    assert element_keys(idea) == {"tree", "glass", "bus"}
    assert noun("Wrapped gifts.") == "gift"


# --- Zamiana z zapasem -----------------------------------------------------------------


def test_swap_with_reserve_fixes_the_cast() -> None:
    pages = [_idea(i, characters=1) for i in range(1, 11)]
    reserve = [_idea(i, characters=2) for i in range(11, 15)]
    new_pages, new_reserve, moves = swap_with_reserve(pages, reserve, LIMITS)
    assert moves == 3
    assert sum(1 for p in new_pages if p.characters == 2) == 3
    assert len(new_pages) == 10 and len(new_reserve) == 4
    assert {p.id for p in new_pages + new_reserve} == {p.id for p in pages + reserve}


def test_swap_stops_when_reserve_does_not_help() -> None:
    pages = [_idea(i) for i in range(1, 11)]
    reserve = [_idea(i) for i in range(11, 13)]
    new_pages, _, moves = swap_with_reserve(pages, reserve, LIMITS)
    assert moves == 0 and new_pages == pages


def test_report_counts_and_issues() -> None:
    pages = [_idea(i, action="sit", setting="kitchen") for i in range(1, 5)]
    report = diversity_report(pages, LIMITS, moved_from_reserve=2, revised=1)
    assert report.pages == 4
    assert report.characters == {"1": 4}
    assert report.actions == {"sit": 4}
    assert report.settings == {"kitchen": 4}
    assert len(report.issues) == 3
    assert (report.moved_from_reserve, report.revised) == (2, 1)


# --- Prompty --------------------------------------------------------------------------


def test_cast_target_comes_from_age_profile(repo_config: AppConfig) -> None:
    _, user = build_prompts(_spec(), repo_config)
    assert "two or three characters doing something together: at least 25% of the pages" in user
    _, user = build_prompts(_spec(age="przedszkole"), repo_config)
    assert "scenes with several characters: not required" in user


def test_balance_prompt_lists_problems_candidates_and_tags(repo_config: AppConfig) -> None:
    pages = [_idea(i, action="sit") for i in range(1, 11)]
    issues = measure(pages, LIMITS)
    system, user = build_balance_prompts(_spec(), repo_config, pages, issues, 9)
    assert "Change at most 9 ideas" in system
    assert "Every scene clearly belongs to the theme" in system
    assert 'use the action "sit"' in user
    assert "Candidates: idea_01, idea_02" in user
    assert "subject: kitten, characters: 1, action: sit, setting: None" in user


# --- Generator i weryfikacja ---------------------------------------------------------


def test_generator_normalizes_tags(repo_config: AppConfig) -> None:
    response = llm_ideas_response(12)
    response["pages"][0].update(
        subject=" Kitten ", characters=-1, action="  Decorate ", setting="Living   Room"
    )
    provider = FakeTextProvider([response])
    idea = IdeaGenerator(provider, repo_config).generate(_spec()).ideas.pages[0]
    assert (idea.subject, idea.characters, idea.action, idea.setting) == (
        "kitten",
        0,
        "decorate",
        "living room",
    )


def _single_cast(count: int) -> dict[str, Any]:
    response = llm_ideas_response(count)
    for page in response["pages"]:
        page["characters"] = 1
    return response


def _balanced(*changes: dict[str, Any]) -> dict[str, Any]:
    ideas = [
        {
            "id": "",
            "title": "Two kittens",
            "scene": "",
            "elements": ["kitten"],
            "subject": "kitten",
            "characters": 2,
            "action": "",
            "setting": "",
            "reason": "więcej postaci",
            **change,
        }
        for change in changes
    ]
    return {"ideas": ideas}


def _review(config: AppConfig, balance: Any, *, pages: int = 10, count: int = 12) -> Any:
    provider = FakeTextProvider(
        [_single_cast(count)], routes={"_Review": approve_all, "_Balance": balance}
    )
    generator = IdeaGenerator(provider, config)
    ideas = generator.generate(_spec(pages)).ideas
    result = IdeaReviewer(provider, config).review(_spec(pages), ideas, generator)
    return result, provider


def test_balanced_book_makes_no_extra_call(repo_config: AppConfig) -> None:
    provider = FakeTextProvider([llm_ideas_response(12)], routes={"_Review": approve_all})
    generator = IdeaGenerator(provider, repo_config)
    ideas = generator.generate(_spec()).ideas
    result = IdeaReviewer(provider, repo_config).review(_spec(), ideas, generator)
    assert [c.schema.__name__ for c in provider.calls] == ["_LLMIdeas", "_Review"]
    assert result.ideas.diversity is not None
    assert result.ideas.diversity.issues == []


def test_llm_revisions_fix_the_cast(repo_config: AppConfig) -> None:
    balance = _balanced(
        {"id": "idea_01", "scene": "Two kittens decorate a tree together"},
        {"id": "idea_02", "scene": "Two kittens build a snowman"},
        {"id": "idea_03", "scene": "Two kittens sled downhill"},
    )
    result, provider = _review(repo_config, balance)
    assert [c.schema.__name__ for c in provider.calls] == ["_LLMIdeas", "_Review", "_Balance"]
    pages = result.ideas.pages[:10]
    assert sum(1 for p in pages if (p.characters or 0) >= 2) == 3
    assert pages[0].scene == "Two kittens decorate a tree together"
    report = result.ideas.diversity
    assert report is not None
    assert (report.revised, report.issues) == (3, [])
    revised = result.ideas.review.revised
    assert [r.reason for r in revised] == ["różnorodność: więcej postaci"] * 3
    assert revised[0].original_scene == "A friendly dinosaur number 1 standing in a meadow"
    assert not any("różnorodność" in w for w in result.warnings)


def test_reserve_is_used_before_the_llm(repo_config: AppConfig) -> None:
    response = _single_cast(12)
    for page in (response["pages"][0], *response["pages"][10:]):
        page["characters"] = 2  # 1 na stronach książki i 2 w zapasie, a wymagane są 3
    provider = FakeTextProvider([response], routes={"_Review": approve_all})
    generator = IdeaGenerator(provider, repo_config)
    ideas = generator.generate(_spec()).ideas
    result = IdeaReviewer(provider, repo_config).review(_spec(), ideas, generator)
    assert "_Balance" not in [c.schema.__name__ for c in provider.calls]
    report = result.ideas.diversity
    assert report is not None
    assert (report.moved_from_reserve, report.revised, report.issues) == (2, 0, [])


def test_unhelpful_or_foreign_revisions_are_dropped(repo_config: AppConfig) -> None:
    balance = _balanced(
        {"id": "idea_01", "scene": "A kitten alone again", "characters": 1},  # nic nie daje
        {"id": "idea_99", "scene": "Two kittens nowhere"},  # spoza książki
        {"id": "idea_02", "scene": "A friendly dinosaur number 3 standing in a meadow"},  # duplikat
        {"id": "idea_04", "scene": "Two kittens skate"},
        {"id": "idea_04", "scene": "Two kittens skate again"},  # drugi raz ten sam
        {"id": "idea_05", "scene": ""},
    )
    result, _ = _review(repo_config, balance)
    report = result.ideas.diversity
    assert report is not None and report.revised == 1
    assert result.ideas.pages[3].scene == "Two kittens skate"
    assert report.issues == ["sceny z kilkoma postaciami: 1 z 10 stron, wymagane co najmniej 3"]
    assert "różnorodność: sceny z kilkoma postaciami: 1 z 10 stron" in result.warnings[-1]


def test_budget_limits_the_number_of_revisions(repo_config: AppConfig) -> None:
    balance = _balanced(
        *({"id": f"idea_{i:02d}", "scene": f"Two kittens play game {i}"} for i in range(1, 8))
    )
    result, _ = _review(repo_config, balance)
    report = result.ideas.diversity
    assert report is not None and report.revised == 3  # brakowało 3 scen


def test_review_revision_keeps_or_replaces_tags(repo_config: AppConfig) -> None:
    def review(system: str, user: str) -> dict[str, Any]:
        return review_response(
            user,
            idea_01={"verdict": "revise", "revised_scene": "A dinosaur bakes cookies"},
            idea_02={
                "verdict": "revise",
                "revised_scene": "Two dinosaurs bake cookies",
                "revised_characters": 2,
                "revised_action": "Bake",
                "revised_setting": "Kitchen",
            },
        )

    provider = FakeTextProvider([llm_ideas_response(12)], routes={"_Review": review})
    generator = IdeaGenerator(provider, repo_config)
    ideas = generator.generate(_spec()).ideas
    pages = IdeaReviewer(provider, repo_config).review(_spec(), ideas, generator).ideas.pages
    first, second = pages[0], pages[1]
    assert (first.subject, first.characters, first.action) == ("dinosaur", 2, None)
    assert (second.characters, second.action, second.setting) == (2, "bake", "kitchen")


# --- Starsze pliki ---------------------------------------------------------------


def test_old_ideas_without_tags_still_load() -> None:
    ideas = BookIdeas(
        book=BookMetadata(title="T", subtitle="", description="d", keywords=[]),
        pages=[PageIdea(id="idea_01", title="t", scene="s", elements=[])],
    )
    data = json.loads(ideas.model_dump_json())
    for key in ("subject", "characters", "action", "setting"):
        del data["pages"][0][key]
    del data["diversity"]
    assert BookIdeas.model_validate(data).pages[0].characters is None
