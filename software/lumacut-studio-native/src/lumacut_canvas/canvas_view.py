"""Szene, Ansicht (Zoom/Pan, Raster) und Lineale der Arbeitsfläche.

Szeneneinheit = 1 mm. Die Arbeitsfläche liegt bei 0,0 … 360,340; außen
herum bleibt etwas Rand zum Verschieben der Ansicht. Die Safezone wird hier
absichtlich nicht gezeichnet.
"""

from __future__ import annotations

import logging
import math

from PySide6.QtCore import QEvent, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (QColor, QFont, QImage, QMouseEvent, QPainter, QPaintEvent, QPen,
                           QWheelEvent)
from PySide6.QtWidgets import QGraphicsScene, QGraphicsView, QWidget

from . import theme
from .items import SelectionOverlay, ShapeItem
from .model import Document
from .workarea import WORK_HEIGHT_MM, WORK_WIDTH_MM

_log = logging.getLogger(__name__)

SCENE_MARGIN_MM = 60.0
MIN_SCALE = 0.4    # px/mm
MAX_SCALE = 60.0   # px/mm
NICE_STEPS = (0.5, 1, 2, 5, 10, 20, 50, 100, 200)


def nice_step(px_per_mm: float, min_px: float) -> float:
    """Kleinster "runder" mm-Abstand, der mindestens ``min_px`` Pixel breit ist."""
    for s in NICE_STEPS:
        if s * px_per_mm >= min_px:
            return s
    return NICE_STEPS[-1]


class CanvasScene(QGraphicsScene):
    """Hält zu jedem Modellobjekt ein :class:`ShapeItem` aktuell."""

    def __init__(self, doc: Document) -> None:
        super().__init__()
        self.doc = doc
        self.setSceneRect(-SCENE_MARGIN_MM, -SCENE_MARGIN_MM,
                          WORK_WIDTH_MM + 2 * SCENE_MARGIN_MM, WORK_HEIGHT_MM + 2 * SCENE_MARGIN_MM)
        self.items_by_id: dict[str, ShapeItem] = {}
        self.overlay = SelectionOverlay()
        self.addItem(self.overlay)
        self.overlay.set_rect(None)
        self.sync()

    def set_document(self, doc: Document) -> None:
        for item in self.items_by_id.values():
            self.removeItem(item)
        self.items_by_id.clear()
        self.doc = doc
        self.sync()

    def sync(self) -> None:
        """Items mit dem Modell abgleichen (anlegen, aktualisieren, entfernen, Z-Ordnung)."""
        doc = self.doc
        layer_rank = {l.id: (len(doc.layers) - 1 - i) for i, l in enumerate(doc.layers)}
        alive: set[str] = set()
        for idx, s in enumerate(doc.shapes):
            layer = doc.layer(s.layer_id)
            item = self.items_by_id.get(s.id)
            if item is None:
                item = ShapeItem(s, layer)
                self.items_by_id[s.id] = item
                self.addItem(item)
            else:
                item.update_from(s, layer)
            # Ebenenreihenfolge zuerst, dann Reihenfolge innerhalb der Ebene.
            item.setZValue(layer_rank[s.layer_id] * 1_000_000 + idx)
            alive.add(s.id)
        for sid in [k for k in self.items_by_id if k not in alive]:
            self.removeItem(self.items_by_id.pop(sid))

    def editable_shape_at(self, pos: QPointF) -> str | None:
        """Oberstes anklickbares Objekt (sichtbare, ungesperrte Ebene) an ``pos``."""
        for item in self.items(pos, Qt.IntersectsItemShape, Qt.DescendingOrder):
            if isinstance(item, ShapeItem) and self.doc.has_shape(item.shape_id) \
                    and self.doc.is_editable(item.shape_id):
                return item.shape_id
        return None


class CanvasView(QGraphicsView):
    """Zoom (Mausrad), Pan (mittlere Maustaste oder Leertaste+Ziehen), Raster."""

    cursorMoved = Signal(float, float)  # mm  # noqa: N815
    viewChanged = Signal()  # noqa: N815
    leftCanvas = Signal()  # noqa: N815

    def __init__(self, scene: CanvasScene, parent: QWidget | None = None) -> None:
        super().__init__(scene, parent)
        self.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
        self.setViewportUpdateMode(QGraphicsView.SmartViewportUpdate)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorViewCenter)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.show_grid = True
        self.backdrop: QImage | None = None
        self._overlays: dict[str, tuple[float, int, object]] = {}  # key -> (z, Reihenfolge, Overlay)
        self._overlay_seq = 0
        self.tool_handler = None  # wird vom Editor gesetzt (tools.ToolController)
        self._pan_start: QPointF | None = None
        self._space_down = False
        self._fitted_once = False
        self.horizontalScrollBar().valueChanged.connect(self.viewChanged)
        self.verticalScrollBar().valueChanged.connect(self.viewChanged)

    # --- Zoom -------------------------------------------------------------
    @property
    def px_per_mm(self) -> float:
        return self.transform().m11()

    def set_zoom(self, px_per_mm: float, anchor: QPointF | None = None) -> None:
        """Zoom to ``px_per_mm`` (clamped); ``anchor`` = viewport point that
        stays fixed (default: view centre). Explicit anchoring instead of
        ``AnchorUnderMouse`` keeps the point under the *event* position fixed
        (wheel/pinch), independent of QCursor."""
        px_per_mm = max(MIN_SCALE, min(MAX_SCALE, px_per_mm))
        f = px_per_mm / self.px_per_mm
        if abs(f - 1.0) < 1e-9:
            return
        vp = self.viewport().rect()
        if anchor is None:
            anchor = QPointF(vp.width() / 2.0, vp.height() / 2.0)
        before = self.mapToScene(anchor.toPoint())
        self.setTransformationAnchor(QGraphicsView.NoAnchor)
        self.scale(f, f)
        after = self.mapFromScene(before)
        hb, vb = self.horizontalScrollBar(), self.verticalScrollBar()
        hb.setValue(hb.value() + round(after.x() - anchor.x()))
        vb.setValue(vb.value() + round(after.y() - anchor.y()))
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self._after_zoom()

    def zoom_by(self, factor: float, anchor: QPointF | None = None) -> None:
        self.set_zoom(self.px_per_mm * factor, anchor)

    def fit_work_area(self) -> None:
        self.fitInView(QRectF(-8, -8, WORK_WIDTH_MM + 16, WORK_HEIGHT_MM + 16), Qt.KeepAspectRatio)
        self._after_zoom()

    def fit_rect(self, rect: QRectF, margin_mm: float = 5.0) -> None:
        """Fit a scene rectangle (mm), e.g. the selection; respects MAX_SCALE."""
        if rect.isNull() or rect.width() < 0 or rect.height() < 0:
            return self.fit_work_area()
        r = rect.adjusted(-margin_mm, -margin_mm, margin_mm, margin_mm)
        self.fitInView(r, Qt.KeepAspectRatio)
        if self.px_per_mm > MAX_SCALE or self.px_per_mm < MIN_SCALE:
            self.set_zoom(self.px_per_mm)  # clamps
            self.centerOn(r.center())
        self._after_zoom()

    def _after_zoom(self) -> None:
        mm_per_px = 1.0 / self.px_per_mm
        scene: CanvasScene = self.scene()  # type: ignore[assignment]
        scene.overlay.set_scale(mm_per_px)
        ShapeItem.hit_tolerance_mm = 5.0 * mm_per_px
        for item in scene.items_by_id.values():
            item.refresh_hit_area()
        self.viewChanged.emit()

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        if not self._fitted_once:
            self._fitted_once = True
            self.fit_work_area()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self.viewChanged.emit()

    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802
        # Wheel (and Ctrl+wheel) zooms at the pointer like LightBurn; trackpads
        # without angle delta report pixel deltas.
        steps = event.angleDelta().y() / 120.0 or event.pixelDelta().y() / 60.0
        if steps:
            self.zoom_by(1.15 ** max(-4.0, min(4.0, steps)), event.position())
        event.accept()

    def viewportEvent(self, event) -> bool:  # noqa: N802
        # Trackpad pinch (macOS/Windows precision touchpads) zooms at the fingers.
        if event.type() == QEvent.NativeGesture and \
                event.gestureType() == Qt.NativeGestureType.ZoomNativeGesture:
            self.zoom_by(1.0 + event.value(), event.position())
            event.accept()
            return True
        return super().viewportEvent(event)

    # --- Maus -------------------------------------------------------------
    def _scene_pos(self, event: QMouseEvent) -> QPointF:
        return self.mapToScene(event.position().toPoint())

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MiddleButton or (event.button() == Qt.LeftButton and self._space_down):
            self._pan_start = event.position()
            self.viewport().setCursor(Qt.ClosedHandCursor)
            return
        if event.button() == Qt.LeftButton and self.tool_handler is not None:
            self.tool_handler.press(self._scene_pos(event), event.modifiers())
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        pos = self._scene_pos(event)
        self.cursorMoved.emit(pos.x(), pos.y())
        if self._pan_start is not None:
            d = event.position() - self._pan_start
            self._pan_start = event.position()
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - int(d.x()))
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - int(d.y()))
            return
        if self.tool_handler is not None:
            self.tool_handler.move(pos, event.modifiers(), bool(event.buttons() & Qt.LeftButton))
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._pan_start is not None and event.button() in (Qt.MiddleButton, Qt.LeftButton):
            self._pan_start = None
            self.viewport().unsetCursor()
            if self.tool_handler is not None:
                self.tool_handler.update_cursor()
            return
        if event.button() == Qt.LeftButton and self.tool_handler is not None:
            self.tool_handler.release(self._scene_pos(event), event.modifiers())
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton and self.tool_handler is not None:
            self.tool_handler.double_click(self._scene_pos(event))
            return
        super().mouseDoubleClickEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        super().leaveEvent(event)
        self.leftCanvas.emit()

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key_Space and not event.isAutoRepeat():
            self._space_down = True
            self.viewport().setCursor(Qt.OpenHandCursor)
            return
        if self.tool_handler is not None and self.tool_handler.key_press(event):
            return
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key_Space and not event.isAutoRepeat():
            self._space_down = False
            if self.tool_handler is not None:
                self.tool_handler.update_cursor()
            return
        super().keyReleaseEvent(event)

    # --- Hintergrund: Arbeitsfläche + Raster ------------------------------
    def drawBackground(self, p: QPainter, rect: QRectF) -> None:  # noqa: N802
        p.fillRect(rect, QColor(theme.CANVAS_OUTSIDE))
        work = QRectF(0, 0, WORK_WIDTH_MM, WORK_HEIGHT_MM)
        p.fillRect(work, QColor(theme.CANVAS_WORK))
        if self.backdrop is not None and not self.backdrop.isNull():
            p.drawImage(work, self.backdrop)
        self._paint_overlays(p, work)
        if self.show_grid:
            self._draw_grid(p, rect.intersected(work))
        pen = QPen(QColor(theme.WORK_BORDER), 1.0)
        pen.setCosmetic(True)
        p.setPen(pen)
        p.drawRect(work)

    def _draw_grid(self, p: QPainter, r: QRectF) -> None:
        if r.isEmpty():
            return
        scale = self.px_per_mm
        minor = nice_step(scale, 9)
        major = minor * (5 if minor in (1, 10, 100) else 2 if minor in (5, 50) else 5)
        for step, color in ((minor, theme.GRID_MINOR), (major, theme.GRID_MAJOR)):
            pen = QPen(QColor(color), 1.0)
            pen.setCosmetic(True)
            p.setPen(pen)
            x = math.ceil(r.left() / step) * step
            while x <= r.right():
                p.drawLine(QPointF(x, r.top()), QPointF(x, r.bottom()))
                x += step
            y = math.ceil(r.top() / step) * step
            while y <= r.bottom():
                p.drawLine(QPointF(r.left(), y), QPointF(r.right(), y))
                y += step

    def set_backdrop(self, image: QImage | None) -> None:
        """Hintergrundbild (z. B. zusammengesetzter Kamerascan) über die ganze
        Arbeitsfläche gespannt. Das Bild muss bereits auf 360 × 340 mm entzerrt sein."""
        self.backdrop = image
        self.resetCachedContent()
        self.viewport().update()

    # --- Overlays (Scan-Bilder, Höhenkarten …) unter den Objekten -----------
    def add_overlay(self, key: str, overlay, z: float = 0.0) -> None:
        """Overlay unter ``key`` einhängen (ersetzt ein vorhandenes gleichen Namens)."""
        if not callable(getattr(overlay, "paint", None)):
            raise TypeError("Overlay braucht eine Methode paint(painter, work_rect)")
        self._overlay_seq += 1
        self._overlays[key] = (float(z), self._overlay_seq, overlay)
        self.refresh_overlays()

    def remove_overlay(self, key: str) -> bool:
        found = self._overlays.pop(key, None) is not None
        if found:
            self.refresh_overlays()
        return found

    def overlay(self, key: str):
        entry = self._overlays.get(key)
        return entry[2] if entry else None

    def overlay_keys(self) -> list[str]:
        """Schlüssel in Zeichenreihenfolge (unten zuerst)."""
        return [k for k, _ in sorted(self._overlays.items(), key=lambda kv: kv[1][:2])]

    def refresh_overlays(self) -> None:
        """Nach Änderungen am Overlay-Objekt (Bild, Sichtbarkeit …) neu zeichnen."""
        self.resetCachedContent()
        self.viewport().update()

    def _paint_overlays(self, p: QPainter, work: QRectF) -> None:
        for key in self.overlay_keys():
            ov = self._overlays[key][2]
            if not getattr(ov, "visible", True):
                continue
            p.save()
            p.setClipRect(work)
            p.setOpacity(max(0.0, min(1.0, float(getattr(ov, "opacity", 1.0)))))
            try:
                ov.paint(p, QRectF(work))
            except Exception:  # fremder Code darf das Zeichnen des Canvas nie abbrechen
                _log.exception("Overlay %r konnte nicht gezeichnet werden", key)
            finally:
                p.restore()

    def set_grid_visible(self, on: bool) -> None:
        self.show_grid = on
        self.resetCachedContent()
        self.viewport().update()


class Ruler(QWidget):
    """mm-Lineal oben oder links, folgt Zoom und Pan der View."""

    THICKNESS = 22

    def __init__(self, view: CanvasView, orientation: Qt.Orientation) -> None:
        super().__init__()
        self.setObjectName("Ruler")
        self.view = view
        self.orientation = orientation
        self.cursor_mm: float | None = None
        if orientation == Qt.Horizontal:
            self.setFixedHeight(self.THICKNESS)
        else:
            self.setFixedWidth(self.THICKNESS)
        view.viewChanged.connect(self.update)
        view.cursorMoved.connect(self._on_cursor)
        view.leftCanvas.connect(self._on_leave)

    def _on_cursor(self, x: float, y: float) -> None:
        self.cursor_mm = x if self.orientation == Qt.Horizontal else y
        self.update()

    def _on_leave(self) -> None:
        self.cursor_mm = None
        self.update()

    def _to_px(self, mm: float) -> float:
        if self.orientation == Qt.Horizontal:
            return float(self.view.mapFromScene(QPointF(mm, 0)).x())
        return float(self.view.mapFromScene(QPointF(0, mm)).y())

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(theme.PANEL))
        horiz = self.orientation == Qt.Horizontal
        length = self.width() if horiz else self.height()
        limit = WORK_WIDTH_MM if horiz else WORK_HEIGHT_MM
        scale = self.view.px_per_mm
        major = nice_step(scale, 60)
        minor = major / (5 if major not in (2, 20, 200) else 4)
        # Bereich der Arbeitsfläche dezent hervorheben.
        a, b = self._to_px(0), self._to_px(limit)
        band = QColor(theme.SURFACE_2)
        if horiz:
            p.fillRect(QRectF(a, 0, b - a, self.height()), band)
        else:
            p.fillRect(QRectF(0, a, self.width(), b - a), band)
        font = QFont(self.font())
        font.setPointSizeF(7.5)
        p.setFont(font)
        t = self.THICKNESS
        start = math.floor(-SCENE_MARGIN_MM / minor) * minor
        v = start
        while v <= limit + SCENE_MARGIN_MM:
            px = self._to_px(v)
            if 0 <= px <= length:
                is_major = abs((v / major) - round(v / major)) < 1e-6
                inside = 0 <= v <= limit
                p.setPen(QColor(theme.TEXT_DIM if inside else "#3c4656"))
                tick = t * (0.45 if is_major else 0.2)
                if horiz:
                    p.drawLine(QPointF(px, t - tick), QPointF(px, t))
                    if is_major:
                        p.drawText(QPointF(px + 2, 9), f"{v:g}")
                else:
                    p.drawLine(QPointF(t - tick, px), QPointF(t, px))
                    if is_major:
                        p.save()
                        p.translate(9, px + 2)
                        p.rotate(-90)
                        p.drawText(QPointF(-24, 0), f"{v:g}")
                        p.restore()
            v += minor
        if self.cursor_mm is not None:
            px = self._to_px(self.cursor_mm)
            p.setPen(QPen(QColor(theme.ACCENT), 1))
            if horiz:
                p.drawLine(QPointF(px, 0), QPointF(px, t))
            else:
                p.drawLine(QPointF(0, px), QPointF(t, px))
        p.setPen(QColor(theme.BORDER))
        if horiz:
            p.drawLine(0, t - 1, self.width(), t - 1)
        else:
            p.drawLine(t - 1, 0, t - 1, self.height())
        p.end()
