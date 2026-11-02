"""Park-corner preflight: refuse a job the Pi would refuse, before sending.

Since Pi commit 9ae8577 the Pi never lasers inside the park corner
X0..cx / Y0..cy (machine mm; head v6: 78 × 35 mm, ``PARK_CORNER_MM`` in
pi400/marlin/transport.py). The head parks and homes there. The upload
preflight refuses an *absolute* job whose powered bounding box starts in
that rectangle, and ``op=place`` refuses a job *placed* on the head or the
user origin that lands there (``placement.check_extent``). The Studio work
area only knows the 30 mm L-shaped safe zone, so without this check a motif
in the top-right corner of the canvas – or any motif placed on the default
user origin (30, 30) – passed the Studio and failed at send/start time.

This module computes the job's powered extent exactly like the Pi
(:func:`powered_bounds` = ``placement.scan``), applies the origin placement
like ``web.make_placement`` (:func:`placement_offset`) and checks it
against the park corner the Pi reports in ``/api/status``
(``park_corner_mm``), falling back to :data:`PARK_CORNER_MM` for a Pi that
does not report it. Pure functions, no Qt; the Qt hook is
:func:`attach_park_check`.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any, Callable

#: Mirror of ``PARK_CORNER_MM`` in pi400/marlin/transport.py (head v6:
#: housing 67 × 24 mm from the beam plus 10 mm). Used only when the Pi does
#: not report ``park_corner_mm``; tests/test_park_corner.py keeps it equal.
PARK_CORNER_MM: tuple[float, float] = (78.0, 35.0)

#: Anchor names by visible corner (Pi ``placement.ANCHORS``, convention
#: "origin_top_right": "t" = small Y, "r" = small X).
ANCHORS = ("tl", "tr", "bl", "br", "center")
COORD_CONVENTION = "origin_top_right"

_EPS = 1e-6
_WORD = re.compile(r"([A-Z])\s*([-+]?(?:\d+(?:\.\d*)?|\.\d+))")
_MOTION = re.compile(r"^G0?([0-3])(?=\s|[A-Z]|$)")


@dataclass(frozen=True)
class Box:
    """Axis-parallel box in machine mm."""

    xmin: float
    ymin: float
    xmax: float
    ymax: float

    def shifted(self, dx: float, dy: float) -> "Box":
        return Box(self.xmin + dx, self.ymin + dy, self.xmax + dx, self.ymax + dy)


@dataclass(frozen=True)
class ParkCheck:
    """Result of :func:`check_job` (``ok`` = the Pi accepts the extent)."""

    ok: bool
    message: str = ""
    bounds: Box | None = None          # powered extent after placement
    corner: tuple[float, float] = PARK_CORNER_MM
    #: Shortest shift out of the corner: (towards +X, towards +Y) in mm.
    shift_mm: tuple[float, float] = (0.0, 0.0)


def _normalize(line: str) -> str:
    """Upper case, comments removed (like ``transport.normalize``)."""
    line = line.split(";", 1)[0]
    line = re.sub(r"\([^)]*\)", "", line)
    return " ".join(line.upper().split())


def _arc_points(x0, y0, x1, y1, words, clockwise):
    points = [(x0, y0), (x1, y1)]
    if "R" in words:
        r = abs(words["R"])
        mx, my = (x0 + x1) / 2, (y0 + y1) / 2
        return points + [(mx - 2 * r, my - 2 * r), (mx + 2 * r, my + 2 * r)]
    cx, cy = x0 + words.get("I", 0.0), y0 + words.get("J", 0.0)
    r = math.hypot(x0 - cx, y0 - cy)
    a0 = math.atan2(y0 - cy, x0 - cx)
    a1 = math.atan2(y1 - cy, x1 - cx)
    if clockwise:
        a0, a1 = a1, a0
    sweep = (a1 - a0) % (2 * math.pi) or 2 * math.pi
    for k in range(4):
        angle = k * math.pi / 2
        if (angle - a0) % (2 * math.pi) <= sweep + 1e-9:
            points.append((cx + r * math.cos(angle), cy + r * math.sin(angle)))
    return points


def powered_bounds(gcode: str | list[str]) -> Box | None:
    """Bounding box of the powered moves (G1..G3 while S > 0), like the
    Pi's ``placement.scan``: G0 and M5 switch the beam off, an S word on a
    G1..G3 sets it, a G1 without S keeps the previous state. None if the
    job never lasers."""
    lines = gcode.splitlines() if isinstance(gcode, str) else gcode
    x = y = None
    absolute = True
    cutting = False
    xs: list[float] = []
    ys: list[float] = []
    for raw in lines:
        cmd = _normalize(raw)
        if not cmd:
            continue
        if cmd.startswith("M5"):
            cutting = False
            continue
        if cmd in ("G90", "G91"):
            absolute = cmd == "G90"
            continue
        if cmd == "G28" or cmd.startswith("G28 "):
            x, y = 0.0, 0.0
            continue
        m = _MOTION.match(cmd)
        if not m:
            continue
        code = int(m.group(1))
        words = {k: float(v) for k, v in _WORD.findall(cmd[m.end():])}
        if absolute:
            nx, ny = words.get("X", x), words.get("Y", y)
        else:
            nx = None if x is None else x + words.get("X", 0.0)
            ny = None if y is None else y + words.get("Y", 0.0)
        if code == 0:
            cutting = False
        elif "S" in words:
            cutting = words["S"] > 0
        if nx is None or ny is None:
            x, y = nx, ny
            continue
        if code in (2, 3) and x is not None and y is not None:
            pts = _arc_points(x, y, nx, ny, words, clockwise=code == 2)
        else:
            pts = [(nx, ny)] + ([(x, y)] if x is not None and y is not None else [])
        if cutting and code != 0:
            for px, py in pts:
                xs.append(px)
                ys.append(py)
        x, y = nx, ny
    if not xs:
        return None
    return Box(min(xs), min(ys), max(xs), max(ys))


def anchor_point(box: Box, anchor: str) -> tuple[float, float]:
    """Motif point that lands on the origin (visible corner names)."""
    if anchor not in ANCHORS:
        raise ValueError("Bezugspunkt muss einer von %s sein" % ", ".join(ANCHORS))
    if anchor == "center":
        return (box.xmin + box.xmax) / 2, (box.ymin + box.ymax) / 2
    return (box.xmin if anchor[1] == "r" else box.xmax,
            box.ymin if anchor[0] == "t" else box.ymax)


def visible_anchor(wire: str, convention: str | None) -> str:
    """Anchor name the Pi got -> visible corner (``client.wire_anchor``,
    an involution: an older Pi without ``coord_convention`` swaps l/r)."""
    if convention == COORD_CONVENTION or wire not in ("tl", "tr", "bl", "br"):
        return wire
    return wire[0] + ("r" if wire[1] == "l" else "l")


def placement_offset(bounds: Box, origin: str, anchor: str,
                     target: tuple[float, float] | None) -> tuple[float, float]:
    """(dx, dy) the Pi applies (``web.make_placement``); (0, 0) for absolute."""
    if origin == "absolute":
        return 0.0, 0.0
    if target is None:
        raise ValueError("Ursprung unbekannt")
    ax, ay = anchor_point(bounds, anchor)
    return round(target[0] - ax, 3), round(target[1] - ay, 3)


def in_corner(box: Box, corner: tuple[float, float]) -> bool:
    """True when the box reaches into the corner (Pi: box start inside it)."""
    cx, cy = corner
    return box.xmin < cx - _EPS and box.ymin < cy - _EPS


def _fmt(v: float) -> str:
    return ("%.1f" % v).rstrip("0").rstrip(".")


ORIGIN_NAMES = {"absolute": "Absolut", "current": "Kopfposition", "user": "Benutzer-Ursprung"}


def check_job(gcode: str, corner: tuple[float, float] = PARK_CORNER_MM, *,
              origin: str = "absolute", anchor: str = "tr",
              target: tuple[float, float] | None = None,
              cutting_bounds: tuple[float, float, float, float] | None = None) -> ParkCheck:
    """Check the powered extent of ``gcode`` after placement.

    ``origin``/``anchor`` are the visible choice (``anchor`` in the
    "origin_top_right" convention), ``target`` the origin point in machine
    mm (head XY for "current", stored user origin for "user").
    ``cutting_bounds`` (x_min, y_min, x_max, y_max) adds the travel check
    the Pi does as well. A job without powered moves, or a placement whose
    origin is unknown, passes (the Pi decides).
    """
    corner = (float(corner[0]), float(corner[1]))
    box = powered_bounds(gcode)
    if box is None:
        return ParkCheck(True, corner=corner)
    try:
        dx, dy = placement_offset(box, origin, anchor, target)
    except ValueError:
        return ParkCheck(True, corner=corner)
    placed = box.shifted(dx, dy)
    where = ("" if origin == "absolute" else
             " am Ursprung „%s“" % ORIGIN_NAMES.get(origin, origin))
    span = "X%s–%s / Y%s–%s mm" % (_fmt(placed.xmin), _fmt(placed.xmax),
                                    _fmt(placed.ymin), _fmt(placed.ymax))
    if cutting_bounds is not None:
        x0, y0, x1, y1 = cutting_bounds
        if (placed.xmin < x0 - _EPS or placed.ymin < y0 - _EPS or
                placed.xmax > x1 + _EPS or placed.ymax > y1 + _EPS):
            return ParkCheck(False, "Motiv%s (%s) liegt außerhalb des Schneidbereichs "
                             "X%s–%s / Y%s–%s mm – der Pi würde den Auftrag ablehnen."
                             % (where, span, _fmt(x0), _fmt(x1), _fmt(y0), _fmt(y1)),
                             placed, corner)
    if not in_corner(placed, corner):
        return ParkCheck(True, bounds=placed, corner=corner)
    sx, sy = corner[0] - placed.xmin, corner[1] - placed.ymin
    msg = ("Motiv%s (%s) reicht in die Park-Ecke X0–%s / Y0–%s mm. Dort parkt der "
           "Laserkopf, der Pi lasert dort nicht und würde den Auftrag ablehnen. "
           "Motiv um mindestens %s mm nach links (X+) oder %s mm nach unten (Y+) "
           "verschieben%s." % (where, span, _fmt(corner[0]), _fmt(corner[1]),
                                _fmt(math.ceil(sx * 10) / 10), _fmt(math.ceil(sy * 10) / 10),
                                "" if origin == "absolute"
                                else " oder den Ursprung/Bezugspunkt ändern"))
    return ParkCheck(False, msg, placed, corner, (sx, sy))


# ------------------------------------------------------------ Pi status
def _status_raw(status: Any) -> dict:
    raw = getattr(status, "raw", None) if status is not None else None
    return raw if isinstance(raw, dict) else (status if isinstance(status, dict) else {})


def _num(v: Any) -> float | None:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    return float(v) if math.isfinite(v) else None


def corner_from_status(status: Any) -> tuple[float, float]:
    """Park corner reported by the Pi (``park_corner_mm``), else the mirror."""
    pc = _status_raw(status).get("park_corner_mm")
    if isinstance(pc, dict):
        x, y = _num(pc.get("x")), _num(pc.get("y"))
        if x is not None and y is not None and x >= 0 and y >= 0:
            return x, y
    return PARK_CORNER_MM


def cutting_bounds_from_status(status: Any) -> tuple[float, float, float, float] | None:
    cb = _status_raw(status).get("cutting_bounds")
    if not isinstance(cb, dict):
        return None
    vals = [_num(cb.get(k)) for k in ("x_min", "y_min", "x_max", "y_max")]
    if any(v is None for v in vals) or vals[2] <= vals[0] or vals[3] <= vals[1]:
        return None
    return tuple(vals)  # type: ignore[return-value]


def origin_target(status: Any, origin: str) -> tuple[float, float] | None:
    """Origin point the Pi would use: head XY or stored user origin."""
    if status is None or origin == "absolute":
        return None
    if origin == "user":
        user = getattr(getattr(status, "origin", None), "user", None)
        return (float(user[0]), float(user[1])) if user else None
    if origin == "current":
        pos = getattr(status, "position", None)
        return (float(pos[0]), float(pos[1])) if pos else None
    return None


def check_for_panel(machine_panel: Any, gcode: str, origin: str | None = None) -> ParkCheck:
    """Check ``gcode`` against the panel's Pi status and job origin.

    ``origin`` None = the origin chosen in the panel (``job_origin()``,
    wire anchor converted back to the visible corner); "absolute" = as sent.
    """
    status = getattr(machine_panel, "_status", None)
    anchor = "tr"
    if origin is None:
        origin, wire = ("absolute", "tr")
        job_origin = getattr(machine_panel, "job_origin", None)
        if callable(job_origin):
            origin, wire = job_origin()
        anchor = visible_anchor(wire, getattr(status, "coord_convention", None))
    return check_job(gcode, corner_from_status(status), origin=origin, anchor=anchor,
                     target=origin_target(status, origin),
                     cutting_bounds=cutting_bounds_from_status(status))


# ------------------------------------------------------------ Qt hook
def attach_park_check(machine_panel: Any, report: Callable[[str], None] | None = None):
    """Wrap ``machine_panel.send_gcode`` with the park-corner preflight.

    Every Studio send (canvas, Ablauf, relief, material test, history) goes
    through ``send_gcode``. The upload itself is checked as absolute (the Pi
    upload preflight refuses an absolute motif in the corner); a one-click
    ``autorun`` is checked at the chosen origin too. A refused send returns
    False and nothing is uploaded; a plain send whose motif would land in
    the corner at the chosen origin (for a later "Start") is uploaded with a
    warning, the origin may still change before the start.
    Returns the original method.
    """
    original = machine_panel.send_gcode

    def show(text: str, bad: bool = True) -> None:
        shower = getattr(machine_panel, "_show_message", None)
        if callable(shower):
            try:
                from machine.panel import BAD, WARN
                shower(text, BAD if bad else WARN)
            except Exception:  # noqa: BLE001 - message only
                pass
        if report is not None:
            report(text)

    def send_gcode(name, gcode, start=False, **kwargs):
        if getattr(machine_panel, "_client", None) is not None:
            absolute = check_for_panel(machine_panel, gcode, "absolute")
            if not absolute.ok:
                show("Nicht gesendet: " + absolute.message)
                return False
            # start=True runs as sent (absolute); autorun and a later "Start"
            # use the origin chosen in the panel.
            placed = None if start and not kwargs.get("autorun") else \
                check_for_panel(machine_panel, gcode)
            if placed is not None and not placed.ok:
                if kwargs.get("autorun"):
                    show("Nicht gestartet: " + placed.message)
                    return False
                show("Gesendet, aber Start am gewählten Ursprung nicht möglich: "
                     + placed.message, bad=False)
        return original(name, gcode, start=start, **kwargs)

    machine_panel.send_gcode = send_gcode
    return original
