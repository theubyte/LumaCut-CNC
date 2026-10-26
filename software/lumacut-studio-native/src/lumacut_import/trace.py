"""Bild nachzeichnen (Bitmap → Vektor), wie LightBurn „Trace Image“ – ohne Qt.

Ablauf je Bildobjekt (``Shape.kind == "image"``):

1. eingebettetes Graustufen-PNG mit OpenCV dekodieren;
2. optional glätten (Gauß-Weichzeichner, ``smoothing_px`` = Sigma in Bildpixeln),
   das nimmt Treppenstufen und JPEG-Rauschen vor dem Schwellwert weg;
3. Schwellwert: Pixel **dunkler** als ``threshold`` sind Vordergrund
   (``invert`` kehrt das um, z. B. für helle Schrift auf dunklem Grund);
   ``auto_threshold`` bestimmt den Wert nach dem Glätten selbst (Otsu,
   für Fotos und Scans mit unbekannter Helligkeit);
4. Konturen mit Löchern (``cv2.RETR_CCOMP``: Außenkontur + Löcher, Inseln in
   Löchern werden wieder eigene Teile);
5. Flecken entfernen (``min_area_mm2``) und vereinfachen
   (Douglas-Peucker, ``tolerance_mm``) – oder mit ``smooth_curves``
   („Glätten“) Kurven einpassen: Ecken bleiben spitz, dazwischen kubische
   Bézierkurven statt Pixeltreppe, fein abgeflacht (≤ ``FLAT_MM``), siehe
   :mod:`.curvefit`;
6. in Canvas-mm umrechnen – Bildbox inkl. Drehung des Bildobjekts.

Jeder Teil (Außenkontur + seine Löcher) wird ein ``polygon`` mit ``rings``
(Gerade-Ungerade-Füllung wie bei Boole-Ergebnissen), so dass Schraffur, Kerf
und Planer („innen zuerst“) Löcher richtig behandeln. Mehrere Teile werden
gruppiert.

Die Konturen liegen auf den Pixelkanten: die Maske wird 2× hochgerechnet
(damit auch 1 Pixel breite Linien eine Fläche haben), OpenCV liefert die
Randpixel-Mitten, shapely legt sie ¼ Bildpixel nach außen (Gehrung). Der Bildrand wird mit
Weiß aufgefüllt, damit Flächen am Rand geschlossene Konturen ergeben.

Mode ``centerline`` (``TraceSettings.mode``) returns open centre lines for line
art instead of outlines (``TraceResult.lines`` → ``path`` objects), see
:mod:`.centerline`.

Laufzeit: Bilder über ``MAX_PIXELS`` und Masken mit zu vielen Randpunkten oder
Teilen werden vor jeder shapely-Arbeit abgelehnt. Teile mit vielen Löchern
(> ``MANY_HOLES``) werden Ring für Ring verbreitert und vereinfacht (STRtree
statt der in GEOS etwa quadratischen Lochzuordnung); ``time_limit_s`` ist die
Notbremse dazu.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

import numpy as np

from lumacut_canvas.model import Shape, new_id, rotate_point

MAX_PARTS = 20000
MAX_POINTS = 400_000
MAX_RAW_POINTS = 400_000           # Randpunkte vor dem Vereinfachen (Rauschschutz)
MAX_PIXELS = 40_000_000            # größere Bilder vorher verkleinern (Maske wird 2× hochgerechnet)
TIME_LIMIT_S = 60.0                # Notbremse je Nachzeichnen (zwischen den Teilen geprüft)
THRESHOLD_RANGE = (1, 255)
SMOOTHING_RANGE = (0.0, 10.0)      # Sigma in Bildpixeln
TOLERANCE_RANGE = (0.0, 2.0)       # mm
MIN_AREA_RANGE = (0.0, 100.0)      # mm²
FLAT_MM = 0.02                     # Glätten: max. Sehnenabweichung der abgeflachten Kurven
FLAT_PX_RANGE = (0.05, 0.25)       # … in Bildpixeln begrenzt (Punktzahl / Pixelraster)
SMOOTH_MAX_RAW_POINTS = 150_000    # Glätten nur bis zu so vielen Randpunkten (~45 µs je Punkt)
SMOOTH_SKIPPED_NOTE = "Glätten übersprungen – Bild sehr detailreich (nur vereinfacht)"
# Trace modes: outline (filled parts with holes) or centre line (open strokes, line art)
MODE_OUTLINE = "outline"
MODE_CENTERLINE = "centerline"
MODES = (MODE_OUTLINE, MODE_CENTERLINE)


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


@dataclass(frozen=True)
class TraceSettings:
    threshold: int = 128            # 0..255, dunkler = Vordergrund
    invert: bool = False            # helle Bereiche nachzeichnen
    smoothing_px: float = 1.0       # Weichzeichnen vor dem Schwellwert (0 = aus)
    tolerance_mm: float = 0.05      # Vereinfachung (0 = jeder Randpixel)
    min_area_mm2: float = 0.2       # kleinere Flecken/Löcher fallen weg
    auto_threshold: bool = False    # Schwellwert automatisch (Otsu) statt ``threshold``
    mode: str = MODE_OUTLINE        # MODE_OUTLINE or MODE_CENTERLINE (see .centerline)
    smooth_curves: bool = True      # „Glätten“: Kurven statt Pixeltreppe, Ecken bleiben spitz

    def normalized(self) -> "TraceSettings":
        return TraceSettings(
            threshold=int(_clamp(int(self.threshold), *THRESHOLD_RANGE)),
            invert=bool(self.invert),
            smoothing_px=round(_clamp(float(self.smoothing_px), *SMOOTHING_RANGE), 2),
            tolerance_mm=round(_clamp(float(self.tolerance_mm), *TOLERANCE_RANGE), 3),
            min_area_mm2=round(_clamp(float(self.min_area_mm2), *MIN_AREA_RANGE), 3),
            auto_threshold=bool(self.auto_threshold),
            mode=self.mode if self.mode in MODES else MODE_OUTLINE,
            smooth_curves=bool(self.smooth_curves))

    @staticmethod
    def for_image(shape: Shape) -> "TraceSettings":
        """Startwerte aus den Bildeinstellungen (Schwellwert, Negativ)."""
        st = shape.image.settings if shape.image is not None else None
        if st is None:
            return TraceSettings()
        return TraceSettings(threshold=st.threshold, invert=st.negative).normalized()


Ring = list[tuple[float, float]]


@dataclass
class TracedPart:
    outer: Ring
    holes: list[Ring] = field(default_factory=list)


@dataclass
class TraceResult:
    parts: list[TracedPart]          # in Bildpixeln (x nach rechts, y nach unten)
    removed: int = 0                 # entfernte Flecken/Löcher
    threshold: int | None = None     # verwendeter Schwellwert (bei „Auto“: Otsu)
    # centre-line mode: open polylines (closed loops repeat the first point at the end)
    lines: list[Ring] = field(default_factory=list)
    note: str = ""                   # Hinweis für den Dialog (z. B. Glätten übersprungen)

    @property
    def point_count(self) -> int:
        return (sum(len(p.outer) + sum(len(h) for h in p.holes) for p in self.parts)
                + sum(len(line) for line in self.lines))

    @property
    def count(self) -> int:
        """Number of traced objects (parts or centre lines)."""
        return len(self.parts) + len(self.lines)


def decode_gray(png: bytes) -> np.ndarray:
    import cv2
    arr = cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_GRAYSCALE)
    if arr is None:
        raise ValueError("Bilddaten nicht lesbar")
    return arr


def _smoothed(gray: np.ndarray, st: TraceSettings) -> np.ndarray:
    import cv2
    g = np.ascontiguousarray(gray, dtype=np.uint8)
    if st.smoothing_px > 0:
        g = cv2.GaussianBlur(g, (0, 0), st.smoothing_px, borderType=cv2.BORDER_REPLICATE)
    return g


def otsu_threshold(gray: np.ndarray) -> int:
    """Automatischer Schwellwert (Otsu) im Sinne von ``threshold``: Pixel
    **dunkler** als der Wert sind Vordergrund (1…255)."""
    import cv2
    g = np.ascontiguousarray(gray, dtype=np.uint8)
    if g.size == 0:
        return 128
    t, _ = cv2.threshold(g, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)
    # OpenCV: Vordergrund (dunkel) ist ``g <= t`` → „dunkler als t + 1“
    return int(_clamp(int(t) + 1, *THRESHOLD_RANGE))


def effective_threshold(gray: np.ndarray, settings: TraceSettings) -> int:
    """Tatsächlich verwendeter Schwellwert (Otsu nach dem Glätten bei „Auto“)."""
    st = settings.normalized()
    return otsu_threshold(_smoothed(gray, st)) if st.auto_threshold else st.threshold


def _mask_and_threshold(gray: np.ndarray, st: TraceSettings) -> tuple[np.ndarray, int]:
    g = _smoothed(gray, st)
    thr = otsu_threshold(g) if st.auto_threshold else st.threshold
    mask = g >= thr if st.invert else g < thr
    return mask.astype(np.uint8) * 255, thr


def foreground_mask(gray: np.ndarray, settings: TraceSettings) -> np.ndarray:
    """uint8-Maske (255 = nachzeichnen) nach Glätten und Schwellwert."""
    return _mask_and_threshold(gray, settings.normalized())[0]


def _shoelace(pts: Ring) -> float:
    a = 0.0
    for (x0, y0), (x1, y1) in zip(pts, pts[1:] + pts[:1]):
        a += x0 * y1 - x1 * y0
    return abs(a) / 2


_MITRE = dict(join_style="mitre", mitre_limit=2.0)
# Ab so vielen Löchern je Teil wird nicht mehr das ganze Polygon auf einmal
# verbreitert/vereinfacht (GEOS wächst dort etwa quadratisch mit der Lochzahl),
# sondern jeder Ring einzeln – mit Konfliktprüfung über einen STRtree.
MANY_HOLES = 64


def _polys(geom) -> list:
    if geom.is_empty:
        return []
    if geom.geom_type == "Polygon":
        return [geom]
    return [g for g in getattr(geom, "geoms", []) if g.geom_type == "Polygon" and not g.is_empty]


def _pixel_polygons(outer: Ring, holes: list[Ring], grow: float):
    """Kontur durch Randpixel-Mitten → Polygon(e), um ``grow`` nach außen
    (Gehrung) auf die echte Pixelkante gelegt."""
    from shapely.geometry import Polygon

    holes = [h for h in holes if len(h) >= 3]
    if len(holes) > MANY_HOLES:
        return _pixel_polygons_many(outer, holes, grow)
    geom = Polygon(outer, holes).buffer(0)
    if geom.is_empty:
        return []
    return _polys(geom.buffer(grow, **_MITRE))


def _pixel_polygons_many(outer: Ring, holes: list[Ring], grow: float):
    """Wie :func:`_pixel_polygons`, aber Außenkontur und Löcher getrennt:
    Außenkontur verbreitern, Löcher um ``grow`` schrumpfen und einsetzen.

    Löcher, die sich berühren (Diagonalkontakt), werden vorher in kleinen
    Gruppen vereinigt; Löcher sauber innerhalb der Außenkontur werden direkt
    eingesetzt, nur die übrigen gehen durch die Differenz. So bleibt der
    Aufwand etwa linear statt quadratisch in der Lochzahl."""
    import shapely
    from shapely.geometry import MultiPolygon, Polygon

    shells = _polys(Polygon(outer).buffer(0).buffer(grow, **_MITRE))
    if not shells:
        return []
    hp = shapely.polygons([shapely.linearrings(h) for h in holes])
    hp = shapely.buffer(shapely.buffer(hp, 0), -grow, **_MITRE)
    hp = [g for h in hp for g in _polys(h)]
    if not hp:
        return shells
    hp = _merge_touching(hp)
    hp_arr = np.array(hp, dtype=object)
    plain = np.array([len(g.interiors) == 0 for g in hp])
    tree = shapely.STRtree(hp_arr)
    out = []
    for shell in shells:
        cand = tree.query(shell, predicate="intersects")
        if not len(cand):
            out.append(shell)
            continue
        if len(shell.interiors) == 0:
            shapely.prepare(shell)
            inside = shapely.contains_properly(shell, hp_arr[cand]) & plain[cand]
            direct, rest = cand[inside], cand[~inside]
        else:
            direct, rest = cand[:0], cand
        if len(direct):
            # disjunkte, einfache Löcher sauber innen: gültig ohne weitere Prüfung
            shell = Polygon(shell.exterior.coords, [hp[k].exterior.coords for k in direct])
        if len(rest):
            shell = shell.difference(MultiPolygon([hp[k] for k in rest]))
        out.extend(_polys(shell))
    return out


def _merge_touching(polys: list) -> list:
    """Sich berührende/überlappende Polygone gruppenweise vereinigen
    (Union-Find über STRtree-Paare) → paarweise disjunkte Polygone."""
    import shapely

    arr = np.array(polys, dtype=object)
    a, b = shapely.STRtree(arr).query(arr, predicate="intersects")
    keep = a < b
    a, b = a[keep], b[keep]
    if not len(a):
        return polys
    parent = list(range(len(polys)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i, j in zip(a.tolist(), b.tolist()):
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[max(ri, rj)] = min(ri, rj)
    groups: dict[int, list[int]] = {}
    for i in range(len(polys)):
        groups.setdefault(find(i), []).append(i)
    out = []
    for idx in groups.values():
        if len(idx) == 1:
            out.append(polys[idx[0]])
        else:
            out.extend(_polys(shapely.union_all(arr[idx])))
    return out


def _simplify(poly, eps: float):
    """Douglas-Peucker mit Topologieerhalt. Bei vielen Löchern jeden Ring einzeln
    vereinfachen und nur Ringe, die sich danach schneiden, unvereinfacht lassen
    (die topologieerhaltende Vereinfachung des ganzen Polygons wächst etwa
    quadratisch mit der Lochzahl)."""
    if len(poly.interiors) <= MANY_HOLES:
        return poly.simplify(eps, preserve_topology=True)
    import shapely
    from shapely.geometry import Polygon

    rings = [poly.exterior, *poly.interiors]
    raw_polys = shapely.polygons(np.array([shapely.linearrings(r.coords) for r in rings],
                                          dtype=object))
    simp = shapely.simplify(raw_polys, eps, preserve_topology=True)
    ok = np.array([g.geom_type == "Polygon" and not g.is_empty for g in simp])
    ok[ok] = shapely.is_valid(simp[ok])
    use_raw = ~ok
    final = np.where(ok, simp, raw_polys)
    for _ in range(3):
        # Außenkontur vorbereitet gegen alle Löcher, Löcher untereinander per STRtree
        # (die riesige Außenkontur nie als Baumelement – sonst O(Löcher × Punkte))
        lines = shapely.boundary(final)
        shell_line = lines[0]
        shapely.prepare(shell_line)
        bad_hole = shapely.intersects(shell_line, lines[1:])
        bad = np.zeros(len(final), bool)
        bad[1:] = bad_hole            # erst das Loch zurücksetzen …
        bad[0] = (bad_hole & use_raw[1:]).any()   # … dann erst die Außenkontur
        tree = shapely.STRtree(lines[1:])
        a, b = tree.query(lines[1:], predicate="intersects")
        bad[1 + a[a != b]] = True
        changed = np.nonzero(bad & ~use_raw)[0]
        if not len(changed):
            break
        use_raw[changed] = True
        final[changed] = raw_polys[changed]
    # Nur noch unvereinfachte Ringe berühren sich (wie im gültigen Original);
    # liegt jedes Loch in der Außenkontur, ist das Ergebnis gültig
    shell = final[0]
    shapely.prepare(shell)
    if len(changed) or not shapely.covers(shell, final[1:]).all():
        return poly
    return Polygon(shell.exterior.coords, [g.exterior.coords for g in final[1:]])


def _flat_px(mx: float, my: float) -> float:
    return _clamp(FLAT_MM / min(mx, my), *FLAT_PX_RANGE)


def _smooth_polygon(poly, eps_px: float, flat_px: float):
    """Glätten: jeden Ring kurvengeglättet (Ecken spitz). ``None``, wenn das
    Ergebnis ungültig wäre (Ringe würden sich schneiden) – dann bleibt es beim
    Vereinfachen der Pixelkontur."""
    from shapely.geometry import Polygon

    from .curvefit import FIT_PX, smooth_polyline
    fit = max(FIT_PX, eps_px)

    def ring(coords) -> Ring:
        pts = [(float(x), float(y)) for x, y in coords[:-1]]
        return smooth_polyline(pts, True, fit, flat_px, edge_midpoints=True)

    ext = ring(poly.exterior.coords)
    if len(ext) < 3:
        return None
    holes = [h for h in (ring(i.coords) for i in poly.interiors) if len(h) >= 3]
    out = Polygon(ext, holes)
    if out.is_empty or not out.is_valid:
        return None
    return out


def trace_gray(gray: np.ndarray, settings: TraceSettings,
               mm_per_px: tuple[float, float] = (1.0, 1.0),
               time_limit_s: float | None = TIME_LIMIT_S) -> TraceResult:
    """Graustufen-Array → Teile in Bildpixel-Koordinaten (Pixelmitte = i + 0,5).

    ``mm_per_px`` dient nur zum Umrechnen von Toleranz und Mindestfläche.
    Die Laufzeit ist begrenzt: zu große oder zu detailreiche Bilder werden vor
    der Geometriearbeit abgelehnt, und nach ``time_limit_s`` Sekunden bricht
    das Nachzeichnen mit ``ValueError`` ab (Vorschau: kurze Grenze).
    """
    import time

    import cv2
    st = settings.normalized()
    if gray.ndim != 2 or gray.size == 0:
        raise ValueError("Bild ist leer")
    if gray.size > MAX_PIXELS:
        raise ValueError(f"Bild zu groß ({gray.shape[1]}×{gray.shape[0]} Pixel) – vorher "
                         f"auf höchstens {MAX_PIXELS // 1_000_000} Megapixel verkleinern")
    deadline = None if time_limit_s is None else time.monotonic() + float(time_limit_s)
    mx, my = (abs(float(v)) or 1.0 for v in mm_per_px)
    # 2× hochgerechnet (nächster Nachbar): auch 1 Pixel breite Linien haben
    # dann eine Fläche zwischen den Randpixel-Mitten; ¼ Pixel nach außen ergibt
    # die echte Pixelkante. Rand mit Hintergrund auffüllen (geschlossene Konturen).
    mask, thr = _mask_and_threshold(gray, st)
    if st.mode == MODE_CENTERLINE:
        return _trace_centerline(mask, thr, st, mx, my, deadline)
    mask = np.repeat(np.repeat(mask, 2, axis=0), 2, axis=1)
    mask = cv2.copyMakeBorder(mask, 1, 1, 1, 1, cv2.BORDER_CONSTANT, value=0)
    found = cv2.findContours(mask, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
    contours, hierarchy = found[-2], found[-1]
    if hierarchy is None or not len(contours):
        return TraceResult([], threshold=thr)
    if len(contours) > 8 * MAX_PARTS:
        raise ValueError(f"Zu viele Konturen ({len(contours)}) – Schwellwert, Glättung "
                         f"oder Mindestfläche anpassen")
    raw_points = sum(len(c) for c in contours)
    if raw_points > MAX_RAW_POINTS:
        raise ValueError(f"Bild zu detailreich ({raw_points} Randpunkte) – Glättung, "
                         f"Schwellwert oder Mindestfläche erhöhen")
    hier = hierarchy[0]
    min_area = max(st.min_area_mm2 / (mx * my), 0.25)   # in Bildpixeln²
    eps_px = st.tolerance_mm / min(mx, my)
    flat_px = _flat_px(mx, my)
    # Glätten kostet ein Vielfaches des Vereinfachens → bei sehr detailreichen
    # Bildern (Rauschen, Fotos) nur vereinfachen und im Dialog darauf hinweisen
    smooth_curves = st.smooth_curves and raw_points <= SMOOTH_MAX_RAW_POINTS
    note = SMOOTH_SKIPPED_NOTE if st.smooth_curves and not smooth_curves else ""
    removed = 0
    points = 0
    parts: list[TracedPart] = []

    def raw(i: int) -> list[tuple[float, float]]:
        # Subpixel-Mitte (2k+1 inkl. Pad) → Bildpixel: (x - 1 + 0,5) / 2
        return list(map(tuple, ((contours[i][:, 0, :] - 0.5) / 2).tolist()))

    def too_small(i: int) -> bool:
        # obere Schranke der Fläche nach dem Verbreitern (in Subpixeln, ¼ = 1 Bildpixel²)
        c = contours[i]
        upper = abs(cv2.contourArea(c)) + 0.5 * cv2.arcLength(c, True) + 1.0
        return upper / 4 < min_area

    # Vorab-Budget (billig, vor jeder shapely-Arbeit): zu viele Teile → sofort ablehnen
    small = np.fromiter((too_small(i) for i in range(len(contours))), bool, len(contours))
    n_top = int(np.count_nonzero((hier[:, 3] < 0) & ~small))
    if n_top > MAX_PARTS:
        raise ValueError(f"Zu viele Konturen ({n_top}) – Schwellwert, Glättung "
                         f"oder Mindestfläche anpassen")

    for i, (_nxt, _prev, child, parent) in enumerate(hier):
        if parent >= 0:
            continue
        if deadline is not None and time.monotonic() > deadline:
            raise ValueError("Nachzeichnen dauert zu lange – Glättung, Schwellwert oder "
                             "Mindestfläche erhöhen")
        if small[i]:
            removed += 1
            continue
        holes = []
        j = child
        while j >= 0:
            if small[j]:
                removed += 1
            else:
                holes.append(raw(j))
            j = hier[j][0]
        outer = raw(i)
        if len(outer) < 3:
            outer = outer + outer[:1] * (3 - len(outer))
        for poly in _pixel_polygons(outer, holes, 0.25):
            if poly.area < min_area:
                removed += 1
                continue
            smooth = _smooth_polygon(poly, eps_px, flat_px) if smooth_curves else None
            if smooth is not None:
                poly = smooth
            elif eps_px > 0:
                poly = _simplify(poly, eps_px)
            if poly.is_empty or poly.geom_type != "Polygon":
                removed += 1
                continue
            ext = [(float(x), float(y)) for x, y in poly.exterior.coords[:-1]]
            if len(ext) < 3:
                removed += 1
                continue
            hs = []
            for interior in poly.interiors:
                ring_pts = [(float(x), float(y)) for x, y in interior.coords[:-1]]
                if len(ring_pts) < 3 or _shoelace(ring_pts) < min_area:
                    removed += 1
                    continue
                hs.append(ring_pts)
            points += len(ext) + sum(len(h) for h in hs)
            if points > MAX_POINTS:
                raise ValueError(f"Zu viele Punkte (> {MAX_POINTS}) – Toleranz oder "
                                 f"Mindestfläche erhöhen")
            parts.append(TracedPart(ext, hs))
            if len(parts) > MAX_PARTS:
                raise ValueError(f"Zu viele Konturen (> {MAX_PARTS}) – Schwellwert, Glättung "
                                 f"oder Mindestfläche anpassen")
    return TraceResult(parts, removed, thr, note=note)


def _trace_centerline(mask: np.ndarray, thr: int, st: TraceSettings, mx: float, my: float,
                      deadline: float | None) -> TraceResult:
    from .centerline import trace_centerline
    lines, removed = trace_centerline(mask, st.tolerance_mm / min(mx, my),
                                      st.min_area_mm2 / (mx * my), deadline,
                                      smooth=st.smooth_curves, flat_px=_flat_px(mx, my))
    points = sum(len(line) for line in lines)
    if points > MAX_POINTS:
        raise ValueError(f"Zu viele Punkte (> {MAX_POINTS}) – Toleranz oder "
                         f"Mindestfläche erhöhen")
    if len(lines) > MAX_PARTS:
        raise ValueError(f"Zu viele Linien (> {MAX_PARTS}) – Schwellwert, Glättung "
                         f"oder Mindestfläche anpassen")
    return TraceResult([], removed, thr, lines)


def image_mm_per_px(shape: Shape) -> tuple[float, float]:
    img = shape.image
    return (abs(shape.geom.w) / img.px_width, abs(shape.geom.h) / img.px_height)


def trace_image(shape: Shape, settings: TraceSettings) -> TraceResult:
    if shape.kind != "image" or shape.image is None:
        raise ValueError("Kein Bildobjekt")
    return trace_gray(decode_gray(shape.image.png), settings, image_mm_per_px(shape))


def to_canvas(shape: Shape, ring: Ring) -> Ring:
    """Bildpixel → Canvas-mm (Bildbox, Drehung um die Boxmitte)."""
    g, img = shape.geom, shape.image
    cx, cy = g.center()
    sx, sy = g.w / img.px_width, g.h / img.px_height
    return [rotate_point(g.x + x * sx, g.y + y * sy, cx, cy, g.rot) for x, y in ring]


def traced_shapes(shape: Shape, result: TraceResult, layer_id: str) -> list[Shape]:
    """Teile → ``polygon``-Objekte (Löcher als ``rings``), mehrere gruppiert."""
    out: list[Shape] = []
    for part in result.parts:
        pts = to_canvas(shape, part.outer)
        rings = []
        for hole in part.holes:
            rings.append(len(pts))
            pts += to_canvas(shape, hole)
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        if max(xs) - min(xs) < 1e-6 or max(ys) - min(ys) < 1e-6:
            continue
        out.append(Shape.from_points("polygon", pts, layer_id, rings=rings))
    for line in result.lines:
        # centre lines stay open ``path`` objects (a closed loop repeats its first point),
        # so a fill layer does not fill them
        pts = to_canvas(shape, line)
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        if len(pts) < 2 or (max(xs) - min(xs) < 1e-6 and max(ys) - min(ys) < 1e-6):
            continue
        out.append(Shape.from_points("path", pts, layer_id))
    if len(out) > 1:
        gid = new_id()
        out = [replace(s, groups=(gid,)) for s in out]
    return out


def trace_to_shapes(shape: Shape, settings: TraceSettings, layer_id: str) -> list[Shape]:
    return traced_shapes(shape, trace_image(shape, settings), layer_id)


__all__ = ["TraceSettings", "TraceResult", "TracedPart", "trace_gray", "trace_image",
           "traced_shapes", "trace_to_shapes", "decode_gray", "foreground_mask",
           "image_mm_per_px", "to_canvas", "otsu_threshold", "effective_threshold",
           "MODE_OUTLINE", "MODE_CENTERLINE", "MODES", "FLAT_MM", "SMOOTH_MAX_RAW_POINTS"]
