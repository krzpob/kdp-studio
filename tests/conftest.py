from __future__ import annotations

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
