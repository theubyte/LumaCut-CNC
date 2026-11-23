"""Manuelle Haltestege je Objekt (LightBurn *Tab tool* / *Add Tabs*).

Ein Steg ist ein Punkt auf dem Umriss einer geschlossenen Kontur des Objekts
(``Shape.tabs``, normiert auf die ungedrehte Objektbox – Verschieben,
Skalieren, Drehen, Duplizieren und Arrays nehmen ihn mit). Beim Senden legt
der Planer (:mod:`lumacut_job.cutpath`) an jedem Punkt einen Steg der
Stegbreite der Ebene (``tab_width_mm``) – an dieser Kontur *statt* der
automatischen Stege der Ebene (wie LightBurn: eine Form mit eigenen Stegen
bekommt keine automatischen). Konturen ohne eigene Stege behalten die
automatischen Stege der Ebene; Stegbreite 0 schaltet alle Stege der Ebene ab.

„Stege gleichmäßig setzen …“ (:func:`place_even_tabs`, LightBurn *Auto-place
tabs* im Steg-Werkzeug) verteilt manuelle Stege auf einmal: eine feste Anzahl
je Kontur oder einer je … mm Umfang, wie die automatischen Stege der Ebene von
Konturstart und Ecken weggeschoben – danach lassen sie sich einzeln
verschieben oder entfernen. Trägt das Objekt einen manuellen Startpunkt
(:mod:`startpoint`), wird die Kontur, auf der er liegt, ab diesem Punkt verteilt
(dort beginnt beim Senden der Schnitt bzw. die Anfahrt) – so hält jeder Steg den
Startabstand schon beim Setzen, und der Planer muss keinen von seinem Platz
schieben.

Wird der Startpunkt danach gesetzt, verschoben oder entfernt
(:func:`follow_start`), wandern gleichmäßig gesetzte Stege mit: liegen die
Stege einer Kontur genau so, wie „Stege gleichmäßig setzen …“ sie ab dem
bisherigen Konturstart gesetzt hätte, werden sie ab dem neuen Start gleich
verteilt (gleiche Anzahl, gleiche Eckenregel). Von Hand gesetzte oder
verschobene Stege bleiben, wo sie sind.

Ebenso nach einer Änderung des Umrisses (:func:`follow_shape` – Knoten
bearbeiten, Pfade vereinfachen, Ecken abrunden / abschrägen, Eckenradius): lagen
die Stege einer Kontur vorher gleichmäßig, werden sie auf dem neuen Umriss mit
derselben Anzahl und Eckenregel neu verteilt, statt nur auf den nächsten
Umrisspunkt übertragen zu werden (dort stünden sie danach ungleich, an einer neuen
Ecke oder am Start). Von Hand gesetzte Stege werden wie bisher nur übertragen.

Hier nur die Rechnung (Qt nur über :func:`shape_paths.shape_polygons`); die
Bedienung (Werkzeug „Stege“, Markierungen, Menü) liegt in :mod:`tabs_ui`.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from typing import Iterable

from .model import Shape, tabs_from_world

Point = tuple[float, float]

#: Objektarten, die Stege tragen können (geschlossene Konturen; Bilder und Linien nicht).
TAB_KINDS = ("rect", "ellipse", "polygon", "path", "text")
#: Zwei Stege näher als das (mm) auf derselben Kontur gelten als ein Steg.
MIN_TAB_DISTANCE_MM = 0.5


def closed_rings(shape: Shape) -> list[list[Point]]:
    """Geschlossene Ringe des Objekts in Arbeitsflächen-mm (Anfang = Ende)."""
    if shape is None or shape.kind not in TAB_KINDS:
        return []
    from .shape_paths import shape_polygons
    out = []
    for poly in shape_polygons(shape):
        if len(poly) >= 4 and math.dist(poly[0], poly[-1]) < 1e-6:
            out.append(poly)
    return out


def can_have_tabs(shape: Shape) -> bool:
    return bool(closed_rings(shape))


def project(p: Point, a: Point, b: Point) -> tuple[float, Point]:
    """Abstand von ``p`` zur Strecke ``a``–``b`` und der nächste Punkt darauf."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    ll = dx * dx + dy * dy
    t = 0.0 if ll <= 1e-18 else max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / ll))
    q = (a[0] + dx * t, a[1] + dy * t)
    return math.dist(p, q), q


def nearest_on_rings(rings: Iterable[list[Point]], p: Point) -> tuple[float, Point | None, int]:
    """``(Abstand, Punkt, Ring-Index)`` des nächsten Umrisspunkts (``inf, None, -1`` ohne Ringe)."""
    best = (math.inf, None, -1)
    for k, ring in enumerate(rings):
        for a, b in zip(ring, ring[1:]):
            d, q = project(p, a, b)
            if d < best[0]:
                best = (d, q, k)
    return best


def with_tab_points(shape: Shape, pts: Iterable[Point]) -> Shape:
    """Kopie mit genau diesen Steg-Punkten (Arbeitsflächen-mm)."""
    return replace(shape, geom=shape.geom.copy(), tabs=tabs_from_world(shape.geom, list(pts)))


def tab_at(shape: Shape, p: Point, tol_mm: float) -> int | None:
    """Index des Stegs, der ``p`` am nächsten liegt (höchstens ``tol_mm`` entfernt)."""
    best, best_d = None, tol_mm
    for i, q in enumerate(shape.tab_points()):
        d = math.dist(p, q)
        if d <= best_d:
            best, best_d = i, d
    return best


def add_tab(shape: Shape, p: Point, tol_mm: float) -> tuple[Shape | None, str]:
    """Steg am nächsten Umrisspunkt zu ``p`` einfügen: ``(neue Form | None, Grund)``."""
    rings = closed_rings(shape)
    if not rings:
        return None, "Nur geschlossene Konturen bekommen Stege."
    d, q, _k = nearest_on_rings(rings, p)
    if q is None or d > tol_mm:
        return None, "Kein Umriss unter dem Zeiger – auf die Kontur tippen."
    pts = shape.tab_points()
    if any(math.dist(q, t) < MIN_TAB_DISTANCE_MM for t in pts):
        return None, "Dort sitzt schon ein Steg."
    return with_tab_points(shape, pts + [q]), ""


def remove_tab(shape: Shape, index: int) -> Shape:
    pts = shape.tab_points()
    return with_tab_points(shape, [q for i, q in enumerate(pts) if i != index])


def move_tab(shape: Shape, index: int, p: Point) -> Shape | None:
    """Steg ``index`` auf den Umrisspunkt nächst ``p`` schieben (``None`` ohne Umriss)."""
    d, q, _k = nearest_on_rings(closed_rings(shape), p)
    if q is None:
        return None
    pts = shape.tab_points()
    pts[index] = q
    return with_tab_points(shape, pts)


def clear_tabs(shape: Shape) -> Shape:
    return replace(shape, geom=shape.geom.copy(), tabs=())


def carry_tabs(new: Shape, pts: Iterable[Point], tol_mm: float = 1.5) -> Shape:
    """Steg-Punkte (Arbeitsflächen-mm) auf ``new`` übertragen: jeder Punkt, der
    höchstens ``tol_mm`` neben einer geschlossenen Kontur von ``new`` liegt,
    wird auf sie gesetzt, die übrigen entfallen (für Knoten bearbeiten,
    Vereinfachen, Zerlegen, Kombinieren)."""
    pts = list(pts)
    if not pts:
        return new if not new.tabs else clear_tabs(new)
    rings = closed_rings(new)
    keep = []
    for p in pts:
        d, q, _k = nearest_on_rings(rings, p)
        if q is not None and d <= tol_mm and all(math.dist(q, t) >= MIN_TAB_DISTANCE_MM for t in keep):
            keep.append(q)
    return with_tab_points(new, keep)


def slide_points(old: Shape, new: Shape, pts: Iterable[Point]) -> list[Point]:
    """Punkte auf dem Umriss von ``old`` an dieselbe Stelle des geänderten Umrisses
    ``new`` mitnehmen: haben beide gleich viele geschlossene Ringe mit gleich vielen
    Ecken (Knoten verschoben), bleibt jeder Punkt auf seiner Kante beim selben Anteil
    (eine Kante wird länger → der Steg wandert mit). Sonst und für Punkte neben dem
    Umriss bleiben die Punkte, wie sie sind (danach :func:`carry_tabs` / ``carry_start``)."""
    pts = list(pts)
    a, b = closed_rings(old), closed_rings(new)
    if not pts or len(a) != len(b) or any(len(r) != len(q) for r, q in zip(a, b)):
        return pts
    out = []
    for p in pts:
        best = (math.inf, -1, -1, 0.0)
        for k, ring in enumerate(a):
            for i, (u, v) in enumerate(zip(ring, ring[1:])):
                dx, dy = v[0] - u[0], v[1] - u[1]
                ll = dx * dx + dy * dy
                t = 0.0 if ll <= 1e-18 else max(0.0, min(1.0, ((p[0] - u[0]) * dx + (p[1] - u[1]) * dy) / ll))
                d = math.dist(p, (u[0] + dx * t, u[1] + dy * t))
                if d < best[0]:
                    best = (d, k, i, t)
        d, k, i, t = best
        if k < 0 or d > 1e-3:
            out.append(p)
            continue
        u, v = b[k][i], b[k][i + 1]
        out.append((u[0] + (v[0] - u[0]) * t, u[1] + (v[1] - u[1]) * t))
    return out


def tab_count(shapes: Iterable[Shape]) -> int:
    return sum(len(s.tabs) for s in shapes)


# --- Stege gleichmäßig setzen ---------------------------------------------------------

#: Verteilung: feste Anzahl je Kontur oder ein Steg je … mm Umfang.
EVEN_MODES = ("count", "spacing")
EVEN_MODE_LABELS = {"count": "Anzahl je Kontur", "spacing": "Abstand"}
EVEN_COUNT_RANGE = (1, 24)            # wie „Stege“ der Schnitt-Optionen
EVEN_SPACING_RANGE = (1.0, 500.0)     # mm
EVEN_MAX_RANGE = (0, 100)             # 0 = ohne Grenze
EVEN_MIN_PERIMETER_RANGE = (0.0, 1000.0)
#: Konturen mit weniger Umfang (mm) bleiben ohne Stege (wie die automatischen Stege).
EVEN_MIN_PERIMETER_MM = 10.0
#: Rechenbreite, wenn die Stegbreite der Ebene 0 ist (Stege werden dann nicht geschnitten).
FALLBACK_WIDTH_MM = 1.0


def even_defaults() -> dict:
    return {"mode": "count", "count": 4, "spacing_mm": 50.0, "max_count": 0,
            "avoid_corners": True, "skip_inner": True, "min_perimeter_mm": EVEN_MIN_PERIMETER_MM,
            "replace": True}


def _clean_even(values: dict | None) -> dict:
    v = {**even_defaults(), **(values or {})}
    mode = v["mode"] if v["mode"] in EVEN_MODES else "count"

    def num(key, lo, hi, cast):
        try:
            x = float(v[key])
        except (TypeError, ValueError):
            x = float(even_defaults()[key])
        if not math.isfinite(x):
            x = float(even_defaults()[key])
        return cast(min(hi, max(lo, x)))

    return {"mode": mode, "count": num("count", *EVEN_COUNT_RANGE, lambda x: int(round(x))),
            "spacing_mm": num("spacing_mm", *EVEN_SPACING_RANGE, float),
            "max_count": num("max_count", *EVEN_MAX_RANGE, lambda x: int(round(x))),
            "avoid_corners": bool(v["avoid_corners"]), "skip_inner": bool(v["skip_inner"]),
            "min_perimeter_mm": num("min_perimeter_mm", *EVEN_MIN_PERIMETER_RANGE, float),
            "replace": bool(v["replace"])}


def ring_length(ring: list[Point]) -> float:
    return sum(math.dist(a, b) for a, b in zip(ring, ring[1:]))


def even_count(perimeter: float, width: float, mode: str, count: int, spacing_mm: float,
               max_count: int = 0) -> int:
    """Steg-Anzahl für eine Kontur – Regeln wie :func:`lumacut_job.cutpath.tab_intervals`:
    ``spacing`` → ein Steg je ``spacing_mm`` (mindestens 1, mit ``max_count`` > 0
    höchstens so viele); jedes Schnittstück mindestens so lang wie ein Steg."""
    if mode == "spacing":
        n = max(1, int((perimeter + 1e-6) // max(spacing_mm, 1e-9)))   # 120 mm / 30 mm = 4
        if max_count > 0:
            n = min(n, int(max_count))
    else:
        n = int(count)
    return max(0, min(n, int((perimeter + 1e-6) // (2 * max(width, 1e-9)))))


def even_points_on_ring(ring: list[Point], n: int, width: float,
                        avoid_corners: bool = True) -> list[Point]:
    """``n`` Steg-Mitten gleichmäßig auf dem geschlossenen Ring (bei ``(i + ½) · L / n``),
    von Start und – mit ``avoid_corners`` – Ecken (≥ 30°) um ``width/2 + 0,5`` mm
    weggeschoben, höchstens um ein Viertel des Abschnitts (wie die automatischen Stege)."""
    from lumacut_job.cutpath import _cum_lengths, _point_at, corner_positions, tab_centers
    if n <= 0 or len(ring) < 4:
        return []
    cum = _cum_lengths(ring)
    corners = corner_positions(ring, cum) if avoid_corners else []
    return [_point_at(ring, cum, c)[0]
            for c in tab_centers(cum[-1], n, max(width, 1e-9), corners)]


def start_ring_index(shape: Shape, rings: list[list[Point]]) -> int:
    """Index des Rings, auf dem der manuelle Startpunkt des Objekts liegt (der
    nächste, höchstens :data:`startpoint.START_SNAP_MM` entfernt – wie beim
    Senden), sonst ``-1``."""
    p = shape.start_point() if shape is not None else None
    if p is None or not rings:
        return -1
    from .startpoint import START_SNAP_MM
    d, _q, k = nearest_on_rings(rings, p)
    return k if d <= START_SNAP_MM else -1


def _inner_flags(rings: list[list[Point]], others: list[list[Point]]) -> list[bool]:
    """Liegt der Ring in einem anderen (größeren) Ring – eigenem Loch-Umriss oder
    einem anderen Objekt derselben Ebene? Ein Prüfpunkt je Ring wie beim Planer."""
    from .pathjoin import _inside, _signed_area
    out = []
    for ring in rings:
        area = abs(_signed_area(ring[:-1]))
        xs, ys = [p[0] for p in ring], [p[1] for p in ring]
        probe = ring[0]
        inner = False
        for other in others:
            if other is ring:
                continue
            oxs, oys = [p[0] for p in other], [p[1] for p in other]
            if (min(oxs) > min(xs) + 1e-9 or max(oxs) < max(xs) - 1e-9
                    or min(oys) > min(ys) + 1e-9 or max(oys) < max(ys) - 1e-9):
                continue        # Box umschließt nicht: kann nicht außen liegen
            if abs(_signed_area(other[:-1])) <= area + 1e-9:
                continue
            if _inside(probe, other[:-1]):
                inner = True
                break
        out.append(inner)
    return out


@dataclass
class EvenTabsResult:
    """Ergebnis von :func:`place_even_tabs` (``add[i]`` ersetzt ``remove[i]``)."""
    remove: list[Shape] = field(default_factory=list)
    add: list[Shape] = field(default_factory=list)
    tabs: int = 0              # neu gesetzte Stege
    contours: int = 0          # Konturen mit neuen Stegen
    skipped_inner: int = 0     # innere Konturen ausgelassen
    too_short: int = 0         # Konturen unter dem Mindestumfang / zu kurz für einen Steg
    removed: int = 0           # ersetzte (alte) manuelle Stege
    zero_width_layers: list[str] = field(default_factory=list)
    auto_layers: list[str] = field(default_factory=list)
    #: Ausgelassene Konturen für die Vorschau: ``(Ring, "inner" | "short")``.
    skipped: list[tuple[list[Point], str]] = field(default_factory=list)
    from_start: int = 0        # Konturen ab dem manuellen Startpunkt verteilt

    @property
    def changed(self) -> int:
        return len(self.add)

    def readout(self) -> str:
        if not self.tabs:
            text = "keine Stege gesetzt"
            if self.removed:
                text = f"{self.removed} manuelle(r) Steg(e) entfernt, keine neuen gesetzt"
        else:
            text = (f"{self.tabs} Steg{'e' if self.tabs != 1 else ''} an {self.contours} "
                    f"Kontur{'en' if self.contours != 1 else ''} ({self.changed} Objekt(e))")
            if self.removed:
                text += f" · {self.removed} alte(r) manuelle(r) Steg(e) ersetzt"
        if self.skipped_inner:
            text += f" · {self.skipped_inner} innere Kontur(en) ausgelassen"
        if self.too_short:
            text += f" · {self.too_short} Kontur(en) zu kurz"
        if self.from_start and self.tabs:
            text += f" · {self.from_start} Kontur(en) ab dem gesetzten Startpunkt verteilt"
        if self.zero_width_layers:
            names = ", ".join(f"„{n}“" for n in self.zero_width_layers)
            text += (f" · Achtung: Stegbreite 0 auf Ebene {names} – dort wird kein Steg geschnitten "
                     "(Schnitt-Optionen)")
        if self.auto_layers and self.tabs:
            text += " · ersetzen an diesen Konturen die automatischen Stege der Ebene"
        return text


def place_even_tabs(doc, shapes: Iterable[Shape], values: dict | None = None) -> EvenTabsResult:
    """Manuelle Stege gleichmäßig auf die geschlossenen Konturen von ``shapes`` setzen.

    Stegbreite je Objekt aus seiner Ebene (``tab_width_mm``; bei 0 wird mit
    :data:`FALLBACK_WIDTH_MM` verteilt und gewarnt). ``skip_inner`` lässt
    Konturen aus, die in einer anderen geschlossenen Kontur derselben Ebene
    liegen (Löcher fallen heraus und brauchen keinen Steg). Mit ``replace``
    ersetzen die neuen Stege die manuellen Stege des Objekts, sonst kommen sie
    hinzu (zu nahe an einem vorhandenen entfallen). Objekte, an denen kein
    neuer Steg entsteht, bleiben unverändert (auch ihre alten Stege) und
    erscheinen nicht im Ergebnis. Die Kontur, auf der ein manueller Startpunkt
    des Objekts liegt (höchstens :data:`startpoint.START_SNAP_MM` entfernt, wie
    beim Senden), wird ab diesem Punkt verteilt (:func:`start_ring_index`).
    """
    v = _clean_even(values)
    res = EvenTabsResult()
    shapes = [s for s in shapes if s is not None and s.kind in TAB_KINDS]
    layer_rings: dict[str, list[list[Point]]] = {}
    if v["skip_inner"]:
        lids = {s.layer_id for s in shapes}
        for s in doc.shapes:
            if s.layer_id in lids and s.kind in TAB_KINDS:
                layer_rings.setdefault(s.layer_id, []).extend(closed_rings(s))
    zero, auto = [], []
    for s in shapes:
        rings = closed_rings(s)
        if not rings:
            continue
        layer = doc.layer(s.layer_id) if hasattr(doc, "layer") else None
        width = float(getattr(layer, "tab_width_mm", FALLBACK_WIDTH_MM) or 0.0)
        name = getattr(layer, "name", "")
        if width <= 0:
            width = FALLBACK_WIDTH_MM
            if name not in zero:
                zero.append(name)
        elif layer is not None and (layer.tab_count > 0 or layer.tab_spacing_mm > 0) and name not in auto:
            auto.append(name)
        flags = (_inner_flags(rings, layer_rings.get(s.layer_id, rings)) if v["skip_inner"]
                 else [False] * len(rings))
        pts: list[Point] = []
        contours = 0
        from_start = 0
        k_start = start_ring_index(s, rings)
        for k, (ring, inner) in enumerate(zip(rings, flags)):
            if inner:
                res.skipped_inner += 1
                res.skipped.append((ring, "inner"))
                continue
            L = ring_length(ring)
            n = even_count(L, width, v["mode"], v["count"], v["spacing_mm"], v["max_count"])
            if L < v["min_perimeter_mm"] or L < 2 * width + 1.0 or n <= 0:
                res.too_short += 1
                res.skipped.append((ring, "short"))
                continue
            if k == k_start:
                from .startpoint import rotate_ring_to
                ring = rotate_ring_to(ring, s.start_point())
            new = even_points_on_ring(ring, n, width, v["avoid_corners"])
            if new:
                pts.extend(new)
                contours += 1
                from_start += k == k_start
        old = s.tab_points()
        keep = [] if v["replace"] else list(old)
        if keep:
            pts = [p for p in pts if all(math.dist(p, q) >= MIN_TAB_DISTANCE_MM for q in keep)]
        if not pts:
            continue            # nichts zu setzen: vorhandene Stege bleiben unangetastet
        new_shape = with_tab_points(s, keep + pts)
        if new_shape.tabs == s.tabs:
            continue
        res.remove.append(s)
        res.add.append(new_shape)
        res.tabs += len(pts)
        res.contours += contours
        res.removed += len(old) if v["replace"] else 0
        res.from_start += from_start
    # Warnungen nur für Ebenen, auf denen wirklich etwas gesetzt wird
    used = {getattr(doc.layer(s.layer_id), "name", "") for s in res.add} if hasattr(doc, "layer") else set()
    res.zero_width_layers = [n for n in zero if n in used]
    res.auto_layers = [n for n in auto if n in used]
    return res


# --- Stege folgen dem Startpunkt -------------------------------------------------------

#: Ein Steg gehört zu einer Kontur bzw. zu einem gleichmäßigen Platz höchstens so weit entfernt (mm).
FOLLOW_TOL_MM = 0.05


def ring_origin(shape: Shape, rings: list[list[Point]], k: int) -> list[Point]:
    """Ring ``k`` so gedreht, wie „Stege gleichmäßig setzen …“ ihn verteilt: ab dem
    manuellen Startpunkt, wenn er auf diesem Ring liegt, sonst ab dem gezeichneten Start."""
    ring = rings[k]
    if start_ring_index(shape, rings) == k:
        from .startpoint import rotate_ring_to
        return rotate_ring_to(ring, shape.start_point())
    return ring


def even_pattern(ring: list[Point], pts: list[Point], width: float) -> bool | None:
    """Liegen ``pts`` genau so, wie :func:`even_points_on_ring` sie ab dem Anfang von
    ``ring`` setzt? Dann die Eckenregel (``True`` = „Ecken meiden“), sonst ``None``.
    Liegen sie mit und ohne Eckenregel gleich (kein Steg nahe einer Ecke), gilt
    „Ecken meiden“ (Voreinstellung des Dialogs; ein Steg auf einer Ecke hält schlecht)."""
    n = len(pts)
    if n <= 0:
        return None
    for avoid in (True, False):
        want = even_points_on_ring(ring, n, width, avoid)
        if len(want) == n and all(any(math.dist(p, q) <= FOLLOW_TOL_MM for q in pts) for p in want) \
                and all(any(math.dist(p, q) <= FOLLOW_TOL_MM for q in want) for p in pts):
            return avoid
    return None


@dataclass
class FollowResult:
    """Ergebnis von :func:`follow_start`."""
    shape: Shape               # neue Form (Startpunkt von ``new``, Stege ggf. neu verteilt)
    contours: int = 0          # Konturen mit neu verteilten Stegen
    tabs: int = 0              # davon betroffene Stege
    kept: int = 0              # Konturen mit Stegen, die nicht gleichmäßig lagen (unverändert)
    too_short: int = 0         # gleichmäßige Konturen, zu kurz für ihre Steg-Anzahl (nur übertragen)
    #: Wo neu verteilt wurde (Text der Meldung): ab dem neuen Start / auf dem neuen Umriss.
    where: str = "ab dem neuen Start"
    #: Was mit von Hand gesetzten Stegen geschah (Text der Meldung).
    kept_text: str = "unverändert"

    def readout(self) -> str:
        parts = []
        if self.contours:
            parts.append(f"{self.tabs} Steg{'e' if self.tabs != 1 else ''} an {self.contours} "
                         f"Kontur{'en' if self.contours != 1 else ''} {self.where} "
                         "gleichmäßig neu verteilt")
        if self.kept:
            parts.append(f"von Hand gesetzte Stege an {self.kept} Kontur"
                         f"{'en' if self.kept != 1 else ''} {self.kept_text}")
        if self.too_short:
            parts.append(f"{self.too_short} Kontur{'en' if self.too_short != 1 else ''} zu kurz "
                         "für ihre Stege – nur übertragen")
        return " · ".join(parts)

    def add(self, other: "FollowResult") -> None:
        """Zählung von ``other`` dazunehmen (mehrere Objekte in einer Meldung)."""
        self.contours += other.contours
        self.tabs += other.tabs
        self.kept += other.kept
        self.too_short += other.too_short


def tab_width_for(doc, shape: Shape) -> float:
    """Rechenbreite der Stege wie :func:`place_even_tabs` (Ebene, sonst Ersatzbreite)."""
    layer = doc.layer(shape.layer_id) if doc is not None and hasattr(doc, "layer") else None
    width = float(getattr(layer, "tab_width_mm", FALLBACK_WIDTH_MM) or 0.0)
    return width if width > 0 else FALLBACK_WIDTH_MM


def follow_start(doc, old: Shape, new: Shape) -> FollowResult:
    """Stege von ``old`` an den Startpunkt von ``new`` anpassen (gleiche Geometrie,
    nur ``start`` anders – gesetzt, verschoben oder entfernt).

    Für jede Kontur, deren Verteil-Anfang sich ändert (der Startpunkt kommt auf sie,
    wandert auf ihr oder verlässt sie – dann gilt wieder ihr gezeichneter Start):
    liegen ihre Stege genau auf den Plätzen, die „Stege gleichmäßig setzen …“ ab dem
    alten Anfang ergibt (:func:`even_pattern`, mit oder ohne „Ecken meiden“, Stegbreite
    der Ebene), werden sie mit derselben Anzahl und Eckenregel ab dem neuen Anfang
    gesetzt – jeder hält so den Startabstand, der Planer schiebt keinen. Andere Stege
    (von Hand gesetzt / verschoben, hinzugefügt) bleiben unverändert."""
    res = FollowResult(shape=new)
    pts = old.tab_points()
    rings = closed_rings(new)
    if not pts or not rings:
        return res
    width = tab_width_for(doc, new)
    on_ring: dict[int, list[Point]] = {}
    loose: list[Point] = []
    for p in pts:
        d, _q, k = nearest_on_rings(rings, p)
        if k >= 0 and d <= FOLLOW_TOL_MM:
            on_ring.setdefault(k, []).append(p)
        else:
            loose.append(p)
    out: list[Point] = list(loose)
    changed = False
    for k in sorted(on_ring):
        mine = on_ring[k]
        before, after = ring_origin(old, rings, k), ring_origin(new, rings, k)
        if math.dist(before[0], after[0]) <= 1e-6:
            out.extend(mine)
            continue
        avoid = even_pattern(before, mine, width)
        moved = even_points_on_ring(after, len(mine), width, avoid) if avoid is not None else []
        if len(moved) != len(mine):
            res.kept += 1
            out.extend(mine)
            continue
        out.extend(moved)
        changed = True
        res.contours += 1
        res.tabs += len(mine)
    if changed:
        res.shape = with_tab_points(new, out)
    return res


# --- Stege folgen dem geänderten Umriss ------------------------------------------------

def _same_points(a: list[Point], b: list[Point], tol: float = 1e-6) -> bool:
    return len(a) == len(b) and all(any(math.dist(p, q) <= tol for q in b) for p in a)


def _ring_map(old_rings: list[list[Point]], new_rings: list[list[Point]],
              on_old: dict[int, list[Point]]) -> dict[int, int]:
    """Welcher neue Ring gehört zu welchem alten (nur alte Ringe mit Stegen)? Gleiche
    Ring-Anzahl: derselbe Index (Knoten bearbeiten, Vereinfachen und Abrunden behalten
    die Reihenfolge); sonst der neue Ring, dem die meisten Stege des alten am nächsten
    liegen. Wollen zwei alte Ringe auf denselben neuen (ein Ring verschwand), gewinnt
    der, dessen Stege ihm im Mittel am nächsten liegen; bei Gleichstand keiner."""
    out: dict[int, int] = {}
    for k, mine in on_old.items():
        if len(old_rings) == len(new_rings):
            out[k] = k
            continue
        votes: dict[int, int] = {}
        for p in mine:
            _d, _q, j = nearest_on_rings(new_rings, p)
            if j >= 0:
                votes[j] = votes.get(j, 0) + 1
        if votes:
            out[k] = max(sorted(votes), key=lambda j: votes[j])
    by_new: dict[int, list[int]] = {}
    for k, j in out.items():
        by_new.setdefault(j, []).append(k)
    result: dict[int, int] = {}
    for j, ks in by_new.items():
        if len(ks) == 1:
            result[ks[0]] = j
            continue
        def mean(k):
            return sum(nearest_on_rings([new_rings[j]], p)[0] for p in on_old[k]) / len(on_old[k])
        ranked = sorted(ks, key=mean)
        if mean(ranked[1]) - mean(ranked[0]) > 1e-6:
            result[ranked[0]] = j
    return result


def follow_shape(doc, old: Shape, new: Shape) -> FollowResult:
    """Stege von ``old`` nach einer Umrissänderung auf ``new`` verteilen.

    ``new`` ist das Ergebnis von Knoten bearbeiten, Vereinfachen, Abrunden oder
    Eckenradius – seine Stege sind schon auf den nächsten Umrisspunkt übertragen
    (:func:`carry_tabs`), sein Startpunkt mit :func:`startpoint.carry_start`. Für jede
    Kontur von ``old``, deren Stege genau so liegen, wie „Stege gleichmäßig setzen …“
    sie ab ihrem Anfang setzt (:func:`even_pattern`, mit oder ohne „Ecken meiden“,
    Stegbreite der Ebene), werden die Stege auf der zugehörigen Kontur von ``new`` mit
    derselben Anzahl und Eckenregel ab deren Anfang (manueller Startpunkt, sonst
    gezeichneter Start) neu gesetzt – so halten sie Abstand zu neuen Ecken und zum
    Start und bleiben gleichmäßig. Ist die neue Kontur für die Anzahl zu kurz, bleiben
    die übertragenen Stege. Von Hand gesetzte Stege bleiben übertragen wie bisher.
    Ergibt die Verteilung dieselben Plätze wie die übertragenen Stege, bleibt ``new``
    unverändert (Datei byte-gleich)."""
    res = FollowResult(shape=new, where="auf dem neuen Umriss", kept_text="nur übertragen")
    pts = old.tab_points()
    old_rings = closed_rings(old)
    new_rings = closed_rings(new)
    if not pts or not old_rings or not new_rings:
        return res
    width = tab_width_for(doc, old)
    on_old: dict[int, list[Point]] = {}
    for p in pts:
        d, _q, k = nearest_on_rings(old_rings, p)
        if k >= 0 and d <= FOLLOW_TOL_MM:
            on_old.setdefault(k, []).append(p)
    if not on_old:
        return res
    ring_of = _ring_map(old_rings, new_rings, on_old)
    carried: dict[int, list[Point]] = {}
    loose: list[Point] = []
    for q in new.tab_points():
        d, _p, j = nearest_on_rings(new_rings, q)
        if j >= 0 and d <= FOLLOW_TOL_MM:
            carried.setdefault(j, []).append(q)
        else:
            loose.append(q)
    target: dict[int, list[Point]] = {}
    for k in sorted(on_old):
        mine = on_old[k]
        avoid = even_pattern(ring_origin(old, old_rings, k), mine, width)
        if avoid is None:
            res.kept += 1
            continue
        j = ring_of.get(k)
        if j is None:
            res.kept += 1
            continue
        n = len(mine)
        L = ring_length(new_rings[j])
        if L < 2 * width + 1.0 or n > int((L + 1e-6) // (2 * max(width, 1e-9))):
            res.too_short += 1
            continue
        want = even_points_on_ring(ring_origin(new, new_rings, j), n, width, avoid)
        if len(want) != n:
            res.too_short += 1
            continue
        if _same_points(want, carried.get(j, [])):
            continue            # liegen schon so (z. B. unveränderte Kontur)
        target[j] = want
        if not _same_points(want, mine):
            res.contours += 1
            res.tabs += n
    if not target:
        return res
    out = list(loose)
    for j in sorted(set(carried) | set(target)):
        out.extend(target.get(j, carried.get(j, [])))
    res.shape = with_tab_points(new, out)
    return res


def follow_shapes(doc, pairs: Iterable[tuple[Shape, Shape]]) -> tuple[list[Shape], FollowResult]:
    """:func:`follow_shape` für mehrere ``(alt, neu)``-Paare: neue Formen und Gesamtzählung."""
    total = FollowResult(shape=None, where="auf dem neuen Umriss", kept_text="nur übertragen")
    out = []
    for old, new in pairs:
        r = follow_shape(doc, old, new)
        out.append(r.shape)
        total.add(r)
    return out, total
