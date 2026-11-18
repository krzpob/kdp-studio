from __future__ import annotations

from kdp_studio.config import AppConfig
from kdp_studio.profiles import format_profiles


def test_all_kinds_in_order(repo_config: AppConfig) -> None:
    lines = format_profiles(repo_config)
    headers = [line for line in lines if line and not line.startswith(" ")]
    assert headers == ["Wiek (--age)", "Styl (--style)", "Format (--format)", "Rynek (--market)"]
    listed = {line.split()[0] for line in lines if line.startswith("  ")}
    markets = repo_config.markets.markets
    assert listed == {*repo_config.ages, *repo_config.styles, *repo_config.formats, *markets}


def test_groups_are_separated_by_blank_line(repo_config: AppConfig) -> None:
    lines = format_profiles(repo_config, ("age", "format"))
    assert lines.count("") == 1
    assert lines[lines.index("") + 1] == "Format (--format)"


def test_line_shows_name_and_description(repo_config: AppConfig) -> None:
    lines = format_profiles(repo_config, ("age",))
    assert lines[1] == (
        "  przedszkole     Przedszkole (3–5 lat): "
        "Jeden duży, prosty obiekt, bardzo grube kontury, bez tła."
    )


def test_keys_are_aligned(repo_config: AppConfig) -> None:
    lines = format_profiles(repo_config, ("style",))[1:]
    starts = {len(line) - len(line[2:].split(" ", 1)[1].lstrip()) for line in lines}
    assert len(starts) == 1


def test_style_lists_allowed_ages(repo_config: AppConfig) -> None:
    lines = format_profiles(repo_config, ("style",))
    zentangle = next(line for line in lines if line.startswith("  zentangle"))
    kawaii = next(line for line in lines if line.startswith("  kawaii"))
    assert zentangle.endswith("Tylko dla wieku: nastolatki, dorosli.")
    assert "Tylko dla wieku" not in kawaii


def test_multiline_description_is_flattened(repo_config: AppConfig) -> None:
    chibi = next(
        line for line in format_profiles(repo_config, ("style",)) if line.startswith("  chibi")
    )
    assert "\n" not in chibi
    assert "  " not in chibi.strip().split(" ", 1)[1].strip()


def test_default_format_is_marked(repo_config: AppConfig) -> None:
    lines = format_profiles(repo_config, ("format",), default_format="square")
    assert lines[1].startswith("  letter") and not lines[1].endswith("Domyślny.")
    assert lines[2].startswith("  square") and lines[2].endswith("Domyślny.")
