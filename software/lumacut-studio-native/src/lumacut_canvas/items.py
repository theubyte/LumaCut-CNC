"""QGraphicsItems: Darstellung der Modellobjekte und der Auswahl.

Die Items sind reine Ansicht. Sie halten keine eigene Geometrie-Wahrheit,
sondern werden bei jeder Dokumentänderung aus dem Modell aktualisiert
(:meth:`CanvasScene.sync`). Dadurch gibt es genau eine Quelle für Undo,
Speichern und Job-Export.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (QBrush, QColor, QPainter, QPainterPath, QPainterPathStroker, QPen,
                           QTransform)
from PySide6.QtWidgets import QGraphicsItem, QStyleOptionGraphicsItem, QWidget

from . import theme
from .touch import MOUSE, TouchMetrics
from .model import Geometry, Layer, Shape, rotate_point
from .shape_paths import geometry_transform, shape_path
from .workarea import Rect

# Handle-Reihenfolge: 0 oben links, dann im Uhrzeigersinn.
#   0 1 2
#   7   3
#   6 5 4
HANDLE_FRACTIONS = ((0, 0), (0.5, 0), (1, 0), (1, 0.5), (1, 1), (0.5, 1), (0, 1), (0, 0.5))
HANDLE_PX = MOUSE.handle_px  # Mausmodus; Touch-Modus siehe touch.TOUCH
ROTATE_HANDLE = 8          # Index des Dreh-Griffs
ROTATE_HANDLE_OFFSET_PX = MOUSE.rotate_offset_px  # Abstand über der oberen Kante


class ShapeItem(QGraphicsItem):
    """Ein Vektorobjekt, gezeichnet in der Farbe seiner Ebene."""

    # Klicktoleranz in mm; die View rechnet TouchMetrics.hit_tolerance_px
    # (Maus 5 px, Touch 12 px) bei jedem Zoom in mm um.
    hit_tolerance_mm: float = 1.0

    def __init__(self, shape: Shape, layer: Layer) -> None:
        super().__init__()
        self.shape_id = shape.id
        self._path = QPainterPath()
        self._hit = QPainterPath()
        self._outline = QPainterPath()  # Fangbereich direkt am Umriss (Trefferpriorität)
        self._color = QColor(layer.color)
        self._kind = shape.kind
        self._geom = shape.geom.copy()
        self._png: bytes | None = None
        self.update_from(shape, layer)

    def update_from(self, shape: Shape, layer: Layer) -> None:
        self.prepareGeometryChange()
        self._kind = shape.kind
        self._geom = shape.geom.copy()
        self._png = shape.image.png if shape.kind == "image" and shape.image else None
        self._path = shape_path(shape)
        self._color = QColor(layer.color)
        self._rebuild_hit()
        self.setVisible(layer.visible)
        self.setOpacity(0.55 if layer.locked else 1.0)
        self.update()

    def _rebuild_hit(self) -> None:
        stroker = QPainterPathStroker()
        stroker.setWidth(self.hit_tolerance_mm * 2)
        if self._kind in ("line", "path", "polygon"):
            self._hit = stroker.createStroke(self._path)
            self._outline = self._hit
            if self._kind == "polygon":  # Polygone sind wie Flächen auch innen anklickbar
                self._hit = self._hit.united(self._path)
        else:
            # Flächen sind innen anklickbar, auch wenn nur der Umriss gelasert wird.
            # Die Klickfläche dreht mit dem Objekt mit.
            b = self._geom.local_bounds()
            m = self.hit_tolerance_mm
            body = QRectF(b.x, b.y, b.w, b.h)
            r = body.adjusted(-m, -m, m, m)
            hit = QPainterPath()
            if self._kind == "ellipse":
                hit.addEllipse(r)
            else:
                hit.addRect(r)
            xf = geometry_transform(self._geom) if self._geom.rot else None
            self._hit = xf.map(hit) if xf is not None else hit
            if self._kind in ("text", "image"):
                # Sichtbar gefüllt: ein Treffer im Objekt zählt wie ein Umriss-Treffer.
                solid = QPainterPath()
                solid.addRect(body)
                self._outline = xf.map(solid) if xf is not None else solid
            else:
                self._outline = stroker.createStroke(self._path)

    def outline_hit(self, pos: QPointF) -> bool:
        """``pos`` (Item-Koordinaten) liegt im Fangbereich des Umrisses bzw. im
        sichtbar gefüllten Objekt (Text, Bild) – nicht nur im Inneren einer Kontur."""
        return self._outline.contains(pos)

    def hit_area(self) -> float:
        """Größe für die Trefferpriorität (mm², Umriss-Box; Linien ≈ 0)."""
        r = self._path.boundingRect()
        return abs(r.width() * r.height())

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
        if self._png is not None:
            self._paint_image(p)
        p.setPen(pen)
        if self._kind == "text":
            fill = QColor(self._color)
            fill.setAlpha(170)
            p.setBrush(QBrush(fill))
        else:
            p.setBrush(Qt.NoBrush)
        p.drawPath(self._path)


    def _paint_image(self, p: QPainter) -> None:
        from .image_cache import qimage_for
        img = qimage_for(self._png)
        if img.isNull():
            return
        b = self._geom.local_bounds()
        p.save()
        if self._geom.rot:
            p.setTransform(geometry_transform(self._geom), True)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        p.drawImage(QRectF(b.x, b.y, b.w, b.h), img)
        p.restore()


class SelectionOverlay(QGraphicsItem):
    """Rahmen mit acht Skalier-Griffen und einem Dreh-Griff um die Auswahl.

    Der Rahmen kann gedreht sein (ein einzelnes gedrehtes Objekt): ``rect``
    ist dann die ungedrehte Box und ``angle`` ihre Drehung um die Mitte.
    """

    def __init__(self) -> None:
        super().__init__()
        self.setZValue(1e9)
        self._rect: Rect | None = None
        self._angle = 0.0
        self._px = 1.0  # mm pro Bildschirmpixel, von der View gesetzt
        self.metrics: TouchMetrics = MOUSE  # Griffgrößen in Bildschirmpixeln
        self.setAcceptedMouseButtons(Qt.NoButton)

    def set_metrics(self, m: TouchMetrics) -> None:
        """Griffgrößen (Maus/Touch) umschalten; Pixelmaße, also zoomunabhängig."""
        self.prepareGeometryChange()
        self.metrics = m
        self.update()

    def handle_size_mm(self) -> float:
        """Gezeichnete Griffgröße in Szenen-mm (konstant in Bildschirmpixeln)."""
        return self.metrics.handle_px * self._px

    def handle_hit_mm(self) -> float:
        """Halbe Kantenlänge des Fangquadrats eines Griffs in Szenen-mm."""
        return max(self.metrics.handle_hit_px, self.metrics.handle_px / 2) * self._px

    def set_scale(self, mm_per_px: float) -> None:
        self.prepareGeometryChange()
        self._px = mm_per_px
        self.update()

    def set_rect(self, r: Rect | None, angle: float = 0.0) -> None:
        self.prepareGeometryChange()
        self._rect = r
        self._angle = angle if r is not None else 0.0
        self.setVisible(r is not None)
        self.update()

    @property
    def rect(self) -> Rect | None:
        return self._rect

    @property
    def angle(self) -> float:
        return self._angle

    def center(self) -> QPointF:
        r = self._rect
        return QPointF(r.x + r.w / 2, r.y + r.h / 2) if r else QPointF()

    def to_local(self, pos: QPointF) -> QPointF:
        """Szenenpunkt in das ungedrehte Rahmen-Koordinatensystem."""
        if not self._angle or self._rect is None:
            return QPointF(pos)
        c = self.center()
        x, y = rotate_point(pos.x(), pos.y(), c.x(), c.y(), -self._angle)
        return QPointF(x, y)

    def to_scene(self, pos: QPointF) -> QPointF:
        if not self._angle or self._rect is None:
            return QPointF(pos)
        c = self.center()
        x, y = rotate_point(pos.x(), pos.y(), c.x(), c.y(), self._angle)
        return QPointF(x, y)

    def _local_handles(self) -> list[QPointF]:
        if self._rect is None:
            return []
        r = self._rect
        pts = [QPointF(r.x + fx * r.w, r.y + fy * r.h) for fx, fy in HANDLE_FRACTIONS]
        pts.append(QPointF(r.x + r.w / 2, r.y - self.metrics.rotate_offset_px * self._px))
        return pts

    def handle_points(self) -> list[QPointF]:
        """Griffe 0–7 (Skalieren) und 8 (Drehen) in Szene-mm."""
        return [self.to_scene(p) for p in self._local_handles()]

    def handle_at(self, pos: QPointF) -> int | None:
        """Index des nächstgelegenen Griffs unter ``pos`` (Szene-mm) oder None.

        Bei kleinen Objekten überlappen sich die Fangbereiche; dann gewinnt
        der nächste Griff, Ecken vor Kanten. Der Dreh-Griff hat Vorrang.
        """
        tol = self.handle_hit_mm()
        lp = self.to_local(pos)
        best: tuple[float, int, int] | None = None
        for i, hp in enumerate(self._local_handles()):
            dx, dy = abs(hp.x() - lp.x()), abs(hp.y() - lp.y())
            if dx <= tol and dy <= tol:
                rank = -1 if i == ROTATE_HANDLE else i % 2  # gerade Indizes = Ecken
                cand = (max(dx, dy), rank, i)
                if best is None or (cand[1], cand[0]) < (best[1], best[0]):
                    best = cand
        return None if best is None else best[2]

    def boundingRect(self) -> QRectF:  # noqa: N802
        if self._rect is None:
            return QRectF()
        m = (self.metrics.handle_px * 1.5 + self.metrics.rotate_offset_px) * self._px
        r = self._rect
        local = QRectF(r.x, r.y, r.w, r.h).adjusted(-m, -m, m, m)
        return self._transform().mapRect(local)

    def _transform(self) -> QTransform:
        if self._rect is None:
            return QTransform()
        return geometry_transform(Geometry(self._rect.x, self._rect.y, self._rect.w, self._rect.h,
                                           self._angle))

    def paint(self, p: QPainter, option: QStyleOptionGraphicsItem, widget: QWidget | None = None) -> None:
        if self._rect is None:
            return
        r = self._rect
        p.setTransform(self._transform(), True)
        pen = QPen(QColor(theme.SELECTION), 1.0, Qt.DashLine)
        pen.setCosmetic(True)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawRect(QRectF(r.x, r.y, r.w, r.h))
        handles = self._local_handles()
        rot = handles.pop()
        p.drawLine(QPointF(r.x + r.w / 2, r.y), rot)
        s = self.handle_size_mm()
        pen = QPen(QColor(theme.SELECTION), 1.6 if self.metrics.handle_px > HANDLE_PX else 1.2)
        pen.setCosmetic(True)
        p.setPen(pen)
        p.setBrush(QColor(theme.BG))
        for hp in handles:
            p.drawRect(QRectF(hp.x() - s / 2, hp.y() - s / 2, s, s))
        p.setRenderHint(QPainter.Antialiasing)
        p.drawEllipse(rot, s * 0.6, s * 0.6)
