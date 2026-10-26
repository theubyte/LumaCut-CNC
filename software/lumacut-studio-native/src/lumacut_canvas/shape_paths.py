"""Umwandlung von Modellobjekten in QPainterPath (für Anzeige und Export).

Benötigt QtGui; für Text muss eine QGuiApplication existieren (Schriften).
"""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QFont, QPainterPath, QTransform

from .model import Geometry, Shape

# Text wird in dieser Größe aufgebaut und dann exakt in die Objektbox skaliert,
# dadurch ist die Box (und nicht die Punktgröße) die maßgebliche Größe in mm.
_TEXT_BUILD_PT = 100.0

# Glatte Kreise/Ellipsen (Anforderungen 2026-10-26 §9.3): größter Abstand der
# Polylinie zur echten Kurve im G-Code, in der Schraffur und bei Boole/Versatz.
FLATTEN_TOL_MM = 0.02
MIN_ELLIPSE_SEGMENTS = 64
MAX_ELLIPSE_SEGMENTS = 4096
# Qt flacht Bézierkurven ab, bis der Fehler ≈ 0,5 Geräteeinheiten unterschreitet;
# vergrößert abflachen und zurückrechnen → Fehler ≈ 0,5/k mm (gemessen ≤ 0,013 mm).
_QT_FLATTEN_UNITS = 0.5
# Ellipse im QPainterPath aus 8 Bézierbögen à 45° statt Qts 4 à 90°:
# Formfehler 4·10⁻⁶·r statt 2,7·10⁻⁴·r (Ø 360 mm: 0,001 statt 0,05 mm) –
# gilt für Anzeige, SVG-Export (echte Kurven „C“) und Kurven-Abflachung.
_ELLIPSE_BEZIER_ARCS = 8


def text_font(family: str, bold: bool = False, italic: bool = False) -> QFont:
    font = QFont(family)
    font.setPointSizeF(_TEXT_BUILD_PT)
    font.setBold(bold)
    font.setItalic(italic)
    return font


def text_path(text: str, family: str, bold: bool = False, italic: bool = False) -> QPainterPath:
    path = QPainterPath()
    font = text_font(family, bold, italic)
    for i, line in enumerate((text or " ").split("\n")):
        path.addText(QPointF(0, i * _TEXT_BUILD_PT * 1.25), font, line or " ")
    return path


def text_aspect(text: str, family: str, bold: bool = False, italic: bool = False) -> float:
    """Breite/Höhe des Textumrisses, um neue Textobjekte maßstäblich anzulegen."""
    r = text_path(text, family, bold, italic).boundingRect()
    return r.width() / r.height() if r.height() > 0 else 1.0


def curve_controls(p0, p1, p2, p3) -> tuple[tuple[float, float], tuple[float, float]]:
    """Bézier-Kontrollpunkte für das Catmull-Rom-Segment p1→p2."""
    c1 = (p1[0] + (p2[0] - p0[0]) / 6.0, p1[1] + (p2[1] - p0[1]) / 6.0)
    c2 = (p2[0] - (p3[0] - p1[0]) / 6.0, p2[1] - (p3[1] - p1[1]) / 6.0)
    return c1, c2


def add_point_rings(path: QPainterPath, pts, ranges, curves: set[int], closed: bool) -> None:
    """Ringe aus Stützpunkten anhängen; Segmente in ``curves`` als Kurve."""
    for a, b in ranges:
        ring = pts[a:b]
        n = len(ring)
        if n == 0:
            continue
        path.moveTo(*ring[0])
        n_seg = n if closed and n > 2 else n - 1
        for k in range(n_seg):
            p1, p2 = ring[k], ring[(k + 1) % n]
            if a + k in curves:
                if closed:
                    p0, p3 = ring[(k - 1) % n], ring[(k + 2) % n]
                else:
                    p0 = ring[k - 1] if k > 0 else p1
                    p3 = ring[k + 2] if k + 2 < n else p2
                c1, c2 = curve_controls(p0, p1, p2, p3)
                path.cubicTo(QPointF(*c1), QPointF(*c2), QPointF(*p2))
            elif closed and k == n - 1:
                break  # gerades Schlusssegment: closeSubpath
            else:
                path.lineTo(*p2)
        if closed:
            path.closeSubpath()


def geometry_transform(g: Geometry) -> QTransform:
    """Drehung des Objekts um seine Boxmitte (Identität bei rot == 0)."""
    t = QTransform()
    if g.rot:
        cx, cy = g.center()
        t.translate(cx, cy)
        t.rotate(g.rot)
        t.translate(-cx, -cy)
    return t


def local_path(shape: Shape) -> QPainterPath:
    """Umriss in Arbeitsflächen-mm *ohne* Drehung."""
    g = shape.geom
    path = QPainterPath()
    if shape.kind == "line":
        path.moveTo(g.x, g.y)
        path.lineTo(g.x + g.w, g.y + g.h)
        return path
    if shape.kind in ("polygon", "path"):
        add_point_rings(path, shape.abs_points(), shape.ring_ranges(), set(shape.curves),
                        closed=shape.kind == "polygon")
        return path
    b = g.local_bounds()
    box = QRectF(b.x, b.y, b.w, b.h)
    if shape.kind in ("rect", "image"):  # Bild: Umriss = Bildrahmen
        path.addRect(box)
    elif shape.kind == "ellipse":
        add_ellipse(path, box)
    elif shape.kind == "text":
        src = text_path(shape.text, shape.font_family, shape.font_bold, shape.font_italic)
        r = src.boundingRect()
        if r.width() > 0 and r.height() > 0:
            t = QTransform()
            t.translate(box.x(), box.y())
            t.scale(box.width() / r.width(), box.height() / r.height())
            t.translate(-r.x(), -r.y())
            path = t.map(src)
    return path


def add_ellipse(path: QPainterPath, box: QRectF, arcs: int = _ELLIPSE_BEZIER_ARCS) -> None:
    """Geschlossene Ellipse in ``box`` aus ``arcs`` kubischen Bögen (Start rechts,
    Richtung wie ``QPainterPath.addEllipse``)."""
    cx, cy = box.center().x(), box.center().y()
    a, b = box.width() / 2.0, box.height() / 2.0
    d = 2.0 * math.pi / arcs
    k = 4.0 / 3.0 * math.tan(d / 4.0)
    path.moveTo(cx + a, cy)
    for i in range(arcs):
        t0, t1 = i * d, (i + 1) * d
        c0, s0, c1, s1 = math.cos(t0), math.sin(t0), math.cos(t1), math.sin(t1)
        path.cubicTo(QPointF(cx + a * (c0 - k * s0), cy + b * (s0 + k * c0)),
                     QPointF(cx + a * (c1 + k * s1), cy + b * (s1 - k * c1)),
                     QPointF(cx + a * c1, cy + b * s1))
    path.closeSubpath()


def ellipse_segments(a: float, b: float, tol: float = FLATTEN_TOL_MM) -> int:
    """Segmentzahl für eine Ellipse mit Halbachsen ``a``, ``b`` (mm).

    Gleichmäßig im Parameter t: der Sehnenfehler ist höchstens der eines Kreises
    mit dem größeren Halbmesser R, also R·(1 − cos(π/n)) ≤ ``tol``. Mindestens
    :data:`MIN_ELLIPSE_SEGMENTS`, Vielfaches von 4 (Scheitel liegen auf Punkten).
    """
    r = max(abs(a), abs(b))
    if r <= tol:
        n = MIN_ELLIPSE_SEGMENTS
    else:
        n = math.ceil(math.pi / math.acos(1.0 - tol / r))
    n = min(MAX_ELLIPSE_SEGMENTS, max(MIN_ELLIPSE_SEGMENTS, n))
    return -(-n // 4) * 4


def ellipse_polygon(g: Geometry, tol: float = FLATTEN_TOL_MM) -> list[tuple[float, float]]:
    """Ellipse der Box ``g`` als geschlossene Polylinie (erster = letzter Punkt),
    Drehung um die Boxmitte wie :func:`geometry_transform`."""
    cx, cy = g.x + g.w / 2.0, g.y + g.h / 2.0
    a, b = abs(g.w) / 2.0, abs(g.h) / 2.0
    n = ellipse_segments(a, b, tol)
    r = math.radians(g.rot or 0.0)
    cr, sr = math.cos(r), math.sin(r)
    pts = []
    for i in range(n):
        t = 2.0 * math.pi * i / n
        u, v = a * math.cos(t), b * math.sin(t)
        pts.append((cx + u * cr - v * sr, cy + u * sr + v * cr))
    pts.append(pts[0])
    return pts


def shape_polygons(shape: Shape, tol: float = FLATTEN_TOL_MM) -> list[list[tuple[float, float]]]:
    """Umriss als Polylinien in Arbeitsflächen-mm (inkl. Drehung), Kurven mit
    Sehnenfehler ≤ ``tol``. Geschlossene Ringe enden auf ihrem Startpunkt.

    Gemeinsame Quelle für G-Code, Schraffur-Beschnitt und Boole/Versatz.
    Ellipsen werden analytisch zerlegt (≥ 64 Segmente), alles andere über Qt
    mit vergrößerter Auflösung; gerade Strecken bekommen keine Zusatzpunkte.
    """
    if shape.kind == "ellipse":
        return [ellipse_polygon(shape.geom, tol)]
    path = shape_path(shape)
    k = max(1.0, _QT_FLATTEN_UNITS / tol)
    out = []
    for poly in path.toSubpathPolygons(QTransform.fromScale(k, k)):
        out.append([(p.x() / k, p.y() / k) for p in poly])
    return out


def shape_path(shape: Shape) -> QPainterPath:
    """Umriss des Objekts in Arbeitsflächen-mm inklusive Drehung.

    Anzeige, SVG/PNG-Export und G-Code gehen alle über diese Funktion, daher
    wirkt eine Drehung überall gleich.
    """
    path = local_path(shape)
    if shape.geom.rot:
        path = geometry_transform(shape.geom).map(path)
    return path
