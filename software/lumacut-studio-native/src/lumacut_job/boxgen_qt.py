"""Dialog „Box-Generator…“ and insertion into the design (Qt side of :mod:`lumacut_job.boxgen`).

Like xTool Studio's Box Generator: size (outer or inner), material thickness,
finger width, kerf, with or without lid, optional slotted dividers (equal
compartments, egg-crate like boxes.py's tray insert); a flat preview of the panels and a
readout (outer / inner size, finger counts, space on the sheet). The panels
are inserted as closed polygons in one group – on the active layer when it
cuts (no fill), otherwise on a new cut layer „Box“ – in one undo step. The
group stays re-editable by double click / „Code bearbeiten…“ (Alt+E).
"""

from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout,
                               QHBoxLayout, QLabel, QSizePolicy, QSpinBox, QWidget)

from lumacut_canvas.commands import AddLayerCommand, AddShapesCommand
from lumacut_canvas.model import Layer
from lumacut_canvas.workarea import WORK_HEIGHT_MM, WORK_WIDTH_MM

from . import boxgen
from .generated import tag
from .qr_qt import layer_fills

CUT_LAYER_NAME = "Box"
TOUCH_PX = 44


class BoxPreview(QWidget):
    """Flat layout of the panels, scaled into the widget, work area outline in grey."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumSize(300, 170)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.rings: list[tuple[str, tuple[tuple[float, float], ...]]] = []
        self.size_mm = (WORK_WIDTH_MM, WORK_HEIGHT_MM)
        self.fits = True

    def set_layout(self, rings, size_mm, fits: bool) -> None:
        self.rings = list(rings)
        self.size_mm = size_mm
        self.fits = fits
        self.update()

    def paintEvent(self, _event) -> None:   # pragma: no cover - drawing only
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor("#ffffff"))
        sw = max(WORK_WIDTH_MM, self.size_mm[0])
        sh = max(WORK_HEIGHT_MM, self.size_mm[1])
        k = min((self.width() - 12) / sw, (self.height() - 12) / sh)
        p.translate((self.width() - sw * k) / 2.0, (self.height() - sh * k) / 2.0)
        p.setPen(QPen(QColor("#bbbbbb"), 1, Qt.DashLine))
        p.drawRect(QRectF(0, 0, WORK_WIDTH_MM * k, WORK_HEIGHT_MM * k))
        p.setPen(QPen(QColor("#c62828") if not self.fits else QColor("#1565c0"), 1.2))
        for name, ring in self.rings:
            if not ring:
                continue
            path = QPainterPath(QPointF(ring[0][0] * k, ring[0][1] * k))
            for x, y in ring[1:]:
                path.lineTo(x * k, y * k)
            path.closeSubpath()
            p.drawPath(path)
            xs = [x for x, _ in ring]
            ys = [y for _, y in ring]
            p.drawText(QRectF(min(xs) * k, min(ys) * k, (max(xs) - min(xs)) * k,
                              (max(ys) - min(ys)) * k), Qt.AlignCenter, name)
        p.end()


class BoxDialog(QDialog):
    """Settings; ``spec()`` returns the normalized :class:`boxgen.BoxSpec`."""

    def __init__(self, parent=None, spec: boxgen.BoxSpec | None = None, active_layer=None,
                 touch: bool = False):
        super().__init__(parent)
        self.setWindowTitle("Box-Generator")
        if spec is None:
            thick = float(getattr(active_layer, "thickness_mm", 0.0) or 0.0)
            spec = boxgen.BoxSpec(thickness_mm=thick) if thick > 0 else boxgen.BoxSpec()
        s = spec.normalized()
        self.touch = touch
        form = QFormLayout(self)
        self.width_mm = self._spin(s.width_mm, boxgen.SIZE_RANGE, 1, "BoxWidth",
                                   "Breite der Box (Vorderkante, X)")
        self.depth_mm = self._spin(s.depth_mm, boxgen.SIZE_RANGE, 1, "BoxDepth",
                                   "Tiefe der Box (Seitenkante, Y)")
        self.height_mm = self._spin(s.height_mm, boxgen.SIZE_RANGE, 1, "BoxHeight",
                                    "Höhe der Box (mit Boden und Deckel)")
        self.inner = QCheckBox("Innenmaße (Platz für den Inhalt)")
        self.inner.setObjectName("BoxInner")
        self.inner.setChecked(s.inner)
        self.inner.setToolTip("Aus: Breite / Tiefe / Höhe sind Außenmaße. An: Innenmaße – die "
                              "Materialdicke kommt außen dazu")
        self.thickness = self._spin(s.thickness_mm, boxgen.THICKNESS_RANGE, 2, "BoxThickness",
                                    "Materialdicke (links) – nachmessen (3-mm-Sperrholz ist "
                                    "oft 2,8–3,2 mm); die Zinken sind genau so tief")
        self.finger = self._spin(s.finger_mm, boxgen.FINGER_RANGE, 1, "BoxFinger",
                                 "Gewünschte Zinkenbreite (rechts); je Kante wird die nächste "
                                 "ungerade Anzahl gewählt, damit beide Enden gleich aussehen")
        self.kerf = self._spin(s.kerf_mm, boxgen.KERF_RANGE, 2, "BoxKerf",
                               "Kerf = Schnittbreite des Lasers (links; Kerf-Test, Diodenlaser "
                               "meist 0,1–0,2 mm): jede Kante wandert um die halbe Schnittbreite "
                               "nach außen, Zinken und Schlitze passen dann saugend. Größer = "
                               "strammer. Nicht zusätzlich den Kerf-Versatz der Ebene setzen")
        self.lid = QCheckBox("Mit Deckel (geschlossene Box)")
        self.lid.setObjectName("BoxLid")
        self.lid.setChecked(s.lid)
        self.lid.setToolTip("Aus: offene Box ohne Deckel, Oberkanten der Wände gerade")
        self.spacing = self._spin(s.spacing_mm, boxgen.SPACING_RANGE, 1, "BoxSpacing",
                                  "Abstand der Teile auf dem Material (rechts)")
        self.dividers_x = self._count(s.dividers_x, "BoxDividersX",
                                      "Trennwände quer (links) – parallel zur Vorderseite, teilen "
                                      "die Tiefe in gleiche Fächer. Volle Innenlänge und -höhe, "
                                      "werden nur eingesteckt (Wände und Boden bleiben "
                                      "unverändert); wo sie die Längswände kreuzen, greifen "
                                      "Schlitze halber Höhe ineinander")
        self.dividers_y = self._count(s.dividers_y, "BoxDividersY",
                                      "Trennwände längs (rechts) – parallel zu den Seiten, teilen "
                                      "die Breite in gleiche Fächer; mit Querwänden gekreuzt "
                                      "(Schlitze von unten)")
        name = getattr(active_layer, "name", "")
        self._active_fills = layer_fills(active_layer)
        self._active_kerf = float(getattr(active_layer, "kerf_mm", 0.0) or 0.0)
        self.new_layer = QCheckBox(f"Neue Ebene „{CUT_LAYER_NAME}“ zum Schneiden anlegen")
        self.new_layer.setObjectName("BoxNewLayer")
        self.new_layer.setChecked(self._active_fills or bool(getattr(active_layer, "locked", False)))
        self.new_layer.setToolTip("Aus: Teile auf die aktive Ebene" + (f" „{name}“" if name else "")
                                  + " – sie muss schneiden (keine Füllung)")
        for cb in (self.inner, self.lid, self.new_layer):
            if touch:
                cb.setMinimumHeight(TOUCH_PX)
        # compact rows so the dialog stays on a 720 px tablet screen in touch mode
        form.addRow("Breite × Tiefe × Höhe", self._row(self.width_mm, QLabel("×"), self.depth_mm,
                                                       QLabel("×"), self.height_mm))
        form.addRow("", self.inner)
        form.addRow("Materialdicke / Zinken", self._row(self.thickness, self.finger))
        form.addRow("Kerf / Abstand", self._row(self.kerf, self.spacing))
        form.addRow("Trennwände quer / längs", self._row(self.dividers_x, self.dividers_y))
        form.addRow("", self._row(self.lid, self.new_layer))
        self.preview = BoxPreview()
        self.preview.setObjectName("BoxPreview")
        form.addRow(self.preview)
        self.info = QLabel()
        self.info.setObjectName("BoxInfo")
        self.info.setWordWrap(True)
        form.addRow("Info", self.info)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.ok_button = self.buttons.button(QDialogButtonBox.Ok)
        self.ok_button.setText("Einfügen")
        if touch:
            for b in self.buttons.buttons():
                b.setMinimumHeight(TOUCH_PX)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        form.addRow(self.buttons)
        for sb in (self.width_mm, self.depth_mm, self.height_mm, self.thickness, self.finger,
                   self.kerf, self.spacing, self.dividers_x, self.dividers_y):
            sb.valueChanged.connect(self._update)
        for cb in (self.inner, self.lid, self.new_layer):
            cb.toggled.connect(self._update)
        self._update()

    @staticmethod
    def _row(*widgets) -> QWidget:
        w = QWidget()
        lay = QHBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        for x in widgets:
            lay.addWidget(x, 0 if isinstance(x, QLabel) else 1)
        return w

    def _spin(self, value: float, rng, decimals: int, name: str, tip: str) -> QDoubleSpinBox:
        sb = QDoubleSpinBox()
        sb.setObjectName(name)
        sb.setRange(*rng)
        sb.setDecimals(decimals)
        sb.setSingleStep(1.0 if decimals <= 1 else 0.05)
        sb.setSuffix(" mm")
        sb.setValue(value)
        sb.setToolTip(tip)
        if self.touch:
            sb.setMinimumHeight(TOUCH_PX)
        return sb

    def _count(self, value: int, name: str, tip: str) -> QSpinBox:
        sb = QSpinBox()
        sb.setObjectName(name)
        sb.setRange(*boxgen.DIVIDER_RANGE)
        sb.setValue(int(value))
        sb.setSpecialValueText("keine")
        sb.setToolTip(tip)
        if self.touch:
            sb.setMinimumHeight(TOUCH_PX)
        return sb

    def spec(self) -> boxgen.BoxSpec:
        return boxgen.BoxSpec(width_mm=self.width_mm.value(), depth_mm=self.depth_mm.value(),
                              height_mm=self.height_mm.value(),
                              thickness_mm=self.thickness.value(), finger_mm=self.finger.value(),
                              kerf_mm=self.kerf.value(), lid=self.lid.isChecked(),
                              inner=self.inner.isChecked(),
                              spacing_mm=self.spacing.value(),
                              dividers_x=self.dividers_x.value(),
                              dividers_y=self.dividers_y.value()).normalized()

    def fill_layer(self) -> bool:
        """True: insert on a new cut layer (name kept from the code dialogs)."""
        return self.new_layer.isChecked()

    def _update(self) -> None:
        s = self.spec()
        try:
            placed, size, fits = boxgen.layout(s)
            text = boxgen.describe(s)
        except ValueError as exc:
            self.preview.set_layout([], (WORK_WIDTH_MM, WORK_HEIGHT_MM), False)
            self.info.setText(str(exc))
            self.ok_button.setEnabled(False)
            return
        self.preview.set_layout(placed, size, fits)
        ok = fits
        if not fits:
            text += (f" – passt nicht auf die Arbeitsfläche ({WORK_WIDTH_MM:.0f} × "
                     f"{WORK_HEIGHT_MM:.0f} mm)")
        if s.finger_mm < s.thickness_mm:
            text += " – Zinken schmaler als die Materialdicke brechen leicht"
        if s.kerf_mm > 0 and self._active_kerf > 0 and not self.new_layer.isChecked():
            text += (f" – Achtung: die aktive Ebene hat schon {self._active_kerf:.2f} mm "
                     "Kerf-Versatz, das wäre doppelt (Kerf hier oder dort auf 0)")
        if not self.new_layer.isChecked() and self._active_fills:
            text += " – Achtung: aktive Ebene füllt, die Teile würden graviert statt geschnitten"
        if (s.dividers_x or s.dividers_y) and s.kerf_mm <= 0:
            text += " – Trennwände ohne Kerf sitzen locker (Kerf-Test machen)"
        self.info.setText(text)
        self.ok_button.setEnabled(ok)


def cut_layer(doc, active, spec: boxgen.BoxSpec) -> Layer:
    """New cut layer „Box“ (no fill) with the material thickness noted."""
    return Layer(CUT_LAYER_NAME, color=doc.next_layer_color(),
                 power=active.power if active else 50.0,
                 speed=active.speed if active else 1500.0,
                 fill_mode="none", thickness_mm=spec.normalized().thickness_mm)


def insert_box(editor, spec: boxgen.BoxSpec, new_layer: bool = False,
               center: tuple[float, float] | None = None) -> list[str]:
    """Insert the panels as one re-editable group (one undo step, optionally with a
    new cut layer). Raises ``ValueError`` (too small, does not fit, layer locked)."""
    doc = editor.document
    s = boxgen.centered(spec, center)
    active = doc.active_layer or (doc.layers[0] if doc.layers else None)
    layer = None
    if new_layer:
        layer = cut_layer(doc, active, s)
        layer_id = layer.id
    else:
        if active is None:
            raise ValueError("Keine Ebene vorhanden")
        if active.locked:
            raise ValueError(f"Ebene „{active.name}“ ist gesperrt")
        layer_id = active.id
    shapes = tag(boxgen.box_shapes(s, layer_id), replace(s, x=0.0, y=0.0))
    stack = editor.undo_stack
    stack.beginMacro("Box einfügen")
    try:
        if layer is not None:
            stack.push(AddLayerCommand(doc, layer, 0))
        stack.push(AddShapesCommand(doc, shapes, "Box"))
    finally:
        stack.endMacro()
    ids = [sh.id for sh in shapes]
    editor.set_selection(ids)
    return ids


__all__ = ["BoxDialog", "BoxPreview", "CUT_LAYER_NAME", "cut_layer", "insert_box"]
