"""Erreichbarkeit des Tasters für ``op=autorun`` – dieselbe Rechnung wie der Pi.

Der Pi (``pi400/marlin/heightmap.py`` + ``transport.probe_reachable``, Stand
``b966c89`` „Motive bis an den Rand lasern“) legt je Motivbereich ein kleines
Raster (1×1 … 4×4) und tastet einen Laserpunkt P direkt ab, wenn der Kopf dafür
in ``X10…380 / Y10…360`` bleibt (Laser aus, Kopf darf in die Safezone)::

    Kopf = P − Tasterversatz          (Versatz = Tasterspitze − Laserpunkt)
    10 ≤ Px − dx ≤ 380,  10 ≤ Py − dy ≤ 360

10/380/360 = Marlin ``PROBING_MARGIN`` 10 mm vor 0 bzw. ``X/Y_BED_SIZE`` 390/370.
Mit dem Versatz −23/+15: Laserpunkte X−13…357 / Y25…375, auf der Arbeitsfläche
also X30…357 / Y30…370 – nur der linke Streifen (Bildschirm x < 33) fehlt.

Ein Rasterpunkt außerhalb wird am **nächsten erreichbaren Ort höchstens 40 mm
daneben** abgetastet (``heightmap.nearest_reachable``, 1-mm-Raster), dessen Höhe
gilt für den Punkt (Ersatzpunkt, Anforderungen 2026-10-26 §2.4). Abgelehnt
(„Kein Abtastpunkt erreichbar“) wird nur, wenn auch so kein Punkt erreichbar ist.

Bildschirm (Canvas, oben links, x nach rechts): ``Maschine = (390 − x, 30 + y)``.
Großes Maschinen-X ist also **links**, großes Y **vorn/unten**.

Hier wird das Raster des Pi nachgerechnet, damit Studio vor dem Hochladen warnt,
an welcher Seite daneben gemessen wird. Test gegen den Pi-Code:
``test_probe_reach.py`` (Konstanten, Punktzahl, Ersatzpunkte).
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any, Iterable, Optional, Sequence

from .geometry import PROBE_OFFSET_MM, SUBSTITUTE_MAX_MM

# --- Pi-Konstanten (pi400/marlin/heightmap.py, transport.py, web.py) ---------
CELL_MM = 5.0
REGION_GAP_MM = 10.0
REGION_MARGIN_MM = 2.0
GRID_INSET_MM = 5.0
GRID_SPACING_MM = 90.0
MAX_PER_SIDE = 4
MAX_REGIONS = 12
MAX_TOTAL_POINTS = 36
SAFE_ZONE_MM = 30.0
PROBE_HEAD_MIN = (10.0, 10.0)      # transport.PROBE_HEAD_MIN (b966c89)
PROBE_HEAD_MAX = (380.0, 360.0)
SUBSTITUTE_STEP_MM = 1.0
TRAVEL = (390.0, 370.0)
SCREEN_X0 = 390.0   # Maschine_x = 390 − Bildschirm_x
SCREEN_Y0 = 30.0    # Maschine_y = 30 + Bildschirm_y

PI_UNREACHABLE = "Kein Abtastpunkt erreichbar"

_WORD = re.compile(r"([A-Z])\s*([-+]?(?:\d+(?:\.\d*)?|\.\d+))")


@dataclass(frozen=True)
class Box:
    xmin: float
    ymin: float
    xmax: float
    ymax: float


@dataclass
class Region:
    box: Box
    xs: list
    ys: list


def laser_reach(offset=PROBE_OFFSET_MM) -> Box:
    """Laserpunkte (Maschinen-mm), an die der Taster kommt – ohne Arbeitsflächen-Schnitt."""
    dx, dy = offset
    return Box(PROBE_HEAD_MIN[0] + dx, PROBE_HEAD_MIN[1] + dy,
               PROBE_HEAD_MAX[0] + dx, PROBE_HEAD_MAX[1] + dy)


def in_box(x: float, y: float, b: Box) -> bool:
    """Wie ``transport._probe_head_ok`` (Kopf = Punkt − Versatz), exakte Grenzen."""
    return b.xmin <= x <= b.xmax and b.ymin <= y <= b.ymax


def pi_reachable(offset=PROBE_OFFSET_MM):
    """``transport.probe_reachable`` als Funktion (Laserpunkt → bool)."""
    dx, dy = offset

    def ok(x: float, y: float) -> bool:
        hx, hy = x - dx, y - dy
        return (PROBE_HEAD_MIN[0] <= hx <= PROBE_HEAD_MAX[0]
                and PROBE_HEAD_MIN[1] <= hy <= PROBE_HEAD_MAX[1])
    return ok


def nearest_reachable(x: float, y: float, reachable, max_mm: float = SUBSTITUTE_MAX_MM,
                      step: float = SUBSTITUTE_STEP_MM) -> Optional[tuple]:
    """Wie ``heightmap.nearest_reachable``: nächster erreichbarer Ort im 1-mm-Raster
    um (x, y), höchstens ``max_mm`` entfernt, sonst ``None``."""
    n = int(max_mm / step)
    best = None
    for i in range(-n, n + 1):
        for j in range(-n, n + 1):
            d = math.hypot(i * step, j * step)
            if d > max_mm or (best is not None and d >= best[0]):
                continue
            px, py = x + i * step, y + j * step
            if reachable(px, py):
                best = (d, (px, py))
    return None if best is None else best[1]


def work_reach(offset=PROBE_OFFSET_MM) -> Box:
    """Abtastbarer Teil der Arbeitsfläche X30…390 / Y30…370 (Maschinen-mm)."""
    r = laser_reach(offset)
    return Box(max(r.xmin, SAFE_ZONE_MM), max(r.ymin, SAFE_ZONE_MM),
               min(r.xmax, TRAVEL[0]), min(r.ymax, TRAVEL[1]))


def screen_box(b: Box) -> Box:
    """Maschinen-Box → Bildschirm-mm (oben links, x nach rechts)."""
    return Box(SCREEN_X0 - b.xmax, b.ymin - SCREEN_Y0, SCREEN_X0 - b.xmin, b.ymax - SCREEN_Y0)


@dataclass(frozen=True)
class Substitute:
    """Ein nicht erreichbarer Abtastpunkt und sein Ersatz (Maschinen-mm)."""
    x: float
    y: float
    probe_x: float
    probe_y: float

    @property
    def distance_mm(self) -> float:
        return math.hypot(self.probe_x - self.x, self.probe_y - self.y)

    @property
    def sides(self) -> tuple:
        """Bildschirmseiten: großes Maschinen-X = links, kleines Y = oben."""
        out = []
        if self.x > self.probe_x + 1e-6:
            out.append("links")
        elif self.x < self.probe_x - 1e-6:
            out.append("rechts")
        if self.y < self.probe_y - 1e-6:
            out.append("oben")
        elif self.y > self.probe_y + 1e-6:
            out.append("unten")
        return tuple(out)


def clamp(x: float, y: float, box: Box) -> tuple:
    """Nächster Punkt im Abtastbereich (Regel Anforderungen §2.4: Ersatzpunkt)."""
    return (min(max(x, box.xmin), box.xmax), min(max(y, box.ymin), box.ymax))


def substitute(x: float, y: float, box: Box, tol: float = 1e-6) -> Optional[Substitute]:
    """``None``, wenn (x, y) erreichbar ist, sonst der geklemmte Ersatzpunkt."""
    px, py = clamp(x, y, box)
    if abs(px - x) <= tol and abs(py - y) <= tol:
        return None
    return Substitute(x, y, px, py)


_SIDE_TEXT = {"links": "am linken Rand (Maschine X > {xmax:g})",
              "rechts": "am rechten Rand (Maschine X < {xmin:g})",
              "oben": "am oberen/hinteren Rand (Maschine Y < {ymin:g})",
              "unten": "am unteren/vorderen Rand (Maschine Y > {ymax:g})"}

DANGER_NOTE = ("Ist das Werkstück dort kleiner, landet der Taster neben dem Werkstück auf "
               "dem Bett und die Höhe stimmt am Rand nicht. Gelasert wird trotzdem.")


def substitution_warning(subs: Sequence[Substitute], box: Box) -> str:
    """Ein deutscher Satz wie in Anforderungen §2.4 (gleicher Wortlaut Studio/Pi/Android)."""
    if not subs:
        return ""
    order = ("links", "rechts", "oben", "unten")
    sides = [s for s in order if any(s in sb.sides for sb in subs)]
    where = " und ".join(_SIDE_TEXT[s].format(xmin=box.xmin, xmax=box.xmax, ymin=box.ymin,
                                              ymax=box.ymax) for s in sides)
    n = len(subs)
    far = max(sb.distance_mm for sb in subs)
    return (f"Achtung: {n} Abtastpunkt{'e' if n != 1 else ''} {where} nicht erreichbar – "
            f"stattdessen bis {_mm_round(far)} mm daneben gemessen. {DANGER_NOTE}")


def _mm_round(v: float) -> str:
    return f"{math.ceil(v * 10 - 1e-9) / 10:g}"


def _powered_points(lines: Iterable[str]):
    """Wie ``heightmap._powered_points`` (Punkte ≤ 2,5 mm auf jedem G1 mit Laser an)."""
    x = y = 0.0
    absolute, cutting = True, False
    step = CELL_MM / 2
    for raw in lines:
        line = re.sub(r"\([^)]*\)", "", raw.split(";", 1)[0]).strip().upper()
        if not line:
            continue
        words = _WORD.findall(line)
        modes = [int(float(v)) for k, v in words if k == "G" and float(v).is_integer()]
        if 90 in modes:
            absolute = True
        if 91 in modes:
            absolute = False
        if line.startswith("M5"):
            cutting = False
        if 0 not in modes and 1 not in modes:
            continue
        vals = {k: float(v) for k, v in words if k in "XYS"}
        nx = (vals["X"] if absolute else x + vals["X"]) if "X" in vals else x
        ny = (vals["Y"] if absolute else y + vals["Y"]) if "Y" in vals else y
        if 0 in modes:
            cutting = False
        if 1 in modes:
            if "S" in vals:
                cutting = vals["S"] > 0
            if cutting and (nx, ny) != (x, y):
                n = max(1, math.ceil(math.hypot(nx - x, ny - y) / step))
                for k in range(n + 1):
                    yield x + (nx - x) * k / n, y + (ny - y) * k / n
        x, y = nx, ny


def _regions(lines) -> list[Box]:
    cells: dict = {}
    for px, py in _powered_points(lines):
        key = (int(px // CELL_MM), int(py // CELL_MM))
        b = cells.get(key)
        cells[key] = (px, py, px, py) if b is None else (
            min(b[0], px), min(b[1], py), max(b[2], px), max(b[3], py))
    if not cells:
        return []
    reach = int(math.ceil(REGION_GAP_MM / CELL_MM))
    seen, regions = set(), []
    for start in cells:
        if start in seen:
            continue
        seen.add(start)
        stack, ext = [start], list(cells[start])
        while stack:
            cx, cy = stack.pop()
            for ddx in range(-reach, reach + 1):
                for ddy in range(-reach, reach + 1):
                    key = (cx + ddx, cy + ddy)
                    if key in cells and key not in seen:
                        seen.add(key)
                        stack.append(key)
                        b = cells[key]
                        ext = [min(ext[0], b[0]), min(ext[1], b[1]),
                               max(ext[2], b[2]), max(ext[3], b[3])]
        regions.append(ext)
    if len(regions) > MAX_REGIONS:
        regions = [[min(r[0] for r in regions), min(r[1] for r in regions),
                    max(r[2] for r in regions), max(r[3] for r in regions)]]
    m, lo = REGION_MARGIN_MM, SAFE_ZONE_MM
    out = [Box(max(lo, r[0] - m), max(lo, r[1] - m), min(TRAVEL[0], r[2] + m),
               min(TRAVEL[1], r[3] + m)) for r in regions]
    return sorted(out, key=lambda b: (b.ymin, b.xmin))


def _per_side(length: float) -> int:
    if length < 4 * GRID_INSET_MM:
        return 1
    return min(MAX_PER_SIDE, max(2, math.ceil(length / GRID_SPACING_MM) + 1))


def _axis(lo: float, hi: float, n: int) -> list:
    if n == 1:
        return [(lo + hi) / 2]
    inset = min(GRID_INSET_MM, (hi - lo) / 4)
    step = (hi - lo - 2 * inset) / (n - 1)
    return [lo + inset + i * step for i in range(n)]


def probe_regions(gcode: str | Sequence[str]) -> list[Region]:
    """Motivbereiche mit den Rasterkoordinaten, die der Pi abtasten will."""
    lines = gcode.splitlines() if isinstance(gcode, str) else list(gcode)
    boxes = _regions(lines)
    sizes = [[_per_side(b.xmax - b.xmin), _per_side(b.ymax - b.ymin)] for b in boxes]
    while sum(c * r for c, r in sizes) > MAX_TOTAL_POINTS:
        i = max(range(len(sizes)), key=lambda k: (max(sizes[k]), sizes[k][0] * sizes[k][1]))
        c, r = sizes[i]
        if c == r == 1:
            break
        sizes[i] = [max(1, v) for v in ([c - 1, r] if c >= r else [c, r - 1])]
    return [Region(b, _axis(b.xmin, b.xmax, c), _axis(b.ymin, b.ymax, r))
            for b, (c, r) in zip(boxes, sizes)]


def _shift(values: Sequence[float], lo: float, hi: float) -> float:
    """Nötige Verschiebung (Maschinen-mm, mit Vorzeichen), damit ein Wert in [lo, hi] fällt."""
    if any(lo - 1e-9 <= v <= hi + 1e-9 for v in values):
        return 0.0
    if min(values) > hi:
        return hi - min(values)
    return lo - max(values)


@dataclass
class ReachReport:
    """Ergebnis der Vorprüfung. ``ok`` = alle Punkte direkt erreichbar.

    Nicht erreichbare Punkte sind **kein Fehler** mehr (Besitzer-Regel §2.4):
    ``substitutes`` nennt die Ersatzpunkte, ``warning`` den Satz dazu.
    ``fallback_point`` ist gesetzt, wenn **kein** Rasterpunkt erreichbar ist:
    dann misst Studio über ``op=autorun`` mit ``x``/``y`` an dieser Stelle.
    """
    ok: bool
    reachable_points: int
    total_points: int
    shift_x: float = 0.0          # Maschinen-mm, nötig für den nächstliegenden Bereich
    shift_y: float = 0.0
    offset: tuple = PROBE_OFFSET_MM
    message: str = ""             # Seite/Verschiebung (nur wenn nichts erreichbar)
    substitutes: list = None
    warning: str = ""
    fallback_point: Optional[tuple] = None
    nearest_point: Optional[tuple] = None   # erreichbarer Punkt am nächsten zum Motiv

    def __post_init__(self):
        if self.substitutes is None:
            self.substitutes = []

    @property
    def none_reachable(self) -> bool:
        return self.total_points > 0 and self.reachable_points == 0


def _mm(v: float) -> int:
    return int(math.ceil(abs(v) - 1e-9)) + 1   # 1 mm Luft


def describe(shift_x: float, shift_y: float, offset=PROBE_OFFSET_MM) -> str:
    """Deutscher Satz: welche Seite, wie weit, wohin schieben, abtastbarer Bereich."""
    reach = laser_reach(offset)
    work = work_reach(offset)
    scr = screen_box(work)
    sides, moves = [], []
    if shift_x < 0:   # Motiv bei zu großem Maschinen-X = links auf dem Bildschirm
        sides.append(f"zu weit links (Maschine X > {reach.xmax:g})")
        moves.append(f"{_mm(shift_x)} mm nach rechts")
    elif shift_x > 0:
        sides.append(f"zu weit rechts (Maschine X < {reach.xmin:g})")
        moves.append(f"{_mm(shift_x)} mm nach links")
    if shift_y > 0:   # zu kleines Y = oben/hinten
        sides.append(f"zu weit oben/hinten (Maschine Y < {reach.ymin:g})")
        moves.append(f"{_mm(shift_y)} mm nach unten")
    elif shift_y < 0:
        sides.append(f"zu weit unten/vorn (Maschine Y > {reach.ymax:g})")
        moves.append(f"{_mm(shift_y)} mm nach oben")
    dx, dy = offset
    text = (f"Kein Abtastpunkt erreichbar: Der Taster (Versatz X{dx:+g}/Y{dy:+g} mm) "
            f"kommt an keine Stelle des Motivs.")
    if sides:
        text += " Motiv liegt " + " und ".join(sides) + ". Motiv um mind. " + \
            " und ".join(moves) + " schieben, dann neu starten."
    text += (f" Abtastbar ist auf dem Bildschirm x {scr.xmin:g}–{scr.xmax:g} mm, "
             f"y {scr.ymin:g}–{scr.ymax:g} mm (von links/oben; Maschine X{work.xmin:g}–"
             f"{work.xmax:g}, Y{work.ymin:g}–{work.ymax:g}).")
    return text


def check_gcode(gcode, offset=PROBE_OFFSET_MM) -> ReachReport:
    """Rechnet wie der Pi (``heightmap._mark_reachable``): direkt erreichbare Punkte,
    Ersatzpunkte ≤ 40 mm daneben (Warnung, kein Abbruch) und nicht erreichbare.

    ``reachable_points`` zählt wie der Pi (direkt + mit Ersatzpunkt). Ist gar keiner
    erreichbar, gibt es ``fallback_point`` (nächster Punkt im Abtastbereich der
    Arbeitsfläche) und ``message`` (Seite, mm).
    """
    reach = laser_reach(offset)
    box = work_reach(offset)
    ok_fn = pi_reachable(offset)
    regions = probe_regions(gcode)
    pts = [(x, y) for r in regions for y in r.ys for x in r.xs]
    subs, lost, direct = [], 0, 0
    for x, y in pts:
        if ok_fn(x, y):
            direct += 1
            continue
        near = nearest_reachable(x, y, ok_fn)
        if near is None:
            lost += 1
        else:
            subs.append(Substitute(x, y, near[0], near[1]))
    rep = ReachReport(ok=not subs and not lost, reachable_points=direct + len(subs),
                      total_points=len(pts), offset=tuple(offset), substitutes=subs,
                      warning=substitution_warning(subs, reach))
    if pts:
        nx, ny = min(pts, key=lambda p: math.hypot(clamp(*p, box)[0] - p[0],
                                                   clamp(*p, box)[1] - p[1]))
        rep.nearest_point = clamp(nx, ny, box)
    if rep.none_reachable:
        best = min(((_shift(r.xs, reach.xmin, reach.xmax), _shift(r.ys, reach.ymin, reach.ymax))
                    for r in regions), key=lambda s: abs(s[0]) + abs(s[1]))
        rep.shift_x, rep.shift_y = best
        rep.message = describe(*best, offset=offset)
        rep.fallback_point = rep.nearest_point
        rep.warning = substitution_warning(
            [Substitute(nx, ny, *rep.fallback_point)], reach)
    return rep


def pi_offset(status: Any) -> tuple:
    """Tasterversatz aus ``/api/status`` → ``probe_xy_offset_mm``, sonst Standardwert."""
    raw = getattr(status, "raw", None)
    val = raw.get("probe_xy_offset_mm") if isinstance(raw, dict) else None
    try:
        if val is not None and len(val) == 2:
            return (float(val[0]), float(val[1]))
    except (TypeError, ValueError):
        pass
    return PROBE_OFFSET_MM


def explain_pi_error(text: str, gcode=None, offset=PROBE_OFFSET_MM) -> str:
    """HTTP-400-Text des Pi „Kein Abtastpunkt erreichbar …“ verständlich machen.

    Mit G-Code (Ursprung „Absolut“) wird die Seite nachgerechnet, sonst nur der
    abtastbare Bereich genannt. Andere Fehlertexte bleiben unverändert.
    """
    if PI_UNREACHABLE not in (text or ""):
        return text
    if gcode is not None:
        rep = check_gcode(gcode, offset)
        if rep.none_reachable:
            return rep.message
    return describe(0.0, 0.0, offset)
