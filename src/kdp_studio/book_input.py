"""FR-20: plik parametrów książki (`--config-file`) i scalanie źródeł parametrów.

Jeden schemat (`BookInput`) opisuje plik i sekcję `input` w `manifest.json`. Klucze to nazwy
flag `generate` bez `--`, z podkreśleniem zamiast myślnika. Strony wstępne, strona FR-14
i okładka mają własne sekcje, bo `qa`, `image_quality` i `max_cost` znaczą tam co innego niż
dla stron. Pierwszeństwo: flaga > plik > `settings.yaml` > wartość domyślna w kodzie.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated, Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from kdp_studio.config import (
    MAX_CONCURRENCY,
    AplusComparisonBook,
    AppConfig,
    CopyrightVariant,
    FirstPage,
    ImageQuality,
    LogLevel,
)

DEFAULT_FORMAT = "letter"
DEFAULT_PAGES = 30
DEFAULT_OUTPUT_DIR = "output"
# Klucze opisujące książkę: w krokach z katalogiem muszą się zgadzać z manifestem.
BOOK_KEYS = ("theme", "age", "style", "format", "pages", "market")
# Pola `input` w manifeście, których nie ma w pliku parametrów.
MANIFEST_ONLY_KEYS = ("front_matter_pages", "config_file", "overrides")


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SectionInput(_Input):
    """Ustawienia kroku z modelem obrazu: polecenie `front-matter` albo `belongs-to`."""

    enabled: bool | None = None  # krok w generate (--front-matter, --belongs-to-page)
    qa: bool | None = None
    image_quality: ImageQuality | None = None
    max_cost: Annotated[float, Field(gt=0)] | None = None


class CoverInput(_Input):
    """Sekcja `cover`: `enabled` to `generate --cover`, reszta to flagi polecenia `cover`.
    `page` i `thumbnails` czyta tylko polecenie `cover` (generate wybiera strony modelem)."""

    enabled: bool | None = None
    page: str | int | None = None  # 7, 07 albo page_07
    thumbnails: list[str | int] | None = None
    template: str | None = None
    color: bool | None = None
    select_pages: bool | None = None
    back_text: bool | None = None
    qa: bool | None = None
    image_quality: ImageQuality | None = None
    max_cost: Annotated[float, Field(gt=0)] | None = None


class AplusBookInput(_Input):
    """Sekcja `aplus` (FR-24): opcje polecenia `aplus` i książki do tabeli porównawczej."""

    color_page: bool | None = None
    feature_images: bool | None = None  # kolumny z grafikami z modelu (aplus.features.source)
    image_quality: ImageQuality | None = None
    max_cost: Annotated[float, Field(gt=0)] | None = None
    comparison: list[AplusComparisonBook] | None = None  # 2–6 książek z własnego konta


class BookInput(_Input):
    """Parametry książki i uruchomienia; None znaczy „nie podano”."""

    theme: str | None = None
    age: str | None = None
    style: str | None = None
    format: str | None = None
    pages: int | None = None
    market: str | None = None  # FR-19
    strict: bool | None = None
    output_dir: str | None = None
    single_sided: bool | None = None  # FR-22
    review_ideas: bool | None = None
    qa: bool | None = None
    image_provider: str | None = None
    image_quality: ImageQuality | None = None
    concurrency: Annotated[int, Field(ge=1, le=MAX_CONCURRENCY)] | None = None
    max_cost: Annotated[float, Field(gt=0)] | None = None
    log_level: LogLevel | None = None
    # FR-23
    first_page: FirstPage | None = None
    instructions: bool | None = None
    copyright: CopyrightVariant | None = None
    copyright_owner: str | None = None
    front_matter: SectionInput | None = None
    belongs_to: SectionInput | None = None
    cover: CoverInput | None = None
    aplus: AplusBookInput | None = None  # FR-24

    @field_validator("cover", mode="before")
    @classmethod
    def _cover_shorthand(cls, value: Any) -> Any:
        """`cover: true` znaczy `cover: {enabled: true}`."""
        return {"enabled": value} if isinstance(value, bool) else value


class ConfigFileInfo(_Input):
    path: str
    sha256: str


class BookInputError(Exception):
    """Zły plik parametrów książki albo niezgodność z manifestem (kod 1)."""

    def __init__(self, errors: list[str]) -> None:
        super().__init__("\n".join(errors))
        self.errors = errors


@dataclass(frozen=True)
class LoadedFile:
    path: Path
    sha256: str
    input: BookInput

    @property
    def label(self) -> str:
        return self.path.name

    def info(self) -> ConfigFileInfo:
        return ConfigFileInfo(path=str(self.path), sha256=self.sha256)


def _message(error: Any) -> str:
    """Komunikat walidacji po polsku dla najczęstszych błędów, inaczej tekst Pydantic."""
    kind = error["type"]
    ctx = error.get("ctx") or {}
    if kind == "extra_forbidden":
        return "nieznany klucz (literówka?)"
    if kind == "literal_error":
        return f"dozwolone {ctx.get('expected', '')} (podano {error['input']!r})"
    if kind in ("bool_type", "bool_parsing"):
        return f"oczekiwano true albo false (podano {error['input']!r})"
    if kind in ("int_type", "int_parsing", "int_from_float"):
        return f"oczekiwano liczby całkowitej (podano {error['input']!r})"
    if kind in ("float_type", "float_parsing"):
        return f"oczekiwano liczby (podano {error['input']!r})"
    if kind in ("string_type", "list_type", "model_type", "dict_type"):
        return f"zły typ wartości (podano {error['input']!r})"
    if kind in ("greater_than", "greater_than_equal", "less_than", "less_than_equal"):
        limits = {
            "greater_than": "większa niż",
            "greater_than_equal": "co najmniej",
            "less_than": "mniejsza niż",
            "less_than_equal": "najwyżej",
        }
        bound = next(iter(ctx.values()), "")
        return f"wartość musi być {limits[kind]} {bound} (podano {error['input']!r})"
    return str(error["msg"])


def _loc(loc: tuple[int | str, ...]) -> str:
    text = ""
    for part in loc:
        text += f"[{part}]" if isinstance(part, int) else (f".{part}" if text else str(part))
    return text


def _relative_to(value: str | None, base: Path) -> str | None:
    if value is None or Path(value).is_absolute():
        return value
    return str(base / value)


def load_book_file(path: Path) -> LoadedFile:
    """Plik YAML (albo JSON) parametrów książki. Plik z sekcją `input` (jak `manifest.json`)
    daje tylko ją. Ścieżki względne liczą się od katalogu pliku. Błędy mają ścieżkę klucza."""
    import hashlib

    label = path.name
    try:
        raw = path.read_bytes()
        data = yaml.safe_load(raw.decode("utf-8"))
    except OSError as e:
        raise BookInputError([f"--config-file: nie można odczytać {path}: {e.strerror}"]) from e
    except (UnicodeDecodeError, yaml.YAMLError) as e:
        raise BookInputError([f"{label}: to nie jest poprawny YAML w UTF-8 ({e})"]) from e
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise BookInputError([f"{label}: plik musi być słownikiem kluczy, a jest {type(data)}"])
    if isinstance(data.get("input"), dict):
        data = {k: v for k, v in data["input"].items() if k not in MANIFEST_ONLY_KEYS}
    try:
        book = BookInput.model_validate(data)
    except ValidationError as e:
        raise BookInputError(
            [f"{label}: {_loc(err['loc'])}: {_message(err)}" for err in e.errors()]
        ) from e
    base = path.resolve().parent
    update: dict[str, Any] = {"output_dir": _relative_to(book.output_dir, base)}
    if book.cover is not None:
        template = _relative_to(book.cover.template, base)
        update["cover"] = book.cover.model_copy(update={"template": template})
    if book.aplus is not None and book.aplus.comparison is not None:
        books = [
            b.model_copy(update={"book": _relative_to(b.book, base)}) for b in book.aplus.comparison
        ]
        update["aplus"] = book.aplus.model_copy(update={"comparison": books})
    return LoadedFile(
        path=path, sha256=hashlib.sha256(raw).hexdigest(), input=book.model_copy(update=update)
    )


def settings_defaults(config: AppConfig) -> BookInput:
    """Wartości z `settings.yaml` i domyślne z kodu: najniższe źródło przy scalaniu."""
    s = config.settings
    front = s.front_matter
    cover = s.cover
    return BookInput(
        format=DEFAULT_FORMAT,
        pages=DEFAULT_PAGES,
        market=s.default_market,
        strict=False,
        output_dir=DEFAULT_OUTPUT_DIR,
        single_sided=s.interior.single_sided,
        review_ideas=s.review_ideas,
        qa=s.qa,
        image_provider=s.providers.image,
        image_quality=s.image_quality,
        concurrency=s.concurrency,
        max_cost=s.max_cost_usd,
        log_level=s.log_level,
        first_page=front.first_page,
        instructions=front.instructions,
        copyright=front.copyright,
        copyright_owner=s.publisher.copyright_owner,
        front_matter=SectionInput(
            enabled=front.in_generate,
            qa=s.qa,
            image_quality=s.image_quality,
            max_cost=s.max_cost_usd,
        ),
        belongs_to=SectionInput(qa=s.qa, image_quality=s.image_quality, max_cost=s.max_cost_usd),
        cover=CoverInput(
            enabled=cover.in_generate,
            color=cover.colorize,
            select_pages=cover.select_pages,
            back_text=cover.back_text,
            qa=cover.qa,
            image_quality=s.image_quality,
            max_cost=s.max_cost_usd,
        ),
        aplus=AplusBookInput(
            color_page=s.aplus.color_page,
            feature_images=s.aplus.features.source == "generated",
            image_quality=s.image_quality,
            max_cost=s.max_cost_usd,
            comparison=list(s.aplus.comparison.books),
        ),
    )


SETTINGS_SOURCE = "settings.yaml"


@dataclass
class Resolved:
    """Skuteczne parametry i źródło każdej podanej wartości (klucz z kropką → źródło)."""

    input: BookInput
    sources: dict[str, str] = field(default_factory=dict)
    file: LoadedFile | None = None

    def source(self, key: str) -> str:
        return self.sources.get(key, SETTINGS_SOURCE)

    def given(self, key: str) -> bool:
        """Wartość podana flagą albo w pliku, a nie wzięta z `settings.yaml`."""
        return key in self.sources

    @property
    def overrides(self) -> list[str]:
        """Klucze nadpisane flagami, gdy był plik parametrów."""
        if self.file is None:
            return []
        return sorted(k for k, v in self.sources.items() if v.startswith("--"))


def _flag(key: str) -> str:
    return "--" + key.rsplit(".", 1)[-1].replace("_", "-")


def _items(model: BaseModel | None, prefix: str = "") -> Iterator[tuple[str, Any]]:
    if model is None:
        return
    for name in type(model).model_fields:
        value = getattr(model, name)
        key = f"{prefix}{name}"
        if isinstance(value, BaseModel):
            yield from _items(value, f"{key}.")
        elif value is not None:
            yield key, value


def _set(data: dict[str, Any], key: str, value: Any) -> None:
    *parents, last = key.split(".")
    for part in parents:
        data = data.setdefault(part, {})
    data[last] = value


def resolve_input(
    cli: BookInput,
    file: LoadedFile | None,
    config: AppConfig,
    cli_names: dict[str, str] | None = None,
) -> Resolved:
    """Scala flagi, plik i `settings.yaml` (FR-20). `cli_names` podaje nazwę flagi dla
    klucza, gdy różni się od nazwy klucza (np. `belongs_to.enabled` → `--belongs-to-page`)."""
    names = cli_names or {}
    merged: dict[str, Any] = {}
    sources: dict[str, str] = {}
    layers: list[tuple[BookInput | None, str | None]] = [
        (settings_defaults(config), None),
        (None if file is None else file.input, None if file is None else file.label),
        (cli, ""),
    ]
    for layer, label in layers:
        for key, value in _items(layer):
            _set(merged, key, value)
            if label is None:
                sources.pop(key, None)
            elif label:
                sources[key] = label
            else:
                sources[key] = names.get(key, _flag(key))
    return Resolved(_construct(merged), sources, file)


def _construct(data: dict[str, Any]) -> BookInput:
    """BookInput bez walidacji: plik jest już sprawdzony przy wczytaniu, a wartości flag
    sprawdzają polecenia (`_quality`, `_workers`, `validate_book_spec`) z własnymi
    komunikatami."""
    sections: dict[str, Any] = {}
    for name, model in (
        ("front_matter", SectionInput),
        ("belongs_to", SectionInput),
        ("cover", CoverInput),
        ("aplus", AplusBookInput),
    ):
        if name in data:
            sections[name] = model.model_construct(**data[name])
    return BookInput.model_construct(**{**data, **sections})


def source_errors(errors: list[str], resolved: Resolved) -> list[str]:
    """Komunikaty walidacji `--pages: …` z wartością z pliku: `kotki.yaml: pages: …`."""
    if resolved.file is None:
        return errors
    out = []
    for error in errors:
        for key in BOOK_KEYS:
            prefix = f"--{key}:"
            if error.startswith(prefix) and resolved.source(key) == resolved.file.label:
                error = f"{resolved.file.label}: {key}:{error[len(prefix) :]}"
                break
        out.append(error)
    return out


def book_mismatch(file: LoadedFile, manifest_input: BaseModel) -> list[str]:
    """Klucze opisujące książkę, które w pliku różnią się od `input` w manifeście."""
    problems = []
    for key in BOOK_KEYS:
        value = getattr(file.input, key)
        saved = getattr(manifest_input, key, None)
        if value is not None and value != saved:
            problems.append(f"{file.label}: {key}: {value!r}, a książka ma {saved!r}")
    if problems:
        problems.append(
            "plik opisuje inną książkę: zmiana tych wartości wymaga nowej książki "
            "albo kdp-studio ideas --redo"
        )
    return problems
