"""Schraffur (Vektor-Füllung) geschlossener Konturen – ohne Qt.

:func:`hatch_lines` legt parallele Linien im Abstand ``interval_mm`` unter
dem Winkel ``angle_deg`` (0° = waagerecht, gegen den Uhrzeigersinn auf dem
Bildschirm gemessen) über eine Menge geschlossener Polygone und schneidet sie
nach der **Gerade-Ungerade-Regel** zu: Löcher (z. B. in „O“, „A“ oder einem
Rahmen aus zwei Rechtecken) bleiben frei. :func:`fill_segments` setzt die
Ebenen-Einstellung um (``"hatch"`` = eine Richtung, ``"crosshatch"`` =
zusätzlich um 90° gedreht, ``"offset"`` = konzentrische Konturen nach innen,
siehe :func:`offset_fill_rings`). Welche Objekte einer Ebene gemeinsam als
*eine* Fläche gefüllt werden, legt ``FILL_GROUPINGS`` fest
(``export.layer_fill_blocks``).

Die Linien liegen auf einem festen Raster ``(k + ½) · interval`` (in der
gedrehten Lage, gemessen vom Ursprung; der halbe Versatz vermeidet Linien
genau auf achsparallelen Kanten), damit benachbarte Objekte derselben Ebene
lückenlos ineinander übergehen. Ergebnis: Liste von Strecken
``((x0, y0), (x1, y1))`` in denselben Koordinaten wie die Eingabe, in
Fahr-Reihenfolge (bidirektional: jede zweite Rasterzeile rückwärts).

Laufzeit ~ O(Kanten + Schnittpunkte): jede Kante trägt sich nur in die
Rasterzeilen ein, die sie überspannt.
"""

from __future__ import annotations

import math
from typing import Iterable, Sequence

Point = tuple[float, float]
Segment = tuple[Point, Point]

FILL_MODES = ("none", "hatch", "crosshatch", "offset")
FILL_LABELS = {"none": "Keine", "hatch": "Schraffur", "crosshatch": "Kreuzschraffur",
               "offset": "Offset-Füllung"}
#: Füllmodi, für die Winkel und Bidirektional eine Bedeutung haben
LINE_FILL_MODES = ("hatch", "crosshatch")
#: Welche Objekte einer Ebene gemeinsam gefüllt werden (LightBurn „Fill shapes
#: individually“ / „Fill groups together“ / „Fill all shapes at once“):
#: gemeinsam gefüllte Objekte bilden *eine* Fläche nach der Gerade-Ungerade-Regel –
#: ein Kreis in einem Rechteck wird so zum Loch, auch als getrennte Objekte.
FILL_GROUPINGS = ("individual", "groups", "together")
FILL_GROUPING_LABELS = {"individual": "Jedes Objekt einzeln",
                        "groups": "Gruppen zusammen",
                        "together": "Alle Objekte zusammen"}
#: Überlauf (LightBurn „Overscanning“) je Ende einer Schraffurlinie, Laser aus –
#: der Kopf erreicht vor dem Einschalten die volle Geschwindigkeit (gcode.py).
#: Gilt nur für LINE_FILL_MODES; 0 = aus (Ausgabe unverändert).
OVERSCAN_RANGE = (0.0, 20.0)    # mm, wie die Bild-Gravur (ImageSettings.overscan_mm)
MAX_OFFSET_RINGS = 5000         # Schutz wie MAX_LINES_PER_PASS
OFFSET_SIMPLIFY_MM = 0.005      # Ringe vereinfachen (weit unter der Strahlbreite)
OFFSET_ARC_TOL_MM = 0.02        # Sehnenfehler gerundeter Ecken (wie shape_paths)
INTERVAL_RANGE = (0.05, 20.0)   # mm
DEFAULT_INTERVAL_MM = 0.2
MAX_LINES_PER_PASS = 20000      # Schutz vor versehentlich winzigen Abständen
_MIN_SEG = 1e-6


def normalize_angle_180(deg: float) -> float:
    """Schraffurwinkel auf [0, 180) (180° ergibt dieselben Linien wie 0°)."""
    a = math.fmod(float(deg), 180.0)
    if a < 0:
        a += 180.0
    return 0.0 if abs(a - 180.0) < 1e-9 else round(a, 3)


def _rot(p: Point, c: float, s: float) -> Point:
    return (p[0] * c - p[1] * s, p[0] * s + p[1] * c)


def hatch_lines(polygons: Iterable[Sequence[Point]], interval_mm: float, angle_deg: float = 0.0,
                bidirectional: bool = True) -> list[Segment]:
    """Schraffurstrecken innerhalb von ``polygons`` (Gerade-Ungerade-Regel).

    Polygone gelten als geschlossen (der letzte Punkt muss nicht wiederholt
    werden); Polygone mit weniger als drei Punkten werden ignoriert.
    """
    interval = float(interval_mm)
    if not interval > 0 or not math.isfinite(interval):
        raise ValueError("Linienabstand muss > 0 sein")
    # Linien unter +angle (Bildschirm, y nach unten) = in Weltkoordinaten
    # waagerecht, nachdem um +angle gedreht wurde; Rückdrehung um -angle.
    # Bildschirm-y zeigt nach unten, daher entspricht "gegen den Uhrzeigersinn
    # auf dem Bildschirm" einer Drehung um -angle in mathematischer Lage.
    a = math.radians(angle_deg)
    c, s = math.cos(a), math.sin(a)          # Welt -> gedreht (um +a)
    edges: list[tuple[float, float, float, float]] = []
    ymin = math.inf
    ymax = -math.inf
    for poly in polygons:
        pts = [_rot((float(x), float(y)), c, s) for x, y in poly]
        if len(pts) >= 2 and pts[0] == pts[-1]:
            pts.pop()
        if len(pts) < 3:
            continue
        for i, p in enumerate(pts):
            q = pts[i - 1]
            if p[1] == q[1]:
                continue  # waagerechte Kanten schneiden keine Rasterzeile sauber
            edges.append((q[0], q[1], p[0], p[1]))
            ymin = min(ymin, p[1], q[1])
            ymax = max(ymax, p[1], q[1])
    if not edges:
        return []
    k0 = math.ceil(ymin / interval - 0.5 - 1e-9)
    k1 = math.floor(ymax / interval - 0.5 + 1e-9)
    if k1 - k0 + 1 > MAX_LINES_PER_PASS:
        raise ValueError(f"Zu viele Schraffurlinien ({k1 - k0 + 1}); Linienabstand vergrößern")
    rows: dict[int, list[float]] = {}
    for x0, y0, x1, y1 in edges:
        lo, hi = (y0, y1) if y0 < y1 else (y1, y0)
        # halboffen [lo, hi): Ecken werden genau einmal gezählt
        ka = math.ceil(lo / interval - 0.5 - 1e-12)
        kb = math.ceil(hi / interval - 0.5 - 1e-12) - 1
        if kb < ka:
            continue
        inv = (x1 - x0) / (y1 - y0)
        for k in range(max(ka, k0), min(kb, k1) + 1):
            y = (k + 0.5) * interval
            if lo <= y < hi:
                rows.setdefault(k, []).append(x0 + (y - y0) * inv)
    ci, si = c, -s                           # gedreht -> Welt (um -a)
    out: list[Segment] = []
    forward = True
    for k in sorted(rows):
        xs = sorted(rows[k])
        y = (k + 0.5) * interval
        row: list[Segment] = []
        for i in range(0, len(xs) - 1, 2):
            xa, xb = xs[i], xs[i + 1]
            if xb - xa > _MIN_SEG:
                row.append((_rot((xa, y), ci, si), _rot((xb, y), ci, si)))
        if not row:
            continue
        if not forward:
            row = [(b, a) for a, b in reversed(row)]
        out.extend(row)
        if bidirectional:
            forward = not forward
    return out


# --- Einstieg in einen Füllblock (freie Startecke) -------------------------------
#
# Ein Schraffurblock (``hatch_lines`` / ``fill_segments``) besteht aus Zeilen:
# aufeinanderfolgende Strecken auf derselben Rasterzeile (Löcher teilen eine
# Zeile in mehrere Strecken) mit derselben Fahrtrichtung. Ein Block kann an
# jeder seiner vier Ecken begonnen werden – erste oder letzte Zeile, an deren
# Anfang oder Ende –, ohne dass sich Linien, Abstände oder die
# Bidirektional-/Unidirektional-Regel ändern:
#
# ``FORWARD``  wie erzeugt;
# ``REVERSED`` Zeilen rückwärts *und* jede Strecke umgedreht (der bisherige
#              „vom anderen Ende“-Einstieg);
# ``ROWS_REVERSED`` Zeilen rückwärts, jede Zeile in ihrer Richtung;
# ``ROWS_FLIPPED``  Zeilen in Reihenfolge, jede Zeile umgedreht.
#
# Wechselnde Richtungen bleiben wechselnd, gleiche bleiben gleich; Überlauf und
# Scan-Versatz hängen nur von der Fahrtrichtung jeder Strecke ab (gcode.py).
FORWARD, REVERSED, ROWS_REVERSED, ROWS_FLIPPED = range(4)
_ROW_EPS = 1e-6


def _unit(seg: Segment):
    (ax, ay), (bx, by) = seg
    d = math.hypot(bx - ax, by - ay)
    return None if d < 1e-12 else ((bx - ax) / d, (by - ay) / d)


def fill_block_rows(block: Sequence[Segment]) -> list[list[Segment]]:
    """Zeilen eines Schraffurblocks (siehe oben), in Block-Reihenfolge.

    Zwei aufeinanderfolgende Strecken gehören zu einer Zeile, wenn sie dieselbe
    Richtung haben, auf einer Geraden liegen und die zweite hinter der ersten
    beginnt. Nulllange Strecken bilden eine eigene Zeile.
    """
    rows: list[list[Segment]] = []
    prev_u = None
    for seg in block:
        u = _unit(seg)
        if rows and u is not None and prev_u is not None:
            last = rows[-1][-1]
            dx, dy = seg[0][0] - last[0][0], seg[0][1] - last[0][1]
            same_dir = u[0] * prev_u[0] + u[1] * prev_u[1] > 1.0 - 1e-9
            on_line = abs(dx * prev_u[1] - dy * prev_u[0]) <= _ROW_EPS
            ahead = ((seg[0][0] - last[1][0]) * u[0] + (seg[0][1] - last[1][1]) * u[1]
                     >= -_ROW_EPS)
            if same_dir and on_line and ahead:
                rows[-1].append(seg)
                prev_u = u
                continue
        rows.append([seg])
        prev_u = u
    return rows


def fill_block_entries(block: Sequence[Segment], reversible: bool = True,
                       corners: bool = False) -> list[tuple[Point, Point, int]]:
    """Mögliche Einstiege ``(start, ende, variante)`` eines Füllblocks.

    Immer ``FORWARD``; mit ``reversible`` auch ``REVERSED``; mit ``corners``
    (nur Schraffur, nie Offset-Ringe) zusätzlich die beiden übrigen Ecken,
    sofern der Block mindestens zwei Zeilen hat. Die Reihenfolge ist zugleich
    die Vorrangregel bei gleichem Abstand.
    """
    if not block:
        return []
    out = [(block[0][0], block[-1][1], FORWARD)]
    if not reversible:
        return out
    out.append((block[-1][1], block[0][0], REVERSED))
    if corners:
        rows = fill_block_rows(block)
        if len(rows) >= 2:
            out.append((rows[-1][0][0], rows[0][-1][1], ROWS_REVERSED))
            out.append((rows[0][-1][1], rows[-1][0][0], ROWS_FLIPPED))
    return out


def fill_block_variant(block: Sequence[Segment], variant: int) -> list[Segment]:
    """Den Block in der Einstiegs-Variante (``FORWARD`` … ``ROWS_FLIPPED``)."""
    if variant == FORWARD:
        return list(block)
    if variant == REVERSED:
        return [(b, a) for a, b in reversed(block)]
    rows = fill_block_rows(block)
    if variant == ROWS_REVERSED:
        return [seg for row in reversed(rows) for seg in row]
    if variant == ROWS_FLIPPED:
        return [(b, a) for row in rows for a, b in reversed(row)]
    raise ValueError(f"Unbekannte Einstiegs-Variante: {variant}")


def nearest_fill_entry(block: Sequence[Segment], pos: Point | None, reversible: bool = True,
                       corners: bool = False) -> tuple[float, list[Segment]]:
    """Abstand von ``pos`` und der Block ab dem nächsten erlaubten Einstieg.

    Bei Gleichstand gewinnt die frühere Variante (``FORWARD`` vor ``REVERSED``
    vor den Ecken), ohne Position (``None``) bleibt der Block, wie er ist.
    """
    if not block:
        return 0.0, []
    if pos is None:
        return 0.0, list(block)
    best_d, best_v = math.inf, FORWARD
    for entry, _exit, v in fill_block_entries(block, reversible, corners):
        d = math.dist(pos, entry)
        if d < best_d:
            best_d, best_v = d, v
    return best_d, fill_block_variant(block, best_v)


def _even_odd_area(polygons: Iterable[Sequence[Point]]):
    """Fläche nach der Gerade-Ungerade-Regel (wie :func:`hatch_lines`) als Shapely-Geometrie."""
    from shapely.geometry import Polygon
    area = None
    for poly in polygons:
        pts = [(float(x), float(y)) for x, y in poly]
        if len(pts) >= 2 and pts[0] == pts[-1]:
            pts.pop()
        if len(pts) < 3:
            continue
        g = Polygon(pts).buffer(0)
        if g.is_empty:
            continue
        area = g if area is None else area.symmetric_difference(g)
    return area


def _rings_of(geom) -> list[list[Point]]:
    """Außen- und Innenringe aller Polygone (offen, ohne wiederholten Endpunkt)."""
    parts = getattr(geom, "geoms", None)
    parts = list(parts) if parts is not None else [geom]
    rings: list[list[Point]] = []
    for g in parts:
        if g.geom_type != "Polygon" or g.is_empty:
            continue
        for ring in (g.exterior, *g.interiors):
            pts = [(float(x), float(y)) for x, y in ring.coords]
            if len(pts) >= 2 and pts[0] == pts[-1]:
                pts.pop()
            if len(pts) >= 3:
                rings.append(pts)
    return rings


def _start_nearest(ring: list[Point], pos: Point) -> list[Point]:
    i = min(range(len(ring)), key=lambda k: math.dist(ring[k], pos))
    return ring[i:] + ring[:i]


def _quad_segs(distance: float) -> int:
    """Segmente je Viertelkreis für gerundete Ecken mit Sehnenfehler ≤ OFFSET_ARC_TOL_MM."""
    if distance <= OFFSET_ARC_TOL_MM:
        return 2
    step = 2 * math.acos(1 - OFFSET_ARC_TOL_MM / distance)
    return max(2, min(32, math.ceil((math.pi / 2) / step)))


def _offset_levels(part, interval: float) -> list[list[list[Point]]]:
    """Ringe einer zusammenhängenden Fläche, Tiefe für Tiefe (äußerste zuerst)."""
    levels: list[list[list[Point]]] = []
    count = 0
    k = 0
    while True:
        d = (k + 0.5) * interval
        g = part.buffer(-d, quad_segs=_quad_segs(d), join_style="round")
        if g.is_empty:
            break
        if OFFSET_SIMPLIFY_MM > 0:
            g = g.simplify(OFFSET_SIMPLIFY_MM, preserve_topology=True)
        level = _rings_of(g)
        count += len(level)
        if count > MAX_OFFSET_RINGS:
            raise ValueError("Zu viele Offset-Ringe; Linienabstand vergrößern")
        if level:
            levels.append(level)
        k += 1
    return levels


def _nearest_index(items: list[list[Point]], pos: Point) -> int:
    return min(range(len(items)), key=lambda i: min(math.dist(p, pos) for p in items[i]))


def offset_fill_rings(polygons: Iterable[Sequence[Point]], interval_mm: float,
                      inside_out: bool = False) -> list[list[Point]]:
    """Offset-Füllung (LightBurn „Offset Fill“): konzentrische Konturen nach innen.

    Die Fläche (Gerade-Ungerade-Regel, Löcher bleiben frei) wird in Schritten
    von ``interval_mm`` nach innen versetzt; der erste Ring liegt ein halbes
    Intervall innerhalb der Kante (wie die Schraffur-Rasterzeilen), jeder
    weitere ein ganzes Intervall tiefer, bis die Fläche verschwindet. Löcher
    bekommen eigene Ringe, die nach außen wachsen. Ergebnis: geschlossene
    Ringe (Startpunkt nicht wiederholt) in Fahr-Reihenfolge.

    Getrennte Inseln (z. B. die Buchstaben eines Texts) werden nacheinander
    ganz gefüllt – zuerst die Insel, die dem vorigen Start am nächsten liegt –,
    damit der Kopf nicht für jede Tiefe zwischen den Inseln pendelt. Innerhalb
    einer Insel von außen nach innen (``inside_out=True``: von innen nach
    außen, die Kante zuletzt); innerhalb einer Tiefe zuerst der
    nächstgelegene Ring, begonnen am Punkt, der dem vorigen Start am nächsten
    liegt (kurze Leerfahrten). Stellen schmaler als ein Intervall bekommen
    keinen Ring (dort lasert die Kontur, wenn „Kontur mitlasern“ an ist).
    """
    interval = float(interval_mm)
    if not interval > 0 or not math.isfinite(interval):
        raise ValueError("Linienabstand muss > 0 sein")
    area = _even_odd_area(polygons)
    if area is None or area.is_empty:
        return []
    x0, y0, x1, y1 = area.bounds
    if min(x1 - x0, y1 - y0) / (2 * interval) > MAX_OFFSET_RINGS:
        raise ValueError("Zu viele Offset-Ringe; Linienabstand vergrößern")
    parts = [g for g in getattr(area, "geoms", [area])
             if g.geom_type == "Polygon" and not g.is_empty]
    islands: list[list[list[list[Point]]]] = []
    count = 0
    for part in parts:
        levels = _offset_levels(part, interval)
        count += sum(len(level) for level in levels)
        if count > MAX_OFFSET_RINGS:
            raise ValueError("Zu viele Offset-Ringe; Linienabstand vergrößern")
        if levels:
            islands.append(levels[::-1] if inside_out else levels)
    out: list[list[Point]] = []
    pos: Point | None = None
    while islands:
        # nächste Insel: deren erste Tiefe dem Kopf am nächsten liegt
        j = 0 if pos is None else min(
            range(len(islands)),
            key=lambda i: min(min(math.dist(p, pos) for p in r) for r in islands[i][0]))
        for level in islands.pop(j):
            level = list(level)
            while level:
                if pos is None:
                    ring = level.pop(0)
                else:
                    ring = _start_nearest(level.pop(_nearest_index(level, pos)), pos)
                out.append(ring)
                pos = ring[0]
    return out


def rings_to_segments(rings: Iterable[Sequence[Point]]) -> list[Segment]:
    """Geschlossene Ringe als lückenlose Streckenkette (innerhalb eines Rings
    beginnt jede Strecke am Ende der vorigen; der G-Code fährt dort kein ``G0``)."""
    segs: list[Segment] = []
    for ring in rings:
        pts = list(ring)
        if len(pts) < 3:
            continue
        for i, p in enumerate(pts):
            q = pts[(i + 1) % len(pts)]
            if math.dist(p, q) > _MIN_SEG:
                segs.append((p, q))
    return segs


def fill_segments(polygons: Sequence[Sequence[Point]], mode: str, interval_mm: float,
                  angle_deg: float = 0.0, bidirectional: bool = True,
                  inside_out: bool = False) -> list[Segment]:
    """Füllstrecken nach Füllmodus (``none`` / ``hatch`` / ``crosshatch`` / ``offset``).

    Bei ``offset`` haben Winkel und Bidirektional keine Bedeutung, ``inside_out``
    gilt nur dort (Ring-Reihenfolge von innen nach außen)."""
    if mode not in FILL_MODES:
        raise ValueError(f"Unbekannter Füllmodus: {mode}")
    if mode == "none":
        return []
    if mode == "offset":
        return rings_to_segments(offset_fill_rings(polygons, interval_mm, inside_out))
    segs = hatch_lines(polygons, interval_mm, angle_deg, bidirectional)
    if mode == "crosshatch":
        segs += hatch_lines(polygons, interval_mm, angle_deg + 90.0, bidirectional)
    return segs


def segments_length(segs: Iterable[Segment]) -> float:
    return sum(math.dist(a, b) for a, b in segs)
