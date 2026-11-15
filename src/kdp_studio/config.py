"""Ładowanie i walidacja konfiguracji z katalogu `config/` (spec §7, §9.2)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated, Any, Literal, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

CONFIG_DIR_ENV = "KDP_STUDIO_CONFIG_DIR"
DEFAULT_CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"

KDP_MIN_SAFE_MARGIN_IN = 0.25  # min. margines KDP bez spadu (spec §7.3)
POTRACE_ALPHAMAX_MAX = 1.3334  # powyżej potrace nie tworzy narożników


class ConfigError(Exception):
    """Nieprawidłowa lub brakująca konfiguracja (kod wyjścia 1)."""


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class PotraceParams(_Strict):
    turdsize: Annotated[int, Field(ge=0)]
    alphamax: Annotated[float, Field(ge=0, le=POTRACE_ALPHAMAX_MAX)]
    opttolerance: Annotated[float, Field(ge=0)]


class PostprocessParams(_Strict):
    threshold: Literal["otsu"] | Annotated[int, Field(ge=0, le=255)]
    min_speck_area: Annotated[int, Field(ge=0)]
    potrace: PotraceParams


class AgeProfile(_Strict):
    name: str
    description: str
    line: str
    subjects: str
    background: str
    fill_areas: str
    prompt_fragment: str
    postprocess: PostprocessParams


class StyleProfile(_Strict):
    name: str
    description: str
    prompt_fragment: str
    allowed_ages: list[str] | None = None

    def allows(self, age: str) -> bool:
        return self.allowed_ages is None or age in self.allowed_ages


class FormatProfile(_Strict):
    name: str
    description: str
    trim_in: tuple[Annotated[float, Field(gt=0)], Annotated[float, Field(gt=0)]]
    dpi: Annotated[int, Field(gt=0)]
    page_px: tuple[Annotated[int, Field(gt=0)], Annotated[int, Field(gt=0)]]
    aspect: Annotated[str, Field(pattern=r"^\d+:\d+$")]
    safe_margin_in: Annotated[float, Field(ge=KDP_MIN_SAFE_MARGIN_IN)]
    gutter_in: Annotated[float, Field(ge=0)]
    composition_hint: str

    @model_validator(mode="after")
    def _page_px_matches_trim(self) -> Self:
        expected = (round(self.trim_in[0] * self.dpi), round(self.trim_in[1] * self.dpi))
        if self.page_px != expected:
            raise ValueError(f"page_px {list(self.page_px)} != trim_in × dpi {list(expected)}")
        return self


class ProviderSettings(_Strict):
    """Nazwy implementacji z rejestru `kdp_studio.providers.registry` (spec §8.2)."""

    text: str = "openai"


class ModelSettings(_Strict):
    text: Annotated[str, Field(min_length=1)] = "gpt-6-luna"


class Settings(_Strict):
    front_matter_pages: Annotated[int, Field(ge=0)] = 2
    reserve_ratio: Annotated[float, Field(ge=0, le=1)] = 0.2
    metadata_language: Annotated[str, Field(min_length=1)] = "English"
    providers: ProviderSettings = ProviderSettings()
    models: ModelSettings = ModelSettings()


class AppConfig(_Strict):
    ages: dict[str, AgeProfile]
    styles: dict[str, StyleProfile]
    formats: dict[str, FormatProfile]
    settings: Settings

    @model_validator(mode="after")
    def _references_exist(self) -> Self:
        for kind, profiles in (
            ("ages", self.ages),
            ("styles", self.styles),
            ("formats", self.formats),
        ):
            if not profiles:
                raise ValueError(f"brak profili w {kind}.yaml")
        for key, style in self.styles.items():
            unknown = [a for a in style.allowed_ages or [] if a not in self.ages]
            if unknown:
                raise ValueError(f"styl '{key}': allowed_ages zawiera nieznany wiek {unknown}")
        return self


def resolve_config_dir(config_dir: Path | None = None) -> Path:
    if config_dir is not None:
        return config_dir
    env = os.environ.get(CONFIG_DIR_ENV)
    return Path(env) if env else DEFAULT_CONFIG_DIR


def _read_yaml(path: Path) -> Any:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise ConfigError(f"brak pliku konfiguracji: {path}") from None
    except OSError as e:
        raise ConfigError(f"nie można odczytać {path}: {e}") from e
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as e:
        raise ConfigError(f"niepoprawny YAML w {path}: {e}") from e
    return {} if data is None else data


def load_config(config_dir: Path | None = None) -> AppConfig:
    """Wczytuje ages/styles/formats/settings.yaml i waliduje ich schemat."""
    directory = resolve_config_dir(config_dir)
    raw = {
        name: _read_yaml(directory / f"{name}.yaml")
        for name in ("ages", "styles", "formats", "settings")
    }
    try:
        return AppConfig.model_validate(raw)
    except ValidationError as e:
        details = "\n".join(
            f"  {'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in e.errors()
        )
        raise ConfigError(f"niepoprawna konfiguracja w {directory}:\n{details}") from e
