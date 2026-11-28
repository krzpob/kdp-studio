"""FR-24: kontrola grafik kolumn A+ z modelu obrazu modelem z wizją (`aplus --qa`).

Grafika z modelu idzie na stronę produktu, więc nie może wprowadzać w błąd: kontrola dostaje
jeden obraz z dwiema częściami, po lewej prawdziwą stronę książki (referencja), po prawej
grafikę z modelu, i sprawdza stałe zasady (bez napisów i twarzy, prawdziwa oprawa, ta sama
strona) oraz kryteria motywu z profilu wieku (`aplus_features[].checks`, np. czysty tył kartki
i kolorowanie pisakami w motywie o druku jednostronnym).
"""

from __future__ import annotations

import io
from typing import Literal

from PIL import Image
from pydantic import BaseModel, ConfigDict, Field

from kdp_studio.config import AplusFeatureTheme
from kdp_studio.providers.base import Usage, VisionProvider

QA_SIDE_PX = 768  # wysokość każdej części obrazu do kontroli
GAP_PX = 24

FeatureCriterion = Literal[
    "text", "people", "page_mismatch", "binding", "theme_mismatch", "protected_character", "other"
]


class FeatureQAIssue(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    criterion: FeatureCriterion
    detail: str  # po polsku


class FeatureQAResult(BaseModel):
    """Wynik kontroli grafiki kolumny w manifeście: `{"pass": …, "issues": […]}`."""

    model_config = ConfigDict(
        frozen=True, extra="forbid", validate_by_name=True, serialize_by_alias=True
    )

    passed: bool = Field(alias="pass")
    issues: list[FeatureQAIssue] = []

    def summary(self) -> str:
        return "; ".join(f"{i.criterion}: {i.detail}" for i in self.issues) or "bez powodu"


class _LLMFeatureVerdict(BaseModel):
    passed: bool
    issues: list[FeatureQAIssue]


QA_INSTRUCTIONS = """\
You are the quality checker for a product photo shown on the Amazon page of a printed coloring \
book. The image has two parts. LEFT: the real black-and-white page from the book. RIGHT: the \
photo generated for the product page. The photo must show this: {scene}. It illustrates this \
benefit for the buyer: {benefit}. The book page shows {page_scene}.

Reject (passed = false) only for these problems, each a separate issue:
- text: any letters, words, numbers, signatures, logos or watermarks in the photo, including \
garbled pseudo-letters.
- people: a face, a head or a whole person; only hands are allowed.
- page_mismatch: the coloring page in the photo shows a different drawing than the book page on \
the left (other subject, other composition, missing or added main elements). Colour added on \
top of the same drawing is fine.
- binding: a spiral or ring binding, perforated tear-out edges, thick card pages or anything \
else that a glued paperback with plain white paper does not have.
- protected_character: a well-known character or a brand from films, games or toys.
- theme_mismatch: the photo does not show the scene above, or breaks one of these checks:
{checks}
- other: any other defect a buyer would notice (deformed hands, broken objects, a messy or \
cut-off main subject).

Calibration: a typical good photo passes; do not reject for matters of taste or for small \
props. When it fails, list every problem, each detail in Polish, briefly, pointing to where it \
is in the photo.
"""

DEFAULT_CHECK = "  - the photo clearly shows the benefit above."


def qa_instructions(theme: AplusFeatureTheme, page_scene: str) -> str:
    checks = "\n".join(f"  - {c.strip()}" for c in theme.checks) or DEFAULT_CHECK
    return QA_INSTRUCTIONS.format(
        scene=theme.scene.strip().rstrip("."),
        benefit=theme.benefit.strip().rstrip("."),
        page_scene=page_scene,
        checks=checks,
    )


def _fit_height(image: Image.Image, height: int) -> Image.Image:
    rgb = image.convert("RGB")
    width = max(1, round(rgb.width * height / rgb.height))
    return rgb.resize((width, height), Image.Resampling.LANCZOS)


def side_by_side(page: Image.Image, photo: Image.Image) -> bytes:
    """Jeden PNG do kontroli: strona książki po lewej, grafika z modelu po prawej."""
    left = _fit_height(page, QA_SIDE_PX)
    right = _fit_height(photo, QA_SIDE_PX)
    sheet = Image.new("RGB", (left.width + GAP_PX + right.width, QA_SIDE_PX), (128, 128, 128))
    sheet.paste(left, (0, 0))
    sheet.paste(right, (left.width + GAP_PX, 0))
    buffer = io.BytesIO()
    sheet.save(buffer, format="PNG")
    return buffer.getvalue()


def check_feature(
    vision: VisionProvider,
    page: Image.Image,
    photo: Image.Image,
    theme: AplusFeatureTheme,
    page_scene: str,
) -> tuple[FeatureQAResult, Usage]:
    verdict, usage = vision.assess(
        side_by_side(page, photo), qa_instructions(theme, page_scene), _LLMFeatureVerdict
    )
    issues = list(verdict.issues)
    if not verdict.passed and not issues:
        issues = [FeatureQAIssue(criterion="other", detail="model odrzucił grafikę bez powodu")]
    return FeatureQAResult(passed=verdict.passed, issues=issues), usage
