"""QR-Code (ISO/IEC 18004) als Vektorobjekte für die Gravur – ohne Fremdpaket.

Reiner Python-Encoder im Byte-Modus (UTF-8), Versionen 1–40, Fehlerkorrektur
L/M/Q/H, automatische Maskenwahl nach den Strafpunkten der Norm. Portiert
und erweitert aus ``android/core/.../Qr.kt`` (dort nur Stufe M, Version 1–10).
Qt-frei; die Flächen werden mit shapely zu geschlossenen Polygonen
verschmolzen, damit Füllen/Schraffur keine inneren Kanten doppelt lasert.

Größe ``size_mm`` ist die Kantenlänge des Codes *ohne* Ruhezone. Die Ruhezone
(``quiet_zone`` Module, Norm: 4) ist ein heller Rand: normal wird sie nur
freigehalten (Position X/Y = linke obere Ecke inkl. Ruhezone), invertiert
(für Materialien, die beim Lasern *hell* werden, z. B. eloxiertes Alu,
Schiefer) wird sie zusammen mit den hellen Modulen graviert.
"""

from __future__ import annotations

from dataclasses import dataclass

from lumacut_canvas.model import Shape, new_id
from lumacut_canvas.workarea import WORK_HEIGHT_MM, WORK_WIDTH_MM

EC_LEVELS = ("L", "M", "Q", "H")
EC_LABELS = {"L": "L (7 %)", "M": "M (15 %)", "Q": "Q (25 %)", "H": "H (30 %)"}
MIN_VERSION, MAX_VERSION = 1, 40
# Kleinste Modulkante, die graviert noch zuverlässig gelesen wird (wie Android).
MIN_MODULE_MM = 0.8
# Darunter wird nicht erzeugt (Laserfleck ≈ 0,1 mm, Linienabstand ≈ 0,1 mm).
HARD_MIN_MODULE_MM = 0.2
SIZE_RANGE = (5.0, 340.0)        # mm, Kantenlänge des Codes
QUIET_RANGE = (0, 10)            # Module

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


def encode(text: str, ec: str = "M", min_version: int = MIN_VERSION, mask: int | None = None) -> QrCode:
    """Text (UTF-8, Byte-Modus) als QR-Code. ``mask`` None = beste Maske."""
    ec = _check_level(ec)
    data = (text or "").encode("utf-8")
    if not data:
        raise ValueError("Kein Text für den QR-Code")
    ver = choose_version(len(data), ec, min_version)
    cap_bits = data_codewords(ver, ec) * 8
    bits: list[int] = []

    def put(value: int, n: int) -> None:
        bits.extend((value >> i) & 1 for i in range(n - 1, -1, -1))
    put(0b0100, 4)
    put(len(data), 8 if ver < 10 else 16)
    for b in data:
        put(b, 8)
    put(0, min(4, cap_bits - len(bits)))
    put(0, (-len(bits)) % 8)
    pad = 0xEC
    while len(bits) < cap_bits:
        put(pad, 8)
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

    def normalized(self) -> "QrSpec":
        ec = str(self.ec).upper()
        return QrSpec(text=str(self.text or ""), ec=ec if ec in EC_LEVELS else "M",
                      size_mm=float(_clamp(float(self.size_mm), *SIZE_RANGE)),
                      quiet_zone=int(_clamp(int(self.quiet_zone), *QUIET_RANGE)),
                      invert=bool(self.invert), x=float(self.x), y=float(self.y))

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
    code = code or encode(s.text, s.ec)
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


def describe(code: QrCode, size_mm: float) -> str:
    module = size_mm / code.size
    return (f"Version {code.version} ({code.size}×{code.size} Module), Maske {code.mask}, "
            f"Modul {module:.2f} mm")
