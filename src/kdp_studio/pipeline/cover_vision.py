"""FR-15 etap 3: oceny okładki modelem z wizją (jedno wywołanie oceny = jeden obraz).

- **Wybór stron:** program składa arkusz kontaktowy z miniaturami gotowych stron i numerami
  narysowanymi przez siebie; model zwraca stronę na przód, miniatury tyłu i uzasadnienie.
  Program sprawdza odpowiedź i uzupełnia ją wyborem domyślnym, gdy model wskaże złe strony.
- **Scena przodu:** model opisuje tło gotowego przodu (horyzont, kolory przy lewej krawędzi),
  żeby tył i grzbiet je kontynuowały.
- **QA okładki** (`--qa`): brak tekstu poza napisami programu, przód pokazuje wybraną stronę,
  tył pasuje stylem do przodu.

To oceny, nie generowanie obrazów, więc D4 ich nie dotyczy.
"""

from __future__ import annotations

import io
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from PIL import Image, ImageDraw
from pydantic import BaseModel, ConfigDict, Field

from kdp_studio.config import AppConfig
from kdp_studio.models import BookSpec, PageIdea
from kdp_studio.pipeline.fonts import load_font
from kdp_studio.providers.base import Usage, VisionProvider

SHEET_THUMB_PX = 220  # szerokość miniatury strony na arkuszu kontaktowym
SHEET_LABEL_PX = 34  # wysokość pasa z numerem nad miniaturą
SHEET_GAP_PX = 12
SHEET_MAX_COLS = 6
QA_WIDTH_PX = 2048  # okładka do QA: wystarczy, żeby zobaczyć tekst i styk grzbietu


def png_bytes(img: Image.Image) -> bytes:
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    return buffer.getvalue()


# --- Arkusz kontaktowy i wybór stron -------------------------------------------------------


def contact_sheet(pages: list[tuple[int, Path]], font_path: Path) -> Image.Image:
    """Miniatury stron w siatce z numerami nad każdą (numery rysuje program)."""
    if not pages:
        raise ValueError("arkusz kontaktowy bez stron")
    thumbs = []
    for number, path in pages:
        with Image.open(path) as img:
            page = img.convert("L")
        height = round(SHEET_THUMB_PX * page.height / page.width)
        thumbs.append((number, page.resize((SHEET_THUMB_PX, height), Image.Resampling.LANCZOS)))
    cols = min(SHEET_MAX_COLS, math.ceil(math.sqrt(len(thumbs))))
    rows = math.ceil(len(thumbs) / cols)
    cell_h = SHEET_LABEL_PX + max(t.height for _, t in thumbs)
    sheet = Image.new(
        "L",
        (
            cols * SHEET_THUMB_PX + (cols + 1) * SHEET_GAP_PX,
            rows * cell_h + (rows + 1) * SHEET_GAP_PX,
        ),
        255,
    )
    draw = ImageDraw.Draw(sheet)
    font = load_font(font_path, round(SHEET_LABEL_PX * 0.8), "Bold")
    for index, (number, thumb) in enumerate(thumbs):
        row, col = divmod(index, cols)
        x = SHEET_GAP_PX + col * (SHEET_THUMB_PX + SHEET_GAP_PX)
        y = SHEET_GAP_PX + row * (cell_h + SHEET_GAP_PX)
        draw.text((x + SHEET_THUMB_PX // 2, y), f"{number:02d}", font=font, fill=0, anchor="mt")
        sheet.paste(thumb, (x, y + SHEET_LABEL_PX))
        draw.rectangle(
            (x - 1, y + SHEET_LABEL_PX - 1, x + SHEET_THUMB_PX, y + SHEET_LABEL_PX + thumb.height),
            outline=0,
            width=1,
        )
    return sheet


class _LLMSelection(BaseModel):
    front: int
    thumbnails: list[int]
    reason: str


SELECT_INSTRUCTIONS = """\
You are the cover designer of a printed children's coloring book "{title}" for {audience}. \
You get a contact sheet with every finished page of the book; the number above each page is \
its page number.

Choose:
- front: the one page that will be colored and used as the front cover illustration. Prefer a \
page with one clear, appealing main subject that is typical for the theme of the book, reads \
well when small, and has some calm space around it. Avoid busy or crowded pages.
- thumbnails: {thumbs_rule}
{fixed}
Use only page numbers shown on the sheet. In reason, explain the choice briefly in Polish.
"""


@dataclass
class PageChoice:
    front: int
    thumbnails: list[int]
    reason: str
    usage: Usage
    warnings: list[str] = field(default_factory=list)


def select_instructions(
    spec: BookSpec, config: AppConfig, title: str, count: int, fixed_front: int | None
) -> str:
    fixed = (
        f"The front is already chosen: page {fixed_front}. Return it as front and choose only "
        "the thumbnails.\n"
        if fixed_front is not None
        else ""
    )
    thumbs_rule = (
        f"exactly {count} other pages shown as small black-and-white previews on the back "
        "cover. They must differ from the front and from each other, and together show the "
        "variety of the book (different subjects, actions and settings)."
        if count
        else "the thumbnails are already chosen; return an empty list."
    )
    return SELECT_INSTRUCTIONS.format(
        title=title, audience=config.ages[spec.age].name, thumbs_rule=thumbs_rule, fixed=fixed
    )


def choose_pages(
    answer: _LLMSelection,
    available: list[int],
    count: int,
    fixed_front: int | None,
    fallback_front: int,
    fallback_thumbs: list[int],
) -> tuple[int, list[int], list[str]]:
    """Sprawdza odpowiedź modelu; złe numery zastępuje wyborem domyślnym (z ostrzeżeniem)."""
    warnings = []
    front = fixed_front if fixed_front is not None else answer.front
    if front not in available:
        warnings.append(f"model wskazał na przód stronę {answer.front}, której nie ma na arkuszu")
        front = fallback_front
    thumbs: list[int] = []
    if count == 0:
        return front, thumbs, warnings
    for number in answer.thumbnails:
        if number in available and number != front and number not in thumbs:
            thumbs.append(number)
    if len(thumbs) != len(answer.thumbnails) or len(thumbs) < count:
        warnings.append(
            "model wskazał niepoprawne miniatury "
            f"({', '.join(map(str, answer.thumbnails)) or 'brak'}); uzupełniono domyślnymi"
        )
    for number in fallback_thumbs + available:
        if len(thumbs) >= count:
            break
        if number != front and number not in thumbs:
            thumbs.append(number)
    return front, thumbs[:count], warnings


def propose_pages(
    vision: VisionProvider,
    sheet: Image.Image,
    instructions: str,
    available: list[int],
    count: int,
    fixed_front: int | None,
    fallback_front: int,
    fallback_thumbs: list[int],
) -> PageChoice:
    answer, usage = vision.assess(png_bytes(sheet), instructions, _LLMSelection)
    front, thumbs, warnings = choose_pages(
        answer, available, count, fixed_front, fallback_front, fallback_thumbs
    )
    return PageChoice(front, thumbs, answer.reason.strip(), usage, warnings)


# --- Scena przodu (horyzont i kolory tła) ----------------------------------------------------


class _LLMFrontScene(BaseModel):
    has_horizon: bool
    horizon: float  # ułamek wysokości od góry; bez znaczenia, gdy has_horizon = false
    band_colors: list[str]  # #RRGGBB od góry do dołu przy lewej krawędzi
    background: str


SCENE_INSTRUCTIONS = """\
You get the front cover illustration of a children's coloring book, without its title. The \
back cover will be painted as a continuation of this picture to the LEFT, so describe the \
background at the LEFT edge of the image.

- has_horizon: true if there is a horizon or a clear line where the ground, floor or water \
meets the sky or a wall at the left edge; false for a pattern, a plain or gradient background.
- horizon: the height of that line at the left edge as a fraction of the image height, \
measured from the top (0 = top, 1 = bottom). Use 0 when has_horizon is false.
- band_colors: the dominant background color at the left edge in each of {bands} horizontal \
bands of equal height, from top to bottom, as #RRGGBB. Ignore black outlines and small objects.
- background: one short English sentence describing the background (for example "light blue \
sky with soft clouds above a green meadow").
"""


@dataclass(frozen=True)
class FrontScene:
    horizon: float | None
    band_colors: list[str]
    background: str
    usage: Usage


def analyze_front(vision: VisionProvider, front: Image.Image, bands: int) -> FrontScene:
    answer, usage = vision.assess(
        png_bytes(front.convert("RGB")), SCENE_INSTRUCTIONS.format(bands=bands), _LLMFrontScene
    )
    horizon = min(1.0, max(0.0, answer.horizon)) if answer.has_horizon else None
    return FrontScene(horizon, list(answer.band_colors), answer.background.strip(), usage)


# --- QA okładki ------------------------------------------------------------------------------

CoverCriterion = Literal["text", "front_mismatch", "style_mismatch", "other"]


class CoverQAIssue(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    criterion: CoverCriterion
    detail: str  # po polsku


class CoverQAResult(BaseModel):
    """Wynik QA okładki w manifeście: `{"pass": …, "issues": […]}` jak przy stronach."""

    model_config = ConfigDict(
        frozen=True, extra="forbid", validate_by_name=True, serialize_by_alias=True
    )

    passed: bool = Field(alias="pass")
    issues: list[CoverQAIssue] = []

    def summary(self) -> str:
        return "; ".join(f"{i.criterion}: {i.detail}" for i in self.issues) or "bez powodu"


class _LLMCoverVerdict(BaseModel):
    passed: bool
    issues: list[CoverQAIssue]


QA_INSTRUCTIONS = """\
You are the quality checker for the printed paperback cover of a children's coloring book. \
You get the whole cover as one image: back cover on the left, the narrow spine in the middle, \
front cover on the right. Decide whether the cover can be printed.

Reject (passed = false) only for these problems, each a separate issue:
- text: any letters, words, numbers, signatures, logos or watermarks other than the texts the \
program printed on purpose: {allowed}. Garbled pseudo-letters in the illustration count too.
- front_mismatch: the front cover illustration does not show this scene: {scene}
- style_mismatch: the back cover and spine look like a different picture than the front (other \
style, palette or lighting), or there is a visible hard seam or color jump at the spine.
- other: any other defect a buyer would notice (broken or deformed subject, cut-off subject \
on the front, illustration covering the title).

Calibration: the black-and-white framed thumbnails of inner pages on the back are intended. \
A typical good cover passes; do not reject for matters of taste. When it fails, list every \
problem, each detail in Polish, briefly, pointing to where it is.
"""


def qa_instructions(
    title: str, subtitle: str, spine_text: bool, back_text: bool, idea: PageIdea | None
) -> str:
    allowed = [f'the title "{title}" on the front']
    if subtitle:
        allowed.append(f'the subtitle "{subtitle}" on the front')
    if spine_text:
        allowed.append(f'the title "{title}" on the spine')
    if back_text:
        allowed.append("a short description of the book on the back")
    scene = f"{idea.title}. {idea.scene}" if idea is not None else "the chosen inner page"
    return QA_INSTRUCTIONS.format(allowed="; ".join(allowed), scene=scene)


def check_cover(
    vision: VisionProvider, cover: Image.Image, instructions: str
) -> tuple[CoverQAResult, Usage]:
    scale = min(1.0, QA_WIDTH_PX / cover.width)
    size = (round(cover.width * scale), round(cover.height * scale))
    small = cover.convert("RGB").resize(size, Image.Resampling.LANCZOS)
    verdict, usage = vision.assess(png_bytes(small), instructions, _LLMCoverVerdict)
    issues = list(verdict.issues)
    if not verdict.passed and not issues:
        issues = [CoverQAIssue(criterion="other", detail="model odrzucił okładkę bez powodu")]
    return CoverQAResult(passed=verdict.passed, issues=issues), usage
