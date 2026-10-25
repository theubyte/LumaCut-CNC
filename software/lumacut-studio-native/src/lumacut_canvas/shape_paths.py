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


def text_path(text: str, family: str) -> QPainterPath:
    path = QPainterPath()
    font = QFont(family)
    font.setPointSizeF(_TEXT_BUILD_PT)
    for i, line in enumerate((text or " ").split("\n")):
        path.addText(QPointF(0, i * _TEXT_BUILD_PT * 1.25), font, line or " ")
    return path


def text_aspect(text: str, family: str) -> float:
    """Breite/Höhe des Textumrisses, um neue Textobjekte maßstäblich anzulegen."""
    r = text_path(text, family).boundingRect()
    return r.width() / r.height() if r.height() > 0 else 1.0


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
    b = g.local_bounds()
    box = QRectF(b.x, b.y, b.w, b.h)
    if shape.kind == "rect":
        path.addRect(box)
    elif shape.kind == "ellipse":
        path.addEllipse(box)
    elif shape.kind == "text":
        src = text_path(shape.text, shape.font_family)
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
