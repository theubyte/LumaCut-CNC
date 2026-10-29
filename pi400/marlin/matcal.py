"""Adaptive material calibration with the head camera (op=matcal).

Engraving: one small field at a time is lasered, photographed and measured
(tone against the untouched material around it, streaks, smoke halo); the
next power is computed from what was seen, until the wanted tones (dark,
medium, light) are found. Cutting: small squares on a RAISED plate, one pass
at a time; after every pass the camera checks whether the piece fell out
(the hole shows dark), so every speed gets exactly the passes it needs and
the setting with the least energy wins (least charring at the back).

Pure Python on purpose: the Pi has no numpy/PIL; a photo is decoded to grey
with ffmpeg. Machine coordinates throughout (mm); the camera model is the
tablet's dot-grid lens model stored in the camera calibration ("android").
Measured on poplar plywood 2026-10-29 (docs/MATERIAL_KALIBRIERUNG.md).
"""
from __future__ import annotations

import math
import subprocess
from dataclasses import dataclass, field

# --- layout -------------------------------------------------------------
ENGRAVE_CELL_MM = 5.0
ENGRAVE_PITCH_MM = 8.0
ENGRAVE_PER_ROW = 6
ENGRAVE_MAX_FIELDS = 18
INTERVAL_MM = 0.1
OVERSCAN_MM = 3.0             # laser-off run-up/out of every raster line
CUT_CELL_MM = 8.0
CUT_PITCH_MM = 12.0
CUT_SPEEDS = (350.0, 500.0, 800.0, 1200.0)
CUT_MAX_PASSES = 10
CUT_Z_STEP_MM = 0.4           # focus follows the cut, at most MAX_FOCUS_DROP_MM in total
MAX_FOCUS_DROP_MM = 3.0

# --- camera ---------------------------------------------------------------
# Height of the camera's projection centre above the machine Z of the probe
# tip: the image scale changes with (CAMERA_ABOVE_Z_MM + Z - surface). From
# the scale of the same marks photographed at Z 24 and Z 70 (2026-10-29).
CAMERA_ABOVE_Z_MM = 88.6
PHOTO_W, PHOTO_H = 1920, 1080
BED_X_MM, BED_Y_OFFSET_MM = 390.0, 30.0   # work = (390 - X, Y - 30), like the apps

# --- engraving search -----------------------------------------------------
TARGETS = (("dunkel", 0.85), ("mittel", 0.55), ("hell", 0.30))
TONE_TOL = 0.06
MAX_PER_TARGET = 4
POWER_RANGE = (1.0, 80.0)
# Below about 6 % this diode laser does not fire reliably (dotted, streaky
# lines on plywood 2026-10-29). Lighter tones therefore keep the energy per
# area (P / v) and go faster instead of lower, up to ENGRAVE_MAX_SPEED.
MIN_POWER_PCT = 8.0
ENGRAVE_MAX_SPEED = 6000.0
# A field counts as clean below these (fractions of the material brightness);
# tuned on plywood: 1500 mm/min smoke halo 0.2-0.4, flickering low power
# stripes 0.1-0.14, good fields 0.02-0.08.
CLEAN_UNEVEN, CLEAN_STRIPES, CLEAN_HALO = 0.12, 0.08, 0.12


class Gray:
    """8-bit grey picture with bilinear sampling."""

    def __init__(self, width: int, height: int, data: bytes):
        if len(data) != width * height:
            raise ValueError("Kamerabild hat %d statt %d Bildpunkte" % (len(data), width * height))
        self.width, self.height, self.data = width, height, data

    def at(self, u: float, v: float) -> float:
        if not (0 <= u < self.width - 1 and 0 <= v < self.height - 1):
            return float("nan")
        iu, iv = int(u), int(v)
        fu, fv = u - iu, v - iv
        d, w = self.data, self.width
        i = iv * w + iu
        top = d[i] + (d[i + 1] - d[i]) * fu
        bottom = d[i + w] + (d[i + w + 1] - d[i + w]) * fu
        return top + (bottom - top) * fv


def decode_gray(jpeg: bytes, width: int = PHOTO_W, height: int = PHOTO_H) -> Gray:
    """JPEG -> grey picture with ffmpeg (already used for the snapshots)."""
    done = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "image2pipe",
                           "-i", "pipe:0", "-vf", "scale=%d:%d" % (width, height),
                           "-f", "rawvideo", "-pix_fmt", "gray", "pipe:1"],
                          input=jpeg, capture_output=True, timeout=30, check=False)
    if done.returncode != 0:
        raise RuntimeError("Kamerabild nicht lesbar: " + done.stderr.decode("utf-8", "replace")[-200:])
    return Gray(width, height, done.stdout)


class CameraModel:
    """Machine point -> photo pixel for the head camera (tablet lens model)."""

    def __init__(self, android: dict):
        lens = (android or {}).get("lens")
        if not lens or len(lens.get("g") or ()) != 9:
            raise RuntimeError("Kamera nicht kalibriert: zuerst in der App die Kamera mit dem Punktraster kalibrieren")
        self.cx, self.cy, self.f = float(lens["cx"]), float(lens["cy"]), float(lens["f"])
        self.k1, self.k2 = float(lens["k1"]), float(lens.get("k2", 0.0))
        self.g = [float(v) for v in lens["g"]]
        self.inv = _inverse3(self.g)
        above = android.get("aboveSurface")
        self.cal_distance = CAMERA_ABOVE_Z_MM + float(above if above is not None else 31.0)
        self.centre = self._to_rel(self.cx, self.cy)
        self.photo_w = int(android.get("photoWidth") or PHOTO_W)
        self.photo_h = int(android.get("photoHeight") or PHOTO_H)

    def _to_rel(self, u, v):
        qx, qy = (u - self.cx) / self.f, (v - self.cy) / self.f
        rd = math.hypot(qx, qy)
        s = 1.0
        if rd > 1e-12:
            r = rd
            for _ in range(30):
                r2 = r * r
                r -= (r * (1 + self.k1 * r2 + self.k2 * r2 * r2) - rd) / (1 + 3 * self.k1 * r2 + 5 * self.k2 * r2 * r2)
            s = r / rd
        return _apply3(self.inv, qx * s, qy * s)

    def _to_pixel(self, rx, ry):
        x, y = _apply3(self.g, rx, ry)
        r2 = x * x + y * y
        d = 1 + self.k1 * r2 + self.k2 * r2 * r2
        return self.cx + self.f * x * d, self.cy + self.f * y * d

    def head_for(self, x: float, y: float) -> tuple[float, float]:
        """Laser position (machine) that puts machine point (x, y) in the picture centre."""
        cx, cy = self.centre                     # work mm relative to the head, any height
        return x + cx, y - cy                    # work x = 390 - X: rel x adds to -X

    def sampler(self, img: Gray, head, z: float, surface_z: float):
        """lum(x, y) for machine points on the surface, head (laser) at ``head``, camera at Z ``z``."""
        k = (CAMERA_ABOVE_Z_MM + z - surface_z) / self.cal_distance
        c0, c1 = self.centre
        hx, hy = head
        to_pixel = self._to_pixel
        sx, sy = img.width / self.photo_w, img.height / self.photo_h

        def lum(x, y):
            rx, ry = hx - x, y - hy               # work mm relative to the head
            u, v = to_pixel(c0 + (rx - c0) / k, c1 + (ry - c1) / k)
            return img.at(u * sx, v * sy)
        return lum


def _apply3(m, x, y):
    w = m[6] * x + m[7] * y + m[8]
    return (m[0] * x + m[1] * y + m[2]) / w, (m[3] * x + m[4] * y + m[5]) / w


def _inverse3(m):
    a, b, c, d, e, f, g, h, i = m
    det = a * (e * i - f * h) - b * (d * i - f * g) + c * (d * h - e * g)
    if abs(det) < 1e-15:
        raise RuntimeError("Linsenmodell ungültig")
    return [(e * i - f * h) / det, (c * h - b * i) / det, (b * f - c * e) / det,
            (f * g - d * i) / det, (a * i - c * g) / det, (c * d - a * f) / det,
            (d * h - e * g) / det, (b * g - a * h) / det, (a * e - b * d) / det]


# --- G-code -------------------------------------------------------------
def s_value(power_pct: float) -> str:
    return "%g" % round(power_pct / 100.0 * 255, 1)


def engrave_field(x, y, power, speed, focus_z, cell=ENGRAVE_CELL_MM):
    """Filled square (raster along X, serpentine, laser-off overscan) at focus."""
    s = s_value(power)
    out = ["M5 I", "M3 I", "G0 X%.3f Y%.3f" % (x - OVERSCAN_MM, y), "G0 Z%.3f F600" % focus_z]
    n = int(round(cell / INTERVAL_MM))
    for k in range(n + 1):
        yy = y + k * INTERVAL_MM
        a, b = (x, x + cell) if k % 2 == 0 else (x + cell, x)
        d = 1 if b > a else -1
        out += ["G1 X%.3f Y%.3f F%d S0" % (a - d * OVERSCAN_MM, yy, speed),
                "G1 X%.3f F%d S0" % (a, speed),
                "G1 X%.3f F%d S%s" % (b, speed, s),
                "G1 X%.3f F%d S0" % (b + d * OVERSCAN_MM, speed)]
    return out + ["M5 I"]


def cut_pass(x, y, speed, power, focus_z, done_passes, cell=CUT_CELL_MM, z_step=CUT_Z_STEP_MM):
    """One pass around the square; the focus follows the cut into the material."""
    z = focus_z - min(z_step * done_passes, MAX_FOCUS_DROP_MM)
    pts = [(x + cell, y), (x + cell, y + cell), (x, y + cell), (x, y)]
    return (["M5 I", "M3 I", "G0 X%.3f Y%.3f" % (x, y), "G0 Z%.3f F600" % z]
            + ["G1 X%.3f Y%.3f F%d S%s" % (a, b, speed, s_value(power)) for a, b in pts] + ["M5 I"])


def engrave_slot(origin, k):
    return (origin[0] + (k % ENGRAVE_PER_ROW) * ENGRAVE_PITCH_MM,
            origin[1] + (k // ENGRAVE_PER_ROW) * ENGRAVE_PITCH_MM)


def cut_slot(origin, k):
    return origin[0] + k * CUT_PITCH_MM, origin[1]


def engrave_area(origin, fields=ENGRAVE_MAX_FIELDS):
    rows = (fields + ENGRAVE_PER_ROW - 1) // ENGRAVE_PER_ROW
    return (origin[0] - OVERSCAN_MM, origin[1],
            origin[0] + (min(fields, ENGRAVE_PER_ROW) - 1) * ENGRAVE_PITCH_MM + ENGRAVE_CELL_MM + OVERSCAN_MM,
            origin[1] + (rows - 1) * ENGRAVE_PITCH_MM + ENGRAVE_CELL_MM)


def cut_area(origin, n=len(CUT_SPEEDS)):
    return origin[0], origin[1], origin[0] + (n - 1) * CUT_PITCH_MM + CUT_CELL_MM, origin[1] + CUT_CELL_MM


# --- measuring ------------------------------------------------------------
def _grid(x0, y0, x1, y1, step):
    nx, ny = int(round((x1 - x0) / step)), int(round((y1 - y0) / step))
    return [[(x0 + i * step, y0 + j * step) for i in range(nx + 1)] for j in range(ny + 1)]


def _mean(values):
    v = [a for a in values if a == a]
    return sum(v) / len(v) if v else float("nan")


def _median(values):
    v = sorted(a for a in values if a == a)
    return v[len(v) // 2] if v else float("nan")


def _std(values):
    v = [a for a in values if a == a]
    if len(v) < 2:
        return 0.0
    m = sum(v) / len(v)
    return math.sqrt(sum((a - m) ** 2 for a in v) / len(v))


def ring(lum, x, y, cell, a, b, step=0.2):
    """Samples a..b mm outside the square (x, y, cell)."""
    out = []
    for row in _grid(x - b, y - b, x + cell + b, y + cell + b, step):
        for px, py in row:
            d = max(x - px, px - (x + cell), y - py, py - (y + cell))
            if a <= d <= b:
                out.append(lum(px, py))
    return out


def locate(before, after, x, y, cell, guess=(0.0, 0.0), reach=1.5):
    """Where the new square really is in the photo: the shift (around
    ``guess``) at which it darkened most. Camera and laser are not perfectly
    registered (about 1-2 mm). Returns (dx, dy, darkening)."""
    inset = 0.25

    def score(dx, dy, step):
        # darkening inside minus darkening just outside: peaks where the square sits
        pts = [p for row in _grid(x + dx + inset, y + dy + inset, x + dx + cell - inset, y + dy + cell - inset, step) for p in row]
        inside = _mean([before(*p) - after(*p) for p in pts])
        diff = lambda px, py: before(px, py) - after(px, py)
        outside = _mean(ring(diff, x + dx, y + dy, cell, 0.25, 0.75, step=step))
        return inside - outside
    best = (-1e9, guess[0], guess[1])
    n = int(round(reach / 0.5))
    for i in range(-n, n + 1):
        for j in range(-n, n + 1):
            dx, dy = guess[0] + i * 0.5, guess[1] + j * 0.5
            s = score(dx, dy, 0.5)
            if s > best[0]:
                best = (s, dx, dy)
    _, bx, by = best
    for i in range(-2, 3):
        for j in range(-2, 3):
            dx, dy = bx + i * 0.25, by + j * 0.25
            s = score(dx, dy, 0.25)
            if s > best[0]:
                best = (s, dx, dy)
    return best[1], best[2], best[0]


def measure_field(lum, x, y, cell=ENGRAVE_CELL_MM):
    """tone 0 = untouched .. 1 = black (against the material 1.4-2.4 mm
    around), uneven (spread over ~0.3 mm), stripes (spread of the raster
    rows), halo (darkening 0.4-0.9 mm around: smoke, overburn)."""
    inset, step = 0.8, 0.1
    rows = [[lum(px, py) for px, py in row] for row in _grid(x + inset, y + inset, x + cell - inset, y + cell - inset, step)]
    wood = _median(ring(lum, x, y, cell, 1.4, 2.4))
    if not wood == wood or wood < 15:
        raise RuntimeError("Feld im Kamerabild nicht auswertbar (zu dunkel oder außerhalb des Bildes)")
    flat = [v for r in rows for v in r]
    blurred = []
    for j in range(1, len(rows) - 1):
        for i in range(1, len(rows[0]) - 1):
            blurred.append(sum(rows[j + a][i + b] for a in (-1, 0, 1) for b in (-1, 0, 1)) / 9)
    near = _mean(ring(lum, x, y, cell, 0.4, 0.9))
    return {"tone": round(min(1.2, max(0.0, 1 - _mean(flat) / wood)), 3),
            "uneven": round(_std(blurred) / wood, 3),
            "stripes": round(_std([_mean(r) for r in rows]) / wood, 3),
            "halo": round(max(-1.0, min(1.0, 1 - near / wood)), 3)}


def clean(m) -> bool:
    return m["uneven"] < CLEAN_UNEVEN and m["stripes"] < CLEAN_STRIPES and m["halo"] < CLEAN_HALO


def hole_ratio(lum, x, y, cell=CUT_CELL_MM):
    """Inside of the square (1.5 mm in) against the material 2-3 mm around:
    about 1 while the piece is in, near 0 once it fell out of the raised plate."""
    inside = _mean([lum(px, py) for row in _grid(x + 1.5, y + 1.5, x + cell - 1.5, y + cell - 1.5, 0.25) for px, py in row])
    around = _median(ring(lum, x, y, cell, 2.0, 3.0, step=0.25))
    if not around == around or around < 15:
        raise RuntimeError("Schnittfeld im Kamerabild nicht auswertbar")
    return inside / around


# --- searches ---------------------------------------------------------------
@dataclass
class EngraveSearch:
    """Which field to laser next. Dark first at ``speed``: a streaky but
    right tone means flicker, so the same energy is tried slower; a smoke
    halo means too slow, so faster. Medium and light then at the dark
    field's speed, by a secant in log(power) over the fields seen."""
    start_power: float = 10.0
    speed: float = 4500.0
    max_fields: int = ENGRAVE_MAX_FIELDS
    fields: list = field(default_factory=list)
    results: dict = field(default_factory=dict)
    _target: int = 0
    _tries: int = 0
    _next: float | None = None

    def done(self) -> bool:
        return self._target >= len(TARGETS) or len(self.fields) >= self.max_fields

    def next(self):
        if self.done():
            return None
        name, target = TARGETS[self._target]
        power = self._next if self._next is not None else self._propose(target)
        power = min(POWER_RANGE[1], max(POWER_RANGE[0], power))
        speed = self.speed
        if power < MIN_POWER_PCT:
            # same energy faster, at the lowest power the laser fires reliably
            speed = min(ENGRAVE_MAX_SPEED, max(speed, speed * MIN_POWER_PCT / power))
            power = MIN_POWER_PCT
        return {"target": name, "tone_target": target, "power": round(power, 1), "speed": round(speed)}

    def add(self, step, measured):
        """``measured`` = measure_field() result for the field lasered with ``step``."""
        f = dict(step, **measured, clean=clean(measured))
        self.fields.append(f)
        self._tries += 1
        self._next = None
        name, target = TARGETS[self._target]
        hit = abs(f["tone"] - target) <= TONE_TOL
        if hit and f["clean"]:
            return self._finish(name, f)
        if hit and name == "dunkel" and self._tries < MAX_PER_TARGET + 2:
            if f["halo"] >= CLEAN_HALO and self.speed < 6000:
                self.speed, self._next = self.speed * 1.5, f["power"] * 1.5      # smoke: faster
                return
            if self.speed > 1500:
                self.speed, self._next = self.speed * 2 / 3, f["power"] * 2 / 3  # flicker: slower
                return
        if self._tries >= MAX_PER_TARGET:
            near = [g for g in self.fields if g["target"] == name]
            ok = [g for g in near if g["clean"]] or near
            self._finish(name, min(ok, key=lambda g: abs(g["tone"] - target)), approximate=True)

    def _finish(self, name, f, approximate=False):
        self.results[name] = dict(f, approximate=approximate or abs(f["tone"] - TARGETS[self._target][1]) > TONE_TOL)
        self._target += 1
        self._tries = 0
        self._next = None

    def _propose(self, target):
        """Next power: secant in log(power) over the fields seen at this speed;
        fields at other speeds count with the same energy per area (P / v)."""
        pts = sorted((g["power"] * self.speed / g["speed"], g["tone"]) for g in self.fields)
        if not pts:
            return self.start_power
        lo = [p for p in pts if p[1] < target]
        hi = [p for p in pts if p[1] >= target]
        if lo and hi:
            (p0, t0), (p1, t1) = max(lo), min(hi)
            if t1 - t0 < 1e-3 or p0 >= p1:
                return math.sqrt(p0 * p1)
            return math.exp(math.log(p0) + (target - t0) / (t1 - t0) * (math.log(p1) - math.log(p0)))
        if hi:
            p, t = min(hi)
            return p / (1.25 + 2.0 * (t - target))
        p, t = max(lo)
        return p * (1.25 + 2.0 * (target - t))


def tone_curve(fields) -> dict | None:
    """Darkness curve of a material from the measured fields, stored with the
    engraving materials (``tone_curve``): the apps move speed and power
    together along it (same tone) or along the tone (lighter/darker)."""
    points = [{"power": round(f["power"], 2), "speed": round(f["speed"]), "tone": round(f["tone"], 3),
               "clean": bool(f.get("clean", True))} for f in fields if f.get("tone") is not None]
    if len(points) < 2:
        return None
    speeds = [p["speed"] for p in points]
    return {"points": points[:40], "min_power_pct": MIN_POWER_PCT, "interval_mm": INTERVAL_MM,
            "speed_min": float(min(speeds + [1500])), "speed_max": float(max(speeds + [ENGRAVE_MAX_SPEED]))}


@dataclass
class CutSearch:
    """One pass at a time per speed until the piece falls out. A speed
    stops early once it already needs more energy (passes / speed) than
    1.6 x the best found so far: it cannot win any more."""
    speeds: tuple = CUT_SPEEDS
    power: float = 100.0
    max_passes: int = CUT_MAX_PASSES
    squares: list = field(default_factory=list)       # per speed: {"speed", "passes", "fell"}
    _i: int = 0
    _passes: int = 0

    def best(self):
        fell = [s for s in self.squares if s["fell"]]
        return min(fell, key=lambda s: (s["passes"] / s["speed"], -s["speed"])) if fell else None

    def _limit(self, speed):
        b = self.best()
        if b is None:
            return self.max_passes
        return max(1, min(self.max_passes, int(math.floor(1.6 * b["passes"] / b["speed"] * speed))))

    def done(self):
        return self._i >= len(self.speeds)

    def next(self):
        if self.done():
            return None
        return {"square": self._i, "speed": self.speeds[self._i], "power": self.power, "pass": self._passes}

    def add(self, step, fell: bool):
        self._passes += 1
        speed = self.speeds[self._i]
        if fell or self._passes >= self._limit(speed):
            self.squares.append({"speed": speed, "passes": self._passes, "fell": bool(fell)})
            self._i += 1
            self._passes = 0
