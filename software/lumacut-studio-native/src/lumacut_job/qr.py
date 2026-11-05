"""QR-Code (ISO/IEC 18004) als Vektorobjekte für die Gravur – ohne Fremdpaket.

Reiner Python-Encoder (Byte-Modus UTF-8 bzw. gemischte Segmente), Versionen 1–40, Fehlerkorrektur
L/M/Q/H, automatische Maskenwahl nach den Strafpunkten der Norm. Portiert
und erweitert aus ``android/core/.../Qr.kt`` (dort nur Stufe M, Version 1–10).
Qt-frei; die Flächen werden mit shapely zu geschlossenen Polygonen
verschmolzen, damit Füllen/Schraffur keine inneren Kanten doppelt lasert.

Größe ``size_mm`` ist die Kantenlänge des Codes *ohne* Ruhezone. Die Ruhezone
(``quiet_zone`` Module, Norm: 4) ist ein heller Rand: normal wird sie nur
freigehalten (Position X/Y = linke obere Ecke inkl. Ruhezone), invertiert
(für Materialien, die beim Lasern *hell* werden, z. B. eloxiertes Alu,
Schiefer) wird sie zusammen mit den hellen Modulen graviert.

Micro QR (``QrSpec.mode`` ``"micro"``): ISO/IEC 18004 Micro QR M1–M4
(:mod:`lumacut_job.micro_qr`) – kleines Symbol für Bauteilkennzeichnung; Ruhezone
Standard 2 Module; Fehlerkorrektur D (nur M1, Erkennung) / L / M / Q; kein ECI,
kein Kanji. Siehe :mod:`lumacut_job.micro_qr`.

GS1 (``QrSpec.mode``): ``"gs1"`` kodiert einen GS1-Elementstring „(01)…(10)…“ als
GS1 QR-Code (Modusindikator „FNC1 an erster Stelle“, FNC1-Trenner als „%“ im
alphanumerischen bzw. GS im Byte-Modus), ``"link"`` eine GS1-Digital-Link-Adresse
(:mod:`lumacut_job.gs1_link`). Beide nutzen gemischte Segmente (numerisch /
alphanumerisch / Byte, kürzeste Bitfolge).

Text-Modus (:func:`encode_text`, ``QrSpec.encode``): ebenfalls gemischte Segmente
(Ziffernfolgen numerisch, GROSSBUCHSTABEN/Ziffern/„ $%*+-./:“ alphanumerisch, Rest
Byte), aber nur, wenn das eine *kleinere Version* ergibt als ein einziges
Byte-Segment – sonst bleibt die Matrix bitgleich zum bisherigen Byte-Segment
(:func:`encode`), damit bestehende Codes beim Bearbeiten nicht ohne Gewinn
anders aussehen.

Nicht-ASCII-Text (Umlaute, „°“, „€“, Emoji …): mit ``QrSpec.eci`` (Standard für neue Codes)
steht vor den Daten die Zeichensatz-Kennung ECI 26 (UTF-8, ISO/IEC 18004 7.4.2), so dass
Handys und Scanner den Text nicht raten müssen; dann sind auch gemischte Segmente sicher.
Japanischer Text (Kana/Kanji, alle Nicht-ASCII-Zeichen in Shift JIS) nutzt stattdessen den
Kanji-Modus (13 Bit je Zeichen statt 24 Bit UTF-8, ohne ECI – den Kanji-Modus lesen Scanner
immer als Shift JIS). Ohne ``eci`` (ältere Dokumente) bleibt Nicht-ASCII-Text wie bisher ein
Byte-Segment ohne Kennung (bitgleich).
"""

from __future__ import annotations

from dataclasses import dataclass

from lumacut_canvas.model import Shape, new_id
from lumacut_canvas.workarea import WORK_HEIGHT_MM, WORK_WIDTH_MM

from . import gs1, gs1_link

EC_LEVELS = ("L", "M", "Q", "H")
EC_LABELS = {"L": "L (7 %)", "M": "M (15 %)", "Q": "Q (25 %)", "H": "H (30 %)"}
MIN_VERSION, MAX_VERSION = 1, 40
# Kleinste Modulkante, die graviert noch zuverlässig gelesen wird (wie Android).
MIN_MODULE_MM = 0.8
# Darunter wird nicht erzeugt (Laserfleck ≈ 0,1 mm, Linienabstand ≈ 0,1 mm).
HARD_MIN_MODULE_MM = 0.2
SIZE_RANGE = (5.0, 340.0)        # mm, Kantenlänge des Codes
QUIET_RANGE = (0, 10)            # Module
MODES = ("text", "gs1", "link", "micro")
MODE_LABELS = {"text": "Text / Adresse", "gs1": "GS1 QR-Code (Elementstring)",
               "link": "GS1 Digital Link (Web-Adresse)",
               "micro": "Micro QR (klein, M1–M4)"}

# Format-Bits je Stufe (Tabelle 12 der Norm).
_FORMAT_BITS = {"L": 1, "M": 0, "Q": 3, "H": 2}

# Fehlerkorrektur-Codewörter je Block und Anzahl Blöcke (Index = Version).
_ECC_PER_BLOCK = {
    "L": (-1, 7, 10, 15, 20, 26, 18, 20, 24, 30, 18, 20, 24, 26, 30, 22, 24, 28, 30, 28, 28,
          28, 28, 30, 30, 26, 28, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30),
    "M": (-1, 10, 16, 26, 18, 24, 16, 18, 22, 22, 26, 30, 22, 22, 24, 24, 28, 28, 26, 26, 26,
          26, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28),
    "Q": (-1, 13, 22, 18, 26, 18, 24, 18, 22, 20, 24, 28, 26, 24, 20, 30, 24, 28, 28, 26, 30,
          28, 30, 30, 30, 30, 28, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30),
    "H": (-1, 17, 28, 22, 16, 22, 28, 26, 26, 24, 28, 24, 28, 22, 24, 24, 30, 28, 28, 26, 28,
          30, 24, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30),
}
_NUM_BLOCKS = {
    "L": (-1, 1, 1, 1, 1, 1, 2, 2, 2, 2, 4, 4, 4, 4, 4, 6, 6, 6, 6, 7, 8, 8, 9, 9, 10, 12,
          12, 12, 13, 14, 15, 16, 17, 18, 19, 19, 20, 21, 22, 24, 25),
    "M": (-1, 1, 1, 1, 2, 2, 4, 4, 4, 5, 5, 5, 8, 9, 9, 10, 10, 11, 13, 14, 16, 17, 17, 18,
          20, 21, 23, 25, 26, 28, 29, 31, 33, 35, 37, 38, 40, 43, 45, 47, 49),
    "Q": (-1, 1, 1, 2, 2, 4, 4, 6, 6, 8, 8, 8, 10, 12, 16, 12, 17, 16, 18, 21, 20, 23, 23,
          25, 27, 29, 34, 34, 35, 38, 40, 43, 45, 48, 51, 53, 56, 59, 62, 65, 68),
    "H": (-1, 1, 1, 2, 4, 4, 4, 5, 6, 8, 8, 11, 11, 16, 16, 18, 16, 19, 21, 25, 25, 25, 34,
          30, 32, 35, 37, 40, 42, 45, 48, 51, 54, 57, 60, 63, 66, 70, 74, 77, 81),
}


def _check_level(ec: str) -> str:
    ec = str(ec).upper()
    if ec not in EC_LEVELS:
        raise ValueError(f"Unbekannte Fehlerkorrektur „{ec}“ (L, M, Q oder H)")
    return ec


def raw_modules(ver: int) -> int:
    """Datenmodule (inkl. Rest-Bits) einer Version ohne Funktionsmuster."""
    result = (16 * ver + 128) * ver + 64
    if ver >= 2:
        align = ver // 7 + 2
        result -= (25 * align - 10) * align - 55
        if ver >= 7:
            result -= 36
    return result


def data_codewords(ver: int, ec: str) -> int:
    ec = _check_level(ec)
    return raw_modules(ver) // 8 - _ECC_PER_BLOCK[ec][ver] * _NUM_BLOCKS[ec][ver]


def capacity(ver: int, ec: str = "M") -> int:
    """Bytes (UTF-8), die im Byte-Modus in ``ver`` bei Stufe ``ec`` passen."""
    count_bits = 8 if ver < 10 else 16
    return (data_codewords(ver, ec) * 8 - 4 - count_bits) // 8


# --- Reed-Solomon über GF(256), Polynom 0x11D -----------------------------------
def _rs_mul(x: int, y: int) -> int:
    z = 0
    for i in range(7, -1, -1):
        z = ((z << 1) ^ ((z >> 7) * 0x11D)) & 0xFF
        z ^= ((y >> i) & 1) * x
    return z


def rs_divisor(degree: int) -> list[int]:
    result = [0] * degree
    result[-1] = 1
    root = 1
    for _ in range(degree):
        for j in range(degree):
            result[j] = _rs_mul(result[j], root)
            if j + 1 < degree:
                result[j] ^= result[j + 1]
        root = _rs_mul(root, 0x02)
    return result


def rs_remainder(data, divisor: list[int]) -> list[int]:
    result = [0] * len(divisor)
    for b in data:
        factor = b ^ result.pop(0)
        result.append(0)
        for i, coef in enumerate(divisor):
            result[i] ^= _rs_mul(coef, factor)
    return result


# --- Matrix ------------------------------------------------------------------------
_MASKS = (
    lambda x, y: (x + y) % 2 == 0,
    lambda x, y: y % 2 == 0,
    lambda x, y: x % 3 == 0,
    lambda x, y: (x + y) % 3 == 0,
    lambda x, y: (x // 3 + y // 2) % 2 == 0,
    lambda x, y: x * y % 2 + x * y % 3 == 0,
    lambda x, y: (x * y % 2 + x * y % 3) % 2 == 0,
    lambda x, y: ((x + y) % 2 + x * y % 3) % 2 == 0,
)


def mask_bit(mask: int, x: int, y: int) -> bool:
    return _MASKS[mask](x, y)


def alignment_positions(ver: int) -> list[int]:
    if ver == 1:
        return []
    n = ver // 7 + 2
    step = 26 if ver == 32 else (ver * 4 + n * 2 + 1) // (n * 2 - 2) * 2
    size = ver * 4 + 17
    return [6] + [size - 7 - i * step for i in range(n - 2, -1, -1)]


class _Builder:
    def __init__(self, ver: int, ec: str) -> None:
        self.ver, self.ec = ver, ec
        self.size = ver * 4 + 17
        self.modules = [[False] * self.size for _ in range(self.size)]
        self.is_function = [[False] * self.size for _ in range(self.size)]

    def _set(self, x: int, y: int, dark: bool) -> None:
        self.modules[y][x] = dark
        self.is_function[y][x] = True

    def draw_function_patterns(self) -> None:
        n = self.size
        for i in range(n):
            self._set(6, i, i % 2 == 0)
            self._set(i, 6, i % 2 == 0)
        for cx, cy in ((3, 3), (n - 4, 3), (3, n - 4)):
            for dy in range(-4, 5):
                for dx in range(-4, 5):
                    x, y = cx + dx, cy + dy
                    if 0 <= x < n and 0 <= y < n:
                        d = max(abs(dx), abs(dy))
                        self._set(x, y, d not in (2, 4))
        pos = alignment_positions(self.ver)
        last = len(pos) - 1
        for i, ax in enumerate(pos):
            for j, ay in enumerate(pos):
                if (i, j) in ((0, 0), (0, last), (last, 0)):
                    continue
                for dy in range(-2, 3):
                    for dx in range(-2, 3):
                        self._set(ax + dx, ay + dy, max(abs(dx), abs(dy)) != 1)
        self.draw_format(0)
        self._draw_version()

    def draw_format(self, mask: int) -> None:
        n = self.size
        data = (_FORMAT_BITS[self.ec] << 3) | mask
        rem = data
        for _ in range(10):
            rem = (rem << 1) ^ ((rem >> 9) * 0x537)
        bits = ((data << 10) | rem) ^ 0x5412

        def bit(i):
            return (bits >> i) & 1 == 1
        for i in range(6):
            self._set(8, i, bit(i))
        self._set(8, 7, bit(6))
        self._set(8, 8, bit(7))
        self._set(7, 8, bit(8))
        for i in range(9, 15):
            self._set(14 - i, 8, bit(i))
        for i in range(8):
            self._set(n - 1 - i, 8, bit(i))
        for i in range(8, 15):
            self._set(8, n - 15 + i, bit(i))
        self._set(8, n - 8, True)

    def _draw_version(self) -> None:
        if self.ver < 7:
            return
        rem = self.ver
        for _ in range(12):
            rem = (rem << 1) ^ ((rem >> 11) * 0x1F25)
        bits = (self.ver << 12) | rem
        for i in range(18):
            dark = (bits >> i) & 1 == 1
            a, b = self.size - 11 + i % 3, i // 3
            self._set(a, b, dark)
            self._set(b, a, dark)

    def draw_codewords(self, data: bytes) -> None:
        n = self.size
        i = 0
        total = len(data) * 8
        right = n - 1
        while right >= 1:
            if right == 6:
                right = 5
            upward = ((right + 1) & 2) == 0
            for vert in range(n):
                y = n - 1 - vert if upward else vert
                for j in range(2):
                    x = right - j
                    if not self.is_function[y][x] and i < total:
                        self.modules[y][x] = (data[i >> 3] >> (7 - (i & 7))) & 1 == 1
                        i += 1
            right -= 2

    def apply_mask(self, mask: int) -> None:
        f = _MASKS[mask]
        for y in range(self.size):
            row, fn = self.modules[y], self.is_function[y]
            for x in range(self.size):
                if not fn[x] and f(x, y):
                    row[x] = not row[x]

    def penalty(self) -> int:
        """Strafpunkte N1–N4 (ISO/IEC 18004, 7.8.3) des ganzen Symbols inkl. Formatinfo.

        Wie die Referenz-Implementierung von Project Nayuki: Muster 1:1:3:1:1
        mit 4 hellen Modulen davor/danach, außerhalb des Symbols gilt hell.
        """
        n = self.size
        m = self.modules
        result = 0

        def add_history(run: int, hist: list[int]) -> None:
            if hist[0] == 0:
                run += n          # heller Rand vor dem ersten Lauf
            hist.pop()
            hist.insert(0, run)

        def count_patterns(h: list[int]) -> int:
            c = h[1]
            core = c > 0 and h[2] == h[4] == h[5] == c and h[3] == c * 3
            return (int(core and h[0] >= c * 4 and h[6] >= c)
                    + int(core and h[6] >= c * 4 and h[0] >= c))

        def line_penalty(line) -> int:
            score = 0
            color, run, hist = False, 0, [0] * 7
            for v in line:
                if v == color:
                    run += 1
                    if run == 5:
                        score += 3
                    elif run > 5:
                        score += 1
                else:
                    add_history(run, hist)
                    if not color:
                        score += count_patterns(hist) * 40
                    color, run = v, 1
            if color:                 # letzten dunklen Lauf abschließen
                add_history(run, hist)
                run = 0
            add_history(run + n, hist)  # heller Rand nach dem letzten Lauf
            return score + count_patterns(hist) * 40

        for y in range(n):
            result += line_penalty(m[y])
        for x in range(n):
            result += line_penalty([m[y][x] for y in range(n)])
        for y in range(n - 1):
            r0, r1 = m[y], m[y + 1]
            for x in range(n - 1):
                if r0[x] == r0[x + 1] == r1[x] == r1[x + 1]:
                    result += 3
        dark = sum(sum(row) for row in m)
        total = n * n
        k = (abs(dark * 20 - total * 10) + total - 1) // total - 1
        return result + k * 10


@dataclass(frozen=True)
class QrCode:
    version: int
    ec: str
    mask: int
    modules: tuple[tuple[bool, ...], ...]

    @property
    def size(self) -> int:
        return len(self.modules)

    def dark(self, x: int, y: int) -> bool:
        return 0 <= x < self.size and 0 <= y < self.size and self.modules[y][x]

    def runs(self, quiet_zone: int = 0, invert: bool = False) -> list[tuple[int, int, int]]:
        """Waagerechte Läufe (Zeile, Start, Ende exkl.) der zu lasernden Module.

        Koordinaten in Modulen, Ursprung links oben inkl. Ruhezone. Invertiert:
        helle Module plus Ruhezone.
        """
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


def choose_version(n_bytes: int, ec: str, min_version: int = MIN_VERSION) -> int:
    ec = _check_level(ec)
    for v in range(max(MIN_VERSION, int(min_version)), MAX_VERSION + 1):
        if n_bytes <= capacity(v, ec):
            return v
    raise ValueError(f"Text zu lang für den QR-Code: {n_bytes} Bytes, bei Fehlerkorrektur {ec} "
                     f"höchstens {capacity(MAX_VERSION, ec)} – kürzeren Text oder Stufe L wählen")


def _bits_to_code(ver: int, ec: str, bits: list[int], mask: int | None) -> QrCode:
    """Terminator, Auffüllen, Reed-Solomon, Matrix und Maske für fertige Datenbits."""
    cap_bits = data_codewords(ver, ec) * 8
    bits = list(bits)
    bits += [0] * min(4, cap_bits - len(bits))
    bits += [0] * ((-len(bits)) % 8)
    pad = 0xEC
    while len(bits) < cap_bits:
        bits += [(pad >> i) & 1 for i in range(7, -1, -1)]
        pad ^= 0xEC ^ 0x11
    words = bytes(int("".join(map(str, bits[i:i + 8])), 2) for i in range(0, len(bits), 8))
    b = _Builder(ver, ec)
    b.draw_function_patterns()
    b.draw_codewords(_interleave(ver, ec, words))
    if mask is None:
        best, best_p = 0, None
        for m in range(8):
            b.apply_mask(m)
            b.draw_format(m)
            p = b.penalty()
            if best_p is None or p < best_p:
                best, best_p = m, p
            b.apply_mask(m)  # XOR: rückgängig
        mask = best
    elif not 0 <= int(mask) < 8:
        raise ValueError("Maske 0–7")
    b.apply_mask(int(mask))
    b.draw_format(int(mask))
    return QrCode(ver, ec, int(mask), tuple(tuple(r) for r in b.modules))


def _put(bits: list[int], value: int, n: int) -> None:
    bits.extend((value >> i) & 1 for i in range(n - 1, -1, -1))


def encode(text: str, ec: str = "M", min_version: int = MIN_VERSION, mask: int | None = None) -> QrCode:
    """Text (UTF-8, Byte-Modus) als QR-Code. ``mask`` None = beste Maske."""
    ec = _check_level(ec)
    data = (text or "").encode("utf-8")
    if not data:
        raise ValueError("Kein Text für den QR-Code")
    ver = choose_version(len(data), ec, min_version)
    bits: list[int] = []
    _put(bits, 0b0100, 4)
    _put(bits, len(data), 8 if ver < 10 else 16)
    for b in data:
        _put(bits, b, 8)
    return _bits_to_code(ver, ec, bits, mask)


# --- Gemischte Segmente (numerisch / alphanumerisch / Byte), GS1 ----------------------
ALNUM_CHARS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ $%*+-./:"
_ALNUM = {c: i for i, c in enumerate(ALNUM_CHARS)}
_MODE_IND = {"N": 0b0001, "A": 0b0010, "B": 0b0100, "K": 0b1000}
_COUNT_BITS = {"N": (10, 12, 14), "A": (9, 11, 13), "B": (8, 16, 16), "K": (8, 10, 12)}
FNC1_FIRST = 0b0101
GS = 0x1D
ECI_MODE = 0b0111
ECI_UTF8 = 26                  # ECI-Kennung UTF-8 (AIM ECI-Register)
# Kanji-Zeichen als Eingabe-Element: KANJI_BASE + 13-Bit-Wert (über Byte 0–255 und gs1.FNC1).
KANJI_BASE = 0x10000


def kanji_value(ch: str) -> int | None:
    """13-Bit-Wert eines Zeichens im QR-Kanji-Modus (Shift JIS 0x8140–0x9FFC, 0xE040–0xEBBF)."""
    try:
        b = ch.encode("shift_jis")
    except (UnicodeEncodeError, LookupError):
        return None
    if len(b) != 2:
        return None
    code = (b[0] << 8) | b[1]
    if 0x8140 <= code <= 0x9FFC:
        code -= 0x8140
    elif 0xE040 <= code <= 0xEBBF:
        code -= 0xC140
    else:
        return None
    return (code >> 8) * 0xC0 + (code & 0xFF)


def _is_japanese(ch: str) -> bool:
    o = ord(ch)
    return (0x3040 <= o <= 0x30FF or 0x3400 <= o <= 0x4DBF or 0x4E00 <= o <= 0x9FFF
            or 0xF900 <= o <= 0xFAFF)


def eci_bits(designator: int) -> list[int]:
    """ECI-Kopf (Modus 0111 + Kennung, 1–3 Bytes je nach Größe)."""
    bits: list[int] = []
    _put(bits, ECI_MODE, 4)
    if designator < 0x80:
        _put(bits, designator, 8)
    elif designator < 0x4000:
        _put(bits, 0b10 << 14 | designator, 16)
    elif designator < 1000000:
        _put(bits, 0b110 << 21 | designator, 24)
    else:
        raise ValueError("ECI-Kennung zu groß")
    return bits


def _version_class(ver: int) -> int:
    return 0 if ver <= 9 else (1 if ver <= 26 else 2)


def _units(item: int, mode: str, gs1_mode: bool):
    """Zeichen eines Eingabe-Elements (Byte 0–255 oder ``gs1.FNC1``) in ``mode``; None = nicht darstellbar.

    GS1: FNC1 ist im alphanumerischen Modus „%“, ein echtes „%“ wird „%%“; im Byte-Modus ist
    FNC1 das Steuerzeichen GS (0x1D).
    """
    if item >= KANJI_BASE:
        return (item - KANJI_BASE,) if mode == "K" else None
    if mode == "K":
        return None
    if item == gs1.FNC1:
        return ("%",) if mode == "A" else ((GS,) if mode == "B" else None)
    if mode == "B":
        return (item,)
    c = chr(item)
    if mode == "N":
        return (c,) if "0" <= c <= "9" else None
    if c not in _ALNUM:
        return None
    return ("%", "%") if c == "%" and gs1_mode else (c,)


def segments(items: list[int], ver: int, gs1_mode: bool = False) -> list[tuple[str, list]]:
    """Kürzeste Segmentfolge [(Modus, Zeichen)] für die Versionsklasse von ``ver``.

    Dynamische Programmierung über die Modi mit Kosten in 1/6 Bit (numerisch 10/3,
    alphanumerisch 11/2, Byte 8, Kanji 13 Bit je Zeichen, Kopf 4 + Zählerbits je Segment) – wie
    der Segment-Optimierer der Referenz-Implementierung von Project Nayuki. Den Kanji-Modus gibt
    es nur für Elemente ab ``KANJI_BASE`` (die nur dort darstellbar sind).
    """
    if not items:
        return []
    cls = _version_class(ver)
    modes = ("N", "A", "B", "K") if any(it >= KANJI_BASE for it in items) else ("N", "A", "B")
    unit_cost = {"N": 20, "A": 33, "B": 48, "K": 78}
    head = {m: (4 + _COUNT_BITS[m][cls]) * 6 for m in modes}
    inf = float("inf")
    cost = {m: inf for m in modes}
    back: list[dict] = []
    for k, item in enumerate(items):
        new, prev = {}, {}
        for m in modes:
            u = _units(item, m, gs1_mode)
            if u is None:
                new[m] = inf
                prev[m] = None
                continue
            c = unit_cost[m] * len(u)
            if k == 0:
                new[m], prev[m] = head[m] + c, None
                continue
            best, arg = cost[m], m
            for m2 in modes:
                if cost[m2] + head[m] < best:
                    best, arg = cost[m2] + head[m], m2
            new[m], prev[m] = best + c, arg
        back.append(prev)
        cost = new
    mode = min(modes, key=lambda m: cost[m])
    chosen = []
    for k in range(len(items) - 1, -1, -1):
        chosen.append(mode)
        mode = back[k][mode] or mode
    chosen.reverse()
    out: list[tuple[str, list]] = []
    for item, m in zip(items, chosen):
        u = list(_units(item, m, gs1_mode))
        if out and out[-1][0] == m:
            out[-1][1].extend(u)
        else:
            out.append((m, u))
    return out


def segment_bits(segs: list[tuple[str, list]], ver: int, fnc1_first: bool = False,
                 eci: int | None = None) -> list[int]:
    cls = _version_class(ver)
    bits: list[int] = eci_bits(eci) if eci is not None else []
    if fnc1_first:
        _put(bits, FNC1_FIRST, 4)
    for mode, chars in segs:
        n = len(chars)
        if n >= 1 << _COUNT_BITS[mode][cls]:
            raise ValueError("Segment zu lang")
        _put(bits, _MODE_IND[mode], 4)
        _put(bits, n, _COUNT_BITS[mode][cls])
        if mode == "N":
            for i in range(0, n, 3):
                grp = "".join(chars[i:i + 3])
                _put(bits, int(grp), (4, 7, 10)[len(grp) - 1])
        elif mode == "A":
            for i in range(0, n - 1, 2):
                _put(bits, _ALNUM[chars[i]] * 45 + _ALNUM[chars[i + 1]], 11)
            if n % 2:
                _put(bits, _ALNUM[chars[-1]], 6)
        elif mode == "K":
            for v in chars:
                _put(bits, v, 13)
        else:
            for b in chars:
                _put(bits, b, 8)
    return bits


def mixed_bits(items: list[int], ec: str = "M", fnc1_first: bool = False,
               min_version: int = MIN_VERSION, eci: int | None = None) -> tuple[int, list[int]]:
    """Kleinste Version und Datenbits mit optimalen Segmenten (ohne Terminator/Auffüllen).

    ``eci``: Zeichensatz-Kennung (z. B. :data:`ECI_UTF8`) vor den Segmenten."""
    ec = _check_level(ec)
    items = list(items)
    if not items:
        raise ValueError("Kein Inhalt für den QR-Code")
    if gs1.FNC1 in items and not fnc1_first:
        raise ValueError("FNC1 nur im GS1-Modus")
    best_bits = None
    for v in range(max(MIN_VERSION, int(min_version)), MAX_VERSION + 1):
        try:
            bits = segment_bits(segments(items, v, fnc1_first), v, fnc1_first, eci)
        except ValueError:
            continue
        best_bits = bits if best_bits is None or len(bits) < len(best_bits) else best_bits
        if len(bits) <= data_codewords(v, ec) * 8:
            return v, bits
    need = (len(best_bits) + 7) // 8 if best_bits else 0
    raise ValueError(f"Inhalt zu lang für den QR-Code: {need} Datenbytes, bei Fehlerkorrektur {ec} "
                     f"höchstens {data_codewords(MAX_VERSION, ec)} – kürzer fassen oder Stufe L wählen")


def encode_items(items: list[int], ec: str = "M", fnc1_first: bool = False,
                 min_version: int = MIN_VERSION, mask: int | None = None) -> QrCode:
    """Bytes (0–255) und ``gs1.FNC1`` mit optimalen Segmenten; ``fnc1_first`` = GS1 QR-Code."""
    ec = _check_level(ec)
    ver, bits = mixed_bits(items, ec, fnc1_first, min_version)
    return _bits_to_code(ver, ec, bits, mask)


TEXT_CHARSETS = ("ascii", "bytes", "eci", "kanji")


def text_charset(text: str, eci: bool = False) -> str:
    """Wie :func:`encode_text` ``text`` kodiert.

    ``"ascii"`` (nur ASCII: numerisch / alphanumerisch / Byte wie bisher), ``"bytes"``
    (Nicht-ASCII ohne ``eci``: ein Byte-Segment UTF-8 ohne Kennung, bisheriges Verhalten),
    ``"kanji"`` (japanischer Text, alle Nicht-ASCII-Zeichen im Kanji-Modus darstellbar, kein „\\“
    oder „~“, die in Shift JIS anders aussehen) oder ``"eci"`` (ECI 26 UTF-8 + Segmente).
    """
    text = text or ""
    if all(ord(c) < 0x80 for c in text):
        return "ascii"
    if not eci:
        return "bytes"
    if (any(_is_japanese(c) for c in text) and "\\" not in text and "~" not in text
            and all(ord(c) < 0x80 or kanji_value(c) is not None for c in text)):
        return "kanji"
    return "eci"


def text_items(text: str, charset: str) -> list[int]:
    """Eingabe-Elemente für :func:`segments`: UTF-8-Bytes bzw. im Kanji-Modus Kanji-Elemente."""
    if charset == "kanji":
        return [ord(c) if ord(c) < 0x80 else KANJI_BASE + kanji_value(c) for c in text]
    return list((text or "").encode("utf-8"))


def text_segments(text: str, ec: str = "M", min_version: int = MIN_VERSION,
                  eci: bool = False) -> list[tuple[str, list]]:
    """Segmente, die :func:`encode_text` für ``text`` verwendet ([("B", Bytes)] = ein Byte-Segment).

    Mit ``eci`` und Nicht-ASCII-Text steht davor noch die ECI-Kennung (siehe :func:`text_charset`).
    """
    ec = _check_level(ec)
    data = (text or "").encode("utf-8")
    if not data:
        raise ValueError("Kein Text für den QR-Code")
    charset = text_charset(text, eci)
    if charset in ("eci", "kanji"):
        items = text_items(text, charset)
        ver, _bits = mixed_bits(items, ec, False, min_version,
                                ECI_UTF8 if charset == "eci" else None)
        return segments(items, ver)
    byte_ver = None
    try:
        byte_ver = choose_version(len(data), ec, min_version)
    except ValueError:
        pass
    if charset == "bytes":         # Nicht-ASCII ohne ECI: ein Byte-Segment (Zeichensatz-Erkennung)
        if byte_ver is None:
            choose_version(len(data), ec, min_version)   # deutsche Fehlermeldung
        return [("B", list(data))]
    try:
        ver, _bits = mixed_bits(list(data), ec, False, min_version)
    except ValueError:
        if byte_ver is None:
            raise
        ver = byte_ver
    if byte_ver is not None and ver >= byte_ver:
        return [("B", list(data))]   # kein Gewinn: bitgleich zum bisherigen Byte-Segment
    return segments(list(data), ver)


def encode_text(text: str, ec: str = "M", min_version: int = MIN_VERSION,
                mask: int | None = None, eci: bool = False) -> QrCode:
    """Text als QR-Code mit gemischten Segmenten, wenn das eine kleinere Version ergibt.

    Sonst (und bei Nicht-ASCII-Text ohne ``eci``) identisch mit :func:`encode` (ein
    Byte-Segment), so dass bestehende Codes bitgleich bleiben, solange sie nicht kleiner werden
    können. Mit ``eci`` bekommt Nicht-ASCII-Text die Kennung ECI 26 (UTF-8) bzw. bei
    japanischem Text den Kanji-Modus (:func:`text_charset`).
    """
    ec = _check_level(ec)
    charset = text_charset(text, eci)
    if charset in ("eci", "kanji"):
        if not text:
            raise ValueError("Kein Text für den QR-Code")
        ver, bits = mixed_bits(text_items(text, charset), ec, False, min_version,
                               ECI_UTF8 if charset == "eci" else None)
        return _bits_to_code(ver, ec, bits, mask)
    segs = text_segments(text, ec, min_version)
    if len(segs) == 1 and segs[0][0] == "B":
        return encode(text, ec, min_version, mask)
    data = (text or "").encode("utf-8")
    ver, bits = mixed_bits(list(data), ec, False, min_version)
    return _bits_to_code(ver, ec, bits, mask)


def segment_summary(segs: list[tuple[str, list]]) -> str:
    """Kurzbeschreibung für den Dialog, z. B. „Segmente: Byte 8, numerisch 12“."""
    names = {"N": "numerisch", "A": "alphanumerisch", "B": "Byte", "K": "Kanji"}
    return "Segmente: " + ", ".join(f"{names[m]} {len(c)}" for m, c in segs)


def gs1_items(text: str) -> list[int]:
    """GS1-Elementstring als Eingabe-Elemente (ohne das führende FNC1, das ist der Modusindikator)."""
    return gs1.sequence(gs1.parse(text))[1:]


def encode_gs1(text: str, ec: str = "M", min_version: int = MIN_VERSION,
               mask: int | None = None) -> QrCode:
    """GS1 QR-Code (ISO/IEC 18004, 7.4.8.2) für einen Elementstring „(01)…(17)…“."""
    return encode_items(gs1_items(text), ec, True, min_version, mask)


def encode_link(text: str, ec: str = "M", domain: str = gs1_link.DEFAULT_DOMAIN,
                min_version: int = MIN_VERSION, mask: int | None = None) -> QrCode:
    """GS1-Digital-Link-QR-Code; ``text`` = Elementstring oder fertige Digital-Link-Adresse."""
    uri, _ = gs1_link.resolve(text, domain)
    return encode_items(list(uri.encode("utf-8")), ec, False, min_version, mask)


def _interleave(ver: int, ec: str, data: bytes) -> bytes:
    blocks = _NUM_BLOCKS[ec][ver]
    ecc_len = _ECC_PER_BLOCK[ec][ver]
    raw = raw_modules(ver) // 8
    n_short = blocks - raw % blocks
    short_len = raw // blocks
    div = rs_divisor(ecc_len)
    all_blocks = []
    k = 0
    for i in range(blocks):
        length = short_len - ecc_len + (0 if i < n_short else 1)
        dat = list(data[k:k + length])
        k += length
        ecc = rs_remainder(dat, div)
        if i < n_short:
            dat.append(0)
        all_blocks.append(dat + ecc)
    out = bytearray()
    for i in range(len(all_blocks[0])):
        for j, blk in enumerate(all_blocks):
            if i != short_len - ecc_len or j >= n_short:
                out.append(blk[i])
    return bytes(out)


# --- Canvas-Objekte -------------------------------------------------------------
def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


@dataclass(frozen=True)
class QrSpec:
    text: str = "https://"
    ec: str = "M"
    size_mm: float = 30.0
    quiet_zone: int = 4
    invert: bool = False
    x: float = 0.0          # linke obere Ecke inkl. Ruhezone
    y: float = 0.0
    mode: str = "text"      # "text", "gs1" (GS1 QR-Code) oder "link" (GS1 Digital Link)
    domain: str = gs1_link.DEFAULT_DOMAIN   # nur "link" mit Elementstring
    # Nur "text": Nicht-ASCII mit ECI 26 (UTF-8) bzw. Kanji-Modus. Fehlt in älteren
    # Dokumenten → False (bitgleich wie bisher); neue Codes aus dem Dialog: True.
    eci: bool = False

    def normalized(self) -> "QrSpec":
        from . import micro_qr as mq
        ec = str(self.ec).upper()
        mode = str(self.mode or "text").lower()
        if mode not in MODES:
            mode = "text"
        domain = "".join(str(self.domain or "").split()) or gs1_link.DEFAULT_DOMAIN
        if mode == "micro":
            if ec not in mq.EC_LEVELS:
                ec = "L"
            size_lo, size_hi = mq.SIZE_RANGE
        else:
            if ec not in EC_LEVELS:
                ec = "M"
            size_lo, size_hi = SIZE_RANGE
        return QrSpec(text=str(self.text or ""), ec=ec,
                      size_mm=float(_clamp(float(self.size_mm), size_lo, size_hi)),
                      quiet_zone=int(_clamp(int(self.quiet_zone), *QUIET_RANGE)),
                      invert=bool(self.invert), x=float(self.x), y=float(self.y),
                      mode=mode, domain=domain, eci=bool(self.eci) and mode == "text")

    def content(self) -> str:
        """Was ein Scanner liest: Text, GS1-Elementstring (normalisiert) oder Digital-Link-Adresse.

        Wirft ``ValueError`` (deutsch) bei ungültigen GS1-Daten.
        """
        s = self.normalized()
        if s.mode == "gs1":
            return gs1.hri(gs1.parse(s.text))
        if s.mode == "link":
            return gs1_link.resolve(s.text, s.domain)[0]
        return s.text

    def encode(self, mask: int | None = None):
        """Full QR (:class:`QrCode`) or Micro QR (:class:`micro_qr.MicroQrCode`)."""
        s = self.normalized()
        if s.mode == "micro":
            from . import micro_qr as mq
            return mq.encode(s.text, s.ec, mask=mask)
        if s.mode == "gs1":
            return encode_gs1(s.text, s.ec, mask=mask)
        if s.mode == "link":
            return encode_link(s.text, s.ec, s.domain, mask=mask)
        return encode_text(s.text, s.ec, mask=mask, eci=s.eci)

    def total_mm(self, code: QrCode) -> float:
        s = self.normalized()
        return s.size_mm * (code.size + 2 * s.quiet_zone) / code.size


def qr_regions(code: QrCode, module_mm: float, quiet_zone: int = 0, invert: bool = False,
               origin: tuple[float, float] = (0.0, 0.0)):
    """Zusammenhängende Laserflächen als shapely-Polygone (mm, Y nach unten)."""
    from shapely.geometry import box
    from shapely.ops import unary_union

    rects = [box(x0, y, x1, y + 1) for y, x0, x1 in code.runs(quiet_zone, invert)]
    merged = unary_union(rects)
    polys = list(getattr(merged, "geoms", [merged]))
    ox, oy = origin
    out = []
    for p in polys:
        if p.is_empty:
            continue
        p = p.simplify(0)  # Zwischenpunkte auf geraden Kanten entfernen (exakt)

        def ring(r):
            pts = [(ox + px * module_mm, oy + py * module_mm) for px, py in r.coords]
            return pts[:-1] if len(pts) > 1 and pts[0] == pts[-1] else pts
        out.append((ring(p.exterior), [ring(i) for i in p.interiors]))
    return out


def qr_shapes(spec: QrSpec, layer_id: str, code: QrCode | None = None) -> list[Shape]:
    """QR-Code als gruppierte ``polygon``-Objekte (eine Fläche je Objekt, Löcher als Ringe).

    Wirft ``ValueError`` bei leerem/zu langem Text, zu kleinen Modulen oder
    wenn der Code samt Ruhezone nicht auf die Arbeitsfläche passt.
    """
    s = spec.normalized()
    if s.mode == "micro":
        from . import micro_qr as mq
        return mq.micro_qr_shapes(s, layer_id, code)
    code = code or s.encode()
    module = s.size_mm / code.size
    if module < HARD_MIN_MODULE_MM:
        raise ValueError(f"Module {module:.2f} mm sind zu klein (mindestens "
                         f"{HARD_MIN_MODULE_MM:.1f} mm) – Code größer machen, Text kürzen oder "
                         "Fehlerkorrektur senken")
    total = module * (code.size + 2 * s.quiet_zone)
    eps = 1e-6
    if s.x < -eps or s.y < -eps or s.x + total > WORK_WIDTH_MM + eps or s.y + total > WORK_HEIGHT_MM + eps:
        raise ValueError(
            f"QR-Code {total:.1f} × {total:.1f} mm (inkl. Ruhezone) passt ab X {s.x:.1f} / Y {s.y:.1f} "
            f"nicht auf die Arbeitsfläche ({WORK_WIDTH_MM:.0f} × {WORK_HEIGHT_MM:.0f} mm)")
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


def content_info(spec: QrSpec) -> str:
    """Deutsche Zeile für den Dialog: was im GS1-Code steht; im Text-Modus der Zeichensatz bei
    Nicht-ASCII-Text und die gemischten Segmente, falls sie den Code verkleinern (sonst "")."""
    s = spec.normalized()
    if s.mode == "micro":
        from . import micro_qr as mq
        mode = mq.choose_mode(s.text)
        names = {"N": "numerisch", "A": "alphanumerisch", "B": "Byte (UTF-8)"}
        return (f"Micro QR – kompakt für Bauteile / wenig Platz; Modus {names[mode]}"
                + ("; kein ECI / Kanji (UTF-8-Bytes)" if mode == "B" and any(ord(c) >= 0x80 for c in s.text)
                   else ""))
    if s.mode == "gs1":
        return "GS1-Daten: " + s.content()
    if s.mode == "link":
        uri, link = gs1_link.resolve(s.text, s.domain)
        return f"Adresse: {uri} ({gs1_link.describe(link)})"
    try:
        segs = text_segments(s.text, s.ec, eci=s.eci)
    except ValueError:
        return ""
    charset = text_charset(s.text, s.eci)
    if charset == "eci":
        return "Zeichensatz UTF-8 (ECI 26) – Umlaute / Sonderzeichen werden sicher erkannt; " + \
            segment_summary(segs)
    if charset == "kanji":
        return "Kanji-Modus (Shift JIS) – japanischer Text kompakt; " + segment_summary(segs)
    if charset == "bytes":
        return ("UTF-8 ohne Zeichensatz-Kennung (älterer Code) – manche Scanner zeigen Umlaute "
                "falsch; „UTF-8 kennzeichnen“ einschalten")
    if len(segs) == 1 and segs[0][0] == "B":
        return ""
    return segment_summary(segs) + " (kleinere Version als ein Byte-Segment)"


def describe(code, size_mm: float) -> str:
    from . import micro_qr as mq
    if isinstance(code, mq.MicroQrCode):
        return mq.describe(code, size_mm)
    module = size_mm / code.size
    return (f"Version {code.version} ({code.size}×{code.size} Module), Maske {code.mask}, "
            f"Modul {module:.2f} mm")
