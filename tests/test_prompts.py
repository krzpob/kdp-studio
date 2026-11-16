from __future__ import annotations

from typing import Any

import pytest

from kdp_studio.config import AppConfig
from kdp_studio.models import BookIdeas, BookSpec
from kdp_studio.pipeline.prompts import FIXED_CONSTRAINTS, PromptBuilder

# Spec FR-04: stałe ograniczenia w każdym prompcie.
SPEC_CONSTRAINTS = [
    "black and white line art",
    "coloring book page",
    "single illustration",
    "one scene",
    "pure white background",
    "closed outlines",
    "no shading",
    "no grayscale",
    "no text",
    "no grid",
    "no multiple panels",
    "no collage",
    "no frame",
]


def _spec(**overrides: Any) -> BookSpec:
    data: dict[str, Any] = {
        "theme": "Świąteczne misie",
        "age": "wczesnoszkolne",
        "style": "cozy",
        "format": "square",
        "pages": 2,
        "front_matter_pages": 2,
        **overrides,
    }
    return BookSpec(**data)


def _ideas(*scenes: str) -> BookIdeas:
    return BookIdeas.model_validate(
        {
            "book": {"title": "T", "subtitle": "", "description": "D", "keywords": []},
            "pages": [
                {"id": f"idea_{i:02d}", "title": f"Page {i}", "scene": scene, "elements": []}
                for i, scene in enumerate(scenes, start=1)
            ],
        }
    )


IDEAS = _ideas(
    "A bear hanging an ornament on a small tree.",
    "A bear rolling gingerbread dough",
    "Two bears building a snowman",
)


def test_fixed_constraints_match_spec() -> None:
    assert FIXED_CONSTRAINTS.split(", ") == SPEC_CONSTRAINTS


def test_prompt_combines_scene_and_profiles(repo_config: AppConfig) -> None:
    prompt = PromptBuilder(_spec(), repo_config).build(IDEAS).pages[0].prompt
    assert prompt.startswith("Scene: A bear hanging an ornament on a small tree.\n")
    assert repo_config.styles["cozy"].prompt_fragment in prompt
    assert repo_config.ages["wczesnoszkolne"].prompt_fragment in prompt
    assert repo_config.formats["square"].composition_hint in prompt
    for constraint in SPEC_CONSTRAINTS:
        assert constraint in prompt


def test_style_block_is_identical_for_every_page(repo_config: AppConfig) -> None:
    prompts = PromptBuilder(_spec(), repo_config).build(IDEAS)
    for page in prompts.pages:
        scene_line, block = page.prompt.split("\n", 1)
        assert scene_line.startswith("Scene: ")
        assert block == prompts.style_block


def test_every_idea_gets_a_prompt_including_reserve(repo_config: AppConfig) -> None:
    prompts = PromptBuilder(_spec(pages=2), repo_config).build(IDEAS)
    assert [p.idea_id for p in prompts.pages] == ["idea_01", "idea_02", "idea_03"]


def test_scene_gets_exactly_one_period(repo_config: AppConfig) -> None:
    pages = PromptBuilder(_spec(), repo_config).build(IDEAS).pages
    assert pages[0].prompt.splitlines()[0] == "Scene: A bear hanging an ornament on a small tree."
    assert pages[1].prompt.splitlines()[0] == "Scene: A bear rolling gingerbread dough."


def test_multiline_yaml_fragments_are_flattened(repo_config: AppConfig) -> None:
    block = PromptBuilder(_spec(), repo_config).style_block
    assert len(block.splitlines()) == 4
    assert "  " not in block


@pytest.mark.parametrize(
    ("field", "value", "fragment"),
    [
        ("format", "letter", "vertical composition, main subjects fill most of the portrait frame"),
        ("age", "dorosli", "fine intricate line work"),
        ("age", "nastolatki", "detailed background may extend to the edges"),
        ("style", "mandala", "mandala style, radially symmetric"),
    ],
)
def test_profiles_change_the_style_block(
    repo_config: AppConfig, field: str, value: str, fragment: str
) -> None:
    default = PromptBuilder(_spec(), repo_config).style_block
    changed = PromptBuilder(_spec(**{field: value}), repo_config).style_block
    assert fragment in changed
    assert fragment not in default
