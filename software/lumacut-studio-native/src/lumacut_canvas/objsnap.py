"""Objektfang (LightBurn *Snap to Objects*, xTool Creative Space „Ausrichtungslinien“).

Qt-frei. Beim Zeichnen, beim Verschieben von Knoten und beim Ziehen eines
Skalier-Griffs rastet ein Punkt auf markante Punkte anderer Objekte ein
(Knoten, Ecken, Kantenmitten, Mittelpunkte, Ellipsen-Quadranten, Linien-Enden,
Mitte der Arbeitsfläche). Liegt kein solcher Punkt im Fangabstand, richtet er
sich je Achse an den Kanten und Mitten der Objektboxen (und der Arbeitsfläche)
aus. Beim Verschieben einer Auswahl rasten linke Kante / Mitte / rechte Kante
bzw. obere Kante / Mitte / untere Kante der Auswahlbox auf die Kanten und Mitten
der anderen Objekte ein. Das Ergebnis enthält Hilfslinien für die Anzeige.

Die Ziele werden einmal je Zug gesammelt (:meth:`SnapTargets.from_document`);
der Fangabstand ist in Bildschirmpixeln festgelegt und wird vom Aufrufer über
den Zoom in mm umgerechnet (:func:`tolerance_mm`).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Iterable

import numpy as np

from .model import Document, Shape, rotate_point
from .workarea import WORK_HEIGHT_MM, WORK_WIDTH_MM, Rect

#: Fangabstand in Bildschirmpixeln (Maus / Touch-Modus).
SNAP_PX = 7.0
SNAP_PX_TOUCH = 14.0
#: Objekte mit mehr Knoten tragen nur Box-Ecken / Mitte bei (z. B. nachgezeichnete Bilder).
MAX_NODES_PER_SHAPE = 400
#: Höchstzahl gesammelter Fangpunkte (Rest: nur Boxen).
MAX_POINTS = 20000
_EPS = 1e-6

NODE = "Knoten"
CORNER = "Ecke"
EDGE_MID = "Kantenmitte"
CENTRE = "Mitte"
QUADRANT = "Quadrant"
END = "Endpunkt"
GROUP_CENTRE = "Gruppenmitte"
AREA_CENTRE = "Mitte der Arbeitsfläche"
AREA_CORNER = "Ecke der Arbeitsfläche"
EDGE = "Kante"
AREA_EDGE = "Rand der Arbeitsfläche"


def tolerance_mm(px_per_mm: float, touch: bool = False) -> float:
    """Fangabstand in mm beim Zoom ``px_per_mm``."""
    return (SNAP_PX_TOUCH if touch else SNAP_PX) / max(px_per_mm, 1e-9)


@dataclass
class Snap:
    """Ergebnis eines Fangs. ``x`` / ``y`` gelten nur, wo ``snapped_x`` /
    ``snapped_y`` gesetzt ist; ``point`` ist der getroffene Fangpunkt (Marke),
    ``guides`` sind Hilfslinien ``(x1, y1, x2, y2)`` in mm."""

    x: float
    y: float
    snapped_x: bool = False
    snapped_y: bool = False
    label: str = ""
    point: tuple[float, float] | None = None
    guides: list[tuple[float, float, float, float]] = field(default_factory=list)

    @property
    def snapped(self) -> bool:
        return self.snapped_x or self.snapped_y


class SnapTargets:
    """Fangpunkte und Ausrichtungslinien eines Dokuments.

    ``points``: ``(x, y, label)``; ``xs`` / ``ys``: senkrechte / waagerechte
    Ausrichtungslinien ``(wert, von, bis, label)`` – ``von`` / ``bis`` ist die
    Ausdehnung der zugehörigen Box auf der anderen Achse (für die Hilfslinie).
    """

    def __init__(self, points: Iterable[tuple[float, float, str]] = (),
                 xs: Iterable[tuple[float, float, float, str]] = (),
                 ys: Iterable[tuple[float, float, float, str]] = ()) -> None:
        self.points = list(points)
        self.xs = list(xs)
        self.ys = list(ys)
        self._pts = np.array([(p[0], p[1]) for p in self.points], dtype=float).reshape(-1, 2)
        self._xv = np.array([v[0] for v in self.xs], dtype=float)
        self._yv = np.array([v[0] for v in self.ys], dtype=float)

    def __len__(self) -> int:
        return len(self.points)

    # --- Sammeln ------------------------------------------------------------
    @classmethod
    def from_document(cls, doc: Document, exclude: Iterable[str] = (),
                      work_area: bool = True) -> "SnapTargets":
        """Ziele aller sichtbaren Objekte außer ``exclude`` (gesperrte Ebenen
        zählen – sie liegen auf dem Material; ausgeblendete nicht)."""
        skip = set(exclude)
        points: list[tuple[float, float, str]] = []
        xs: list[tuple[float, float, float, str]] = []
        ys: list[tuple[float, float, float, str]] = []
        groups: dict[str, Rect] = {}
        for s in doc.shapes:
            if s.id in skip:
                continue
            try:
                layer = doc.layer(s.layer_id)
            except KeyError:
                continue
            if not layer.visible:
                continue
            b = s.bounds()
            _box_lines(b, xs, ys)
            budget = MAX_POINTS - len(points)
            if budget > 0:
                points.extend(shape_points(s)[:budget])
            if s.groups:
                top = s.groups[0]
                groups[top] = b if top not in groups else groups[top].united(b)
        for b in groups.values():
            _box_lines(b, xs, ys)
            points.append((b.x + b.w / 2, b.y + b.h / 2, GROUP_CENTRE))
        if work_area:
            W, H = WORK_WIDTH_MM, WORK_HEIGHT_MM
            points.append((W / 2, H / 2, AREA_CENTRE))
            points.extend((x, y, AREA_CORNER) for x in (0.0, W) for y in (0.0, H))
            for v in (0.0, W / 2, W):
                xs.append((v, 0.0, H, AREA_CENTRE if v == W / 2 else AREA_EDGE))
            for v in (0.0, H / 2, H):
                ys.append((v, 0.0, W, AREA_CENTRE if v == H / 2 else AREA_EDGE))
        return cls(points, xs, ys)

    # --- Fangen ------------------------------------------------------------
    def nearest_point(self, x: float, y: float, tol: float) -> tuple[float, float, str] | None:
        """Nächster Fangpunkt höchstens ``tol`` entfernt (bei Gleichstand der zuerst gesammelte)."""
        if not len(self._pts) or tol <= 0:
            return None
        d = np.hypot(self._pts[:, 0] - x, self._pts[:, 1] - y)
        i = int(np.argmin(d))
        return self.points[i] if d[i] <= tol + _EPS else None

    def snap_point(self, x: float, y: float, tol: float) -> Snap:
        """Punkt fangen: zuerst Fangpunkte, sonst je Achse Box-Kanten / -Mitten."""
        hit = self.nearest_point(x, y, tol)
        if hit is not None:
            return Snap(hit[0], hit[1], True, True, hit[2], (hit[0], hit[1]))
        snap = Snap(x, y)
        vx = _nearest(self._xv, [x], tol)
        if vx is not None:
            value, _ = vx
            snap.x, snap.snapped_x = value, True
            snap.label = _label(self.xs, self._xv, value)
        vy = _nearest(self._yv, [y], tol)
        if vy is not None:
            value, _ = vy
            snap.y, snap.snapped_y = value, True
            snap.label = snap.label or _label(self.ys, self._yv, value)
        if snap.snapped_x:
            lo, hi = _span(self.xs, self._xv, snap.x)
            snap.guides.append((snap.x, min(lo, snap.y), snap.x, max(hi, snap.y)))
        if snap.snapped_y:
            lo, hi = _span(self.ys, self._yv, snap.y)
            snap.guides.append((min(lo, snap.x), snap.y, max(hi, snap.x), snap.y))
        return snap

    def snap_box(self, box: Rect, tol: float,
                 axes: tuple[bool, bool] = (True, True)) -> tuple[float, float, Snap]:
        """Auswahlbox ausrichten: Korrektur ``(ddx, ddy)`` so, dass linke Kante /
        Mitte / rechte Kante (oben / Mitte / unten) auf einer Ausrichtungslinie
        liegt; ``Snap.x`` / ``Snap.y`` ist der getroffene Linienwert. ``axes``:
        welche Achsen fangen dürfen (x, y)."""
        snap = Snap(box.x, box.y)
        ddx = ddy = 0.0
        hx = _nearest(self._xv, [box.x, box.x + box.w / 2, box.right], tol) if axes[0] else None
        if hx is not None:
            value, k = hx
            ddx = value - (box.x, box.x + box.w / 2, box.right)[k]
            snap.x, snap.snapped_x = value, True
            snap.label = _label(self.xs, self._xv, value)
        hy = _nearest(self._yv, [box.y, box.y + box.h / 2, box.bottom], tol) if axes[1] else None
        if hy is not None:
            value, k = hy
            ddy = value - (box.y, box.y + box.h / 2, box.bottom)[k]
            snap.y, snap.snapped_y = value, True
            snap.label = snap.label or _label(self.ys, self._yv, value)
        top, bottom = box.y + ddy, box.bottom + ddy
        left, right = box.x + ddx, box.right + ddx
        if snap.snapped_x:
            lo, hi = _span(self.xs, self._xv, snap.x)
            snap.guides.append((snap.x, min(lo, top), snap.x, max(hi, bottom)))
        if snap.snapped_y:
            lo, hi = _span(self.ys, self._yv, snap.y)
            snap.guides.append((min(lo, left), snap.y, max(hi, right), snap.y))
        return ddx, ddy, snap


def _nearest(values: np.ndarray, cands: list[float], tol: float) -> tuple[float, int] | None:
    """Nächster Linienwert zu einem der Kandidaten: ``(wert, kandidat)``."""
    if not len(values) or tol <= 0:
        return None
    best: tuple[float, float, int] | None = None
    for k, c in enumerate(cands):
        d = np.abs(values - c)
        i = int(np.argmin(d))
        if d[i] <= tol + _EPS and (best is None or d[i] < best[0] - _EPS):
            best = (float(d[i]), float(values[i]), k)
    return None if best is None else (best[1], best[2])


def _span(lines, values: np.ndarray, value: float) -> tuple[float, float]:
    idx = np.nonzero(np.abs(values - value) <= 1e-6)[0]
    return min(lines[i][1] for i in idx), max(lines[i][2] for i in idx)


def _label(lines, values: np.ndarray, value: float) -> str:
    idx = np.nonzero(np.abs(values - value) <= 1e-6)[0]
    labels = [lines[i][3] for i in idx]
    for want in (CENTRE, EDGE, AREA_CENTRE):
        if want in labels:
            return want
    return labels[0] if labels else ""


def _box_lines(b: Rect, xs: list, ys: list) -> None:
    xs.extend([(b.x, b.y, b.bottom, EDGE), (b.x + b.w / 2, b.y, b.bottom, CENTRE),
               (b.right, b.y, b.bottom, EDGE)])
    ys.extend([(b.y, b.x, b.right, EDGE), (b.y + b.h / 2, b.x, b.right, CENTRE),
               (b.bottom, b.x, b.right, EDGE)])


def _rot(g, pts: list[tuple[float, float]]) -> list[tuple[float, float]]:
    if not g.rot:
        return pts
    cx, cy = g.center()
    return [rotate_point(x, y, cx, cy, g.rot) for x, y in pts]


def shape_points(s: Shape) -> list[tuple[float, float, str]]:
    """Fangpunkte eines Objekts in Arbeitsflächen-mm (inkl. Drehung)."""
    g = s.geom
    cx, cy = g.center()
    out: list[tuple[float, float, str]] = [(cx, cy, CENTRE)]
    x0, y0, x1, y1 = g.x, g.y, g.x + g.w, g.y + g.h
    mids = [((x0 + x1) / 2, y0), (x1, (y0 + y1) / 2), ((x0 + x1) / 2, y1), (x0, (y0 + y1) / 2)]
    corners = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    if s.kind == "line":
        out += [(x, y, END) for x, y in _rot(g, [(x0, y0), (x1, y1)])]
    elif s.kind == "ellipse":
        out += [(x, y, QUADRANT) for x, y in _rot(g, mids)]
    elif s.kind == "rect" and not s.generator:
        if not s.corner_radius:
            out += [(x, y, CORNER) for x, y in _rot(g, corners)]
        out += [(x, y, EDGE_MID) for x, y in _rot(g, mids)]
    elif s.kind in ("polygon", "path") and not s.generator and len(s.points) <= MAX_NODES_PER_SHAPE:
        pts = _rot(g, s.abs_points())
        curves = set(s.curves)
        closed = s.kind == "polygon"
        for a, b in s.ring_ranges():
            ring = pts[a:b]
            out += [(x, y, NODE) for x, y in ring]
            n = len(ring)
            for i in range(n if closed else n - 1):
                if a + i in curves:
                    continue  # Kurvensegment: Sehnenmitte liegt nicht auf dem Umriss
                (px, py), (qx, qy) = ring[i], ring[(i + 1) % n]
                if math.hypot(qx - px, qy - py) > 1e-6:
                    out.append(((px + qx) / 2, (py + qy) / 2, EDGE_MID))
    else:  # Text, Bild, Codes, sehr dichte Pfade: Box-Ecken
        out += [(x, y, CORNER) for x, y in _rot(g, corners)]
    return out
