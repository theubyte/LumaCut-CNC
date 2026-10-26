"""Knotenwerkzeug im Canvas (Werkzeug „Knoten“, Taste N).

* Tippen/Klicken auf ein Polygon oder einen Pfad (auch Freihand) zeigt seine
  Knoten; Knoten ziehen verschiebt sie (ein Undo-Schritt je Zug).
* Doppelklick auf ein Segment fügt dort einen Knoten ein, Doppelklick auf
  einen Knoten löscht ihn; Entf/Rücktaste löscht den gewählten Knoten.
* Pfeiltasten verschieben den gewählten Knoten (1 mm, Umschalt 10 mm).
* Die Kontextleiste (und das Kontextmenü per Rechtsklick/langem Drücken)
  bietet Knoten einfügen/löschen, Kurve ⇄ Gerade, Pfad schließen/öffnen und
  „In Pfad umwandeln“ für Rechteck, Ellipse und Linie – alles fingertauglich.

Rechnen in :mod:`nodes`; Undo über :class:`ReplaceShapeCommand`.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QKeyEvent, QPainter, QPen
from PySide6.QtWidgets import QGraphicsItem, QHBoxLayout, QLabel, QMenu, QToolButton, QWidget

from . import nodes, theme
from .edit_commands import ReplaceShapeCommand
from .model import Shape
from .shape_paths import shape_path

ACTIONS = (("node_add", "Knoten einfügen", "+ Knoten"),
           ("node_delete", "Knoten löschen", "− Knoten"),
           ("node_curve", "Segment: Kurve ⇄ Gerade", "Kurve ⇄ Gerade"),
           ("node_close", "Pfad schließen / öffnen", "Schließen"),
           ("node_convert", "In Pfad umwandeln (Knoten bearbeiten)", "In Pfad"))


class NodeItem(QGraphicsItem):
    """Zeichnet Umriss und Knoten des bearbeiteten Objekts über allem."""

    def __init__(self, ctl: "NodeEditor") -> None:
        super().__init__()
        self.ctl = ctl
        self.setZValue(1.1e9)
        self.setAcceptedMouseButtons(Qt.NoButton)
        self._rect = QRectF()

    def sync(self) -> None:
        self.prepareGeometryChange()
        s = self.ctl.shape()
        if s is None:
            self._rect = QRectF()
            self.setVisible(False)
        else:
            b = s.bounds()
            m = self.ctl.handle_mm() * 2
            self._rect = QRectF(b.x - m, b.y - m, b.w + 2 * m, b.h + 2 * m)
            self.setVisible(True)
        self.update()

    def boundingRect(self) -> QRectF:  # noqa: N802 - Qt API
        return self._rect

    def paint(self, p: QPainter, option, widget=None) -> None:
        s = self.ctl.shape()
        if s is None:
            return
        p.setRenderHint(QPainter.Antialiasing)
        pen = QPen(QColor(theme.SELECTION), 1.0)
        pen.setCosmetic(True)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        if nodes.is_editable(s):
            p.drawPath(shape_path(s))
            size = self.ctl.handle_mm()
            curves = set(s.curves)
            ranges = s.ring_ranges()
            for i, (x, y) in enumerate(nodes.scene_points(s)):
                ring = next((a, b) for a, b in ranges if a <= i < b)
                prev = i - 1 if i > ring[0] else (ring[1] - 1 if nodes.is_closed(s) else None)
                smooth = i in curves or (prev is not None and prev in curves)
                sel = i == self.ctl.node
                p.setBrush(QColor(theme.ACCENT if sel else theme.BG))
                r = QRectF(x - size / 2, y - size / 2, size, size)
                p.drawEllipse(r) if smooth else p.drawRect(r)
        else:
            dash = QPen(pen)
            dash.setStyle(Qt.DashLine)
            p.setPen(dash)
            p.drawPath(shape_path(s))


class NodeEditor:
    """Zustand und Bedienung des Knotenwerkzeugs (von ToolController gerufen)."""

    def __init__(self, editor) -> None:
        self.ed = editor
        self.shape_id: str | None = None
        self.node: int | None = None
        self._drag_orig: Shape | None = None
        self._moved = False
        self.item = NodeItem(self)
        editor.scene.addItem(self.item)
        self.item.setVisible(False)
        editor.documentChanged.connect(self._doc_changed)

    # --- Zustand ---------------------------------------------------------
    @property
    def doc(self):
        return self.ed.document

    @property
    def active(self) -> bool:
        from .tools import Tool
        return self.ed.tools.tool == Tool.NODE

    def shape(self) -> Shape | None:
        if self.shape_id and self.doc.has_shape(self.shape_id):
            return self.doc.shape(self.shape_id)
        return None

    def mm_per_px(self) -> float:
        return 1.0 / max(self.ed.view.px_per_mm, 1e-9)

    def handle_mm(self) -> float:
        return self.ed.view.metrics.handle_px * self.mm_per_px()

    def node_tol_mm(self) -> float:
        m = self.ed.view.metrics
        return max(m.handle_hit_px, m.handle_px / 2) * self.mm_per_px()

    def seg_tol_mm(self) -> float:
        return self.ed.view.metrics.hit_tolerance_px * self.mm_per_px()

    def set_target(self, shape_id: str | None, node: int | None = None) -> None:
        if shape_id is not None and not self.doc.is_editable(shape_id):
            shape_id = None
        self.shape_id, self.node = shape_id, (node if shape_id else None)
        self.refresh()

    def reset(self) -> None:
        self._drag_orig = None
        self.set_target(None)

    def _doc_changed(self) -> None:
        s = self.shape()
        if s is None:
            self.shape_id, self.node = None, None
        elif self.node is not None and (not nodes.is_editable(s) or self.node >= len(s.points)):
            self.node = None
        self.refresh()

    def refresh(self) -> None:
        on = self.active and self.shape() is not None
        if on:
            self.item.sync()
        else:
            self.item.setVisible(False)
        self.update_actions()
        bar = getattr(self.ed, "property_bar", None)
        if bar is not None and hasattr(bar, "node_controls"):
            bar.node_controls.refresh()

    def update_actions(self) -> None:
        a = getattr(self.ed, "actions_by_name", {})
        s = self.shape() if self.active else None
        edit = nodes.is_editable(s)
        has_seg = edit and self.node is not None and nodes.has_segment(s, self.node)
        states = {"node_add": edit, "node_delete": edit and self.node is not None,
                  "node_curve": has_seg, "node_close": edit,
                  "node_convert": s is not None and s.kind in nodes.CONVERTIBLE_KINDS}
        for name, on in states.items():
            if name in a:
                a[name].setEnabled(bool(on))
        if "node_close" in a:
            a["node_close"].setText("Pfad öffnen" if edit and nodes.is_closed(s) else "Pfad schließen")

    # --- Änderungen ------------------------------------------------------
    def _push(self, new: Shape, label: str, merge_key: str | None = None) -> None:
        self.ed.undo_stack.push(ReplaceShapeCommand(self.doc, new, label, merge_key))

    def _guard(self, fn, label: str) -> bool:
        try:
            fn()
            return True
        except nodes.NodeError as e:
            self.ed.notify(str(e))
            return False

    def _live(self, new: Shape) -> None:
        cur = self.doc.shape(new.id)
        self.doc.begin_batch()
        cur.kind, cur.geom, cur.points = new.kind, new.geom.copy(), new.points
        cur.rings, cur.curves = new.rings, new.curves
        self.doc.changed()
        self.doc.end_batch()

    def move_node_to(self, index: int, pos: tuple[float, float], merge_key: str | None = None) -> None:
        s = self.shape()
        if nodes.is_editable(s):
            self._push(nodes.move_node(s, index, pos), "Knoten verschieben", merge_key)

    def add_node(self, segment: int | None = None, pos: tuple[float, float] | None = None) -> None:
        s = self.shape()
        if not nodes.is_editable(s):
            return
        seg = segment if segment is not None else (self.node if self.node is not None else 0)

        def run():
            new, idx = nodes.insert_node(s, seg, pos)
            self._push(new, "Knoten einfügen")
            self.node = idx
            self.refresh()
        self._guard(run, "Knoten einfügen")

    def delete_node(self, index: int | None = None) -> bool:
        s = self.shape()
        index = self.node if index is None else index
        if not nodes.is_editable(s) or index is None:
            return False

        def run():
            self._push(nodes.delete_node(s, index), "Knoten löschen")
            self.node = None
            self.refresh()
        return self._guard(run, "Knoten löschen")

    def toggle_curve(self) -> None:
        s = self.shape()
        if nodes.is_editable(s) and self.node is not None:
            self._guard(lambda: self._push(nodes.toggle_curve(s, self.node), "Kurve ⇄ Gerade"), "")
            self.refresh()

    def toggle_closed(self) -> None:
        s = self.shape()
        if not nodes.is_editable(s):
            return

        def run():
            closing = not nodes.is_closed(s)
            new, at = nodes.set_closed(s, closing, None if closing else self.node)
            self._push(new, "Pfad schließen" if closing else "Pfad öffnen")
            self.node = at
            self.refresh()
        self._guard(run, "")

    def convert(self) -> bool:
        s = self.shape()
        if s is None or nodes.is_editable(s):
            return False
        ok = self._guard(lambda: self._push(nodes.to_editable(s), "In Pfad umwandeln"), "")
        if ok:
            self.ed.notify("In Pfad umgewandelt – Knoten können jetzt bearbeitet werden.")
        self.refresh()
        return ok

    # --- Eingaben (Szenen-mm) --------------------------------------------
    def press(self, pos: QPointF) -> None:
        p = (pos.x(), pos.y())
        s = self.shape()
        if nodes.is_editable(s):
            i = nodes.node_at(s, p, self.node_tol_mm())
            if i is not None:
                self.node = i
                self._drag_orig = s.copy()
                self._moved = False
                self.refresh()
                return
            if nodes.segment_at(s, p, self.seg_tol_mm()) is not None:
                self.node = None
                self.refresh()
                return
        hit = self.ed.scene.editable_shape_at(pos)
        self.ed.set_selection([hit] if hit else [])
        self.set_target(hit)
        s = self.shape()
        if s is not None and not nodes.is_editable(s):
            self.ed.notify("Text: „In Pfade“ umwandeln." if s.kind == "text" else
                           "Doppelklick oder „In Pfad“ wandelt das Objekt zum Bearbeiten der Knoten um."
                           if s.kind in nodes.CONVERTIBLE_KINDS else "Dieses Objekt hat keine Knoten.")

    def move(self, pos: QPointF) -> None:
        if self._drag_orig is None or self.node is None:
            return
        from .tools import _clamp_point
        p = _clamp_point(self.ed.tools.snap_point(pos))
        try:
            self._live(nodes.move_node(self._drag_orig, self.node, (p.x(), p.y())))
        except nodes.NodeError:
            return
        self._moved = True

    def release(self) -> None:
        orig, self._drag_orig = self._drag_orig, None
        if orig is None or not self._moved or not self.doc.has_shape(orig.id):
            return
        new = self.doc.shape(orig.id).copy()
        self._live(orig)
        self._push(new, "Knoten verschieben")
        self._moved = False

    def cancel(self) -> None:
        if self._drag_orig is not None and self._moved and self.doc.has_shape(self._drag_orig.id):
            self._live(self._drag_orig)
        self._drag_orig = None
        self._moved = False

    def double_click(self, pos: QPointF) -> None:
        p = (pos.x(), pos.y())
        s = self.shape()
        if s is None:
            self.press(pos)
            s = self.shape()
            if s is None:
                return
        if not nodes.is_editable(s):
            if s.kind in nodes.CONVERTIBLE_KINDS:
                self.convert()
            return
        i = nodes.node_at(s, p, self.node_tol_mm())
        if i is not None:
            self.delete_node(i)
            return
        seg = nodes.segment_at(s, p, self.seg_tol_mm())
        if seg is not None:
            self.add_node(seg[0], seg[1])

    def key_press(self, event: QKeyEvent) -> bool:
        keys = {Qt.Key_Left: (-1, 0), Qt.Key_Right: (1, 0), Qt.Key_Up: (0, -1), Qt.Key_Down: (0, 1)}
        s = self.shape()
        if event.key() == Qt.Key_Escape:
            if self.node is not None:
                self.node = None
                self.refresh()
            else:
                self.ed.set_selection([])
                self.set_target(None)
            return True
        if event.key() in (Qt.Key_Delete, Qt.Key_Backspace) and self.node is not None:
            return self.delete_node()
        if event.key() in keys and nodes.is_editable(s) and self.node is not None:
            step = 10.0 if event.modifiers() & Qt.ShiftModifier else 1.0
            x, y = nodes.scene_points(s)[self.node]
            dx, dy = keys[event.key()]
            self.move_node_to(self.node, (x + dx * step, y + dy * step), f"nudge:{self.node}")
            return True
        return False

    def context_target(self, scene_pt: QPointF) -> None:
        """Vor dem Kontextmenü: Knoten unter dem Finger wählen."""
        s = self.shape()
        if nodes.is_editable(s):
            i = nodes.node_at(s, (scene_pt.x(), scene_pt.y()), self.node_tol_mm())
            if i is not None:
                self.node = i
                self.refresh()
                return
        hit = self.ed.scene.editable_shape_at(scene_pt)
        if hit is not None and hit != self.shape_id:
            self.set_target(hit)


class NodeControls(QWidget):
    """Knöpfe in der Kontextleiste, solange das Knotenwerkzeug aktiv ist."""

    def __init__(self, editor) -> None:
        super().__init__()
        self.setObjectName("NodeControls")
        self.ed = editor
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        self.hint = QLabel("Knoten")
        lay.addWidget(self.hint)
        self.buttons: dict[str, QToolButton] = {}
        for name, _label, short in ACTIONS:
            b = QToolButton()
            b.setObjectName(f"NodeButton_{name}")
            b.setText(short)
            b.clicked.connect(lambda _=False, n=name: self.ed.actions_by_name[n].trigger())
            lay.addWidget(b)
            self.buttons[name] = b
        self.setVisible(False)

    def refresh(self) -> None:
        ne = getattr(self.ed, "node_editor", None)
        on = ne is not None and ne.active
        self.setVisible(on)
        if not on:
            return
        a = self.ed.actions_by_name
        for name, b in self.buttons.items():
            act = a.get(name)
            if act is not None:
                b.setEnabled(act.isEnabled())
                b.setToolTip(act.text())
        if "node_close" in a:
            self.buttons["node_close"].setText("Öffnen" if a["node_close"].text() == "Pfad öffnen" else "Schließen")
        s = ne.shape()
        self.hint.setText("Knoten: Objekt antippen" if s is None else
                          f"Knoten {ne.node + 1}/{len(s.points)}" if ne.node is not None and nodes.is_editable(s)
                          else f"{len(s.points)} Knoten" if nodes.is_editable(s) else "Knoten")


def install(editor) -> NodeEditor:
    ne = NodeEditor(editor)
    editor._act("node_add", ACTIONS[0][1], lambda _=False: ne.add_node())
    editor._act("node_delete", ACTIONS[1][1], lambda _=False: ne.delete_node())
    editor._act("node_curve", ACTIONS[2][1], lambda _=False: ne.toggle_curve())
    editor._act("node_close", ACTIONS[3][1], lambda _=False: ne.toggle_closed())
    editor._act("node_convert", ACTIONS[4][1], lambda _=False: ne.convert())
    ne.update_actions()
    return ne


def add_to_menu(editor, menu: QMenu) -> None:
    """Knotenaktionen oben ins Kontextmenü (nur im Knotenwerkzeug)."""
    a = editor.actions_by_name
    for name, _l, _s in ACTIONS:
        if a[name].isEnabled():
            menu.addAction(a[name])
