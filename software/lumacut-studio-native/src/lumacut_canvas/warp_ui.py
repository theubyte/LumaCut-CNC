"""Pfad-Menü: „Verzerren …“ (LightBurn *Warp Selection* / *Deform*, xTool „Verzerren“).

Dialog mit einer Vorschau, in der die vier Ecken der Auswahl mit Maus oder Finger
gezogen werden (Touch-Modus: große Anfasser), Zahlenfeldern je Ecke (→ X / ↓ Y in mm,
Bildschirmrichtung), Wölbung der Ober- / Unterkante, Art (Hülle / Perspektive) und
Schnellwahl (oben / unten schmaler, rechts höher, Bogen, zurücksetzen). Rechnen in
:mod:`warp`; die Aktion ist genau ein Undo-Schritt, jedes Objekt bleibt an seiner Stelle
im Stapel. Von :func:`pathops_ui.install` eingebunden. Kürzel Alt+Umschalt+W („Warp“).
"""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QKeySequence, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout,
                               QGridLayout, QHBoxLayout, QLabel, QPushButton, QWidget)

from . import warp
from .edit_commands import ReplaceShapesCommand

TEXT = "Verzerren …"
ACTIONS = [("path_warp", TEXT, "Alt+Shift+W")]
MENU_ACTIONS = [name for name, _t, _k in ACTIONS]
PRESETS = [("top_narrow", "Oben schmaler"), ("bottom_narrow", "Unten schmaler"),
           ("rise_right", "Rechts höher"), ("arch", "Bogen"), ("reset", "Zurücksetzen")]


def default_values() -> dict:
    return {"mode": "envelope", "offsets": ((0.0, 0.0),) * 4, "bulge_top": 0.0,
            "bulge_bottom": 0.0}


class WarpPreview(QWidget):
    """Vorschau: Box gestrichelt, verzerrte Umrisse blau, Ecken als ziehbare Anfasser."""

    cornerMoved = Signal(int, float, float)   # Ecke, neue Lage in Arbeitsflächen-mm

    def __init__(self, box, touch: bool = False, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("WarpPreview")
        self.box = box
        self.touch = touch
        self.quad = list(warp.box_corners(box))
        self.outlines: list[tuple[list, bool]] = []
        self.drag: int | None = None
        self.setMinimumSize(320 if touch else 260, 240 if touch else 190)
        self.setMouseTracking(True)

    @property
    def handle_px(self) -> float:
        return 22.0 if self.touch else 10.0     # halbe Trefferfläche (Touch: 44 px)

    def _frame(self) -> tuple[float, float, float]:
        """Maßstab und Versatz: Box samt Viereck (und Wölbung) passend ins Feld."""
        xs = [p[0] for p in self.quad] + [self.box.x, self.box.right]
        ys = [p[1] for p in self.quad] + [self.box.y, self.box.bottom]
        for pts, _closed in self.outlines:
            xs += [p[0] for p in pts]
            ys += [p[1] for p in pts]
        x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
        pad = self.handle_px + 6
        w, h = max(self.width() - 2 * pad, 10), max(self.height() - 2 * pad, 10)
        k = min(w / max(x1 - x0, 1e-6), h / max(y1 - y0, 1e-6))
        ox = pad + (w - (x1 - x0) * k) / 2 - x0 * k
        oy = pad + (h - (y1 - y0) * k) / 2 - y0 * k
        return k, ox, oy

    def to_screen(self, p) -> QPointF:
        k, ox, oy = self._frame()
        return QPointF(ox + p[0] * k, oy + p[1] * k)

    def to_world(self, q: QPointF) -> tuple[float, float]:
        k, ox, oy = self._frame()
        return ((q.x() - ox) / k, (q.y() - oy) / k)

    def set_state(self, quad, outlines) -> None:
        self.quad = list(quad)
        self.outlines = outlines
        self.update()

    def corner_at(self, pos: QPointF) -> int | None:
        best, idx = self.handle_px + 1e-9, None
        for i, p in enumerate(self.quad):
            d = math.dist((pos.x(), pos.y()), (self.to_screen(p).x(), self.to_screen(p).y()))
            if d <= best:
                best, idx = d, i
        return idx

    def paintEvent(self, _ev) -> None:  # noqa: N802 - Qt
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor("#fafafa"))
        pen = QPen(QColor("#9e9e9e"), 1, Qt.DashLine)
        p.setPen(pen)
        b = self.box
        p.drawRect(QRectF(self.to_screen((b.x, b.y)), self.to_screen((b.right, b.bottom))))
        p.setPen(QPen(QColor("#1565c0"), 1.4))
        for pts, closed in self.outlines:
            if len(pts) < 2:
                continue
            path = QPainterPath(self.to_screen(pts[0]))
            for q in pts[1:]:
                path.lineTo(self.to_screen(q))
            if closed:
                path.closeSubpath()
            p.drawPath(path)
        p.setPen(QPen(QColor("#ef6c00"), 1, Qt.DotLine))
        corners = [self.to_screen(q) for q in self.quad]
        for i in range(4):
            p.drawLine(corners[i], corners[(i + 1) % 4])
        r = self.handle_px * 0.55
        for i, c in enumerate(corners):
            p.setPen(QPen(QColor("#ef6c00"), 2))
            p.setBrush(QColor("#ffe0b2") if i != self.drag else QColor("#ef6c00"))
            p.drawEllipse(c, r, r)
        p.end()

    def mousePressEvent(self, ev) -> None:  # noqa: N802 - Qt
        if ev.button() == Qt.LeftButton:
            self.drag = self.corner_at(ev.position())
            if self.drag is not None:
                self._grab = self._frame()
                self.update()

    def mouseMoveEvent(self, ev) -> None:  # noqa: N802 - Qt
        if self.drag is None:
            c = self.corner_at(ev.position())
            self.setCursor(Qt.SizeAllCursor if c is not None else Qt.ArrowCursor)
            return
        k, ox, oy = self._grab      # Maßstab vom Drückzeitpunkt (Ecke folgt dem Finger)
        q = ev.position()
        self.cornerMoved.emit(self.drag, (q.x() - ox) / k, (q.y() - oy) / k)

    def mouseReleaseEvent(self, _ev) -> None:  # noqa: N802 - Qt
        if self.drag is not None:
            self.drag = None
            self.update()


class WarpDialog(QDialog):
    def __init__(self, shapes, parent=None, values: dict | None = None, touch: bool = False) -> None:
        super().__init__(parent)
        self.setWindowTitle("Verzerren")
        self.shapes = list(shapes)
        self.box = warp.selection_box(self.shapes)
        v = {**default_values(), **(values or {})}
        form = QFormLayout(self)
        self.mode = QComboBox()
        for key in warp.MODES:
            self.mode.addItem(warp.MODE_LABELS[key], key)
        self.mode.setCurrentIndex(max(0, self.mode.findData(v["mode"])))
        self.mode.setToolTip("Hülle: jede Seite der Auswahl geht auf die Seite des Vierecks, "
                             "Linien quer durch werden gebogen (LightBurn Warp), mit Wölbung "
                             "als Bogen / Tonne · Perspektive: Geraden bleiben gerade, wie schräg "
                             "von vorn gesehen")
        form.addRow("Art", self.mode)
        self.preview = WarpPreview(self.box, touch)
        self.preview.setToolTip("Ecken mit Maus oder Finger ziehen")
        form.addRow(self.preview)
        grid = QGridLayout()
        grid.addWidget(QLabel("→ X"), 0, 1)
        grid.addWidget(QLabel("↓ Y"), 0, 2)
        self.spins: list[tuple[QDoubleSpinBox, QDoubleSpinBox]] = []
        for i, key in enumerate(warp.CORNERS):
            grid.addWidget(QLabel(warp.CORNER_LABELS[key]), i + 1, 0)
            pair = []
            for j in range(2):
                sb = QDoubleSpinBox()
                sb.setObjectName(f"WarpOffset_{key}_{'xy'[j]}")
                sb.setRange(*warp.OFFSET_RANGE)
                sb.setDecimals(2)
                sb.setSingleStep(1.0)
                sb.setSuffix(" mm")
                sb.setValue(float(v["offsets"][i][j]))
                sb.setToolTip("Verschiebung dieser Ecke gegenüber der Auswahl-Box "
                              "(+ nach rechts / unten, wie auf dem Bildschirm)")
                if touch:
                    sb.setMinimumHeight(44)
                grid.addWidget(sb, i + 1, j + 1)
                pair.append(sb)
            self.spins.append(tuple(pair))
        form.addRow(grid)
        self.bulge_top = self._bulge_box(v["bulge_top"], touch)
        self.bulge_bottom = self._bulge_box(v["bulge_bottom"], touch)
        form.addRow("Wölbung oben", self.bulge_top)
        form.addRow("Wölbung unten", self.bulge_bottom)
        row = QHBoxLayout()
        self.preset_buttons = {}
        for key, label in PRESETS:
            btn = QPushButton(label)
            btn.setObjectName(f"WarpPreset_{key}")
            if touch:
                btn.setMinimumHeight(44)
            btn.clicked.connect(lambda _=False, k=key: self.apply_preset(k))
            row.addWidget(btn)
            self.preset_buttons[key] = btn
        form.addRow(row)
        self.readout = QLabel()
        self.readout.setObjectName("WarpReadout")
        self.readout.setWordWrap(True)
        form.addRow(self.readout)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        form.addRow(self.buttons)
        self.mode.currentIndexChanged.connect(self.update_readout)
        for pair in self.spins:
            for sb in pair:
                sb.valueChanged.connect(self.update_readout)
        self.bulge_top.valueChanged.connect(self.update_readout)
        self.bulge_bottom.valueChanged.connect(self.update_readout)
        self.preview.cornerMoved.connect(self.move_corner)
        self.update_readout()

    @staticmethod
    def _bulge_box(value: float, touch: bool) -> QDoubleSpinBox:
        sb = QDoubleSpinBox()
        sb.setRange(*warp.BULGE_RANGE)
        sb.setDecimals(2)
        sb.setSingleStep(1.0)
        sb.setSuffix(" mm")
        sb.setValue(float(value))
        sb.setToolTip("Kante als Bogen: Stich in der Mitte, + nach oben, − nach unten "
                      "(nur bei „Hülle“; beide gleich = Bogen, oben + / unten − = Tonne)")
        if touch:
            sb.setMinimumHeight(44)
        return sb

    def offsets(self) -> tuple[tuple[float, float], ...]:
        return tuple((sx.value(), sy.value()) for sx, sy in self.spins)

    def values(self) -> dict:
        return {"mode": self.mode.currentData(), "offsets": self.offsets(),
                "bulge_top": self.bulge_top.value(), "bulge_bottom": self.bulge_bottom.value()}

    def current_warp(self) -> warp.Warp:
        v = self.values()
        return warp.warp_from_offsets(self.box, v["offsets"], v["mode"], v["bulge_top"],
                                      v["bulge_bottom"])

    def _set_offsets(self, offsets) -> None:
        for (sx, sy), (dx, dy) in zip(self.spins, offsets):
            for sb, val in ((sx, dx), (sy, dy)):
                sb.blockSignals(True)
                sb.setValue(val)
                sb.blockSignals(False)

    def move_corner(self, i: int, x: float, y: float) -> None:
        cx, cy = warp.box_corners(self.box)[i]
        offs = list(self.offsets())
        offs[i] = (round(x - cx, 2), round(y - cy, 2))
        self._set_offsets(offs)
        self.update_readout()

    def apply_preset(self, key: str) -> None:
        for sb in (self.bulge_top, self.bulge_bottom):
            sb.blockSignals(True)
        try:
            if key == "arch":
                b = round(0.15 * self.box.h, 2)
                self.mode.setCurrentIndex(self.mode.findData("envelope"))
                self.bulge_top.setValue(b)
                self.bulge_bottom.setValue(b)
            else:
                self._set_offsets(warp.preset_offsets(key, self.box))
                if key == "reset":
                    self.bulge_top.setValue(0.0)
                    self.bulge_bottom.setValue(0.0)
        finally:
            for sb in (self.bulge_top, self.bulge_bottom):
                sb.blockSignals(False)
        self.update_readout()

    def result_preview(self) -> warp.WarpResult:
        return warp.warp_shapes(self.shapes, self.current_warp())

    def update_readout(self) -> None:
        persp = self.mode.currentData() == "perspective"
        self.bulge_top.setEnabled(not persp)
        self.bulge_bottom.setEnabled(not persp)
        w = self.current_warp()
        res = warp.warp_shapes(self.shapes, w)
        outlines = []
        for s in res.add:
            closed = s.kind == "polygon"
            pts = s.abs_points()
            for a, b in s.ring_ranges():
                outlines.append((pts[a:b], closed))
        self.preview.set_state(w.quad, outlines)
        text = res.readout()
        if not res.problem and w.is_identity():
            text = "Ecken ziehen oder Werte eingeben – noch unverändert. " + text
        self.readout.setText(text)
        ok = res.changed > 0 and not res.problem and res.inside and not w.is_identity()
        self.buttons.button(QDialogButtonBox.Ok).setEnabled(ok)


class WarpTool:
    def __init__(self, editor) -> None:
        self.editor = editor
        self.last_mode = "envelope"         # Art bleibt in der Sitzung
        self.ask = self._ask                # für Tests austauschbar

    def _ask(self, shapes):
        dlg = WarpDialog(shapes, self.editor, {"mode": self.last_mode},
                         touch=bool(getattr(self.editor, "touch_mode", False)))
        return dlg.values() if dlg.exec() == QDialog.Accepted else None

    def _scope(self):
        ed = self.editor
        doc = ed.document
        want = {i for i in ed.selection if doc.has_shape(i) and doc.is_editable(i)}
        return [s for s in doc.shapes if s.id in want]

    def run(self) -> None:
        ed = self.editor
        shapes = self._scope()
        if not any(warp.can_warp(s) for s in shapes):
            ed.notify("Verzerren: Formen, Linien oder Text auswählen (Bilder werden nicht verzerrt).")
            return
        v = self.ask(shapes)
        if not v:
            return
        v = {**default_values(), **v}
        self.last_mode = v["mode"]
        box = warp.selection_box(shapes)
        w = warp.warp_from_offsets(box, v["offsets"], v["mode"], v["bulge_top"], v["bulge_bottom"])
        res = warp.warp_shapes(shapes, w)
        if res.problem or not res.changed:
            ed.notify("Verzerren: " + res.readout())
            return
        if not res.inside:
            ed.notify("Verzerren: das Ergebnis läge teils außerhalb der Arbeitsfläche – "
                      "nichts geändert.")
            return
        ed.undo_stack.beginMacro("Verzerren")
        try:       # einzeln ersetzen: jede Form bleibt an ihrer Stelle im Stapel
            for old, new in zip(res.remove, res.add):
                ed.undo_stack.push(ReplaceShapesCommand(ed.document, [old], [new], "Verzerren"))
        finally:
            ed.undo_stack.endMacro()
        keep = [i for i in ed.selection if ed.document.has_shape(i)]
        ed.set_selection(list(dict.fromkeys(keep + [s.id for s in res.add])))
        ed.notify("Verzerren: " + res.readout())


def install(editor) -> WarpTool:
    tool = WarpTool(editor)
    for name, text, key in ACTIONS:
        editor._act(name, text, lambda _=False: tool.run(), QKeySequence(key) if key else None)
    a = editor.actions_by_name["path_warp"]
    a.setToolTip(f"{TEXT}  (Alt+Umschalt+W) – Auswahl in ein Viereck / einen Bogen verzerren "
                 "wie LightBurn Warp Selection / Deform: Hülle oder Perspektive")
    return tool
