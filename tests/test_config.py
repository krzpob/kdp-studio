from __future__ import annotations

import copy
from pathlib import Path

import pytest
import yaml

from kdp_studio.config import DEFAULT_CONFIG_DIR, AppConfig, ConfigError, load_config
from tests.conftest import ConfigDirFactory


def _raw(name: str) -> dict[str, object]:
    data = yaml.safe_load((DEFAULT_CONFIG_DIR / f"{name}.yaml").read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return copy.deepcopy(data)


def test_repo_config_is_valid(repo_config: AppConfig) -> None:
    assert list(repo_config.ages) == [
        "przedszkole",
        "wczesnoszkolne",
        "szkolne",
        "nastolatki",
        "dorosli",
    ]
    assert set(repo_config.formats) == {"letter", "square"}
    assert repo_config.settings.front_matter.pages == 4  # FR-23: z instrukcją


def test_speck_area_shrinks_with_thinner_lines(repo_config: AppConfig) -> None:
    areas = [age.postprocess.min_speck_area for age in repo_config.ages.values()]
    assert areas == sorted(areas, reverse=True)


def test_style_allowed_ages(repo_config: AppConfig) -> None:
    assert repo_config.styles["zentangle"].allows("dorosli")
    assert not repo_config.styles["zentangle"].allows("przedszkole")
    assert not repo_config.styles["fantasy"].allows("wczesnoszkolne")
    assert repo_config.styles["kawaii"].allows("przedszkole")


def test_env_var_selects_config_dir(
    config_dir: ConfigDirFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    directory = config_dir(settings={"front_matter": {"instructions": False}})
    monkeypatch.setenv("KDP_STUDIO_CONFIG_DIR", str(directory))
    assert load_config().settings.front_matter.pages == 2


def test_missing_settings_key_uses_default(config_dir: ConfigDirFactory) -> None:
    directory = config_dir()
    (directory / "settings.yaml").write_text("", encoding="utf-8")
    assert load_config(directory).settings.front_matter.pages == 4


def test_missing_file(config_dir: ConfigDirFactory) -> None:
    directory = config_dir()
    (directory / "styles.yaml").unlink()
    with pytest.raises(ConfigError, match=r"brak pliku konfiguracji: .*styles\.yaml"):
        load_config(directory)


def test_invalid_yaml(config_dir: ConfigDirFactory) -> None:
    directory = config_dir()
    (directory / "ages.yaml").write_text("przedszkole: [unclosed", encoding="utf-8")
    with pytest.raises(ConfigError, match="niepoprawny YAML"):
        load_config(directory)


def test_page_px_must_match_trim_and_dpi(config_dir: ConfigDirFactory) -> None:
    formats = _raw("formats")
    formats["letter"]["page_px"] = [2550, 3000]  # type: ignore[index]
    with pytest.raises(ConfigError, match=r"formats\.letter.*page_px"):
        load_config(config_dir(formats=formats))


def test_safe_margin_below_kdp_minimum(config_dir: ConfigDirFactory) -> None:
    formats = _raw("formats")
    formats["square"]["safe_margin_in"] = 0.1  # type: ignore[index]
    with pytest.raises(
        ConfigError, match=r"format 'square': safe_margin_in 0\.1 < .*outside_min_in"
    ):
        load_config(config_dir(formats=formats))


def test_unknown_field_is_rejected(config_dir: ConfigDirFactory) -> None:
    styles = _raw("styles")
    styles["kawaii"]["promt_fragment"] = "typo"  # type: ignore[index]
    with pytest.raises(ConfigError, match=r"styles\.kawaii\.promt_fragment"):
        load_config(config_dir(styles=styles))


def test_allowed_ages_must_reference_existing_age(config_dir: ConfigDirFactory) -> None:
    styles = _raw("styles")
    styles["kawaii"]["allowed_ages"] = ["niemowleta"]  # type: ignore[index]
    with pytest.raises(ConfigError, match="niemowleta"):
        load_config(config_dir(styles=styles))


def test_empty_profiles_file(config_dir: ConfigDirFactory, tmp_path: Path) -> None:
    directory = config_dir()
    (directory / "formats.yaml").write_text("", encoding="utf-8")
    with pytest.raises(ConfigError, match=r"brak profili w formats\.yaml"):
        load_config(directory)


def test_kdp_margins_rows_must_increase(config_dir: ConfigDirFactory) -> None:
    settings = _raw("settings")
    settings["kdp_margins"]["gutter_by_pages"][1]["gutter_in"] = 0.3  # type: ignore[index]
    with pytest.raises(ConfigError, match="muszą rosnąć"):
        load_config(config_dir(settings=settings))


def test_kdp_margins_from_settings(repo_config: AppConfig) -> None:
    margins = repo_config.settings.kdp_margins
    assert margins.outside_min_in == 0.25
    assert margins.max_pages == 828
    assert [margins.gutter_in(p) for p in (24, 150, 151, 300, 301, 828, 829)] == [
        0.375,
        0.375,
        0.5,
        0.5,
        0.625,
        0.875,
        None,
    ]
