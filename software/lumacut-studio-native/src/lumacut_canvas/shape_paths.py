"""Umwandlung von Modellobjekten in QPainterPath (für Anzeige und Export).

Benötigt QtGui; für Text muss eine QGuiApplication existieren (Schriften).
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import QFont, QPainterPath, QTransform

from .model import Geometry, Shape

# Text wird in dieser Größe aufgebaut und dann exakt in die Objektbox skaliert,
# dadurch ist die Box (und nicht die Punktgröße) die maßgebliche Größe in mm.
_TEXT_BUILD_PT = 100.0


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
        path.addEllipse(box)
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


def shape_path(shape: Shape) -> QPainterPath:
    """Umriss des Objekts in Arbeitsflächen-mm inklusive Drehung.

    Anzeige, SVG/PNG-Export und G-Code gehen alle über diese Funktion, daher
    wirkt eine Drehung überall gleich.
    """
    path = local_path(shape)
    if shape.geom.rot:
        path = geometry_transform(shape.geom).map(path)
    return path
