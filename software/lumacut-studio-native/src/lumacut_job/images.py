"""Bildobjekte des Canvas → Raster-/3D-G-Code (über :mod:`.raster`).

Jedes Bildobjekt (``Shape.kind == "image"``) wird samt Drehung im
Linienabstand seiner Einstellungen in ein Graustufen-Array gerendert
(achsparallele Hüllbox, außerhalb des Bildes = nicht lasern) und mit der
vorhandenen Raster-Engine umgesetzt:

* ``threshold``/``floyd``/``atkinson``/``ordered``/``grayscale``/``jarvis``/
  ``stucki``/``sierra``/``halftone``/``newsprint``/``sketch`` →
  :func:`raster.power_map` + :func:`raster.scanlines` (Punktbreitenkorrektur
  ``dot_width_mm`` gilt für alle Modi inkl. 3D);
* ``depth3d`` → :func:`raster.sliced_depth_gcode` (Mehrfach-Durchgänge nach
  Helligkeit, optional Fokus-Absenkung je Stufe).

Bildanpassung (Helligkeit, Kontrast, Gamma, Schärfen) rechnet
:func:`raster.power_map` bzw. :func:`raster.sliced_depth_gcode` vor dem Modus;
bei gedrehten Bildern verhindert eine Innen-Maske (:func:`render_inside`), dass
die Ecken der Hüllbox durch Anpassung oder Skizzen-Kanten gelasert werden.

Scan-Versatz (:mod:`.scan_offset`, Tabelle nach Geschwindigkeit): jede
Rasterzeile wandert um den halben Versatz entgegen ihrer Fahrtrichtung –
Ursprung um die Hälfte zurück, Rückwärtszeilen um den ganzen Versatz
(``RasterSettings.scan_offset_mm``) vor. Am Rand der Arbeitsfläche wird der
Versatz gekürzt; ohne Tabelle bleibt die Ausgabe gleich.

Scan-Winkel (LightBurn „Scan Angle“ / „Angle Increment“, ``ImageSettings.scan_angle``
und ``angle_increment``): bei einem Winkel ≠ 0 wird das Bild in einem um den
Winkel gedrehten Raster gerendert (:class:`ScanGeometry`, :func:`render_gray_frame`)
– eine Zeile = eine Rasterzeile unter dem Winkel – und mit derselben Engine
gerastert; :func:`raster.scanlines_frame` gibt die Zeilen als schräge ``G1`` aus
(X und Y zugleich, wie Vektorlinien). Jede Zeile wird auf die Sehne des
(gedrehten) Bildes gekürzt, Overscan und Scan-Versatz laufen entlang der
Zeile, der Halbtonwinkel bleibt auf dem Werkstück wie eingestellt. Mit
Winkel-Schritt bekommt jeder weitere Durchgang den Winkel + k × Schritt
(eigene Rasterung je Winkel). Winkel 0 = bisheriger Weg, Ausgabe unverändert.

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

from .raster import (_MAX_X, _MAX_Y, _MIN_X, _MIN_Y, RasterSettings, ScanFrame, power_map,
                     scanlines, scanlines_frame, sliced_depth_gcode, wrap_angle)

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
                          negative=st.negative, halftone_cpi=st.halftone_cpi,
                          halftone_angle=st.halftone_angle, dot_width_mm=st.dot_width_mm,
                          brightness=st.brightness, contrast=st.contrast, gamma=st.gamma,
                          sharpen=st.sharpen, sharpen_radius=st.sharpen_radius,
                          black_point=st.black_point, white_point=st.white_point,
                          curve=st.curve)


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


def render_inside(shape: Shape, interval_mm: float) -> np.ndarray | None:
    """Bool-Maske „Pixel liegt im (gedrehten) Bild“ im Raster von :func:`render_gray`.

    ``None`` bei ungedrehten Bildern (Hüllbox = Bild, alles innen).
    """
    if not shape.geom.rot:
        return None
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QColor, QImage, QPainter

    from lumacut_canvas.shape_paths import geometry_transform

    b = shape.geom.bounds()
    cols = max(1, int(round(b.w / interval_mm)))
    rows = max(1, int(round(b.h / interval_mm)))
    canvas = QImage(cols, rows, QImage.Format_Grayscale8)
    canvas.fill(QColor(0, 0, 0))
    p = QPainter(canvas)
    p.scale(cols / b.w if b.w else 1.0, rows / b.h if b.h else 1.0)
    p.translate(-b.x, -b.y)
    p.setTransform(geometry_transform(shape.geom), True)
    lb = shape.geom.local_bounds()
    p.fillRect(QRectF(lb.x, lb.y, lb.w, lb.h), QColor(255, 255, 255))
    p.end()
    stride = canvas.bytesPerLine()
    arr = np.frombuffer(canvas.constBits(), dtype=np.uint8, count=stride * rows)
    return arr.reshape(rows, stride)[:, :cols] >= 128


def _strip(program: str) -> list[str]:
    """Header (5 Zeilen) und Footer (M5 I, M400) eines Teilprogramms entfernen."""
    lines = program.strip().splitlines()
    return lines[5:-2]


def pass_angles(st) -> list[float]:
    """Scan-Winkel je Durchgang (Grad in [-90, 90)): Winkel + k × Schritt."""
    st = st.normalized()
    return [wrap_angle(st.scan_angle + k * st.angle_increment) if (st.scan_angle or st.angle_increment)
            else 0.0 for k in range(st.passes)]


def _axis_body(shape: Shape, scan_offsets=None) -> list[str]:
    """Rasterzeilen entlang Maschinen-X (bisheriger Weg, Scan-Winkel 0)."""
    st = shape.image.settings.normalized()
    gray, (cx, cy) = render_gray(shape, st.line_interval_mm)
    width = gray.shape[1] * st.line_interval_mm
    adjusts = st.mode == "sketch" or raster_settings(shape).adjusted()
    inside = render_inside(shape, st.line_interval_mm) if adjusts else None
    if inside is not None and inside.shape != gray.shape:
        inside = None
    if IMAGE_FLIP_X:
        # Nullpunkt oben rechts (Anforderungen 2026-10-26 §2.1): Maschinen-X wächst
        # nach links. Raster laufen in +X ab Spalte 0 → Spalte 0 = rechte Bildkante.
        gray = np.ascontiguousarray(gray[:, ::-1])
        if inside is not None:
            inside = np.ascontiguousarray(inside[:, ::-1])
        ox, oy = to_machine(cx + width, cy)
        flipped = True
    else:
        ox, oy = to_machine(cx, cy)
        flipped = False
    # Scan-Versatz: halbe Verschiebung je Richtung, am Rand gekürzt.
    off = scan_offsets.offset_for(st.speed_mm_min) if scan_offsets is not None else 0.0
    edge = max(0.0, min(ox - _MIN_X, _MAX_X - (ox + width)))
    if abs(off) / 2 > edge:
        off = (2 * edge) if off > 0 else (-2 * edge)
    ox -= off / 2
    # Overscan am Rand der Arbeitsfläche kürzen statt den Auftrag abzulehnen.
    room = min(ox - _MIN_X, _MAX_X - (ox + width), ox + off - _MIN_X, _MAX_X - (ox + off + width))
    s = raster_settings(shape, max(0.0, min(st.overscan_mm, room)))
    s.scan_offset_mm = round(off, 4)
    if flipped:
        # Gespiegeltes Array: Rasterwinkel spiegeln, damit der Halbton auf dem
        # Werkstück unter dem eingestellten Winkel liegt (wie in der Vorschau).
        s.halftone_angle = -s.halftone_angle
    if st.mode == "depth3d":
        prog = sliced_depth_gcode(gray, (ox, oy), width, gray.shape[0] * st.line_interval_mm,
                                  s, levels=st.depth_levels, z_step_mm=st.z_step_mm,
                                  inside=inside)
        return _strip(prog)
    pm = power_map(gray, s) if inside is None else power_map(gray, s, inside=inside)
    return scanlines(pm, (ox, oy), s)


# ----------------------------------------------------------- Scan-Winkel
@dataclass(frozen=True)
class ScanGeometry:
    """Gedrehtes Raster eines Bildobjekts für einen Scan-Winkel.

    Canvas-mm (Y nach unten): Zeilenrichtung ``u = (cos θ, −sin θ)`` (θ gegen
    den Uhrzeigersinn wie auf dem Bildschirm), Zeilenfolge ``v = (sin θ, cos θ)``
    (θ = 0: ``u`` = +X, ``v`` = +Y wie bisher). Ein Punkt ``(a, b)`` des
    Rasters (mm ab der linken oberen Rasterecke) liegt bei
    ``c + (a0 + a)·u + (b0 + b)·v``; Spalte *i* / Zeile *j* = Laserpunkt
    ``a ∈ [i·px, (i+1)·px]``, ``b = (j + ½)·px``.
    """

    angle: float
    px: float
    cx: float
    cy: float
    ux: float
    uy: float
    vx: float
    vy: float
    a0: float
    b0: float
    cols: int
    rows: int
    corners: tuple                # Bildecken im Raster ((a, b), ...) in mm

    def canvas_point(self, a: float, b: float) -> tuple[float, float]:
        aa, bb = self.a0 + a, self.b0 + b
        return (self.cx + aa * self.ux + bb * self.vx, self.cy + aa * self.uy + bb * self.vy)

    def chords(self) -> list[tuple[float, float]]:
        """Je Zeile ``(lo, hi)`` in mm entlang der Zeile: Teil im Bild."""
        out = []
        pts = list(self.corners)
        n = len(pts)
        for j in range(self.rows):
            b = (j + 0.5) * self.px
            hits = []
            for k in range(n):
                (a1, b1), (a2, b2) = pts[k], pts[(k + 1) % n]
                if (b1 <= b <= b2 or b2 <= b <= b1) and abs(b2 - b1) > 1e-12:
                    hits.append(a1 + (b - b1) * (a2 - a1) / (b2 - b1))
            out.append((min(hits), max(hits)) if hits else (1.0, 0.0))
        return out

    def machine_frame(self) -> ScanFrame:
        x0, y0 = to_machine(*self.canvas_point(0.0, 0.0))
        xu, yu = to_machine(*self.canvas_point(1.0, 0.0))
        xv, yv = to_machine(*self.canvas_point(0.0, 1.0))
        return ScanFrame(x0, y0, xu - x0, yu - y0, xv - x0, yv - y0)

    def qtransform(self):
        """Canvas-mm → Rasterpixel (für QPainter)."""
        from PySide6.QtGui import QTransform
        p = self.px
        dx = (-(self.ux * self.cx + self.uy * self.cy) - self.a0) / p
        dy = (-(self.vx * self.cx + self.vy * self.cy) - self.b0) / p
        return QTransform(self.ux / p, self.vx / p, self.uy / p, self.vy / p, dx, dy)


def scan_geometry(shape: Shape, angle: float, interval_mm: float) -> ScanGeometry:
    """Raster des Bildobjekts unter ``angle`` Grad (siehe :class:`ScanGeometry`)."""
    import math
    t = math.radians(angle)
    ux, uy = math.cos(t), -math.sin(t)
    vx, vy = math.sin(t), math.cos(t)
    cx, cy = shape.geom.center()
    ab = [((x - cx) * ux + (y - cy) * uy, (x - cx) * vx + (y - cy) * vy)
          for x, y in shape.geom.corner_points()]
    amin, amax = min(a for a, _ in ab), max(a for a, _ in ab)
    bmin, bmax = min(b for _, b in ab), max(b for _, b in ab)
    cols = max(1, int(math.ceil((amax - amin) / interval_mm - 1e-6)))
    rows = max(1, int(math.ceil((bmax - bmin) / interval_mm - 1e-6)))
    if cols * rows > MAX_RASTER_PIXELS:
        raise ValueError(f"Bild zu groß für {interval_mm:g} mm Linienabstand "
                         f"({cols}×{rows} Punkte) – Linienabstand erhöhen")
    a0 = (amin + amax) / 2 - cols * interval_mm / 2
    b0 = (bmin + bmax) / 2 - rows * interval_mm / 2
    corners = tuple((a - a0, b - b0) for a, b in ab)
    return ScanGeometry(float(angle), interval_mm, cx, cy, ux, uy, vx, vy, a0, b0, cols, rows,
                        corners)


def _paint_frame(shape: Shape, geo: ScanGeometry, fill, draw) -> np.ndarray:
    from PySide6.QtGui import QImage, QPainter

    from lumacut_canvas.shape_paths import geometry_transform

    canvas = QImage(geo.cols, geo.rows, QImage.Format_Grayscale8)
    canvas.fill(fill)
    p = QPainter(canvas)
    p.setRenderHint(QPainter.SmoothPixmapTransform)
    p.setTransform(geo.qtransform())
    if shape.geom.rot:
        p.setTransform(geometry_transform(shape.geom), True)
    draw(p)
    p.end()
    stride = canvas.bytesPerLine()
    arr = np.frombuffer(canvas.constBits(), dtype=np.uint8, count=stride * geo.rows)
    return arr.reshape(geo.rows, stride)[:, :geo.cols].copy()


def render_gray_frame(shape: Shape, geo: ScanGeometry) -> np.ndarray:
    """Bild im gedrehten Raster (uint8, außerhalb = Nicht-lasern-Wert wie :func:`render_gray`)."""
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QColor

    from lumacut_canvas.image_cache import qimage_for

    src = qimage_for(shape.image.png)
    if src.isNull():
        raise ValueError("Bilddaten beschädigt")
    neg = shape.image.settings.negative
    lb = shape.geom.local_bounds()
    return _paint_frame(shape, geo, QColor(0, 0, 0) if neg else QColor(255, 255, 255),
                        lambda p: p.drawImage(QRectF(lb.x, lb.y, lb.w, lb.h), src))


def render_inside_frame(shape: Shape, geo: ScanGeometry) -> np.ndarray:
    """Innen-Maske im gedrehten Raster (wie :func:`render_inside`)."""
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QColor

    lb = shape.geom.local_bounds()
    arr = _paint_frame(shape, geo, QColor(0, 0, 0),
                       lambda p: p.fillRect(QRectF(lb.x, lb.y, lb.w, lb.h), QColor(255, 255, 255)))
    return arr >= 128


def _room(x: float, y: float, dx: float, dy: float) -> float:
    """Weg ab (x, y) in Richtung (dx, dy) bis zum Rand der Arbeitsfläche."""
    r = float("inf")
    if dx > 1e-12:
        r = min(r, (_MAX_X - x) / dx)
    elif dx < -1e-12:
        r = min(r, (x - _MIN_X) / -dx)
    if dy > 1e-12:
        r = min(r, (_MAX_Y - y) / dy)
    elif dy < -1e-12:
        r = min(r, (y - _MIN_Y) / -dy)
    return r


def angled_settings(shape: Shape, angle: float, scan_offsets=None,
                    geo: ScanGeometry | None = None) -> tuple[RasterSettings, ScanFrame]:
    """Raster-Einstellungen und Maschinen-Rahmen für einen Scan-Winkel.

    Scan-Versatz und Overscan werden wie beim waagerechten Raster am Rand der
    Arbeitsfläche gekürzt – gemessen entlang der Zeile ab den Bildecken (die
    Zeilen enden auf dem Bildrand, der Weg zum Rand ist an einer Ecke am kürzesten).
    """
    st = shape.image.settings.normalized()
    geo = geo or scan_geometry(shape, angle, st.line_interval_mm)
    frame = geo.machine_frame()
    room = float("inf")
    for a, b in geo.corners:
        x, y = frame.point(a, b)
        room = min(room, _room(x, y, frame.ux, frame.uy), _room(x, y, -frame.ux, -frame.uy))
    room = max(0.0, room)
    off = scan_offsets.offset_for(st.speed_mm_min) if scan_offsets is not None else 0.0
    if abs(off) / 2 > room:
        off = (2 * room) if off > 0 else (-2 * room)
    frame = frame.shifted(-off / 2)
    s = raster_settings(shape, max(0.0, min(st.overscan_mm, room - abs(off) / 2)))
    s.scan_offset_mm = round(off, 4)
    # Halbton im gedrehten Raster: Winkel auf dem Werkstück bleibt der eingestellte.
    s.halftone_angle = wrap_angle(s.halftone_angle + angle)
    return s, frame


def _angled_body(shape: Shape, angle: float, scan_offsets=None) -> list[str]:
    """Rasterzeilen unter ``angle`` Grad (schräge ``G1``)."""
    st = shape.image.settings.normalized()
    geo = scan_geometry(shape, angle, st.line_interval_mm)
    gray = render_gray_frame(shape, geo)
    adjusts = st.mode == "sketch" or raster_settings(shape).adjusted()
    inside = render_inside_frame(shape, geo) if adjusts else None
    s, frame = angled_settings(shape, angle, scan_offsets, geo)
    chords = geo.chords()
    if st.mode == "depth3d":
        px = st.line_interval_mm
        prog = sliced_depth_gcode(gray, (0.0, 0.0), geo.cols * px, geo.rows * px, s,
                                  levels=st.depth_levels, z_step_mm=st.z_step_mm,
                                  inside=inside, frame=frame, chords=chords)
        return _strip(prog)
    pm = power_map(gray, s) if inside is None else power_map(gray, s, inside=inside)
    return scanlines_frame(pm, frame, s, chords=chords)


def image_job(shape: Shape, layer_name: str = "", scan_offsets=None) -> ImageJob:
    """Raster-/3D-Programm eines Bildes; ``scan_offsets`` = ``ScanOffsetTable`` oder None."""
    st = shape.image.settings.normalized()
    title = f"; IMAGE {shape.id} {st.mode.upper()}"
    angles = pass_angles(st)
    if not any(angles):
        body = _axis_body(shape, scan_offsets)
        if not body:
            raise ValueError("Bild enthält nichts zu gravieren")
        lines = [title]
        for k in range(st.passes):
            if st.passes > 1:
                lines.append(f"; PASS {k + 1} OF {st.passes}")
            lines += body
        return ImageJob(shape.id, layer_name, lines)
    bodies: dict[float, list[str]] = {}
    lines = [title]
    for k, angle in enumerate(angles):
        if angle not in bodies:
            body = (_angled_body(shape, angle, scan_offsets) if angle
                    else _axis_body(shape, scan_offsets))
            if not body:
                raise ValueError("Bild enthält nichts zu gravieren")
            bodies[angle] = body
        if st.passes > 1:
            lines.append(f"; PASS {k + 1} OF {st.passes}")
        lines.append(f"; SCAN ANGLE {angle:g}")
        lines += bodies[angle]
    return ImageJob(shape.id, layer_name, lines)


def document_image_jobs(doc: Document, scan_offsets=None) -> list[ImageJob]:
    """Bilder sichtbarer Ebenen, unterste Ebene zuerst (wie job_layers).

    ``Layer.z_offset`` wraps each image of that layer in the same relative
    ``G91``/``G0 Z``/``G90`` pair that vector layers use (negativ = näher am
    Material), so a material-test focus axis also moves image cells.
    """
    jobs: list[ImageJob] = []
    for layer in reversed(doc.layers):
        if not layer.visible:
            continue
        z = float(getattr(layer, "z_offset", 0.0) or 0.0)
        wrap = (["G91", f"G0 Z{z:.3f} F600", "G90"],
                ["G91", f"G0 Z{-z:.3f} F600", "G90"]) if abs(z) > 1e-9 else None
        for s in doc.shapes_in_layer(layer.id):
            if s.kind == "image" and s.image is not None:
                job = image_job(s, layer.name, scan_offsets)
                if wrap is not None:
                    job.lines = wrap[0] + job.lines + wrap[1]
                jobs.append(job)
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
