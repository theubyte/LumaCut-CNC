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

Schnittzugaben (``cut_allowance``, Standard an – weiter als LightBurns / xTools
Nesting, wo „Abstand“ Kerf und Anfahrt mit abdecken muss): Der Abstand gilt
zwischen den *echten* Schnittlinien. Liegt die Außenkontur eines Teils auf einer
Ebene mit Kerf-Versatz nach außen (``kerf_mm`` > 0), wird sein Umriss vorher um
den Versatz vergrößert (wie der Planer: Gehrung, Grenze 2). Hat die Ebene eine
An- oder Abfahrt, bekommt das Teil zusätzlich einen „Anfahrtsraum“ der längeren
von beiden rund um den (versetzten) Umriss: kein anderes Teil (und kein
ausgespartes Objekt) liegt darin – die An-/Abfahrt eines Teils trifft so nie ein
Nachbarteil, egal wo der Planer den Start setzt; Anfahrtsräume zweier Teile
dürfen sich überlappen (beide liegen im Abfall) und über den Materialrand
ragen. Zwei Teile halten also Abstand + Kerf A + Kerf B + max(Anfahrt A, B).
Löcher und Objekte innerhalb eines Teils zählen nicht (ihr Versatz und ihre
Anfahrt liegen im Teil).

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

from .model import Document, Geometry, Shape, is_closed_shape
from .workarea import WORK_RECT, Rect

SPACING_MM = 2.0
SPACING_RANGE = (0.0, 50.0)
MARGIN_MM = 2.0
MARGIN_RANGE = (0.0, 100.0)
MAX_CELLS = 1200            # Zellen je Seite des Bereichs (Rechenzeit / Genauigkeit)
MIN_RES_MM = 0.25           # feinste Zelle
_OUTLINE_TOL_MM = 0.05      # Abflachung der Umrisse für die Belegung
_CONTAIN_TOL_MM = 0.01
EPS_MM = 1e-6
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


@dataclass(frozen=True)
class Allowance:
    """Schnittzugabe eines Teils: Kerf-Versatz nach außen und Reichweite der
    An-/Abfahrt über die (versetzte) Schnittlinie hinaus, je in mm."""

    kerf: float = 0.0
    lead: float = 0.0

    @property
    def active(self) -> bool:
        return self.kerf > 1e-9 or self.lead > 1e-9

    def merged(self, other: "Allowance") -> "Allowance":
        return Allowance(max(self.kerf, other.kerf), max(self.lead, other.lead))

    def text(self) -> str:
        parts = []
        if self.kerf > 1e-9:
            parts.append(f"Kerf +{_fmt(self.kerf, 2)} mm")
        if self.lead > 1e-9:
            parts.append(f"An-/Abfahrt {_fmt(self.lead)} mm")
        return ", ".join(parts)


def layer_allowance(layer) -> Allowance:
    """Zugabe, die eine Ebene einer geschlossenen Außenkontur gibt: positiver Kerf
    (zur Abfallseite = Teil größer) und die längere von An- und Abfahrt (der Planer
    weicht notfalls senkrecht aus – Reichweite = volle Länge)."""
    if layer is None:
        return Allowance()

    def num(name):
        try:
            v = float(getattr(layer, name, 0.0) or 0.0)
        except (TypeError, ValueError):
            return 0.0
        return v if math.isfinite(v) else 0.0
    return Allowance(max(0.0, num("kerf_mm")), max(0.0, num("lead_in_mm"), num("lead_out_mm")))


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
        if (shape.kind in _OPEN_KINDS or shape.kind == "text" and not is_closed_shape(shape)) \
                and not _is_loop(poly):   # Einlinien-Text: Striche als Linien
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


def unit_allowance(doc: Document, shapes: Iterable[Shape]) -> Allowance:
    """Größte Zugabe der äußeren geschlossenen Objekte eines Teils (Gruppe). Objekte,
    die in einem anderen geschlossenen Objekt des Teils liegen (Löcher, Gravuren),
    zählen nicht – ihr Versatz und ihre Anfahrt bleiben im Teil."""
    shapes = list(shapes)
    cand = []
    for s in shapes:
        if not is_closed_shape(s):
            continue
        try:
            a = layer_allowance(doc.layer(s.layer_id))
        except KeyError:
            continue
        if a.active:
            cand.append((s, a))
    if not cand:
        return Allowance()
    filled: dict[str, BaseGeometry] = {}

    def solid(s: Shape) -> BaseGeometry:
        if s.id not in filled:
            filled[s.id] = _fill_holes(shape_footprint(s))
        return filled[s.id]

    out = Allowance()
    for s, a in cand:
        fp = shape_footprint(s)
        if fp.area <= 1e-9:          # offener Pfad: kein Versatz, keine Anfahrt
            continue
        b = s.bounds()
        inside = False
        for o in shapes:
            if o.id == s.id or not is_closed_shape(o):
                continue
            ob = o.bounds()
            if ob.x > b.x + EPS_MM or ob.y > b.y + EPS_MM or ob.right < b.right - EPS_MM \
                    or ob.bottom < b.bottom - EPS_MM or ob.w * ob.h <= b.w * b.h + 1e-9:
                continue
            if solid(o).buffer(_CONTAIN_TOL_MM).contains(fp):
                inside = True
                break
        if not inside:
            out = out.merged(a)
    return out


def grown(g: BaseGeometry, kerf: float) -> BaseGeometry:
    """Umriss um den Kerf-Versatz vergrößert (Gehrung wie der Planer)."""
    if kerf <= 1e-9:
        return g
    return g.buffer(kerf, join_style="mitre", mitre_limit=2.0, quad_segs=8)


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
    allowance: Allowance = field(default_factory=Allowance)


@dataclass
class _Variant:
    angle: float
    mask: np.ndarray                   # Teil (um Kerf und halben Abstand vergrößert)
    reach: np.ndarray | None           # dazu der Anfahrtsraum (None = keiner)
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
    allowance: Allowance = field(default_factory=Allowance)   # größte eingerechnete Zugabe
    allowance_parts: int = 0           # Teile mit Zugabe

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
        if self.allowance_parts:
            text += (f" · Schnittzugabe eingerechnet ({self.allowance.text()}, "
                     f"{self.allowance_parts} Teil(e))")
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
        out.append(_Part(ids, unary_union([parts[k].footprint for k in members]), parts[r].center,
                         parts[r].allowance))
    return out


def nest(doc: Document, ids: Iterable[str], *, container_id: str | None = None,
         spacing: float = SPACING_MM, margin: float = MARGIN_MM, rotation: str = "90",
         corner: str = "top_right", form: str = "true", keep_contained: bool = True,
         avoid_others: bool = True, area: Rect | None = None,
         cut_allowance: bool = True) -> NestResult:
    """Teile der Auswahl ``ids`` verschachteln. ``container_id``: Rechteck als
    Material (bleibt stehen), sonst ``area`` bzw. die Arbeitsfläche.
    ``cut_allowance``: Kerf-Versatz und An-/Abfahrt der Ebenen einrechnen (siehe
    Modul-Doku) – ohne Kerf / Anfahrt auf den Ebenen ändert es nichts."""
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
        members = [shapes[i] for i in u]
        parts.append(_Part(list(u), unit_footprint(members),
                           (b.x + b.w / 2, b.y + b.h / 2),
                           unit_allowance(doc, members) if cut_allowance else Allowance()))
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

    # Obstacles with their own allowance (only with cut_allowance)
    moving = {i for p in parts for i in p.ids}
    moving.add(container_id)
    obstacle_shapes = []
    if avoid_others:
        region = box(ax, ay, ax + W * res, ay + H * res)
        for s in doc.shapes:
            if s.id in moving or not doc.layer(s.layer_id).visible:
                continue
            a = unit_allowance(doc, [s]) if cut_allowance else Allowance()
            reach_mm = grow + a.kerf + a.lead
            b = s.bounds()
            if b.right < ax - reach_mm or b.x > ax + W * res + reach_mm \
                    or b.bottom < ay - reach_mm or b.y > ay + H * res + reach_mm:
                continue
            fp = grown(shape_footprint(s), a.kerf)
            if not fp.intersects(region.buffer(grow + a.lead)):
                continue
            obstacle_shapes.append((fp, a))
    # Anfahrtsräume: das Raster bekommt einen Rand von P Zellen, in den nur
    # Anfahrtsräume ragen dürfen (der Teil selbst bleibt im Bereich).
    max_lead = max([p.allowance.lead for p in parts] + [a.lead for _fp, a in obstacle_shapes])
    any_reach = max_lead > 1e-9
    P = int(math.ceil(max_lead / res)) + 1 if any_reach else 0
    Wp, Hp = W + 2 * P, H + 2 * P
    axp, ayp = ax - P * res, ay - P * res
    occ = np.zeros((Hp, Wp), np.uint8)                 # Teile (mit Kerf, halbem Abstand)
    occ_reach = np.zeros((Hp, Wp), np.uint8) if any_reach else None   # Teile + Anfahrtsraum
    outside = np.zeros((Hp, Wp), np.uint8)             # Rand außerhalb des Bereichs
    if P:
        outside[:P, :] = 1
        outside[-P:, :] = 1
        outside[:, :P] = 1
        outside[:, -P:] = 1
    for fp, a in obstacle_shapes:
        _raster(_cover(fp, grow, res), axp, ayp, res, Wp, Hp, into=occ)
        if occ_reach is not None:
            _raster(_cover(fp, grow + a.lead, res), axp, ayp, res, Wp, Hp, into=occ_reach)
        res_out.obstacles += 1
    if occ_reach is not None:
        occ_reach |= occ

    def variants(part: _Part) -> list[_Variant]:
        out = []
        kerf, lead = part.allowance.kerf, part.allowance.lead
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
            fp = grown(fp, kerf)
            # Rasterbox = exakte Hüllbox des um ``grow`` (+ Anfahrtsraum) vergrößerten
            # Umrisses (der Puffer als Vieleck liegt minimal innerhalb des echten Abstands).
            fx0, fy0, fx1, fy1 = fp.bounds
            g2 = grow + lead
            minx, miny, maxx, maxy = fx0 - g2, fy0 - g2, fx1 + g2, fy1 + g2
            w = max(1, int(math.ceil((maxx - minx) / res - 1e-9)))
            h = max(1, int(math.ceil((maxy - miny) / res - 1e-9)))
            if form == "true":
                region = _cover(fp, grow, res)
            else:
                region = box(fx0 - grow, fy0 - grow, fx1 + grow, fy1 + grow).buffer(
                    0.75 * res, join_style="mitre")
            mask = _raster(region, minx, miny, res, w, h)
            reach = None
            if lead > 1e-9:
                rregion = _cover(fp, g2, res) if form == "true" else \
                    box(minx, miny, maxx, maxy).buffer(0.75 * res, join_style="mitre")
                reach = _raster(rregion, minx, miny, res, w, h)
            out.append(_Variant(a, mask, reach, minx, miny, true_fp, gb))
        return out

    top, right = corner.startswith("top"), corner.endswith("right")

    def collides(r0: int, c0: int, v: _Variant, body_occ: np.ndarray) -> bool:
        h, w = v.mask.shape
        if np.any(body_occ[r0:r0 + h, c0:c0 + w] & v.mask):
            return True
        return v.reach is not None and bool(np.any(occ[r0:r0 + h, c0:c0 + w] & v.reach))

    def first_fit(free: np.ndarray, h: int, w: int, v: _Variant, body_occ: np.ndarray):
        """Beste freie Lage: kleinste Ausdehnung vom Startrand (Zeile), dann von der
        Startseite (Spalte); exakt nachgeprüft (Rundung der Korrelation)."""
        for _ in range(_MAX_VERIFY):
            rows = np.flatnonzero(free.any(axis=1))
            if rows.size == 0:
                return None
            r0 = int(rows[0] if top else rows[-1])
            cols = np.flatnonzero(free[r0])
            c0 = int(cols[-1] if right else cols[0])
            if not collides(r0, c0, v, body_occ):
                far_y = r0 + h if top else Hp - r0
                far_x = Wp - c0 if right else c0 + w
                return far_y * (Wp + 1) + far_x, r0, c0
            free[r0, c0] = False
        return None

    # größte zuerst (Hüllbox-Fläche), bei Gleichstand in Auswahlreihenfolge
    order = sorted(range(len(parts)), key=lambda k: -_bbox_area(parts[k].footprint))
    placed_fp = []
    for k in order:
        part = parts[k]
        best = None
        # Der Teil selbst darf weder Teile noch deren Anfahrtsräume noch den Rand treffen,
        # sein Anfahrtsraum keine Teile.
        body_occ = occ_reach if occ_reach is not None else occ
        if P:
            body_occ = body_occ | outside
        body_f = body_occ.astype(np.float32)
        occ_f = occ.astype(np.float32) if any_reach else None
        for vi, v in enumerate(variants(part)):
            h, w = v.mask.shape
            if h > Hp or w > Wp:
                continue
            corr = cv2.matchTemplate(body_f, v.mask.astype(np.float32), cv2.TM_CCORR)
            free = corr < 0.5
            if v.reach is not None:
                free &= cv2.matchTemplate(occ_f, v.reach.astype(np.float32), cv2.TM_CCORR) < 0.5
            # Die Objektboxen (bei gedrehten Ellipsen / Texten größer als der Umriss) müssen
            # in der Arbeitsfläche bleiben, sonst schiebt das Dokument sie zurück.
            c_lo = math.ceil((v.mx0 - axp - v.boxes.x) / res - 1e-9)
            c_hi = math.floor((WORK_RECT.right - v.boxes.right + v.mx0 - axp) / res + 1e-9)
            r_lo = math.ceil((v.my0 - ayp - v.boxes.y) / res - 1e-9)
            r_hi = math.floor((WORK_RECT.bottom - v.boxes.bottom + v.my0 - ayp) / res + 1e-9)
            free[:, :max(0, c_lo)] = False
            free[:, max(0, c_hi + 1):] = False
            free[:max(0, r_lo)] = False
            free[max(0, r_hi + 1):] = False
            fit = first_fit(free, h, w, v, body_occ)
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
        if occ_reach is not None:
            occ_reach[r0:r0 + h, c0:c0 + w] |= v.reach if v.reach is not None else v.mask
        dx = axp + c0 * res - v.mx0
        dy = ayp + r0 * res - v.my0
        for i in part.ids:
            g = shapes[i].geom
            if v.angle:
                g = g.rotated(v.angle, *part.center)
            res_out.moves[i] = g.translated(dx, dy)
        placed_fp.append(_translate(v.footprint, dx, dy))
        res_out.placed += 1
        res_out.rotated += 1 if v.angle else 0
        if part.allowance.active:
            res_out.allowance = res_out.allowance.merged(part.allowance)
            res_out.allowance_parts += 1
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
