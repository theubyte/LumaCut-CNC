"""Export der Arbeitsfläche (SVG/PNG) und Übergabe an die Jobplanung.

:func:`job_layers` ist die Schnittstelle für den Job-/Maschinenteil: pro
sichtbarer Ebene die Laserparameter und alle Konturen als Polylinien in
**Maschinen**-mm (Safezone-Versatz bereits eingerechnet). Mit „Nach Gruppen“
(``Document.cut_order.order_by == "group"``, LightBurn *Order by Group*) kommt
stattdessen je oberster Gruppe ein Satz Ebenen (:func:`cut_units`) – jede Gruppe
wird mit allen ihren Ebenen fertig, bevor die nächste beginnt. „Nach Priorität“
(``order_by == "priority"``, LightBurn *Order by Priority*) macht dasselbe je
Objekt-Priorität (``Shape.priority``, kleinste zuerst, :func:`priority_units`).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, replace

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QBrush, QColor, QImage, QPainter, QPen
from PySide6.QtSvg import QSvgGenerator

from .hatch import LINE_FILL_MODES, fill_segments, pass_angles
from .material import layer_pass_plan
from .model import CUT_LAYER_FIELDS, FILLABLE_KINDS, Document, Layer, Shape
from .shape_paths import shape_path, shape_polygons
from .workarea import WORK_HEIGHT_MM, WORK_WIDTH_MM, Rect, machine_to_screen, to_machine


@dataclass
class JobLayer:
    layer_id: str
    name: str
    power_percent: float
    speed_mm_min: float
    passes: int
    polylines: list[list[tuple[float, float]]]  # Maschinen-mm
    z_step_mm: float = 0.0  # Fokus-Absenkung je Durchgang
    z_offset_mm: float = 0.0  # relativer Fokus-Versatz der ganzen Ebene (negativ = näher)
    # Tiefe je Durchgang aus der Material-Planung (material.layer_pass_plan),
    # leer ohne Planung. Nur für den optionalen G-Code-Hook (gcode.pass_hook).
    pass_depths_mm: tuple[float, ...] = ()
    # Schnitt-Optionen der Ebene (Layer.kerf_mm …, siehe lumacut_job.cutpath).
    # Werden erst vom Planer (lumacut_job.planner.optimize_layers) angewendet.
    kerf_mm: float = 0.0
    tab_count: int = 0
    tab_width_mm: float = 1.0
    tab_spacing_mm: float = 0.0
    lead_in_mm: float = 0.0
    lead_in_arc: bool = False
    lead_out_mm: float = 0.0
    overcut_mm: float = 0.0
    perf_cut_mm: float = 0.0
    perf_skip_mm: float = 1.0
    overlap_tol_mm: float = 0.0   # > 0: überlappende Linien nur einmal (lumacut_job.overlap)
    tab_skip_inner: bool = False  # keine Stege an innen liegenden Konturen
    tab_max: int = 0              # Abstands-Modus: höchstens so viele Stege (0 = unbegrenzt)
    tab_cut_power: float = 0.0    # Steg-Leistung % (gepulst: "tab_pulse" / "tab_off")
    # Manuelle Stege der Objekte dieser Ebene (Shape.tabs, lumacut_canvas.tabs) als
    # Punkte in Maschinen-mm; der Planer setzt sie auf die nächste Kontur (statt der
    # automatischen Stege dieser Kontur). Leer = nur automatische Stege.
    tab_points: tuple[tuple[float, float], ...] = ()
    # Manuelle Startpunkte der Objekte dieser Ebene (Shape.start, lumacut_canvas.startpoint)
    # in Maschinen-mm: die Kontur, auf der einer liegt, beginnt dort (der Export dreht sie
    # schon, der Planer nach dem Kerf-Versatz erneut) und der Planer verlegt ihren Start
    # nicht. Leer = Startpunkte wie bisher.
    start_points: tuple[tuple[float, float], ...] = ()
    # Art je Polylinie nach der Planung ("cut", "lead_in", "lead_out", "tab" =
    # Schnittstück nach einer Steg-Lücke, "perf" = nach einer
    # Perforations-Lücke, "tab_pulse" / "tab_off" = Puls mit Laser an / Stück
    # mit Laser aus innerhalb eines Stegs mit Steg-Leistung); leer = alles "cut".
    poly_kinds: tuple[str, ...] = ()
    # Vektor-Füllung: je Füllgruppe (Objekt, Gruppe oder ganze Ebene, siehe
    # Layer.fill_grouping) ein Block Schraffurstrecken ((x0, y0), (x1, y1)) in
    # Maschinen-mm, bereits in Fahr-Reihenfolge.
    # Der G-Code lasert je Durchgang zuerst die Füllungen, dann die Konturen.
    fills: list[list[tuple[tuple[float, float], tuple[float, float]]]] = field(default_factory=list)
    # True (Offset-Füllung): Blöcke nie rückwärts fahren – die Ring-Reihenfolge
    # (außen → innen bzw. innen → außen) ist eine Einstellung der Ebene.
    fill_fixed_order: bool = False
    # Überlauf je Ende einer Schraffurstrecke (Laser aus, Layer.fill_overscan_mm);
    # 0 bei Offset-Füllung. Erst der G-Code (gcode.overscan_segment) verlängert.
    fill_overscan_mm: float = 0.0
    # Scan-Versatz der Füllstrecken (mm, lumacut_job.scan_offset): erst der G-Code
    # verschiebt jede Strecke um die Hälfte entgegen ihrer Fahrtrichtung; 0 = aus.
    fill_scan_offset_mm: float = 0.0
    # Freie Startecke (Schraffur/Kreuzschraffur): ein Block darf an jeder seiner
    # vier Ecken beginnen – Zeilen rückwärts und/oder jede Zeile umgedreht
    # (hatch.fill_block_entries); Planer und G-Code wählen den nächsten Einstieg.
    fill_free_corner: bool = False
    # Winkel-Schritt je Durchgang (Layer.fill_angle_increment, LightBurn „Angle
    # Increment“): je Durchgang eigene Schraffurblöcke (``pass_fills[p]``, Eintrag 0 =
    # ``fills``) und ihr Winkel (``pass_fill_angles[p]``). Leer = jeder Durchgang
    # lasert ``fills`` (ohne Schritt, ein Durchgang oder Offset-Füllung).
    pass_fills: list = field(default_factory=list)
    pass_fill_angles: tuple[float, ...] = ()
    # Schnittreihenfolge des Projekts (model.CutOrder, „Optimierung…“); None =
    # Planer-Standard. Jede Ebene trägt sie, damit alle Aufrufer des Planers
    # (Senden, Vorschau, Schätzung, Rahmen, Park-Ecke) gleich planen.
    cut_order: object = None
    # „Nach Gruppen“ (CutOrder.order_by == "group"): Nummer der Gruppe im Auftrag als
    # "i OF n" – der G-Code schreibt davor einmal ``; GROUP i OF n``. "" = nach Ebenen.
    # „Nach Priorität“: ``unit_kind`` "PRIORITY", ``unit`` "p (i OF n)" →
    # ``; PRIORITY p (i OF n)``.
    unit: str = ""
    unit_kind: str = "GROUP"


def shape_fill_segments(shape: Shape, layer: Layer):
    """Schraffur eines Objekts nach der Ebenen-Füllung (Arbeitsflächen-mm).

    Gerade-Ungerade-Regel über alle Teilpfade des Objekts (Löcher in Text,
    Rahmen). Leer, wenn die Ebene nicht füllt oder das Objekt offen ist.
    Füllt immer nur dieses Objekt (``fill_grouping`` siehe :func:`layer_fill_blocks`).
    """
    if layer.fill_mode == "none" or shape.kind not in FILLABLE_KINDS:
        return []
    polys = shape_polygons(shape)
    return fill_segments(polys, layer.fill_mode, layer.line_interval_mm, layer.hatch_angle,
                         layer.hatch_bidirectional, getattr(layer, "offset_inside_out", False))


def _fill_shape_groups(doc: Document, layer: Layer) -> list[list[Shape]]:
    """Objekte der Ebene, die jeweils gemeinsam gefüllt werden (Objekt-Reihenfolge)."""
    shapes = [s for s in doc.shapes_in_layer(layer.id) if s.kind in FILLABLE_KINDS]
    grouping = getattr(layer, "fill_grouping", "individual")
    mode = _unit_mode(doc)
    if grouping == "together":
        if not shapes:
            return []
        if mode == "layer":
            return [shapes]
        # Nach Gruppen / Priorität: „alle zusammen“ je Einheit (oberste Gruppe bzw.
        # Priorität; ohne Gruppe: zusammen), weil jede Einheit für sich gelasert wird.
        parts: dict[object, list[Shape]] = {}
        for s in shapes:
            parts.setdefault(_unit_key(mode, s), []).append(s)
        return list(parts.values())
    if grouping != "groups":
        return [[s] for s in shapes]
    out: list[list[Shape]] = []
    by_group: dict[object, list[Shape]] = {}
    for s in shapes:
        top = s.groups[0] if s.groups else None
        if top is None:
            out.append([s])
            continue
        # Nach Priorität: eine Gruppe mit verschiedenen Prioritäten füllt je Priorität.
        key = (top, s.priority) if mode == "priority" else top
        if key in by_group:
            by_group[key].append(s)
        else:
            by_group[key] = [s]
            out.append(by_group[key])
    return out


def layer_fill_blocks(doc: Document, layer: Layer,
                      angle: float | None = None) -> list[tuple[list[str], list]]:
    """Füllung einer Ebene als Blöcke ``(objekt_ids, strecken)`` (Arbeitsflächen-mm).

    Je nach ``layer.fill_grouping`` ein Block je Objekt, je oberster Gruppe
    (ungruppierte Objekte einzeln) oder einer für alle Objekte der Ebene.
    Gemeinsam gefüllte Objekte bilden eine Fläche nach der
    Gerade-Ungerade-Regel: überlappende Teile und ineinander liegende Objekte
    bleiben frei (wie LightBurn). Leere Blöcke entfallen. ``angle`` ersetzt den
    Schraffurwinkel der Ebene (Winkel-Schritt je Durchgang, :func:`layer_pass_fill_blocks`).
    """
    if layer.fill_mode == "none":
        return []
    hatch_angle = layer.hatch_angle if angle is None else angle
    blocks = []
    for group in _fill_shape_groups(doc, layer):
        polys = [poly for s in group for poly in shape_polygons(s)]
        segs = fill_segments(polys, layer.fill_mode, layer.line_interval_mm, hatch_angle,
                             layer.hatch_bidirectional,
                             getattr(layer, "offset_inside_out", False))
        if segs:
            blocks.append(([s.id for s in group], segs))
    return blocks


def layer_fill_pass_angles(layer: Layer) -> tuple[float, ...]:
    """Schraffurwinkel je Durchgang, wenn der Winkel-Schritt wirkt, sonst ``()``.

    Wirkt nur bei Schraffur / Kreuzschraffur, mehr als einem Durchgang und einem
    Schritt, der wirklich einen anderen Winkel ergibt (180° = dieselben Linien).
    """
    inc = float(getattr(layer, "fill_angle_increment", 0.0) or 0.0)
    if layer.fill_mode not in LINE_FILL_MODES or int(layer.passes) < 2 or not inc:
        return ()
    angles = pass_angles(layer.hatch_angle, inc, layer.passes)
    return tuple(angles) if len(set(angles)) > 1 else ()


def layer_pass_fill_blocks(doc: Document, layer: Layer, first=None):
    """Füllblöcke je Durchgang (LightBurn „Angle Increment“) oder ``None`` ohne Schritt.

    Liste mit einem Eintrag je Durchgang (wie :func:`layer_fill_blocks`, unter dem
    Winkel des Durchgangs); gleiche Winkel teilen sich dieselbe Liste. ``first`` =
    bereits berechnete Blöcke unter dem Ebenenwinkel (Durchgang 1).
    """
    angles = layer_fill_pass_angles(layer)
    if not angles:
        return None
    cache: dict[float, list] = {}
    if first is not None:
        cache[angles[0]] = first
    out = []
    for a in angles:
        if a not in cache:
            cache[a] = layer_fill_blocks(doc, layer, a)
        out.append(cache[a])
    return out


def _unit_mode(doc: Document) -> str:
    """"layer" (Standard), "group" oder "priority" (``CutOrder.order_by``)."""
    mode = getattr(getattr(doc, "cut_order", None), "order_by", "layer")
    return mode if mode in ("group", "priority") else "layer"


def _unit_key(mode: str, s: Shape):
    """Einheit eines Objekts: oberste Gruppe ("" = ohne) bzw. Priorität."""
    if mode == "priority":
        return s.priority
    return s.groups[0] if s.groups else ""


#: Kopfposition, ab der der Planer plant (``lumacut_job.planner.optimize_layers``).
PLAN_START_MACHINE = (30.0, 30.0)


def _unit_box(shapes: list[Shape]) -> Rect:
    box = shapes[0].bounds()
    for s in shapes[1:]:
        box = box.united(s.bounds())
    return box


def _box_contains(outer: Rect, inner: Rect, eps: float = 1e-6) -> bool:
    """``inner`` liegt ganz in ``outer`` und ist kleiner (gleiche Boxen: nein)."""
    return (outer.x <= inner.x + eps and outer.y <= inner.y + eps
            and inner.right <= outer.right + eps and inner.bottom <= outer.bottom + eps
            and outer.w * outer.h > inner.w * inner.h + eps)


def _lead(box: Rect, direction: str) -> tuple[float, float]:
    """(Vorderkante, Ausdehnung) einer Box in Schnittrichtung (Bildschirm-Sicht)."""
    if direction == "top_bottom":
        return box.y, box.h
    if direction == "bottom_top":
        return -box.bottom, box.h
    if direction == "left_right":
        return box.x, box.w
    return -box.right, box.w


def _box_distance(box: Rect, pt: tuple[float, float]) -> float:
    dx = max(box.x - pt[0], 0.0, pt[0] - box.right)
    dy = max(box.y - pt[1], 0.0, pt[1] - box.bottom)
    return dx * dx + dy * dy


def _order_groups(units: list[tuple[str, list[Shape]]], order) -> list[tuple[str, list[Shape]]]:
    """Reihenfolge der Gruppen nach den Optimierungseinstellungen.

    Optimierung aus: Reihenfolge der Objekte (erstes Objekt jeder Gruppe).
    Sonst „Innere Formen zuerst“: eine Gruppe, deren Box ganz in der Box einer
    anderen liegt, kommt vor ihr; „In Richtung schneiden“: Zeile für Zeile in
    Schnittrichtung (Zeilenhöhe = halbe Ausdehnung der vordersten Gruppe), in der
    Zeile die nächste; sonst „Leerfahrten verkürzen“: die zur vorigen Gruppe
    nächstgelegene (ab der Startposition des Planers).
    """
    if len(units) < 2 or order is None or not order.enabled:
        return list(units)
    boxes = [_unit_box(shapes) for _gid, shapes in units]
    pos = machine_to_screen(*PLAN_START_MACHINE)
    remaining = list(range(len(units)))
    out: list[int] = []
    while remaining:
        cands = remaining
        if order.inside_first:
            cands = [i for i in remaining
                     if not any(j != i and _box_contains(boxes[i], boxes[j]) for j in remaining)]
            cands = cands or remaining
        if order.direction:
            leads = {i: _lead(boxes[i], order.direction) for i in cands}
            front = min(cands, key=lambda i: (leads[i][0], i))
            limit = leads[front][0] + leads[front][1] / 2 + 1e-6
            cands = [i for i in cands if leads[i][0] <= limit]
        if order.reduce_travel or order.direction:
            pick = min(cands, key=lambda i: (_box_distance(boxes[i], pos), i))
        else:
            pick = min(cands)
        b = boxes[pick]
        pos = (b.x + b.w / 2, b.y + b.h / 2)
        out.append(pick)
        remaining.remove(pick)
    return [units[i] for i in out]


def cut_units(doc: Document) -> list[tuple[str, list[Shape]]]:
    """Gruppen für „Nach Gruppen“: ``[(oberste_gruppen_id, objekte)]`` in Schnittfolge.

    Zählt nur Vektor-Objekte sichtbarer Ebenen (Bilder werden ohnehin vorab
    graviert). Gruppen in der Reihenfolge von :func:`_order_groups`; alle Objekte
    ohne Gruppe bilden zusammen die letzte Einheit (id ""), z. B. ein Rahmen oder
    eine Platte um gruppierte Teile.
    """
    visible = {l.id for l in doc.layers if l.visible}
    by_id: dict[str, list[Shape]] = {}
    for s in doc.shapes:
        if s.kind == "image" or s.layer_id not in visible:
            continue
        by_id.setdefault(s.groups[0] if s.groups else "", []).append(s)
    loose = by_id.pop("", None)
    units = _order_groups(list(by_id.items()), getattr(doc, "cut_order", None))
    if loose:
        units.append(("", loose))
    return units


def priority_units(doc: Document) -> list[tuple[int, list[Shape]]]:
    """Einheiten für „Nach Priorität“: ``[(priorität, objekte)]``, kleinste zuerst.

    Wie :func:`cut_units` nur Vektor-Objekte sichtbarer Ebenen (Bilder werden
    ohnehin vorab graviert); innerhalb einer Priorität die Objekt-Reihenfolge –
    die Reihenfolge der Konturen plant der Planer je Ebene wie immer.
    """
    visible = {l.id for l in doc.layers if l.visible}
    by_prio: dict[int, list[Shape]] = {}
    for s in doc.shapes:
        if s.kind == "image" or s.layer_id not in visible:
            continue
        by_prio.setdefault(int(s.priority), []).append(s)
    return sorted(by_prio.items())


def _machine_fills(fill_blocks, ids: set[str] | None) -> list:
    return [[(to_machine(*a), to_machine(*b)) for a, b in segs]
            for bids, segs in fill_blocks if ids is None or (bids and bids[0] in ids)]


def _job_layer(doc: Document, layer: Layer, fill_blocks, ids: set[str] | None = None,
               unit: str = "", pass_blocks=None) -> JobLayer | None:
    """Eine Ebene als :class:`JobLayer` (nur Objekte aus ``ids``, None = alle).

    ``pass_blocks``: Füllblöcke je Durchgang (:func:`layer_pass_fill_blocks`) oder None.
    """
    polys: list[list[tuple[float, float]]] = []
    tab_points: list[tuple[float, float]] = []
    start_points: list[tuple[float, float]] = []
    fills = _machine_fills(fill_blocks, ids)
    pass_fills: list = []
    if pass_blocks:
        converted: dict[int, list] = {id(fill_blocks): fills}
        for blocks in pass_blocks:
            if id(blocks) not in converted:
                converted[id(blocks)] = _machine_fills(blocks, ids)
            pass_fills.append(converted[id(blocks)])
        if not any(pass_fills):
            pass_fills = []
    for s in doc.shapes_in_layer(layer.id):
        if ids is not None and s.id not in ids:
            continue
        if s.kind == "image":
            continue  # Bilder werden gerastert (lumacut_job.images), nicht umfahren
        if s.kind in FILLABLE_KINDS and layer.fill_mode != "none" and not layer.hatch_outline:
            continue  # nur Füllung, keine Kontur
        if s.kind == "line":
            path = shape_path(s)
            a, b = path.elementAt(0), path.elementAt(1)
            polys.append([to_machine(a.x, a.y), to_machine(b.x, b.y)])
            continue
        shape_polys = shape_polygons(s)
        start = s.start_point() if s.start else None
        if start is not None:
            from .startpoint import START_SNAP_MM, apply_start_points
            shape_polys, placed, _dropped = apply_start_points(shape_polys, [start], START_SNAP_MM)
            start_points.extend(to_machine(x, y) for x, y in placed)
        for poly in shape_polys:
            polys.append([to_machine(x, y) for x, y in poly])
        if s.tabs:
            tab_points.extend(to_machine(x, y) for x, y in s.tab_points())
    if not (polys or fills or pass_fills):
        return None
    plan = layer_pass_plan(layer)
    return JobLayer(layer.id, layer.name, layer.power, layer.speed,
                    layer.passes, polys, layer.z_step,
                    z_offset_mm=float(getattr(layer, "z_offset", 0.0) or 0.0),
                    pass_depths_mm=plan.pass_depths if plan else (),
                    **{k: getattr(layer, k) for k in CUT_LAYER_FIELDS}, fills=fills,
                    fill_fixed_order=layer.fill_mode == "offset",
                    fill_free_corner=layer.fill_mode in LINE_FILL_MODES,
                    fill_overscan_mm=(getattr(layer, "fill_overscan_mm", 0.0)
                                      if layer.fill_mode in LINE_FILL_MODES
                                      else 0.0),
                    cut_order=getattr(doc, "cut_order", None),
                    tab_points=tuple(tab_points), start_points=tuple(start_points), unit=unit, pass_fills=pass_fills,
                    pass_fill_angles=layer_fill_pass_angles(layer) if pass_fills else ())


def job_layers(doc: Document) -> list[JobLayer]:
    """Ebenen in Ausführungsreihenfolge (unterste Ebene zuerst).

    Ellipsen, Kurven und Text werden in Polylinien zerlegt
    (:func:`shape_paths.shape_polygons`, Sehnenfehler ≤ 0,02 mm).
    Ausgeblendete Ebenen werden nicht gelasert.

    „Nach Gruppen“ (LightBurn *Order by Group*): für jede Einheit aus
    :func:`cut_units` die Ebenen (unterste zuerst) mit nur ihren Objekten –
    eine Ebene kann so mehrmals vorkommen, jeweils mit ``unit`` = "i OF n".
    „Nach Priorität“ (LightBurn *Order by Priority*) ebenso je Einheit aus
    :func:`priority_units` mit ``unit_kind`` "PRIORITY" und ``unit`` = "p (i OF n)".
    Gibt es nur eine Einheit (keine Gruppen / eine einzige Priorität), ist das
    Ergebnis dasselbe wie nach Ebenen.
    """
    layers = [l for l in reversed(doc.layers) if l.visible]
    blocks = {l.id: layer_fill_blocks(doc, l) for l in layers}
    passes = {l.id: layer_pass_fill_blocks(doc, l, blocks[l.id]) for l in layers}
    mode = _unit_mode(doc)
    if mode != "layer":
        units = (list(priority_units(doc)) if mode == "priority"
                 else [(None, shapes) for _gid, shapes in cut_units(doc)])
        if len(units) > 1:
            parts = []
            for key, shapes in units:
                ids = {s.id for s in shapes}
                part = [jl for l in layers
                        if (jl := _job_layer(doc, l, blocks[l.id], ids,
                                             pass_blocks=passes[l.id])) is not None]
                if part:
                    parts.append((key, part))
            if len(parts) > 1:
                n = len(parts)
                if mode == "priority":
                    return [replace(jl, unit=f"{key} ({i} OF {n})", unit_kind="PRIORITY")
                            for i, (key, part) in enumerate(parts, 1) for jl in part]
                return [replace(jl, unit=f"{i} OF {n}")
                        for i, (_key, part) in enumerate(parts, 1) for jl in part]
            return [jl for _key, part in parts for jl in part]
    return [jl for l in layers
            if (jl := _job_layer(doc, l, blocks[l.id], pass_blocks=passes[l.id])) is not None]


def _paint(doc: Document, p: QPainter, line_width_mm: float, show_fill: bool = False) -> None:
    p.setRenderHint(QPainter.Antialiasing)
    for layer in reversed(doc.layers):
        if not layer.visible:
            continue
        color = QColor(layer.color)
        filled: set[str] = set()
        if show_fill:
            pen = QPen(color, line_width_mm)
            pen.setCosmetic(False)
            p.setPen(pen)
            for ids, segs in layer_fill_blocks(doc, layer):
                for a, b in segs:
                    p.drawLine(QPointF(*a), QPointF(*b))
                filled.update(ids)
        for s in doc.shapes_in_layer(layer.id):
            pen = QPen(color, line_width_mm)
            pen.setCosmetic(False)
            p.setPen(pen)
            if s.kind == "image" and s.image is not None:
                _paint_image(p, s)
                continue
            if s.id in filled and not layer.hatch_outline:
                continue
            p.setBrush(QBrush(color) if s.kind == "text" else Qt.NoBrush)
            p.drawPath(shape_path(s))


def _paint_image(p: QPainter, s) -> None:
    from .image_cache import qimage_for
    from .shape_paths import geometry_transform
    img = qimage_for(s.image.png)
    if img.isNull():
        return
    b = s.geom.local_bounds()
    p.save()
    if s.geom.rot:
        p.setTransform(geometry_transform(s.geom), True)
    p.drawImage(QRectF(b.x, b.y, b.w, b.h), img)
    p.restore()


def export_svg(doc: Document, path: str | os.PathLike[str], show_fill: bool = False) -> None:
    """SVG in mm-Maßstab (viewBox = 0 0 360 340); ``show_fill`` zeichnet die Schraffur."""
    gen = QSvgGenerator()
    gen.setFileName(os.fspath(path))
    gen.setTitle("LumaCut Studio")
    # 25.4 dpi -> 1 Benutzereinheit = 1 mm
    gen.setResolution(int(round(25.4)))
    gen.setSize(QSize(int(WORK_WIDTH_MM), int(WORK_HEIGHT_MM)))
    gen.setViewBox(QRectF(0, 0, WORK_WIDTH_MM, WORK_HEIGHT_MM))
    p = QPainter(gen)
    _paint(doc, p, 0.2, show_fill)
    p.end()


def export_png(doc: Document, path: str | os.PathLike[str], px_per_mm: float = 10.0,
               background: QColor | None = None, show_fill: bool = False) -> QImage:
    """Rastert die Arbeitsfläche (Standard 10 px/mm = 254 dpi); ``show_fill`` mit Schraffur."""
    img = QImage(int(WORK_WIDTH_MM * px_per_mm), int(WORK_HEIGHT_MM * px_per_mm),
                 QImage.Format_ARGB32)
    img.fill(background or QColor(255, 255, 255))
    p = QPainter(img)
    p.scale(px_per_mm, px_per_mm)
    _paint(doc, p, max(0.15, 1.5 / px_per_mm), show_fill)
    p.end()
    img.setDotsPerMeterX(int(px_per_mm * 1000))
    img.setDotsPerMeterY(int(px_per_mm * 1000))
    if not img.save(os.fspath(path)):
        raise OSError(f"PNG konnte nicht gespeichert werden: {path}")
    return img
