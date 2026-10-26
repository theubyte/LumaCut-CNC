"""Werkzeuge: Auswahl (Verschieben/Skalieren/Drehen/Rahmenauswahl), Rechteck,
Ellipse, Linie, Polygon, Freihand, Text.

Der :class:`ToolController` bekommt Mausereignisse in Szene-mm von der
:class:`~canvas_view.CanvasView`. Während eines Zugs wird das Modell live
geändert (für flüssige Vorschau); beim Loslassen wird der Ausgangszustand
wiederhergestellt und die Änderung als *ein* Undo-Befehl eingestellt.
"""

from __future__ import annotations

import math
from enum import Enum
from typing import TYPE_CHECKING

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QKeyEvent, QPen
from PySide6.QtWidgets import QGraphicsRectItem, QInputDialog

from . import theme
from .commands import AddShapesCommand, SetGeometryCommand, SetTextCommand
from .items import ROTATE_HANDLE
from .model import (Geometry, Shape, keep_inside_together, normalize_angle, rotate_point,
                    simplify_polyline)
from .shape_paths import text_aspect
from .workarea import WORK_HEIGHT_MM, WORK_WIDTH_MM, Rect, clamp_offset

if TYPE_CHECKING:
    from .editor import CanvasEditor

MIN_SIZE_MM = 0.5
DEFAULT_SIZE_MM = 20.0
DEFAULT_TEXT_HEIGHT_MM = 10.0
ROTATE_SNAP_DEG = 15.0


class Tool(str, Enum):
    SELECT = "select"
    RECT = "rect"
    ELLIPSE = "ellipse"
    LINE = "line"
    POLYGON = "polygon"
    FREEHAND = "freehand"
    TEXT = "text"


TOOL_LABELS = {Tool.SELECT: "Auswahl", Tool.RECT: "Rechteck", Tool.ELLIPSE: "Ellipse",
               Tool.LINE: "Linie", Tool.POLYGON: "Polygon", Tool.FREEHAND: "Freihand",
               Tool.TEXT: "Text"}
TOOL_SHORTCUTS = {Tool.SELECT: "V", Tool.RECT: "R", Tool.ELLIPSE: "E", Tool.LINE: "L",
                  Tool.POLYGON: "P", Tool.FREEHAND: "F", Tool.TEXT: "T"}
CLOSE_SNAP_PX = 8.0  # Klick so nah am ersten Punkt schließt das Polygon
# Freihand: Ramer-Douglas-Peucker-Toleranz in mm (Abweichung von der gezeichneten
# Linie) und Mindestabstand roher Mauspunkte.
FREEHAND_TOLERANCE_MM = 0.2
FREEHAND_MIN_STEP_MM = 0.05


def _clamp_point(p: QPointF) -> QPointF:
    return QPointF(min(max(p.x(), 0.0), WORK_WIDTH_MM), min(max(p.y(), 0.0), WORK_HEIGHT_MM))


def resize_bounds(orig: Rect, handle: int, pos: QPointF, proportional: bool,
                  clamp: bool = True) -> Rect:
    """Neue Auswahlbox, wenn Griff ``handle`` nach ``pos`` gezogen wird.

    Die gegenüberliegende Kante/Ecke bleibt fest. Mit ``proportional``
    (Umschalt) bleibt das Seitenverhältnis erhalten. Ergebnis wird auf die
    Arbeitsfläche begrenzt (``clamp=False`` für gedrehte Rahmen, deren
    lokales Koordinatensystem nicht achsparallel zur Fläche ist).
    """
    left, top, right, bottom = orig.x, orig.y, orig.right, orig.bottom
    moves_l = handle in (0, 6, 7)
    moves_r = handle in (2, 3, 4)
    moves_t = handle in (0, 1, 2)
    moves_b = handle in (4, 5, 6)
    x, y = pos.x(), pos.y()
    if clamp:
        x = min(max(x, 0.0), WORK_WIDTH_MM)
        y = min(max(y, 0.0), WORK_HEIGHT_MM)
    if moves_l:
        left = min(x, right - MIN_SIZE_MM)
    if moves_r:
        right = max(x, left + MIN_SIZE_MM)
    if moves_t:
        top = min(y, bottom - MIN_SIZE_MM)
    if moves_b:
        bottom = max(y, top + MIN_SIZE_MM)
    w, h = right - left, bottom - top
    if proportional and orig.w > 0 and orig.h > 0:
        corner = handle in (0, 2, 4, 6)
        sx, sy = w / orig.w, h / orig.h
        s = max(sx, sy) if corner else (sx if handle in (3, 7) else sy)
        # Nicht über die Fläche hinaus wachsen lassen.
        max_w = right if moves_l else (WORK_WIDTH_MM - left if moves_r else WORK_WIDTH_MM)
        max_h = bottom if moves_t else (WORK_HEIGHT_MM - top if moves_b else WORK_HEIGHT_MM)
        if clamp:
            s = min(s, max_w / orig.w, max_h / orig.h)
        w, h = orig.w * s, orig.h * s
        if moves_l:
            left = right - w
        elif not moves_r:  # Kanten oben/unten: horizontal zentriert skalieren
            left = orig.x + (orig.w - w) / 2
        if moves_t:
            top = bottom - h
        elif not moves_b:
            top = orig.y + (orig.h - h) / 2
    # Box (bei Lininen kann eine Kante 0 sein) erhalten
    if orig.w == 0:
        left, w = orig.x, 0.0
    if orig.h == 0:
        top, h = orig.y, 0.0
    return Rect(left, top, w, h)


class ToolController:
    HANDLE_CURSORS = {0: Qt.SizeFDiagCursor, 4: Qt.SizeFDiagCursor, 2: Qt.SizeBDiagCursor,
                      6: Qt.SizeBDiagCursor, 1: Qt.SizeVerCursor, 5: Qt.SizeVerCursor,
                      3: Qt.SizeHorCursor, 7: Qt.SizeHorCursor, ROTATE_HANDLE: Qt.PointingHandCursor}

    def __init__(self, editor: "CanvasEditor") -> None:
        self.ed = editor
        self.tool = Tool.SELECT
        self._mode: str | None = None  # "move" | "resize" | "rotate" | "rubber" | "draw"
        self._start = QPointF()
        self._orig: dict[str, Geometry] = {}
        self._orig_bounds: Rect | None = None
        self._handle: int | None = None
        self._frame_angle = 0.0          # Drehung des Auswahlrahmens beim Start
        self._frame_center = QPointF()
        self._rot_start = 0.0
        self._moved = False
        self._preview_id: str | None = None
        self.roi_pending = False  # Editor.request_roi(): nächster Zug zieht einen Bereich auf
        self._poly: list[tuple[float, float]] = []  # gesetzte Polygonpunkte (mm)
        self._hover: tuple[float, float] | None = None
        self._free: list[tuple[float, float]] = []  # rohe Freihand-Punkte (mm)
        self._rubber = QGraphicsRectItem()
        pen = QPen(QColor(theme.ACCENT), 1, Qt.DashLine)
        pen.setCosmetic(True)
        self._rubber.setPen(pen)
        fill = QColor(theme.ACCENT)
        fill.setAlpha(28)
        self._rubber.setBrush(fill)
        self._rubber.setZValue(2e9)
        self._rubber.setVisible(False)
        editor.scene.addItem(self._rubber)

    # --- Helfer -----------------------------------------------------------
    @property
    def doc(self):
        return self.ed.document

    def snap(self, v: float) -> float:
        step = self.ed.snap_step_mm
        return round(v / step) * step if self.ed.snap_enabled and step > 0 else v

    def snap_point(self, p: QPointF) -> QPointF:
        return QPointF(self.snap(p.x()), self.snap(p.y()))

    def set_tool(self, tool: Tool) -> None:
        self.cancel()
        self.tool = tool
        self.update_cursor()

    def update_cursor(self) -> None:
        vp = self.ed.view.viewport()
        if self.roi_pending:
            vp.setCursor(Qt.CrossCursor)
            return
        vp.setCursor(Qt.ArrowCursor if self.tool == Tool.SELECT
                     else Qt.IBeamCursor if self.tool == Tool.TEXT else Qt.CrossCursor)

    def cancel(self) -> None:
        """Laufenden Zug abbrechen und Ausgangszustand wiederherstellen."""
        if self._mode in ("move", "resize", "rotate") and self._orig:
            self._apply(self._orig)
        if self._mode in ("draw", "poly", "free") and self._preview_id and self.doc.has_shape(self._preview_id):
            self.doc.remove_shape(self._preview_id)
        self._poly = []
        self._free = []
        self._hover = None
        self._rubber.setVisible(False)
        self._mode = None
        self._preview_id = None
        if self.roi_pending:
            self.roi_pending = False
            self.update_cursor()
            self.ed.roiCancelled.emit()

    def abort_drag(self) -> None:
        """Laufenden Zug verwerfen, z. B. wenn ein zweiter Finger zum Zoomen
        dazukommt: Objekte springen zurück, Vorschauen verschwinden. Anders als
        :meth:`cancel` bleiben ein angefangenes Polygon und eine angeforderte
        Bereichsauswahl erhalten."""
        mode = self._mode
        if mode == "poly":
            return
        if mode in ("move", "resize", "rotate") and self._orig:
            self._apply(self._orig)
        if mode in ("draw", "free") and self._preview_id and self.doc.has_shape(self._preview_id):
            self.doc.remove_shape(self._preview_id)
        self._free = []
        self._orig = {}
        self._rubber.setVisible(False)
        self._mode = None
        self._preview_id = None
        self._moved = False

    def _apply(self, geoms: dict[str, Geometry]) -> None:
        self.doc.begin_batch()
        for sid, g in geoms.items():
            if self.doc.has_shape(sid):
                self.doc.shape(sid).geom = g.copy()
        self.doc.changed()
        self.doc.end_batch()

    def _active_layer_ok(self) -> bool:
        layer = self.doc.active_layer
        if layer is None or layer.locked or not layer.visible:
            self.ed.notify("Aktive Ebene ist gesperrt oder ausgeblendet.")
            return False
        return True

    # --- Mausereignisse ---------------------------------------------------
    def press(self, pos: QPointF, mods: Qt.KeyboardModifier) -> None:
        self._start = pos
        self._moved = False
        if self.roi_pending:
            self._mode = "roi"
            p = _clamp_point(self.snap_point(pos))
            self._start = p
            self._rubber.setRect(QRectF(p, p))
            self._rubber.setVisible(True)
        elif self.tool == Tool.SELECT:
            self._press_select(pos, mods)
        elif self.tool == Tool.TEXT:
            self._create_text(pos)
        elif self.tool == Tool.POLYGON:
            self._press_polygon(pos, mods)
        elif self.tool == Tool.FREEHAND:
            if self._active_layer_ok():
                self._mode = "free"
                p = _clamp_point(pos)  # ohne Raster: Freihand soll der Hand folgen
                self._free = [(p.x(), p.y())]
        elif self._active_layer_ok():
            self._mode = "draw"

    def _press_select(self, pos: QPointF, mods: Qt.KeyboardModifier) -> None:
        handle = self.ed.scene.overlay.handle_at(pos) if self.ed.selection else None
        if handle is not None:
            ov = self.ed.scene.overlay
            self._orig = {i: self.doc.shape(i).geom.copy() for i in self.ed.selection}
            # Rahmen (bei einem gedrehten Einzelobjekt dessen ungedrehte Box).
            self._orig_bounds = ov.rect
            self._frame_angle = ov.angle
            self._frame_center = ov.center()
            self._handle = handle
            if handle == ROTATE_HANDLE:
                self._mode = "rotate"
                self._rot_start = self._angle_to(pos)
            else:
                self._mode = "resize"
            return
        hit = self.ed.scene.editable_shape_at(pos)
        shift = bool(mods & Qt.ShiftModifier)
        if hit is not None:
            # Gruppen werden immer als Ganzes (äußerste Gruppe) gewählt.
            unit = self.doc.unit_of(hit)
            sel = list(self.ed.selection)
            if shift:
                sel = [s for s in sel if s not in unit] if hit in sel else sel + unit
            elif hit not in sel:
                sel = unit
            self.ed.set_selection(sel)
            sel = self.ed.selection
            if hit in sel:
                self._mode = "move"
                self._orig = {i: self.doc.shape(i).geom.copy() for i in sel}
                self._orig_bounds = self.doc.selection_bounds(sel)
            return
        self._mode = "rubber"
        if not shift:
            self.ed.set_selection([])
        self._rubber.setRect(QRectF(pos, pos))
        self._rubber.setVisible(True)

    def move(self, pos: QPointF, mods: Qt.KeyboardModifier, dragging: bool) -> None:
        if self._mode == "poly":
            self._hover = self._poly_point(pos, bool(mods & Qt.ShiftModifier))
            self._update_poly_preview()
            return
        if self._mode == "free":
            if dragging:
                self._add_free_point(pos)
            return
        if self._mode is None or not dragging:
            if self.tool == Tool.SELECT and self._mode is None and not self.roi_pending:
                h = self.ed.scene.overlay.handle_at(pos) if self.ed.selection else None
                vp = self.ed.view.viewport()
                if h is not None:
                    vp.setCursor(self.HANDLE_CURSORS[h])
                elif self.ed.scene.editable_shape_at(pos):
                    vp.setCursor(Qt.SizeAllCursor)
                else:
                    vp.setCursor(Qt.ArrowCursor)
            return
        if (pos - self._start).manhattanLength() * self.ed.view.px_per_mm < 3 and not self._moved:
            return  # kleine Zitterbewegungen beim Klicken ignorieren
        self._moved = True
        shift = bool(mods & Qt.ShiftModifier)
        if self._mode == "move":
            self._drag_move(pos, shift)
        elif self._mode == "resize":
            self._drag_resize(pos, shift)
        elif self._mode == "rotate":
            self._drag_rotate(pos, shift)
        elif self._mode == "rubber":
            self._rubber.setRect(QRectF(self._start, pos).normalized())
        elif self._mode == "roi":
            self._rubber.setRect(QRectF(self._start, _clamp_point(self.snap_point(pos))).normalized())
        elif self._mode == "draw":
            self._drag_draw(pos, shift)

    def _drag_move(self, pos: QPointF, axis_lock: bool) -> None:
        ob = self._orig_bounds
        assert ob is not None
        dx, dy = pos.x() - self._start.x(), pos.y() - self._start.y()
        if axis_lock:  # Umschalt: nur horizontal oder vertikal
            if abs(dx) > abs(dy):
                dy = 0.0
            else:
                dx = 0.0
        # Linke obere Ecke der Auswahl am Raster ausrichten.
        dx = self.snap(ob.x + dx) - ob.x
        dy = self.snap(ob.y + dy) - ob.y
        # Ganze Auswahl gemeinsam in der Fläche halten (Anordnung bleibt erhalten).
        cx, cy = clamp_offset(Rect(ob.x + dx, ob.y + dy, ob.w, ob.h))
        dx, dy = dx + cx, dy + cy
        self._apply({i: g.translated(dx, dy) for i, g in self._orig.items()})
        self.ed.refresh_selection_overlay()

    def _angle_to(self, pos: QPointF) -> float:
        c = self._frame_center
        return math.degrees(math.atan2(pos.y() - c.y(), pos.x() - c.x()))

    def _drag_resize(self, pos: QPointF, proportional: bool) -> None:
        ob = self._orig_bounds
        assert ob is not None and self._handle is not None
        a = self._frame_angle
        if not a:
            nb = resize_bounds(ob, self._handle, self.snap_point(pos), proportional)
            self._apply({i: g.mapped(ob, nb) for i, g in self._orig.items()})
        else:
            # Gedrehtes Einzelobjekt: im eigenen (ungedrehten) Koordinatensystem
            # skalieren, damit Griffe entlang der Objektkanten wirken.
            c = self._frame_center
            lx, ly = rotate_point(pos.x(), pos.y(), c.x(), c.y(), -a)
            nb = resize_bounds(ob, self._handle, QPointF(lx, ly), proportional, clamp=False)
            new = {}
            for i, g in self._orig.items():
                lg = Geometry(g.x, g.y, g.w, g.h).mapped(ob, nb)
                wx, wy = rotate_point(*lg.center(), c.x(), c.y(), a)
                ng = lg.with_center(wx, wy)
                ng.rot = g.rot
                new[i] = ng
            self._apply(new)
        self.ed.refresh_selection_overlay()

    def rotation_delta(self, pos: QPointF, snap: bool) -> float:
        """Drehwinkel seit Zugbeginn; mit ``snap`` auf 15°-Schritte (absolut
        beim Einzelobjekt, relativ bei Mehrfachauswahl)."""
        delta = normalize_angle(self._angle_to(pos) - self._rot_start)
        if snap:
            base = self._frame_angle
            delta = round((base + delta) / ROTATE_SNAP_DEG) * ROTATE_SNAP_DEG - base
        return delta

    def _drag_rotate(self, pos: QPointF, snap: bool) -> None:
        delta = self.rotation_delta(pos, snap)
        c = self._frame_center
        new = keep_inside_together({i: g.rotated(delta, c.x(), c.y()) for i, g in self._orig.items()})
        self._apply(new)
        ob = self._orig_bounds
        if ob is not None and len(self._orig) > 1:
            # Mehrfachauswahl: ursprünglichen Rahmen mitdrehen (statt springender Hüllbox).
            first = next(iter(self._orig))
            ref = self._orig[first].rotated(delta, c.x(), c.y())
            dx, dy = new[first].x - ref.x, new[first].y - ref.y
            self.ed.scene.overlay.set_rect(Rect(ob.x + dx, ob.y + dy, ob.w, ob.h),
                                           normalize_angle(self._frame_angle + delta))
        else:
            self.ed.refresh_selection_overlay()
        self.ed.notify(f"Drehung: {normalize_angle(self._frame_angle + delta):.1f}°")

    def _drag_draw(self, pos: QPointF, constrain: bool) -> None:
        a = _clamp_point(self.snap_point(self._start))
        b = _clamp_point(self.snap_point(pos))
        w, h = b.x() - a.x(), b.y() - a.y()
        if self.tool == Tool.LINE:
            if constrain:  # auf 45°-Schritte einrasten
                ang = round(math.atan2(h, w) / (math.pi / 4)) * (math.pi / 4)
                length = math.hypot(w, h)
                w, h = length * math.cos(ang), length * math.sin(ang)
            geom = Geometry(a.x(), a.y(), w, h)
        else:
            if constrain:  # Quadrat/Kreis
                s = max(abs(w), abs(h))
                w, h = math.copysign(s, w or 1), math.copysign(s, h or 1)
            geom = Geometry(min(a.x(), a.x() + w), min(a.y(), a.y() + h), abs(w), abs(h))
        if self._preview_id is None:
            shape = Shape(self.tool.value, geom, self.doc.active_layer_id)  # type: ignore[arg-type]
            self.doc.add_shape(shape)
            self._preview_id = shape.id
        else:
            self.doc.set_geometry(self._preview_id, geom)

    # --- Polygon -----------------------------------------------------------
    def _poly_point(self, pos: QPointF, constrain: bool) -> tuple[float, float]:
        p = _clamp_point(self.snap_point(pos))
        if constrain and self._poly:  # Umschalt: Kante auf 45°-Schritte
            lx, ly = self._poly[-1]
            w, h = p.x() - lx, p.y() - ly
            ang = round(math.atan2(h, w) / (math.pi / 4)) * (math.pi / 4)
            length = w * math.cos(ang) + h * math.sin(ang)  # Projektion auf die Richtung
            p = _clamp_point(QPointF(lx + length * math.cos(ang), ly + length * math.sin(ang)))
        return (p.x(), p.y())

    def _press_polygon(self, pos: QPointF, mods: Qt.KeyboardModifier) -> None:
        if not self._poly and not self._active_layer_ok():
            return
        self._mode = "poly"
        if len(self._poly) >= 3:
            fx, fy = self._poly[0]
            if math.hypot(pos.x() - fx, pos.y() - fy) * self.ed.view.px_per_mm <= CLOSE_SNAP_PX:
                self.finish_polygon()
                return
        p = self._poly_point(pos, bool(mods & Qt.ShiftModifier))
        if not self._poly or math.hypot(p[0] - self._poly[-1][0], p[1] - self._poly[-1][1]) > 1e-6:
            self._poly.append(p)
        self._hover = None
        self._update_poly_preview()
        if len(self._poly) == 1:
            self.ed.notify("Polygon: klicken = Punkt, Doppelklick/Enter = schließen, "
                           "Rücktaste = letzter Punkt weg, Esc = abbrechen")

    def _update_poly_preview(self) -> None:
        pts = self._poly + ([self._hover] if self._hover and self._hover != self._poly[-1] else [])
        if len(pts) < 2:
            if self._preview_id and self.doc.has_shape(self._preview_id):
                self.doc.remove_shape(self._preview_id)
            self._preview_id = None
            return
        kind = "polygon" if len(pts) >= 3 else "path"
        shape = Shape.from_points(kind, pts, self.doc.active_layer_id)
        if self._preview_id and self.doc.has_shape(self._preview_id):
            prev = self.doc.shape(self._preview_id)
            self.doc.begin_batch()
            prev.kind, prev.points = shape.kind, shape.points
            prev.geom = shape.geom
            self.doc.changed()
            self.doc.end_batch()
        else:
            self.doc.add_shape(shape)
            self._preview_id = shape.id

    def remove_last_polygon_point(self) -> None:
        if self._poly:
            self._poly.pop()
            self._update_poly_preview()
            if not self._poly:
                self.cancel()

    def finish_polygon(self) -> Shape | None:
        """Laufendes Polygon schließen und als ein Undo-Schritt anlegen."""
        pts = list(self._poly)
        self.cancel()  # Vorschau entfernen, Zustand zurücksetzen
        if len(pts) < 3:
            if pts:
                self.ed.notify("Polygon braucht mindestens 3 Punkte.")
            return None
        shape = Shape.from_points("polygon", pts, self.doc.active_layer_id)
        if max(shape.geom.w, shape.geom.h) < MIN_SIZE_MM:
            return None
        self.ed.undo_stack.push(AddShapesCommand(self.doc, [shape], "Polygon zeichnen"))
        self.ed.set_selection([shape.id])
        return shape

    # --- Freihand ------------------------------------------------------------
    def _add_free_point(self, pos: QPointF) -> None:
        p = _clamp_point(pos)
        lx, ly = self._free[-1]
        if math.hypot(p.x() - lx, p.y() - ly) < FREEHAND_MIN_STEP_MM:
            return
        self._free.append((p.x(), p.y()))
        shape = Shape.from_points("path", self._free, self.doc.active_layer_id)
        if self._preview_id and self.doc.has_shape(self._preview_id):
            prev = self.doc.shape(self._preview_id)
            self.doc.begin_batch()
            prev.points, prev.geom = shape.points, shape.geom
            self.doc.changed()
            self.doc.end_batch()
        else:
            self.doc.add_shape(shape)
            self._preview_id = shape.id

    def finish_freehand(self, pos: QPointF | None = None) -> Shape | None:
        """Strich vereinfachen (RDP) und als offenen Pfad in einem Undo-Schritt anlegen."""
        if pos is not None and self._free:
            self._add_free_point(pos)
        raw = list(self._free)
        self._mode = "free"
        self.cancel()  # Vorschau entfernen
        pts = simplify_polyline(raw, FREEHAND_TOLERANCE_MM)
        if len(pts) < 2:
            return None
        shape = Shape.from_points("path", pts, self.doc.active_layer_id)
        if max(shape.geom.w, shape.geom.h) < MIN_SIZE_MM:
            return None
        self.ed.undo_stack.push(AddShapesCommand(self.doc, [shape], "Freihand zeichnen"))
        self.ed.set_selection([shape.id])
        return shape

    def release(self, pos: QPointF, mods: Qt.KeyboardModifier) -> None:
        mode, self._mode = self._mode, None
        if mode == "free":
            self.finish_freehand(pos)
            return
        if mode == "poly":
            self._mode = mode  # Polygon bleibt über mehrere Klicks aktiv
            return
        if mode in ("move", "resize", "rotate"):
            if self._moved:
                new = {i: self.doc.shape(i).geom.copy() for i in self._orig}
                self._apply(self._orig)
                label = {"move": "Verschieben", "resize": "Skalieren", "rotate": "Drehen"}[mode]
                self.ed.undo_stack.push(SetGeometryCommand(self.doc, self._orig, new, label))
            self._orig = {}
        elif mode == "rubber":
            self._rubber.setVisible(False)
            r = self._rubber.rect()
            if r.width() * self.ed.view.px_per_mm > 3 or r.height() * self.ed.view.px_per_mm > 3:
                hits = [s.id for s in self.doc.shapes if self.doc.is_editable(s.id)
                        and QRectF(s.bounds().x, s.bounds().y, max(s.bounds().w, 1e-3),
                                   max(s.bounds().h, 1e-3)).intersects(r)]
                sel = list(self.ed.selection) if mods & Qt.ShiftModifier else []
                self.ed.set_selection(sel + [h for h in hits if h not in sel])
        elif mode == "draw":
            self._finish_draw(pos)
        elif mode == "roi":
            self._rubber.setVisible(False)
            r = QRectF(self._start, _clamp_point(self.snap_point(pos))).normalized()
            if r.width() >= MIN_SIZE_MM and r.height() >= MIN_SIZE_MM:
                self.roi_pending = False
                self.update_cursor()
                self.ed._roi_finished(Rect(r.x(), r.y(), r.width(), r.height()))
            # Zu kleiner Zug (Klick): weiter auf einen Bereich warten, Esc bricht ab.

    def _finish_draw(self, pos: QPointF) -> None:
        pid, self._preview_id = self._preview_id, None
        if pid is not None and self.doc.has_shape(pid):
            shape = self.doc.shape(pid)
            b = shape.bounds()
            self.doc.remove_shape(pid)
            if max(b.w, b.h) < MIN_SIZE_MM:
                return
        else:
            # Einfacher Klick: Objekt in Standardgröße anlegen.
            p = _clamp_point(self.snap_point(pos))
            d = DEFAULT_SIZE_MM
            geom = Geometry(p.x(), p.y(), d, 0.0) if self.tool == Tool.LINE else Geometry(p.x(), p.y(), d, d)
            shape = Shape(self.tool.value, geom, self.doc.active_layer_id)  # type: ignore[arg-type]
        new = shape.copy()
        self.ed.undo_stack.push(AddShapesCommand(self.doc, [new], f"{TOOL_LABELS[self.tool]} zeichnen"))
        self.ed.set_selection([new.id])

    def _create_text(self, pos: QPointF) -> None:
        if not self._active_layer_ok():
            return
        text, ok = QInputDialog.getText(self.ed, "Text", "Text eingeben:", text="LumaCut")
        if not ok or not text.strip():
            return
        self.add_text(text, _clamp_point(self.snap_point(pos)))

    def add_text(self, text: str, pos: QPointF, height_mm: float = DEFAULT_TEXT_HEIGHT_MM) -> Shape:
        """Textobjekt mit natürlichem Seitenverhältnis anlegen (auch für Tests/Skripte)."""
        family = self.ed.text_font_family
        bold = getattr(self.ed, "text_font_bold", False)
        italic = getattr(self.ed, "text_font_italic", False)
        w = height_mm * text_aspect(text, family, bold, italic)
        shape = Shape("text", Geometry(pos.x(), pos.y(), w, height_mm), self.doc.active_layer_id,  # type: ignore[arg-type]
                      text=text, font_family=family, font_bold=bold, font_italic=italic)
        self.ed.undo_stack.push(AddShapesCommand(self.doc, [shape], "Text einfügen"))
        self.ed.set_selection([shape.id])
        return shape

    def double_click(self, pos: QPointF) -> None:
        if self.tool == Tool.POLYGON and self._mode == "poly":
            self.finish_polygon()  # der erste Klick des Doppelklicks hat den Punkt schon gesetzt
            return
        if self.tool != Tool.SELECT:
            return
        hit = self.ed.scene.editable_shape_at(pos)
        if hit and self.doc.shape(hit).kind == "image":
            handler = getattr(self.ed, "image_settings_handler", None)  # lumacut_import.qt
            if handler is not None:
                handler(hit)
            return
        if hit and self.doc.shape(hit).kind == "text":
            old = self.doc.shape(hit).text
            text, ok = QInputDialog.getText(self.ed, "Text bearbeiten", "Text:", text=old)
            if ok and text.strip() and text != old:
                self.ed.undo_stack.push(SetTextCommand(self.doc, hit, text))

    def key_press(self, event: QKeyEvent) -> bool:
        """Pfeiltasten verschieben die Auswahl (1 mm, mit Umschalt 10 mm)."""
        keys = {Qt.Key_Left: (-1, 0), Qt.Key_Right: (1, 0), Qt.Key_Up: (0, -1), Qt.Key_Down: (0, 1)}
        if self._mode == "poly":
            if event.key() in (Qt.Key_Return, Qt.Key_Enter):
                self.finish_polygon()
                return True
            if event.key() == Qt.Key_Backspace:
                self.remove_last_polygon_point()
                return True
            if event.key() == Qt.Key_Escape:
                self.cancel()
                return True
        if event.key() == Qt.Key_Escape and self.roi_pending:
            self.cancel()  # nur die Bereichsauswahl abbrechen, Auswahl bleibt
            return True
        if event.key() == Qt.Key_Escape:
            self.cancel()
            self.ed.set_selection([])
            return True
        if event.key() in keys and self.ed.selection and self._mode is None:
            step = 10.0 if event.modifiers() & Qt.ShiftModifier else 1.0
            dx, dy = (v * step for v in keys[event.key()])
            self.ed.translate_selection(dx, dy)
            return True
        return False
