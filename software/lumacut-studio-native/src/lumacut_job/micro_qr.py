"""Micro QR Code (ISO/IEC 18004, Versions M1–M4) as vector objects for engraving.

Pure-Python encoder, no extra dependency. Reuses Reed–Solomon helpers from
:mod:`lumacut_job.qr`. Modes: numeric, alphanumeric, byte (UTF-8). Kanji is not
implemented (Micro QR capacity is tiny; document that in the README).

Quiet zone default: 2 modules (ISO). Size is the edge length *without* quiet zone,
same convention as full QR. No ECI / FNC1 / structured append (not available in
Micro QR).
"""

from __future__ import annotations

from dataclasses import dataclass

from lumacut_canvas.model import Shape, new_id
from lumacut_canvas.workarea import WORK_HEIGHT_MM, WORK_WIDTH_MM

from . import qr as _qr

# Versions M1–M4 → side length in modules.
VERSIONS = (1, 2, 3, 4)
VERSION_SIZE = {1: 11, 2: 13, 3: 15, 4: 17}
# Error correction: D = detection only (M1); L/M/Q as in the ISO (no H).
EC_LEVELS = ("D", "L", "M", "Q")
EC_LABELS = {
    "D": "Erkennung (nur M1)",
    "L": "L (7 %)",
    "M": "M (15 %)",
    "Q": "Q (25 %)",
}
# EC levels available per version.
EC_FOR_VERSION = {1: ("D",), 2: ("L", "M"), 3: ("L", "M"), 4: ("L", "M", "Q")}
# Data-bit capacity (incl. mode + count; excl. terminator) and total / data codewords.
# From ISO/IEC 18004 Table 7 / Table 8 (and segno cross-check).
# (version, ec) → data capacity in bits.
DATA_BITS = {
    (1, "D"): 20,
    (2, "L"): 40, (2, "M"): 32,
    (3, "L"): 84, (3, "M"): 68,
    (4, "L"): 128, (4, "M"): 112, (4, "Q"): 80,
}
# (version, ec) → (total_codewords, data_codewords). Last data CW is 4 bits for M1/M3.
TOTAL_CW = {
    (1, "D"): (5, 3),
    (2, "L"): (10, 5), (2, "M"): (10, 4),
    (3, "L"): (17, 11), (3, "M"): (17, 9),
    (4, "L"): (24, 16), (4, "M"): (24, 14), (4, "Q"): (24, 10),
}
# Terminator length (zeros) per version.
_TERMINATOR = {1: 3, 2: 5, 3: 7, 4: 9}
# Mode indicator bit width (M1 has none).
_MODE_BITS = {1: 0, 2: 1, 3: 2, 4: 3}
# Character-count bits: mode → (M1, M2, M3, M4); None = not supported.
_COUNT_BITS = {
    "N": (3, 4, 5, 6),
    "A": (None, 3, 4, 5),
    "B": (None, None, 4, 5),
}
# Mode indicator values (fit in _MODE_BITS[ver] bits).
_MODE_IND = {"N": 0, "A": 1, "B": 2}

# Format information: 5-bit (symbol_number<<2 | mask) → 15-bit BCH word (ISO Table C.1 Micro).
# Symbol numbers: M1=0, M2-L=1, M2-M=2, M3-L=3, M3-M=4, M4-L=5, M4-M=6, M4-Q=7.
_SYMBOL_NUMBER = {
    (1, "D"): 0,
    (2, "L"): 1, (2, "M"): 2,
    (3, "L"): 3, (3, "M"): 4,
    (4, "L"): 5, (4, "M"): 6, (4, "Q"): 7,
}
_FORMAT_INFO = (
    0x4445, 0x4172, 0x4E2B, 0x4B1C, 0x55AE, 0x5099, 0x5FC0, 0x5AF7,
    0x6793, 0x62A4, 0x6DFD, 0x68CA, 0x7678, 0x734F, 0x7C16, 0x7921,
    0x06DE, 0x03E9, 0x0CB0, 0x0987, 0x1735, 0x1202, 0x1D5B, 0x186C,
    0x2508, 0x203F, 0x2F66, 0x2A51, 0x34E3, 0x31D4, 0x3E8D, 0x3BBA,
)

# Micro QR data masks (ISO Table 10) – subset of full-QR masks 1, 4, 6, 7.
# Arguments are (row, col) like the ISO / segno.
_MASKS = (
    lambda i, j: i % 2 == 0,
    lambda i, j: (i // 2 + j // 3) % 2 == 0,
    lambda i, j: (i * j % 2 + i * j % 3) % 2 == 0,
    lambda i, j: ((i + j) % 2 + i * j % 3) % 2 == 0,
)

MIN_MODULE_MM = _qr.MIN_MODULE_MM
HARD_MIN_MODULE_MM = _qr.HARD_MIN_MODULE_MM
SIZE_RANGE = (3.0, 340.0)       # Micro symbols are tiny; allow smaller edge
QUIET_RANGE = (0, 10)
DEFAULT_QUIET = 2
FILL_LAYER_NAME = "Micro-QR"
ALNUM_CHARS = _qr.ALNUM_CHARS
_ALNUM = _qr._ALNUM


def _check_ec(ec: str) -> str:
    ec = str(ec).upper()
    if ec not in EC_LEVELS:
        raise ValueError(f"Unbekannte Fehlerkorrektur „{ec}“ (D, L, M oder Q für Micro QR)")
    return ec


def _put(bits: list[int], value: int, n: int) -> None:
    bits.extend((value >> i) & 1 for i in range(n - 1, -1, -1))


def choose_mode(text: str) -> str:
    """Best single mode for ``text``: N / A / B (UTF-8)."""
    if text.isdigit():
        return "N"
    if all(c in _ALNUM for c in text):
        return "A"
    return "B"


def char_count(text: str, mode: str) -> int:
    if mode == "B":
        return len(text.encode("utf-8"))
    return len(text)


def data_bits_for(text: str, mode: str) -> list[int]:
    """Raw data bits for one segment (no mode / count / terminator)."""
    bits: list[int] = []
    if mode == "N":
        for i in range(0, len(text), 3):
            grp = text[i:i + 3]
            _put(bits, int(grp), (4, 7, 10)[len(grp) - 1])
    elif mode == "A":
        for i in range(0, len(text) - 1, 2):
            _put(bits, _ALNUM[text[i]] * 45 + _ALNUM[text[i + 1]], 11)
        if len(text) % 2:
            _put(bits, _ALNUM[text[-1]], 6)
    else:
        for b in text.encode("utf-8"):
            _put(bits, b, 8)
    return bits


def segment_bit_length(text: str, mode: str, ver: int) -> int:
    """Total bits of mode + count + data for ``ver`` (before terminator)."""
    mb = _MODE_BITS[ver]
    cb = _COUNT_BITS[mode][ver - 1]
    if cb is None:
        raise ValueError(f"Modus {mode} nicht in Version M{ver}")
    return mb + cb + len(data_bits_for(text, mode))


def capacity_bits(ver: int, ec: str) -> int:
    return DATA_BITS[(ver, _check_ec(ec))]


def fits(text: str, ver: int, ec: str, mode: str | None = None) -> bool:
    mode = mode or choose_mode(text)
    try:
        return segment_bit_length(text, mode, ver) <= capacity_bits(ver, ec)
    except ValueError:
        return False


def choose_version(text: str, ec: str, min_version: int = 1) -> tuple[int, str]:
    """Smallest (version, mode) that fits ``text`` at error level ``ec``."""
    ec = _check_ec(ec)
    mode = choose_mode(text)
    for ver in VERSIONS:
        if ver < max(1, int(min_version)):
            continue
        if ec not in EC_FOR_VERSION[ver]:
            continue
        if mode == "N" or (mode == "A" and ver >= 2) or (mode == "B" and ver >= 3):
            if fits(text, ver, ec, mode):
                return ver, mode
    raise ValueError(
        f"Text zu lang für Micro QR: bei Fehlerkorrektur {ec} passt er in keine Version M1–M4 "
        f"(höchstens M4) – kürzeren Text oder niedrigere Stufe wählen, oder normalen QR-Code nutzen")


@dataclass(frozen=True)
class MicroQrCode:
    version: int          # 1–4 (= M1–M4)
    ec: str
    mask: int
    modules: tuple[tuple[bool, ...], ...]

    @property
    def size(self) -> int:
        return len(self.modules)

    @property
    def version_name(self) -> str:
        return f"M{self.version}"

    def dark(self, x: int, y: int) -> bool:
        return 0 <= x < self.size and 0 <= y < self.size and self.modules[y][x]

    def runs(self, quiet_zone: int = 0, invert: bool = False) -> list[tuple[int, int, int]]:
        """Horizontal runs (row, start, end excl.) of modules to laser – same as :class:`qr.QrCode`."""
        q = max(0, int(quiet_zone))
        full = self.size + 2 * q
        out = []
        for y in range(full):
            x = 0
            while x < full:
                if self.dark(x - q, y - q) == invert:
                    x += 1
                    continue
                e = x
                while e < full and self.dark(e - q, y - q) != invert:
                    e += 1
                out.append((y, x, e))
                x = e
        return out


class _Builder:
    """Micro QR matrix: one finder, timing on row/col 0, format on row/col 8."""

    def __init__(self, ver: int, ec: str) -> None:
        self.ver, self.ec = ver, ec
        self.size = VERSION_SIZE[ver]
        # 0x2 = unset encoding region; False/True once placed.
        self.modules = [[0x2] * self.size for _ in range(self.size)]
        self.is_function = [[False] * self.size for _ in range(self.size)]

    def _set(self, x: int, y: int, dark: bool) -> None:
        self.modules[y][x] = bool(dark)
        self.is_function[y][x] = True

    def draw_function_patterns(self) -> None:
        n = self.size
        # Finder 7×7 (dark rings at Chebyshev d≠2) + 1-module light separator → 8×8.
        for dy in range(7):
            for dx in range(7):
                d = max(abs(dx - 3), abs(dy - 3))
                self._set(dx, dy, d != 2)
        for i in range(8):
            self._set(7, i, False)
            self._set(i, 7, False)
        # Timing patterns on row 0 and column 0 from index 8 onward.
        bit = True
        for i in range(8, n):
            self._set(i, 0, bit)
            self._set(0, i, bit)
            bit = not bit
        # Reserve format-information modules (row 8 / col 8); filled later.
        for i in range(8):
            self.modules[i + 1][8] = False
            self.is_function[i + 1][8] = True
            self.modules[8][i + 1] = False
            self.is_function[8][i + 1] = True

    def draw_format(self, mask: int) -> None:
        sn = _SYMBOL_NUMBER[(self.ver, self.ec)]
        bits = _FORMAT_INFO[(sn << 2) | mask]
        for i in range(8):
            vbit = (bits >> i) & 1
            hbit = (bits >> (14 - i)) & 1
            self._set(8, i + 1, bool(vbit))   # col 8, rows 1..8
            self._set(i + 1, 8, bool(hbit))   # row 8, cols 1..8

    def draw_codewords(self, bit_stream: list[int]) -> None:
        n = self.size
        idx = 0
        total = len(bit_stream)
        # M1/M3 start the zigzag as if shifted (ISO / segno ``inc = 2``).
        inc = 2 if self.ver in (1, 3) else 0
        for right in range(n - 1, 0, -2):
            for vertical in range(n):
                for z in range(2):
                    x = right - z
                    upwards = ((right + inc) & 2) == 0
                    y = (n - 1 - vertical) if upwards else vertical
                    if self.modules[y][x] == 0x2 and idx < total:
                        self.modules[y][x] = bool(bit_stream[idx])
                        idx += 1
        if idx != total:
            raise RuntimeError(f"Micro QR placement: wrote {idx}/{total} bits")

    def apply_mask(self, mask: int) -> None:
        f = _MASKS[mask]
        for y in range(self.size):
            for x in range(self.size):
                if not self.is_function[y][x] and f(y, x):
                    self.modules[y][x] = not self.modules[y][x]

    def micro_score(self) -> int:
        """Mask evaluation for Micro QR (ISO 7.8.3.2) – higher is better."""
        n = self.size
        m = self.modules
        sum1 = sum(1 for i in range(1, n) if m[i][n - 1])
        sum2 = sum(1 for i in range(1, n) if m[n - 1][i])
        return sum1 * 16 + sum2 if sum1 <= sum2 else sum2 * 16 + sum1


def _build_bit_stream(text: str, ver: int, ec: str, mode: str) -> list[int]:
    """Mode + count + data + terminator + pad to data capacity (bits)."""
    bits: list[int] = []
    mb = _MODE_BITS[ver]
    if mb:
        _put(bits, _MODE_IND[mode], mb)
    cb = _COUNT_BITS[mode][ver - 1]
    n = char_count(text, mode)
    if n >= 1 << cb:
        raise ValueError("Inhalt zu lang für die Micro-QR-Versionsklasse")
    _put(bits, n, cb)
    bits.extend(data_bits_for(text, mode))
    cap = capacity_bits(ver, ec)
    # Terminator
    bits.extend([0] * min(_TERMINATOR[ver], cap - len(bits)))
    # Pad to codeword boundary. M1/M3: final data codeword is 4 bits.
    if ver in (1, 3):
        # After terminator, pad with zeros up to the 4-bit-oriented capacity.
        bits.extend([0] * (cap - len(bits)))
    else:
        bits.extend([0] * ((-len(bits)) % 8))
        pad_bytes = ((0xEC, 0x11))
        i = 0
        while len(bits) < cap:
            b = pad_bytes[i % 2]
            _put(bits, b, 8)
            i += 1
    if len(bits) != cap:
        # Cap may not be multiple of 8 for M1/M3 – we padded with zeros already.
        if len(bits) > cap:
            bits = bits[:cap]
        else:
            bits.extend([0] * (cap - len(bits)))
    return bits


def _message_bits(text: str, ver: int, ec: str, mode: str) -> list[int]:
    """Final bit stream incl. Reed–Solomon ECC codewords."""
    data_bits = _build_bit_stream(text, ver, ec, mode)
    total_cw, data_cw = TOTAL_CW[(ver, ec)]
    ecc_cw = total_cw - data_cw
    # Pack data bits into codewords; M1/M3 last data CW is 4 bits (high nibble).
    codewords: list[int] = []
    if ver in (1, 3):
        # data_cw-1 full bytes + one 4-bit nibble stored in high half for RS.
        full = data_cw - 1
        for i in range(full):
            v = 0
            for b in data_bits[i * 8:(i + 1) * 8]:
                v = (v << 1) | b
            codewords.append(v)
        nib = 0
        for b in data_bits[full * 8:full * 8 + 4]:
            nib = (nib << 1) | b
        codewords.append(nib << 4)   # low nibble 0000 for RS, as per ISO
    else:
        for i in range(0, len(data_bits), 8):
            v = 0
            for b in data_bits[i:i + 8]:
                v = (v << 1) | b
            codewords.append(v)
    assert len(codewords) == data_cw
    rem = _qr.rs_remainder(codewords, _qr.rs_divisor(ecc_cw))
    # Emit bits: for M1/M3 the last data CW contributes only 4 bits.
    out: list[int] = []
    if ver in (1, 3):
        for cw in codewords[:-1]:
            _put(out, cw, 8)
        _put(out, codewords[-1] >> 4, 4)
    else:
        for cw in codewords:
            _put(out, cw, 8)
    for cw in rem:
        _put(out, cw, 8)
    return out


def encode(text: str, ec: str = "L", min_version: int = 1,
           mask: int | None = None) -> MicroQrCode:
    """Encode ``text`` as Micro QR (auto version). ``mask`` None = best of 0–3."""
    text = text or ""
    if not text:
        raise ValueError("Kein Text für den Micro-QR-Code")
    ec = _check_ec(ec)
    ver, mode = choose_version(text, ec, min_version)
    return _encode_at(text, ver, ec, mode, mask)


def encode_at(text: str, ver: int, ec: str, mask: int | None = None) -> MicroQrCode:
    """Encode at a fixed version (raises if it does not fit)."""
    text = text or ""
    if not text:
        raise ValueError("Kein Text für den Micro-QR-Code")
    ver = int(ver)
    if ver not in VERSIONS:
        raise ValueError("Micro-QR-Version M1–M4")
    ec = _check_ec(ec)
    if ec not in EC_FOR_VERSION[ver]:
        raise ValueError(f"Fehlerkorrektur {ec} nicht für Version M{ver}")
    mode = choose_mode(text)
    if not fits(text, ver, ec, mode):
        raise ValueError(f"Text passt nicht in Micro QR M{ver} / {ec}")
    return _encode_at(text, ver, ec, mode, mask)


def _encode_at(text: str, ver: int, ec: str, mode: str,
               mask: int | None) -> MicroQrCode:
    stream = _message_bits(text, ver, ec, mode)
    b = _Builder(ver, ec)
    b.draw_function_patterns()
    b.draw_codewords(stream)
    if mask is None:
        best, best_s = 0, -1
        for m in range(4):
            b.apply_mask(m)
            s = b.micro_score()
            if s > best_s:
                best, best_s = m, s
            b.apply_mask(m)  # XOR undo
        mask = best
    elif not 0 <= int(mask) < 4:
        raise ValueError("Micro-QR-Maske 0–3")
    b.apply_mask(int(mask))
    b.draw_format(int(mask))
    modules = tuple(tuple(bool(c) for c in row) for row in b.modules)
    return MicroQrCode(ver, ec, int(mask), modules)


def describe(code: MicroQrCode, size_mm: float) -> str:
    module = size_mm / code.size
    return (f"Version {code.version_name} ({code.size}×{code.size} Module), Maske {code.mask}, "
            f"Modul {module:.2f} mm")


# --- Canvas (mirrors qr.qr_shapes) ---------------------------------------------
def micro_qr_shapes(spec, layer_id: str, code: MicroQrCode | None = None) -> list[Shape]:
    """Micro QR as grouped ``polygon`` objects. ``spec`` is a :class:`qr.QrSpec` with mode micro."""
    from .qr import qr_regions  # same geometry helper (duck-typed .runs)

    s = spec.normalized()
    code = code or encode(s.text, s.ec if s.ec in EC_LEVELS else "L")
    module = s.size_mm / code.size
    if module < HARD_MIN_MODULE_MM:
        raise ValueError(
            f"Module {module:.2f} mm sind zu klein (mindestens {HARD_MIN_MODULE_MM:.1f} mm) – "
            "Code größer machen oder Text kürzen")
    total = module * (code.size + 2 * s.quiet_zone)
    eps = 1e-6
    if (s.x < -eps or s.y < -eps
            or s.x + total > WORK_WIDTH_MM + eps or s.y + total > WORK_HEIGHT_MM + eps):
        raise ValueError(
            f"Micro-QR-Code {total:.1f} × {total:.1f} mm (inkl. Ruhezone) passt ab "
            f"X {s.x:.1f} / Y {s.y:.1f} nicht auf die Arbeitsfläche "
            f"({WORK_WIDTH_MM:.0f} × {WORK_HEIGHT_MM:.0f} mm)")
    group = new_id()
    out = []
    for outer, holes in qr_regions(code, module, s.quiet_zone, s.invert, (s.x, s.y)):
        pts = list(outer)
        rings = []
        for h in holes:
            rings.append(len(pts))
            pts.extend(h)
        sh = Shape.from_points("polygon", pts, layer_id, rings=rings)
        sh.groups = (group,)
        out.append(sh)
    return out


__all__ = [
    "DEFAULT_QUIET", "FILL_LAYER_NAME", "EC_FOR_VERSION", "EC_LABELS", "EC_LEVELS", "HARD_MIN_MODULE_MM",
    "MIN_MODULE_MM", "QUIET_RANGE", "SIZE_RANGE", "VERSIONS", "VERSION_SIZE",
    "MicroQrCode", "capacity_bits", "choose_mode", "choose_version", "describe",
    "encode", "encode_at", "fits", "micro_qr_shapes",
]
