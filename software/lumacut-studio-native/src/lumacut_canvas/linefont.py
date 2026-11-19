"""Einlinien-Schriften für Textobjekte (LightBurns *single-line fonts* / xTools
Einlinien-Schrift): jeder Buchstabe ist ein Strich statt eines Umrisses.

Ein Diodenlaser fährt einen Einlinien-Text einmal als Linie ab – schnell, dünn und
gleichmäßig (Beschriftungen, Skalen, kleine Seriennummern, Unterschriften, Stifte im
Plotter-Halter), wo ein Umriss-Text doppelt umfahren oder flächig gefüllt werden muss.

Qt-frei. Die Glyphen kommen aus den Hershey-Schriften (:mod:`linefont_data`);
Umlaute und Akzente werden aus Grundbuchstabe und Zeichen zusammengesetzt, „ß“, „€“
und „°“ sind eigene Striche. Unbekannte Zeichen erscheinen als „?“.

Eigene Einlinien-Schriften (wie LightBurns eigene Single-Line-Fonts): SVG-Fonts (Inkscapes
„Hershey Text“ / EMS-Schriften, Relief SingleLine …) und Hershey-``.jhf``-Dateien werden
in Hershey-Einheiten umgerechnet (ein Geviert = :data:`EM_UNITS`), in den Schriftordner
(:func:`user_font_dir`) kopiert und heißen ``USER_FONT_PREFIX + Name``. Fehlt eine solche
Schrift (Projekt von einem anderen Rechner), zeichnet die eingebaute Sans als Ersatz.

Koordinaten der Hershey-Daten: y nach unten (wie Qt), Grundlinie bei ``BASE_LINE``,
Versalhöhe ``-12`` … ``9`` = 21 Einheiten. Ein Geviert (Schriftgröße) sind
:data:`EM_UNITS` Hershey-Einheiten.
"""

from __future__ import annotations

import math
import os
import re
import shutil
import sys
import unicodedata
import xml.etree.ElementTree as ET
from functools import lru_cache
from pathlib import Path

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


# Eigene Einlinien-Schriften (LightBurn lädt SHX- / eigene Einlinien-Schriften): SVG-Fonts
# (Inkscape „Hershey Text“ / EMS-Schriften, Relief SingleLine …) und Hershey-``.jhf``-Dateien.
# ``Shape.font_family`` = Präfix + Name; ohne geladene Datei (Projekt von einem anderen
# Rechner) zeichnet die eingebaute Sans als Ersatz.
USER_FONT_PREFIX = "LumaCut Einlinie: "
USER_FONT_SUFFIXES = (".svg", ".jhf")
_USER_FONTS: dict[str, dict[str, "Glyph"]] = {}
_USER_FILES: dict[str, Path] = {}
_USER_CAPS: dict[str, float] = {}
_USER_STATE = {"scanned": False}
USER_FONT_ERRORS: dict[str, str] = {}        # Dateiname -> Grund (beim Einlesen übersprungen)


def is_line_font(family: str | None) -> bool:
    """``family`` ist eine eingebaute oder eigene Einlinien-Schrift."""
    return isinstance(family, str) and (family in LINE_FONTS or (
        family.startswith(USER_FONT_PREFIX) and len(family) > len(USER_FONT_PREFIX)))


def is_user_font(family: str | None) -> bool:
    """``family`` ist eine eigene (geladene oder fehlende) Einlinien-Schrift."""
    return is_line_font(family) and family not in LINE_FONTS


def font_label(family: str) -> str:
    """Anzeigename: „Einlinie (Sans)“ … bzw. „Einlinie: Name“ (+ „(fehlt)“)."""
    if family in LINE_FONT_LABELS:
        return LINE_FONT_LABELS[family]
    name = family[len(USER_FONT_PREFIX):] if is_user_font(family) else family
    return f"Einlinie: {name}" + ("" if font_available(family) else " (fehlt)")


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


def _font(family: str) -> dict[str, Glyph]:
    """Glyphen der Schrift; eine eigene Schrift, die nicht geladen ist, zeichnet die Sans."""
    if family in LINE_FONTS:
        return _builtin_font(family)
    if is_user_font(family):
        ensure_user_fonts()
        glyphs = _USER_FONTS.get(family)
        if glyphs is not None:
            return glyphs
    return _builtin_font(LINE_FONT_SANS)


@lru_cache(maxsize=None)
def _builtin_font(family: str) -> dict[str, Glyph]:
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
        g = (glyphs.get(" " if ch == "\t" else ch) or _composed(glyphs, ch) or glyphs.get(FALLBACK_CHAR)
             or _builtin_font(LINE_FONT_SANS)[FALLBACK_CHAR])
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


def word_starts(line: str) -> list[int]:
    """Indizes der Wörter einer Zeile nach dem ersten – dort dehnt der Blocksatz die Lücken.

    Eine Lücke ist ein Lauf von Leerzeichen zwischen zwei Wörtern; Leerzeichen am Anfang
    (Einzug) und am Ende der Zeile sind keine Lücke.
    """
    return [k for k in range(1, len(line)) if line[k] != " " and line[k - 1] == " "
            and line[:k].strip(" ")]


def justified(lines: list[str], i: int) -> bool:
    """Zeile ``i`` wird im Blocksatz gedehnt: nicht die letzte Zeile und mit mindestens einer
    Wortlücke (wie der Blocksatz einer Textverarbeitung – letzte Zeile und einzelne Wörter
    bleiben linksbündig)."""
    return i < len(lines) - 1 and bool(word_starts(lines[i]))


def justify_shifts(line: str, extra: float) -> list[float]:
    """Verschiebung je Zeichen von ``line``, um ``extra`` gleichmäßig auf die Wortlücken zu
    verteilen (Zeichen vor der ersten Lücke 0, Zeichen des letzten Worts ``extra``)."""
    starts = word_starts(line)
    if not starts or extra <= 0:
        return [0.0] * len(line)
    step = extra / len(starts)
    out, k = [], 0
    for j in range(len(line)):
        while k < len(starts) and starts[k] <= j:
            k += 1
        out.append(k * step)
    return out


def text_strokes(text: str, family: str, italic: bool = False, *, letter_spacing: float = 0.0,
                 line_spacing: float = 100.0, align: str = "left",
                 pitch_units: float = 1.25 * EM_UNITS * 0.75) -> list[Stroke]:
    """Striche eines (mehrzeiligen) Textes in Hershey-Einheiten.

    Text-Satz wie :func:`shape_paths.text_path`: ``letter_spacing`` in % des Gevierts
    nach jedem Zeichen, ``line_spacing`` in % von ``pitch_units`` (Zeilenabstand),
    ``align`` richtet die Zeilen nach ihrer Laufweite aus („justify“ = Blocksatz an den
    Wortlücken, :func:`justify_shifts`). ``italic`` stellt schräg.
    Zeile i hat ihre Grundlinie bei ``BASE_LINE + i · pitch``.
    """
    extra = letter_spacing / 100.0 * EM_UNITS
    pitch = pitch_units * (line_spacing / 100.0 if line_spacing != 100.0 else 1.0)
    lines = (text or "").split("\n")
    adv = [line_advance(line, family, extra) for line in lines]
    widest = max(adv) if adv else 0.0
    share = {"center": 0.5, "right": 1.0}.get(align, 0.0) if len(lines) > 1 else 0.0
    if align == "justify" and len(lines) > 1:      # Blocksatz: bis zum Ende der breitesten Zeile
        ink = [line_advance(line.rstrip(" "), family, extra) for line in lines]
        widest = max(ink)
    out: list[Stroke] = []
    for i, line in enumerate(lines):
        x = (widest - adv[i]) * share
        dy = i * pitch
        shifts = (justify_shifts(line, widest - ink[i])
                  if align == "justify" and justified(lines, i) else None)
        for j, ch in enumerate(line):
            g = glyph(family, ch)
            gx0 = x + shifts[j] if shifts else x
            for s in g.strokes:
                pts = []
                for gx, gy in s:
                    px = gx0 + gx - g.left
                    if italic:
                        px += ITALIC_SLANT * (BASE_LINE - gy)
                    pts.append((px, gy + dy))
                out.append(pts)
            x += g.advance + extra
    return out


# --- Eigene Einlinien-Schriften -----------------------------------------------------------------

CURVE_STEP_UNITS = 0.5          # Kurven eines SVG-Fonts: Sehnenlänge höchstens ≈ 0,5 Hershey-Einheiten
MAX_FONT_BYTES = 8 * 1024 * 1024
_CAP_PROBES = "HIEFTLKN"


class FontFileError(ValueError):
    """Die Datei ist keine lesbare Einlinien-Schrift (deutsche Meldung)."""


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def _num(value, default: float) -> float:
    try:
        v = float(str(value).strip())
    except (TypeError, ValueError):
        return default
    return v if math.isfinite(v) else default


def _svg_strokes(d: str, k: float) -> list[Stroke]:
    """SVG-Pfaddaten einer Glyphe (y nach oben) -> Striche in Hershey-Einheiten (y nach
    unten, Grundlinie ``BASE_LINE``). Kurven werden in kurze Sehnen zerlegt,
    ``Z`` schließt den Strich auf seinem Anfangspunkt (wie das „o“ der Hershey-Daten)."""
    import svgelements as se

    def pt(q) -> Point:
        return (round(q.x * k, 6), round(BASE_LINE - q.y * k, 6))

    try:
        path = se.Path(d)
    except Exception as exc:  # noqa: BLE001 - kaputte Pfaddaten
        raise FontFileError(f"Pfaddaten nicht lesbar ({exc})") from exc
    strokes: list[Stroke] = []
    cur: Stroke = []

    def flush() -> None:
        pts = [p for i, p in enumerate(cur) if i == 0 or p != cur[i - 1]]
        if len(pts) >= 2:
            strokes.append(pts)

    for seg in path:
        if isinstance(seg, se.Move):
            flush()
            cur = [pt(seg.end)]
        elif isinstance(seg, se.Close):
            if cur:
                cur.append(cur[0])
            flush()
            cur = [cur[0]] if cur else []
        elif isinstance(seg, se.Line):
            if not cur:
                cur = [pt(seg.start)]
            cur.append(pt(seg.end))
        elif seg.start is not None and seg.end is not None:
            if not cur:
                cur = [pt(seg.start)]
            try:
                length = seg.length(error=1e-3) * k
            except Exception:  # noqa: BLE001 - entartete Kurve
                length = math.dist(pt(seg.start), pt(seg.end))
            n = max(2, min(200, math.ceil(length / CURVE_STEP_UNITS)))
            cur.extend(pt(seg.point(i / n)) for i in range(1, n + 1))
    flush()
    return strokes


def parse_svg_font(data: bytes | str) -> tuple[str, dict[str, Glyph], float]:
    """SVG-Font (``<font>`` / ``<font-face>`` / ``<glyph unicode d horiz-adv-x>``) ->
    (Name, Glyphen in Hershey-Einheiten, Versalhöhe in Hershey-Einheiten).

    Ein Geviert (``units-per-em``) wird :data:`EM_UNITS` Hershey-Einheiten, die Grundlinie
    ``BASE_LINE`` – gleiche Bedeutung von Schriftgröße, Zeilen- und Zeichenabstand wie bei
    den eingebauten Schriften. Glyphen für mehrere Zeichen (Ligaturen) werden übersprungen.
    """
    if isinstance(data, str):
        data = data.encode("utf-8")
    if b"<!ENTITY" in data:
        raise FontFileError("SVG mit Entity-Definitionen wird nicht gelesen")
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise FontFileError(f"kein gültiges SVG ({exc})") from exc
    font = next((el for el in root.iter() if _local(el.tag) == "font"), None)
    if font is None:
        raise FontFileError("kein SVG-Font (Element <font> fehlt) – eine normale SVG-Grafik "
                            "bitte über „Importieren“ öffnen")
    face = next((el for el in font.iter() if _local(el.tag) == "font-face"), None)
    face_attr = face.attrib if face is not None else {}
    upm = _num(face_attr.get("units-per-em"), 1000.0)
    if upm <= 0:
        upm = 1000.0
    k = EM_UNITS / upm
    default_adv = _num(font.get("horiz-adv-x"), upm / 3.0)
    name = (face_attr.get("font-family") or font.get("id") or "").strip().strip("'\"")
    glyphs: dict[str, Glyph] = {}
    missing: Glyph | None = None
    for el in font.iter():
        tag = _local(el.tag)
        if tag not in ("glyph", "missing-glyph"):
            continue
        adv = max(0.0, _num(el.get("horiz-adv-x"), default_adv)) * k
        d = el.get("d") or ""
        g = Glyph(0.0, adv, _svg_strokes(d, k) if d.strip() else [])
        if tag == "missing-glyph":
            missing = g
            continue
        uni = el.get("unicode")
        if uni is None or len(uni) != 1 or uni in glyphs:
            continue
        glyphs[uni] = g
    if not any(g.strokes for g in glyphs.values()):
        raise FontFileError("der SVG-Font enthält keine Glyphen mit Strichen")
    _complete(glyphs, default_adv * k, missing)
    cap = next((BASE_LINE - min(y for st in glyphs[c].strokes for _x, y in st)
                for c in _CAP_PROBES if c in glyphs and glyphs[c].strokes), 0.0)
    if cap <= 0:
        cap = _num(face_attr.get("cap-height"), 0.0) * k or 0.7 * EM_UNITS
    return name, glyphs, cap


def _jhf_records(text: str) -> list[str]:
    """Einträge einer ``.jhf``-Datei; lange Glyphen sind dort über mehrere Zeilen
    umbrochen (Länge = 8 + 2 · Punktzahl)."""
    records: list[str] = []
    buf = ""
    for raw in text.splitlines():
        line = raw.rstrip("\r")
        if not buf:
            if not line.strip() or line.startswith("#"):
                continue
            buf = line
        else:
            buf += line
        head = buf[5:8].strip()
        if not head.isdigit():
            raise FontFileError(f"Hershey-Zeile nicht lesbar: „{buf[:16]}“")
        need = 8 + 2 * int(head)
        if len(buf.rstrip()) >= need - 1:
            records.append(buf[:need].ljust(need))
            buf = ""
    if buf:
        raise FontFileError("Hershey-Datei endet mitten in einer Glyphe")
    return records


def parse_jhf_font(text: str) -> tuple[dict[str, Glyph], float]:
    """Hershey-``.jhf``-Datei (Glyphen der Reihe nach ab dem Leerzeichen, wie die
    eingebauten Schriften) -> (Glyphen, Versalhöhe in Hershey-Einheiten)."""
    try:
        records = _jhf_records(text)
        glyphs = {chr(32 + i): parse_jhf_line(r) for i, r in enumerate(records[:95])}
    except FontFileError:
        raise
    except (ValueError, IndexError) as exc:
        raise FontFileError(f"keine Hershey-Schrift ({exc})") from exc
    if not any(g.strokes for g in glyphs.values()):
        raise FontFileError("die Hershey-Datei enthält keine Glyphen mit Strichen")
    _complete(glyphs, EM_UNITS / 3.0, None)
    cap = next((BASE_LINE - min(y for st in glyphs[c].strokes for _x, y in st)
                for c in _CAP_PROBES if c in glyphs and glyphs[c].strokes), 0.0)
    return glyphs, cap if cap > 0 else BASE_LINE + 12.0


def _complete(glyphs: dict[str, Glyph], space_adv: float, missing: Glyph | None) -> None:
    """Leerzeichen, „?“-Ersatz und typografische Zeichen (– „ “ …) ergänzen, wenn die
    Schrift sie nicht selbst hat."""
    if " " not in glyphs:
        glyphs[" "] = Glyph(0.0, space_adv, [])
    if FALLBACK_CHAR not in glyphs and missing is not None and missing.strokes:
        glyphs[FALLBACK_CHAR] = missing
    for alias, target in _ALIASES.items():
        if alias not in glyphs and target in glyphs:
            glyphs[alias] = glyphs[target]


def _family_name(name: str, fallback: str) -> str:
    name = re.sub(r"\s+", " ", (name or "").strip()) or fallback
    return USER_FONT_PREFIX + name[:60]


def read_font_file(path) -> tuple[str, dict[str, Glyph], float]:
    """Datei lesen -> (Schriftname ``USER_FONT_PREFIX + …``, Glyphen, Versalhöhe)."""
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix not in USER_FONT_SUFFIXES:
        raise FontFileError("nur SVG-Fonts (.svg) und Hershey-Schriften (.jhf)")
    try:
        if path.stat().st_size > MAX_FONT_BYTES:
            raise FontFileError("Datei zu groß für eine Einlinien-Schrift")
        data = path.read_bytes()
    except OSError as exc:
        raise FontFileError(f"Datei nicht lesbar ({exc.strerror or exc})") from exc
    if suffix == ".svg":
        name, glyphs, cap = parse_svg_font(data)
    else:
        glyphs, cap = parse_jhf_font(data.decode("latin-1"))
        name = ""
    return _family_name(name, path.stem), glyphs, cap


def register_font(family: str, glyphs: dict[str, Glyph], cap_units: float = BASE_LINE + 12.0,
                  source: Path | None = None) -> str:
    """Eigene Schrift unter ``family`` bekannt machen (ersetzt eine gleichnamige)."""
    if not is_user_font(family):
        raise ValueError(f"kein Name einer eigenen Einlinien-Schrift: {family!r}")
    _USER_FONTS[family] = glyphs
    _USER_CAPS[family] = float(cap_units)
    if source is not None:
        _USER_FILES[family] = Path(source)
    for key in [k for k in _CACHE if k[0] == family]:
        del _CACHE[key]
    return family


def user_font_dir() -> Path:
    """Ordner der eigenen Einlinien-Schriften: ``LUMACUT_FONT_DIR`` (Tests / portabel), sonst
    ``%APPDATA%\\LumaCut\\fonts`` (Windows) bzw. ``~/.local/share/LumaCut/fonts``."""
    env = os.environ.get("LUMACUT_FONT_DIR")
    if env:
        return Path(env)
    if sys.platform.startswith("win") and os.environ.get("APPDATA"):
        return Path(os.environ["APPDATA"]) / "LumaCut" / "fonts"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "LumaCut" / "fonts"
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / "LumaCut" / "fonts"


def ensure_user_fonts() -> None:
    """Eigene Schriften aus :func:`user_font_dir` einmal einlesen (kaputte Dateien werden
    übersprungen und in :data:`USER_FONT_ERRORS` vermerkt)."""
    if _USER_STATE["scanned"]:
        return
    _USER_STATE["scanned"] = True
    folder = user_font_dir()
    try:
        files = sorted(p for p in folder.iterdir() if p.suffix.lower() in USER_FONT_SUFFIXES)
    except OSError:
        return
    for p in files:
        try:
            family, glyphs, cap = read_font_file(p)
        except FontFileError as exc:
            USER_FONT_ERRORS[p.name] = str(exc)
            continue
        if family not in _USER_FONTS:
            register_font(family, glyphs, cap, p)


def install_font_file(path) -> str:
    """Schriftdatei prüfen, in :func:`user_font_dir` kopieren und laden; gibt den Namen
    (``Shape.font_family``) zurück. :class:`FontFileError` mit deutscher Meldung."""
    ensure_user_fonts()
    src = Path(path)
    family, glyphs, cap = read_font_file(src)
    folder = user_font_dir()
    stem = re.sub(r"[^\w.-]+", "_", family[len(USER_FONT_PREFIX):]).strip("._") or "schrift"
    dest = folder / (stem + src.suffix.lower())
    try:
        folder.mkdir(parents=True, exist_ok=True)
        old = _USER_FILES.get(family)
        if old is not None and old != dest and old.exists() and old.parent == folder:
            old.unlink()
        if src.resolve() != dest.resolve():
            shutil.copyfile(src, dest)
    except OSError as exc:
        raise FontFileError(f"Schrift nicht gespeichert ({exc.strerror or exc})") from exc
    return register_font(family, glyphs, cap, dest)


def user_fonts() -> list[str]:
    """Geladene eigene Einlinien-Schriften (Namen), alphabetisch."""
    ensure_user_fonts()
    return sorted(_USER_FONTS, key=str.casefold)


def line_fonts() -> list[str]:
    """Alle Einlinien-Schriften für Auswahllisten: eingebaute, dann eigene."""
    return list(LINE_FONTS) + user_fonts()


def glyph_chars(family: str) -> list[str]:
    """Zeichen mit eigener Glyphe in der Schrift (ohne zusammengesetzte Umlaute)."""
    return sorted(_font(family))


def font_available(family: str) -> bool:
    """Eingebaute oder geladene eigene Schrift (False: Ersatz durch die Sans)."""
    if family in LINE_FONTS:
        return True
    if not is_user_font(family):
        return False
    ensure_user_fonts()
    return family in _USER_FONTS


def cap_units(family: str) -> float:
    """Versalhöhe der Schrift in Hershey-Einheiten (eingebaute: 21)."""
    if is_user_font(family) and font_available(family):
        return _USER_CAPS.get(family, BASE_LINE + 12.0)
    return BASE_LINE + 12.0


def clear_user_fonts() -> None:
    """Eigene Schriften vergessen (Tests); der Ordner wird beim nächsten Zugriff neu gelesen."""
    for family in list(_USER_FONTS):
        for key in [k for k in _CACHE if k[0] == family]:
            del _CACHE[key]
    _USER_FONTS.clear()
    _USER_FILES.clear()
    _USER_CAPS.clear()
    USER_FONT_ERRORS.clear()
    _USER_STATE["scanned"] = False
    for key in [k for k in _CACHE if is_user_font(k[0])]:
        del _CACHE[key]


def missing_user_fonts(families) -> list[str]:
    """Eigene Schriften aus ``families``, die auf diesem Rechner fehlen (Ersatz: Sans)."""
    return sorted({f for f in families if is_user_font(f) and not font_available(f)})


def missing_fonts_note(families) -> str:
    """Hinweis für fehlende eigene Schriften (leer, wenn alle da sind)."""
    missing = missing_user_fonts(families)
    if not missing:
        return ""
    names = ", ".join(f"„{f[len(USER_FONT_PREFIX):]}“" for f in missing)
    return (f"Einlinien-Schrift {names} fehlt auf diesem Rechner – Ersatz: Einlinie (Sans); "
            "Schriftdatei über „Schrift laden …“ in der Textleiste laden")


__all__ = ["EM_UNITS", "LINE_FONTS", "LINE_FONT_LABELS", "LINE_FONT_SANS", "LINE_FONT_SCRIPT",
           "USER_FONT_PREFIX", "FontFileError", "Glyph", "cap_units", "clear_user_fonts", "ensure_user_fonts",
           "font_available", "font_label", "glyph", "glyph_chars", "has_glyph", "install_font_file", "is_line_font",
           "is_user_font", "line_advance", "line_fonts", "missing_chars", "missing_fonts_note", "missing_user_fonts",
           "parse_jhf_font", "parse_jhf_line", "parse_svg_font", "read_font_file", "register_font",
           "text_strokes", "user_font_dir", "user_fonts"]
