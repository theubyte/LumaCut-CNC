"""Einlinien-Schriften für Textobjekte (LightBurns *single-line fonts* / xTools
Einlinien-Schrift): jeder Buchstabe ist ein Strich statt eines Umrisses.

Ein Diodenlaser fährt einen Einlinien-Text einmal als Linie ab – schnell, dünn und
gleichmäßig (Beschriftungen, Skalen, kleine Seriennummern, Unterschriften, Stifte im
Plotter-Halter), wo ein Umriss-Text doppelt umfahren oder flächig gefüllt werden muss.

Qt-frei. Die Glyphen kommen aus den Hershey-Schriften (:mod:`linefont_data`);
Umlaute und Akzente werden aus Grundbuchstabe und Zeichen zusammengesetzt, „ß“, „€“
und „°“ sind eigene Striche. Unbekannte Zeichen erscheinen als „?“.

Koordinaten der Hershey-Daten: y nach unten (wie Qt), Grundlinie bei ``BASE_LINE``,
Versalhöhe ``-12`` … ``9`` = 21 Einheiten. Ein Geviert (Schriftgröße) sind
:data:`EM_UNITS` Hershey-Einheiten.
"""

from __future__ import annotations

import math
import unicodedata
from functools import lru_cache

from . import linefont_data

Point = tuple[float, float]
Stroke = list[Point]

# Schriftnamen (``Shape.font_family``). Kein Systemfont heißt so; ältere LumaCut-
# Versionen zeigen dafür ihre Standardschrift.
LINE_FONT_SANS = "LumaCut Einlinie"
LINE_FONT_SCRIPT = "LumaCut Einlinie Schreibschrift"
LINE_FONTS = {LINE_FONT_SANS: "futural", LINE_FONT_SCRIPT: "scripts"}
LINE_FONT_LABELS = {LINE_FONT_SANS: "Einlinie (Sans)", LINE_FONT_SCRIPT: "Einlinie (Schreibschrift)"}

EM_UNITS = 32.0           # Hershey-Einheiten je Geviert (−16 … +16 um die Mitte)
BASE_LINE = 9.0
ITALIC_SLANT = 0.2        # Schrägstellung für „Kursiv“ (x je Einheit Höhe über der Grundlinie)
FALLBACK_CHAR = "?"

# Kombinierende Zeichen -> Akzent-Striche (relativ zur Mitte über dem Buchstaben,
# y = 0 ist die Unterkante des Akzents).
_DOT = [(0.0, -1.0), (-1.0, 0.0), (0.0, 1.0), (1.0, 0.0), (0.0, -1.0)]
_MARKS: dict[str, list[Stroke]] = {
    "\u0308": [[(x - 3.0, y - 1.0) for x, y in _DOT], [(x + 3.0, y - 1.0) for x, y in _DOT]],  # Trema
    "\u0301": [[(-1.0, 0.0), (2.0, -3.0)]],                     # Akut
    "\u0300": [[(1.0, 0.0), (-2.0, -3.0)]],                     # Gravis
    "\u0302": [[(-3.0, 0.0), (0.0, -3.0), (3.0, 0.0)]],         # Zirkumflex
    "\u030C": [[(-3.0, -3.0), (0.0, 0.0), (3.0, -3.0)]],        # Hatschek
    "\u0303": [[(-3.0, -1.0), (-2.0, -2.0), (-1.0, -2.0), (1.0, -1.0), (2.0, -1.0), (3.0, -2.0)]],  # Tilde
    "\u030A": [[(0.0, -3.0), (-1.5, -1.5), (0.0, 0.0), (1.5, -1.5), (0.0, -3.0)]],  # Ring
}
_CEDILLA = [(0.0, 9.0), (0.0, 11.0), (2.0, 11.5), (2.0, 13.0), (-1.0, 13.5)]

# Eigene Zeichen (Hershey-Einheiten, Grundlinie 9): ß, Grad, Euro über „C“.
_ESZETT = ((-6.0, 7.0), [[(-4.0, 9.0), (-4.0, -6.0), (-3.0, -9.0), (-1.0, -11.0), (1.0, -12.0),
                         (3.0, -12.0), (5.0, -11.0), (6.0, -9.0), (6.0, -7.0), (5.0, -5.0),
                         (3.0, -4.0), (1.0, -4.0), (4.0, -3.0), (6.0, -1.0), (7.0, 1.0),
                         (7.0, 4.0), (6.0, 6.0), (4.0, 8.0), (2.0, 9.0), (0.0, 9.0)]])
_DEGREE = ((-4.0, 4.0), [[(math.cos(t) * 2.5, -9.5 + math.sin(t) * 2.5)
                          for t in (2.0 * math.pi * i / 12.0 for i in range(13))]])


# Typografische Zeichen ohne eigene Hershey-Glyphe -> nächstliegendes ASCII-Zeichen.
_ALIASES = {"\u2013": "-", "\u2014": "-", "\u2212": "-", "\u2010": "-", "\u2011": "-",
            "\u201e": '"', "\u201c": '"', "\u201d": '"', "\u00ab": '"', "\u00bb": '"',
            "\u201a": "'", "\u2018": "'", "\u2019": "'", "\u00b4": "'", "\u2032": "'",
            "\u00a0": " ", "\u202f": " ", "\u2009": " ", "\u00d7": "x", "\u00b7": ".",
            "\u2022": "."}


def is_line_font(family: str | None) -> bool:
    """``family`` ist eine der eingebauten Einlinien-Schriften."""
    return isinstance(family, str) and family in LINE_FONTS


class Glyph:
    __slots__ = ("left", "right", "strokes")

    def __init__(self, left: float, right: float, strokes: list[Stroke]) -> None:
        self.left, self.right, self.strokes = left, right, strokes

    @property
    def advance(self) -> float:
        return self.right - self.left


def parse_jhf_line(line: str) -> Glyph:
    """Eine ``.jhf``-Zeile (5 Zeichen Nummer, 3 Zeichen Punktzahl, Paare relativ zu „R“,
    „ R“ = Stift heben) in eine :class:`Glyph`."""
    data = line[8:]
    vals = [(data[i], data[i + 1]) for i in range(0, len(data) - 1, 2)]
    if not vals:
        return Glyph(0.0, 0.0, [])
    left, right = ord(vals[0][0]) - 82, ord(vals[0][1]) - 82
    strokes: list[Stroke] = []
    cur: Stroke = []
    for a, b in vals[1:]:
        if a == " " and b == "R":
            if len(cur) >= 2:
                strokes.append(cur)
            cur = []
            continue
        cur.append((float(ord(a) - 82), float(ord(b) - 82)))
    if len(cur) >= 2:
        strokes.append(cur)
    return Glyph(float(left), float(right), strokes)


@lru_cache(maxsize=None)
def _font(family: str) -> dict[str, Glyph]:
    data = getattr(linefont_data, LINE_FONTS[family].upper())
    lines = [line for line in data if line and not line.startswith("#")]
    glyphs = {chr(32 + i): parse_jhf_line(line) for i, line in enumerate(lines)}
    base_c = glyphs["C"]
    euro = [list(s) for s in base_c.strokes]
    cx = (base_c.left + base_c.right) / 2.0
    euro += [[(base_c.left + 1.0, -4.0), (cx + 2.0, -4.0)], [(base_c.left + 1.0, 0.0), (cx + 1.0, 0.0)]]
    glyphs["\u20ac"] = Glyph(base_c.left - 1.0, base_c.right, euro)
    glyphs["\u00df"] = Glyph(_ESZETT[0][0], _ESZETT[0][1], [list(s) for s in _ESZETT[1]])
    glyphs["\u00b0"] = Glyph(_DEGREE[0][0], _DEGREE[0][1], [list(s) for s in _DEGREE[1]])
    dot = glyphs["."]
    glyphs["\u2026"] = Glyph(dot.left, dot.left + 3.0 * dot.advance,      # Auslassungspunkte
                             [[(x + k * dot.advance, y) for x, y in st] for k in range(3) for st in dot.strokes])
    for alias, target in _ALIASES.items():
        glyphs[alias] = glyphs[target]
    return glyphs


def _composed(glyphs: dict[str, Glyph], ch: str) -> Glyph | None:
    """Umlaut / Akzentbuchstabe aus Grundbuchstabe + Zeichen (Unicode-Zerlegung)."""
    decomp = unicodedata.normalize("NFD", ch)
    if len(decomp) < 2 or decomp[0] not in glyphs:
        return None
    base = glyphs[decomp[0]]
    marks = decomp[1:]
    if not base.strokes or any(m not in _MARKS and m != "\u0327" for m in marks):
        return None
    pts = [p for s in base.strokes for p in s]
    top = min(y for _x, y in pts)
    if decomp[0] in "ij":          # Punkt des i / j durch das Zeichen ersetzen
        body = [s for s in base.strokes if max(y for _x, y in s) > top + 3.0]
        pts_body = [p for s in body for p in s]
        if body and pts_body:
            base = Glyph(base.left, base.right, body)
            top = min(y for _x, y in pts_body)
            pts = pts_body
    band = [x for x, y in pts if y <= top + 3.0]
    cx = sum(band) / len(band) if band else (base.left + base.right) / 2.0
    strokes = [list(s) for s in base.strokes]
    y0 = top - 2.0
    for m in marks:
        if m == "\u0327":
            strokes.append([(cx + x, y) for x, y in _CEDILLA])
            continue
        strokes += [[(cx + x, y0 + y) for x, y in s] for s in _MARKS[m]]
        y0 -= 4.0
    return Glyph(base.left, base.right, strokes)


_CACHE: dict[tuple[str, str], Glyph] = {}


def glyph(family: str, ch: str) -> Glyph:
    """Glyphe für ``ch`` (zusammengesetzt oder „?“, wenn die Schrift es nicht kennt)."""
    key = (family, ch)
    g = _CACHE.get(key)
    if g is None:
        glyphs = _font(family)
        g = glyphs.get(" " if ch == "\t" else ch) or _composed(glyphs, ch) or glyphs[FALLBACK_CHAR]
        _CACHE[key] = g
    return g


def has_glyph(family: str, ch: str) -> bool:
    """Die Schrift kann ``ch`` zeichnen (eigene oder zusammengesetzte Glyphe)."""
    glyphs = _font(family)
    return ch in "\n\t" or ch in glyphs or _composed(glyphs, ch) is not None


def missing_chars(text: str, family: str) -> str:
    """Zeichen von ``text``, die die Einlinien-Schrift nur als „?“ zeigen kann."""
    return "".join(ch for ch in dict.fromkeys(text or "") if not has_glyph(family, ch))


def line_advance(line: str, family: str, letter_spacing_units: float = 0.0) -> float:
    """Laufweite einer Zeile in Hershey-Einheiten (mit Zusatzabstand je Zeichen)."""
    return sum(glyph(family, ch).advance + letter_spacing_units for ch in line)


def text_strokes(text: str, family: str, italic: bool = False, *, letter_spacing: float = 0.0,
                 line_spacing: float = 100.0, align: str = "left",
                 pitch_units: float = 1.25 * EM_UNITS * 0.75) -> list[Stroke]:
    """Striche eines (mehrzeiligen) Textes in Hershey-Einheiten.

    Text-Satz wie :func:`shape_paths.text_path`: ``letter_spacing`` in % des Gevierts
    nach jedem Zeichen, ``line_spacing`` in % von ``pitch_units`` (Zeilenabstand),
    ``align`` richtet die Zeilen nach ihrer Laufweite aus. ``italic`` stellt schräg.
    Zeile i hat ihre Grundlinie bei ``BASE_LINE + i · pitch``.
    """
    extra = letter_spacing / 100.0 * EM_UNITS
    pitch = pitch_units * (line_spacing / 100.0 if line_spacing != 100.0 else 1.0)
    lines = (text or "").split("\n")
    adv = [line_advance(line, family, extra) for line in lines]
    widest = max(adv) if adv else 0.0
    share = {"center": 0.5, "right": 1.0}.get(align, 0.0) if len(lines) > 1 else 0.0
    out: list[Stroke] = []
    for i, line in enumerate(lines):
        x = (widest - adv[i]) * share
        dy = i * pitch
        for ch in line:
            g = glyph(family, ch)
            for s in g.strokes:
                pts = []
                for gx, gy in s:
                    px = x + gx - g.left
                    if italic:
                        px += ITALIC_SLANT * (BASE_LINE - gy)
                    pts.append((px, gy + dy))
                out.append(pts)
            x += g.advance + extra
    return out


__all__ = ["EM_UNITS", "LINE_FONTS", "LINE_FONT_LABELS", "LINE_FONT_SANS", "LINE_FONT_SCRIPT",
           "Glyph", "glyph", "has_glyph", "is_line_font", "line_advance", "missing_chars", "parse_jhf_line",
           "text_strokes"]
