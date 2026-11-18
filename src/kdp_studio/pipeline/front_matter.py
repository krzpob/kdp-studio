"""FR-23: strony wstępne: strona tytułowa do kolorowania, prawa autorskie i instrukcja.

Strona 1 to tytułowa do kolorowania (`front_title.png`) albo „This book belongs to…” (FR-14).
Tytułową rysuje model jak ramkę FR-14: scena z motywem książki z pustym górnym pasem, w który
program wpisuje tytuł konturowymi literami. Bez modelu (gdy `front-matter` nie było
uruchomione) `finalize` robi stronę 1 z samym tytułem na środku (układ `text_only`).

Prawa autorskie (`front_copyright.png`) i teksty instrukcji (`front_instructions.png`) pochodzą
z `texts` w `config/markets.yaml` według języka rynku książki (FR-19) i wpisuje je program,
bez modelu. Instrukcja ma pod tekstem ilustrację z modelu z główną postacią książki, a po
nieudanych próbach grafikę zapasową z `assets/` (SVG bez postaci).
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass, replace
from pathlib import Path

import resvg_py
from PIL import Image, ImageDraw, ImageFont

from kdp_studio.config import (
    AppConfig,
    FrontMatterSettings,
    FrontTexts,
    InstructionsSettings,
    PostprocessParams,
    TitlePageSettings,
)
from kdp_studio.models import BookIdeas, BookSpec
from kdp_studio.pipeline.belongs_to import Layout, Rect, ink_ratio, theme_elements
from kdp_studio.pipeline.fonts import FontError, load_font
from kdp_studio.pipeline.ideas import _respell
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
from kdp_studio.pipeline.prompts import PromptBuilder

TITLE_NAME = "front_title"
COPYRIGHT_NAME = "front_copyright"
INSTRUCTIONS_NAME = "front_instructions"
TITLE_IDEA = "title"  # id „pomysłu” w odrzuconych próbach
INSTRUCTIONS_IDEA = "instructions"

LINE_SPACING = 1.25  # wysokość wiersza względem rozmiaru czcionki
PARAGRAPH_GAP = 0.5  # odstęp między akapitami, ułamek wysokości wiersza
TITLE_WIDTH = 0.94  # najszerszy wiersz tytułu względem szerokości pola (obrys wychodzi poza)
TITLE_MAX_LINES = 3
MIN_TITLE_SCALE = 0.35  # tytuł nie zmniejsza się bardziej niż do 35% rozmiaru z ustawień
MIN_TEXT_SCALE = 0.6  # teksty instrukcji nie zmniejszają się bardziej niż do 60%
ART_GAP = 0.03  # odstęp tekstu od grafiki, ułamek wysokości obszaru treści


class FrontMatterError(Exception):
    """Brak tłumaczenia albo właściciela praw dla stron wstępnych (kod 1, przed API)."""


# --- Teksty ----------------------------------------------------------------------------------


def front_texts(config: AppConfig, market: str) -> FrontTexts:
    """Teksty stron wstępnych w języku rynku, w pisowni rynku (np. „colour” na CA i AU)."""
    profile = config.markets.markets[market]
    texts = config.markets.texts_for(profile.locale)
    if texts is None:
        raise FrontMatterError(
            f"brak tekstów stron wstępnych (prawa autorskie, instrukcja) dla rynku {market} "
            f"({profile.locale}): dodaj tłumaczenie w texts w config/markets.yaml"
        )
    spelling = {wrong.casefold(): right for wrong, right in profile.spelling.items()}
    if not spelling:
        return texts

    def fixed(values: dict[str, str]) -> dict[str, str]:
        return {key: _respell(text, spelling)[0] for key, text in values.items()}

    return texts.model_copy(
        update={
            "copyright": fixed(texts.copyright),
            "instructions": fixed(texts.instructions),
        }
    )


def copyright_paragraphs(texts: FrontTexts, variant: str, year: int, owner: str) -> list[str]:
    """Akapity strony praw autorskich: każdy wiersz tekstu z konfiguracji to osobny akapit."""
    text = texts.copyright[variant].format(year=year, owner=owner.strip())
    return [line.strip() for line in text.splitlines() if line.strip()]


def book_year(created_at: str) -> int:
    """Rok z daty utworzenia książki w manifeście: ponowne `finalize` w styczniu go nie zmienia."""
    return int(created_at[:4])


# --- Składanie tekstu --------------------------------------------------------------------------


def _font(path: Path, size: int, variation: str | None) -> ImageFont.FreeTypeFont:
    try:
        return load_font(path, size, variation)
    except FontError as e:
        raise PostprocessError(str(e)) from e


def wrap(text: str, font: ImageFont.FreeTypeFont, width: float) -> list[str]:
    """Wiersze tekstu nie szersze niż `width` (podział na słowach; za długie słowo zostaje)."""
    lines: list[str] = []
    current = ""
    for word in text.split():
        candidate = f"{current} {word}".strip()
        if current and font.getlength(candidate) > width:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines


def line_height(font: ImageFont.FreeTypeFont) -> int:
    """Wysokość wiersza: co najmniej od górnej do dolnej linii czcionki (z wydłużeniami
    liter), żeby ostatni wiersz nie wychodził poza margines."""
    ascent, descent = font.getmetrics()
    return max(round((font.size or 1) * LINE_SPACING), ascent + descent)


def _left_x(left: float, line: str, font: ImageFont.FreeTypeFont) -> float:
    """Pozycja wiersza wyrównanego do lewej: litera z ujemnym odstępem (np. „©”, „J”) nie
    wychodzi poza obszar treści."""
    return left - min(0.0, font.getbbox(line, anchor="la")[0])


def _blank_page(geometry: PageGeometry) -> Image.Image:
    return Image.new("L", geometry.page_px, WHITE)


def _two_tone(img: Image.Image) -> Image.Image:
    return img.point(lambda v: BLACK if v < RETHRESHOLD else WHITE, mode="L")


def _save_checked(img: Image.Image, path: Path, geometry: PageGeometry) -> None:
    save_page_png(_two_tone(img), path, geometry.dpi)
    problems = verify_page(path, geometry)
    if problems:
        raise PostprocessError("; ".join(problems))


def render_copyright(
    book_dir: Path, geometry: PageGeometry, settings: FrontMatterSettings, paragraphs: list[str]
) -> Path:
    """`front_copyright.png`: akapity wyrównane do lewej, blok tuż nad dolnym marginesem.

    Za długi tekst program zmniejsza do `copyright_min_pt`; dalej PostprocessError.
    """
    left, top, right, bottom = geometry.content_box
    width, height = right - left, bottom - top
    pt = settings.copyright_pt
    while True:
        size = max(1, round(pt / 72 * geometry.dpi))
        font = _font(settings.text_font_path, size, settings.text_font_variation)
        blocks = [wrap(p, font, width) for p in paragraphs]
        line_h = line_height(font)
        gap = round(line_h * PARAGRAPH_GAP)
        total = sum(len(b) for b in blocks) * line_h + gap * (len(blocks) - 1)
        widest = max((font.getlength(line) for b in blocks for line in b), default=0)
        if total <= height and widest <= width:
            break
        pt -= 0.5
        if pt < settings.copyright_min_pt:
            raise PostprocessError(
                "tekst praw autorskich nie mieści się na stronie nawet w "
                f"{settings.copyright_min_pt:g} pt (front_matter.copyright_min_pt)"
            )
    img = _blank_page(geometry)
    draw = ImageDraw.Draw(img)
    draw.fontmode = "1"  # bez antyaliasingu: tylko czerń i biel
    y = bottom - total
    for index, block in enumerate(blocks):
        for line in block:
            draw.text((_left_x(left, line, font), y), line, font=font, fill=BLACK, anchor="la")
            y += line_h
        if index < len(blocks) - 1:
            y += gap
    path = book_dir / f"{COPYRIGHT_NAME}.png"
    _save_checked(img, path, geometry)
    return path


def draw_title(
    img: Image.Image,
    rect: Rect,
    title: str,
    font_path: Path,
    variation: str | None,
    max_px: int,
) -> Image.Image:
    """Tytuł konturowymi literami (biały środek do pokolorowania), wyśrodkowany w prostokącie,
    najwyżej w trzech wierszach; zmniejszany, aż się zmieści."""
    left, top, right, bottom = rect
    width, height = right - left, bottom - top
    size = max_px
    while True:
        font = _font(font_path, size, variation)
        lines = wrap(title, font, width * TITLE_WIDTH)
        line_h = round(size * 1.15)
        widest = max((font.getlength(line) for line in lines), default=0)
        fits = len(lines) <= TITLE_MAX_LINES and widest <= width * TITLE_WIDTH
        if fits and len(lines) * line_h <= height:
            break
        size = int(size * 0.92)
        if size < max_px * MIN_TITLE_SCALE:
            raise PostprocessError("tytuł nie mieści się w polu na tytuł (za małe pole)")
    out = img.convert("L").copy()
    draw = ImageDraw.Draw(out)
    draw.fontmode = "1"
    stroke = max(2, round(size * 0.045))
    y = top + (height - len(lines) * line_h) / 2 + line_h / 2
    center = left + width / 2
    for line in lines:
        draw.text(
            (center, y), line, font=font, fill=WHITE, stroke_width=stroke, stroke_fill=BLACK,
            anchor="mm",
        )  # fmt: skip
        y += line_h
    return _two_tone(out)


# --- Strona tytułowa -----------------------------------------------------------------------------


def title_prompt(spec: BookSpec, config: AppConfig, ideas: BookIdeas) -> tuple[str, list[str]]:
    """Prompt sceny z pustym górnym pasem na tytuł i użyte elementy motywu."""
    settings = config.settings.title_page
    elements = theme_elements(ideas, spec.pages)
    theme = " ".join(ideas.book.title.lower().split())
    decorated = f", with {', '.join(elements)}" if elements else ""
    composition = " ".join(settings.composition.split()).rstrip(" .")
    scene = (
        f"Scene: {composition}{decorated}. The picture matches a coloring book about {theme}. "
        "Leave the top of the page blank: the title will be added later.\n"
    )
    return scene + PromptBuilder(spec, config).style_block, elements


@dataclass(frozen=True)
class TitleRenderer:
    """Surowa grafika → `front_title.png` z tytułem; bez grafiki: sam tytuł (`text_only`)."""

    book_dir: Path
    geometry: PageGeometry
    params: PostprocessParams
    settings: TitlePageSettings
    font_path: Path  # czcionka napisów rynku (FR-19)
    title: str

    @property
    def max_retries(self) -> int:
        return self.settings.max_retries

    @property
    def max_ink_ratio(self) -> float | None:
        return self.settings.max_ink_ratio

    def text_rect(self, layout: Layout) -> Rect:
        if layout == "text_only":
            return self.geometry.area(0.0, 0.0, 1.0, 1.0)
        box = self.settings.text_box
        return self.geometry.area(box.x, box.y, box.width, box.height)

    def art_geometry(self, layout: Layout) -> PageGeometry:
        if layout == "frame":
            return self.geometry
        # Układ zapasowy: grafika pierwszej strony książki pod polem na tytuł.
        box = self.settings.text_box
        below = min(0.9, box.y + box.height + ART_GAP)
        return self.geometry.with_art(0.0, below, 1.0, 1.0 - below)

    def _postprocessor(self, layout: Layout, book_dir: Path) -> PagePostprocessor:
        return PagePostprocessor(
            book_dir=book_dir, geometry=self.art_geometry(layout), params=self.params
        )

    def _max_px(self) -> int:
        return max(1, round(self.settings.font_pt / 72 * self.geometry.dpi))

    def text_box_ink(self, raw: Path) -> float:
        with tempfile.TemporaryDirectory(prefix="kdp-studio-title-") as tmp:
            files = self._postprocessor("frame", Path(tmp)).process(raw, TITLE_NAME)
            with Image.open(files.page) as img:
                return ink_ratio(img, self.text_rect("frame"))

    def render(self, raw: Path, layout: Layout) -> PageFiles:
        files = self._postprocessor(layout, self.book_dir).process(raw, TITLE_NAME)
        with Image.open(files.page) as img:
            page = draw_title(
                img,
                self.text_rect(layout),
                self.title,
                self.font_path,
                self.settings.font_variation,
                self._max_px(),
            )
        _save_checked(page, files.page, self.geometry)
        return files

    def render_text_only(self) -> Path:
        """Strona 1 bez modelu: sam tytuł na środku (`finalize`, gdy nie było `front-matter`)."""
        page = draw_title(
            _blank_page(self.geometry),
            self.text_rect("text_only"),
            self.title,
            self.font_path,
            self.settings.font_variation,
            self._max_px(),
        )
        path = self.book_dir / f"{TITLE_NAME}.png"
        _save_checked(page, path, self.geometry)
        return path

    def preview(self, raw: Path, layout: Layout) -> bytes:
        with tempfile.TemporaryDirectory(prefix="kdp-studio-title-") as tmp:
            return replace(self, book_dir=Path(tmp)).render(raw, layout).page.read_bytes()


# --- Instrukcja ----------------------------------------------------------------------------------


def main_subject(ideas: BookIdeas, pages: int) -> str:
    """Główna postać książki: najczęstszy `subject` stron (jak w FR-14)."""
    elements = theme_elements(ideas, pages, count=1)
    return elements[0] if elements else "character"


def instructions_prompt(spec: BookSpec, config: AppConfig, ideas: BookIdeas) -> tuple[str, str]:
    """Prompt ilustracji instrukcji i główna postać, z blokiem stylu stron (FR-04)."""
    subject = main_subject(ideas, spec.pages)
    composition = " ".join(config.settings.instructions.composition.split()).rstrip(" .")
    scene = f"Scene: {composition.format(subject=f'a friendly {subject}')}.\n"
    return scene + PromptBuilder(spec, config).style_block, subject


def fallback_instructions_art(svg: Path, target: Path) -> Path:
    """Grafika zapasowa instrukcji (SVG z `assets/`) jako PNG do obróbki jak grafika modelu."""
    try:
        png = resvg_py.svg_to_bytes(svg_path=str(svg))
    except (OSError, ValueError) as e:
        raise PostprocessError(f"nie można wyrenderować {svg}: {e}") from e
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(bytes(png))
    return target


@dataclass(frozen=True)
class InstructionsRenderer:
    """Surowa ilustracja → `front_instructions.png`: teksty u góry, ilustracja w `art_box`."""

    book_dir: Path
    geometry: PageGeometry
    params: PostprocessParams
    settings: InstructionsSettings
    front: FrontMatterSettings
    heading_font: Path  # czcionka napisów rynku (FR-19), wariant heading_variation
    texts: dict[str, str]  # heading, intro, section, body

    @property
    def max_retries(self) -> int:
        return self.settings.max_retries

    @property
    def max_ink_ratio(self) -> float | None:
        return None  # ilustracja nie ma pola na tekst; teksty są nad nią

    def text_box_ink(self, raw: Path) -> float:
        return 0.0

    def art_geometry(self) -> PageGeometry:
        box = self.settings.art_box
        return self.geometry.with_art(box.x, box.y, box.width, box.height)

    def text_rect(self) -> Rect:
        top = max(0.05, self.settings.art_box.y - ART_GAP)
        return self.geometry.area(0.0, 0.0, 1.0, top)

    def _items(self, scale: float) -> list[tuple[str, ImageFont.FreeTypeFont, bool, float]]:
        """(tekst, czcionka, wyśrodkowany, odstęp przed w wierszach) w skali `scale`."""
        dpi = self.geometry.dpi

        def px(pt: float) -> int:
            return max(1, round(pt * scale / 72 * dpi))

        front, settings = self.front, self.settings
        heading = _font(self.heading_font, px(settings.heading_pt), settings.heading_variation)
        body = _font(front.text_font_path, px(settings.body_pt), front.text_font_variation)
        section = _font(front.text_font_path, px(settings.section_pt), front.text_bold_variation)
        return [
            (self.texts["heading"], heading, True, 0.0),
            (self.texts["intro"], body, False, 0.8),
            (self.texts["section"], section, False, 0.8),
            (self.texts["body"], body, False, 0.3),
        ]

    def _draw_texts(self, img: Image.Image) -> Image.Image:
        left, top, right, bottom = self.text_rect()
        width, height = right - left, bottom - top
        scale = 1.0
        while True:
            layout = []
            total = 0.0
            for text, font, centered, before in self._items(scale):
                line_h = line_height(font)
                lines = wrap(text, font, width)
                total += before * line_h + len(lines) * line_h
                layout.append((lines, font, centered, before, line_h))
            widest = max(f.getlength(line) for lines, f, *_ in layout for line in lines)
            if total <= height and widest <= width:
                break
            scale *= 0.92
            if scale < MIN_TEXT_SCALE:
                raise PostprocessError("teksty instrukcji nie mieszczą się nad ilustracją")
        out = img.convert("L").copy()
        draw = ImageDraw.Draw(out)
        draw.fontmode = "1"
        y = float(top)
        for lines, font, centered, before, line_h in layout:
            y += before * line_h
            for line in lines:
                if centered:
                    draw.text((left + width / 2, y), line, font=font, fill=BLACK, anchor="ma")
                else:
                    draw.text(
                        (_left_x(left, line, font), y), line, font=font, fill=BLACK, anchor="la"
                    )
                y += line_h
        return _two_tone(out)

    def render(self, raw: Path, layout: Layout) -> PageFiles:
        processor = PagePostprocessor(
            book_dir=self.book_dir, geometry=self.art_geometry(), params=self.params
        )
        files = processor.process(raw, INSTRUCTIONS_NAME)
        with Image.open(files.page) as img:
            page = self._draw_texts(img)
        _save_checked(page, files.page, self.geometry)
        return files

    def preview(self, raw: Path, layout: Layout) -> bytes:
        with tempfile.TemporaryDirectory(prefix="kdp-studio-instr-") as tmp:
            return replace(self, book_dir=Path(tmp)).render(raw, layout).page.read_bytes()
