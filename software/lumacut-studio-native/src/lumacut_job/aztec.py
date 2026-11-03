"""Aztec Code (ISO/IEC 24778) as vector objects for engraving – pure Python.

Compact symbols (1–4 layers, 15×15 … 27×27 modules) and full-range symbols
(4–32 layers, 31×31 … 151×151 modules with reference grid). Aztec needs no
quiet zone (the finder is the bull's eye in the centre), so it is the most
compact 2D code for small marks, e.g. tickets, part labels and tool tags.

Encodation (:func:`encode_bits`) is a shortest-path search over the five
character modes Upper, Lower, Mixed, Punct and Digit with latches, shifts,
the two-character Punct codes (". ", ", ", ": ", CR LF) and Binary Shift runs
for bytes outside the character sets, so the bit stream is as short as the
mode tables allow. Text that is not ASCII is written as UTF-8 behind an
FLG(2) ECI 26 designator (readers guess the character set of bytes above 127
otherwise). ``gs1`` encodes a GS1 element string "(01)…(10)…"
(:mod:`lumacut_job.gs1`) as GS1 Aztec: FLG(0) = FNC1 first and as separator.

The data words are bit-stuffed, protected by Reed-Solomon over GF(2⁶),
GF(2⁸), GF(2¹⁰) or GF(2¹²) (by layer count) with at least ``ecc_percent`` of
the symbol words plus 3 for error correction (ISO recommendation: 23 % + 3), the mode message with
GF(16) – the same layout as the ISO standard and the zxing reference encoder.

Output style is the one of :mod:`lumacut_job.datamatrix`: ``size_mm`` is the
edge of the symbol without quiet zone; the quiet zone stays light (normal) or
is engraved together with the light modules (inverted).
"""

from __future__ import annotations

from dataclasses import dataclass

from lumacut_canvas.model import Shape, new_id
from lumacut_canvas.workarea import WORK_HEIGHT_MM, WORK_WIDTH_MM

from . import gs1, qr

AUTO = 0
MIN_MODULE_MM = qr.MIN_MODULE_MM
HARD_MIN_MODULE_MM = qr.HARD_MIN_MODULE_MM
SIZE_RANGE = qr.SIZE_RANGE
QUIET_RANGE = (0, 10)
DEFAULT_QUIET = 1
ECC_RANGE = (10, 90)              # percent of the symbol (ISO recommends 23 % + 3 words)
DEFAULT_ECC = 23
FNC1 = gs1.FNC1

# --- symbol formats -------------------------------------------------------------------

WORD_SIZE = [4, 6, 6, 8, 8, 8, 8, 8, 8] + [10] * 14 + [12] * 10   # index: layers (0 = mode message)


def total_bits(layers: int, compact: bool) -> int:
    """Bits in all data layers of a symbol."""
    return ((88 if compact else 112) + 16 * layers) * layers


def matrix_size(layers: int, compact: bool) -> int:
    base = (11 if compact else 14) + 4 * layers
    return base if compact else base + 1 + 2 * ((base // 2 - 1) // 15)


@dataclass(frozen=True)
class Format:
    compact: bool
    layers: int

    @property
    def size(self) -> int:
        return matrix_size(self.layers, self.compact)

    @property
    def key(self) -> int:
        return self.size

    @property
    def word_size(self) -> int:
        return WORD_SIZE[self.layers]

    @property
    def words(self) -> int:
        return total_bits(self.layers, self.compact) // self.word_size

    @property
    def label(self) -> str:
        kind = "kompakt" if self.compact else "voll"
        layers = f"{self.layers} Lage{'n' if self.layers > 1 else ''}"
        return f"{self.size} × {self.size} ({kind}, {layers})"


# Candidate order of the reference encoder: compact 1–4, then full 4–32 (full 1–3 are
# never smaller than a compact symbol). All edges are distinct, so the edge is the key.
FORMATS_LIST = tuple([Format(True, n) for n in range(1, 5)]
                     + [Format(False, n) for n in range(4, 33)])
FORMATS = {f.key: f for f in FORMATS_LIST}
SIZES = tuple(FORMATS)


def symbol_key(symbol) -> int:
    """Normalize a ``spec.symbol`` value (edge or 0); ``ValueError`` for unknown sizes."""
    try:
        n = int(str(symbol).split("x")[0].strip()) if isinstance(symbol, str) else int(symbol)
    except (TypeError, ValueError):
        raise ValueError(f"Unbekannte Aztec-Größe {symbol!r}") from None
    if n != AUTO and n not in FORMATS:
        raise ValueError(f"Unbekannte Aztec-Größe {symbol!r}")
    return n


# --- Galois fields / Reed-Solomon -----------------------------------------------------

_POLY = {4: 0x13, 6: 0x43, 8: 0x12D, 10: 0x409, 12: 0x1069}
_FIELDS: dict[int, tuple[list[int], list[int]]] = {}


def _field(bits: int) -> tuple[list[int], list[int]]:
    if bits not in _FIELDS:
        n = 1 << bits
        exp, log = [0] * (2 * n), [0] * n
        x = 1
        for i in range(n - 1):
            exp[i] = x
            log[x] = i
            x <<= 1
            if x & n:
                x ^= _POLY[bits]
        for i in range(n - 1, 2 * n):
            exp[i] = exp[i - (n - 1)]
        _FIELDS[bits] = (exp, log)
    return _FIELDS[bits]


def gf_mul(a: int, b: int, bits: int) -> int:
    if a == 0 or b == 0:
        return 0
    exp, log = _field(bits)
    return exp[log[a] + log[b]]


def rs_ecc(data: list[int], n: int, bits: int) -> list[int]:
    """``n`` check words for ``data`` over GF(2^bits), generator roots α¹…αⁿ."""
    exp, _log = _field(bits)
    gen = [1]
    for i in range(1, n + 1):
        nxt = [0] * (len(gen) + 1)
        for j, g in enumerate(gen):
            nxt[j] ^= g
            nxt[j + 1] ^= gf_mul(g, exp[i], bits)
        gen = nxt
    rem = [0] * n
    for d in data:
        f = d ^ rem[0]
        rem = rem[1:] + [0]
        if f:
            for j in range(n):
                rem[j] ^= gf_mul(gen[j + 1], f, bits)
    return rem


# --- high-level encodation ------------------------------------------------------------

UPPER, LOWER, MIXED, DIGIT, PUNCT = range(5)
_MODE_NAMES = ("Upper", "Lower", "Mixed", "Digit", "Punct")
_WIDTH = (5, 5, 5, 4, 5)

_CHARS: list[dict[int, int]] = [{} for _ in range(5)]
_CHARS[UPPER][32] = _CHARS[LOWER][32] = _CHARS[DIGIT][32] = _CHARS[MIXED][32] = 1
for _i in range(26):
    _CHARS[UPPER][ord("A") + _i] = 2 + _i
    _CHARS[LOWER][ord("a") + _i] = 2 + _i
for _i in range(10):
    _CHARS[DIGIT][ord("0") + _i] = 2 + _i
_CHARS[DIGIT][ord(",")] = 12
_CHARS[DIGIT][ord(".")] = 13
for _i, _c in enumerate([*range(1, 14), 27, 28, 29, 30, 31, *b"@\\^_`|~", 127]):
    _CHARS[MIXED][_c] = 2 + _i
_CHARS[PUNCT][13] = 1
for _i, _c in enumerate(b"!\"#$%&'()*+,-./:;<=>?[]{}"):
    _CHARS[PUNCT][_c] = 6 + _i
PUNCT_PAIRS = {b"\r\n": 2, b". ": 3, b", ": 4, b": ": 5}

# Latch sequences (code, bits) from mode to mode (ISO 24778 table 2, shortest paths).
_LATCH: dict[tuple[int, int], tuple[tuple[int, int], ...]] = {
    (UPPER, LOWER): ((28, 5),), (UPPER, MIXED): ((29, 5),), (UPPER, DIGIT): ((30, 5),),
    (UPPER, PUNCT): ((29, 5), (30, 5)),
    (LOWER, UPPER): ((30, 5), (14, 4)), (LOWER, MIXED): ((29, 5),), (LOWER, DIGIT): ((30, 5),),
    (LOWER, PUNCT): ((29, 5), (30, 5)),
    (MIXED, UPPER): ((29, 5),), (MIXED, LOWER): ((28, 5),), (MIXED, DIGIT): ((29, 5), (30, 5)),
    (MIXED, PUNCT): ((30, 5),),
    (DIGIT, UPPER): ((14, 4),), (DIGIT, LOWER): ((14, 4), (28, 5)),
    (DIGIT, MIXED): ((14, 4), (29, 5)), (DIGIT, PUNCT): ((14, 4), (29, 5), (30, 5)),
    (PUNCT, UPPER): ((31, 5),), (PUNCT, LOWER): ((31, 5), (28, 5)),
    (PUNCT, MIXED): ((31, 5), (29, 5)), (PUNCT, DIGIT): ((31, 5), (30, 5)),
}
_LATCH_BITS = {k: sum(b for _c, b in v) for k, v in _LATCH.items()}
BINARY_SHIFT = 31                 # in Upper, Lower and Mixed
_SHORT_RUN = 31                   # Binary Shift: 5-bit length up to 31 bytes, then 11 bits
MAX_BINARY_RUN = 2047 + 31


def text_items(text: str, gs1_mode: bool = False) -> tuple[list[tuple[int, int]], list[int]]:
    """(prefix bits, items): ASCII as is, else ECI 26 + UTF-8; GS1: FNC1 + element string."""
    if gs1_mode:
        return [], gs1.sequence(gs1.parse(text))
    if text.isascii():
        return [], list(text.encode("ascii"))
    # P/S FLG(2) "2" "6" – the designator for ECI 26 (UTF-8), see ISO 24778 7.3.1.2
    return [(0, 5), (0, 5), (2, 3), (4, 4), (8, 4)], list(text.encode("utf-8"))


def encode_items(items: list[int],
                 prefix: list[tuple[int, int]] | None = None) -> list[tuple[int, int]]:
    """Shortest bit sequence for ``items`` (bytes, :data:`FNC1`) as (value, bits) pairs.

    Dynamic program over the positions; states are the latched mode, and – inside a
    Binary Shift run – the run length (1…31 short, 32 = long form). Each state keeps
    its cheapest cost and a back pointer, so the result is optimal for this model.
    """
    n = len(items)
    # state key: (mode, run) with run 0 = not in binary; value: (cost, prev_pos, prev_key, action)
    best: list[dict] = [dict() for _ in range(n + 1)]
    best[0][(UPPER, 0)] = (0, -1, None, None)

    def relax(pos, key, cost, prev_pos, prev_key, action):
        cur = best[pos].get(key)
        if cur is None or cost < cur[0]:
            best[pos][key] = (cost, prev_pos, prev_key, action)

    for i in range(n + 1):
        states = best[i]
        # leave a binary run (header and bytes are paid already)
        for (m, run), (cost, *_r) in list(states.items()):
            if run:
                relax(i, (m, 0), cost, i, (m, run), ("end",))
        # latch to another mode
        for m in range(5):
            cur = states.get((m, 0))
            if cur is None:
                continue
            for m2 in range(5):
                if m2 != m:
                    relax(i, (m2, 0), cur[0] + _LATCH_BITS[(m, m2)], i, (m, 0), ("latch", m, m2))
        if i == n:
            break
        c = items[i]
        pair = None
        if i + 1 < n and FNC1 not in (c, items[i + 1]):
            pair = PUNCT_PAIRS.get(bytes(items[i:i + 2]))
        for (m, run), (cost, *_r) in list(states.items()):
            key = (m, run)
            if run:
                if c == FNC1:
                    continue
                if run < _SHORT_RUN:
                    relax(i + 1, (m, run + 1), cost + 8, i, key, ("byte", c))
                elif run == _SHORT_RUN:
                    relax(i + 1, (m, 32), cost + 8 + 6, i, key, ("byte", c))
                else:
                    relax(i + 1, (m, 32), cost + 8, i, key, ("byte", c))
                continue
            w = _WIDTH[m]
            if c == FNC1:
                if m == PUNCT:
                    relax(i + 1, key, cost + 5 + 3, i, key, ("fnc1", m))
                else:
                    relax(i + 1, key, cost + w + 5 + 3, i, key, ("fnc1", m))
                continue
            code = _CHARS[m].get(c)
            if code is not None:
                relax(i + 1, key, cost + w, i, key, ("char", m, code))
            if m != PUNCT:
                pc = _CHARS[PUNCT].get(c)
                if pc is not None:
                    relax(i + 1, key, cost + w + 5, i, key, ("pshift", m, pc))
                if pair is not None:
                    relax(i + 2, key, cost + w + 5, i, key, ("pshift", m, pair))
                if m in (LOWER, DIGIT) and c in _CHARS[UPPER]:
                    relax(i + 1, key, cost + w + 5, i, key, ("ushift", m, _CHARS[UPPER][c]))
            elif pair is not None:
                relax(i + 2, key, cost + 5, i, key, ("char", m, pair))
            if m in (UPPER, LOWER, MIXED):
                relax(i + 1, (m, 1), cost + 5 + 5 + 8, i, key, ("bstart", m, c))
    end = min(best[n].items(), key=lambda kv: kv[1][0], default=None)
    if end is None:
        raise ValueError("Text lässt sich nicht als Aztec-Code darstellen")
    # walk back
    actions = []
    pos, key = n, end[0]
    while True:
        cost, prev_pos, prev_key, action = best[pos][key]
        if action is None:
            break
        actions.append(action)
        pos, key = prev_pos, prev_key
    actions.reverse()
    out: list[tuple[int, int]] = list(prefix or [])
    run: list[int] | None = None

    def flush():
        k = len(run)
        if k > MAX_BINARY_RUN:            # longer than any symbol can hold anyway
            raise ValueError("Text zu lang für einen Aztec-Code")
        out.extend([(k, 5)] if k <= _SHORT_RUN else [(0, 5), (k - _SHORT_RUN, 11)])
        out.extend((b, 8) for b in run)

    for a in actions:
        kind = a[0]
        if kind == "byte":
            run.append(a[1])
            continue
        if run is not None:
            flush()
            run = None
        if kind == "latch":
            out.extend(_LATCH[(a[1], a[2])])
        elif kind == "char":
            out.append((a[2], _WIDTH[a[1]]))
        elif kind in ("pshift", "ushift"):
            shift = 0 if kind == "pshift" else (28 if a[1] == LOWER else 15)
            out.extend([(shift, _WIDTH[a[1]]), (a[2], 5)])
        elif kind == "fnc1":              # FLG(0), behind a Punct Shift unless in Punct
            if a[1] != PUNCT:
                out.append((0, _WIDTH[a[1]]))
            out.extend([(0, 5), (0, 3)])
        elif kind == "bstart":
            out.append((BINARY_SHIFT, 5))
            run = [a[2]]
    if run is not None:
        flush()
    return out


def encode_bits(text: str, gs1_mode: bool = False) -> list[int]:
    """The data bit stream (before stuffing) for ``text``."""
    prefix, items = text_items(text, gs1_mode)
    bits = []
    for v, b in encode_items(items, prefix):
        bits.extend((v >> (b - 1 - k)) & 1 for k in range(b))
    return bits


def stuff_bits(bits: list[int], word_size: int) -> list[int]:
    """Words of ``word_size`` bits; all-0 / all-1 words get a complementary stuffed bit."""
    n = len(bits)
    mask = (1 << word_size) - 2
    out = []
    i = 0
    while i < n:
        word = 0
        for j in range(word_size):
            if i + j >= n or bits[i + j]:
                word |= 1 << (word_size - 1 - j)
        if word & mask == mask:
            out.append(word & mask)
            i += word_size - 1
        elif word & mask == 0:
            out.append(word | 1)
            i += word_size - 1
        else:
            out.append(word)
            i += word_size
    return out


def _bits_of(words: list[int], width: int) -> list[int]:
    return [(w >> (width - 1 - k)) & 1 for w in words for k in range(width)]


def mode_message(compact: bool, layers: int, data_words: int) -> list[int]:
    if compact:
        v, nb, total = ((layers - 1) << 6) | (data_words - 1), 8, 7
    else:
        v, nb, total = ((layers - 1) << 11) | (data_words - 1), 16, 10
    words = [(v >> (nb - 4 * (k + 1))) & 0xF for k in range(nb // 4)]
    return _bits_of(words + rs_ecc(words, total - len(words), 4), 4)


def _candidates(symbol) -> tuple:
    key = symbol_key(symbol)
    if key == AUTO:
        return FORMATS_LIST
    return FORMATS_LIST[FORMATS_LIST.index(FORMATS[key]):]


def ecc_words_needed(total_words: int, ecc_percent: int = DEFAULT_ECC) -> int:
    """Minimum check words: ``ecc_percent`` of the symbol plus 3 (ISO/IEC 24778 recommendation)."""
    return -(-total_words * int(ecc_percent) // 100) + 3


def choose_format(bits: list[int], symbol=AUTO, ecc_percent: int = DEFAULT_ECC):
    """(format, stuffed data words) – the first candidate with room for data + check words."""
    stuffed: dict[int, list[int]] = {}
    for f in _candidates(symbol):
        if len(bits) > total_bits(f.layers, f.compact):
            continue
        w = f.word_size
        words = stuffed.setdefault(w, stuff_bits(bits, w))
        if f.compact and len(words) > 64:          # mode message holds 6 bits of length
            continue
        if len(words) + ecc_words_needed(f.words, ecc_percent) <= f.words:
            return f, words
    raise ValueError("Text zu lang für einen Aztec-Code (höchstens 151 × 151 Module) – "
                     "Text kürzen oder Fehlerkorrektur senken")


@dataclass(frozen=True)
class AztecCode:
    """Encoded symbol; ``modules[y][x]`` True = dark, origin top left (API of ``QrCode``)."""

    size: int
    compact: bool
    layers: int
    data_words: int
    modules: tuple[tuple[bool, ...], ...]

    @property
    def rows(self) -> int:
        return self.size

    @property
    def format(self) -> Format:
        return FORMATS.get(self.size) or Format(self.compact, self.layers)

    @property
    def ecc_words(self) -> int:
        return self.format.words - self.data_words

    def dark(self, x: int, y: int) -> bool:
        return 0 <= x < self.size and 0 <= y < self.size and self.modules[y][x]

    def runs(self, quiet_zone: int = 0, invert: bool = False) -> list[tuple[int, int, int]]:
        """Horizontal runs (row, start, end excl.) of the modules to laser incl. quiet zone."""
        q = max(0, int(quiet_zone))
        w = self.size + 2 * q
        out = []
        for y in range(w):
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


def build(f: Format, words: list[int]) -> AztecCode:
    """Symbol of format ``f`` from the stuffed data words (adds the check words)."""
    compact, layers, w = f.compact, f.layers, f.word_size
    tb = total_bits(layers, compact)
    n_total = tb // w
    cws = list(words) + rs_ecc(words, n_total - len(words), w)
    bits = [0] * (tb % w) + _bits_of(cws, w)
    base = (11 if compact else 14) + 4 * layers
    size = matrix_size(layers, compact)
    if compact:
        amap = list(range(base))
    else:
        amap = [0] * base
        oc, c = base // 2, size // 2
        for i in range(oc):
            off = i + i // 15
            amap[oc - i - 1] = c - off - 1
            amap[oc + i] = c + off + 1
    grid = [[False] * size for _ in range(size)]

    def put(x, y):
        grid[y][x] = True

    row_off = 0
    for i in range(layers):
        rs = (layers - i) * 4 + (9 if compact else 12)
        for j in range(rs):
            co = 2 * j
            for k in range(2):
                if bits[row_off + co + k]:
                    put(amap[2 * i + k], amap[2 * i + j])
                if bits[row_off + 2 * rs + co + k]:
                    put(amap[2 * i + j], amap[base - 1 - 2 * i - k])
                if bits[row_off + 4 * rs + co + k]:
                    put(amap[base - 1 - 2 * i - k], amap[base - 1 - 2 * i - j])
                if bits[row_off + 6 * rs + co + k]:
                    put(amap[base - 1 - 2 * i - j], amap[2 * i + k])
        row_off += 8 * rs
    # mode message around the finder
    mm = mode_message(compact, layers, len(words))
    c = size // 2
    if compact:
        for i in range(7):
            o = c - 3 + i
            if mm[i]:
                put(o, c - 5)
            if mm[i + 7]:
                put(c + 5, o)
            if mm[20 - i]:
                put(o, c + 5)
            if mm[27 - i]:
                put(c - 5, o)
    else:
        for i in range(10):
            o = c - 5 + i + i // 5
            if mm[i]:
                put(o, c - 7)
            if mm[i + 10]:
                put(c + 7, o)
            if mm[29 - i]:
                put(o, c + 7)
            if mm[39 - i]:
                put(c - 7, o)
    # bull's eye with orientation marks, reference grid (full symbols)
    eye = 5 if compact else 7
    for i in range(0, eye, 2):
        for j in range(c - i, c + i + 1):
            put(j, c - i)
            put(j, c + i)
            put(c - i, j)
            put(c + i, j)
    for x, y in ((c - eye, c - eye), (c - eye + 1, c - eye), (c - eye, c - eye + 1),
                 (c + eye, c - eye), (c + eye, c - eye + 1), (c + eye, c + eye - 1)):
        put(x, y)
    if not compact:
        i = j = 0
        while i < base // 2 - 1:
            for k in range(c & 1, size, 2):
                put(c - j, k)
                put(c + j, k)
                put(k, c - j)
                put(k, c + j)
            i += 15
            j += 16
    return AztecCode(size, compact, layers, len(words), tuple(tuple(r) for r in grid))


def encode(text: str, symbol=AUTO, ecc_percent: int = DEFAULT_ECC,
           gs1_mode: bool = False) -> AztecCode:
    """Encode ``text``: ``symbol`` 0 = smallest that fits, an edge = this size or larger."""
    if not text:
        raise ValueError("Kein Text für den Aztec-Code")
    bits = encode_bits(text, gs1_mode)
    f, words = choose_format(bits, symbol, ecc_percent)
    return build(f, words)


# --- Vector output ------------------------------------------------------------------

def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


@dataclass(frozen=True)
class AztecSpec:
    text: str = "LumaCut"
    symbol: int = AUTO          # edge of the minimum size, 0 = automatic
    ecc_percent: int = DEFAULT_ECC
    size_mm: float = 15.0       # edge without quiet zone
    quiet_zone: int = DEFAULT_QUIET
    invert: bool = False
    gs1: bool = False           # text is a GS1 element string "(01)…(10)…"
    x: float = 0.0              # top left corner incl. quiet zone
    y: float = 0.0

    def normalized(self) -> "AztecSpec":
        try:
            sym = symbol_key(self.symbol)
        except ValueError:
            sym = AUTO
        return AztecSpec(text=str(self.text or ""), symbol=sym,
                         ecc_percent=int(_clamp(int(self.ecc_percent), *ECC_RANGE)),
                         size_mm=float(_clamp(float(self.size_mm), *SIZE_RANGE)),
                         quiet_zone=int(_clamp(int(self.quiet_zone), *QUIET_RANGE)),
                         invert=bool(self.invert), gs1=bool(self.gs1),
                         x=float(self.x), y=float(self.y))

    def encode(self) -> AztecCode:
        s = self.normalized()
        return encode(s.text, s.symbol, s.ecc_percent, s.gs1)

    def module_mm(self, code: AztecCode) -> float:
        return self.normalized().size_mm / code.size

    def total(self, code: AztecCode) -> tuple[float, float]:
        s = self.normalized()
        t = s.size_mm / code.size * (code.size + 2 * s.quiet_zone)
        return t, t

    def total_mm(self, code: AztecCode) -> float:
        return self.total(code)[0]


def aztec_shapes(spec: AztecSpec, layer_id: str, code: AztecCode | None = None) -> list[Shape]:
    """Symbol as grouped ``polygon`` objects (one area per object, holes as rings).

    Raises ``ValueError`` for empty/too long text, too small modules or when the
    symbol incl. quiet zone does not fit on the work area.
    """
    s = spec.normalized()
    code = code or s.encode()
    module = s.size_mm / code.size
    if module < HARD_MIN_MODULE_MM:
        raise ValueError(f"Module {module:.2f} mm sind zu klein (mindestens "
                         f"{HARD_MIN_MODULE_MM:.1f} mm) – Code größer machen, Text kürzen oder "
                         "Fehlerkorrektur senken")
    tw, th = s.total(code)
    eps = 1e-6
    if (s.x < -eps or s.y < -eps or s.x + tw > WORK_WIDTH_MM + eps
            or s.y + th > WORK_HEIGHT_MM + eps):
        raise ValueError(
            f"Aztec-Code {tw:.1f} × {th:.1f} mm (inkl. Ruhezone) passt ab X {s.x:.1f} / "
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


def describe(code: AztecCode, size_mm: float) -> str:
    module = size_mm / code.size
    kind = "kompakt" if code.compact else "voll"
    ecc = 100.0 * code.ecc_words / max(1, code.format.words)
    return (f"{code.size} × {code.size} Module ({kind}, {code.layers} "
            f"Lage{'n' if code.layers > 1 else ''}, {code.data_words} Datenwörter, "
            f"Fehlerkorrektur {ecc:.0f} %), Modul {module:.2f} mm")


__all__ = ["AUTO", "AztecCode", "AztecSpec", "FORMATS", "SIZES", "aztec_shapes", "build",
           "choose_format", "describe", "encode", "encode_bits", "stuff_bits", "symbol_key"]
