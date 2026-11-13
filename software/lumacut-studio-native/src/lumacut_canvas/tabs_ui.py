"""Werkzeug „Stege“ (Alt+Umschalt+T) – manuelle Haltestege wie LightBurns *Tab tool*.

* Tippen/Klicken auf den Umriss einer geschlossenen Form setzt dort einen Steg
  (ein Undo-Schritt); die Form wird gewählt.
* Tippen auf einen vorhandenen Steg entfernt ihn, Ziehen schiebt ihn entlang
  des Umrisses (ein Undo-Schritt je Zug).
* Pfad › „Stege gleichmäßig setzen …“ (Alt+Umschalt+G, LightBurn *Auto-place
  tabs*) verteilt manuelle Stege auf einmal auf die Auswahl (ohne Auswahl auf
  alle bearbeitbaren Objekte): Anzahl je Kontur oder Abstand, Ecken meiden,
  innere Konturen auslassen – ein Undo-Schritt; danach einzeln verschiebbar.
* Pfad › „Manuelle Stege entfernen“ löscht die Stege der Auswahl.
* Alle manuellen Stege sind auf der Arbeitsfläche als kurze orange Balken in
  Stegbreite der Ebene markiert (immer, nicht nur im Werkzeug); die
  Pfadvorschau zeigt die Lücken so, wie sie gesendet werden.

Die Stegbreite, die Steg-Leistung und der Konturstart kommen von der Ebene
(Schnitt-Optionen); eine Kontur mit eigenen Stegen bekommt keine automatischen.
Rechnen in :mod:`tabs`, Schneiden in :mod:`lumacut_job.cutpath`.
"""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QKeySequence, QPainter, QPen
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
                               QFormLayout, QGraphicsItem, QLabel, QSpinBox)

from . import tabs
from .edit_commands import ReplaceShapeCommand
from .model import Shape, tabs_from_world
from .workarea import WORK_HEIGHT_MM, WORK_WIDTH_MM

TAB_COLOR = "#ff8a3d"
MARKER_PX = 4.0            # Strichstärke der Markierung (Bildschirm-Pixel)
MIN_MARKER_MM = 0.6        # Markierung mindestens so lang (Stegbreite 0 / sehr klein)
ACTIONS = (("tabs_clear", "Manuelle Stege entfernen"),)
EVEN_ACTION = ("tabs_even", "Stege gleichmäßig setzen …", "Alt+Shift+G")


def _fmt(v: float) -> str:
    return f"{v:g}".replace(".", ",")


class TabMarkers(QGraphicsItem):
    """Zeichnet die manuellen Stege aller Objekte sichtbarer Ebenen."""

    def __init__(self, ctl: "TabTool") -> None:
        super().__init__()
        self.ctl = ctl
        self.setZValue(1.05e9)
        self.setAcceptedMouseButtons(Qt.NoButton)
        self.marks: list[tuple[QPointF, QPointF, bool]] = []   # (von, bis, hervorgehoben)
        self.setVisible(False)

    def sync(self) -> None:
        marks = self.ctl.marker_segments()
        if not marks and not self.marks:
            return              # keine Stege: nichts neu zeichnen (häufigster Fall)
        self.marks = marks
        self.setVisible(bool(marks))
        self.update()

    def boundingRect(self) -> QRectF:  # noqa: N802 - Qt API
        return QRectF(-20, -20, WORK_WIDTH_MM + 40, WORK_HEIGHT_MM + 40)

    def paint(self, p: QPainter, option, widget=None) -> None:
        if not self.marks:
            return
        p.setRenderHint(QPainter.Antialiasing)
        for a, b, hot in self.marks:
            pen = QPen(QColor("#ffffff" if hot else TAB_COLOR), MARKER_PX + (2 if hot else 0))
            pen.setCosmetic(True)
            pen.setCapStyle(Qt.FlatCap)
            p.setPen(pen)
            p.drawLine(a, b)


class TabTool:
    """Zustand und Bedienung des Steg-Werkzeugs (von ToolController gerufen)."""

    def __init__(self, editor) -> None:
        self.ed = editor
        self._drag: tuple[Shape, int] | None = None     # (Ausgangsform, Steg-Index)
        self._moved = False
        self._start = QPointF()
        self.hot: tuple[str, int] | None = None          # gezogener Steg (hervorgehoben)
        self.item = TabMarkers(self)
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

    def tab_tol_mm(self) -> float:
        m = self.ed.view.metrics
        return max(m.handle_hit_px, m.handle_px / 2) * self.mm_per_px()

    # --- Anzeige -----------------------------------------------------------
    def marker_segments(self) -> list[tuple[QPointF, QPointF, bool]]:
        out = []
        for s in self.doc.shapes:
            if not s.tabs:
                continue
            layer = next((l for l in self.doc.layers if l.id == s.layer_id), None)
            if layer is None or not layer.visible:
                continue
            half = max(float(getattr(layer, "tab_width_mm", 1.0) or 0.0), MIN_MARKER_MM) / 2
            rings = tabs.closed_rings(s)
            for i, q in enumerate(s.tab_points()):
                d, _pt, k = tabs.nearest_on_rings(rings, q)
                ux, uy = 1.0, 0.0
                if k >= 0:
                    ux, uy = _tangent(rings[k], q)
                out.append((QPointF(q[0] - ux * half, q[1] - uy * half),
                            QPointF(q[0] + ux * half, q[1] + uy * half), self.hot == (s.id, i)))
        return out

    # --- Treffer -----------------------------------------------------------
    def _targets(self) -> list[Shape]:
        return [s for s in self.doc.shapes if s.kind in tabs.TAB_KINDS and self.doc.is_editable(s.id)]

    def tab_at(self, p: tuple[float, float]) -> tuple[Shape, int] | None:
        best, best_d = None, self.tab_tol_mm()
        for s in self._targets():
            for i, q in enumerate(s.tab_points()):
                d = math.dist(p, q)
                if d <= best_d:
                    best, best_d = (s, i), d
        return best

    def outline_at(self, p: tuple[float, float]) -> Shape | None:
        best, best_d = None, self.outline_tol_mm()
        for s in reversed(self._targets()):          # oberstes Objekt zuerst
            b = s.bounds()
            if not (b.x - best_d <= p[0] <= b.x + b.w + best_d and b.y - best_d <= p[1] <= b.y + b.h + best_d):
                continue
            d, q, _k = tabs.nearest_on_rings(tabs.closed_rings(s), p)
            if q is not None and d < best_d:
                best, best_d = s, d
        return best

    # --- Änderungen ----------------------------------------------------------
    def _status(self, s: Shape, verb: str) -> str:
        layer = self.doc.layer(s.layer_id)
        n = len(s.tabs)
        text = f"{verb} – {n} manuelle{'r' if n == 1 else ''} Steg{'e' if n != 1 else ''} an diesem Objekt"
        width = float(getattr(layer, "tab_width_mm", 0.0) or 0.0)
        if width <= 0:
            text += (f" · Achtung: Stegbreite der Ebene „{layer.name}“ ist 0 – es wird kein Steg "
                     "geschnitten (Schnitt-Optionen)")
        else:
            text += f" · Stegbreite {_fmt(width)} mm (Ebene „{layer.name}“)"
            if n and (layer.tab_count > 0 or layer.tab_spacing_mm > 0):
                text += " · ersetzt an dieser Kontur die automatischen Stege"
        return text

    def add_at(self, p: tuple[float, float]) -> Shape | None:
        """Steg auf dem nächsten Umriss unter ``p`` setzen (ein Undo-Schritt)."""
        s = self.outline_at(p)
        if s is None:
            self.ed.notify("Stege: auf den Umriss einer geschlossenen Form tippen "
                           "(Rechteck, Ellipse, Polygon, Text) – Tippen auf einen Steg entfernt ihn.")
            return None
        new, why = tabs.add_tab(s, p, self.outline_tol_mm())
        if new is None:
            self.ed.notify(why)
            return None
        self.ed.undo_stack.push(ReplaceShapeCommand(self.doc, new, "Steg setzen"))
        self.ed.set_selection(self.doc.unit_of(new.id))
        self.ed.notify(self._status(new, "Steg gesetzt"))
        return new

    def remove(self, shape_id: str, index: int) -> None:
        s = self.doc.shape(shape_id)
        new = tabs.remove_tab(s, index)
        self.ed.undo_stack.push(ReplaceShapeCommand(self.doc, new, "Steg entfernen"))
        self.ed.notify(self._status(new, "Steg entfernt"))

    def clear_selection(self) -> int:
        """Manuelle Stege der Auswahl entfernen (ein Undo-Schritt); Anzahl entfernter Stege."""
        shapes = [self.doc.shape(i) for i in self.ed.selection
                  if self.doc.has_shape(i) and self.doc.is_editable(i) and self.doc.shape(i).tabs]
        n = tabs.tab_count(shapes)
        if not shapes:
            self.ed.notify("Manuelle Stege entfernen: die Auswahl hat keine manuellen Stege")
            return 0
        self.ed.undo_stack.beginMacro("Manuelle Stege entfernen")
        try:
            for s in shapes:
                self.ed.undo_stack.push(ReplaceShapeCommand(self.doc, tabs.clear_tabs(s),
                                                            "Manuelle Stege entfernen"))
        finally:
            self.ed.undo_stack.endMacro()
        self.ed.notify(f"{n} manuelle{'r' if n == 1 else ''} Steg{'e' if n != 1 else ''} entfernt"
                       f" ({len(shapes)} Objekt(e)) – dort gelten wieder die automatischen Stege der Ebene")
        return n

    def _live(self, shape_id: str, new: Shape) -> None:
        cur = self.doc.shape(shape_id)
        self.doc.begin_batch()
        cur.tabs = new.tabs
        self.doc.changed()
        self.doc.end_batch()

    # --- Eingaben (Szenen-mm) --------------------------------------------
    def press(self, pos: QPointF) -> None:
        p = (pos.x(), pos.y())
        self._start = QPointF(pos)
        self._moved = False
        hit = self.tab_at(p)
        if hit is not None:
            s, i = hit
            self._drag = (s.copy(), i)
            self.hot = (s.id, i)
            self.item.sync()
            return
        self._drag = None
        self.add_at(p)

    def move(self, pos: QPointF) -> None:
        if self._drag is None:
            return
        if not self._moved and (pos - self._start).manhattanLength() * self.ed.view.px_per_mm < 3:
            return
        orig, i = self._drag
        new = tabs.move_tab(orig, i, (pos.x(), pos.y()))
        if new is not None and self.doc.has_shape(orig.id):
            self._moved = True
            self._live(orig.id, new)

    def release(self) -> None:
        drag, self._drag = self._drag, None
        self.hot = None
        if drag is None:
            return
        orig, i = drag
        if not self.doc.has_shape(orig.id):
            return
        if not self._moved:              # Tippen auf einen Steg: entfernen
            self.item.sync()
            self.remove(orig.id, i)
            return
        new = self.doc.shape(orig.id).copy()
        self._live(orig.id, orig)
        self.ed.undo_stack.push(ReplaceShapeCommand(self.doc, new, "Steg verschieben"))
        self._moved = False
        self.ed.notify(self._status(new, "Steg verschoben"))

    def cancel(self) -> None:
        if self._drag is not None and self._moved and self.doc.has_shape(self._drag[0].id):
            self._live(self._drag[0].id, self._drag[0])
        self._drag = None
        self._moved = False
        if self.hot is not None:
            self.hot = None
            self.item.sync()


def _tangent(ring, q) -> tuple[float, float]:
    best = (math.inf, (1.0, 0.0))
    for a, b in zip(ring, ring[1:]):
        d, _pt = tabs.project(q, a, b)
        ll = math.dist(a, b)
        if d < best[0] and ll > 1e-9:
            best = (d, ((b[0] - a[0]) / ll, (b[1] - a[1]) / ll))
    return best[1]


class EvenTabsDialog(QDialog):
    """„Stege gleichmäßig setzen“: Verteilung, Anzahl / Abstand, Optionen; Zähler live."""

    def __init__(self, doc, shapes, parent=None, values: dict | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Stege gleichmäßig setzen")
        self.setObjectName("EvenTabsDialog")
        self.doc = doc
        self.shapes = list(shapes)
        v = tabs._clean_even(values)
        form = QFormLayout(self)
        self.mode = QComboBox()
        for key in tabs.EVEN_MODES:
            self.mode.addItem(tabs.EVEN_MODE_LABELS[key], key)
        self.mode.setCurrentIndex(max(0, self.mode.findData(v["mode"])))
        self.mode.setToolTip("Anzahl je Kontur: jede Kontur bekommt gleich viele Stege · Abstand: "
                             "ein Steg je … mm Umfang (große Teile mehr, kleine weniger) – "
                             "wie LightBurn „Auto-place tabs“")
        self.count = QSpinBox()
        self.count.setRange(*tabs.EVEN_COUNT_RANGE)
        self.count.setValue(v["count"])
        self.count.setToolTip("Stege je geschlossener Kontur (zu kurze Konturen bekommen weniger: "
                              "jedes Schnittstück bleibt mindestens so lang wie ein Steg)")
        self.spacing = QDoubleSpinBox()
        self.spacing.setRange(*tabs.EVEN_SPACING_RANGE)
        self.spacing.setDecimals(1)
        self.spacing.setSingleStep(5.0)
        self.spacing.setSuffix(" mm")
        self.spacing.setValue(v["spacing_mm"])
        self.spacing.setToolTip("Ein Steg je so viel Umfang, mindestens einer je Kontur")
        self.max_count = QSpinBox()
        self.max_count.setRange(*tabs.EVEN_MAX_RANGE)
        self.max_count.setSpecialValueText("ohne Grenze")
        self.max_count.setValue(v["max_count"])
        self.max_count.setToolTip("Höchstens so viele Stege je Kontur (LightBurn „Limit Max Tabs“)")
        self.min_perimeter = QDoubleSpinBox()
        self.min_perimeter.setRange(*tabs.EVEN_MIN_PERIMETER_RANGE)
        self.min_perimeter.setDecimals(1)
        self.min_perimeter.setSingleStep(5.0)
        self.min_perimeter.setSuffix(" mm")
        self.min_perimeter.setValue(v["min_perimeter_mm"])
        self.min_perimeter.setToolTip("Konturen mit weniger Umfang bleiben ohne Stege "
                                      "(kleine Buchstaben, Bohrungen)")
        self.avoid_corners = QCheckBox("Ecken meiden")
        self.avoid_corners.setChecked(v["avoid_corners"])
        self.avoid_corners.setToolTip("Stege um halbe Stegbreite + 0,5 mm von Ecken (ab 30°) und vom "
                                      "Konturstart wegschieben – höchstens um ein Viertel des Abstands")
        self.skip_inner = QCheckBox("Innere Konturen auslassen")
        self.skip_inner.setChecked(v["skip_inner"])
        self.skip_inner.setToolTip("Keine Stege an Konturen, die in einer anderen Kontur derselben Ebene "
                                   "liegen (Löcher fallen heraus und brauchen keinen Steg)")
        self.replace = QCheckBox("Vorhandene manuelle Stege ersetzen")
        self.replace.setChecked(v["replace"])
        self.replace.setToolTip("Aus: neue Stege kommen zu den vorhandenen hinzu")
        self.readout = QLabel()
        self.readout.setObjectName("EvenTabsReadout")
        self.readout.setWordWrap(True)
        form.addRow("Verteilung", self.mode)
        form.addRow("Anzahl", self.count)
        form.addRow("Abstand", self.spacing)
        form.addRow("Höchstens", self.max_count)
        form.addRow("Mindestumfang", self.min_perimeter)
        form.addRow("", self.avoid_corners)
        form.addRow("", self.skip_inner)
        form.addRow("", self.replace)
        form.addRow(self.readout)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        form.addRow(self.buttons)
        for w in (self.mode,):
            w.currentIndexChanged.connect(self.update_readout)
        for w in (self.count, self.spacing, self.max_count, self.min_perimeter):
            w.valueChanged.connect(self.update_readout)
        for w in (self.avoid_corners, self.skip_inner, self.replace):
            w.toggled.connect(self.update_readout)
        self.update_readout()

    def result_preview(self) -> tabs.EvenTabsResult:
        return tabs.place_even_tabs(self.doc, self.shapes, self.values())

    def update_readout(self) -> None:
        spacing = self.mode.currentData() == "spacing"
        self.count.setEnabled(not spacing)
        self.spacing.setEnabled(spacing)
        self.max_count.setEnabled(spacing)
        res = self.result_preview()
        self.readout.setText(res.readout())
        self.buttons.button(QDialogButtonBox.Ok).setEnabled(res.changed > 0)

    def values(self) -> dict:
        return {"mode": self.mode.currentData(), "count": self.count.value(),
                "spacing_mm": self.spacing.value(), "max_count": self.max_count.value(),
                "avoid_corners": self.avoid_corners.isChecked(),
                "skip_inner": self.skip_inner.isChecked(),
                "min_perimeter_mm": self.min_perimeter.value(), "replace": self.replace.isChecked()}


class EvenTabs:
    """Aktion „Stege gleichmäßig setzen …“ (ein Undo-Schritt, letzte Eingabe je Sitzung)."""

    def __init__(self, editor) -> None:
        self.ed = editor
        self.last = tabs.even_defaults()
        self.ask = self._ask                 # für Tests austauschbar

    def _ask(self, shapes):
        dlg = EvenTabsDialog(self.ed.document, shapes, self.ed, self.last)
        return dlg.values() if dlg.exec() == QDialog.Accepted else None

    def scope(self) -> list[Shape]:
        doc = self.ed.document
        ids = self.ed.selection if self.ed.selection else [s.id for s in doc.shapes]
        want = {i for i in ids if doc.has_shape(i) and doc.is_editable(i)}
        return [s for s in doc.shapes if s.id in want and tabs.can_have_tabs(s)]

    def run(self) -> tabs.EvenTabsResult | None:
        ed = self.ed
        shapes = self.scope()
        if not shapes:
            ed.notify("Stege gleichmäßig setzen: keine geschlossenen Formen "
                      + ("in der Auswahl" if ed.selection else "im Dokument")
                      + " (Rechteck, Ellipse, Polygon, Pfad, Text)")
            return None
        v = self.ask(shapes)
        if not v:
            return None
        self.last = tabs._clean_even(v)
        res = tabs.place_even_tabs(ed.document, shapes, self.last)
        title = "Stege gleichmäßig setzen"
        if res.changed:
            ed.undo_stack.beginMacro(title)
            try:
                for new in res.add:
                    ed.undo_stack.push(ReplaceShapeCommand(ed.document, new, title))
            finally:
                ed.undo_stack.endMacro()
        ed.notify(f"{title}: " + res.readout())
        return res


def install(editor) -> TabTool:
    tool = TabTool(editor)
    editor._act("tabs_clear", ACTIONS[0][1], lambda _=False: tool.clear_selection())
    tool.even = EvenTabs(editor)
    name, text, key = EVEN_ACTION
    editor._act(name, text, lambda _=False: tool.even.run(), QKeySequence(key))
    return tool


__all__ = ["TabTool", "TabMarkers", "EvenTabs", "EvenTabsDialog", "install", "tabs_from_world"]
