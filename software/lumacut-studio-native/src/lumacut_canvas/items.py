"""QGraphicsItems: Darstellung der Modellobjekte und der Auswahl.

Die Items sind reine Ansicht. Sie halten keine eigene Geometrie-Wahrheit,
sondern werden bei jeder Dokumentänderung aus dem Modell aktualisiert
(:meth:`CanvasScene.sync`). Dadurch gibt es genau eine Quelle für Undo,
Speichern und Job-Export.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QPainter, QPainterPath, QPainterPathStroker, QPen
from PySide6.QtWidgets import QGraphicsItem, QStyleOptionGraphicsItem, QWidget

from . import theme
from .model import Layer, Shape
from .shape_paths import shape_path
from .workarea import Rect

# Handle-Reihenfolge: 0 oben links, dann im Uhrzeigersinn.
#   0 1 2
#   7   3
#   6 5 4
HANDLE_FRACTIONS = ((0, 0), (0.5, 0), (1, 0), (1, 0.5), (1, 1), (0.5, 1), (0, 1), (0, 0.5))
HANDLE_PX = 9.0


class ShapeItem(QGraphicsItem):
    """Ein Vektorobjekt, gezeichnet in der Farbe seiner Ebene."""

    # Klicktoleranz in Pixeln; wird von der View in mm umgerechnet.
    hit_tolerance_mm: float = 1.0

    def __init__(self, shape: Shape, layer: Layer) -> None:
        super().__init__()
        self.shape_id = shape.id
        self._path = QPainterPath()
        self._hit = QPainterPath()
        self._color = QColor(layer.color)
        self._kind = shape.kind
        self.update_from(shape, layer)

    def update_from(self, shape: Shape, layer: Layer) -> None:
        self.prepareGeometryChange()
        self._kind = shape.kind
        self._path = shape_path(shape)
        self._color = QColor(layer.color)
        self._rebuild_hit()
        self.setVisible(layer.visible)
        self.setOpacity(0.55 if layer.locked else 1.0)
        self.update()

    def _rebuild_hit(self) -> None:
        if self._kind == "line":
            stroker = QPainterPathStroker()
            stroker.setWidth(self.hit_tolerance_mm * 2)
            self._hit = stroker.createStroke(self._path)
        else:
            # Flächen sind innen anklickbar, auch wenn nur der Umriss gelasert wird.
            r = self._path.boundingRect()
            m = self.hit_tolerance_mm
            hit = QPainterPath()
            if self._kind == "ellipse":
                hit.addEllipse(r.adjusted(-m, -m, m, m))
            else:
                hit.addRect(r.adjusted(-m, -m, m, m))
            self._hit = hit

    def refresh_hit_area(self) -> None:
        self.prepareGeometryChange()
        self._rebuild_hit()

    def boundingRect(self) -> QRectF:  # noqa: N802 - Qt API
        return self._hit.boundingRect().united(self._path.boundingRect())

    def shape(self) -> QPainterPath:  # noqa: A003 - Qt API
        return self._hit

    def paint(self, p: QPainter, option: QStyleOptionGraphicsItem, widget: QWidget | None = None) -> None:
        pen = QPen(self._color, 1.6)
        pen.setCosmetic(True)  # konstante Bildschirmbreite, unabhängig vom Zoom
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(pen)
        if self._kind == "text":
            fill = QColor(self._color)
            fill.setAlpha(170)
            p.setBrush(QBrush(fill))
        else:
            p.setBrush(Qt.NoBrush)
        p.drawPath(self._path)


class SelectionOverlay(QGraphicsItem):
    """Rahmen mit acht Skalier-Griffen um die aktuelle Auswahl."""

    def __init__(self) -> None:
        super().__init__()
        self.setZValue(1e9)
        self._rect: Rect | None = None
        self._px = 1.0  # mm pro Bildschirmpixel, von der View gesetzt
        self.setAcceptedMouseButtons(Qt.NoButton)

    def set_scale(self, mm_per_px: float) -> None:
        self.prepareGeometryChange()
        self._px = mm_per_px
        self.update()

    def set_rect(self, r: Rect | None) -> None:
        self.prepareGeometryChange()
        self._rect = r
        self.setVisible(r is not None)
        self.update()

    @property
    def rect(self) -> Rect | None:
        return self._rect

    def handle_points(self) -> list[QPointF]:
        if self._rect is None:
            return []
        r = self._rect
        return [QPointF(r.x + fx * r.w, r.y + fy * r.h) for fx, fy in HANDLE_FRACTIONS]

    def handle_at(self, pos: QPointF) -> int | None:
        """Index des nächstgelegenen Griffs unter ``pos`` (Szene-mm) oder None.

        Bei kleinen Objekten überlappen sich die Fangbereiche; dann gewinnt
        der nächste Griff, Ecken vor Kanten.
        """
        tol = HANDLE_PX * self._px
        best: tuple[float, int, int] | None = None
        for i, hp in enumerate(self.handle_points()):
            dx, dy = abs(hp.x() - pos.x()), abs(hp.y() - pos.y())
            if dx <= tol and dy <= tol:
                cand = (max(dx, dy), i % 2, i)  # gerade Indizes = Ecken
                if best is None or cand < best:
                    best = cand
        return None if best is None else best[2]

    def boundingRect(self) -> QRectF:  # noqa: N802
        if self._rect is None:
            return QRectF()
        m = HANDLE_PX * self._px * 1.5
        r = self._rect
        return QRectF(r.x, r.y, r.w, r.h).adjusted(-m, -m, m, m)

    def paint(self, p: QPainter, option: QStyleOptionGraphicsItem, widget: QWidget | None = None) -> None:
        if self._rect is None:
            return
        r = self._rect
        pen = QPen(QColor(theme.SELECTION), 1.0, Qt.DashLine)
        pen.setCosmetic(True)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawRect(QRectF(r.x, r.y, r.w, r.h))
        s = HANDLE_PX * self._px
        pen = QPen(QColor(theme.SELECTION), 1.2)
        pen.setCosmetic(True)
        p.setPen(pen)
        p.setBrush(QColor(theme.BG))
        for hp in self.handle_points():
            p.drawRect(QRectF(hp.x() - s / 2, hp.y() - s / 2, s, s))
