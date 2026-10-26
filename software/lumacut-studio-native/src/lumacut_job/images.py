"""Bildobjekte des Canvas → Raster-/3D-G-Code (über :mod:`.raster`).

Jedes Bildobjekt (``Shape.kind == "image"``) wird samt Drehung im
Linienabstand seiner Einstellungen in ein Graustufen-Array gerendert
(achsparallele Hüllbox, außerhalb des Bildes = nicht lasern) und mit der
vorhandenen Raster-Engine umgesetzt:

* ``threshold``/``floyd``/``atkinson``/``ordered``/``grayscale`` →
  :func:`raster.power_map` + :func:`raster.scanlines`;
* ``depth3d`` → :func:`raster.sliced_depth_gcode` (Mehrfach-Durchgänge nach
  Helligkeit, optional Fokus-Absenkung je Stufe).

Der Overscan wird je Bild auf den Platz bis zum Rand der Arbeitsfläche
begrenzt, damit Bilder am Rand gültig bleiben. Header/Footer schreibt
:func:`planner.optimized_document_gcode` genau einmal für den ganzen Auftrag.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from lumacut_canvas.export import JobLayer
from lumacut_canvas.model import Document, Shape
from lumacut_canvas.workarea import IMAGE_FLIP_X, to_machine

from .raster import _MAX_X, _MIN_X, RasterSettings, power_map, scanlines, sliced_depth_gcode

MAX_RASTER_PIXELS = 16_000_000


@dataclass
class ImageJob:
    shape_id: str
    layer_name: str
    lines: list[str]          # Rumpf ohne Header/Footer


def raster_settings(shape: Shape, overscan_mm: float | None = None) -> RasterSettings:
    st = shape.image.settings.normalized()
    mode = "floyd" if st.mode == "depth3d" else st.mode
    return RasterSettings(line_interval_mm=st.line_interval_mm, power=st.power,
                          min_power=min(st.min_power, st.power), speed_mm_min=st.speed_mm_min,
                          mode=mode, threshold=st.threshold, bidirectional=st.bidirectional,
                          overscan_mm=st.overscan_mm if overscan_mm is None else overscan_mm,
                          negative=st.negative)


def render_gray(shape: Shape, interval_mm: float) -> tuple[np.ndarray, tuple[float, float]]:
    """Bild (inkl. Drehung) → (uint8-Array, Canvas-mm der linken oberen Ecke).

    Ein Pixel = ``interval_mm``. Flächen der Hüllbox außerhalb des gedrehten
    Bildes bekommen den Nicht-lasern-Wert (Weiß bzw. Schwarz bei Negativ).
    """
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QColor, QImage, QPainter

    from lumacut_canvas.image_cache import qimage_for
    from lumacut_canvas.shape_paths import geometry_transform

    src = qimage_for(shape.image.png)
    if src.isNull():
        raise ValueError("Bilddaten beschädigt")
    b = shape.geom.bounds()
    cols = max(1, int(round(b.w / interval_mm)))
    rows = max(1, int(round(b.h / interval_mm)))
    if cols * rows > MAX_RASTER_PIXELS:
        raise ValueError(f"Bild zu groß für {interval_mm:g} mm Linienabstand "
                         f"({cols}×{rows} Punkte) – Linienabstand erhöhen")
    neg = shape.image.settings.negative
    canvas = QImage(cols, rows, QImage.Format_RGB32)
    canvas.fill(QColor(0, 0, 0) if neg else QColor(255, 255, 255))
    p = QPainter(canvas)
    p.setRenderHint(QPainter.SmoothPixmapTransform)
    p.scale(cols / b.w if b.w else 1.0, rows / b.h if b.h else 1.0)
    p.translate(-b.x, -b.y)
    if shape.geom.rot:
        p.setTransform(geometry_transform(shape.geom), True)
    lb = shape.geom.local_bounds()
    p.drawImage(QRectF(lb.x, lb.y, lb.w, lb.h), src)
    p.end()
    gray = canvas.convertToFormat(QImage.Format_Grayscale8)
    stride = gray.bytesPerLine()
    arr = np.frombuffer(gray.constBits(), dtype=np.uint8, count=stride * rows)
    return arr.reshape(rows, stride)[:, :cols].copy(), (b.x, b.y)


def _strip(program: str) -> list[str]:
    """Header (5 Zeilen) und Footer (M5 I, M400) eines Teilprogramms entfernen."""
    lines = program.strip().splitlines()
    return lines[5:-2]


def image_job(shape: Shape, layer_name: str = "") -> ImageJob:
    st = shape.image.settings.normalized()
    gray, (cx, cy) = render_gray(shape, st.line_interval_mm)
    width = gray.shape[1] * st.line_interval_mm
    if IMAGE_FLIP_X:
        # Nullpunkt oben rechts (Anforderungen 2026-10-26 §2.1): Maschinen-X wächst
        # nach links. Raster laufen in +X ab Spalte 0 → Spalte 0 = rechte Bildkante.
        gray = np.ascontiguousarray(gray[:, ::-1])
        ox, oy = to_machine(cx + width, cy)
    else:
        ox, oy = to_machine(cx, cy)
    # Overscan am Rand der Arbeitsfläche kürzen statt den Auftrag abzulehnen.
    room = min(ox - _MIN_X, _MAX_X - (ox + width))
    s = raster_settings(shape, max(0.0, min(st.overscan_mm, room)))
    title = f"; IMAGE {shape.id} {st.mode.upper()}"
    if st.mode == "depth3d":
        prog = sliced_depth_gcode(gray, (ox, oy), width, gray.shape[0] * st.line_interval_mm,
                                  s, levels=st.depth_levels, z_step_mm=st.z_step_mm)
        body = _strip(prog)
    else:
        body = scanlines(power_map(gray, s), (ox, oy), s)
    if not body:
        raise ValueError("Bild enthält nichts zu gravieren")
    lines = [title]
    for k in range(st.passes):
        if st.passes > 1:
            lines.append(f"; PASS {k + 1} OF {st.passes}")
        lines += body
    return ImageJob(shape.id, layer_name, lines)


def document_image_jobs(doc: Document) -> list[ImageJob]:
    """Bilder sichtbarer Ebenen, unterste Ebene zuerst (wie job_layers)."""
    jobs: list[ImageJob] = []
    for layer in reversed(doc.layers):
        if not layer.visible:
            continue
        for s in doc.shapes_in_layer(layer.id):
            if s.kind == "image" and s.image is not None:
                jobs.append(image_job(s, layer.name))
    return jobs


def image_outline_layers(doc: Document) -> list[JobLayer]:
    """Umriss (gedrehte Box) jedes sichtbaren Bildes – für Rahmen und Vorschau."""
    polys = []
    for layer in reversed(doc.layers):
        if not layer.visible:
            continue
        for s in doc.shapes_in_layer(layer.id):
            if s.kind == "image":
                pts = [to_machine(x, y) for x, y in s.geom.corner_points()]
                polys.append(pts + [pts[0]])
    if not polys:
        return []
    return [JobLayer("__images__", "Bilder", 1.0, 1000.0, 1, polys)]
