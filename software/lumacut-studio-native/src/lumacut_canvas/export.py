"""Export der Arbeitsfläche (SVG/PNG) und Übergabe an die Jobplanung.

:func:`job_layers` ist die Schnittstelle für den Job-/Maschinenteil: pro
sichtbarer Ebene die Laserparameter und alle Konturen als Polylinien in
**Maschinen**-mm (Safezone-Versatz bereits eingerechnet).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QBrush, QColor, QImage, QPainter, QPen
from PySide6.QtSvg import QSvgGenerator

from .hatch import fill_segments
from .material import layer_pass_plan
from .model import CUT_LAYER_FIELDS, FILLABLE_KINDS, Document, Layer, Shape
from .shape_paths import shape_path, shape_polygons
from .workarea import WORK_HEIGHT_MM, WORK_WIDTH_MM, to_machine


@dataclass
class JobLayer:
    layer_id: str
    name: str
    power_percent: float
    speed_mm_min: float
    passes: int
    polylines: list[list[tuple[float, float]]]  # Maschinen-mm
    z_step_mm: float = 0.0  # Fokus-Absenkung je Durchgang
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
    # Art je Polylinie nach der Planung ("cut", "lead_in", "lead_out", "tab" =
    # Schnittstück nach einer Steg-Lücke); leer = alles "cut".
    poly_kinds: tuple[str, ...] = ()
    # Vektor-Füllung: je gefülltem Objekt ein Block Schraffurstrecken
    # ((x0, y0), (x1, y1)) in Maschinen-mm, bereits in Fahr-Reihenfolge.
    # Der G-Code lasert je Durchgang zuerst die Füllungen, dann die Konturen.
    fills: list[list[tuple[tuple[float, float], tuple[float, float]]]] = field(default_factory=list)


def shape_fill_segments(shape: Shape, layer: Layer):
    """Schraffur eines Objekts nach der Ebenen-Füllung (Arbeitsflächen-mm).

    Gerade-Ungerade-Regel über alle Teilpfade des Objekts (Löcher in Text,
    Rahmen). Leer, wenn die Ebene nicht füllt oder das Objekt offen ist.
    """
    if layer.fill_mode == "none" or shape.kind not in FILLABLE_KINDS:
        return []
    polys = shape_polygons(shape)
    return fill_segments(polys, layer.fill_mode, layer.line_interval_mm, layer.hatch_angle,
                         layer.hatch_bidirectional)


def job_layers(doc: Document) -> list[JobLayer]:
    """Ebenen in Ausführungsreihenfolge (unterste Ebene zuerst).

    Ellipsen, Kurven und Text werden in Polylinien zerlegt
    (:func:`shape_paths.shape_polygons`, Sehnenfehler ≤ 0,02 mm).
    Ausgeblendete Ebenen werden nicht gelasert.
    """
    result: list[JobLayer] = []
    for layer in reversed(doc.layers):
        if not layer.visible:
            continue
        polys: list[list[tuple[float, float]]] = []
        fills = []
        for s in doc.shapes_in_layer(layer.id):
            if s.kind == "image":
                continue  # Bilder werden gerastert (lumacut_job.images), nicht umfahren
            segs = shape_fill_segments(s, layer)
            if segs:
                fills.append([(to_machine(*a), to_machine(*b)) for a, b in segs])
            if s.kind in FILLABLE_KINDS and layer.fill_mode != "none" and not layer.hatch_outline:
                continue  # nur Füllung, keine Kontur
            if s.kind == "line":
                path = shape_path(s)
                a, b = path.elementAt(0), path.elementAt(1)
                polys.append([to_machine(a.x, a.y), to_machine(b.x, b.y)])
                continue
            for poly in shape_polygons(s):
                polys.append([to_machine(x, y) for x, y in poly])
        if polys or fills:
            plan = layer_pass_plan(layer)
            result.append(JobLayer(layer.id, layer.name, layer.power, layer.speed,
                                   layer.passes, polys, layer.z_step,
                                   plan.pass_depths if plan else (),
                                   **{k: getattr(layer, k) for k in CUT_LAYER_FIELDS}, fills=fills))
    return result


def _paint(doc: Document, p: QPainter, line_width_mm: float, show_fill: bool = False) -> None:
    p.setRenderHint(QPainter.Antialiasing)
    for layer in reversed(doc.layers):
        if not layer.visible:
            continue
        color = QColor(layer.color)
        for s in doc.shapes_in_layer(layer.id):
            pen = QPen(color, line_width_mm)
            pen.setCosmetic(False)
            p.setPen(pen)
            if s.kind == "image" and s.image is not None:
                _paint_image(p, s)
                continue
            if show_fill:
                segs = shape_fill_segments(s, layer)
                for a, b in segs:
                    p.drawLine(QPointF(*a), QPointF(*b))
                if segs and not layer.hatch_outline:
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
