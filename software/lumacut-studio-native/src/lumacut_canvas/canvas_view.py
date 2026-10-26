"""Szene, Ansicht (Zoom/Pan, Raster) und Lineale der Arbeitsfläche.

Szeneneinheit = 1 mm. Die Arbeitsfläche liegt bei 0,0 … 360,340; außen
herum bleibt etwas Rand zum Verschieben der Ansicht. Die Safezone wird hier
absichtlich nicht gezeichnet.
"""

from __future__ import annotations

import logging
import math
import time

from PySide6.QtCore import QEvent, QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import (QColor, QEventPoint, QFont, QImage, QMouseEvent, QPainter, QPaintEvent,
                           QPen, QWheelEvent)
from PySide6.QtWidgets import (QApplication, QGraphicsScene, QGraphicsView, QHBoxLayout, QToolButton,
                               QWidget)

from . import icons, theme, touch
from .items import SelectionOverlay, ShapeItem
from .model import Document
from .workarea import WORK_HEIGHT_MM, WORK_WIDTH_MM

_log = logging.getLogger(__name__)

SCENE_MARGIN_MM = 60.0
MIN_SCALE = 0.4    # px/mm
MAX_SCALE = 60.0   # px/mm
NICE_STEPS = (0.5, 1, 2, 5, 10, 20, 50, 100, 200)
PX_PER_MM_100 = 96 / 25.4  # 100 % = physische Größe bei logischen 96 dpi
TAP_SLOP_PX = 10.0         # so weit darf ein Finger wandern, bevor aus Tippen Ziehen wird
DOUBLE_TAP_PX = 24.0       # zwei Taps so nah beieinander = Doppeltipp
TOUCH_MOUSE_GUARD_S = 0.6  # so lange nach Touch werden "Maus"-Ereignisse aus Touch ignoriert


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
        """Anklickbares Objekt (sichtbare, ungesperrte Ebene) an ``pos``.

        Fangbereich: ``ShapeItem.hit_tolerance_mm`` (Bildschirm-Pixel des
        Touch-Modus, von der View in mm umgerechnet). Liegen mehrere Objekte im
        Fangbereich, gewinnt
          1. ein Treffer auf dem Umriss (bzw. im Bild/Text) vor einem Treffer
             nur im Inneren einer Kontur,
          2. dann das kleinere Objekt (damit eine dünne Linie oder ein kleines
             Teil auf/unter einer großen Fläche erreichbar bleibt),
          3. dann das oberste.
        """
        best: tuple | None = None
        best_id: str | None = None
        for z, item in enumerate(self.items(pos, Qt.IntersectsItemShape, Qt.DescendingOrder)):
            if not (isinstance(item, ShapeItem) and self.doc.has_shape(item.shape_id)
                    and self.doc.is_editable(item.shape_id)):
                continue
            local = item.mapFromScene(pos)
            key = (0 if item.outline_hit(local) else 1, item.hit_area(), z)
            if best is None or key < best:
                best, best_id = key, item.shape_id
        return best_id


_TOUCH_EVENTS = (QEvent.TouchBegin, QEvent.TouchUpdate, QEvent.TouchEnd, QEvent.TouchCancel)


class ZoomButtons(QWidget):
    """Große Zoom-Knöpfe im Canvas (unten rechts), für Finger gedacht:
    Verkleinern, Vergrößern, Einpassen, 100 %."""

    def __init__(self, view: "CanvasView") -> None:
        super().__init__(view)
        self.setObjectName("ZoomButtons")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(
            f"#ZoomButtons {{ background: {theme.PANEL}; border: 1px solid {theme.BORDER}; border-radius: 10px; }}"
            f"#ZoomButtons QToolButton {{ background: transparent; border: 1px solid transparent;"
            f" border-radius: 8px; color: {theme.TEXT}; font-weight: 600; }}"
            f"#ZoomButtons QToolButton:pressed {{ background: #173a33; border-color: {theme.ACCENT}; }}")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(6)
        self.buttons: dict[str, QToolButton] = {}
        for name, icon, text, tip, slot in (
                ("zoom_out", "zoom_out", "", "Verkleinern", lambda: view.zoom_by(0.8)),
                ("zoom_in", "zoom_in", "", "Vergrößern", lambda: view.zoom_by(1.25)),
                ("fit", "fit", "", "Einpassen", view.fit_work_area),
                ("zoom_100", None, "100%", "100 % (physische Größe)", lambda: view.set_zoom(PX_PER_MM_100))):
            b = QToolButton(self)
            b.setObjectName(f"Zoom_{name}")
            b.setToolTip(tip)
            b.setFocusPolicy(Qt.NoFocus)
            if icon:
                b.setIcon(icons.icon(icon))
            else:
                b.setText(text)
            b.clicked.connect(slot)
            lay.addWidget(b)
            self.buttons[name] = b
        self.set_button_size(touch.MOUSE.zoom_button_px)

    def set_button_size(self, px: int) -> None:
        for b in self.buttons.values():
            b.setFixedSize(px, px)
            b.setIconSize(QSize(int(px * 0.6), int(px * 0.6)))
        self.adjustSize()


class CanvasView(QGraphicsView):
    """Zoom (Mausrad), Pan (mittlere Maustaste oder Leertaste+Ziehen), Raster."""

    cursorMoved = Signal(float, float)  # mm  # noqa: N815
    viewChanged = Signal()  # noqa: N815
    leftCanvas = Signal()  # noqa: N815
    touchDetected = Signal()  # erste echte Touchscreen-Eingabe  # noqa: N815

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
        # Liefert die Zoom-Mitte für das Mausrad (Auswahl-Mitte in mm) oder None
        # (= am Mauszeiger zoomen). Wird vom Editor gesetzt.
        self.zoom_anchor_provider = None
        self._wheel_anchor: tuple[tuple[float, float], QPointF] | None = None
        self._pan_start: QPointF | None = None
        self._space_down = False
        self._fitted_once = False
        self.touch_mode = False
        self.metrics: touch.TouchMetrics = touch.MOUSE
        self._touch_seen = False
        self._touch: dict | None = None  # laufende Touch-Folge (siehe _touch_event)
        self._touch_end_t = -1e9           # Zeitpunkt der letzten Touch-Folge (monotonic)
        self._last_tap: tuple[float, QPointF] | None = None
        self.viewport().setAttribute(Qt.WA_AcceptTouchEvents, True)
        self.zoom_buttons = ZoomButtons(self)
        self.zoom_buttons.setVisible(False)  # nur im Touch-Modus; mit Maus gibt es die Aktionsleiste
        self.horizontalScrollBar().valueChanged.connect(self.viewChanged)
        self.verticalScrollBar().valueChanged.connect(self.viewChanged)

    # --- Touch-Modus ------------------------------------------------------
    def set_touch_mode(self, on: bool) -> None:
        """Anfasser, Fangbereiche und Zoom-Knöpfe auf Finger- bzw. Mausgröße."""
        self.touch_mode = bool(on)
        self.metrics = touch.metrics(self.touch_mode)
        scene: CanvasScene = self.scene()  # type: ignore[assignment]
        scene.overlay.set_metrics(self.metrics)
        self.zoom_buttons.set_button_size(self.metrics.zoom_button_px)
        self.zoom_buttons.setVisible(self.touch_mode)
        self._place_zoom_buttons()
        self._after_zoom()

    def _place_zoom_buttons(self) -> None:
        zb = self.zoom_buttons
        vp = self.viewport().geometry()
        zb.move(vp.right() - zb.width() - 12, vp.bottom() - zb.height() - 12)
        zb.raise_()

    # --- Zoom -------------------------------------------------------------
    @property
    def px_per_mm(self) -> float:
        return self.transform().m11()

    def set_zoom(self, px_per_mm: float, anchor: QPointF | None = None,
                 scene_pt: QPointF | None = None) -> None:
        """Zoom to ``px_per_mm`` (clamped); ``anchor`` = viewport point that
        stays fixed (default: view centre). Explicit anchoring instead of
        ``AnchorUnderMouse`` keeps the point under the *event* position fixed
        (wheel/pinch), independent of QCursor. ``scene_pt`` (mm): diesen
        Szenenpunkt an ``anchor`` festhalten (Standard: der Punkt unter ``anchor``)."""
        px_per_mm = max(MIN_SCALE, min(MAX_SCALE, px_per_mm))
        f = px_per_mm / self.px_per_mm
        if abs(f - 1.0) < 1e-9:
            return
        vp = self.viewport().rect()
        if anchor is None:
            anchor = QPointF(vp.width() / 2.0, vp.height() / 2.0)
        before = QPointF(scene_pt) if scene_pt is not None else \
            self.viewportTransform().inverted()[0].map(QPointF(anchor))
        self.setTransformationAnchor(QGraphicsView.NoAnchor)
        self.scale(f, f)
        self._pin(before, anchor)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self._after_zoom()
        self._pin(before, anchor)  # _after_zoom kann die Ansicht minimal verschieben

    def _pin(self, scene_pt: QPointF, anchor: QPointF) -> None:
        """Scrollleisten so stellen, dass ``scene_pt`` bei ``anchor`` (Viewport) liegt."""
        hb, vb = self.horizontalScrollBar(), self.verticalScrollBar()
        for _ in range(3):  # Scrollwerte sind ganzzahlig -> ggf. nachkorrigieren
            after = self.viewportTransform().map(scene_pt)
            dx, dy = round(after.x() - anchor.x()), round(after.y() - anchor.y())
            if not dx and not dy:
                break
            hb.setValue(hb.value() + dx)
            vb.setValue(vb.value() + dy)

    def zoom_by(self, factor: float, anchor: QPointF | None = None,
                scene_pt: QPointF | None = None) -> None:
        self.set_zoom(self.px_per_mm * factor, anchor, scene_pt)

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
        ShapeItem.hit_tolerance_mm = self.metrics.hit_tolerance_px * mm_per_px
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
        self._place_zoom_buttons()
        self.viewChanged.emit()

    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802
        # Wheel (and Ctrl+wheel) zooms at the pointer like LightBurn; trackpads
        # without angle delta report pixel deltas.
        steps = event.angleDelta().y() / 120.0 or event.pixelDelta().y() / 60.0
        if steps:
            self.zoom_wheel(1.15 ** max(-4.0, min(4.0, steps)), event.position())
        event.accept()

    def zoom_wheel(self, factor: float, pos: QPointF) -> None:
        """Mausrad-Zoom mit Ankerwahl.

        * Keine Auswahl: der Punkt unter dem Mauszeiger bleibt stehen.
        * Mit Auswahl (``zoom_anchor_provider`` liefert deren Mitte in mm): die
          Mitte der Auswahl bleibt an ihrer Bildschirmposition. Liegt sie
          außerhalb des Sichtbereichs, wird nach dem Zoomen auf sie zentriert –
          man zoomt also immer *zur* Auswahl hin.
        """
        center = self.zoom_anchor_provider() if self.zoom_anchor_provider else None
        if center is None:
            self.zoom_by(factor, pos)
            return
        now = self._viewport_pos(center)
        last = self._wheel_anchor
        # Aufeinanderfolgende Radschritte nutzen denselben Zielpunkt, sonst
        # summieren sich die ganzzahligen Scroll-Rundungen (je ≤ 0,5 px) auf.
        if last and last[0] == (center.x(), center.y()) and \
                abs(last[1].x() - now.x()) <= 2 and abs(last[1].y() - now.y()) <= 2:
            now = last[1]
        if self.viewport().rect().contains(now.toPoint()):
            self.zoom_by(factor, now, center)
            self._wheel_anchor = ((center.x(), center.y()), QPointF(now))
        else:
            self.zoom_by(factor)
            self.centerOn(center)
            self._wheel_anchor = None
            self.viewChanged.emit()

    def _viewport_pos(self, scene_pt: QPointF) -> QPointF:
        """Exakte (nicht gerundete) Viewport-Position eines Szenenpunkts."""
        return self.viewportTransform().map(scene_pt)

    def viewportEvent(self, event) -> bool:  # noqa: N802
        # Trackpad pinch (macOS/Windows precision touchpads) zooms at the fingers.
        if event.type() == QEvent.NativeGesture and \
                event.gestureType() == Qt.NativeGestureType.ZoomNativeGesture:
            self.zoom_by(1.0 + event.value(), event.position())
            event.accept()
            return True
        if event.type() in _TOUCH_EVENTS and self._touch_event(event):
            return True
        return super().viewportEvent(event)

    # --- Touch ------------------------------------------------------------
    def pinch_to(self, px_per_mm: float, anchor: QPointF, scene_pt: QPointF) -> None:
        """Zoom auf ``px_per_mm`` (begrenzt auf MIN/MAX_SCALE) und ``scene_pt``
        (mm) an die Viewport-Position ``anchor`` legen. Zoomen und Verschieben
        in einem Schritt: so folgt die Zeichnung beim Pinch den Fingern."""
        px_per_mm = max(MIN_SCALE, min(MAX_SCALE, px_per_mm))
        f = px_per_mm / self.px_per_mm
        scaled = abs(f - 1.0) > 1e-9
        if scaled:
            self.setTransformationAnchor(QGraphicsView.NoAnchor)
            self.scale(f, f)
            self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self._pin(scene_pt, anchor)
        if scaled:
            self._after_zoom()
            self._pin(scene_pt, anchor)

    def _touch_points(self, event) -> list[tuple[int, QPointF]]:
        """Aktive Finger (id, Viewport-Position), über die globale Position
        abgebildet – funktioniert auch für selbst erzeugte Ereignisse."""
        vp = self.viewport()
        return [(p.id(), vp.mapFromGlobal(p.globalPosition()))
                for p in event.points() if p.state() != QEventPoint.State.Released]

    def _touch_event(self, event) -> bool:
        """Touchscreen-Folge auswerten.

        * Ein Finger auf leerem Hintergrund mit dem Auswahl-Werkzeug (kein
          Objekt, kein Griff): Ansicht verschieben. Tippen bleibt ein Klick
          (Auswahl aufheben); Rahmenauswahl geht weiter mit Maus/Stift.
        * Ein Finger sonst: tippen/ziehen wie mit der linken Maustaste. Der Druck
          wird erst weitergegeben, wenn der Finger ``TAP_SLOP_PX`` wandert
          oder abhebt – kommt vorher ein zweiter Finger dazu, passiert am
          Objekt gar nichts.
        * Zwei Finger: Pinch-Zoom um die Fingermitte, gleichzeitig Verschieben
          mit der Mitte. Ein schon laufender Zug wird verworfen
          (:meth:`ToolController.abort_drag`), damit nichts versehentlich
          verschoben wird. Bis alle Finger oben sind, bleibt es beim Zoomen.

        * Doppeltipp = Doppelklick (Text bearbeiten, Polygon schließen …).

        Touchpad-Ereignisse und aus Mausereignissen synthetisierte Touch-Events
        werden nicht ausgewertet (False -> Qt-Standardbehandlung). Weil die
        Touch-Events angenommen werden, erzeugt Qt keine Ersatz-Mausereignisse;
        solche vom System werden zusätzlich verworfen (:meth:`_ignore_mouse`).
        """
        if not touch.is_touchscreen_event(event):
            return False
        event.accept()
        if not self._touch_seen:
            self._touch_seen = True
            self.touchDetected.emit()
        et = event.type()
        st = self._touch
        if et == QEvent.TouchCancel:
            if st and st["mode"] == "tool" and self.tool_handler is not None:
                self.tool_handler.abort_drag()
            self._touch = None
            self._touch_end_t = time.monotonic()
            return True
        pts = self._touch_points(event)
        if st is None:
            if not pts:
                return True
            start = QPointF(pts[0][1])
            mode = "pan" if self._empty_background(start) else "pending"
            st = self._touch = {"mode": mode, "start": start, "last": QPointF(start), "moved": False}
        if len(pts) >= 2 and st["mode"] != "pinch":
            if st["mode"] == "tool" and self.tool_handler is not None:
                self.tool_handler.abort_drag()
            self._start_pinch(st, pts)
        elif st["mode"] == "pinch":
            self._update_pinch(st, pts)
        elif pts:
            pos = pts[0][1]
            st["last"] = QPointF(pos)
            self._touch_single_move(st, pos)
        if et == QEvent.TouchEnd or not pts:
            self._touch_end(st)
            self._touch = None
            self._touch_end_t = time.monotonic()
        return True

    def _empty_background(self, vp_pos: QPointF) -> bool:
        """Startet ein Finger hier, verschiebt er die Ansicht statt aufzuziehen."""
        th = self.tool_handler
        if th is None or getattr(th, "roi_pending", False) or getattr(th, "_mode", None) is not None:
            return False
        from .tools import Tool  # zirkulären Import beim Laden vermeiden
        if th.tool != Tool.SELECT:
            return False
        pos = self.mapToScene(vp_pos.toPoint())
        scene: CanvasScene = self.scene()  # type: ignore[assignment]
        if scene.overlay.isVisible() and scene.overlay.handle_at(pos) is not None:
            return False
        return scene.editable_shape_at(pos) is None

    def _ignore_mouse(self, event: QMouseEvent) -> bool:
        """Mausereignis aus einer Touch-Eingabe, die schon als Touch behandelt
        wurde (oder gerade läuft) -> nicht ein zweites Mal auswerten."""
        if not touch.is_mouse_from_touch(event):
            return False
        return self._touch is not None or time.monotonic() - self._touch_end_t < TOUCH_MOUSE_GUARD_S

    def _start_pinch(self, st: dict, pts: list[tuple[int, QPointF]]) -> None:
        (i0, a), (i1, b) = pts[0], pts[1]
        st.update(mode="pinch", ids=(i0, i1), dist0=max(1.0, math.hypot(b.x() - a.x(), b.y() - a.y())),
                  scale0=self.px_per_mm)
        c = (a + b) / 2
        st["scene0"] = self.viewportTransform().inverted()[0].map(c)

    def _update_pinch(self, st: dict, pts: list[tuple[int, QPointF]]) -> None:
        by_id = dict(pts)
        if len(pts) < 2:
            return  # ein Finger ist schon oben: nichts mehr tun, bis alle oben sind
        if not all(i in by_id for i in st["ids"]):
            self._start_pinch(st, pts)  # anderer Finger übernimmt: neu ansetzen
            return
        a, b = by_id[st["ids"][0]], by_id[st["ids"][1]]
        d = max(1.0, math.hypot(b.x() - a.x(), b.y() - a.y()))
        self.pinch_to(st["scale0"] * d / st["dist0"], (a + b) / 2, st["scene0"])

    def _touch_single_move(self, st: dict, pos: QPointF) -> None:
        if st["mode"] == "pan":
            d0 = pos - st["start"]
            if not st["moved"] and math.hypot(d0.x(), d0.y()) < TAP_SLOP_PX:
                return
            prev = st.get("pan_last", st["start"])
            d = pos - prev
            st["moved"] = True
            hb, vb = self.horizontalScrollBar(), self.verticalScrollBar()
            # Ganzzahlige Scrollwerte: Rest mitnehmen, damit langsames Ziehen nicht hängen bleibt.
            dx, dy = round(d.x()), round(d.y())
            if dx or dy:
                hb.setValue(hb.value() - dx)
                vb.setValue(vb.value() - dy)
                st["pan_last"] = prev + QPointF(dx, dy)
            return
        if st["mode"] == "pending":
            d = pos - st["start"]
            if math.hypot(d.x(), d.y()) < TAP_SLOP_PX:
                return
            st["mode"] = "tool"
            if self.tool_handler is not None:
                self.tool_handler.press(self.mapToScene(st["start"].toPoint()), Qt.NoModifier)
        if st["mode"] == "tool" and self.tool_handler is not None:
            scene_pos = self.mapToScene(pos.toPoint())
            self.cursorMoved.emit(scene_pos.x(), scene_pos.y())
            self.tool_handler.move(scene_pos, Qt.NoModifier, True)

    def _touch_end(self, st: dict) -> None:
        th = self.tool_handler
        tap = st["mode"] == "pending" or (st["mode"] == "pan" and not st["moved"])
        if th is None or not (tap or st["mode"] == "tool"):
            return
        start = self.mapToScene(st["start"].toPoint())
        if tap:  # Tippen = Klick an der Startposition
            th.press(start, Qt.NoModifier)
            th.release(start, Qt.NoModifier)
            now, last = time.monotonic(), self._last_tap
            gap = (st["start"] - last[1]) if last else QPointF()
            if last and now - last[0] <= QApplication.doubleClickInterval() / 1000.0 and \
                    math.hypot(gap.x(), gap.y()) <= DOUBLE_TAP_PX:
                self._last_tap = None
                th.double_click(start)
            else:
                self._last_tap = (now, QPointF(st["start"]))
            return
        self._last_tap = None
        th.release(self.mapToScene(st["last"].toPoint()), Qt.NoModifier)

    # --- Maus -------------------------------------------------------------
    def _scene_pos(self, event: QMouseEvent) -> QPointF:
        return self.mapToScene(event.position().toPoint())

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._ignore_mouse(event):
            event.accept()
            return
        if event.button() == Qt.MiddleButton or (event.button() == Qt.LeftButton and self._space_down):
            self._pan_start = event.position()
            self.viewport().setCursor(Qt.ClosedHandCursor)
            return
        if event.button() == Qt.LeftButton and self.tool_handler is not None:
            self.tool_handler.press(self._scene_pos(event), event.modifiers())
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._ignore_mouse(event):
            event.accept()
            return
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
        if self._ignore_mouse(event):
            event.accept()
            return
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
        if self._ignore_mouse(event):
            event.accept()
            return
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
