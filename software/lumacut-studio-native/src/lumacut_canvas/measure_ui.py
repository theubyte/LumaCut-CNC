"""Werkzeug „Messen“ (M) – Abstand / ΔX / ΔY / Winkel zwischen zwei gefangenen
Punkten wie LightBurns *Measure*-Werkzeug.

* Ziehen misst vom Druck- zum Loslasspunkt; alternativ (Finger) zwei Punkte
  antippen: der erste Tipp setzt den Start, bis zum zweiten folgt die Messung dem
  Mauszeiger.
* Beide Punkte fangen wie die Zeichenwerkzeuge an Knoten, Ecken, Kantenmitten,
  Mittelpunkten, Quadranten und Linien-Enden anderer Objekte („An Objekten
  fangen“, 7 px / Touch-Modus 14 px), sonst am 1-mm-Raster; Alt setzt den
  Objektfang aus, Umschalt rastet die Richtung in 15°-Schritten ein.
* Auf der Zeichenfläche: Strecke mit Endmarken und ein Schild mit Abstand,
  ΔX / ΔY und Winkel (Anzeige-Einheit mm / Zoll); die Statusleiste zeigt dasselbe.
* Die letzte Messung bleibt stehen, bis neu gemessen, Esc gedrückt oder das
  Werkzeug gewechselt wird. Strg+C (im Werkzeug) bzw. „Messung kopieren“ im
  Kontextmenü legt den Abstand („42.43 mm“) in die Zwischenablage.
* Keine Änderung am Dokument: kein Undo-Schritt, nicht gespeichert, kein G-Code.

Rechnen in :mod:`measure` (Qt-frei).
"""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QKeyEvent, QPainter, QPen
from PySide6.QtWidgets import QApplication, QGraphicsItem, QGraphicsLineItem

from . import measure, theme
from .measure import Measurement
from .unit_ui import display_units

MEASURE_COLOR = "#ffc857"
Z_VALUE = 2.05e9          # über den Objekten, unter den Fang-Hilfslinien
TAP_PX = 3.0              # kürzerer Zug zählt als Tippen (erster Punkt)


def _touch(ed) -> bool:
    return bool(getattr(ed, "touch_mode", False))


class MeasureMarker(QGraphicsItem):
    """Endmarke (Kreis mit Kreuz) in Bildschirm-Pixeln, unabhängig vom Zoom."""

    def __init__(self, ed) -> None:
        super().__init__()
        self.ed = ed
        self.setFlag(QGraphicsItem.ItemIgnoresTransformations, True)
        self.setAcceptedMouseButtons(Qt.NoButton)
        self.setZValue(Z_VALUE + 1)
        self.setVisible(False)

    def radius(self) -> float:
        return 7.0 if _touch(self.ed) else 4.5

    def boundingRect(self) -> QRectF:  # noqa: N802 - Qt API
        return QRectF(-12, -12, 24, 24)

    def paint(self, p: QPainter, option, widget=None) -> None:
        r = self.radius()
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QPen(QColor(MEASURE_COLOR), 2.0 if _touch(self.ed) else 1.5))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(QPointF(0, 0), r, r)
        p.drawLine(QPointF(-r - 3, 0), QPointF(r + 3, 0))
        p.drawLine(QPointF(0, -r - 3), QPointF(0, r + 3))


class MeasureLabel(QGraphicsItem):
    """Schild mit Abstand / ΔX / ΔY / Winkel neben der Streckenmitte (Pixel).

    Es sitzt seitlich der Strecke (auf der oberen Seite, bei senkrechten Strecken
    rechts), damit Strecke, Endmarken und Fang-Hilfslinien sichtbar bleiben.
    """

    GAP = 12.0
    PAD = 6.0

    def __init__(self, ed) -> None:
        super().__init__()
        self.ed = ed
        self.lines: list[str] = []
        self._rect = QRectF()
        self.setFlag(QGraphicsItem.ItemIgnoresTransformations, True)
        self.setAcceptedMouseButtons(Qt.NoButton)
        self.setZValue(Z_VALUE + 2)
        self.setVisible(False)

    def font(self) -> QFont:
        f = QFont()
        f.setPointSizeF(12.0 if _touch(self.ed) else 9.5)
        return f

    def set_lines(self, lines: list[str], direction: tuple[float, float] = (1.0, 0.0)) -> None:
        """``direction``: Richtung der Strecke auf dem Bildschirm (x rechts, y unten)."""
        fm = QFontMetricsF(self.font())
        w = max((fm.horizontalAdvance(t) for t in lines), default=0.0) + 2 * self.PAD
        h = fm.height() * len(lines) + 2 * self.PAD
        dx, dy = direction
        n = math.hypot(dx, dy)
        nx, ny = (-dy / n, dx / n) if n > 1e-12 else (0.0, -1.0)   # Normale
        if ny > 1e-9 or (abs(ny) <= 1e-9 and nx < 0):
            nx, ny = -nx, -ny                                       # obere / rechte Seite
        ax, ay = nx * self.GAP, ny * self.GAP
        # Die Ecke des Schilds, die zur Strecke zeigt, liegt auf dem Ankerpunkt.
        x = ax if nx >= -1e-9 else ax - w
        y = ay - h if ny <= 1e-9 else ay
        if abs(nx) < 0.3:   # (fast) waagerechte Strecke: Schild mittig darüber
            x = -w / 2
        if abs(ny) < 0.3:   # (fast) senkrechte Strecke: Schild mittig daneben
            y = -h / 2
        self.prepareGeometryChange()
        self.lines = list(lines)
        self._rect = QRectF(x, y, w, h)
        self.update()

    def boundingRect(self) -> QRectF:  # noqa: N802 - Qt API
        return self._rect.adjusted(-1, -1, 1, 1)

    def paint(self, p: QPainter, option, widget=None) -> None:
        if not self.lines:
            return
        p.setRenderHint(QPainter.Antialiasing)
        bg = QColor(theme.PANEL)
        bg.setAlpha(225)
        p.setPen(QPen(QColor(MEASURE_COLOR), 1.0))
        p.setBrush(bg)
        p.drawRoundedRect(self._rect, 4, 4)
        f = self.font()
        p.setFont(f)
        fm = QFontMetricsF(f)
        y = self._rect.y() + self.PAD + fm.ascent()
        for i, t in enumerate(self.lines):
            p.setPen(QColor(MEASURE_COLOR if i == 0 else theme.TEXT))
            p.drawText(QPointF(self._rect.x() + self.PAD, y), t)
            y += fm.height()


class MeasureTool:
    """Zustand und Bedienung des Mess-Werkzeugs (von ToolController gerufen)."""

    def __init__(self, editor) -> None:
        self.ed = editor
        self.measurement: Measurement | None = None
        self.pending = False      # erster Punkt gesetzt, zweiter folgt der Maus
        self._dragging = False
        self._fresh = False       # aktueller Zug hat einen neuen Startpunkt gesetzt
        self._press_px = QPointF()
        self.line = QGraphicsLineItem()
        self.line.setZValue(Z_VALUE)
        self.line.setAcceptedMouseButtons(Qt.NoButton)
        self.line.setVisible(False)
        self.markers = (MeasureMarker(editor), MeasureMarker(editor))
        self.label = MeasureLabel(editor)
        for item in (self.line, *self.markers, self.label):
            editor.scene.addItem(item)

    # --- Hilfen --------------------------------------------------------------
    @property
    def ctl(self):
        return self.ed.tools

    @property
    def unit(self) -> str:
        return display_units().unit

    @property
    def active(self) -> bool:
        """Läuft gerade eine Messung (Ziehen oder auf den zweiten Punkt warten)?"""
        return self._dragging or self.pending

    def _point(self, pos: QPointF) -> tuple[float, float]:
        p = self.ctl.snap_point(pos)
        return (p.x(), p.y())

    def _end_point(self, pos: QPointF, mods) -> tuple[float, float]:
        p = self._point(pos)
        if mods is not None and mods & Qt.ShiftModifier and self.measurement is not None:
            p = measure.constrain(self.measurement.start, p)
        return p

    def _set(self, m: Measurement | None) -> None:
        self.measurement = m
        self.refresh()

    def refresh(self) -> None:
        """Strecke / Marken / Schild nach Messung, Einheit oder Touch-Modus neu zeichnen."""
        m = self.measurement
        if m is None:
            for item in (self.line, *self.markers, self.label):
                item.setVisible(False)
            return
        pen = QPen(QColor(MEASURE_COLOR), 2.0 if _touch(self.ed) else 1.5, Qt.DashLine)
        pen.setCosmetic(True)
        self.line.setPen(pen)
        self.line.setLine(m.x1, m.y1, m.x2, m.y2)
        self.line.setVisible(not m.is_point)
        self.markers[0].setPos(m.x1, m.y1)
        self.markers[1].setPos(m.x2, m.y2)
        self.markers[0].setVisible(True)
        self.markers[1].setVisible(not m.is_point)
        for mk in self.markers:
            mk.update()
        self.label.set_lines(measure.label_lines(m, self.unit), (m.x2 - m.x1, m.y2 - m.y1))
        self.label.setPos(*m.midpoint())
        self.label.setVisible(True)

    def _status(self, final: bool = False) -> None:
        m = self.measurement
        if m is None:
            return
        text = measure.readout(m, self.unit)
        osnap = getattr(self.ed, "object_snap", None)
        last = getattr(osnap, "last", None)
        if last is not None and not final:
            text += f" · Fang: {last.label}"
        if final:
            text += "  (Strg+C kopiert den Abstand, Esc löscht)"
        self.ed.notify(text)

    # --- Mausereignisse --------------------------------------------------------
    def press(self, pos: QPointF, mods) -> None:
        self.ctl._osnap_begin((), mods)
        self._dragging = True
        self._press_px = pos * self.ed.view.px_per_mm
        if self.pending and self.measurement is not None:
            self._fresh = False
            m = self.measurement
            self._set(Measurement(m.x1, m.y1, *self._end_point(pos, mods)))
        else:
            self._fresh = True
            p = self._point(pos)
            self._set(Measurement(*p, *p))
        osnap = self.ctl.object_snap
        if osnap is not None and not self.pending:
            osnap.keep_anchor()  # Fang des Startpunkts bleibt sichtbar
        self._status()

    def move(self, pos: QPointF, mods, dragging: bool) -> None:
        if not (self._dragging and dragging) and not self.pending:
            return
        m = self.measurement
        if m is None:
            return
        osnap = self.ctl.object_snap
        if osnap is not None and osnap.enabled and osnap.targets is None:
            osnap.begin(())  # nach dem ersten Tipp: Ziele für den zweiten Punkt
            self.ctl._osnap_mods(mods)
        self._set(Measurement(m.x1, m.y1, *self._end_point(pos, mods)))
        self._status()

    def release(self, pos: QPointF, mods) -> None:
        if not self._dragging:
            return
        self._dragging = False
        m = self.measurement
        if m is None:
            return
        moved = (pos * self.ed.view.px_per_mm - self._press_px).manhattanLength()
        if self._fresh and moved < TAP_PX:
            # Klick / Tipp: Startpunkt gesetzt, Ende folgt der Maus bis zum nächsten Klick.
            self.pending = True
            self.ed.notify("Messen: Startpunkt gesetzt – Endpunkt klicken oder antippen "
                           "(Umschalt = 15°-Schritte, Alt = ohne Objektfang, Esc = abbrechen)")
            return
        self.pending = False
        self._set(Measurement(m.x1, m.y1, *self._end_point(pos, mods)))
        self._status(final=True)

    def double_click(self, pos: QPointF) -> None:
        """Maus-Doppelklick: Qt schickt statt des zweiten Drückens einen Doppelklick."""
        if self.pending and not self._dragging:
            self.press(pos, QApplication.keyboardModifiers())

    def abort(self) -> None:
        """Zweiter Finger (Zoomen): laufenden Zug verwerfen."""
        if self._dragging:
            self.clear()

    # --- Tasten / Abbruch ---------------------------------------------------------
    def clear(self) -> bool:
        """Messung löschen; ``True``, wenn etwas zu löschen war."""
        had = self.measurement is not None or self.pending
        self.pending = False
        self._dragging = False
        self._fresh = False
        self._set(None)
        osnap = self.ctl.object_snap if hasattr(self.ed, "tools") else None
        if osnap is not None:
            osnap.end()
        return had

    def cancel(self) -> None:
        self.clear()

    def key_press(self, event: QKeyEvent) -> bool:
        if event.key() == Qt.Key_Escape and self.clear():
            self.ed.notify("Messung gelöscht")
            return True
        return False

    def copy(self) -> bool:
        """Abstand in die Zwischenablage; ``False`` ohne Messung."""
        m = self.measurement
        if m is None or self._dragging:
            return False
        text = measure.clipboard_text(m, self.unit)
        QApplication.clipboard().setText(text)
        self.ed.notify(f"Abstand {text} in die Zwischenablage kopiert")
        return True


def add_to_menu(editor, menu) -> None:
    """„Messung kopieren“ / „Messung löschen“ im Kontextmenü des Werkzeugs."""
    mt = editor.measure_tool
    if mt.measurement is None or mt._dragging:
        return
    menu.addAction(editor.actions_by_name["measure_copy"])
    menu.addAction(editor.actions_by_name["measure_clear"])


def install(editor) -> MeasureTool:
    tool = MeasureTool(editor)
    c = editor._act("measure_copy", "Messung kopieren", lambda: tool.copy())
    c.setToolTip("Gemessenen Abstand in die Zwischenablage kopieren (im Werkzeug „Messen“: Strg+C)")
    editor._act("measure_clear", "Messung löschen",
                lambda: tool.clear() and editor.notify("Messung gelöscht"))
    return tool


__all__ = ["MEASURE_COLOR", "MeasureLabel", "MeasureMarker", "MeasureTool", "add_to_menu", "install"]
