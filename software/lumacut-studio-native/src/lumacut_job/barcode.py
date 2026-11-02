"""1D barcodes (Code 128, EAN-13, EAN-8, UPC-A) as vector objects for engraving.

Pure Python, Qt-free, no third-party encoder. Matches the "Barcode" tool of
LightBurn and xTool Creative Space:

* **Code 128** – printable ASCII (32–126). Code sets B and C are chosen per
  character by a shortest-encoding search (digit pairs in C, everything else
  in B, switching with CODE B / CODE C), modulo-103 check symbol.
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

from .arctext import Glyph

SYMBOLOGIES = ("code128", "ean13", "ean8", "upca")
LABELS = {"code128": "Code 128", "ean13": "EAN-13", "ean8": "EAN-8", "upca": "UPC-A"}
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

# Minimum quiet zones in modules (left, right): ISO/IEC 15417 / 15420.
QUIET_MODULES = {"code128": (10, 10), "ean13": (11, 7), "ean8": (7, 7), "upca": (9, 9)}

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
CODE_C, CODE_B, START_B, START_C, STOP = 99, 100, 104, 105, 106

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


def _c128_pairs(text: str, i: int) -> bool:
    return i + 1 < len(text) and text[i].isdigit() and text[i + 1].isdigit() \
        and text[i].isascii() and text[i + 1].isascii()


def code128_values(text: str) -> list[int]:
    """Symbol values incl. start, check symbol and stop for ``text``.

    Shortest encoding over code sets B and C (dynamic programming); on equal
    length the encoder stays in its current set and starts in B.
    """
    text = str(text)
    if not text:
        raise ValueError("Kein Text für den Barcode")
    if len(text) > MAX_CODE128_CHARS:
        raise ValueError(f"Text zu lang für Code 128 (höchstens {MAX_CODE128_CHARS} Zeichen)")
    bad = sorted({c for c in text if not 32 <= ord(c) <= 126})
    if bad:
        shown = ", ".join(repr(c) for c in bad[:5])
        raise ValueError(f"Code 128 erlaubt nur ASCII-Zeichen ohne Umlaute – nicht erlaubt: {shown}")
    n = len(text)
    inf = float("inf")
    # cost[i][s]: symbols needed for text[i:] while in set s (0 = B, 1 = C).
    cost = [[inf, inf] for _ in range(n + 1)]
    step: list[list[tuple | None]] = [[None, None] for _ in range(n + 1)]
    cost[n] = [0, 0]
    for i in range(n - 1, -1, -1):
        pair = _c128_pairs(text, i)
        # in B: one character, or CODE C + pair
        opts_b = [(1 + cost[i + 1][0], ("B", i + 1, 0))]
        if pair:
            opts_b.append((2 + cost[i + 2][1], ("toC", i + 2, 1)))
        cost[i][0], step[i][0] = min(opts_b, key=lambda o: o[0])
        # in C: a digit pair, or CODE B + one character
        opts_c = []
        if pair:
            opts_c.append((1 + cost[i + 2][1], ("C", i + 2, 1)))
        opts_c.append((2 + cost[i + 1][0], ("toB", i + 1, 0)))
        cost[i][1], step[i][1] = min(opts_c, key=lambda o: o[0])
    s = 1 if _c128_pairs(text, 0) and cost[0][1] < cost[0][0] else 0
    values = [START_C if s else START_B]
    i = 0
    while i < n:
        kind, nxt, ns = step[i][s]
        if kind == "B":
            values.append(ord(text[i]) - 32)
        elif kind == "C":
            values.append(int(text[i:i + 2]))
        elif kind == "toC":
            values += [CODE_C, int(text[i:i + 2])]
        else:  # toB
            values += [CODE_B, ord(text[i]) - 32]
        i, s = nxt, ns
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


def encode(symbology: str, data: str) -> Barcode:
    sym = str(symbology).lower()
    if sym not in SYMBOLOGIES:
        raise ValueError(f"Unbekannter Barcode-Typ „{symbology}“")
    if sym == "code128":
        values = code128_values(data)
        mods = code128_modules(values)
        return Barcode(sym, str(data), mods, tuple(values),
                       (TextSegment(str(data), 0, len(mods)),))
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
                           invert=bool(self.invert), x=float(self.x), y=float(self.y))

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
    code = code or encode(s.symbology, s.data)
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
    code = code or encode(s.symbology, s.data)
    w, h = s.size_mm(code)
    cx, cy = center or (WORK_WIDTH_MM / 2.0, WORK_HEIGHT_MM / 2.0)
    x = min(max(0.0, cx - w / 2.0), max(0.0, WORK_WIDTH_MM - w))
    y = min(max(0.0, cy - h / 2.0), max(0.0, WORK_HEIGHT_MM - h))
    return replace(s, x=x, y=y)


def describe(spec: BarcodeSpec, code: Barcode) -> str:
    s = spec.normalized()
    w, h = s.size_mm(code)
    extra = ""
    if code.symbology == "code128":
        extra = f", {len(code.values)} Symbole"
    elif code.text:
        extra = f", Prüfziffer {code.text[-1]}"
    inv = ", invertiert" if s.invert else ""
    return (f"{LABELS[code.symbology]} „{code.text}“: {len(code.modules)} Module{extra}, "
            f"{w:.1f} × {h:.1f} mm inkl. Ruhezone{inv}")


__all__ = ["Barcode", "BarcodeSpec", "LABELS", "SYMBOLOGIES", "TextSegment", "bar_rects",
           "barcode_shapes", "centered", "check", "code128_checksum", "code128_modules",
           "code128_values", "complete_digits", "describe", "ean_check_digit", "ean_modules",
           "encode", "text_rings"]
