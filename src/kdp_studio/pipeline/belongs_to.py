"""FR-14: strona „This book belongs to…” w motywie książki.

Model obrazu rysuje tylko ramkę z elementami motywu wokół pustej tabliczki, bo litery
z modelu bywają krzywe i z literówkami. Napis i linię na imię wpisuje program czcionką
z `assets/fonts` (SIL OFL). Po obróbce (FR-06) program sprawdza, czy pole na tekst jest
puste; jeśli nie, generuje ramkę ponownie, a po wyczerpaniu prób przechodzi na układ
zapasowy: grafika pierwszej gotowej strony książki w górnej części i napis pod nią.

Krok 2 (`BelongsToMaker`) zapisuje surową grafikę `raw/front_belongs_to.png` i wybiera
układ; krok 3 (`BelongsToRenderer.render`) robi z niej gotową stronę z napisem. Ten sam
`BelongsToMaker` robi też stronę tytułową i ilustrację instrukcji (FR-23) z ich rendererami
(`FrontRenderer`).
"""

from __future__ import annotations

import shutil
import tempfile
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Literal, Protocol

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from kdp_studio.config import AppConfig, BelongsToAge, BelongsToSettings, PostprocessParams
from kdp_studio.models import BookIdeas, BookSpec
from kdp_studio.pipeline.fonts import FontError, load_font
from kdp_studio.pipeline.output import RAW_DIR, REJECTED_DIR, write_bytes_atomic
from kdp_studio.pipeline.postprocess import (
    BLACK,
    RETHRESHOLD,
    WHITE,
    PageFiles,
    PageGeometry,
    PagePostprocessor,
    PostprocessError,
    save_page_png,
    verify_page,
)
from kdp_studio.pipeline.prompts import FRAME_CONSTRAINTS, PromptBuilder
from kdp_studio.pipeline.qa import QAChecker, QAIssue, QAResult
from kdp_studio.pipeline.worker import RejectedAttempt
from kdp_studio.providers.base import ImageProvider, ImageRequest, ProviderError, Usage

FRONT_NAME = "front_belongs_to"  # alfabetycznie przed page_*, więc w Canvie jest pierwszy
FRONT_IDEA = "belongs_to"  # id „pomysłu” w odrzuconych próbach
Layout = Literal["frame", "fallback", "text_only"]  # text_only: strona 1 bez modelu (FR-23)
Rect = tuple[int, int, int, int]

NAME_LINE_WIDTH = 0.85  # długość linii na imię względem szerokości pola
TEXT_WIDTH = 0.95  # najszerszy napis względem szerokości pola
MIN_FONT_SCALE = 0.4  # napis nie zmniejsza się bardziej, niż do 40% rozmiaru z profilu


# --- Prompt --------------------------------------------------------------------------------


def theme_elements(ideas: BookIdeas, pages: int, count: int = 3) -> list[str]:
    """Główna postać i najczęstsze przedmioty stron książki (bez zapasu), deterministycznie."""
    book = ideas.pages[:pages]
    subjects = Counter(i.subject for i in book if i.subject)
    chosen: list[str] = [subjects.most_common(1)[0][0]] if subjects else []
    elements = Counter(e.strip().lower() for i in book for e in i.elements if e.strip())
    for element, _ in elements.most_common():
        if len(chosen) >= count:
            break
        if element not in chosen and not any(element in c or c in element for c in chosen):
            chosen.append(element)
    return chosen


def belongs_to_prompt(spec: BookSpec, config: AppConfig, ideas: BookIdeas) -> tuple[str, list[str]]:
    """Prompt ramki i użyte elementy motywu. Blok stylu jak na stronach, bez „no frame”."""
    settings = config.settings.belongs_to_page
    elements = theme_elements(ideas, spec.pages)
    theme = " ".join(ideas.book.title.lower().split())
    decorated = f", decorated with {', '.join(elements)}" if elements else ""
    composition = " ".join(settings.composition.split()).rstrip(" .")
    scene = (
        f"Scene: {composition}{decorated}. The frame matches a coloring book about {theme}. "
        "Leave the plaque blank: the owner's name will be added later.\n"
    )
    return scene + PromptBuilder(spec, config).style_block_with(FRAME_CONSTRAINTS), elements


# --- Pole na tekst i napis ---------------------------------------------------------------------


def ink_ratio(img: Image.Image, rect: Rect) -> float:
    """Udział czarnych pikseli w prostokącie strony w trybie L."""
    left, top, right, bottom = rect
    pixels = np.asarray(img.convert("L"))[top:bottom, left:right]
    return float(np.mean(pixels < RETHRESHOLD)) if pixels.size else 0.0


def _font(settings: BelongsToSettings, size: int) -> ImageFont.FreeTypeFont:
    try:
        return load_font(settings.font_path, size, settings.font_variation)
    except FontError as e:
        raise PostprocessError(str(e)) from e


def draw_text_block(
    img: Image.Image, rect: Rect, settings: BelongsToSettings, age: BelongsToAge, dpi: int
) -> Image.Image:
    """Napis i linia na imię wyśrodkowane w prostokącie; wynik tylko 0 i 255.

    Rozmiar z profilu wieku; napis za szeroki albo całość za wysoka jest zmniejszana.
    """
    left, top, right, bottom = rect
    box_w, box_h = right - left, bottom - top
    size = round(age.font_pt / 72 * dpi)
    text = settings.text
    assert text is not None, "napis FR-14 ustala AppConfig.belongs_to_settings(rynek)"
    font = _font(settings, size)
    x0, y0, x1, y1 = font.getbbox(text)
    scale = min(1.0, TEXT_WIDTH * box_w / max(1, x1 - x0))
    line_h = age.name_line_height_in * dpi
    gap = 0.35 * size
    total = (y1 - y0) * scale + (gap + line_h) * scale
    scale *= min(1.0, box_h / total)
    if scale < MIN_FONT_SCALE:
        raise PostprocessError("napis nie mieści się w polu na tekst (za małe pole)")
    if scale < 1.0:
        size = max(1, round(size * scale))
        font = _font(settings, size)
        x0, y0, x1, y1 = font.getbbox(text)
        line_h *= scale
        gap = 0.35 * size

    text_w, text_h = x1 - x0, y1 - y0
    block_h = text_h + gap + line_h
    top_y = top + (box_h - block_h) / 2
    out = img.convert("L").copy()
    draw = ImageDraw.Draw(out)
    draw.fontmode = "1"  # bez antyaliasingu: tylko czerń i biel
    x = left + (box_w - text_w) / 2 - x0
    y = top_y - y0
    if age.outline_text:
        stroke = max(2, round(size * 0.045))
        draw.text((x, y), text, font=font, fill=WHITE, stroke_width=stroke, stroke_fill=BLACK)
    else:
        draw.text((x, y), text, font=font, fill=BLACK)
    thickness = max(3, round(dpi * 0.02))
    line_y = round(top_y + block_h - thickness)
    half = box_w * NAME_LINE_WIDTH / 2
    center = left + box_w / 2
    draw.rectangle(
        (round(center - half), line_y, round(center + half), line_y + thickness - 1), fill=BLACK
    )
    return out.point(lambda v: BLACK if v < RETHRESHOLD else WHITE, mode="L")


# --- Krok 3: gotowa strona -------------------------------------------------------------------


@dataclass(frozen=True)
class BelongsToRenderer:
    """Surowa grafika → `front_belongs_to.png` (z napisem) i `svg/front_belongs_to.svg`."""

    book_dir: Path
    geometry: PageGeometry
    params: PostprocessParams
    settings: BelongsToSettings
    age: BelongsToAge

    @property
    def max_retries(self) -> int:
        return self.settings.max_retries

    @property
    def max_ink_ratio(self) -> float | None:
        return self.settings.max_ink_ratio

    def text_rect(self, layout: Layout) -> Rect:
        if layout == "frame":
            box = self.settings.text_box
            return self.geometry.area(box.x, box.y, box.width, box.height)
        art = self.settings.fallback_art_height
        return self.geometry.area(0.0, art, 1.0, 1.0 - art)

    def art_geometry(self, layout: Layout) -> PageGeometry:
        if layout == "frame":
            return self.geometry
        # Odstęp między grafiką a napisem: grafika kończy się trochę wyżej niż pole tekstu.
        return self.geometry.with_art(0.0, 0.0, 1.0, self.settings.fallback_art_height * 0.95)

    def _postprocessor(self, layout: Layout, book_dir: Path) -> PagePostprocessor:
        return PagePostprocessor(
            book_dir=book_dir, geometry=self.art_geometry(layout), params=self.params
        )

    def text_box_ink(self, raw: Path) -> float:
        """Tusz w polu na tekst ramki po obróbce, bez zapisu w katalogu książki."""
        with tempfile.TemporaryDirectory(prefix="kdp-studio-front-") as tmp:
            files = self._postprocessor("frame", Path(tmp)).process(raw, FRONT_NAME)
            with Image.open(files.page) as img:
                return ink_ratio(img, self.text_rect("frame"))

    def render(self, raw: Path, layout: Layout) -> PageFiles:
        """Gotowa strona z napisem; PostprocessError, gdy wynik nie spełnia NFR-07."""
        files = self._postprocessor(layout, self.book_dir).process(raw, FRONT_NAME)
        with Image.open(files.page) as img:
            rect = self.text_rect(layout)
            page = draw_text_block(img, rect, self.settings, self.age, self.geometry.dpi)
        save_page_png(page, files.page, self.geometry.dpi)
        problems = verify_page(files.page, self.geometry)
        if problems:
            raise PostprocessError("; ".join(problems))
        return files

    def preview(self, raw: Path, layout: Layout) -> bytes:
        """Gotowa strona w katalogu tymczasowym (dla QA w kroku 2)."""
        with tempfile.TemporaryDirectory(prefix="kdp-studio-front-") as tmp:
            files = replace(self, book_dir=Path(tmp)).render(raw, layout)
            return files.page.read_bytes()


# --- Krok 2: surowa grafika i wybór układu ----------------------------------------------------


class FrontRenderer(Protocol):
    """Renderer strony wstępnej z grafiką z modelu (FR-14, FR-23)."""

    @property
    def max_retries(self) -> int: ...

    @property
    def max_ink_ratio(self) -> float | None: ...  # None: bez kontroli pustego pola na tekst

    def text_box_ink(self, raw: Path) -> float: ...

    def preview(self, raw: Path, layout: Layout) -> bytes: ...


@dataclass(frozen=True)
class BelongsToOutcome:
    status: Literal["ok", "failed"]
    duration_s: float
    prompt: str
    layout: Layout | None = None
    raw_file: Path | None = None
    fallback_source: str | None = None  # strona książki, której grafika jest w układzie zapasowym
    attempts: int = 0
    usage: Usage = field(default_factory=Usage)
    qa: QAResult | None = None
    qa_usage: Usage = field(default_factory=Usage)
    rejected: list[RejectedAttempt] = field(default_factory=list)
    error: str | None = None
    budget_exceeded: bool = False


@dataclass
class BelongsToMaker:
    """Generuje ramkę z ponowieniami; po ich wyczerpaniu wybiera układ zapasowy."""

    provider: ImageProvider
    book_dir: Path
    aspect: str
    quality: str
    renderer: FrontRenderer
    elements: list[str]
    qa: QAChecker | None = None
    over_budget: Callable[[], bool] | None = None
    clock: Callable[[], float] = time.monotonic
    name: str = FRONT_NAME  # plik strony (front_belongs_to, front_title, front_instructions)
    idea: str = FRONT_IDEA  # id „pomysłu” w odrzuconych próbach
    # Ocena QA gotowej strony; None: kryteria strony FR-14 (`QAChecker.check_belongs_to`).
    qa_check: Callable[[bytes], tuple[QAResult, Usage]] | None = None
    box_label: str = "pole na imię"  # w komunikacie o niepustym polu na tekst

    @property
    def raw_path(self) -> Path:
        return self.book_dir / RAW_DIR / f"{self.name}.png"

    def _assess(self, page: bytes) -> tuple[QAResult, Usage]:
        if self.qa_check is not None:
            return self.qa_check(page)
        assert self.qa is not None
        return self.qa.check_belongs_to(page, self.elements)

    def _reject(self, attempt: int) -> Path:
        target = self.book_dir / REJECTED_DIR / f"{self.name}_try{attempt}.png"
        target.parent.mkdir(parents=True, exist_ok=True)
        self.raw_path.replace(target)
        return target

    def make(self, prompt: str, fallback: tuple[str, Path] | None) -> BelongsToOutcome:
        """`fallback`: (nazwa strony, jej surowa grafika) do układu zapasowego albo None.

        ProviderError z fatal=True przechodzi wyżej (kod 4), jak w workerze stron.
        """
        started = self.clock()
        usage = qa_usage = Usage()
        rejected: list[RejectedAttempt] = []
        qa: QAResult | None = None
        last_error: str | None = None
        budget = False
        attempt = 0
        max_attempts = 1 + self.renderer.max_retries
        while attempt < max_attempts:
            if self.over_budget is not None and self.over_budget():
                budget = True
                break
            attempt += 1
            try:
                result = self.provider.generate(
                    ImageRequest(prompt=prompt, aspect=self.aspect, quality=self.quality)
                )
            except ProviderError as e:
                if e.fatal:
                    raise
                last_error = str(e)
                continue
            usage += result.usage
            write_bytes_atomic(self.raw_path, result.png_bytes)
            issue = self._check()
            if issue is None and (self.qa is not None or self.qa_check is not None):
                try:
                    qa, used = self._assess(self.renderer.preview(self.raw_path, "frame"))
                except ProviderError as e:
                    if e.fatal:
                        raise
                    qa, used = None, Usage()
                    issue = [QAIssue(criterion="other", detail=f"kontrola jakości: {e}")]
                qa_usage += used
                if qa is not None and not qa.passed:
                    issue = qa.issues
            if issue is None:
                return BelongsToOutcome(
                    status="ok",
                    duration_s=self.clock() - started,
                    prompt=prompt,
                    layout="frame",
                    raw_file=self.raw_path,
                    attempts=attempt,
                    usage=usage,
                    qa=qa,
                    qa_usage=qa_usage,
                    rejected=rejected,
                )
            moved = self._reject(attempt)
            rejected.append(RejectedAttempt(attempt, self.idea, moved, issue))
            last_error = "; ".join(f"{i.criterion}: {i.detail}" for i in issue)

        reason = "przekroczony limit kosztu" if budget else last_error or "brak grafiki"
        failed = BelongsToOutcome(
            status="failed",
            duration_s=self.clock() - started,
            prompt=prompt,
            attempts=attempt,
            usage=usage,
            qa_usage=qa_usage,
            rejected=rejected,
            error=f"{reason}; brak gotowej strony książki do układu zapasowego",
            budget_exceeded=budget,
        )
        if fallback is None:
            return failed
        source, source_raw = fallback
        self.raw_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source_raw, self.raw_path)
        return replace(
            failed,
            status="ok",
            layout="fallback",
            raw_file=self.raw_path,
            fallback_source=source,
            error=None,
        )

    def _check(self) -> list[QAIssue] | None:
        """Problem z polem na tekst albo obróbką; None, gdy pole jest puste."""
        try:
            ink = self.renderer.text_box_ink(self.raw_path)
        except PostprocessError as e:
            return [QAIssue(criterion="other", detail=f"obróbka: {e}")]
        limit = self.renderer.max_ink_ratio
        if limit is not None and ink > limit:
            return [
                QAIssue(
                    criterion="other",
                    detail=f"{self.box_label} nie jest puste ({ink:.1%} tuszu, limit {limit:.1%})",
                )
            ]
        return None
