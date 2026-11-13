"""Werkzeug „Startpunkt“ (Alt+Umschalt+A) – manueller Startpunkt wie LightBurns *Set Start Point*.

* Tippen/Klicken auf den Umriss einer geschlossenen Form legt dort ihren
  Startpunkt fest (ein Undo-Schritt, ein vorhandener Startpunkt der Form wird
  ersetzt); die Form wird gewählt.
* Tippen auf einen vorhandenen Startpunkt entfernt ihn, Ziehen schiebt ihn
  entlang des Umrisses (ein Undo-Schritt je Zug).
* Pfad › „Startpunkte entfernen“ löscht die Startpunkte der Auswahl.
* Alle Startpunkte sind auf der Arbeitsfläche als grüner Punkt mit einem
  kurzen Pfeil in Laufrichtung markiert (immer, nicht nur im Werkzeug); die
  Pfadvorschau zeigt den Start so, wie er gesendet wird.

Die Kontur beginnt beim Senden genau dort – auch mit „Besten Startpunkt
wählen“; An-/Abfahrt, Überschnitt und Stege richten sich danach. Rechnen in
:mod:`startpoint`, Planen in :mod:`lumacut_job.planner` / :mod:`lumacut_job.cutpath`.
"""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QPainter, QPen
from PySide6.QtWidgets import QGraphicsItem

from . import startpoint
from .edit_commands import ReplaceShapeCommand
from .model import Shape
from .workarea import WORK_HEIGHT_MM, WORK_WIDTH_MM

START_COLOR = "#3ddc84"
DOT_PX = 5.0             # Radius der Markierung (Bildschirm-Pixel)
ARROW_PX = 16.0          # Länge des Richtungspfeils (Bildschirm-Pixel)
ACTIONS = (("start_clear", "Startpunkte entfernen"),)


class StartMarkers(QGraphicsItem):
    """Zeichnet die manuellen Startpunkte aller Objekte sichtbarer Ebenen."""

    def __init__(self, ctl: "StartTool") -> None:
        super().__init__()
        self.ctl = ctl
        self.setZValue(1.06e9)
        self.setAcceptedMouseButtons(Qt.NoButton)
        self.marks: list[tuple[QPointF, tuple[float, float] | None, bool]] = []
        self.setVisible(False)

    def sync(self) -> None:
        marks = self.ctl.markers()
        if not marks and not self.marks:
            return              # keine Startpunkte: nichts neu zeichnen (häufigster Fall)
        self.marks = marks
        self.setVisible(bool(marks))
        self.update()

    def boundingRect(self) -> QRectF:  # noqa: N802 - Qt API
        return QRectF(-20, -20, WORK_WIDTH_MM + 40, WORK_HEIGHT_MM + 40)

    def paint(self, p: QPainter, option, widget=None) -> None:
        if not self.marks:
            return
        p.setRenderHint(QPainter.Antialiasing)
        scale = max(p.worldTransform().m11(), 1e-9)          # px je mm
        touch = getattr(self.ctl.ed, "touch_mode", False)
        r_px = DOT_PX * (1.5 if touch else 1.0)
        for pt, direction, hot in self.marks:
            color = QColor("#ffffff" if hot else START_COLOR)
            if direction is not None:
                L = ARROW_PX * (1.5 if touch else 1.0) / scale
                tip = QPointF(pt.x() + direction[0] * L, pt.y() + direction[1] * L)
                pen = QPen(color, 2.0)
                pen.setCosmetic(True)
                p.setPen(pen)
                p.drawLine(pt, tip)
                head = 5.0 / scale
                for sgn in (1, -1):
                    ang = math.atan2(direction[1], direction[0]) + math.pi + sgn * math.radians(30)
                    p.drawLine(tip, QPointF(tip.x() + math.cos(ang) * head,
                                            tip.y() + math.sin(ang) * head))
            pen = QPen(QColor("#10141a"), 1.5)
            pen.setCosmetic(True)
            p.setPen(pen)
            p.setBrush(QBrush(color))
            r = r_px / scale
            p.drawEllipse(pt, r, r)


class StartTool:
    """Zustand und Bedienung des Startpunkt-Werkzeugs (von ToolController gerufen)."""

    def __init__(self, editor) -> None:
        self.ed = editor
        self._drag: Shape | None = None      # Ausgangsform beim Ziehen
        self._moved = False
        self._start = QPointF()
        self.hot: str | None = None           # Form, deren Startpunkt gezogen wird
        self.item = StartMarkers(self)
        editor.scene.addItem(self.item)
        editor.documentChanged.connect(self.item.sync)
        self.item.sync()

    @property
    def doc(self):
        return self.ed.document

    def mm_per_px(self) -> float:
        return 1.0 / max(self.ed.view.px_per_mm, 1e-9)

    def outline_tol_mm(self) -> float:
        m = self.ed.view.metrics
        return max(m.hit_tolerance_px, m.handle_px / 2) * self.mm_per_px()

    def marker_tol_mm(self) -> float:
        m = self.ed.view.metrics
        return max(m.handle_hit_px, m.handle_px / 2) * self.mm_per_px()

    # --- Anzeige -----------------------------------------------------------
    def markers(self) -> list[tuple[QPointF, tuple[float, float] | None, bool]]:
        out = []
        for s in self.doc.shapes:
            if not s.start:
                continue
            layer = next((l for l in self.doc.layers if l.id == s.layer_id), None)
            if layer is None or not layer.visible:
                continue
            p = s.start_point()
            out.append((QPointF(*p), startpoint.start_direction(s), self.hot == s.id))
        return out

    # --- Treffer -----------------------------------------------------------
    def _targets(self) -> list[Shape]:
        return [s for s in self.doc.shapes
                if s.kind in startpoint.START_POINT_KINDS and self.doc.is_editable(s.id)]

    def start_at(self, p: tuple[float, float]) -> Shape | None:
        """Objekt, dessen Startpunkt ``p`` am nächsten liegt (in Fangweite)."""
        best, best_d = None, self.marker_tol_mm()
        for s in self._targets():
            q = s.start_point()
            if q is not None and math.dist(p, q) <= best_d:
                best, best_d = s, math.dist(p, q)
        return best

    def outline_at(self, p: tuple[float, float]) -> Shape | None:
        best, best_d = None, self.outline_tol_mm()
        for s in reversed(self._targets()):          # oberstes Objekt zuerst
            b = s.bounds()
            if not (b.x - best_d <= p[0] <= b.x + b.w + best_d and b.y - best_d <= p[1] <= b.y + b.h + best_d):
                continue
            d, q, _k = startpoint.nearest_outline(s, p)
            if q is not None and d < best_d:
                best, best_d = s, d
        return best

    # --- Änderungen ----------------------------------------------------------
    def _status(self, s: Shape, verb: str) -> str:
        layer = self.doc.layer(s.layer_id)
        if not s.start:
            return f"{verb} – die Kontur beginnt wieder dort, wo der Planer es wählt"
        text = f"{verb} – die Kontur beginnt hier (Pfeil = Laufrichtung)"
        extra = []
        if getattr(layer, "lead_in_mm", 0.0) > 0:
            extra.append("die Anfahrt setzt hier an")
        if getattr(layer, "fill_mode", "none") != "none" and not getattr(layer, "hatch_outline", True):
            extra.append(f"Achtung: Ebene „{layer.name}“ füllt ohne Kontur – der Startpunkt "
                         "wirkt erst mit „Kontur“")
        return text + (" · " + " · ".join(extra) if extra else "")

    def set_at(self, p: tuple[float, float]) -> Shape | None:
        """Startpunkt auf dem nächsten Umriss unter ``p`` setzen (ein Undo-Schritt)."""
        s = self.outline_at(p)
        if s is None:
            self.ed.notify("Startpunkt: auf den Umriss einer geschlossenen Form tippen "
                           "(Rechteck, Ellipse, Polygon, Text) – Tippen auf den Startpunkt entfernt ihn.")
            return None
        new, why = startpoint.set_start(s, p, self.outline_tol_mm())
        if new is None:
            self.ed.notify(why)
            return None
        verb = "Startpunkt versetzt" if s.start else "Startpunkt gesetzt"
        self.ed.undo_stack.push(ReplaceShapeCommand(self.doc, new, "Startpunkt setzen"))
        self.ed.set_selection(self.doc.unit_of(new.id))
        self.ed.notify(self._status(new, verb))
        return new

    def remove(self, shape_id: str) -> None:
        s = self.doc.shape(shape_id)
        new = startpoint.clear_start(s)
        self.ed.undo_stack.push(ReplaceShapeCommand(self.doc, new, "Startpunkt entfernen"))
        self.ed.notify(self._status(new, "Startpunkt entfernt"))

    def clear_selection(self) -> int:
        """Startpunkte der Auswahl entfernen (ein Undo-Schritt); Anzahl entfernter Startpunkte."""
        shapes = [self.doc.shape(i) for i in self.ed.selection
                  if self.doc.has_shape(i) and self.doc.is_editable(i) and self.doc.shape(i).start]
        if not shapes:
            self.ed.notify("Startpunkte entfernen: die Auswahl hat keine Startpunkte")
            return 0
        self.ed.undo_stack.beginMacro("Startpunkte entfernen")
        try:
            for s in shapes:
                self.ed.undo_stack.push(ReplaceShapeCommand(self.doc, startpoint.clear_start(s),
                                                            "Startpunkte entfernen"))
        finally:
            self.ed.undo_stack.endMacro()
        n = len(shapes)
        self.ed.notify(f"{n} Startpunkt{'e' if n != 1 else ''} entfernt – dort wählt wieder "
                       "der Planer den Start")
        return n

    def _live(self, shape_id: str, new: Shape) -> None:
        cur = self.doc.shape(shape_id)
        self.doc.begin_batch()
        cur.start = new.start
        self.doc.changed()
        self.doc.end_batch()

    # --- Eingaben (Szenen-mm) --------------------------------------------
    def press(self, pos: QPointF) -> None:
        p = (pos.x(), pos.y())
        self._start = QPointF(pos)
        self._moved = False
        hit = self.start_at(p)
        if hit is not None:
            self._drag = hit.copy()
            self.hot = hit.id
            self.item.sync()
            return
        self._drag = None
        self.set_at(p)

    def move(self, pos: QPointF) -> None:
        if self._drag is None:
            return
        if not self._moved and (pos - self._start).manhattanLength() * self.ed.view.px_per_mm < 3:
            return
        orig = self._drag
        d, q, _k = startpoint.nearest_outline(orig, (pos.x(), pos.y()))
        if q is not None and self.doc.has_shape(orig.id):
            self._moved = True
            self._live(orig.id, startpoint.with_start(orig, q))

    def release(self) -> None:
        orig, self._drag = self._drag, None
        self.hot = None
        if orig is None:
            return
        if not self.doc.has_shape(orig.id):
            return
        if not self._moved:              # Tippen auf den Startpunkt: entfernen
            self.item.sync()
            self.remove(orig.id)
            return
        new = self.doc.shape(orig.id).copy()
        self._live(orig.id, orig)
        self.ed.undo_stack.push(ReplaceShapeCommand(self.doc, new, "Startpunkt verschieben"))
        self._moved = False
        self.ed.notify(self._status(new, "Startpunkt verschoben"))

    def cancel(self) -> None:
        if self._drag is not None and self._moved and self.doc.has_shape(self._drag.id):
            self._live(self._drag.id, self._drag)
        self._drag = None
        self._moved = False
        if self.hot is not None:
            self.hot = None
            self.item.sync()


def install(editor) -> StartTool:
    tool = StartTool(editor)
    editor._act(ACTIONS[0][0], ACTIONS[0][1], lambda _=False: tool.clear_selection())
    return tool


__all__ = ["StartTool", "StartMarkers", "install"]
