"""Toolbar-Icons, im Code gezeichnet (keine Bilddateien, skalieren scharf).

Jedes Icon wird auf einem 24×24-Raster beschrieben und in 48 px gerendert.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Callable

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap, QPolygonF

from . import theme

_SIZE = 48


def _pen(p: QPainter, color: str, w: float = 1.8) -> None:
    pen = QPen(QColor(color), w)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)


def _select(p: QPainter, c: str) -> None:
    path = QPainterPath()
    path.moveTo(6, 3); path.lineTo(6, 19); path.lineTo(10, 15.5)
    path.lineTo(13, 21); path.lineTo(15.5, 20); path.lineTo(12.6, 14.2); path.lineTo(18, 14)
    path.closeSubpath()
    _pen(p, c, 1.6); p.setBrush(QColor(c)); p.drawPath(path)


def _rect(p, c):
    _pen(p, c); p.drawRoundedRect(QRectF(4, 6, 16, 12), 1.5, 1.5)


def _ellipse(p, c):
    _pen(p, c); p.drawEllipse(QRectF(3.5, 5.5, 17, 13))


def _line(p, c):
    _pen(p, c, 2.0); p.drawLine(QPointF(5, 19), QPointF(19, 5))
    p.setBrush(QColor(c)); p.drawEllipse(QPointF(5, 19), 1.6, 1.6); p.drawEllipse(QPointF(19, 5), 1.6, 1.6)


def _polygon(p, c):
    pts = [QPointF(12, 4), QPointF(20, 10), QPointF(17, 19.5), QPointF(7, 19.5), QPointF(4, 10)]
    _pen(p, c); p.drawPolygon(QPolygonF(pts))
    p.setBrush(QColor(c))
    for q in pts:
        p.drawEllipse(q, 1.4, 1.4)


def _freehand(p, c):
    _pen(p, c, 2.0); path = QPainterPath(); path.moveTo(4, 17)
    path.cubicTo(7, 6, 10, 6, 11.5, 12); path.cubicTo(13, 18, 17, 18, 20, 7); p.drawPath(path)
    p.setBrush(QColor(c)); p.drawEllipse(QPointF(4, 17), 1.4, 1.4)


def _text(p, c):
    _pen(p, c, 2.2); p.drawLine(QPointF(5, 5.5), QPointF(19, 5.5)); p.drawLine(QPointF(12, 5.5), QPointF(12, 19.5))
    _pen(p, c, 1.6); p.drawLine(QPointF(9.5, 19.5), QPointF(14.5, 19.5))


def _undo(p, c):
    _pen(p, c); path = QPainterPath(); path.moveTo(8, 9); path.lineTo(15, 9)
    path.cubicTo(22, 9, 22, 19, 15, 19); path.lineTo(9, 19); p.drawPath(path)
    p.drawPolyline(QPolygonF([QPointF(11, 5), QPointF(7, 9), QPointF(11, 13)]))


def _redo(p, c):
    p.translate(24, 0); p.scale(-1, 1); _undo(p, c)


def _delete(p, c):
    _pen(p, c); p.drawLine(QPointF(4.5, 7), QPointF(19.5, 7)); p.drawLine(QPointF(10, 4.5), QPointF(14, 4.5))
    p.drawRoundedRect(QRectF(6.5, 7, 11, 13), 1.5, 1.5)
    p.drawLine(QPointF(10.5, 10.5), QPointF(10.5, 16.5)); p.drawLine(QPointF(13.5, 10.5), QPointF(13.5, 16.5))


def _fit(p, c):
    _pen(p, c)
    for pts in (((4, 9), (4, 4), (9, 4)), ((15, 4), (20, 4), (20, 9)),
                ((20, 15), (20, 20), (15, 20)), ((9, 20), (4, 20), (4, 15))):
        p.drawPolyline(QPolygonF([QPointF(*q) for q in pts]))
    p.drawRect(QRectF(8.5, 8.5, 7, 7))


def _zoom(p, c, plus: bool):
    _pen(p, c); p.drawEllipse(QPointF(10.5, 10.5), 6, 6); p.drawLine(QPointF(15, 15), QPointF(20, 20))
    p.drawLine(QPointF(8, 10.5), QPointF(13, 10.5))
    if plus:
        p.drawLine(QPointF(10.5, 8), QPointF(10.5, 13))


def _grid(p, c):
    _pen(p, c, 1.4); p.drawRect(QRectF(4, 4, 16, 16))
    for v in (9.33, 14.66):
        p.drawLine(QPointF(v, 4), QPointF(v, 20)); p.drawLine(QPointF(4, v), QPointF(20, v))


def _snap(p, c):
    _pen(p, c, 2.0); path = QPainterPath(); path.moveTo(6, 4); path.lineTo(6, 12)
    path.arcTo(QRectF(6, 6, 12, 12), 180, 180); path.lineTo(18, 4); p.drawPath(path)
    _pen(p, theme.ACCENT, 2.6); p.drawLine(QPointF(6, 4), QPointF(6, 7)); p.drawLine(QPointF(18, 4), QPointF(18, 7))


def _open(p, c):
    _pen(p, c); path = QPainterPath(); path.moveTo(3.5, 18.5); path.lineTo(3.5, 6); path.lineTo(9, 6)
    path.lineTo(11, 8); path.lineTo(18.5, 8); path.lineTo(18.5, 11); p.drawPath(path)
    p.drawPolygon(QPolygonF([QPointF(3.5, 18.5), QPointF(7, 11), QPointF(21, 11), QPointF(17.5, 18.5)]))


def _save(p, c):
    _pen(p, c); p.drawPolygon(QPolygonF([QPointF(4, 4), QPointF(17, 4), QPointF(20, 7), QPointF(20, 20), QPointF(4, 20)]))
    p.drawRect(QRectF(8, 4, 7, 5)); p.drawRect(QRectF(7.5, 13, 9, 7))


def _export(p, c):
    _pen(p, c); p.drawPolyline(QPolygonF([QPointF(9, 6), QPointF(5, 6), QPointF(5, 19), QPointF(19, 19), QPointF(19, 15)]))
    p.drawLine(QPointF(11, 13), QPointF(20, 4)); p.drawPolyline(QPolygonF([QPointF(14, 4), QPointF(20, 4), QPointF(20, 10)]))


def _eye(p, c, off: bool = False):
    _pen(p, c, 1.6); path = QPainterPath(); path.moveTo(3, 12)
    path.quadTo(12, 3, 21, 12); path.quadTo(12, 21, 3, 12); p.drawPath(path)
    p.drawEllipse(QPointF(12, 12), 2.8, 2.8)
    if off:
        _pen(p, theme.DANGER, 2.0); p.drawLine(QPointF(5, 19), QPointF(19, 5))


def _lock(p, c, open_: bool = False):
    _pen(p, c, 1.7); p.drawRoundedRect(QRectF(5.5, 11, 13, 9), 1.5, 1.5)
    path = QPainterPath(); path.moveTo(8.5, 11); path.lineTo(8.5, 8)
    path.arcTo(QRectF(8.5, 4.5, 7, 7), 180, -180)
    if not open_:
        path.lineTo(15.5, 11)
    p.drawPath(path)


def _plus(p, c):
    _pen(p, c, 2.0); p.drawLine(QPointF(12, 5), QPointF(12, 19)); p.drawLine(QPointF(5, 12), QPointF(19, 12))


def _arrow(p, c, up: bool):
    _pen(p, c, 2.0)
    if not up:
        p.translate(0, 24); p.scale(1, -1)
    p.drawLine(QPointF(12, 19), QPointF(12, 5)); p.drawPolyline(QPolygonF([QPointF(6, 11), QPointF(12, 5), QPointF(18, 11)]))


def _duplicate(p, c):
    _pen(p, c); p.drawRoundedRect(QRectF(8, 8, 12, 12), 1.5, 1.5)
    p.drawPolyline(QPolygonF([QPointF(16, 8), QPointF(16, 4), QPointF(4, 4), QPointF(4, 16), QPointF(8, 16)]))


def _link(p, c):
    _pen(p, c, 1.8)
    p.drawRoundedRect(QRectF(3, 8.5, 10, 7), 3.5, 3.5)
    p.drawRoundedRect(QRectF(11, 8.5, 10, 7), 3.5, 3.5)


def _rotate(p, c, cw: bool = True):
    if not cw:
        p.translate(24, 0); p.scale(-1, 1)
    _pen(p, c); path = QPainterPath(); path.arcMoveTo(QRectF(5, 5, 14, 14), 150)
    path.arcTo(QRectF(5, 5, 14, 14), 150, -280); p.drawPath(path)
    end = path.currentPosition()
    p.drawPolyline(QPolygonF([QPointF(end.x() - 4.2, end.y() - 0.6), end, QPointF(end.x() - 0.2, end.y() + 4.2)]))


def _group(p, c, ungroup: bool = False):
    pen = QPen(QColor(c), 1.3, Qt.DashLine if not ungroup else Qt.SolidLine)
    if not ungroup:
        pen.setDashPattern([2, 2])
        p.setPen(pen); p.setBrush(Qt.NoBrush); p.drawRect(QRectF(3, 3, 18, 18))
    _pen(p, c, 1.6)
    if ungroup:
        p.drawRect(QRectF(3.5, 3.5, 8, 8)); p.drawRect(QRectF(12.5, 12.5, 8, 8))
    else:
        p.drawRect(QRectF(6, 6, 7, 7)); p.drawEllipse(QRectF(11, 11, 7, 7))


_PAINTERS: dict[str, Callable[[QPainter, str], None]] = {
    "select": _select, "rect": _rect, "ellipse": _ellipse, "line": _line, "text": _text,
    "polygon": _polygon, "freehand": _freehand,
    "undo": _undo, "redo": _redo, "delete": _delete, "fit": _fit,
    "zoom_in": lambda p, c: _zoom(p, c, True), "zoom_out": lambda p, c: _zoom(p, c, False),
    "grid": _grid, "snap": _snap, "open": _open, "save": _save, "export": _export,
    "eye": _eye, "eye_off": lambda p, c: _eye(p, c, True),
    "lock": _lock, "unlock": lambda p, c: _lock(p, c, True),
    "plus": _plus, "up": lambda p, c: _arrow(p, c, True), "down": lambda p, c: _arrow(p, c, False),
    "duplicate": _duplicate, "link": _link,
    "group": _group, "ungroup": lambda p, c: _group(p, c, True),
    "rotate_cw": _rotate, "rotate_ccw": lambda p, c: _rotate(p, c, False),
}


def _render(name: str, color: str) -> QPixmap:
    pm = QPixmap(_SIZE, _SIZE)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.scale(_SIZE / 24.0, _SIZE / 24.0)
    _PAINTERS[name](p, color)
    p.end()
    return pm


@lru_cache(maxsize=None)
def icon(name: str) -> QIcon:
    """Icon mit Normal-, Aktiv- und Deaktiviert-Zustand."""
    ic = QIcon()
    ic.addPixmap(_render(name, "#c9d3e0"), QIcon.Normal, QIcon.Off)
    ic.addPixmap(_render(name, theme.ACCENT), QIcon.Normal, QIcon.On)
    ic.addPixmap(_render(name, "#4a5566"), QIcon.Disabled)
    return ic


def available() -> list[str]:
    return sorted(_PAINTERS)
