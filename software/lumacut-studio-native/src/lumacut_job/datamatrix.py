"""Data Matrix ECC 200 (ISO/IEC 16022) as vector objects for engraving – pure Python.

Square symbols 10×10 … 144×144 modules, Reed-Solomon over GF(256) (field
polynomial 0x12D, generator roots α¹…αⁿ), ASCII encodation with digit-pair
compaction and Upper Shift for bytes above 127, pad codewords with the
253-state randomisation of the standard. Text that is not ISO 8859-1 is
written as UTF-8 behind an ECI 26 designator. Codeword placement follows the
reference algorithm of ISO/IEC 16022 Annex F.

Output style is the one of :mod:`lumacut_job.qr`: ``size_mm`` is the edge of
the symbol *without* quiet zone, the quiet zone (``quiet_zone`` modules,
standard: at least 1) stays light (normal) or is engraved together with the
light modules (inverted – for materials that turn *light* when lasered).
Regions are merged with shapely into closed polygons so fill/hatch does not
laser inner edges twice.
"""

from __future__ import annotations

from dataclasses import dataclass

from lumacut_canvas.model import Shape, new_id
from lumacut_canvas.workarea import WORK_HEIGHT_MM, WORK_WIDTH_MM

from . import qr

# size: (data region edge, regions per side, data codewords, ECC codewords, interleaved blocks)
SYMBOLS: dict[int, tuple[int, int, int, int, int]] = {
    10: (8, 1, 3, 5, 1), 12: (10, 1, 5, 7, 1), 14: (12, 1, 8, 10, 1), 16: (14, 1, 12, 12, 1),
    18: (16, 1, 18, 14, 1), 20: (18, 1, 22, 18, 1), 22: (20, 1, 30, 20, 1),
    24: (22, 1, 36, 24, 1), 26: (24, 1, 44, 28, 1),
    32: (14, 2, 62, 36, 1), 36: (16, 2, 86, 42, 1), 40: (18, 2, 114, 48, 1),
    44: (20, 2, 144, 56, 1), 48: (22, 2, 174, 68, 1), 52: (24, 2, 204, 84, 2),
    64: (14, 4, 280, 112, 2), 72: (16, 4, 368, 144, 4), 80: (18, 4, 456, 192, 4),
    88: (20, 4, 576, 224, 4), 96: (22, 4, 696, 272, 4), 104: (24, 4, 816, 336, 6),
    120: (18, 6, 1050, 408, 6), 132: (20, 6, 1304, 496, 8), 144: (22, 6, 1558, 620, 10),
}
SIZES = tuple(SYMBOLS)
AUTO = 0                          # spec.symbol: smallest size that fits

MIN_MODULE_MM = qr.MIN_MODULE_MM
HARD_MIN_MODULE_MM = qr.HARD_MIN_MODULE_MM
SIZE_RANGE = qr.SIZE_RANGE
QUIET_RANGE = (0, 10)
DEFAULT_QUIET = 2

PAD = 129
UPPER_SHIFT = 235
ECI = 241
ECI_UTF8 = 26

# --- Reed-Solomon over GF(256), polynomial x^8+x^5+x^3+x^2+1 (0x12D) -----------------

_EXP = [0] * 512
_LOG = [0] * 256
_v = 1
for _i in range(255):
    _EXP[_i] = _v
    _LOG[_v] = _i
    _v <<= 1
    if _v & 0x100:
        _v ^= 0x12D
for _i in range(255, 512):
    _EXP[_i] = _EXP[_i - 255]


def gf_mul(a: int, b: int) -> int:
    if a == 0 or b == 0:
        return 0
    return _EXP[_LOG[a] + _LOG[b]]


def rs_generator(n: int) -> list[int]:
    """Coefficients (highest power first, leading 1 dropped) of ∏(x − αⁱ), i = 1…n."""
    g = [1]
    for i in range(1, n + 1):
        root = _EXP[i]
        nxt = g + [0]
        for j, c in enumerate(g):
            nxt[j + 1] ^= gf_mul(c, root)
        g = nxt
    return g[1:]


def rs_ecc(data, n: int) -> list[int]:
    gen = rs_generator(n)
    rem = [0] * n
    for b in data:
        f = b ^ rem.pop(0)
        rem.append(0)
        if f:
            for i, c in enumerate(gen):
                rem[i] ^= gf_mul(c, f)
    return rem


# --- Encodation ---------------------------------------------------------------------

def encode_ascii(data: bytes) -> list[int]:
    """ASCII encodation: digit pairs → 130+nn, 0…127 → value+1, 128…255 via Upper Shift."""
    out: list[int] = []
    i, n = 0, len(data)
    while i < n:
        c = data[i]
        if 48 <= c <= 57 and i + 1 < n and 48 <= data[i + 1] <= 57:
            out.append(130 + (c - 48) * 10 + (data[i + 1] - 48))
            i += 2
            continue
        if c > 127:
            out += [UPPER_SHIFT, c - 127]
        else:
            out.append(c + 1)
        i += 1
    return out


def text_codewords(text: str) -> list[int]:
    """Codewords for ``text``: ISO 8859-1 (default interpretation) or ECI 26 + UTF-8."""
    try:
        return encode_ascii(text.encode("latin-1"))
    except UnicodeEncodeError:
        return [ECI, ECI_UTF8 + 1] + encode_ascii(text.encode("utf-8"))


def pad(codewords: list[int], capacity: int) -> list[int]:
    out = list(codewords)
    if len(out) < capacity:
        out.append(PAD)
    while len(out) < capacity:
        pos = len(out) + 1
        v = PAD + (149 * pos) % 253 + 1
        out.append(v - 254 if v > 254 else v)
    return out


def choose_size(n_codewords: int, min_size: int = AUTO) -> int:
    for s in SIZES:
        if s >= min_size and SYMBOLS[s][2] >= n_codewords:
            return s
    raise ValueError(f"Text zu lang für Data Matrix ({n_codewords} Codewörter, höchstens "
                     f"{SYMBOLS[SIZES[-1]][2]} bei 144 × 144)")


def capacity_digits(size: int) -> int:
    return 2 * SYMBOLS[size][2]


def interleave(size: int, data: list[int]) -> list[int]:
    """Data plus ECC codewords in symbol order (blocks interleaved round-robin)."""
    _r, _n, n_data, n_ecc, blocks = SYMBOLS[size]
    assert len(data) == n_data
    per_ecc = n_ecc // blocks
    out = list(data) + [0] * n_ecc
    for b in range(blocks):
        ecc = rs_ecc(data[b::blocks], per_ecc)
        for j, e in enumerate(ecc):
            out[n_data + b + j * blocks] = e
    return out


# --- Placement (ISO/IEC 16022 Annex F) ----------------------------------------------

def placement(nrow: int, ncol: int) -> list[list[int]]:
    """Mapping matrix: value 8·cw + bit index (0 = MSB) or −1/−2 for fixed light/dark."""
    arr = [[None] * ncol for _ in range(nrow)]

    def module(r, c, cw, bit):
        if r < 0:
            r += nrow
            c += 4 - ((nrow + 4) % 8)
        if c < 0:
            c += ncol
            r += 4 - ((ncol + 4) % 8)
        arr[r][c] = cw * 8 + bit

    def utah(r, c, cw):
        for bit, (dr, dc) in enumerate(((-2, -2), (-2, -1), (-1, -2), (-1, -1),
                                        (-1, 0), (0, -2), (0, -1), (0, 0))):
            module(r + dr, c + dc, cw, bit)

    def corner(cw, cells):
        for bit, (r, c) in enumerate(cells):
            module(r, c, cw, bit)

    cw, row, col = 0, 4, 0
    while True:
        if row == nrow and col == 0:
            corner(cw, ((nrow - 1, 0), (nrow - 1, 1), (nrow - 1, 2), (0, ncol - 2),
                        (0, ncol - 1), (1, ncol - 1), (2, ncol - 1), (3, ncol - 1)))
            cw += 1
        if row == nrow - 2 and col == 0 and ncol % 4:
            corner(cw, ((nrow - 3, 0), (nrow - 2, 0), (nrow - 1, 0), (0, ncol - 4),
                        (0, ncol - 3), (0, ncol - 2), (0, ncol - 1), (1, ncol - 1)))
            cw += 1
        if row == nrow - 2 and col == 0 and ncol % 8 == 4:
            corner(cw, ((nrow - 3, 0), (nrow - 2, 0), (nrow - 1, 0), (0, ncol - 2),
                        (0, ncol - 1), (1, ncol - 1), (2, ncol - 1), (3, ncol - 1)))
            cw += 1
        if row == nrow + 4 and col == 2 and ncol % 8 == 0:
            corner(cw, ((nrow - 1, 0), (nrow - 1, ncol - 1), (0, ncol - 3), (0, ncol - 2),
                        (0, ncol - 1), (1, ncol - 3), (1, ncol - 2), (1, ncol - 1)))
            cw += 1
        while True:                       # sweep up and to the right
            if row < nrow and col >= 0 and arr[row][col] is None:
                utah(row, col, cw)
                cw += 1
            row -= 2
            col += 2
            if not (row >= 0 and col < ncol):
                break
        row += 1
        col += 3
        while True:                       # sweep down and to the left
            if row >= 0 and col < ncol and arr[row][col] is None:
                utah(row, col, cw)
                cw += 1
            row += 2
            col -= 2
            if not (row < nrow and col >= 0):
                break
        row += 3
        col += 1
        if not (row < nrow or col < ncol):
            break
    if arr[nrow - 1][ncol - 1] is None:   # fixed pattern in the lower right corner
        arr[nrow - 1][ncol - 1] = arr[nrow - 2][ncol - 2] = -2
        arr[nrow - 1][ncol - 2] = arr[nrow - 2][ncol - 1] = -1
    return arr


@dataclass(frozen=True)
class DataMatrix:
    """Encoded symbol; ``modules[y][x]`` True = dark, origin top left (same API as ``QrCode``)."""

    size: int
    codewords: tuple[int, ...]
    modules: tuple[tuple[bool, ...], ...]

    @property
    def data_codewords(self) -> int:
        return SYMBOLS[self.size][2]

    def dark(self, x: int, y: int) -> bool:
        return 0 <= x < self.size and 0 <= y < self.size and self.modules[y][x]

    runs = qr.QrCode.runs


def build(size: int, codewords: list[int]) -> DataMatrix:
    region, per_side, *_ = SYMBOLS[size]
    n = region * per_side
    mapping = placement(n, n)
    grid = [[False] * size for _ in range(size)]
    step = region + 2
    for ry in range(per_side):
        for rx in range(per_side):
            y0, x0 = ry * step, rx * step
            for k in range(step):
                grid[y0 + step - 1][x0 + k] = True          # solid bottom edge
                grid[y0 + k][x0] = True                     # solid left edge
                grid[y0][x0 + k] = k % 2 == 0               # dotted top edge
                grid[y0 + k][x0 + step - 1] = k % 2 == 1    # dotted right edge
            for r in range(region):
                for c in range(region):
                    v = mapping[ry * region + r][rx * region + c]
                    dark = v == -2 if v < 0 else bool(codewords[v >> 3] & (0x80 >> (v & 7)))
                    grid[y0 + 1 + r][x0 + 1 + c] = dark
    return DataMatrix(size, tuple(codewords), tuple(tuple(r) for r in grid))


def encode(text: str, size: int = AUTO) -> DataMatrix:
    """Encode ``text``; ``size`` 0 = smallest square symbol that fits, else the minimum edge."""
    if not text:
        raise ValueError("Kein Text für den Data-Matrix-Code")
    size = int(size)
    if size and size not in SYMBOLS:
        raise ValueError(f"Unbekannte Data-Matrix-Größe {size} (möglich: {', '.join(map(str, SIZES))})")
    data = text_codewords(text)
    s = choose_size(len(data), size)
    return build(s, interleave(s, pad(data, SYMBOLS[s][2])))


# --- Vector output ------------------------------------------------------------------

def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


@dataclass(frozen=True)
class DataMatrixSpec:
    text: str = "LumaCut"
    symbol: int = AUTO       # module count per edge, 0 = automatic
    size_mm: float = 15.0
    quiet_zone: int = DEFAULT_QUIET
    invert: bool = False
    x: float = 0.0           # top left corner incl. quiet zone
    y: float = 0.0

    def normalized(self) -> "DataMatrixSpec":
        sym = int(self.symbol or 0)
        return DataMatrixSpec(text=str(self.text or ""), symbol=sym if sym in SYMBOLS else AUTO,
                              size_mm=float(_clamp(float(self.size_mm), *SIZE_RANGE)),
                              quiet_zone=int(_clamp(int(self.quiet_zone), *QUIET_RANGE)),
                              invert=bool(self.invert), x=float(self.x), y=float(self.y))

    def total_mm(self, code: DataMatrix) -> float:
        s = self.normalized()
        return s.size_mm * (code.size + 2 * s.quiet_zone) / code.size


def datamatrix_shapes(spec: DataMatrixSpec, layer_id: str, code: DataMatrix | None = None) -> list[Shape]:
    """Symbol as grouped ``polygon`` objects (one area per object, holes as rings).

    Raises ``ValueError`` for empty/too long text, too small modules or when the
    symbol incl. quiet zone does not fit on the work area.
    """
    s = spec.normalized()
    code = code or encode(s.text, s.symbol)
    module = s.size_mm / code.size
    if module < HARD_MIN_MODULE_MM:
        raise ValueError(f"Module {module:.2f} mm sind zu klein (mindestens "
                         f"{HARD_MIN_MODULE_MM:.1f} mm) – Code größer machen oder Text kürzen")
    total = module * (code.size + 2 * s.quiet_zone)
    eps = 1e-6
    if s.x < -eps or s.y < -eps or s.x + total > WORK_WIDTH_MM + eps or s.y + total > WORK_HEIGHT_MM + eps:
        raise ValueError(
            f"Data Matrix {total:.1f} × {total:.1f} mm (inkl. Ruhezone) passt ab X {s.x:.1f} / "
            f"Y {s.y:.1f} nicht auf die Arbeitsfläche ({WORK_WIDTH_MM:.0f} × {WORK_HEIGHT_MM:.0f} mm)")
    group = new_id()
    out = []
    for outer, holes in qr.qr_regions(code, module, s.quiet_zone, s.invert, (s.x, s.y)):
        pts = list(outer)
        rings = []
        for h in holes:
            rings.append(len(pts))
            pts.extend(h)
        sh = Shape.from_points("polygon", pts, layer_id, rings=rings)
        sh.groups = (group,)
        out.append(sh)
    return out


def describe(code: DataMatrix, size_mm: float) -> str:
    module = size_mm / code.size
    used = SYMBOLS[code.size][2]
    return f"{code.size} × {code.size} Module ({used} Datencodewörter), Modul {module:.2f} mm"
