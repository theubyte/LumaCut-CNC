"""Seriennummern: ein Textobjekt als Raster fortlaufend nummerierter Kopien.

Entspricht dem Stapel-Anwendungsfall von LightBurns „Variable Text“
(Seriennummern auf Schildern, Etiketten, Anhängern): Die Vorlage enthält
Platzhalter, jede Kopie bekommt den nächsten Wert. Qt-frei bis auf die
übergebene Funktion für das Seitenverhältnis des Textes.

Platzhalter:

``{n}``       fortlaufende Nummer (Start, Schritt)
``{n:3}``     Nummer mit führenden Nullen auf 3 Stellen (``007``)
``{date}``    heutiges Datum ``TT.MM.JJJJ``
``{{`` ``}}`` wörtliche geschweifte Klammern
"""

from __future__ import annotations

import datetime as _dt
import re
from dataclasses import dataclass, replace
from typing import Callable

from lumacut_canvas.model import Shape, new_id
from lumacut_canvas.workarea import WORK_HEIGHT_MM, WORK_WIDTH_MM

MAX_COUNT = 500
COUNT_RANGE = (1, MAX_COUNT)
COLUMNS_RANGE = (1, 100)
GAP_RANGE = (0.0, 100.0)
VALUE_RANGE = (-999_999, 999_999)

_TOKEN = re.compile(r"\{\{|\}\}|\{n(?::(\d{1,2}))?\}|\{date\}")


def has_counter(template: str) -> bool:
    return any(m.group(0).startswith("{n") for m in _TOKEN.finditer(template or ""))


def format_serial(template: str, value: int, today: _dt.date | None = None) -> str:
    """Platzhalter in ``template`` durch ``value`` bzw. das Datum ersetzen."""
    today = today or _dt.date.today()

    def sub(m: re.Match) -> str:
        tok = m.group(0)
        if tok == "{{":
            return "{"
        if tok == "}}":
            return "}"
        if tok == "{date}":
            return today.strftime("%d.%m.%Y")
        width = int(m.group(1) or 0)
        sign = "-" if value < 0 else ""
        return sign + str(abs(value)).zfill(width)

    return _TOKEN.sub(sub, template or "")


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


@dataclass(frozen=True)
class SerialSpec:
    template: str = "{n}"
    start: int = 1
    step: int = 1
    count: int = 10
    columns: int = 5
    gap_x_mm: float = 2.0
    gap_y_mm: float = 2.0

    def normalized(self) -> "SerialSpec":
        return SerialSpec(
            template=str(self.template or ""),
            start=int(_clamp(int(self.start), *VALUE_RANGE)),
            step=int(_clamp(int(self.step), *VALUE_RANGE)),
            count=int(_clamp(int(self.count), *COUNT_RANGE)),
            columns=int(_clamp(int(self.columns), *COLUMNS_RANGE)),
            gap_x_mm=float(_clamp(float(self.gap_x_mm), *GAP_RANGE)),
            gap_y_mm=float(_clamp(float(self.gap_y_mm), *GAP_RANGE)),
        )

    def values(self) -> list[int]:
        s = self.normalized()
        return [s.start + i * s.step for i in range(s.count)]

    def texts(self, today: _dt.date | None = None) -> list[str]:
        s = self.normalized()
        return [format_serial(s.template, v, today) for v in s.values()]


def default_template(text: str) -> str:
    """Vorlage für den Dialog: vorhandene Platzhalter behalten, sonst `` {n}`` anhängen."""
    text = text or ""
    if has_counter(text):
        return text
    return f"{text} {{n}}".strip() if text.strip() else "{n}"


def serial_shapes(src: Shape, spec: SerialSpec, aspect: Callable[..., float],
                  today: _dt.date | None = None) -> list[Shape]:
    """Kopien von ``src`` (kind ``text``) mit fortlaufenden Texten im Raster.

    Höhe, Schrift, Drehung, Ebene und horizontale Streckung bleiben erhalten;
    die Breite folgt dem jeweiligen Text. Erste Kopie an der Stelle von
    ``src``, dann zeilenweise. Alle Kopien bilden eine neue Gruppe.
    ``aspect(text, family, bold, italic)`` liefert Breite/Höhe des Textes.
    Wirft ``ValueError``, wenn das Raster nicht auf die Arbeitsfläche passt.
    """
    if src.kind != "text":
        raise ValueError("Seriennummern gehen nur mit einem Textobjekt")
    s = spec.normalized()
    if not has_counter(s.template):
        raise ValueError("Die Vorlage braucht einen Platzhalter {n} (z. B. „Nr. {n:3}“)")
    texts = s.texts(today)
    if any(not t.strip() for t in texts):
        raise ValueError("Die Vorlage ergibt leeren Text")
    g = src.geom
    h = abs(g.h)
    if h <= 0:
        raise ValueError("Das Textobjekt hat keine Höhe")
    base = aspect(src.text, src.font_family, src.font_bold, src.font_italic)
    stretch = abs(g.w) / (h * base) if base > 0 else 1.0
    widths = [h * aspect(t, src.font_family, src.font_bold, src.font_italic) * stretch for t in texts]
    cell_w = max(widths)
    cols = min(s.columns, len(texts))
    rows = (len(texts) + cols - 1) // cols
    group = new_id()
    out: list[Shape] = []
    for i, (text, w) in enumerate(zip(texts, widths)):
        r, c = divmod(i, cols)
        sh = src.copy(new_identity=True)
        sh.text = text
        sh.geom = replace(g.copy(), x=g.x + c * (cell_w + s.gap_x_mm),
                          y=g.y + r * (h + s.gap_y_mm), w=w, h=h)
        sh.groups = (group,) + tuple(src.groups)
        out.append(sh)
    boxes = [sh.bounds() for sh in out]
    x0, y0 = min(b.x for b in boxes), min(b.y for b in boxes)
    x1, y1 = max(b.x + b.w for b in boxes), max(b.y + b.h for b in boxes)
    eps = 1e-6
    if x0 < -eps or y0 < -eps or x1 > WORK_WIDTH_MM + eps or y1 > WORK_HEIGHT_MM + eps:
        raise ValueError(
            f"Raster {x1 - x0:.1f} × {y1 - y0:.1f} mm passt ab X {g.x:.1f} / Y {g.y:.1f} nicht auf die "
            f"Arbeitsfläche ({WORK_WIDTH_MM:.0f} × {WORK_HEIGHT_MM:.0f} mm) – Anzahl, Spalten, Abstand "
            "oder Textgröße ändern oder den Text weiter nach oben links schieben")
    return out
