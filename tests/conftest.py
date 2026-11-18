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


# Ceny modeli fałszywych dostawców (FR-10), USD za 1M tokenów. Przy ich `usage_per_call`:
# wywołanie tekstowe $0.0002, grafika $0.0101, ocena QA $0.00104.
FAKE_PRICES: dict[str, dict[str, float]] = {
    "fake-text": {"input_per_1m": 1.0, "output_per_1m": 2.0},
    "fake-image": {"input_per_1m": 10.0, "output_per_1m": 100.0},
    "fake-vision": {"input_per_1m": 1.0, "output_per_1m": 2.0},
}
FAKE_IMAGE_COST = 0.0101


def fake_settings(**overrides: Any) -> dict[str, Any]:
    """settings.yaml z repozytorium z cenami fałszywych modeli i nadpisanymi kluczami."""
    settings: dict[str, Any] = yaml.safe_load(
        (DEFAULT_CONFIG_DIR / "settings.yaml").read_text(encoding="utf-8")
    )
    settings["api_pricing"]["models"].update(FAKE_PRICES)
    # Testy CLI okładki podają konwerter albo sprawdzają komunikat o braku profilu.
    settings["cover"]["cmyk"]["profile"] = None
    settings.update(overrides)
    return settings


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


# --- FR-15 etap 3: model z wizją przy okładce ---------------------------------------------


class CoverVision:
    """Odpowiedzi modelu z wizją dla `cover`: wybór stron, scena przodu, QA okładki.

    Rozpoznaje wywołanie po instrukcjach. `selection`, `scene` i `verdict` można zmienić
    w teście; `calls` to rodzaje kolejnych wywołań.
    """

    def __init__(self) -> None:
        self.selection: dict[str, Any] = {
            "front": 3,
            "thumbnails": [1, 5, 6],
            "reason": "wyraźny motyw na przodzie",
        }
        self.scene: dict[str, Any] = {
            "has_horizon": False,
            "horizon": 0.0,
            "band_colors": ["#FFFFFF"] * 8,
            "background": "plain white background",
        }
        self.verdict: dict[str, Any] = {"passed": True, "issues": []}
        self.calls: list[str] = []
        self.images: list[bytes] = []

    def __call__(self, image_png: bytes, instructions: str) -> dict[str, Any]:
        self.images.append(image_png)
        if "contact sheet" in instructions:
            self.calls.append("select")
            return self.selection
        if "paperback cover" in instructions:  # przed sceną: QA też wspomina przód
            self.calls.append("qa")
            return self.verdict
        if "front cover illustration" in instructions:
            self.calls.append("scene")
            return self.scene
        raise AssertionError(f"nieznane wywołanie modelu z wizją: {instructions[:80]}")
