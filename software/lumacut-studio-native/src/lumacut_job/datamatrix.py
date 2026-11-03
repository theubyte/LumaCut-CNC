"""Data Matrix ECC 200 (ISO/IEC 16022) as vector objects for engraving – pure Python.

Square symbols 10×10 … 144×144, the six rectangular symbols 8×18 … 16×48
and the 18 DMRE rectangles 8×48 … 26×64 of ISO/IEC 21471 (Data Matrix
Rectangular Extension – longer and taller flat codes; not every scanner reads
them, so automatic rectangles stay ISO/IEC 16022 unless DMRE is asked for)
modules, Reed-Solomon over GF(256) (field polynomial 0x12D, generator roots
α¹…αⁿ), pad codewords with the 253-state randomisation of the standard.

Encodation picks the shortest mix of the ASCII (digit pairs, Upper Shift),
C40 (upper case and digits), Text (lower case and digits), X12 and – for UTF-8
behind ECI – Base 256 (bytes, 255-state randomised) modes with a dynamic program over the input
(:func:`encode_data`), so long upper- or lower-case text and umlauts need
smaller symbols than plain ASCII. C40 / Text / X12 runs are packed in whole
triples and left with Unlatch, which is dropped when the data ends exactly at
the symbol capacity. Text that is not ASCII is written as UTF-8 behind
an ECI 26 designator (also umlauts – readers often misread ISO 8859-1
bytes without ECI). ``gs1`` encodes a GS1 element string "(01)…(10)…"
(:mod:`lumacut_job.gs1`) as GS1 DataMatrix: FNC1 first, FNC1 as separator.
Codeword placement follows the reference algorithm of ISO/IEC 16022 Annex F.

Output style is the one of :mod:`lumacut_job.qr`: ``size_mm`` is the *width*
of the symbol without quiet zone (the edge for square symbols), the quiet
zone (``quiet_zone`` modules, standard: at least 1) stays light (normal) or
is engraved together with the light modules (inverted – for materials that
turn *light* when lasered). Regions are merged with shapely into closed
polygons so fill/hatch does not laser inner edges twice.
"""

from __future__ import annotations

from dataclasses import dataclass

from lumacut_canvas.model import Shape, new_id
from lumacut_canvas.workarea import WORK_HEIGHT_MM, WORK_WIDTH_MM

from . import gs1, qr

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
# Rectangular symbols (ISO/IEC 16022 table 7): (rows, cols): (region rows, region cols,
# regions side by side, data codewords, ECC codewords) – all with one RS block.
RECT_SYMBOLS: dict[tuple[int, int], tuple[int, int, int, int, int]] = {
    (8, 18): (6, 16, 1, 5, 7), (8, 32): (6, 14, 2, 10, 11), (12, 26): (10, 24, 1, 16, 14),
    (12, 36): (10, 16, 2, 22, 18), (16, 36): (14, 16, 2, 32, 24), (16, 48): (14, 22, 2, 49, 28),
}
RECT_SIZES = tuple(f"{r}x{c}" for r, c in RECT_SYMBOLS)
# DMRE (ISO/IEC 21471 table 7), same layout as RECT_SYMBOLS – all with one RS block.
DMRE_SYMBOLS: dict[tuple[int, int], tuple[int, int, int, int, int]] = {
    (8, 48): (6, 22, 2, 18, 15), (8, 64): (6, 14, 4, 24, 18), (8, 80): (6, 18, 4, 32, 22),
    (8, 96): (6, 22, 4, 38, 28), (8, 120): (6, 18, 6, 49, 32), (8, 144): (6, 22, 6, 63, 36),
    (12, 64): (10, 14, 4, 43, 27), (12, 88): (10, 20, 4, 64, 36), (16, 64): (14, 14, 4, 62, 36),
    (20, 36): (18, 16, 2, 44, 28), (20, 44): (18, 20, 2, 56, 34), (20, 64): (18, 14, 4, 84, 42),
    (22, 48): (20, 22, 2, 72, 38), (24, 48): (22, 22, 2, 80, 41), (24, 64): (22, 14, 4, 108, 46),
    (26, 40): (24, 18, 2, 70, 38), (26, 48): (24, 22, 2, 90, 42), (26, 64): (24, 14, 4, 118, 50),
}
DMRE_SIZES = tuple(f"{r}x{c}" for r, c in DMRE_SYMBOLS)
AUTO = 0                          # spec.symbol: smallest square size that fits
AUTO_RECT = -1                    # spec.symbol: smallest rectangular size that fits
AUTO_DMRE = -2                    # spec.symbol: smallest rectangle incl. DMRE that fits
AUTOS = (AUTO, AUTO_RECT, AUTO_DMRE)


class Format(tuple):
    """Symbol format (rows, cols, region rows, region cols, regions down, regions across,
    data codewords, ECC codewords, interleaved blocks)."""

    rows = property(lambda self: self[0])
    cols = property(lambda self: self[1])
    region = property(lambda self: (self[2], self[3]))
    regions = property(lambda self: (self[4], self[5]))
    data = property(lambda self: self[6])
    ecc = property(lambda self: self[7])
    blocks = property(lambda self: self[8])

    @property
    def square(self) -> bool:
        return self[0] == self[1]

    @property
    def key(self):
        """The ``spec.symbol`` value: edge (int) for squares, "RxC" for rectangles."""
        return self[0] if self.square else f"{self[0]}x{self[1]}"

    @property
    def dmre(self) -> bool:
        """Rectangular extension size (ISO/IEC 21471)."""
        return (self[0], self[1]) in DMRE_SYMBOLS

    @property
    def label(self) -> str:
        return f"{self[0]} × {self[1]}"


def _formats() -> dict:
    out = {}
    for n, (region, per, data, ecc, blocks) in SYMBOLS.items():
        out[n] = Format((n, n, region, region, per, per, data, ecc, blocks))
    for (r, c), (rr, rc, across, data, ecc) in (*RECT_SYMBOLS.items(), *DMRE_SYMBOLS.items()):
        assert c == across * (rc + 2) and r == rr + 2
        out[f"{r}x{c}"] = Format((r, c, rr, rc, 1, across, data, ecc, 1))
    return out


FORMATS = _formats()
SQUARE_FORMATS = tuple(FORMATS[n] for n in SIZES)
RECT_FORMATS = tuple(FORMATS[k] for k in RECT_SIZES)
DMRE_FORMATS = tuple(FORMATS[k] for k in DMRE_SIZES)
# all rectangles by capacity (ties: smaller area first) – the AUTO_DMRE search order
ALL_RECT_FORMATS = tuple(sorted(RECT_FORMATS + DMRE_FORMATS,
                                key=lambda f: (f.data, f.rows * f.cols)))


def symbol_key(symbol):
    """Normalised ``spec.symbol``: 0 / −1 / −2 (automatic square / rectangle / rectangle
    incl. DMRE), the edge of a square symbol (int) or "RxC" for a rectangle (also DMRE);
    ``ValueError`` if unknown."""
    if isinstance(symbol, str):
        t = symbol.strip().lower().replace("×", "x").replace(" ", "")
        if "x" in t:
            r, _, c = t.partition("x")
            if r.isdigit() and c.isdigit():
                key = int(r) if r == c else f"{int(r)}x{int(c)}"
                if key in FORMATS:
                    return key
            raise ValueError(f"Unbekannte Data-Matrix-Größe {symbol}")
        try:
            symbol = int(t)
        except ValueError:
            raise ValueError(f"Unbekannte Data-Matrix-Größe {symbol}") from None
    symbol = int(symbol or 0)
    if symbol in AUTOS or symbol in SYMBOLS:
        return symbol
    raise ValueError(f"Unbekannte Data-Matrix-Größe {symbol} (möglich: {', '.join(map(str, SIZES))}"
                     f", rechteckig {', '.join(RECT_SIZES)} oder DMRE {', '.join(DMRE_SIZES)})")

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

FNC1_CW = 232
LATCH_C40, LATCH_B256, LATCH_X12, LATCH_TEXT = 230, 231, 238, 239
UNLATCH = 254
B256_MAX = 1555                   # longest Base 256 field (2-byte length, fits 144 × 144)


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


def _c40_values(c: int, text_mode: bool) -> tuple[int, ...] | None:
    """C40 (or Text) values for one input item (byte or ``gs1.FNC1``)."""
    if c == gs1.FNC1:
        return (1, 27)                                  # Shift 2, FNC1
    if c > 255:
        return None
    if c >= 128:
        return (1, 30) + _c40_values(c - 128, text_mode)  # Shift 2, Upper Shift
    if c == 32:
        return (3,)
    if 48 <= c <= 57:
        return (c - 44,)
    if text_mode:
        if 97 <= c <= 122:
            return (c - 83,)
        if 65 <= c <= 90:
            return (2, c - 64)                          # Shift 3: upper case
        if c == 96:
            return (2, 0)
        if c >= 123:
            return (2, c - 96)
    else:
        if 65 <= c <= 90:
            return (c - 51,)
        if c >= 96:
            return (2, c - 96)                          # Shift 3: ` a–z { | } ~ DEL
    if c < 32:
        return (0, c)                                   # Shift 1: control characters
    if 33 <= c <= 47:
        return (1, c - 33)                              # Shift 2: punctuation
    if 58 <= c <= 64:
        return (1, c - 43)
    return (1, c - 69)                                  # [ \ ] ^ _


_X12 = {13: 0, 42: 1, 62: 2, 32: 3}


def _x12_values(c: int) -> tuple[int, ...] | None:
    if c in _X12:
        return (_X12[c],)
    if 48 <= c <= 57:
        return (c - 44,)
    if 65 <= c <= 90:
        return (c - 51,)
    return None


_MODES = ("c40", "text", "x12")
_LATCH = {"c40": LATCH_C40, "text": LATCH_TEXT, "x12": LATCH_X12}


def _values(mode: str, c: int):
    if mode == "x12":
        return _x12_values(c)
    return _c40_values(c, mode == "text")


def _pack(values: list[int]) -> list[int]:
    out = []
    for k in range(0, len(values), 3):
        v = 1600 * values[k] + 40 * values[k + 1] + values[k + 2] + 1
        out += [v >> 8, v & 0xFF]
    return out


def _b256_len(n: int) -> list[int]:
    return [n] if n <= 249 else [n // 250 + 249, n % 250]


def _randomise_255(cw: int, pos: int) -> int:
    return (cw + (149 * pos) % 255 + 1) % 256


@dataclass(frozen=True)
class Encoded:
    """Data codewords before padding; ``trailing_unlatch``: the last one is an Unlatch
    that may be left out when the data fills the symbol exactly."""

    codewords: tuple[int, ...]
    trailing_unlatch: bool = False

    def __len__(self) -> int:
        return len(self.codewords)


def encode_items(items: list[int], prefix: list[int] | None = None,
                 base256: bool = True) -> Encoded:
    """Shortest codeword stream for ``items`` (bytes 0…255 and ``gs1.FNC1``).

    Dynamic program over (position, mode): ASCII, C40 / Text / X12 with 0–2
    values of an unfinished triple, and Base 256 fields from ASCII. Costs are
    counted in thirds of a codeword (a C40 value is ⅔). Mode runs end with
    Unlatch on a full triple. On equal length ASCII wins. ``prefix``
    codewords (ECI, FNC1) come first; Base 256 is randomised by position.
    ``base256`` False: no Base 256 fields (readers guess the character set of
    Base 256 bytes without ECI – Shift JIS instead of ISO 8859-1 – so
    ISO 8859-1 text keeps Upper Shift).
    """
    prefix = list(prefix or [])
    n = len(items)
    inf = float("inf")
    n_states = 1 + 3 * len(_MODES)        # 0 = ASCII, 1 + 3·m + k
    cost = [[inf] * n_states for _ in range(n + 1)]
    back: list[list[tuple | None]] = [[None] * n_states for _ in range(n + 1)]
    cost[0][0] = 0
    high = base256 and any(128 <= c <= 255 for c in items)
    vals = [[_values(m, c) for c in items] for m in _MODES]

    def relax(i, st, c, prev):
        if c < cost[i][st]:
            cost[i][st] = c
            back[i][st] = prev

    for i in range(n + 1):
        for m in range(len(_MODES)):            # Unlatch on a full triple
            st = 1 + 3 * m
            if cost[i][st] < inf:
                relax(i, 0, cost[i][st] + 3, (i, st, ("cw", (UNLATCH,))))
        if i == n:
            break
        a = cost[i][0]
        if a < inf:
            c = items[i]
            if c == gs1.FNC1:
                relax(i + 1, 0, a + 3, (i, 0, ("cw", (FNC1_CW,))))
            elif 48 <= c <= 57 and i + 1 < n and 48 <= items[i + 1] <= 57:
                relax(i + 2, 0, a + 3, (i, 0, ("cw", (130 + (c - 48) * 10 + items[i + 1] - 48,))))
            elif c > 127:
                relax(i + 1, 0, a + 6, (i, 0, ("cw", (UPPER_SHIFT, c - 127))))
            else:
                relax(i + 1, 0, a + 3, (i, 0, ("cw", (c + 1,))))
            for m, mode in enumerate(_MODES):    # latch
                relax(i, 1 + 3 * m, a + 3, (i, 0, ("cw", (_LATCH[mode],))))
            if high:                            # Base 256 field from i to j
                for j in range(i + 1, min(n, i + B256_MAX) + 1):
                    if items[j - 1] > 255:
                        break
                    ln = j - i
                    relax(j, 0, a + 3 * (1 + len(_b256_len(ln)) + ln), (i, 0, ("b256", ln)))
        for m in range(len(_MODES)):
            v = vals[m][i]
            if v is None:
                continue
            for k in range(3):
                st = 1 + 3 * m + k
                if cost[i][st] < inf:
                    relax(i + 1, 1 + 3 * m + (k + len(v)) % 3, cost[i][st] + 2 * len(v),
                          (i, st, ("vals", v)))
    if cost[n][0] == inf:
        raise ValueError("Text lässt sich nicht als Data Matrix codieren")
    steps = []
    i, st = n, 0
    while (i, st) != (0, 0):
        pi, pst, act = back[i][st]
        steps.append((pi, act))
        i, st = pi, pst
    steps.reverse()
    out = list(prefix)
    pending: list[int] = []
    last_unlatch = False
    for pi, (kind, arg) in steps:
        last_unlatch = False
        if kind == "vals":
            pending += arg
            continue
        if pending:
            out += _pack(pending)
            pending = []
        if kind == "cw":
            out += arg
            last_unlatch = arg == (UNLATCH,)
        else:                                   # Base 256: latch, length, data – randomised
            field = _b256_len(arg) + list(items[pi:pi + arg])
            out.append(LATCH_B256)
            out += [_randomise_255(cw, len(out) + 1 + k) for k, cw in enumerate(field)]
    return Encoded(tuple(out), last_unlatch)


def text_items(text: str, gs1_mode: bool = False) -> tuple[list[int], list[int]]:
    """(prefix codewords, items) for ``text``: ASCII, else ECI 26 + UTF-8 (also for
    umlauts: readers guess the character set of bytes above 127 without ECI and
    often show Shift JIS instead of ISO 8859-1); GS1:
    the parsed element string with FNC1 (``ValueError`` on invalid GS1 data)."""
    if gs1_mode:
        seq = gs1.sequence(gs1.parse(text))
        return [FNC1_CW], seq[1:]
    if text.isascii():
        return [], list(text.encode("ascii"))
    return [ECI, ECI_UTF8 + 1], list(text.encode("utf-8"))


def encode_data(text: str, gs1_mode: bool = False) -> Encoded:
    prefix, items = text_items(text, gs1_mode)
    return encode_items(items, prefix, base256=ECI in prefix)


def text_codewords(text: str, gs1_mode: bool = False) -> list[int]:
    """Data codewords for ``text`` (shortest encodation, before padding)."""
    return list(encode_data(text, gs1_mode).codewords)


def pad(codewords: list[int], capacity: int) -> list[int]:
    out = list(codewords)
    if len(out) < capacity:
        out.append(PAD)
    while len(out) < capacity:
        pos = len(out) + 1
        v = PAD + (149 * pos) % 253 + 1
        out.append(v - 254 if v > 254 else v)
    return out


def _candidates(symbol) -> tuple:
    key = symbol_key(symbol)
    if key == AUTO:
        return SQUARE_FORMATS
    if key == AUTO_RECT:
        return RECT_FORMATS
    if key == AUTO_DMRE:
        return ALL_RECT_FORMATS
    f = FORMATS[key]
    if f.dmre:
        # the chosen size, then larger ones of the same height, then any larger rectangle
        same = [g for g in ALL_RECT_FORMATS if g.rows == f.rows and g.data >= f.data]
        same.sort(key=lambda g: (g is not f, g.data))
        return tuple(same) + tuple(g for g in ALL_RECT_FORMATS
                                   if g.data >= f.data and g not in same)
    family = SQUARE_FORMATS if f.square else RECT_FORMATS
    return tuple(g for g in family if g.data >= f.data)


def choose_format(n_codewords: int, symbol=AUTO, trailing_unlatch: bool = False) -> Format:
    """Smallest format of the requested family that holds ``n_codewords`` (one less when
    a trailing Unlatch can be dropped because the data then fills it exactly)."""
    cands = _candidates(symbol)
    for f in cands:
        if f.data >= n_codewords or (trailing_unlatch and f.data == n_codewords - 1):
            return f
    big = cands[-1]
    hint = " – quadratische Größe wählen" if not big.square else ""
    raise ValueError(f"Text zu lang für Data Matrix ({n_codewords} Codewörter, höchstens "
                     f"{big.data} bei {big.label}){hint}")


def choose_size(n_codewords: int, min_size: int = AUTO) -> int:
    """Edge of the smallest square symbol (at least ``min_size``) for ``n_codewords``."""
    for s in SIZES:
        if s >= min_size and SYMBOLS[s][2] >= n_codewords:
            return s
    raise ValueError(f"Text zu lang für Data Matrix ({n_codewords} Codewörter, höchstens "
                     f"{SYMBOLS[SIZES[-1]][2]} bei 144 × 144)")


def capacity_digits(size) -> int:
    return 2 * FORMATS[symbol_key(size)].data


def interleave(size, data: list[int]) -> list[int]:
    """Data plus ECC codewords in symbol order (blocks interleaved round-robin)."""
    f = size if isinstance(size, Format) else FORMATS[symbol_key(size)]
    n_data, n_ecc, blocks = f.data, f.ecc, f.blocks
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
        if r >= nrow:                     # only DMRE 26 × 40 / 26 × 48 / 26 × 64 (ISO 21471)
            r -= nrow
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
    """Encoded symbol; ``modules[y][x]`` True = dark, origin top left (same API as ``QrCode``).

    ``size`` is the width in modules (the edge of square symbols), ``rows`` the height.
    """

    size: int
    codewords: tuple[int, ...]
    modules: tuple[tuple[bool, ...], ...]
    rows: int = 0

    def __post_init__(self):
        if not self.rows:
            object.__setattr__(self, "rows", self.size)

    @property
    def cols(self) -> int:
        return self.size

    @property
    def format(self) -> Format:
        return FORMATS[self.rows if self.rows == self.size else f"{self.rows}x{self.size}"]

    @property
    def square(self) -> bool:
        return self.rows == self.size

    @property
    def data_codewords(self) -> int:
        return self.format.data

    def dark(self, x: int, y: int) -> bool:
        return 0 <= x < self.size and 0 <= y < self.rows and self.modules[y][x]

    def runs(self, quiet_zone: int = 0, invert: bool = False) -> list[tuple[int, int, int]]:
        """Horizontal runs (row, start, end excl.) of the modules to laser, in modules
        from the top left incl. quiet zone. Inverted: light modules plus quiet zone."""
        q = max(0, int(quiet_zone))
        w, h = self.size + 2 * q, self.rows + 2 * q
        out = []
        for y in range(h):
            x = 0
            while x < w:
                if self.dark(x - q, y - q) == invert:
                    x += 1
                    continue
                e = x
                while e < w and self.dark(e - q, y - q) != invert:
                    e += 1
                out.append((y, x, e))
                x = e
        return out


def build(size, codewords: list[int]) -> DataMatrix:
    """Symbol of format ``size`` (edge, "RxC" or :class:`Format`) from all codewords."""
    f = size if isinstance(size, Format) else FORMATS[symbol_key(size)]
    (rh, rw), (nv, nh) = f.region, f.regions
    mapping = placement(rh * nv, rw * nh)
    grid = [[False] * f.cols for _ in range(f.rows)]
    for ry in range(nv):
        for rx in range(nh):
            y0, x0 = ry * (rh + 2), rx * (rw + 2)
            for k in range(rw + 2):
                grid[y0 + rh + 1][x0 + k] = True            # solid bottom edge
                grid[y0][x0 + k] = k % 2 == 0               # dotted top edge
            for k in range(rh + 2):
                grid[y0 + k][x0] = True                     # solid left edge
                grid[y0 + k][x0 + rw + 1] = k % 2 == 1      # dotted right edge
            for r in range(rh):
                for c in range(rw):
                    v = mapping[ry * rh + r][rx * rw + c]
                    dark = v == -2 if v < 0 else bool(codewords[v >> 3] & (0x80 >> (v & 7)))
                    grid[y0 + 1 + r][x0 + 1 + c] = dark
    return DataMatrix(f.cols, tuple(codewords), tuple(tuple(r) for r in grid), f.rows)


def encode(text: str, size=AUTO, gs1_mode: bool = False) -> DataMatrix:
    """Encode ``text``.

    ``size``: 0 = smallest square symbol that fits, −1 = smallest rectangle, −2 =
    smallest rectangle incl. DMRE (ISO/IEC 21471), an edge (int) or "RxC" = this
    size or the next larger one of the same shape (DMRE: same height first).
    ``gs1_mode``: ``text`` is a GS1 element string "(AI)value…" (GS1 DataMatrix).
    """
    if not text:
        raise ValueError("Kein Text für den Data-Matrix-Code")
    enc = encode_data(text, gs1_mode)
    f = choose_format(len(enc), size, enc.trailing_unlatch)
    data = list(enc.codewords)
    if enc.trailing_unlatch and f.data == len(data) - 1:
        data.pop()                       # data ends in C40/Text/X12 exactly at the capacity
    return build(f, interleave(f, pad(data, f.data)))


# --- Vector output ------------------------------------------------------------------

def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


@dataclass(frozen=True)
class DataMatrixSpec:
    text: str = "LumaCut"
    symbol: int | str = AUTO  # edge, "RxC", 0 / -1 / -2 = automatic square / rectangle / DMRE
    size_mm: float = 15.0     # width without quiet zone (edge of square symbols)
    quiet_zone: int = DEFAULT_QUIET
    invert: bool = False
    gs1: bool = False         # text is a GS1 element string "(01)…(10)…"
    x: float = 0.0            # top left corner incl. quiet zone
    y: float = 0.0

    def normalized(self) -> "DataMatrixSpec":
        try:
            sym = symbol_key(self.symbol)
        except (TypeError, ValueError):
            sym = AUTO
        return DataMatrixSpec(text=str(self.text or ""), symbol=sym,
                              size_mm=float(_clamp(float(self.size_mm), *SIZE_RANGE)),
                              quiet_zone=int(_clamp(int(self.quiet_zone), *QUIET_RANGE)),
                              invert=bool(self.invert), gs1=bool(self.gs1),
                              x=float(self.x), y=float(self.y))

    def encode(self) -> DataMatrix:
        s = self.normalized()
        return encode(s.text, s.symbol, s.gs1)

    def module_mm(self, code: DataMatrix) -> float:
        return self.normalized().size_mm / code.size

    def total(self, code: DataMatrix) -> tuple[float, float]:
        """Width and height incl. quiet zone (mm)."""
        s = self.normalized()
        m = s.size_mm / code.size
        return m * (code.size + 2 * s.quiet_zone), m * (code.rows + 2 * s.quiet_zone)

    def total_mm(self, code: DataMatrix) -> float:
        return self.total(code)[0]


def datamatrix_shapes(spec: DataMatrixSpec, layer_id: str, code: DataMatrix | None = None) -> list[Shape]:
    """Symbol as grouped ``polygon`` objects (one area per object, holes as rings).

    Raises ``ValueError`` for empty/too long text, too small modules or when the
    symbol incl. quiet zone does not fit on the work area.
    """
    s = spec.normalized()
    code = code or s.encode()
    module = s.size_mm / code.size
    if module < HARD_MIN_MODULE_MM:
        raise ValueError(f"Module {module:.2f} mm sind zu klein (mindestens "
                         f"{HARD_MIN_MODULE_MM:.1f} mm) – Code größer machen oder Text kürzen")
    tw, th = s.total(code)
    eps = 1e-6
    if s.x < -eps or s.y < -eps or s.x + tw > WORK_WIDTH_MM + eps or s.y + th > WORK_HEIGHT_MM + eps:
        raise ValueError(
            f"Data Matrix {tw:.1f} × {th:.1f} mm (inkl. Ruhezone) passt ab X {s.x:.1f} / "
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
    used = code.data_codewords
    dmre = " DMRE" if code.format.dmre else ""
    return (f"{code.rows} × {code.size} Module{dmre} ({used} Datencodewörter), "
            f"Modul {module:.2f} mm")
