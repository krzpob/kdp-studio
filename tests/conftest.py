from __future__ import annotations

import re
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import yaml

from kdp_studio.config import DEFAULT_CONFIG_DIR, AppConfig, load_config

ConfigDirFactory = Callable[..., Path]


@pytest.fixture(scope="session")
def repo_config() -> AppConfig:
    """Konfiguracja z katalogu config/ w repozytorium."""
    return load_config(DEFAULT_CONFIG_DIR)


@pytest.fixture
def config_dir(tmp_path: Path) -> ConfigDirFactory:
    """Kopia config/ w tmp_path; argumenty nazwane nadpisują zawartość plików.

    Przykład: config_dir(settings={"front_matter_pages": 0}).
    """

    def factory(**overrides: Any) -> Path:
        target = tmp_path / "config"
        shutil.copytree(DEFAULT_CONFIG_DIR, target, dirs_exist_ok=True)
        for name, data in overrides.items():
            (target / f"{name}.yaml").write_text(
                yaml.safe_dump(data, allow_unicode=True), encoding="utf-8"
            )
        return target

    return factory


def scene_tags(
    subject: str = "dinosaur", characters: int = 1, action: str = "", setting: str = ""
) -> dict[str, Any]:
    """Cechy sceny (FR-03b) w odpowiedzi LLM. Puste czynność i miejsce pomiar pomija."""
    return {"subject": subject, "characters": characters, "action": action, "setting": setting}


def llm_ideas_response(count: int, **book: Any) -> dict[str, Any]:
    """Odpowiedź LLM w kształcie schematu `_LLMIdeas` z `count` różnymi pomysłami.

    Co drugi pomysł ma dwie postacie, a przedmioty się nie powtarzają, więc rozkład
    spełnia limity różnorodności (FR-03b) i nie wywołuje wyrównania.
    """
    return {
        "book": {
            "title": "Dino Friends",
            "subtitle": "A Coloring Book for Toddlers",
            "description": "Big, simple dinosaurs to color.",
            "keywords": ["dinosaur coloring book", "toddler coloring"],
            **book,
        },
        "theme_anchors": [],
        "pages": [
            {
                "title": f"Dinosaur {i}",
                "scene": f"A friendly dinosaur number {i} standing in a meadow",
                "elements": ["dinosaur", f"rock{i}"],
                **scene_tags(characters=2 if i % 2 else 1),
            }
            for i in range(1, count + 1)
        ],
    }


REVIEW_ID = re.compile(r"^(idea_\d+) \|", re.MULTILINE)


def review_response(user: str, **verdicts: dict[str, Any]) -> dict[str, Any]:
    """Werdykty weryfikacji dla pomysłów z sekcji "Ideas to review"; domyślnie `ok`."""
    pending = user.split("Ideas to review:", 1)[1]
    result = []
    for idea_id in REVIEW_ID.findall(pending):
        verdict = {
            "id": idea_id,
            "verdict": "ok",
            "reason": "",
            "revised_title": "",
            "revised_scene": "",
            "revised_elements": [],
            "revised_subject": "",
            "revised_characters": 0,
            "revised_action": "",
            "revised_setting": "",
        }
        verdict.update(verdicts.get(idea_id, {}))
        result.append(verdict)
    return {"verdicts": result}


def approve_all(system: str, user: str) -> dict[str, Any]:
    return review_response(user)
