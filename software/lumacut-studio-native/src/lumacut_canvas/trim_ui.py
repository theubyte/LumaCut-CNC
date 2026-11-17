"""Werkzeug „Trimmen“ (Alt+Umschalt+X) – Stücke per Tippen entfernen wie LightBurns *Trim Shapes*.

* Tippen/Klicken auf eine Linie, einen offenen Pfad oder den Umriss eines Rechtecks,
  einer Ellipse, eines Polygons / Sterns entfernt das Stück zwischen den zwei
  nächsten Kreuzungen mit anderen Formen (oder zwischen einer Kreuzung und dem
  freien Ende) – genau ein Undo-Schritt je Tippen. Damit lassen sich auch innere
  Stücke (zwischen zwei Kreuzungen) und Überstände über der Grenze von
  „Überstände abschneiden …“ entfernen.
* Eine geschlossene Form wird dabei zum offenen Pfad (wie in LightBurn); weitere
  Ringe eines Polygons (Löcher) bleiben ein geschlossenes Polygon.
* Ziehen über mehrere Stücke (wie LightBurns Trimmen mit gedrückter Maustaste)
  zieht eine Linie; jedes Stück, das sie kreuzt, fällt beim Loslassen weg – alle
  zusammen in einem Undo-Schritt. Bestimmt werden die Stücke gegen den Zustand vor
  dem Zug, also genau das, was die rote Vorschau zeigt.
* Mit der Maus zeigt das Werkzeug vorher rot gestrichelt, welches Stück wegfällt
  (grau: hier gibt es nichts zu trimmen); mit dem Finger (Touch-Modus, größerer
  Fangabstand) entfernt der Tipp direkt, Strg+Z holt es zurück.
* Geschnitten wird an allen Formen sichtbarer Ebenen (auch gesperrter, auch Text
  und erzeugte Objekte); getrimmt werden nur Formen entsperrter Ebenen. Text,
  Bilder und erzeugte Objekte (QR-Code, Barcode …) werden nie getrimmt.

Rechnen in :mod:`pathtrim` (:class:`~pathtrim.TrimIndex`).
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QGraphicsItem

from . import pathtrim
from .edit_commands import ReplaceShapesCommand
from .workarea import WORK_HEIGHT_MM, WORK_WIDTH_MM

TRIM_COLOR = "#ff5a5f"
NONE_COLOR = "#8a8f98"
TAP_PX = 6.0             # weiter bewegt = kein Tippen


class TrimMarker(QGraphicsItem):
    """Zeigt das Stück, das ein Tippen entfernen würde."""

    def __init__(self) -> None:
        super().__init__()
        self.setZValue(1.07e9)
        self.setAcceptedMouseButtons(Qt.NoButton)
        self.piece: list[tuple[float, float]] = []
        self.pieces: list[list[tuple[float, float]]] = []   # Ziehen: alle Stücke
        self.fence: list[tuple[float, float]] = []          # Ziehen: die Zuglinie
        self.ok = True
        self.touch = False
        self.setVisible(False)

    def show_piece(self, piece, ok: bool) -> None:
        piece = list(piece or [])
        if (piece == self.piece and ok == self.ok and not self.fence
                and self.isVisible() == bool(piece)):
            return
        self.piece, self.ok = piece, ok
        self.pieces, self.fence = ([piece] if piece else []), []
        self.setVisible(bool(piece))
        self.update()

    def show_sweep(self, fence, pieces) -> None:
        """Zuglinie (grau gestrichelt) und alle Stücke, die beim Loslassen wegfallen."""
        self.fence = list(fence or [])
        self.pieces = [list(p) for p in pieces or [] if len(p) >= 2]
        self.piece = self.pieces[0] if len(self.pieces) == 1 else []
        self.ok = bool(self.pieces)
        self.setVisible(bool(self.fence))
        self.update()

    def boundingRect(self) -> QRectF:  # noqa: N802 - Qt API
        return QRectF(-20, -20, WORK_WIDTH_MM + 40, WORK_HEIGHT_MM + 40)

    def paint(self, p: QPainter, option, widget=None) -> None:
        p.setRenderHint(QPainter.Antialiasing)
        p.setBrush(Qt.NoBrush)
        if len(self.fence) == 2:
            pen = QPen(QColor(NONE_COLOR), 2.0 if self.touch else 1.5)
            pen.setCosmetic(True)
            pen.setStyle(Qt.DotLine)
            p.setPen(pen)
            p.drawLine(QPointF(*self.fence[0]), QPointF(*self.fence[1]))
        path = QPainterPath()
        for piece in self.pieces:
            if len(piece) < 2:
                continue
            path.moveTo(QPointF(*piece[0]))
            for pt in piece[1:]:
                path.lineTo(QPointF(*pt))
        if path.isEmpty():
            return
        pen = QPen(QColor(TRIM_COLOR if self.ok else NONE_COLOR), 4.0 if self.touch else 3.0)
        pen.setCosmetic(True)
        pen.setStyle(Qt.DashLine)
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        p.drawPath(path)


class TrimTool:
    """Zustand und Bedienung des Trimmwerkzeugs (von ToolController gerufen)."""

    def __init__(self, editor) -> None:
        self.ed = editor
        self._index: pathtrim.TrimIndex | None = None
        self._start: QPointF | None = None
        self._moved = False
        self.item = TrimMarker()
        editor.scene.addItem(self.item)
        editor.documentChanged.connect(self._invalidate)

    @property
    def doc(self):
        return self.ed.document

    def _invalidate(self) -> None:
        self._index = None
        if self.item.isVisible():
            self.item.show_piece([], True)

    def tolerance_mm(self) -> float:
        m = self.ed.view.metrics
        return max(m.hit_tolerance_px, m.handle_px / 2) / max(self.ed.view.px_per_mm, 1e-9)

    def index(self) -> pathtrim.TrimIndex:
        if self._index is None:
            visible = {l.id for l in self.doc.layers if l.visible}
            unlocked = {l.id for l in self.doc.layers if l.visible and not l.locked}
            shapes = [s for s in self.doc.shapes if s.layer_id in visible]
            self._index = pathtrim.TrimIndex(shapes, [s.id for s in shapes if s.layer_id in unlocked])
        return self._index

    def pick_at(self, pos: QPointF) -> pathtrim.TrimPick | None:
        return self.index().pick((pos.x(), pos.y()), self.tolerance_mm())

    # --- Anzeige -----------------------------------------------------------
    def hover(self, pos: QPointF) -> None:
        pick = self.pick_at(pos)
        self.item.touch = bool(getattr(self.ed, "touch_mode", False))
        if pick is None:
            self.item.show_piece([], True)
        else:
            self.item.show_piece(pick.removed, pick.ok)

    # --- Aktion -----------------------------------------------------------
    def trim_at(self, pos: QPointF) -> bool:
        """Stück unter ``pos`` entfernen (ein Undo-Schritt); True wenn getrimmt."""
        pick = self.pick_at(pos)
        if pick is None:
            locked = pathtrim.TrimIndex([s for s in self.index().shapes]).pick(
                (pos.x(), pos.y()), self.tolerance_mm())
            if locked is not None:
                self.ed.notify("Trimmen: die Ebene dieser Form ist gesperrt")
            else:
                self.ed.notify("Trimmen: hier liegt keine Linie / kein Umriss zum Trimmen "
                               "(Text erst in Pfade umwandeln)")
            return False
        if not pick.ok:
            self.ed.notify(f"Trimmen: {pick.reason}")
            self.item.show_piece(pick.removed, False)
            return False
        was_selected = pick.shape.id in self.ed.selection
        sel = [i for i in self.ed.selection if i not in pick.remove]
        self.ed.undo_stack.push(ReplaceShapesCommand(self.doc, pick.remove, pick.add, "Trimmen"))
        if was_selected:
            sel += [s.id for s in pick.add]
        self.ed.set_selection([i for i in sel if self.doc.has_shape(i)])
        self.item.show_piece([], True)
        what = "Stück" if pick.shape.kind in ("path", "line") else "Stück der Kontur (jetzt offener Pfad)"
        self.ed.notify(f"Trimmen: {what} von {pick.length_mm:.1f} mm entfernt – Strg+Z holt es zurück")
        return True

    def sweep(self, a: QPointF, b: QPointF) -> pathtrim.TrimSweep:
        return self.index().sweep((a.x(), a.y()), (b.x(), b.y()))

    def trim_sweep(self, a: QPointF, b: QPointF) -> int:
        """Alle Stücke entfernen, die die Zuglinie ``a``–``b`` kreuzt (ein Undo-Schritt).

        Rückgabe: Anzahl entfernter Stücke."""
        sw = self.sweep(a, b)
        self.item.show_piece([], True)
        if not sw.ok:
            locked = pathtrim.TrimIndex(list(self.index().shapes)).sweep((a.x(), a.y()), (b.x(), b.y()))
            if locked.ok:
                self.ed.notify("Trimmen: die gekreuzten Formen liegen auf gesperrten Ebenen")
            elif sw.skipped:
                self.ed.notify("Trimmen: die Linie kreuzt nur Formen ohne Kreuzung mit anderen – "
                               "Entf löscht ein ganzes Objekt")
            else:
                self.ed.notify("Trimmen: die gezogene Linie kreuzt kein Stück zum Trimmen")
            return 0
        sel = list(self.ed.selection)
        stack = self.ed.undo_stack
        stack.beginMacro("Trimmen")
        try:
            for sid, add in sw.replace:
                stack.push(ReplaceShapesCommand(self.doc, [sid], add, "Trimmen"))
                if sid in sel:
                    sel = [i for i in sel if i != sid] + [s.id for s in add]
        finally:
            stack.endMacro()
        self.ed.set_selection([i for i in sel if self.doc.has_shape(i)])
        n = len(sw.pieces)
        what = "1 Stück" if n == 1 else f"{n} Stücke"
        self.ed.notify(f"Trimmen: {what} ({sw.length_mm:.1f} mm) von {len(sw.replace)} Form(en) "
                       "entfernt – Strg+Z holt alle zurück")
        return n

    # --- Eingaben (Szenen-mm) --------------------------------------------
    def press(self, pos: QPointF) -> None:
        self._start = QPointF(pos)
        self._moved = False

    def move(self, pos: QPointF) -> None:
        if self._start is None:
            return
        if (pos - self._start).manhattanLength() * self.ed.view.px_per_mm > TAP_PX:
            self._moved = True
        if not self._moved:
            self.hover(pos)
            return
        # Ziehen: Zuglinie und alle Stücke zeigen, die sie kreuzt
        self.item.touch = bool(getattr(self.ed, "touch_mode", False))
        sw = self.sweep(self._start, pos)
        self.item.show_sweep(sw.fence, sw.pieces)

    def release(self, pos: QPointF) -> None:
        start, self._start = self._start, None
        moved, self._moved = self._moved, False
        if start is None:
            return
        if moved:
            self.trim_sweep(start, pos)
            return
        self.trim_at(start)

    def cancel(self) -> None:
        self._start = None
        self._moved = False
        self.item.show_piece([], True)


def install(editor) -> TrimTool:
    return TrimTool(editor)


__all__ = ["TrimTool", "TrimMarker", "install"]
