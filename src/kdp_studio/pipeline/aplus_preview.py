"""FR-24: podgląd `aplus.html` ułożony jak moduły A+, z przyciskiem kopiowania przy każdym polu.

Edytor A+ nie zamienia wklejonego HTML na formatowanie (sprawdzone 24.11.2026), więc przycisk
kopiuje zwykły tekst, a punkty listy jako osobne wiersze. Pogrubienie i listę nakłada się
paskiem narzędzi edytora; podgląd mówi, gdzie.
"""

from __future__ import annotations

import html
from collections.abc import Sequence
from dataclasses import dataclass, field

from kdp_studio.pipeline.aplus_models import AplusFileInfo, ChartColumn

PREVIEW_FILE = "aplus.html"


@dataclass(frozen=True)
class PreviewField:
    label: str
    text: str
    limit: int | None = None
    hint: str = ""
    lines: bool = False  # punkty listy, każdy w osobnym wierszu


@dataclass(frozen=True)
class PreviewModule:
    title: str  # „2. Standard Image Header With Text”
    note: str = ""
    images: Sequence[AplusFileInfo] = ()
    fields: Sequence[PreviewField] = ()
    chart: Sequence[ChartColumn] = ()
    warnings: Sequence[str] = field(default_factory=tuple)
    alts: Sequence[str] = ()  # tekst alternatywny każdej grafiki z `images`
    chart_alts: Sequence[str] = ()  # tekst alternatywny okładki w każdej kolumnie tabeli
    alt_limit: int | None = None


STYLE = """
body { font: 15px/1.45 -apple-system, "Segoe UI", sans-serif; margin: 0; background: #f4f2ee;
  color: #222; }
main { max-width: 1000px; margin: 0 auto; padding: 24px 16px 64px; }
h1 { font-size: 22px; margin: 0 0 4px; }
.lead { color: #555; margin: 0 0 24px; }
section { background: #fff; border-radius: 10px; padding: 18px 20px; margin: 0 0 20px;
  box-shadow: 0 1px 3px rgba(0,0,0,.08); }
h2 { font-size: 17px; margin: 0 0 6px; }
.note { color: #555; margin: 0 0 12px; }
.images { display: flex; flex-wrap: wrap; gap: 12px; margin: 0 0 12px; }
figure { margin: 0; flex: 1 1 200px; max-width: 100%; }
figure img { width: 100%; height: auto; border: 1px solid #ddd; border-radius: 4px; }
figcaption { font-size: 12px; color: #666; }
.field { border-top: 1px solid #eee; padding: 10px 0; }
.field-head { display: flex; align-items: center; gap: 10px; }
.field-head strong { flex: 1; }
.count { font-size: 12px; color: #666; }
.count.over { color: #b00020; font-weight: bold; }
.text { white-space: pre-wrap; margin: 6px 0 0; }
.hint { font-size: 12px; color: #7a5b00; margin: 4px 0 0; }
.warn { color: #b00020; font-size: 13px; }
.alt { font-size: 12px; color: #333; margin: 4px 0 0; }
button { cursor: pointer; border: 1px solid #888; background: #fafafa; border-radius: 6px;
  padding: 3px 10px; font: inherit; font-size: 13px; }
button.done { background: #dff3e0; border-color: #4a8; }
table { border-collapse: collapse; width: 100%; font-size: 14px; }
td, th { border: 1px solid #ddd; padding: 6px 8px; text-align: left; vertical-align: top; }
"""

SCRIPT = """
document.querySelectorAll("button[data-copy]").forEach(function (button) {
  button.addEventListener("click", function () {
    var text = button.getAttribute("data-copy");
    var done = function () {
      button.classList.add("done");
      button.textContent = "Skopiowano";
      setTimeout(function () { button.classList.remove("done"); button.textContent = "Kopiuj"; },
        1500);
    };
    var fallback = function () {
      var area = document.createElement("textarea");
      area.value = text;
      area.style.position = "fixed";
      area.style.opacity = "0";
      document.body.appendChild(area);
      area.select();
      var ok = false;
      try { ok = document.execCommand("copy"); } catch (e) { ok = false; }
      document.body.removeChild(area);
      if (ok) { done(); } else { button.textContent = "Zaznacz i skopiuj ręcznie"; }
    };
    if (navigator.clipboard && window.isSecureContext) {
      navigator.clipboard.writeText(text).then(done, fallback);
    } else {
      fallback();
    }
  });
});
"""


def _esc(text: str) -> str:
    return html.escape(text, quote=True)


def _button(text: str) -> str:
    return f'<button type="button" data-copy="{_esc(text)}">Kopiuj</button>'


def _field(item: PreviewField) -> str:
    count = ""
    if item.limit is not None:
        over = " over" if len(item.text) > item.limit else ""
        count = f'<span class="count{over}">{len(item.text)} / {item.limit} znaków</span>'
    body = _esc(item.text) if item.text else "<em>(puste: pole można pominąć)</em>"
    hint = f'<p class="hint">{_esc(item.hint)}</p>' if item.hint else ""
    copy = _button(item.text) if item.text else ""
    return (
        f'<div class="field"><div class="field-head"><strong>{_esc(item.label)}</strong>'
        f'{count}{copy}</div><p class="text">{body}</p>{hint}</div>'
    )


def _alt(text: str, limit: int | None) -> str:
    """Tekst alternatywny pod grafiką: A+ wymaga go przy każdej grafice."""
    if not text:
        return '<p class="warn">⚠ Brak tekstu alternatywnego: A+ go wymaga.</p>'
    count = ""
    if limit is not None:
        over = " over" if len(text) > limit else ""
        count = f' <span class="count{over}">{len(text)} / {limit}</span>'
    return f'<p class="alt">Tekst alternatywny{count}: {_esc(text)} {_button(text)}</p>'


def _image(info: AplusFileInfo, alt: str = "", limit: int | None = None) -> str:
    size = f"{info.bytes / 1024:.0f} KB"
    return (
        f'<figure><img src="{_esc(info.path)}" alt="{_esc(alt or info.path)}">'
        f"<figcaption>{_esc(info.path)} · {info.width} × {info.height} px · {size}</figcaption>"
        f"{_alt(alt, limit)}</figure>"
    )


def _chart(
    columns: Sequence[ChartColumn], alts: Sequence[str] = (), limit: int | None = None
) -> str:
    labels = list(columns[0].rows) if columns else []
    alts = list(alts) + [""] * (len(columns) - len(alts))
    head = "".join(
        f"<th>{_esc(c.title)}<br><small>{_esc(c.asin or 'ta książka (ASIN po publikacji)')}"
        f"{' ' + _button(c.asin) if c.asin else ''}</small>{_alt(alt, limit)}</th>"
        for c, alt in zip(columns, alts, strict=True)
    )
    rows = "".join(
        f"<tr><th>{_esc(label)} {_button(label)}</th>"
        + "".join(
            f"<td>{_esc(c.rows.get(label, ''))} {_button(c.rows.get(label, ''))}</td>"
            for c in columns
        )
        + "</tr>"
        for label in labels
    )
    return f"<table><tr><th></th>{head}</tr>{rows}</table>"


def render_preview(title: str, modules: Sequence[PreviewModule]) -> str:
    """Strona HTML z modułami w kolejności edytora A+."""
    parts = []
    for module in modules:
        note = f'<p class="note">{_esc(module.note)}</p>' if module.note else ""
        warnings = "".join(f'<p class="warn">⚠ {_esc(w)}</p>' for w in module.warnings)
        alts = list(module.alts) + [""] * (len(module.images) - len(module.alts))
        images = "".join(
            _image(i, a, module.alt_limit) for i, a in zip(module.images, alts, strict=True)
        )
        images = f'<div class="images">{images}</div>' if images else ""
        fields = "".join(_field(f) for f in module.fields)
        chart = _chart(module.chart, module.chart_alts, module.alt_limit) if module.chart else ""
        parts.append(
            f"<section><h2>{_esc(module.title)}</h2>{note}{warnings}{images}{fields}{chart}"
            "</section>"
        )
    return (
        '<!doctype html>\n<html lang="pl"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f"<title>A+ Content: {_esc(title)}</title><style>{STYLE}</style></head><body><main>"
        f"<h1>A+ Content: {_esc(title)}</h1>"
        '<p class="lead">Moduły w kolejności na stronie. Obrazy wgraj z katalogu aplus/, teksty '
        "skopiuj przyciskiem „Kopiuj” (zwykły tekst). Pogrubienie i listy nałóż paskiem "
        "narzędzi edytora A+, bo edytor nie przyjmuje HTML. Każda grafika potrzebuje tekstu "
        "alternatywnego: jest pod nią, też z przyciskiem.</p>"
        + "".join(parts)
        + f"<script>{SCRIPT}</script></main></body></html>\n"
    )
