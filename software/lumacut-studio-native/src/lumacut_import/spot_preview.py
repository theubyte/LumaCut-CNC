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


@dataclass(frozen=True)
class SpotInfo:
    spot_mm: float
    interval_mm: float
    sub: int                    # Bildpunkte je Laserpunkt (je Richtung)
    dots: tuple[int, int]       # gezeigte Laserpunkte (Spalten, Zeilen)
    cropped: bool               # Ausschnitt kleiner als die Vorschau
    dot_width_mm: float = 0.0

    @property
    def ratio(self) -> float:
        return self.spot_mm / self.interval_mm

    @property
    def verdict(self) -> str:
        return spot_verdict(self.interval_mm, self.spot_mm)

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


def spot_verdict(interval_mm: float, spot_mm: float) -> str:
    """``"gaps"`` (helle Streifen zwischen den Zeilen), ``"overlap"`` (Spuren
    überlappen stark, Bild dunkler) oder ``"ok"``."""
    r = spot_mm / interval_mm
    if r < GAP_RATIO:
        return "gaps"
    if r > OVERLAP_RATIO:
        return "overlap"
    return "ok"


def verdict_text(interval_mm: float, spot_mm: float) -> str:
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


def _blur(track: np.ndarray, sigma_px: float) -> np.ndarray:
    """Gauß-Strahl (σ in Bildpunkten); Energie so normiert, dass die Mitte
    einer langen Linie mit voller Leistung 1 ist."""
    if sigma_px < 0.3:
        return track
    import cv2
    half = max(1, int(math.ceil(3.0 * sigma_px)))
    k = cv2.getGaussianKernel(2 * half + 1, sigma_px, cv2.CV_64F)
    e = cv2.sepFilter2D(track, cv2.CV_64F, k, k, borderType=cv2.BORDER_CONSTANT)
    return e / float(k.max())


def simulate_spot(pixels: np.ndarray, interval_mm: float, spot_mm: float,
                  dot_width_mm: float = 0.0,
                  max_pixels: int = MAX_PREVIEW_PIXELS) -> tuple[np.ndarray, SpotInfo]:
    """Vorschaupixel (uint8, 0 = volle Leistung, 255 = nicht lasern; ein Pixel
    je Laserpunkt, Zeilen = Rasterzeilen) → Bild der gelaserten Spuren mit
    der Punktgröße ``spot_mm`` (uint8, 0 = schwarz) und :class:`SpotInfo`."""
    if not interval_mm > 0:
        raise ValueError("Linienabstand muss größer als 0 sein")
    spot = clamp_spot(spot_mm)
    px = np.asarray(pixels, dtype=np.uint8)
    if px.ndim != 2 or px.size == 0:
        raise ValueError("leere Vorschau")
    sub = subsamples(interval_mm, spot)
    rows, cols = px.shape
    y0, x0, ch, cw = _crop(rows, cols, max(1, int(max_pixels) // (sub * sub)))
    # Rand mitnehmen, damit Spuren knapp außerhalb in den Ausschnitt strahlen.
    m = int(math.ceil(1.5 * spot / interval_mm)) + 1
    t, lft = min(m, y0), min(m, x0)
    b, r = min(m, rows - y0 - ch), min(m, cols - x0 - cw)
    part = px[y0 - t:y0 + ch + b, x0 - lft:x0 + cw + r]
    dw = max(0.0, min(float(dot_width_mm), interval_mm)) / interval_mm
    track = track_map(part, sub, dw)
    energy = _blur(track, spot * SIGMA_PER_SPOT / interval_mm * sub)
    # Mitte einer Linie mit voller Leistung = genau Schwarz.
    dark = np.minimum(1.0, (1.0 - np.exp(-GAIN * energy)) / (1.0 - math.exp(-GAIN)))
    out = np.clip(np.rint(255.0 * (1.0 - dark)), 0, 255).astype(np.uint8)
    out = out[t * sub:(t + ch) * sub, lft * sub:(lft + cw) * sub]
    info = SpotInfo(spot, float(interval_mm), sub, (cw, ch), (ch, cw) != (rows, cols),
                    float(dot_width_mm))
    return np.ascontiguousarray(out), info


def load_prefs(settings) -> tuple[bool, float]:
    """``(simulieren, Punktgröße)`` aus QSettings (ohne: aus, Vorgabe)."""
    if settings is None:
        return False, DEFAULT_SPOT_MM
    on = settings.value(SETTINGS_SIMULATE) if settings.contains(SETTINGS_SIMULATE) else False
    on = on is True or str(on).lower() in ("true", "1")
    spot = settings.value(SETTINGS_SPOT) if settings.contains(SETTINGS_SPOT) else None
    return on, clamp_spot(spot) if spot is not None else DEFAULT_SPOT_MM


def save_prefs(settings, simulate: bool, spot_mm: float) -> None:
    if settings is None:
        return
    settings.setValue(SETTINGS_SIMULATE, bool(simulate))
    settings.setValue(SETTINGS_SPOT, clamp_spot(spot_mm))
    settings.sync()
