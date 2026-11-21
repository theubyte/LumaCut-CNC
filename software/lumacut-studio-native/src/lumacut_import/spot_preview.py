"""Laserpunkt-Simulation der Bildvorschau („Laserpunkt simulieren“).

Die Vorschau im Dialog „Bildeinstellungen“ zeigt sonst einen Vorschaupixel je
Laserpunkt – als ob der Strahl ein Quadrat genau im Linienabstand brennt. Ein
Diodenlaser brennt aber eine Spur mit seiner eigenen Breite (Punktgröße, z. B.
0,08 mm): ist der Linienabstand größer, bleiben helle Streifen zwischen den
Zeilen; ist er viel kleiner, überlappen die Spuren und das Bild wird dunkler
und matschig. LightBurn und xTool Creative Space raten deshalb, den
Linienabstand an die Punktgröße anzupassen, zeigen den Effekt aber nicht.

:func:`simulate_spot` rechnet aus den Vorschaupixeln (genau die Punkte und
Leistungen des Auftrags) ein vergrößertes Bild: jede Rasterzeile ist eine
Spur auf ihrer Mittellinie, gebrannte Strecken entlang der Zeile wie im
G-code (Punktbreitenkorrektur kürzt sie wie :func:`lumacut_job.raster._dot_width`),
quer dazu ein Gauß-Strahl mit σ = Punktgröße / 4. Die Energie addiert sich
(Überlappung wird dunkler), die Schwärzung ist ``1 − exp(−k · E)`` mit ``k`` so,
dass eine einzelne Linie mit voller Leistung genau in der Punktgröße breit
erscheint (Rand = 50 % Grau, Mitte schwarz, auf Schwarz begrenzt). Material, Leistung und
Geschwindigkeit werden nicht modelliert – die Punktgröße ist die gemessene
Breite einer gelaserten Linie mit den eigenen Werten.

Diodenlaser haben meist keinen runden, sondern einen länglichen Punkt (z. B.
0,08 × 0,06 mm – der Emitter ist ein Streifen). ``spot_y_mm`` gibt dann die
Punktgröße in Y der Maschine an (``spot_mm`` = X): der Strahl wird ein
elliptischer Gauß mit σx = X / 4, σy = Y / 4 in Maschinenlage, im Raster des
Durchgangs um den Scan-Winkel gedreht. Die Spur ist dann quer zur
Scan-Richtung so breit wie der Punkt in dieser Richtung
(:func:`track_width`: bei 0° die Y-, bei 90° die X-Größe) – Lücken,
Überlappung und „Als Linienabstand“ richten sich nach dieser Spurbreite.

Gezeigt wird ein mittiger Ausschnitt mit ``sub`` (ungerade, 1…7) Bildpunkten
je Laserpunkt, höchstens ``max_pixels`` Bildpunkte – eine Lupe auf die echte
Punktstruktur. G-code, Auftrag und Projekt bleiben unverändert.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

SPOT_RANGE_MM = (0.01, 1.0)
DEFAULT_SPOT_MM = 0.08          # typischer Diodenlaser (5–10 W optisch)
MAX_SUB = 7                     # Bildpunkte je Laserpunkt (ungerade)
SIGMA_PER_SPOT = 0.25           # σ des Strahls = Punktgröße / 4
EDGE_DARKNESS = 0.5             # Schwärzung am Rand einer einzelnen Linie
# Energie am Linienrand (Abstand Punktgröße / 2): exp(-(d/2)² / (2σ²)) = exp(-2)
GAIN = math.log(1.0 / (1.0 - EDGE_DARKNESS)) / math.exp(-0.25 / (2 * SIGMA_PER_SPOT ** 2))
GAP_RATIO = 0.9                 # Punktgröße / Linienabstand darunter: Lücken
OVERLAP_RATIO = 1.6             # darüber: starke Überlappung
MAX_PREVIEW_PIXELS = 360_000

SETTINGS_SIMULATE = "image_preview/simulate_spot"
SETTINGS_SPOT = "image_preview/spot_mm"
SETTINGS_SPOT_Y = "image_preview/spot_y_mm"
ROUND_TOL = 1e-6                # mm: X und Y gleich = runder Punkt
OTHER_DIRECTION_HINT = 1.15     # Spurbreiten um ≥ 15 % verschieden: andere Richtung nennen


@dataclass(frozen=True)
class SpotInfo:
    spot_mm: float
    interval_mm: float
    sub: int                    # Bildpunkte je Laserpunkt (je Richtung)
    dots: tuple[int, int]       # gezeigte Laserpunkte (Spalten, Zeilen)
    cropped: bool               # Ausschnitt kleiner als die Vorschau
    dot_width_mm: float = 0.0
    spot_y_mm: float | None = None   # Punktgröße in Y (None = rund, wie X)
    angle: float = 0.0               # Scan-Winkel des Durchgangs (Grad)

    @property
    def size_y_mm(self) -> float:
        return self.spot_mm if self.spot_y_mm is None else self.spot_y_mm

    @property
    def round(self) -> bool:
        return abs(self.size_y_mm - self.spot_mm) <= ROUND_TOL

    @property
    def track_mm(self) -> float:
        """Breite der Spur quer zur Scan-Richtung."""
        return track_width(self.spot_mm, self.size_y_mm, self.angle)

    @property
    def ratio(self) -> float:
        return self.track_mm / self.interval_mm

    @property
    def verdict(self) -> str:
        return spot_verdict(self.interval_mm, self.track_mm)

    @property
    def label(self) -> str:
        """„0.08 mm“ (rund) oder „0.08 × 0.06 mm“ (X × Y)."""
        return spot_label(self.spot_mm, self.size_y_mm)

    @property
    def size_mm(self) -> tuple[float, float]:
        return self.dots[0] * self.interval_mm, self.dots[1] * self.interval_mm


def clamp_spot(spot_mm) -> float:
    try:
        v = float(spot_mm)
    except (TypeError, ValueError):
        return DEFAULT_SPOT_MM
    if not math.isfinite(v):
        return DEFAULT_SPOT_MM
    return min(max(v, SPOT_RANGE_MM[0]), SPOT_RANGE_MM[1])


def spot_label(spot_mm: float, spot_y_mm: float | None = None) -> str:
    if spot_y_mm is None or abs(spot_y_mm - spot_mm) <= ROUND_TOL:
        return f"{spot_mm:g} mm"
    return f"{spot_mm:g} × {spot_y_mm:g} mm"


def track_width(spot_mm: float, spot_y_mm: float | None = None, angle: float = 0.0) -> float:
    """Breite der gelaserten Spur quer zur Scan-Richtung ``angle`` (Grad,
    0° = Zeilen entlang X) für einen Punkt ``spot_mm`` (X) × ``spot_y_mm`` (Y):
    ``√(X² · sin² + Y² · cos²)`` – bei 0° die Y-, bei 90° die X-Größe."""
    x = clamp_spot(spot_mm)
    y = x if spot_y_mm is None else clamp_spot(spot_y_mm)
    if abs(x - y) <= ROUND_TOL:
        return x
    t = math.radians(float(angle))
    return math.sqrt((x * math.sin(t)) ** 2 + (y * math.cos(t)) ** 2)


def raster_sigmas(spot_mm: float, spot_y_mm: float | None, angle: float) -> tuple[float, float, float]:
    """Kovarianz des Strahls (mm², ``(c_xx, c_yy, c_xy)``) im Raster eines
    Durchgangs mit Scan-Winkel ``angle``: Zeilen = x, quer = y (nach unten).
    Die Maschinen-X-Achse liegt dort bei ``(cos, sin)``, die Y-Achse bei
    ``(−sin, cos)`` (die Vorschau dreht das Raster gegen den Uhrzeigersinn
    zurück, :func:`lumacut_import.image_preview.rotate_pixels`)."""
    sx = clamp_spot(spot_mm) * SIGMA_PER_SPOT
    sy = (sx if spot_y_mm is None else clamp_spot(spot_y_mm) * SIGMA_PER_SPOT)
    t = math.radians(float(angle))
    c, s = math.cos(t), math.sin(t)
    cxx = sx * sx * c * c + sy * sy * s * s
    cyy = sx * sx * s * s + sy * sy * c * c
    cxy = (sx * sx - sy * sy) * c * s
    return cxx, cyy, cxy


def spot_verdict(interval_mm: float, spot_mm: float) -> str:
    """``"gaps"`` (helle Streifen zwischen den Zeilen), ``"overlap"`` (Spuren
    überlappen stark, Bild dunkler) oder ``"ok"``."""
    r = spot_mm / interval_mm
    if r < GAP_RATIO:
        return "gaps"
    if r > OVERLAP_RATIO:
        return "overlap"
    return "ok"


def verdict_text(interval_mm: float, spot_mm: float, spot_y_mm: float | None = None,
                 angle: float = 0.0) -> str:
    """Hinweis zum Linienabstand. Bei einem länglichen Punkt (``spot_y_mm``
    ≠ ``spot_mm``) zählt die Spurbreite quer zur Scan-Richtung ``angle``."""
    if spot_y_mm is not None and abs(clamp_spot(spot_y_mm) - clamp_spot(spot_mm)) > ROUND_TOL:
        return _elliptic_verdict_text(interval_mm, clamp_spot(spot_mm),
                                      clamp_spot(spot_y_mm), float(angle))
    v = spot_verdict(interval_mm, spot_mm)
    dpi = 25.4 / spot_mm
    if v == "gaps":
        return (f"Linienabstand {interval_mm:g} mm > Punktgröße {spot_mm:g} mm – helle Streifen "
                f"zwischen den Zeilen; Linienabstand ≈ Punktgröße ({dpi:.0f} DPI) wählen.")
    if v == "overlap":
        return (f"Punktgröße {spot_mm:g} mm = {spot_mm / interval_mm:.1f} × Linienabstand – "
                f"die Spuren überlappen stark, das Bild wird dunkler und verliert Details; "
                f"Linienabstand ≈ Punktgröße ({dpi:.0f} DPI) oder weniger Leistung.")
    return f"Linienabstand passt zur Punktgröße {spot_mm:g} mm."


def _elliptic_verdict_text(interval_mm: float, x: float, y: float, angle: float) -> str:
    track = track_width(x, y, angle)
    dpi = 25.4 / track
    head = (f"Punkt {x:g} × {y:g} mm (X × Y): Spur quer zur Scan-Richtung "
            f"{track:.3f} mm breit")
    v = spot_verdict(interval_mm, track)
    if v == "gaps":
        text = (f"{head} – Linienabstand {interval_mm:g} mm ist größer, helle Streifen zwischen "
                f"den Zeilen; Linienabstand ≈ Spurbreite ({dpi:.0f} DPI) wählen.")
    elif v == "overlap":
        text = (f"{head} = {track / interval_mm:.1f} × Linienabstand – die Spuren überlappen "
                f"stark, das Bild wird dunkler und verliert Details; Linienabstand ≈ "
                f"Spurbreite ({dpi:.0f} DPI) oder weniger Leistung.")
    else:
        text = f"{head} – Linienabstand passt."
    other_angle = (angle + 90.0) % 180.0
    other = track_width(x, y, other_angle)
    if max(other, track) >= OTHER_DIRECTION_HINT * min(other, track):
        finer = "schmaler" if other < track else "breiter"
        text += (f" Bei Scan-Winkel {other_angle:g}° wäre die Spur {other:.3f} mm "
                 f"{finer}.")
    return text


def subsamples(interval_mm: float, spot_mm: float) -> int:
    """Bildpunkte je Laserpunkt: so fein, dass ein Bildpunkt höchstens σ des
    Strahls ist (ungerade, damit die Zeilenmitte auf einen Bildpunkt fällt)."""
    sigma = spot_mm * SIGMA_PER_SPOT
    n = max(1, math.ceil(interval_mm / sigma - 1e-9))
    if n % 2 == 0:
        n += 1
    return min(n, MAX_SUB)


def _crop(rows: int, cols: int, budget: int) -> tuple[int, int, int, int]:
    """Mittiger Ausschnitt ``(y0, x0, h, w)`` mit höchstens ``budget`` Punkten."""
    if rows * cols <= budget:
        return 0, 0, rows, cols
    ch = min(rows, max(1, int(budget ** 0.5)))
    cw = min(cols, max(1, budget // ch))
    return (rows - ch) // 2, (cols - cw) // 2, ch, cw


def _rows_with_dot_width(power: np.ndarray, sub: int, dw_px: float) -> np.ndarray:
    """Abdeckung je Bildpunkt entlang der Zeilen (0…255), gebrannte Strecken
    um die Punktbreitenkorrektur gekürzt wie im G-code."""
    from lumacut_job.raster import _dot_width
    rows, cols = power.shape
    out = np.zeros((rows, cols * sub), dtype=np.float64)
    edges = np.arange(cols * sub + 1, dtype=np.float64) / sub
    for r in range(rows):
        row = power[r]
        nz = np.nonzero(row)[0]
        if nz.size == 0:
            continue
        c0, c1 = int(nz[0]), int(nz[-1]) + 1
        runs = []
        start = c0
        for c in range(c0 + 1, c1 + 1):
            if c == c1 or row[c] != row[start]:
                runs.append((start, c, int(row[start])))
                start = c
        runs = _dot_width(runs, dw_px)
        xs = [float(runs[0][0])]
        acc = [0.0]
        for a, b, v in runs:
            xs.append(float(b))
            acc.append(acc[-1] + v * (b - a))
        integral = np.interp(edges, xs, acc)       # flach vor / nach der Zeile
        out[r] = np.diff(integral) * sub
    return out


def track_map(pixels: np.ndarray, sub: int, dot_width_px: float = 0.0) -> np.ndarray:
    """Spuren der Rasterzeilen als Bild mit ``sub`` × ``sub`` Bildpunkten je
    Laserpunkt: Leistung 0…1 auf der Mittel-Bildpunktzeile jeder Rasterzeile."""
    px = np.asarray(pixels)
    power = (255 - px.astype(np.int32))
    rows, cols = power.shape
    if dot_width_px > 0:
        line = _rows_with_dot_width(power, sub, dot_width_px) / 255.0
    else:
        line = np.repeat(power.astype(np.float64) / 255.0, sub, axis=1)
    out = np.zeros((rows * sub, cols * sub), dtype=np.float64)
    out[sub // 2::sub] = line
    return out


MIN_SIGMA_PX = 0.3              # schmaler: in dieser Richtung nicht verwischen


def _kernel_1d(sigma_px: float) -> np.ndarray:
    import cv2
    if sigma_px < MIN_SIGMA_PX:
        return np.ones((1, 1), dtype=np.float64)
    half = max(1, int(math.ceil(3.0 * sigma_px)))
    return cv2.getGaussianKernel(2 * half + 1, sigma_px, cv2.CV_64F)


def _blur(track: np.ndarray, sigma_px: float, sigma_y_px: float | None = None,
          cov_xy_px: float = 0.0) -> np.ndarray:
    """Gauß-Strahl (σ in Bildpunkten, ``sigma_px`` entlang der Zeilen,
    ``sigma_y_px`` quer dazu – None = rund, ``cov_xy_px`` = Kovarianz eines
    schräg liegenden elliptischen Punkts); Energie so normiert, dass die Mitte
    einer langen Linie mit voller Leistung 1 ist."""
    import cv2
    sy = sigma_px if sigma_y_px is None else sigma_y_px
    if abs(cov_xy_px) <= 1e-9 * max(1.0, sigma_px * sy):
        if sigma_px < MIN_SIGMA_PX and sy < MIN_SIGMA_PX:
            return track
        kx, ky = _kernel_1d(sigma_px), _kernel_1d(sy)
        e = cv2.sepFilter2D(track, cv2.CV_64F, kx, ky, borderType=cv2.BORDER_CONSTANT)
        return e / float(ky.max())
    # Schräger elliptischer Punkt: volle 2D-Gauß-Maske (Kovarianz positiv
    # definit halten, sehr schmale Richtungen wie oben nicht feiner als 0,3 px).
    cxx, cyy, cxy = sigma_px ** 2, sy ** 2, cov_xy_px
    half_tr = (cxx + cyy) / 2
    disc = math.sqrt(max(0.0, half_tr * half_tr - (cxx * cyy - cxy * cxy)))
    l1, l2 = half_tr + disc, half_tr - disc
    if l2 < MIN_SIGMA_PX ** 2:
        vx, vy = cxy, l1 - cxx                    # Eigenvektor zum großen Eigenwert
        n = math.hypot(vx, vy)
        vx, vy = vx / n, vy / n
        l1, l2 = max(l1, MIN_SIGMA_PX ** 2), MIN_SIGMA_PX ** 2
        cxx = l1 * vx * vx + l2 * vy * vy
        cyy = l1 * vy * vy + l2 * vx * vx
        cxy = (l1 - l2) * vx * vy
    hx = max(1, int(math.ceil(3.0 * math.sqrt(cxx))))
    hy = max(1, int(math.ceil(3.0 * math.sqrt(cyy))))
    yy, xx = np.mgrid[-hy:hy + 1, -hx:hx + 1].astype(np.float64)
    det = cxx * cyy - cxy * cxy
    q = (cyy * xx * xx - 2.0 * cxy * xx * yy + cxx * yy * yy) / det
    k = np.exp(-0.5 * q)
    k /= k.sum()
    e = cv2.filter2D(track, cv2.CV_64F, k, borderType=cv2.BORDER_CONSTANT)
    # Lange Linie entlang der Zeilen: Energie in der Mitte = Zeilensumme der Maske.
    return e / float(k.sum(axis=1).max())


def simulate_spot(pixels: np.ndarray, interval_mm: float, spot_mm: float,
                  dot_width_mm: float = 0.0,
                  max_pixels: int = MAX_PREVIEW_PIXELS,
                  spot_y_mm: float | None = None,
                  angle: float = 0.0) -> tuple[np.ndarray, SpotInfo]:
    """Vorschaupixel (uint8, 0 = volle Leistung, 255 = nicht lasern; ein Pixel
    je Laserpunkt, Zeilen = Rasterzeilen) → Bild der gelaserten Spuren mit
    der Punktgröße ``spot_mm`` (uint8, 0 = schwarz) und :class:`SpotInfo`.

    ``spot_y_mm``: Punktgröße in Y der Maschine für einen länglichen
    Diodenpunkt (None = rund); ``angle``: Scan-Winkel des Durchgangs, in
    dessen Raster ``pixels`` liegen (der Punkt liegt dort entsprechend gedreht)."""
    if not interval_mm > 0:
        raise ValueError("Linienabstand muss größer als 0 sein")
    spot = clamp_spot(spot_mm)
    spot_y = None if spot_y_mm is None else clamp_spot(spot_y_mm)
    if spot_y is not None and abs(spot_y - spot) <= ROUND_TOL:
        spot_y = None
    angle = float(angle) if angle is not None and math.isfinite(float(angle)) else 0.0
    small = spot if spot_y is None else min(spot, spot_y)
    big = spot if spot_y is None else max(spot, spot_y)
    px = np.asarray(pixels, dtype=np.uint8)
    if px.ndim != 2 or px.size == 0:
        raise ValueError("leere Vorschau")
    sub = subsamples(interval_mm, small)
    rows, cols = px.shape
    y0, x0, ch, cw = _crop(rows, cols, max(1, int(max_pixels) // (sub * sub)))
    # Rand mitnehmen, damit Spuren knapp außerhalb in den Ausschnitt strahlen.
    m = int(math.ceil(1.5 * big / interval_mm)) + 1
    t, lft = min(m, y0), min(m, x0)
    b, r = min(m, rows - y0 - ch), min(m, cols - x0 - cw)
    part = px[y0 - t:y0 + ch + b, x0 - lft:x0 + cw + r]
    dw = max(0.0, min(float(dot_width_mm), interval_mm)) / interval_mm
    track = track_map(part, sub, dw)
    if spot_y is None:
        energy = _blur(track, spot * SIGMA_PER_SPOT / interval_mm * sub)
    else:
        cxx, cyy, cxy = raster_sigmas(spot, spot_y, angle)
        f = sub / interval_mm
        energy = _blur(track, math.sqrt(cxx) * f, math.sqrt(cyy) * f, cxy * f * f)
    # Mitte einer Linie mit voller Leistung = genau Schwarz.
    dark = np.minimum(1.0, (1.0 - np.exp(-GAIN * energy)) / (1.0 - math.exp(-GAIN)))
    out = np.clip(np.rint(255.0 * (1.0 - dark)), 0, 255).astype(np.uint8)
    out = out[t * sub:(t + ch) * sub, lft * sub:(lft + cw) * sub]
    info = SpotInfo(spot, float(interval_mm), sub, (cw, ch), (ch, cw) != (rows, cols),
                    float(dot_width_mm), spot_y, angle)
    return np.ascontiguousarray(out), info


def load_prefs(settings) -> tuple[bool, float]:
    """``(simulieren, Punktgröße)`` aus QSettings (ohne: aus, Vorgabe)."""
    if settings is None:
        return False, DEFAULT_SPOT_MM
    on = settings.value(SETTINGS_SIMULATE) if settings.contains(SETTINGS_SIMULATE) else False
    on = on is True or str(on).lower() in ("true", "1")
    spot = settings.value(SETTINGS_SPOT) if settings.contains(SETTINGS_SPOT) else None
    return on, clamp_spot(spot) if spot is not None else DEFAULT_SPOT_MM


def load_spot_y(settings, spot_mm: float) -> float:
    """Punktgröße in Y aus QSettings (ohne Eintrag: rund, wie ``spot_mm``)."""
    if settings is None or not settings.contains(SETTINGS_SPOT_Y):
        return clamp_spot(spot_mm)
    return clamp_spot(settings.value(SETTINGS_SPOT_Y))


def save_prefs(settings, simulate: bool, spot_mm: float, spot_y_mm: float | None = None) -> None:
    if settings is None:
        return
    settings.setValue(SETTINGS_SIMULATE, bool(simulate))
    settings.setValue(SETTINGS_SPOT, clamp_spot(spot_mm))
    if spot_y_mm is not None:
        settings.setValue(SETTINGS_SPOT_Y, clamp_spot(spot_y_mm))
    settings.sync()
