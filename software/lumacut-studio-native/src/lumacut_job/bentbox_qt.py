"""Dialog „Flex-Box (runde Ecken)…“ and insertion (Qt side of :mod:`lumacut_job.bentbox`).

A box with rounded corners whose wall is one bent strip with a living hinge in
every corner: size (outer or inner), inner corner radius, material thickness,
finger width, kerf, with or without lid, hinge pattern / slit / bridge / pitch
and a two-part wall for boxes longer than the work area; a flat preview of the
parts with their hinge cuts and a readout. Inserted as one re-editable group –
on the active layer when it cuts (no fill), otherwise on a new cut layer
„Flex-Box“ – in one undo step.
"""

from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
                               QFormLayout, QHBoxLayout, QLabel, QSizePolicy, QWidget)

from lumacut_canvas.commands import AddLayerCommand, AddShapesCommand
from lumacut_canvas.model import Layer
from lumacut_canvas.workarea import WORK_HEIGHT_MM, WORK_WIDTH_MM

from . import bentbox
from .generated import tag
from .qr_qt import layer_fills

CUT_LAYER_NAME = "Flex-Box"
TOUCH_PX = 44


class BentBoxPreview(QWidget):
    """Flat layout of the parts with their hinge cuts, work area outline in grey."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumSize(300, 150)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.placed: list = []
        self.size_mm = (WORK_WIDTH_MM, WORK_HEIGHT_MM)
        self.fits = True

    @property
    def rings(self) -> list:
        return [(name, ring) for name, ring, _cuts in self.placed]

    def set_layout(self, placed, size_mm, fits: bool) -> None:
        self.placed = list(placed)
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
        colour = QColor("#c62828") if not self.fits else QColor("#1565c0")
        for name, ring, cuts in self.placed:
            p.setPen(QPen(colour, 0.6))
            for pts, closed in cuts:
                path = QPainterPath(QPointF(pts[0][0] * k, pts[0][1] * k))
                for x, y in pts[1:]:
                    path.lineTo(x * k, y * k)
                if closed:
                    path.closeSubpath()
                p.drawPath(path)
            p.setPen(QPen(colour, 1.2))
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


class BentBoxDialog(QDialog):
    """Settings; ``spec()`` returns the normalized :class:`bentbox.BentBoxSpec`."""

    def __init__(self, parent=None, spec: bentbox.BentBoxSpec | None = None, active_layer=None,
                 touch: bool = False):
        super().__init__(parent)
        self.setWindowTitle("Flex-Box")
        if spec is None:
            thick = float(getattr(active_layer, "thickness_mm", 0.0) or 0.0)
            spec = (bentbox.BentBoxSpec(thickness_mm=thick) if thick > 0
                    else bentbox.BentBoxSpec())
        s = spec.normalized()
        self.touch = touch
        form = QFormLayout(self)
        self.width_mm = self._spin(s.width_mm, bentbox.SIZE_RANGE, 1, "BentWidth",
                                   "Breite der Box (Vorderseite, X)")
        self.depth_mm = self._spin(s.depth_mm, bentbox.SIZE_RANGE, 1, "BentDepth",
                                   "Tiefe der Box (Seite, Y)")
        self.height_mm = self._spin(s.height_mm, bentbox.SIZE_RANGE, 1, "BentHeight",
                                    "Höhe der Box (mit Boden und Deckel)")
        self.inner = QCheckBox("Innenmaße")
        self.inner.setObjectName("BentInner")
        self.inner.setChecked(s.inner)
        self.inner.setToolTip("Aus: Breite / Tiefe / Höhe sind Außenmaße. An: Innenmaße – die "
                              "Materialdicke kommt außen dazu")
        self.radius = self._spin(s.radius_mm, bentbox.RADIUS_RANGE, 1, "BentRadius",
                                 "Innenradius der runden Ecken (Innenseite der Wand; außen kommt "
                                 "die Materialdicke dazu). Größer = leichter zu biegen")
        self.thickness = self._spin(s.thickness_mm, bentbox.THICKNESS_RANGE, 2, "BentThickness",
                                    "Materialdicke (links) – nachmessen (3-mm-Sperrholz ist "
                                    "oft 2,8–3,2 mm); Zinken und Biegestrecke hängen davon ab")
        self.finger = self._spin(s.finger_mm, bentbox.FINGER_RANGE, 1, "BentFinger",
                                 "Gewünschte Zinkenbreite (rechts) an den geraden Seiten von "
                                 "Boden und Deckel")
        self.kerf = self._spin(s.kerf_mm, bentbox.KERF_RANGE, 2, "BentKerf",
                               "Kerf = Schnittbreite des Lasers (links): jede Kante wandert um "
                               "die halbe Schnittbreite nach außen, Zinken passen dann saugend. "
                               "Die Scharnier-Schlitze bleiben unverändert. Nicht zusätzlich den "
                               "Kerf-Versatz der Ebene setzen")
        self.spacing = self._spin(s.spacing_mm, bentbox.SPACING_RANGE, 1, "BentSpacing",
                                  "Abstand der Teile auf dem Material (rechts)")
        self.pattern = QComboBox()
        self.pattern.setObjectName("BentPattern")
        for key in bentbox.PATTERNS:
            self.pattern.addItem(bentbox.PATTERN_LABELS[key], key)
        self.pattern.setCurrentIndex(bentbox.PATTERNS.index(s.pattern))
        self.pattern.setToolTip("Scharnier-Muster in den Ecken: gerade Schlitze (Standard), "
                                "Wellen oder Rauten (am weichsten)")
        self.cut = self._spin(s.cut_mm, bentbox.CUT_RANGE, 1, "BentCut",
                              "Gewünschte Schlitzlänge – wird an die Wandhöhe angepasst. "
                              "Länger = weicher")
        self.bridge = self._spin(s.bridge_mm, bentbox.BRIDGE_RANGE, 1, "BentBridge",
                                 "Steg zwischen zwei Schlitzen einer Linie; kürzer = weicher, "
                                 "unter 1,5 mm reißt er leicht")
        self.pitch = self._spin(s.pitch_mm, bentbox.PITCH_RANGE, 2, "BentPitch",
                                "Abstand der Schlitzlinien; kleiner = weicher, für 3 mm "
                                "Sperrholz meist 1,5–3 mm")
        self.lid = QCheckBox("Mit Deckel")
        self.lid.setObjectName("BentLid")
        self.lid.setChecked(s.lid)
        self.lid.setToolTip("Aus: offene Box ohne Deckel, Oberkante der Wand gerade")
        self.split = QCheckBox("Wand zweiteilig")
        self.split.setObjectName("BentSplit")
        self.split.setChecked(s.split)
        self.split.setToolTip("Die Wand als zwei Hälften schneiden (Stöße hinten und vorne in "
                              "der Mitte) – für Boxen, deren Wand länger ist als die "
                              "Arbeitsfläche")
        name = getattr(active_layer, "name", "")
        self._active_fills = layer_fills(active_layer)
        self._active_kerf = float(getattr(active_layer, "kerf_mm", 0.0) or 0.0)
        self.new_layer = QCheckBox(f"Neue Ebene „{CUT_LAYER_NAME}“")
        self.new_layer.setObjectName("BentNewLayer")
        self.new_layer.setChecked(self._active_fills or bool(getattr(active_layer, "locked", False)))
        self.new_layer.setToolTip("Neue Schneid-Ebene anlegen. Aus: Teile auf die aktive Ebene"
                                  + (f" „{name}“" if name else "")
                                  + " – sie muss schneiden (keine Füllung)")
        if touch:
            for w in (self.inner, self.lid, self.split, self.new_layer, self.pattern):
                w.setMinimumHeight(TOUCH_PX)
        # compact rows so the dialog stays on a 720 px tablet screen in touch mode
        form.addRow("Breite × Tiefe × Höhe", self._row(self.width_mm, QLabel("×"), self.depth_mm,
                                                       QLabel("×"), self.height_mm))
        form.addRow("Eckradius innen", self._row(self.radius, self.inner))
        form.addRow("Materialdicke / Zinken", self._row(self.thickness, self.finger))
        form.addRow("Kerf / Abstand", self._row(self.kerf, self.spacing))
        form.addRow("Scharnier", self._row(self.pattern, self.pitch))
        form.addRow("Schlitz / Steg", self._row(self.cut, self.bridge))
        form.addRow("", self._row(self.lid, self.split, self.new_layer))
        self.preview = BentBoxPreview()
        self.preview.setObjectName("BentPreview")
        form.addRow(self.preview)
        self.info = QLabel()
        self.info.setObjectName("BentInfo")
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
        for sb in (self.width_mm, self.depth_mm, self.height_mm, self.radius, self.thickness,
                   self.finger, self.kerf, self.spacing, self.cut, self.bridge, self.pitch):
            sb.valueChanged.connect(self._update)
        for cb in (self.inner, self.lid, self.split, self.new_layer):
            cb.toggled.connect(self._update)
        self.pattern.currentIndexChanged.connect(self._update)
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

    def spec(self) -> bentbox.BentBoxSpec:
        return bentbox.BentBoxSpec(
            width_mm=self.width_mm.value(), depth_mm=self.depth_mm.value(),
            height_mm=self.height_mm.value(), radius_mm=self.radius.value(),
            thickness_mm=self.thickness.value(), finger_mm=self.finger.value(),
            kerf_mm=self.kerf.value(), lid=self.lid.isChecked(), inner=self.inner.isChecked(),
            pattern=self.pattern.currentData(), cut_mm=self.cut.value(),
            bridge_mm=self.bridge.value(), pitch_mm=self.pitch.value(),
            split=self.split.isChecked(), spacing_mm=self.spacing.value()).normalized()

    def fill_layer(self) -> bool:
        """True: insert on a new cut layer (name kept from the code dialogs)."""
        return self.new_layer.isChecked()

    def _update(self) -> None:
        s = self.spec()
        try:
            placed, size, fits = bentbox.layout(s)
            text = bentbox.describe(s)
        except ValueError as exc:
            self.preview.set_layout([], (WORK_WIDTH_MM, WORK_HEIGHT_MM), False)
            self.info.setText(str(exc))
            self.ok_button.setEnabled(False)
            return
        self.preview.set_layout(placed, size, fits)
        if not fits:
            text += (f" – passt nicht auf die Arbeitsfläche ({WORK_WIDTH_MM:.0f} × "
                     f"{WORK_HEIGHT_MM:.0f} mm)" + ("" if s.split else " – „Wand zweiteilig“ "
                                                    "versuchen"))
        for w in bentbox.warnings(s):
            text += f" – {w}"
        if s.kerf_mm > 0 and self._active_kerf > 0 and not self.new_layer.isChecked():
            text += (f" – Achtung: die aktive Ebene hat schon {self._active_kerf:.2f} mm "
                     "Kerf-Versatz, das wäre doppelt (Kerf hier oder dort auf 0)")
        if not self.new_layer.isChecked() and self._active_fills:
            text += " – Achtung: aktive Ebene füllt, die Teile würden graviert statt geschnitten"
        self.info.setText(text)
        self.ok_button.setEnabled(fits)


def cut_layer(doc, active, spec: bentbox.BentBoxSpec) -> Layer:
    """New cut layer „Flex-Box“ (no fill) with the material thickness noted."""
    return Layer(CUT_LAYER_NAME, color=doc.next_layer_color(),
                 power=active.power if active else 50.0,
                 speed=active.speed if active else 1500.0,
                 fill_mode="none", thickness_mm=spec.normalized().thickness_mm)


def insert_bentbox(editor, spec: bentbox.BentBoxSpec, new_layer: bool = False,
                   center: tuple[float, float] | None = None) -> list[str]:
    """Insert the parts as one re-editable group (one undo step, optionally with a
    new cut layer). Raises ``ValueError`` (cannot be built, does not fit, layer locked)."""
    doc = editor.document
    s = bentbox.centered(spec, center)
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
    shapes = tag(bentbox.bentbox_shapes(s, layer_id), replace(s, x=0.0, y=0.0))
    stack = editor.undo_stack
    stack.beginMacro("Flex-Box einfügen")
    try:
        if layer is not None:
            stack.push(AddLayerCommand(doc, layer, 0))
        stack.push(AddShapesCommand(doc, shapes, "Flex-Box"))
    finally:
        stack.endMacro()
    ids = [sh.id for sh in shapes]
    editor.set_selection(ids)
    return ids


__all__ = ["BentBoxDialog", "BentBoxPreview", "CUT_LAYER_NAME", "cut_layer", "insert_bentbox"]
