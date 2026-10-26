"""Schnitt-Optionen je Ebene: Kerf-Versatz, Haltestege, An-/Abfahrt (Qt-frei).

Wie LightBurn *Kerf Offset*, *Tabs/Bridges* und *Lead-In/Lead-Out*
(Cut Settings Editor) bzw. xTool Creative Space *Kerf* / *Bridge*:

* :func:`offset_closed` – geschlossene Konturen werden zur **Abfallseite**
  versetzt (``kerf_mm > 0``: Außenkonturen nach außen, Löcher nach innen,
  d. h. Teile werden größer und Löcher kleiner – genau der Ausgleich der
  Schnittbreite). Außen/Loch entscheidet die Verschachtelungstiefe (gerade
  Tiefe = Außenkontur). Robuster Polygon-Versatz mit ``shapely``
  (Gehrungsecken, Begrenzung 2). Offene Pfade bleiben unverändert;
  zerfällt eine Kontur beim Verkleinern, werden alle Teilstücke geschnitten,
  verschwindet sie ganz, bleibt die Originalkontur (Warnung).
* :func:`split_tabs` – lässt gleichmäßig verteilte, ungeschnittene Stege
  (Laser aus, G0 über die Lücke) in geschlossenen Konturen stehen, schiebt
  Stege von Ecken weg und lässt sie bei zu kurzen Konturen weg.
* :func:`lead_in` / :func:`lead_out` – Gerade (45°) oder Viertelkreis auf der
  Abfallseite (außen bei Außenkonturen, innen bei Löchern). Liegt die
  An-/Abfahrt außerhalb der Arbeitsfläche oder auf der falschen Seite, wird
  sie verkürzt und notfalls weggelassen – nie außerhalb der Arbeitsfläche.
* :class:`LeadObstacles` – Kollisionsprüfung wie LightBurn: eine An-/Abfahrt
  darf keine andere Kontur des Jobs (alle Ebenen) berühren oder kreuzen und
  die eigene Kontur nur im Startpunkt treffen. Passt sie nicht, werden der
  Reihe nach versucht: anderer Bogen-Drehsinn (Kontur umgekehrt), gerade
  statt Bogen, senkrecht, kürzer, und ein anderer Startpunkt entlang der
  Kontur (Kantenmitten bzw. gleichmäßig verteilte Punkte bei Kurven, die
  nächstgelegenen zuerst). Erst dann wird sie weggelassen und gemeldet.

Alle Koordinaten sind Maschinen-mm; geschlossene Polylinien haben gleichen
Anfangs- und Endpunkt (siehe :mod:`.planner`).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from lumacut_canvas.workarea import WORK_HEIGHT_MM, WORK_WIDTH_MM, to_machine

from .planner import containment, is_closed, point_in_polygon

Point = tuple[float, float]
Poly = list[Point]

_MIN_X, _MIN_Y = to_machine(0.0, 0.0)
_MAX_X, _MAX_Y = to_machine(WORK_WIDTH_MM, WORK_HEIGHT_MM)
CORNER_DEG = 30.0        # Richtungswechsel ab dem ein Punkt als Ecke gilt
MIN_TAB_PERIMETER = 10.0  # mm: kürzere Konturen bekommen keine Stege
ARC_SEGMENTS = 8

# Art einer Polylinie in JobLayer.poly_kinds
KIND_CUT = "cut"
KIND_LEAD_IN = "lead_in"
KIND_LEAD_OUT = "lead_out"
KIND_TAB = "tab"          # Schnittstück, vor dem eine Steg-Lücke (Laser aus) liegt


@dataclass
class CutOptions:
    kerf_mm: float = 0.0
    tab_count: int = 0
    tab_width_mm: float = 1.0
    tab_spacing_mm: float = 0.0
    lead_in_mm: float = 0.0
    lead_in_arc: bool = False
    lead_out_mm: float = 0.0

    @property
    def active(self) -> bool:
        return bool(self.kerf_mm or self.lead_in_mm or self.lead_out_mm
                    or (self.tab_width_mm > 0 and (self.tab_count > 0 or self.tab_spacing_mm > 0)))

    @staticmethod
    def of(obj) -> "CutOptions":
        return CutOptions(**{k: getattr(obj, k) for k in CutOptions.__dataclass_fields__
                             if hasattr(obj, k)})


@dataclass
class CutResult:
    polylines: list[Poly] = field(default_factory=list)
    kinds: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    skipped_leads: int = 0   # Konturen, deren Anfahrt wegfiel
    moved_leads: int = 0     # Konturen mit verlegtem Startpunkt wegen Kollision


def in_work_area(p: Point, eps: float = 1e-6) -> bool:
    return _MIN_X - eps <= p[0] <= _MAX_X + eps and _MIN_Y - eps <= p[1] <= _MAX_Y + eps


def signed_area(poly: Poly) -> float:
    a = 0.0
    for (x0, y0), (x1, y1) in zip(poly, poly[1:] + poly[:1]):
        a += x0 * y1 - x1 * y0
    return a / 2


def nesting_depth(polys: list[Poly]) -> list[int]:
    """Anzahl der geschlossenen Konturen, in denen jede Polylinie liegt."""
    return [len(p) for p in containment(polys)]


# --- Kerf ------------------------------------------------------------------

def _ring_of(geom) -> list[Poly]:
    from shapely.geometry import MultiPolygon, Polygon
    if isinstance(geom, Polygon):
        geoms = [geom]
    elif isinstance(geom, MultiPolygon):
        geoms = list(geom.geoms)
    else:
        geoms = [g for g in getattr(geom, "geoms", []) if isinstance(g, Polygon)]
    out = []
    for g in geoms:
        if g.is_empty or g.area < 1e-6:
            continue
        pts = [(float(x), float(y)) for x, y in g.exterior.coords]
        out.append(pts)
    return out


def offset_ring(ring: Poly, distance: float) -> list[Poly]:
    """Geschlossene Kontur um ``distance`` mm versetzen (+ = größer).

    Ergebnis: geschlossene Ringe mit der Laufrichtung des Originals (leer,
    wenn die Kontur verschwindet).
    """
    from shapely.geometry import Polygon
    from shapely.validation import make_valid
    poly = Polygon(ring)
    if not poly.is_valid:
        poly = make_valid(poly)
    if poly.is_empty:
        return []
    res = poly.buffer(distance, join_style="mitre", mitre_limit=2.0, quad_segs=8)
    rings = _ring_of(res)
    ccw = signed_area(ring[:-1]) > 0
    out = []
    for r in rings:
        if (signed_area(r[:-1]) > 0) != ccw:
            r = list(reversed(r))
        out.append(r)
    return out


def offset_closed(polys: list[Poly], kerf_mm: float) -> tuple[list[Poly], list[str]]:
    """Alle geschlossenen Konturen zur Abfallseite versetzen (siehe Modul-Doku)."""
    if not kerf_mm:
        return [list(p) for p in polys], []
    depth = nesting_depth(polys)
    out: list[Poly] = []
    warnings: list[str] = []
    for p, d in zip(polys, depth):
        if not is_closed(p) or abs(signed_area(p[:-1])) < 1e-9:
            out.append(list(p))
            continue
        dist = kerf_mm if d % 2 == 0 else -kerf_mm
        rings = offset_ring(p, dist)
        if not rings:
            warnings.append("Kontur zu klein für Kerf-Versatz – unverändert geschnitten")
            out.append(list(p))
            continue
        out.extend(rings)
    return out, warnings


# --- Haltestege ---------------------------------------------------------------

def _cum_lengths(poly: Poly) -> list[float]:
    acc = [0.0]
    for a, b in zip(poly, poly[1:]):
        acc.append(acc[-1] + math.dist(a, b))
    return acc


def _point_at(poly: Poly, cum: list[float], s: float) -> tuple[Point, int]:
    """Punkt bei Bogenlänge ``s`` und Index des Segments (0-basiert)."""
    s = max(0.0, min(cum[-1], s))
    for i in range(len(poly) - 1):
        if cum[i + 1] >= s:
            seg = cum[i + 1] - cum[i]
            t = 0.0 if seg <= 0 else (s - cum[i]) / seg
            a, b = poly[i], poly[i + 1]
            return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t), i
    return poly[-1], len(poly) - 2


def _sub_path(poly: Poly, cum: list[float], s0: float, s1: float) -> Poly:
    p0, i0 = _point_at(poly, cum, s0)
    p1, i1 = _point_at(poly, cum, s1)
    pts = [p0] + [poly[k] for k in range(i0 + 1, i1 + 1) if s0 < cum[k] < s1] + [p1]
    clean = [pts[0]]
    for q in pts[1:]:
        if math.dist(q, clean[-1]) > 1e-9:
            clean.append(q)
    return clean


def corner_positions(poly: Poly, cum: list[float] | None = None,
                     min_deg: float = CORNER_DEG) -> list[float]:
    """Bogenlängen der Ecken (Richtungswechsel ≥ ``min_deg``) einer geschlossenen Kontur."""
    cum = cum or _cum_lengths(poly)
    ring = poly[:-1]
    n = len(ring)
    out = []
    for i in range(n):
        a, b, c = ring[i - 1], ring[i], ring[(i + 1) % n]
        v1 = (b[0] - a[0], b[1] - a[1])
        v2 = (c[0] - b[0], c[1] - b[1])
        l1, l2 = math.hypot(*v1), math.hypot(*v2)
        if l1 < 1e-9 or l2 < 1e-9:
            continue
        cosang = max(-1.0, min(1.0, (v1[0] * v2[0] + v1[1] * v2[1]) / (l1 * l2)))
        if math.degrees(math.acos(cosang)) >= min_deg:
            out.append(cum[i])
    return out


def tab_centers(perimeter: float, count: int, width: float, corners: list[float]) -> list[float]:
    """Gleichmäßig verteilte Steg-Mitten, von Ecken weggeschoben.

    Die Kontur beginnt und endet bei 0 (dort sitzt die Anfahrt), daher liegen
    die Stege bei ``(i + 0.5) · L / n``; jeder darf sich um höchstens ein
    Viertel seines Abschnitts verschieben, um ``width/2 + 0.5`` mm Abstand zu
    allen Ecken (und zum Start) zu halten.
    """
    if count <= 0 or width <= 0:
        return []
    step = perimeter / count
    clear = width / 2 + 0.5
    avoid = sorted(set([0.0, perimeter] + list(corners)))
    out = []
    for i in range(count):
        c0 = (i + 0.5) * step
        best = c0
        limit = step / 4
        if any(abs(c0 - a) < clear for a in avoid):
            cand = []
            for a in avoid:
                for c in (a - clear, a + clear):
                    if abs(c - c0) <= limit and all(abs(c - b) >= clear - 1e-9 for b in avoid):
                        cand.append(c)
            if cand:
                best = min(cand, key=lambda c: abs(c - c0))
        out.append(best)
    return out


def split_tabs(poly: Poly, count: int, width: float, spacing: float = 0.0) -> list[Poly]:
    """Geschlossene Kontur in Schnittstücke mit ``count`` Lücken der Breite ``width``.

    ``spacing > 0`` → ein Steg je ``spacing`` mm Umfang (mindestens 1).
    Mindestregel: Umfang ≥ ``MIN_TAB_PERIMETER`` und jedes Schnittstück
    mindestens so lang wie ein Steg – sonst weniger Stege (bis keiner).
    """
    if not is_closed(poly) or width <= 0:
        return [poly]
    cum = _cum_lengths(poly)
    L = cum[-1]
    if spacing > 0:
        count = max(1, int(L // spacing))
    if L < MIN_TAB_PERIMETER:
        return [poly]
    count = min(count, int(L // (2 * width)))
    if count <= 0:
        return [poly]
    centers = tab_centers(L, count, width, corner_positions(poly, cum))
    pieces = []
    s = 0.0
    for c in centers:
        a, b = c - width / 2, c + width / 2
        if a > s + 1e-6:
            pieces.append(_sub_path(poly, cum, s, a))
        s = b
    if L > s + 1e-6:
        pieces.append(_sub_path(poly, cum, s, L))
    return [p for p in pieces if len(p) >= 2]


# --- An-/Abfahrt -------------------------------------------------------------

def _waste_normal(poly: Poly, outer: bool, at_start: bool) -> tuple[Point, Point]:
    """(Tangente, Normale zur Abfallseite) am Start bzw. Ende der Kontur."""
    if at_start:
        a, b = poly[0], next(q for q in poly[1:] if math.dist(q, poly[0]) > 1e-9)
    else:
        b = poly[-1]
        a = next(q for q in reversed(poly[:-1]) if math.dist(q, b) > 1e-9)
    L = math.dist(a, b)
    t = ((b[0] - a[0]) / L, (b[1] - a[1]) / L)
    ccw = signed_area(poly[:-1]) > 0
    right = (t[1], -t[0])
    outward = right if ccw else (-right[0], -right[1])
    n = outward if outer else (-outward[0], -outward[1])
    return t, n


def _arc(center: Point, r: float, a0: float, a1: float) -> Poly:
    return [(center[0] + r * math.cos(a0 + (a1 - a0) * k / ARC_SEGMENTS),
             center[1] + r * math.sin(a0 + (a1 - a0) * k / ARC_SEGMENTS))
            for k in range(ARC_SEGMENTS + 1)]


def _lead_shape(p: Point, t: Point, n: Point, length: float, arc: bool, entering: bool) -> Poly:
    """Polylinie, die bei ``p`` tangential (``t``) ein- bzw. ausläuft."""
    sgn = -1.0 if entering else 1.0
    if not arc:
        k = length / math.sqrt(2)
        q = (p[0] + sgn * t[0] * k + n[0] * k, p[1] + sgn * t[1] * k + n[1] * k)
        return [q, p] if entering else [p, q]
    c = (p[0] + n[0] * length, p[1] + n[1] * length)
    a_p = math.atan2(p[1] - c[1], p[0] - c[0])
    # Drehsinn so wählen, dass die Bewegung bei p in Richtung t läuft.
    cross = (p[0] - c[0]) * t[1] - (p[1] - c[1]) * t[0]
    d = math.pi / 2 if cross > 0 else -math.pi / 2  # +: gegen den Uhrzeigersinn
    if entering:
        return _arc(c, length, a_p - d, a_p)
    return _arc(c, length, a_p, a_p + d)


class LeadObstacles:
    """Alle Konturen eines Jobs als Hindernisse für An-/Abfahrten (shapely).

    ``blocker(contour)`` liefert eine Prüffunktion ``lead -> bool`` (True =
    Kollision). Deckungsgleiche Konturen (z. B. dieselbe Form auf einer
    Markier-Ebene) gelten als die eigene und blockieren nicht.
    """

    SAME_TOL_MM = 0.01

    def __init__(self, polys: list[Poly]):
        from shapely.geometry import LineString
        from shapely.strtree import STRtree
        self.geoms = [LineString(p) for p in polys
                      if len(p) >= 2 and any(math.dist(p[0], q) > 1e-9 for q in p)]
        self.tree = STRtree(self.geoms) if self.geoms else None

    def blocker(self, contour: Poly):
        from shapely.geometry import LineString, Point as SPoint
        own = LineString(contour)
        own_len = own.length
        same: dict[int, bool] = {}

        def is_same(i: int) -> bool:
            if i not in same:
                g = self.geoms[i]
                same[i] = (abs(g.length - own_len) <= 4 * self.SAME_TOL_MM + 1e-3 * own_len
                           and g.hausdorff_distance(own) <= self.SAME_TOL_MM)
            return same[i]

        def blocked(lead: Poly) -> bool:
            g = LineString(lead)
            # Anschluss = das Ende, das auf der Kontur liegt (Start darf wandern)
            joint = min((lead[0], lead[-1]), key=lambda q: own.distance(SPoint(q)))
            # eigene Kontur nur im Anschlusspunkt berühren
            free = g.difference(SPoint(joint).buffer(1e-3))
            if not free.is_empty and free.intersects(own):
                return True
            if self.tree is None:
                return False
            for i in self.tree.query(g):
                o = self.geoms[int(i)]
                if g.intersects(o) and not is_same(int(i)):
                    return True
            return False

        return blocked


def _lead_ok(lead: Poly, contour: Poly, outer: bool, blocked=None) -> bool:
    if not all(in_work_area(q) for q in lead):
        return False
    if blocked is not None and blocked(lead):
        return False
    inner_pts = lead[1:-1] or lead
    tip = [q for q in inner_pts if math.dist(q, contour[0]) > 1e-6 and math.dist(q, contour[-1]) > 1e-6]
    for q in tip:
        if point_in_polygon(q, contour) == outer:  # außen: Punkt darf nicht innen liegen
            return False
    return True


def make_lead(poly: Poly, outer: bool, length: float, arc: bool, entering: bool,
              blocked=None, tries: int = 4) -> Poly | None:
    """An- oder Abfahrt für eine geschlossene Kontur; ``None`` wenn kein Platz.

    Bei Platzmangel (Arbeitsfläche, kleines Loch, Kollision über ``blocked``)
    wird bis zu dreimal halbiert.
    """
    if length <= 0 or not is_closed(poly) or abs(signed_area(poly[:-1])) < 1e-9:
        return None
    p = poly[0] if entering else poly[-1]
    t, n = _waste_normal(poly, outer, entering)
    shapes = [arc, False] if arc else [False]
    for perpendicular in (False, True):
        for use_arc in shapes:
            if perpendicular and use_arc:
                continue
            L = length
            for _ in range(tries):
                if perpendicular:
                    q = (p[0] + n[0] * L, p[1] + n[1] * L)
                    lead = [q, p] if entering else [p, q]
                else:
                    lead = _lead_shape(p, t, n, L, use_arc, entering)
                if _lead_ok(lead, poly, outer, blocked):
                    return lead
                L /= 2
    return None


def start_mid_edge(poly: Poly) -> Poly:
    """Geschlossene Kontur, die in der Mitte ihrer ersten Kante beginnt.

    Der Planer startet Konturen gern an einer Ecke; eine tangentiale An-/Abfahrt
    braucht aber eine gerade Kante (wie LightBurn, das An-/Abfahrten nicht in
    Ecken setzt). Kurven (keine Ecke am Start) bleiben unverändert.
    """
    if not is_closed(poly) or len(poly) < 4:
        return poly
    cum = _cum_lengths(poly)
    if not corner_positions(poly, cum) or corner_positions(poly, cum)[0] > 1e-9:
        return poly
    ring = poly[:-1]
    a, b = ring[0], ring[1]
    if math.dist(a, b) < 1e-6:
        return poly
    m = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
    rotated = [m] + ring[1:] + [ring[0], m]
    return rotated


MAX_START_CANDIDATES = 12


def start_candidates(poly: Poly) -> list[Poly]:
    """Alternative Startpunkte einer geschlossenen Kontur, nächste zuerst.

    Kantenmitten (gerade Kanten) bzw. 8 gleichmäßig verteilte Punkte (Kurven,
    viele kurze Kanten); jede Kandidatin auch mit umgekehrter Laufrichtung.
    """
    ring = poly[:-1]
    if len(ring) < 3:
        return []
    cum = _cum_lengths(poly)
    per = cum[-1]
    if per <= 1e-9:
        return []
    long_edges = [i for i in range(len(ring)) if cum[i + 1] - cum[i] >= per / 40]
    if long_edges and len(long_edges) <= 4 * MAX_START_CANDIDATES:
        pos = [(cum[i] + cum[i + 1]) / 2 for i in long_edges]
    else:
        pos = [per * k / 8 for k in range(8)]
    pos.sort(key=lambda s: min(s, per - s))  # Nähe zum ursprünglichen Start
    out: list[Poly] = []
    for s in pos[:MAX_START_CANDIDATES]:
        if s <= 1e-9 or per - s <= 1e-9:
            rot = list(poly)
        else:
            rot = _sub_path(poly, cum, s, per) + _sub_path(poly, cum, 0.0, s)[1:]
        out.append(rot)
    return out


def _with_leads(p: Poly, outer: bool, opts: CutOptions, blocked) -> tuple[Poly, Poly | None, bool]:
    """(Kontur, Anfahrt, verlegt?).

    Ohne Hindernisse wie bisher (Kantenmitte, notfalls kürzer). Mit
    Hindernissen zuerst volle Länge an allen Kandidaten (umgekehrt, andere
    Startpunkte), erst danach kürzere Anfahrten – lieber verlegen als stummeln.
    """
    first = start_mid_edge(p)
    if blocked is None or opts.lead_in_mm <= 0:
        return first, make_lead(first, outer, opts.lead_in_mm, opts.lead_in_arc, True), False
    cands = [first, list(reversed(first))] + [c for base in start_candidates(p)
                                              for c in (base, list(reversed(base)))]
    for tries in (1, 4):
        for k, cand in enumerate(cands):
            lead = make_lead(cand, outer, opts.lead_in_mm, opts.lead_in_arc, True, blocked, tries)
            if lead:
                return cand, lead, k > 0
    return first, None, False


# --- Ebene ------------------------------------------------------------------

def apply_cut_options(polys: list[Poly], opts: CutOptions, depth: list[int] | None = None,
                      obstacles: LeadObstacles | None = None) -> CutResult:
    """Haltestege und An-/Abfahrt auf bereits **geordnete** Polylinien anwenden.

    ``depth`` = Verschachtelungstiefe je Polylinie (gerade = Außenkontur);
    ohne Angabe wird sie berechnet. ``obstacles`` (alle Konturen des Jobs)
    schaltet die Kollisionsprüfung der An-/Abfahrten ein. Liefert Polylinien plus Art je Polylinie
    (``cut``/``lead_in``/``lead_out``/``tab``) in Schnittreihenfolge.
    """
    res = CutResult()
    if depth is None:
        depth = nesting_depth(polys)
    tabs_on = opts.tab_width_mm > 0 and (opts.tab_count > 0 or opts.tab_spacing_mm > 0)
    for p, d in zip(polys, depth):
        if not is_closed(p):
            res.polylines.append(p)
            res.kinds.append(KIND_CUT)
            continue
        outer = d % 2 == 0
        blocked = obstacles.blocker(p) if obstacles is not None and (
            opts.lead_in_mm > 0 or opts.lead_out_mm > 0) else None
        if opts.lead_in_mm > 0:
            p, lead, moved = _with_leads(p, outer, opts, blocked)
            res.moved_leads += moved
        else:
            lead = None
            if opts.lead_out_mm > 0:
                p = start_mid_edge(p)
        if lead:
            res.polylines.append(lead)
            res.kinds.append(KIND_LEAD_IN)
        elif opts.lead_in_mm > 0:
            res.skipped_leads += 1
            res.warnings.append("Anfahrt weggelassen (kein Platz)")
        pieces = split_tabs(p, opts.tab_count, opts.tab_width_mm, opts.tab_spacing_mm) if tabs_on else [p]
        for k, piece in enumerate(pieces):
            res.polylines.append(piece)
            res.kinds.append(KIND_TAB if k else KIND_CUT)
        out = make_lead(p, outer, opts.lead_out_mm, opts.lead_in_arc, False, blocked)
        if out and math.dist(pieces[-1][-1], p[-1]) < 1e-6:
            res.polylines.append(out)
            res.kinds.append(KIND_LEAD_OUT)
    return res
