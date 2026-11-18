from __future__ import annotations

from typing import Any

import pytest

from kdp_studio.config import AppConfig
from kdp_studio.models import BookSpec
from kdp_studio.pipeline.ideas import IdeaGenerator, build_prompts, reserve_count
from kdp_studio.providers.base import ProviderError, Usage
from kdp_studio.providers.fake import FakeTextProvider
from tests.conftest import llm_ideas_response


def _spec(pages: int = 10, **overrides: Any) -> BookSpec:
    data: dict[str, Any] = {
        "theme": "Dinozaury",
        "age": "przedszkole",
        "style": "kawaii",
        "format": "square",
        "pages": pages,
        "front_matter_pages": 2,
        **overrides,
    }
    return BookSpec(**data)


def _generate(config: AppConfig, *responses: Any, pages: int = 10) -> Any:
    provider = FakeTextProvider(list(responses))
    return IdeaGenerator(provider, config).generate(_spec(pages)), provider


@pytest.mark.parametrize(("pages", "ratio", "expected"), [(30, 0.2, 6), (10, 0.2, 2), (1, 0.2, 1)])
def test_reserve_count(pages: int, ratio: float, expected: int) -> None:
    assert reserve_count(pages, ratio) == expected


# --- Prompt --------------------------------------------------------------------------


def test_prompt_contains_profiles_and_count(repo_config: AppConfig) -> None:
    system, user = build_prompts(_spec(30), repo_config)
    age = repo_config.ages["przedszkole"]
    assert "Dinozaury" in user
    assert age.prompt_fragment in user
    assert age.subjects in user
    assert repo_config.styles["kawaii"].prompt_fragment in user
    assert repo_config.formats["square"].composition_hint in user
    assert "exactly 36 page ideas (30 pages plus 6 reserve" in user
    assert "The printed book has 30 coloring pages" in user
    assert "it must be 30" in user
    assert "copyrighted or trademarked characters" in system
    assert "in English" in system
    assert "Vary the book as a whole" in system
    assert "scenes with several characters: not required" in user  # przedszkole


@pytest.mark.parametrize(
    ("market", "language", "word", "audience"),
    [
        ("US", "American English", "Coloring Book", "for Kids Ages 3–5"),
        ("UK", "British English", "Colouring Book", "for Kids Ages 3–5"),
        ("DE", "German", "Malbuch", "für Kinder von 3 bis 5 Jahren"),
    ],
)
def test_prompt_uses_the_market_language(
    repo_config: AppConfig, market: str, language: str, word: str, audience: str
) -> None:
    system, _ = build_prompts(_spec(market=market), repo_config)
    domain = repo_config.markets.markets[market].domain
    assert f"sold on {domain}" in system
    assert f"keywords in {language}," in system
    assert f'Call the book a "{word}"' in system
    assert f'write it as "{audience}"' in system
    adults, _ = build_prompts(_spec(market=market, age="dorosli", style="mandala"), repo_config)
    assert repo_config.markets.markets[market].terms.adults in adults


def test_prompt_follows_format(repo_config: AppConfig) -> None:
    _, user = build_prompts(_spec(format="letter"), repo_config)
    assert repo_config.formats["letter"].composition_hint in user


# --- Wynik ---------------------------------------------------------------------------


def test_exact_count(repo_config: AppConfig) -> None:
    result, provider = _generate(repo_config, llm_ideas_response(12))
    ideas = result.ideas
    assert [p.id for p in ideas.pages] == [f"idea_{i:02d}" for i in range(1, 13)]
    assert ideas.pages[0].scene == "A friendly dinosaur number 1 standing in a meadow"
    assert ideas.book.title == "Dino Friends"
    assert result.warnings == []
    assert result.attempts == 1
    assert result.usage == Usage(input_tokens=100, output_tokens=50)
    assert len(provider.calls) == 1


def test_surplus_is_trimmed(repo_config: AppConfig) -> None:
    result, _ = _generate(repo_config, llm_ideas_response(20))
    assert len(result.ideas.pages) == 12


def test_smaller_reserve_is_a_warning(repo_config: AppConfig) -> None:
    result, provider = _generate(repo_config, llm_ideas_response(11))
    assert len(result.ideas.pages) == 11
    assert result.warnings == [
        "model zwrócił 11 unikalnych pomysłów zamiast 12; zapas na odrzucone strony to 1"
    ]
    assert len(provider.calls) == 1


def test_too_few_ideas_retries(repo_config: AppConfig) -> None:
    result, provider = _generate(repo_config, llm_ideas_response(5), llm_ideas_response(12))
    assert result.attempts == 2
    assert len(result.ideas.pages) == 12
    assert len(provider.calls) == 2
    assert result.usage == Usage(input_tokens=200, output_tokens=100)


def test_too_few_ideas_after_all_attempts(repo_config: AppConfig) -> None:
    with pytest.raises(ProviderError, match="5 unikalnych pomysłów zamiast co najmniej 10"):
        _generate(repo_config, llm_ideas_response(5))


def test_duplicates_are_removed(repo_config: AppConfig) -> None:
    response = llm_ideas_response(15)
    pages = response["pages"]
    pages[3]["title"] = "  dinosaur 1!"  # ten sam tytuł co strona 1
    pages[5]["scene"] = pages[4]["scene"].upper()  # ta sama scena co strona 5
    pages[7]["scene"] = "   "  # pusta scena
    result, _ = _generate(repo_config, response)
    titles = [p.title for p in result.ideas.pages]
    assert titles == [f"Dinosaur {i}" for i in (1, 2, 3, 5, 7, 9, 10, 11, 12, 13, 14, 15)]
    assert [p.id for p in result.ideas.pages][-1] == "idea_12"


def test_keywords_are_deduplicated_and_capped(repo_config: AppConfig) -> None:
    keywords = ["Dinosaurs", "dinosaurs ", "", *[f"kw {i}" for i in range(10)]]
    result, _ = _generate(repo_config, llm_ideas_response(12, keywords=keywords))
    assert result.ideas.book.keywords == [
        "Dinosaurs",
        "kw 0",
        "kw 1",
        "kw 2",
        "kw 3",
        "kw 4",
        "kw 5",
    ]


def test_invalid_metadata_retries(repo_config: AppConfig) -> None:
    result, provider = _generate(
        repo_config, llm_ideas_response(12, title="  "), llm_ideas_response(12)
    )
    assert result.attempts == 2
    assert len(provider.calls) == 2
    assert result.ideas.book.title == "Dino Friends"


def test_invalid_metadata_after_all_attempts(repo_config: AppConfig) -> None:
    with pytest.raises(ProviderError, match=r"niepoprawne metadane książki \(title\)"):
        _generate(repo_config, llm_ideas_response(12, title=""))


def test_elements_are_cleaned(repo_config: AppConfig) -> None:
    response = llm_ideas_response(12)
    response["pages"][0]["elements"] = ["Tree", "tree", " ", "rock"]
    result, _ = _generate(repo_config, response)
    assert result.ideas.pages[0].elements == ["Tree", "rock"]
