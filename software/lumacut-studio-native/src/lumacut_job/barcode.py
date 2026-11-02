"""1D barcodes (Code 128, GS1-128, EAN-13, EAN-8, UPC-A) as vector objects for engraving.

Pure Python, Qt-free, no third-party encoder. Matches the "Barcode" tool of
LightBurn and xTool Creative Space:

* **Code 128** – ASCII. Code sets A, B and C are chosen per character by a
  shortest-encoding search (digit pairs in C, control characters in A,
  everything else in B, switching with CODE A / B / C), modulo-103 check
  symbol. Control characters (Tab, CR, LF, GS …) are typed as escape
  sequences when ``escapes`` is on (:func:`unescape`).
* **GS1-128** – Code 128 with a leading FNC1 and the GS1 element string
  typed as "(01)09501101530003(17)261231(10)AB-12" (:mod:`lumacut_job.gs1`):
  fixed-length fields and check digits are verified, variable-length fields
  are terminated with FNC1, the human-readable line shows the AIs in
  parentheses.
* **EAN-13 / EAN-8 / UPC-A** – digits only. Without the check digit
  (12 / 7 / 11 digits) it is appended; with it (13 / 8 / 12) it is verified.

Geometry: each bar (run of dark modules) becomes one filled rectangle
``polygon``; all bars and the optional human-readable text are grouped.
``x``/``y`` is the top-left corner *including* the quiet zone, which is
only kept free (it is not engraved). Units are mm, Y points down.

Inverted mode (``invert``, for materials that turn *light* when lasered:
anodised aluminium, slate, coated metal) engraves the background instead:
quiet zone, spaces and a border of ``INVERT_MARGIN_*`` above and below,
with the bars and digits left as holes. The quiet zone is then always on
and the bar width correction widens the bars (narrows the spaces).

The human-readable line needs glyph outlines, which come from Qt
(:func:`lumacut_job.arctext_qt.glyphs_for`); callers pass them in as
``glyph_fn(text, cap_height_mm) -> list[arctext.Glyph]``. Without it the
text is left out.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Callable

from lumacut_canvas.model import Shape, new_id
from lumacut_canvas.workarea import WORK_HEIGHT_MM, WORK_WIDTH_MM

from . import gs1
from .arctext import Glyph
from .gs1 import FNC1

SYMBOLOGIES = ("code128", "gs1_128", "ean13", "ean8", "upca")
LABELS = {"code128": "Code 128", "gs1_128": "GS1-128", "ean13": "EAN-13", "ean8": "EAN-8",
          "upca": "UPC-A"}
# Narrow bar (module) width. Below WARN_MODULE_MM a diode spot (~0.08–0.1 mm)
# visibly widens the bars and scanners start to fail; below HARD_MIN it is refused.
MODULE_RANGE = (0.1, 5.0)
HARD_MIN_MODULE_MM = MODULE_RANGE[0]
WARN_MODULE_MM = 0.15
HEIGHT_RANGE = (2.0, 300.0)          # bar height, mm
TEXT_RANGE = (0.5, 30.0)             # digit (cap) height, mm
SHRINK_RANGE = (0.0, 0.3)            # bar width reduction, mm (spot compensation)
INVERT_MARGIN_MM = 1.0               # inverted: engraved border above/below, at least …
INVERT_MARGIN_MODULES = 5            # … or this many modules
MAX_CODE128_CHARS = 80
MAX_GS1_128_CHARS = 48               # GS1 General Specifications 5.4.1: 48 data characters

# Minimum quiet zones in modules (left, right): ISO/IEC 15417 / 15420.
QUIET_MODULES = {"code128": (10, 10), "gs1_128": (10, 10), "ean13": (11, 7), "ean8": (7, 7), "upca": (9, 9)}

# --- Code 128 -----------------------------------------------------------------
# Bar/space widths of the symbol values 0–105 (bar first), ISO/IEC 15417 Table 1.
_C128 = (
    "212222", "222122", "222221", "121223", "121322", "131222", "122213", "122312", "132212",
    "221213", "221312", "231212", "112232", "122132", "122231", "113222", "123122", "123221",
    "223211", "221132", "221231", "213212", "223112", "312131", "311222", "321122", "321221",
    "312212", "322112", "322211", "212123", "212321", "232121", "111323", "131123", "131321",
    "112313", "132113", "132311", "211313", "231113", "231311", "112133", "112331", "132131",
    "113123", "113321", "133121", "313121", "211331", "231131", "213113", "213311", "213131",
    "311123", "311321", "331121", "312113", "312311", "332111", "314111", "221411", "431111",
    "111224", "111422", "121124", "121421", "141122", "141221", "112214", "112412", "122114",
    "122411", "142112", "142211", "241211", "221114", "413111", "241112", "134111", "111242",
    "121142", "121241", "114212", "124112", "124211", "411212", "421112", "421211", "212141",
    "214121", "412121", "111143", "111341", "131141", "114113", "114311", "411113", "411311",
    "113141", "114131", "311141", "411131", "211412", "211214", "211232",
)
_C128_STOP = "2331112"
CODE_C, CODE_B, CODE_A, FNC1_VALUE, START_A, START_B, START_C, STOP = \
    99, 100, 101, 102, 103, 104, 105, 106
START = (START_A, START_B, START_C)           # by set: 0 = A, 1 = B, 2 = C
SWITCH = (CODE_A, CODE_B, CODE_C)
# Escape sequences for control characters in Code 128 (``escapes`` on).
ESCAPES = {"\\": 92, "t": 9, "n": 10, "r": 13, "e": 27, "g": 29, "0": 0}

# --- EAN / UPC -----------------------------------------------------------------
_EAN_L = ("0001101", "0011001", "0010011", "0111101", "0100011",
          "0110001", "0101111", "0111011", "0110111", "0001011")
_EAN_R = tuple("".join("1" if b == "0" else "0" for b in p) for p in _EAN_L)
_EAN_G = tuple(p[::-1] for p in _EAN_R)
# Parity of digits 2–7 selected by the first EAN-13 digit.
_EAN_PARITY = ("LLLLLL", "LLGLGG", "LLGGLG", "LLGGGL", "LGLLGG",
               "LGGLLG", "LGGGLL", "LGLGLG", "LGLGGL", "LGGLGL")
_GUARD, _CENTER = "101", "01010"
_EAN_LEN = {"ean13": 13, "ean8": 8, "upca": 12}


def _widths_to_modules(widths: str, dark_first: bool = True) -> str:
    out, dark = [], dark_first
    for w in widths:
        out.append(("1" if dark else "0") * int(w))
        dark = not dark
    return "".join(out)


def unescape(text: str) -> str:
    """Control characters from escape sequences: ``\\t`` Tab, ``\\n`` LF, ``\\r`` CR,
    ``\\e`` ESC, ``\\g`` GS (group separator), ``\\0`` NUL, ``\\xHH`` any ASCII code,
    ``\\\\`` backslash. ``ValueError`` (German) on an unknown or incomplete sequence."""
    out, i, n = [], 0, len(text)
    while i < n:
        ch = text[i]
        if ch != "\\":
            out.append(ch)
            i += 1
            continue
        nxt = text[i + 1:i + 2].lower()
        if nxt == "x":
            hx = text[i + 2:i + 4]
            if len(hx) != 2 or any(c not in "0123456789abcdefABCDEF" for c in hx) or int(hx, 16) > 127:
                raise ValueError(f"Escape „\\x{hx}“ ungültig – \\x00 bis \\x7F erwartet")
            out.append(chr(int(hx, 16)))
            i += 4
        elif nxt in ESCAPES:
            out.append(chr(ESCAPES[nxt]))
            i += 2
        else:
            raise ValueError(f"Unbekanntes Escape „\\{text[i + 1:i + 2]}“ – erlaubt: \\t \\n \\r "
                             "\\e \\g \\0 \\xHH \\\\")
    return "".join(out)


def readable(text: str) -> str:
    """Human-readable line: control characters left out."""
    return "".join(c for c in text if 32 <= ord(c) < 127)


def code128_values(text: str) -> list[int]:
    """Symbol values incl. start, check symbol and stop for ``text`` (ASCII 0–127)."""
    text = str(text)
    if not text:
        raise ValueError("Kein Text für den Barcode")
    if len(text) > MAX_CODE128_CHARS:
        raise ValueError(f"Text zu lang für Code 128 (höchstens {MAX_CODE128_CHARS} Zeichen)")
    bad = sorted({c for c in text if ord(c) > 127})
    if bad:
        shown = ", ".join(repr(c) for c in bad[:5])
        raise ValueError(f"Code 128 erlaubt nur ASCII-Zeichen ohne Umlaute – nicht erlaubt: {shown}")
    return code128_sequence_values([ord(c) for c in text])


def _c128_digit(c) -> bool:
    return 48 <= c <= 57


def _c128_unit(seq, i: int, s: int):
    """(symbol value(s), length) for the unit at ``seq[i]`` in set ``s`` (0 A, 1 B, 2 C) or None."""
    c = seq[i]
    if c == FNC1:
        return FNC1_VALUE, 1
    if s == 2:
        if i + 1 < len(seq) and _c128_digit(c) and seq[i + 1] != FNC1 and _c128_digit(seq[i + 1]):
            return (c - 48) * 10 + seq[i + 1] - 48, 2
        return None
    if s == 0:
        return (c + 64, 1) if c < 32 else ((c - 32, 1) if c < 96 else None)
    return (c - 32, 1) if 32 <= c <= 127 else None


def code128_sequence_values(seq: list[int]) -> list[int]:
    """Symbol values incl. start, check symbol and stop for a sequence of codes.

    ``seq`` holds character codes 0–127 and :data:`gs1.FNC1`. Shortest encoding
    over code sets A, B and C (dynamic programming over the position and the
    current set); on equal length the encoder stays in its set, a new set is
    tried in the order B, C, A and the symbol starts in B unless C or A is
    shorter – so printable text without control characters is encoded
    exactly as with sets B and C only.
    """
    n = len(seq)
    inf = float("inf")
    cost = [[inf] * 3 for _ in range(n + 1)]
    step: list[list[tuple | None]] = [[None] * 3 for _ in range(n + 1)]
    cost[n] = [0, 0, 0]
    for i in range(n - 1, -1, -1):
        for s in range(3):
            best, choice = inf, None
            for t in (s,) + tuple(x for x in (1, 2, 0) if x != s):
                u = _c128_unit(seq, i, t)
                if u is None:
                    continue
                c = (0 if t == s else 1) + 1 + cost[i + u[1]][t]
                if c < best:
                    best, choice = c, (t, u[0], u[1])
            cost[i][s], step[i][s] = best, choice
    s = 1
    for t in (2, 0):
        if cost[0][t] < cost[0][s]:
            s = t
    if cost[0][s] == inf:
        raise ValueError("Text lässt sich nicht als Code 128 codieren")
    values = [START[s]]
    i = 0
    while i < n:
        t, value, length = step[i][s]
        if t != s:
            values.append(SWITCH[t])
        values.append(value)
        i, s = i + length, t
    values.append(code128_checksum(values))
    values.append(STOP)
    return values


def code128_checksum(values: list[int]) -> int:
    """Modulo-103 check symbol over start symbol and data values."""
    return (values[0] + sum(k * v for k, v in enumerate(values[1:], start=1))) % 103


def code128_modules(values: list[int]) -> str:
    return "".join(_widths_to_modules(_C128_STOP if v == STOP else _C128[v]) for v in values)


def ean_check_digit(digits: str) -> int:
    """GS1 mod-10 check digit for the digits *without* the check digit."""
    total = sum(int(d) * (3 if k % 2 == 0 else 1) for k, d in enumerate(reversed(digits)))
    return (10 - total % 10) % 10


def complete_digits(symbology: str, data: str) -> str:
    """Digits incl. check digit: appended when missing, verified when given."""
    n = _EAN_LEN[symbology]
    d = "".join(str(data).split())
    label = LABELS[symbology]
    if not d:
        raise ValueError(f"Keine Ziffern für {label}")
    if not (d.isascii() and d.isdigit()):
        raise ValueError(f"{label} erlaubt nur Ziffern 0–9")
    if len(d) == n - 1:
        return d + str(ean_check_digit(d))
    if len(d) != n:
        raise ValueError(f"{label} braucht {n - 1} Ziffern (Prüfziffer wird ergänzt) oder {n}")
    want = ean_check_digit(d[:-1])
    if int(d[-1]) != want:
        raise ValueError(f"Prüfziffer von {label} falsch: {d[-1]}, richtig wäre {want}")
    return d


def ean_modules(symbology: str, digits: str) -> str:
    if symbology == "upca":
        symbology, digits = "ean13", "0" + digits
    if symbology == "ean8":
        left = "".join(_EAN_L[int(c)] for c in digits[:4])
        right = "".join(_EAN_R[int(c)] for c in digits[4:])
    else:
        par = _EAN_PARITY[int(digits[0])]
        left = "".join((_EAN_L if p == "L" else _EAN_G)[int(c)] for p, c in zip(par, digits[1:7]))
        right = "".join(_EAN_R[int(c)] for c in digits[7:])
    return _GUARD + left + _CENTER + right + _GUARD


@dataclass(frozen=True)
class TextSegment:
    """Human-readable text under modules ``start``..``end`` (may lie in the quiet zone).

    ``spread``: one character per equal slot (EAN digit groups), else centred.
    """

    text: str
    start: float
    end: float
    spread: bool = False


@dataclass(frozen=True)
class Barcode:
    symbology: str
    text: str                                 # encoded content (EAN incl. check digit)
    modules: str                              # "1" = dark module
    values: tuple[int, ...] = ()              # Code 128 symbol values
    segments: tuple[TextSegment, ...] = ()
    guards: tuple[tuple[int, int], ...] = ()  # module ranges drawn longer (EAN/UPC)

    @property
    def quiet(self) -> tuple[int, int]:
        return QUIET_MODULES[self.symbology]

    def bars(self) -> list[tuple[int, int]]:
        """Dark runs as (first module, width in modules)."""
        out, start = [], None
        for k, m in enumerate(self.modules + "0"):
            if m == "1" and start is None:
                start = k
            elif m != "1" and start is not None:
                out.append((start, k - start))
                start = None
        return out


def encode(symbology: str, data: str, escapes: bool = False) -> Barcode:
    """Encode ``data``; ``escapes``: Code 128 escape sequences for control characters."""
    sym = str(symbology).lower()
    if sym not in SYMBOLOGIES:
        raise ValueError(f"Unbekannter Barcode-Typ „{symbology}“")
    if sym == "code128":
        text = unescape(str(data)) if escapes else str(data)
        values = code128_values(text)
        mods = code128_modules(values)
        shown = readable(text)
        return Barcode(sym, text, mods, tuple(values),
                       (TextSegment(shown, 0, len(mods)),) if shown else ())
    if sym == "gs1_128":
        elements = gs1.parse(data)
        seq = gs1.sequence(elements)
        if len(seq) - 1 > MAX_GS1_128_CHARS:
            raise ValueError(f"Zu viele Zeichen für GS1-128 ({len(seq) - 1}, höchstens "
                             f"{MAX_GS1_128_CHARS} inkl. Datenbezeichnern und Trennzeichen)")
        values = code128_sequence_values(seq)
        mods = code128_modules(values)
        text = gs1.hri(elements)
        return Barcode(sym, text, mods, tuple(values), (TextSegment(text, 0, len(mods)),))
    d = complete_digits(sym, data)
    mods = ean_modules(sym, d)
    if sym == "ean13":
        seg = (TextSegment(d[0], -7, -1), TextSegment(d[1:7], 3, 45, True),
               TextSegment(d[7:], 50, 92, True))
        guards = ((0, 3), (45, 50), (92, 95))
    elif sym == "ean8":
        seg = (TextSegment(d[:4], 3, 31, True), TextSegment(d[4:], 36, 64, True))
        guards = ((0, 3), (31, 36), (64, 67))
    else:  # upca: first and last digit sit outside, their bars are long like the guards
        seg = (TextSegment(d[0], -7, -1), TextSegment(d[1:6], 10, 45, True),
               TextSegment(d[6:11], 50, 85, True), TextSegment(d[11], 96, 102))
        guards = ((0, 10), (45, 50), (85, 95))
    return Barcode(sym, d, mods, (), seg, guards)


# --- Canvas objects -------------------------------------------------------------
def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


@dataclass(frozen=True)
class BarcodeSpec:
    symbology: str = "code128"
    data: str = "LumaCut"
    module_mm: float = 0.33           # narrow bar width
    height_mm: float = 15.0           # bar height
    quiet_zone: bool = True           # keep the standard quiet zone free (part of the size)
    show_text: bool = True            # human-readable line below the bars
    text_mm: float = 2.5              # digit height
    shrink_mm: float = 0.0            # bar width reduction against the burn spread
    font_family: str = "Segoe UI"     # human-readable line (outlines via Qt)
    invert: bool = False              # laser the background (spaces, quiet zone, margin), not the bars
    escapes: bool = False             # Code 128: \\t, \\r, \\n, \\g, \\xHH … are control characters
    x: float = 0.0                    # top-left incl. quiet zone
    y: float = 0.0

    def normalized(self) -> "BarcodeSpec":
        sym = str(self.symbology).lower()
        return BarcodeSpec(symbology=sym if sym in SYMBOLOGIES else "code128",
                           data=str(self.data if self.data is not None else ""),
                           module_mm=float(_clamp(float(self.module_mm), 0.0, MODULE_RANGE[1])),
                           height_mm=float(_clamp(float(self.height_mm), *HEIGHT_RANGE)),
                           quiet_zone=bool(self.quiet_zone) or bool(self.invert),
                           show_text=bool(self.show_text),
                           text_mm=float(_clamp(float(self.text_mm), *TEXT_RANGE)),
                           shrink_mm=float(_clamp(float(self.shrink_mm), *SHRINK_RANGE)),
                           font_family=str(self.font_family or "Segoe UI"),
                           invert=bool(self.invert), escapes=bool(self.escapes) and sym == "code128",
                           x=float(self.x), y=float(self.y))

    def encode(self) -> "Barcode":
        """The encoded barcode for this spec."""
        return encode(self.symbology, self.data, self.escapes and self.symbology == "code128")

    def margin_mm(self) -> float:
        """Engraved light border above and below the code in inverted mode (0 otherwise)."""
        return max(INVERT_MARGIN_MM, INVERT_MARGIN_MODULES * self.module_mm) if self.invert else 0.0

    def text_gap(self) -> float:
        return max(self.module_mm, 0.25 * self.text_mm)

    def size_mm(self, code: Barcode) -> tuple[float, float]:
        """Width incl. quiet zone and height incl. the text line."""
        s = self.normalized()
        ql, qr = code.quiet if s.quiet_zone else (0, 0)
        w = (ql + len(code.modules) + qr) * s.module_mm
        h = s.height_mm + ((s.text_gap() + s.text_mm) if s.show_text else 0.0) + 2 * s.margin_mm()
        return w, h


def check(spec: BarcodeSpec, code: Barcode) -> None:
    """Raise ``ValueError`` when the barcode is too thin or does not fit the work area."""
    s = spec.normalized()
    if s.module_mm < HARD_MIN_MODULE_MM - 1e-9:
        raise ValueError(f"Modulbreite {s.module_mm:.2f} mm ist zu schmal (mindestens "
                         f"{HARD_MIN_MODULE_MM:.2f} mm)")
    if s.shrink_mm > s.module_mm / 2.0 + 1e-9:
        raise ValueError(f"Strichkorrektur {s.shrink_mm:.2f} mm ist größer als die halbe "
                         f"Modulbreite ({s.module_mm / 2.0:.2f} mm)")
    w, h = s.size_mm(code)
    eps = 1e-6
    if s.x < -eps or s.y < -eps or s.x + w > WORK_WIDTH_MM + eps or s.y + h > WORK_HEIGHT_MM + eps:
        raise ValueError(
            f"Barcode {w:.1f} × {h:.1f} mm (inkl. Ruhezone) passt ab X {s.x:.1f} / Y {s.y:.1f} "
            f"nicht auf die Arbeitsfläche ({WORK_WIDTH_MM:.0f} × {WORK_HEIGHT_MM:.0f} mm)")


def bar_rects(spec: BarcodeSpec, code: Barcode) -> list[tuple[float, float, float, float]]:
    """Bars as (x0, y0, x1, y1) in mm, corrected by ``shrink_mm``.

    Normal mode: bars are lasered and become narrower. Inverted: the spaces are
    lasered, so the (unlasered) bars become wider by the same amount.
    """
    s = spec.normalized()
    m = s.module_mm
    ql = code.quiet[0] if s.quiet_zone else 0
    long_h = s.height_mm + (s.text_gap() + s.text_mm / 2.0 if s.show_text else 0.0)
    half = s.shrink_mm / 2.0 * (-1.0 if s.invert else 1.0)
    top = s.y + s.margin_mm()
    out = []
    for start, width in code.bars():
        guard = any(a <= start and start + width <= b for a, b in code.guards)
        x0 = s.x + (ql + start) * m + half
        x1 = s.x + (ql + start + width) * m - half
        out.append((x0, top, x1, top + (long_h if guard else s.height_mm)))
    return out


GlyphFn = Callable[[str, float], list[Glyph]]


def text_rings(spec: BarcodeSpec, code: Barcode, glyph_fn: GlyphFn) -> list[list[list[tuple]]]:
    """Glyph outlines of the human-readable line: one list of rings per character.

    The digit height is reduced uniformly when a segment would be wider than
    its space under the bars.
    """
    s = spec.normalized()
    m = s.module_mm
    ql = code.quiet[0] if s.quiet_zone else 0
    per_seg = [glyph_fn(seg.text, s.text_mm) for seg in code.segments]
    scale = 1.0
    for seg, glyphs in zip(code.segments, per_seg):
        room = (seg.end - seg.start) * m
        if seg.spread:
            need = max((g.advance for g in glyphs), default=0.0) * len(glyphs)
        else:
            need = sum(g.advance for g in glyphs)
        if need > room * 0.98 > 0:
            scale = min(scale, room * 0.98 / need)
    base_y = s.y + s.margin_mm() + s.height_mm + s.text_gap() + s.text_mm * scale
    out = []
    for seg, glyphs in zip(code.segments, per_seg):
        x0 = s.x + (ql + seg.start) * m
        room = (seg.end - seg.start) * m
        if seg.spread and glyphs:
            slot = room / len(glyphs)
            lefts = [x0 + slot * (k + 0.5) - g.advance * scale / 2.0 for k, g in enumerate(glyphs)]
        else:
            total = sum(g.advance for g in glyphs) * scale
            lefts, cur = [], x0 + (room - total) / 2.0
            for g in glyphs:
                lefts.append(cur)
                cur += g.advance * scale
        for g, left in zip(glyphs, lefts):
            rings = [[(left + u * scale, base_y + v * scale) for u, v in ring] for ring in g.rings
                     if len(ring) >= 3]
            if rings:
                out.append(rings)
    return out


def barcode_shapes(spec: BarcodeSpec, layer_id: str, code: Barcode | None = None,
                   glyph_fn: GlyphFn | None = None) -> list[Shape]:
    """Barcode as grouped ``polygon`` objects: one rectangle per bar, one object per glyph.

    Raises ``ValueError`` for invalid content, too thin modules or when it
    does not fit the work area.
    """
    s = spec.normalized()
    code = code or s.encode()
    check(s, code)
    group = new_id()
    if s.invert:
        return _inverted_shapes(s, code, layer_id, group, glyph_fn)
    out = []
    for x0, y0, x1, y1 in bar_rects(s, code):
        sh = Shape.from_points("polygon", [(x0, y0), (x1, y0), (x1, y1), (x0, y1)], layer_id)
        sh.groups = (group,)
        out.append(sh)
    if s.show_text and glyph_fn is not None:
        for rings in text_rings(s, code, glyph_fn):
            flat, starts = [], []
            for ring in rings:
                if flat:
                    starts.append(len(flat))
                flat.extend(ring)
            sh = Shape.from_points("polygon", flat, layer_id, rings=starts)
            sh.groups = (group,)
            out.append(sh)
    return out


def _inverted_shapes(s: BarcodeSpec, code: Barcode, layer_id: str, group: str,
                     glyph_fn: GlyphFn | None) -> list[Shape]:
    """Background (quiet zone, spaces, margin) minus bars and digits as polygons with holes."""
    from shapely.geometry import Polygon, box
    from shapely.ops import unary_union

    w, h = s.size_mm(code)
    keep = [box(*r) for r in bar_rects(s, code)]
    if s.show_text and glyph_fn is not None:
        for rings in text_rings(s, code, glyph_fn):
            g = Polygon()
            for ring in rings:
                g = g.symmetric_difference(Polygon(ring).buffer(0))   # even-odd like the canvas
            keep.append(g)
    area = box(s.x, s.y, s.x + w, s.y + h).difference(unary_union(keep))
    out = []
    for p in getattr(area, "geoms", [area]):
        if p.is_empty or p.geom_type != "Polygon":
            continue
        p = p.simplify(0)

        def ring(r):
            pts = list(r.coords)
            return pts[:-1] if len(pts) > 1 and pts[0] == pts[-1] else pts
        pts = ring(p.exterior)
        starts = []
        for hole in p.interiors:
            starts.append(len(pts))
            pts.extend(ring(hole))
        sh = Shape.from_points("polygon", pts, layer_id, rings=starts)
        sh.groups = (group,)
        out.append(sh)
    return out


def centered(spec: BarcodeSpec, center: tuple[float, float] | None = None,
             code: Barcode | None = None) -> BarcodeSpec:
    """Spec with X/Y so that the barcode (incl. quiet zone) is centred on ``center``."""
    s = spec.normalized()
    code = code or s.encode()
    w, h = s.size_mm(code)
    cx, cy = center or (WORK_WIDTH_MM / 2.0, WORK_HEIGHT_MM / 2.0)
    x = min(max(0.0, cx - w / 2.0), max(0.0, WORK_WIDTH_MM - w))
    y = min(max(0.0, cy - h / 2.0), max(0.0, WORK_HEIGHT_MM - h))
    return replace(s, x=x, y=y)


def describe(spec: BarcodeSpec, code: Barcode) -> str:
    s = spec.normalized()
    w, h = s.size_mm(code)
    extra = ""
    if code.values:
        extra = f", {len(code.values)} Symbole"
    elif code.text:
        extra = f", Prüfziffer {code.text[-1]}"
    inv = ", invertiert" if s.invert else ""
    shown = s.data if s.escapes and code.symbology == "code128" else code.text
    return (f"{LABELS[code.symbology]} „{shown}“: {len(code.modules)} Module{extra}, "
            f"{w:.1f} × {h:.1f} mm inkl. Ruhezone{inv}")


__all__ = ["Barcode", "BarcodeSpec", "LABELS", "SYMBOLOGIES", "TextSegment", "bar_rects",
           "barcode_shapes", "centered", "check", "code128_checksum", "code128_modules",
           "code128_sequence_values", "code128_values", "complete_digits", "describe",
           "ean_check_digit", "ean_modules", "encode", "readable", "text_rings", "unescape"]
