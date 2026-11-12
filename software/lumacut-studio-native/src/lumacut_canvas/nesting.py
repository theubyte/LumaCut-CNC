"""Verschachteln (Nesting): Teile platzsparend auf das Material legen.

Wie LightBurns *Nesting* (Quick Nest = Hüllboxen, True Nest = echte Form) und
xTools „Intelligentes Verschachteln“: Die ausgewählten Teile (eine äußerste
Gruppe zählt als ein Teil) werden – größte zuerst – in einen Bereich gelegt:
ein ausgewähltes Rechteck (das Material, bleibt stehen) oder die Arbeitsfläche.
Optional dürfen sie in 90°- oder 45°-Schritten gedreht werden; andere sichtbare
Objekte im Bereich werden ausgespart, Objekte innerhalb eines Teils (Gravur in
einer Platte, Löcher als eigene Objekte) bleiben mit ihm zusammen.

Verfahren (Rasterverfahren, „bottom-left fill“): Der Bereich wird in Zellen
von ``res`` mm zerlegt (höchstens :data:`MAX_CELLS` je Seite, mindestens
:data:`MIN_RES_MM`). Jede Teile-Form wird um den halben Abstand vergrößert und
*konservativ* gerastert (jede Zelle, die die vergrößerte Form berührt, ist
belegt) – zwei Teile, deren Zellen sich nicht überschneiden, halten also
sicher mindestens ``spacing`` mm Abstand. Die freie Lage je Drehung findet eine
Kreuzkorrelation (OpenCV ``matchTemplate``) in einem Schritt; gewählt wird die
Lage, die am wenigsten vom Startrand (Standard: oben rechts = Nullpunkt der
Maschine) wegragt. Jede gewählte Lage wird exakt nachgeprüft.

Die Teile werden nur verschoben / gedreht (``Geometry.translated`` /
``rotated``) – Formen, Ebenen, Stege und G-Code-Wege bleiben sonst gleich.
Qt-frei bis auf :func:`shape_paths.shape_polygons` (Text braucht Schriften).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Iterable

import numpy as np
from shapely import make_valid
from shapely.geometry import LineString, Polygon, box
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from .model import Document, Geometry, Shape
from .workarea import WORK_RECT, Rect

SPACING_MM = 2.0
SPACING_RANGE = (0.0, 50.0)
MARGIN_MM = 2.0
MARGIN_RANGE = (0.0, 100.0)
MAX_CELLS = 1200            # Zellen je Seite des Bereichs (Rechenzeit / Genauigkeit)
MIN_RES_MM = 0.25           # feinste Zelle
_OUTLINE_TOL_MM = 0.05      # Abflachung der Umrisse für die Belegung
_CONTAIN_TOL_MM = 0.01
_MAX_VERIFY = 64            # Kandidaten je Drehung, die exakt nachgeprüft werden

ROTATIONS = ("none", "90", "45")
ROTATION_LABELS = {"none": "Nicht drehen", "90": "In 90°-Schritten",
                   "45": "In 45°-Schritten"}
ROTATION_ANGLES = {"none": (0.0,), "90": (0.0, 90.0, 180.0, 270.0),
                   "45": tuple(45.0 * k for k in range(8))}
CORNERS = ("top_right", "top_left", "bottom_right", "bottom_left")
CORNER_LABELS = {"top_right": "Oben rechts (Nullpunkt)", "top_left": "Oben links",
                 "bottom_right": "Unten rechts", "bottom_left": "Unten links"}
FORMS = ("true", "box")
FORM_LABELS = {"true": "Echte Form", "box": "Hüllbox (ordentlicher, schneller)"}
CONTAINERS = ("rect", "work")
CONTAINER_LABELS = {"rect": "Ausgewähltes Rechteck (Material)", "work": "Arbeitsfläche"}

_OPEN_KINDS = ("line", "path")


def _fmt(v: float, decimals: int = 1) -> str:
    return f"{v:.{decimals}f}".replace(".", ",")


# --- Umrisse ------------------------------------------------------------------------

def _is_loop(poly) -> bool:
    return len(poly) > 3 and math.dist(poly[0], poly[-1]) < 1e-6


def shape_footprint(shape: Shape) -> BaseGeometry:
    """Belegte Fläche eines Objekts in Arbeitsflächen-mm: geschlossene Ringe
    gefüllt (Löcher zählen mit – kein Teil wird in ein Loch gelegt), offene
    Linien als Linie, Bilder als Rahmen."""
    from .shape_paths import shape_polygons
    parts: list[BaseGeometry] = []
    for poly in shape_polygons(shape, _OUTLINE_TOL_MM):
        if len(poly) < 2:
            continue
        if shape.kind in _OPEN_KINDS and not _is_loop(poly):
            parts.append(LineString(poly))
        elif len(poly) >= 3:
            p = Polygon(poly)
            parts.append(p if p.is_valid else make_valid(p))
        else:
            parts.append(LineString(poly))
    if not parts:
        b = shape.bounds()
        return box(b.x, b.y, b.right, b.bottom)
    return unary_union(parts)


def _fill_holes(g: BaseGeometry) -> BaseGeometry:
    """Flächen ohne Löcher (Außenringe gefüllt), Linien unverändert."""
    if isinstance(g, Polygon):
        return Polygon(g.exterior) if not g.is_empty else g
    if hasattr(g, "geoms"):
        return unary_union([_fill_holes(p) for p in g.geoms])
    return g


def unit_footprint(shapes: Iterable[Shape], form: str = "true") -> BaseGeometry:
    g = unary_union([shape_footprint(s) for s in shapes])
    if form == "box":
        return box(*g.bounds)
    return g


# --- Rastern ------------------------------------------------------------------------

def _exteriors(g: BaseGeometry) -> list[np.ndarray]:
    out = []
    for p in getattr(g, "geoms", [g]):
        if isinstance(p, Polygon) and not p.is_empty:
            out.append(np.asarray(p.exterior.coords, dtype=float))
        elif hasattr(p, "geoms"):
            out += _exteriors(p)
    return out


def _raster(region: BaseGeometry, ox: float, oy: float, res: float, w: int, h: int,
            into: np.ndarray | None = None) -> np.ndarray:
    """Zellen (Zeile, Spalte) mit Mittelpunkt in ``region`` (gefüllt) setzen;
    Zelle j deckt x ∈ [ox + j·res, ox + (j+1)·res)."""
    import cv2      # erst beim Verschachteln laden (Programmstart bleibt schnell)
    mask = into if into is not None else np.zeros((h, w), np.uint8)
    pts = []
    for ring in _exteriors(region):
        px = ((ring[:, 0] - ox) / res - 0.5) * 16.0
        py = ((ring[:, 1] - oy) / res - 0.5) * 16.0
        pts.append(np.round(np.stack([px, py], axis=1)).astype(np.int32))
    if pts:
        cv2.fillPoly(mask, pts, 1, lineType=cv2.LINE_8, shift=4)
    return mask


def _cover(geom: BaseGeometry, grow: float, res: float) -> BaseGeometry:
    """Konservative Rasterfläche: um ``grow`` (halber Abstand) vergrößert und um
    eine halbe Zellendiagonale (+ Reserve), damit jede berührte Zelle gesetzt wird."""
    return geom.buffer(grow + 0.75 * res, quad_segs=8)


@dataclass
class _Part:
    ids: list[str]
    footprint: BaseGeometry            # ungedreht, an der alten Stelle
    center: tuple[float, float]


@dataclass
class _Variant:
    angle: float
    mask: np.ndarray
    mx0: float
    my0: float
    footprint: BaseGeometry
    boxes: Rect                        # Objektboxen (inkl. Drehung) – müssen in die Arbeitsfläche


@dataclass
class NestResult:
    """Neue Geometrien (ein Undo-Schritt) und Ablesewerte für Dialog / Statusleiste."""

    moves: dict[str, Geometry] = field(default_factory=dict)
    total: int = 0
    placed: int = 0
    unplaced: list[list[str]] = field(default_factory=list)
    rotated: int = 0
    obstacles: int = 0
    used: Rect | None = None
    utilization: float = 0.0
    container: Rect | None = None
    res: float = 0.0

    def readout(self) -> str:
        if not self.total:
            return "Keine Teile zum Verschachteln"
        text = f"{self.placed} von {self.total} Teil(en) verschachtelt"
        if self.used is not None and self.placed:
            text += (f" · belegt {_fmt(self.used.w)} × {_fmt(self.used.h)} mm"
                     f" · Materialnutzung {round(self.utilization * 100)} %")
        if self.rotated:
            text += f" · {self.rotated} gedreht"
        if self.unplaced:
            text += f" · {len(self.unplaced)} passen nicht (bleiben an ihrer Stelle)"
        if self.obstacles:
            text += f" · {self.obstacles} andere(s) Objekt(e) ausgespart"
        return text


# --- Teile, Bereich, Hindernisse ------------------------------------------------------

def _units(doc: Document, ids: Iterable[str]) -> list[list[str]]:
    units: dict[str, list[str]] = {}
    for i in ids:
        if not doc.has_shape(i):
            continue
        s = doc.shape(i)
        units.setdefault(s.groups[0] if s.groups else i, []).append(i)
    return list(units.values())


def container_candidate(doc: Document, ids: Iterable[str]) -> str | None:
    """Größtes ausgewähltes, ungedrehtes, ungruppiertes Rechteck, das die übrigen
    Teile (nach Fläche) aufnehmen könnte – LightBurn nimmt so das Material-Rechteck."""
    units = _units(doc, ids)
    rects = [u[0] for u in units if len(u) == 1 and doc.shape(u[0]).kind == "rect"
             and not doc.shape(u[0]).groups and abs(doc.shape(u[0]).geom.rot % 360) < 1e-9]
    if not rects or len(units) < 2:
        return None
    best = max(rects, key=lambda i: doc.shape(i).bounds().w * doc.shape(i).bounds().h)
    b = doc.shape(best).bounds()
    others = 0.0
    for u in units:
        if u == [best]:
            continue
        ub = doc.selection_bounds(u)
        others += ub.w * ub.h
        if ub.w > max(b.w, b.h) + 1e-9 and ub.h > max(b.w, b.h) + 1e-9:
            return None
    return best if b.w * b.h >= others - 1e-9 else None


def _merge_contained(parts: list[_Part]) -> list[_Part]:
    """Teile innerhalb eines anderen Teils (Gravur auf einer Platte, als eigene
    Objekte importierte Löcher) wandern mit dem kleinsten umschließenden Teil."""
    filled = [_fill_holes(p.footprint) for p in parts]
    order = sorted(range(len(parts)), key=lambda k: filled[k].area)
    host: dict[int, int] = {}
    for pos, k in enumerate(order):
        fk = parts[k].footprint
        for j in order[pos + 1:]:
            if filled[j].area > filled[k].area + 1e-9 and \
                    filled[j].buffer(_CONTAIN_TOL_MM).contains(fk):
                host[k] = j
                break

    def root(k):
        while k in host:
            k = host[k]
        return k

    merged: dict[int, list[int]] = {}
    for k in range(len(parts)):
        merged.setdefault(root(k), []).append(k)
    out = []
    for r in sorted(merged):
        members = merged[r]
        ids = [i for k in members for i in parts[k].ids]
        out.append(_Part(ids, unary_union([parts[k].footprint for k in members]), parts[r].center))
    return out


def nest(doc: Document, ids: Iterable[str], *, container_id: str | None = None,
         spacing: float = SPACING_MM, margin: float = MARGIN_MM, rotation: str = "90",
         corner: str = "top_right", form: str = "true", keep_contained: bool = True,
         avoid_others: bool = True, area: Rect | None = None) -> NestResult:
    """Teile der Auswahl ``ids`` verschachteln. ``container_id``: Rechteck als
    Material (bleibt stehen), sonst ``area`` bzw. die Arbeitsfläche."""
    import cv2
    if rotation not in ROTATIONS:
        raise ValueError(f"Unbekannte Drehung: {rotation}")
    if corner not in CORNERS:
        raise ValueError(f"Unbekannte Ecke: {corner}")
    if form not in FORMS:
        raise ValueError(f"Unbekannte Form: {form}")
    spacing = max(0.0, float(spacing))
    margin = max(0.0, float(margin))
    ids = [i for i in ids if doc.has_shape(i)]
    if container_id is not None and doc.has_shape(container_id):
        cont = doc.shape(container_id).bounds()
    else:
        container_id = None
        cont = area or WORK_RECT
    res_out = NestResult(container=cont)
    units = [u for u in _units(doc, ids) if u != [container_id]]
    units = [[i for i in u if i != container_id] for u in units]
    units = [u for u in units if u]
    if not units:
        return res_out
    shapes = {s.id: s for s in doc.shapes}
    parts = []
    for u in units:
        b = doc.selection_bounds(u)
        parts.append(_Part(list(u), unit_footprint([shapes[i] for i in u]),
                           (b.x + b.w / 2, b.y + b.h / 2)))
    if keep_contained:
        parts = _merge_contained(parts)
    res_out.total = len(parts)

    # Raster über dem erlaubten Bereich: Rand um (halber Abstand − Randabstand) erweitert,
    # weil die gerasterten Teile bereits um den halben Abstand vergrößert sind.
    grow = spacing / 2.0
    e = grow - margin
    ax, ay, aw, ah = cont.x - e, cont.y - e, cont.w + 2 * e, cont.h + 2 * e
    if aw <= 0 or ah <= 0:
        res_out.unplaced = [p.ids for p in parts]
        return res_out
    res = max(MIN_RES_MM, max(aw, ah) / MAX_CELLS)
    res_out.res = res
    W, H = int(math.floor(aw / res + 1e-9)), int(math.floor(ah / res + 1e-9))
    occ = np.zeros((H, W), np.uint8)
    if avoid_others:
        moving = {i for p in parts for i in p.ids}
        moving.add(container_id)
        region = box(ax, ay, ax + W * res, ay + H * res)
        for s in doc.shapes:
            if s.id in moving or not doc.layer(s.layer_id).visible:
                continue
            b = s.bounds()
            if b.right < ax or b.x > ax + W * res or b.bottom < ay or b.y > ay + H * res:
                continue
            fp = shape_footprint(s)
            if not fp.intersects(region.buffer(grow)):
                continue
            _raster(_cover(fp, grow, res), ax, ay, res, W, H, into=occ)
            res_out.obstacles += 1

    def variants(part: _Part) -> list[_Variant]:
        out = []
        for a in ROTATION_ANGLES[rotation]:
            if a:
                rot = []
                for i in part.ids:
                    c = shapes[i].copy()
                    c.geom = shapes[i].geom.rotated(a, *part.center)
                    rot.append(c)
                fp = unit_footprint(rot)
                gb = _union_rect([c.bounds() for c in rot])
            else:
                fp = part.footprint
                gb = _union_rect([shapes[i].bounds() for i in part.ids])
            true_fp = fp
            # Rasterbox = exakte Hüllbox des um ``grow`` vergrößerten Umrisses (der Puffer
            # als Vieleck liegt minimal innerhalb des echten Abstands).
            fx0, fy0, fx1, fy1 = fp.bounds
            minx, miny, maxx, maxy = fx0 - grow, fy0 - grow, fx1 + grow, fy1 + grow
            w = max(1, int(math.ceil((maxx - minx) / res - 1e-9)))
            h = max(1, int(math.ceil((maxy - miny) / res - 1e-9)))
            region = _cover(fp, grow, res) if form == "true" else \
                box(minx, miny, maxx, maxy).buffer(0.75 * res, join_style="mitre")
            mask = _raster(region, minx, miny, res, w, h)
            out.append(_Variant(a, mask, minx, miny, true_fp, gb))
        return out

    top, right = corner.startswith("top"), corner.endswith("right")

    def first_fit(free: np.ndarray, h: int, w: int, mask: np.ndarray):
        """Beste freie Lage: kleinste Ausdehnung vom Startrand (Zeile), dann von der
        Startseite (Spalte); exakt nachgeprüft (Rundung der Korrelation)."""
        for _ in range(_MAX_VERIFY):
            rows = np.flatnonzero(free.any(axis=1))
            if rows.size == 0:
                return None
            r0 = int(rows[0] if top else rows[-1])
            cols = np.flatnonzero(free[r0])
            c0 = int(cols[-1] if right else cols[0])
            if not np.any(occ[r0:r0 + h, c0:c0 + w] & mask):
                far_y = r0 + h if top else H - r0
                far_x = W - c0 if right else c0 + w
                return far_y * (W + 1) + far_x, r0, c0
            free[r0, c0] = False
        return None

    # größte zuerst (Hüllbox-Fläche), bei Gleichstand in Auswahlreihenfolge
    order = sorted(range(len(parts)), key=lambda k: -_bbox_area(parts[k].footprint))
    placed_fp = []
    for k in order:
        part = parts[k]
        best = None
        occ_f = occ.astype(np.float32)
        for vi, v in enumerate(variants(part)):
            h, w = v.mask.shape
            if h > H or w > W:
                continue
            corr = cv2.matchTemplate(occ_f, v.mask.astype(np.float32), cv2.TM_CCORR)
            free = corr < 0.5
            # Die Objektboxen (bei gedrehten Ellipsen / Texten größer als der Umriss) müssen
            # in der Arbeitsfläche bleiben, sonst schiebt das Dokument sie zurück.
            c_lo = math.ceil((v.mx0 - ax - v.boxes.x) / res - 1e-9)
            c_hi = math.floor((WORK_RECT.right - v.boxes.right + v.mx0 - ax) / res + 1e-9)
            r_lo = math.ceil((v.my0 - ay - v.boxes.y) / res - 1e-9)
            r_hi = math.floor((WORK_RECT.bottom - v.boxes.bottom + v.my0 - ay) / res + 1e-9)
            free[:, :max(0, c_lo)] = False
            free[:, max(0, c_hi + 1):] = False
            free[:max(0, r_lo)] = False
            free[max(0, r_hi + 1):] = False
            fit = first_fit(free, h, w, v.mask)
            if fit is None:
                continue
            cand = (fit[0], vi, fit[1], fit[2], v)
            if best is None or cand[:2] < best[:2]:
                best = cand
        if best is None:
            res_out.unplaced.append(part.ids)
            continue
        _sc, _vi, r0, c0, v = best
        h, w = v.mask.shape
        occ[r0:r0 + h, c0:c0 + w] |= v.mask
        dx = ax + c0 * res - v.mx0
        dy = ay + r0 * res - v.my0
        for i in part.ids:
            g = shapes[i].geom
            if v.angle:
                g = g.rotated(v.angle, *part.center)
            res_out.moves[i] = g.translated(dx, dy)
        placed_fp.append(_translate(v.footprint, dx, dy))
        res_out.placed += 1
        res_out.rotated += 1 if v.angle else 0
    if placed_fp:
        u = unary_union(placed_fp)
        minx, miny, maxx, maxy = u.bounds
        res_out.used = Rect(minx, miny, maxx - minx, maxy - miny)
        bb = res_out.used.w * res_out.used.h
        res_out.utilization = min(1.0, sum(_fill_holes(f).area for f in placed_fp) / bb) if bb > 0 else 0.0
    return res_out


def _union_rect(rects: list[Rect]) -> Rect:
    r = rects[0]
    for b in rects[1:]:
        r = r.united(b)
    return r


def _bbox_area(g: BaseGeometry) -> float:
    minx, miny, maxx, maxy = g.bounds
    return (maxx - minx) * (maxy - miny)


def _translate(g: BaseGeometry, dx: float, dy: float) -> BaseGeometry:
    from shapely import affinity
    return affinity.translate(g, dx, dy)
