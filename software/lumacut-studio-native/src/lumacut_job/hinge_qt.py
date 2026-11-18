"""Dialog „Flex-Scharnier…“ and insertion into the design (Qt side of :mod:`lumacut_job.hinge`).

Living hinge / kerf-bend pattern: field size, pattern (straight slits, waves,
diamonds), direction of the slits, slit length, bridge, line pitch, half slits
to the edge and an optional frame that cuts the part out. A bend helper turns
an inner radius and an angle into the field width across the bend. The cuts
are inserted as one re-editable group – on the active layer when it cuts (no
fill), otherwise on a new cut layer „Scharnier“ – in one undo step. With a
selection the field takes the selection's size and is centred on it.
"""

from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
                               QFormLayout, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QWidget)

from lumacut_canvas.commands import AddLayerCommand, AddShapesCommand
from lumacut_canvas.model import Layer

from . import hinge
from .generated import tag
from .qr_qt import layer_fills

CUT_LAYER_NAME = "Scharnier"
TOUCH_PX = 44


class HingePreview(QWidget):
    """The cuts of the part scaled into the widget (frame dark, slits blue)."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setMinimumSize(300, 140)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.cuts: list[tuple[tuple[tuple[float, float], ...], bool]] = []
        self.size_mm = (1.0, 1.0)
        self.fits = True

    def set_cuts(self, cuts, size_mm, fits: bool) -> None:
        self.cuts = list(cuts)
        self.size_mm = size_mm
        self.fits = fits
        self.update()

    def paintEvent(self, _event) -> None:   # pragma: no cover - drawing only
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor("#ffffff"))
        sw, sh = max(self.size_mm[0], 1e-6), max(self.size_mm[1], 1e-6)
        k = min((self.width() - 12) / sw, (self.height() - 12) / sh)
        p.translate((self.width() - sw * k) / 2.0, (self.height() - sh * k) / 2.0)
        p.setPen(QPen(QColor("#c62828") if not self.fits else QColor("#1565c0"), 1.0))
        for pts, closed in self.cuts:
            if not pts:
                continue
            path = QPainterPath(QPointF(pts[0][0] * k, pts[0][1] * k))
            for x, y in pts[1:]:
                path.lineTo(x * k, y * k)
            if closed:
                path.closeSubpath()
            p.drawPath(path)
        p.end()


class HingeDialog(QDialog):
    """Settings; ``spec()`` returns the normalized :class:`hinge.HingeSpec`."""

    def __init__(self, parent=None, spec: hinge.HingeSpec | None = None, active_layer=None,
                 touch: bool = False):
        super().__init__(parent)
        self.setWindowTitle("Flex-Scharnier")
        if spec is None:
            thick = float(getattr(active_layer, "thickness_mm", 0.0) or 0.0)
            spec = hinge.HingeSpec(thickness_mm=thick) if thick > 0 else hinge.HingeSpec()
        s = spec.normalized()
        self.touch = touch
        form = QFormLayout(self)
        self.pattern = QComboBox()
        self.pattern.setObjectName("HingePattern")
        for key in hinge.PATTERNS:
            self.pattern.addItem(hinge.PATTERN_LABELS[key], key)
        self.pattern.setCurrentIndex(hinge.PATTERNS.index(s.pattern))
        self.pattern.setToolTip("Gerade Schlitze: Standard, biegt in einer Richtung. Wellen: "
                                "etwas weicher, verdreht sich leichter. Rauten: Löcher statt "
                                "Schlitze – am weichsten, nimmt am meisten Material weg")
        self.width_mm = self._spin(s.width_mm, hinge.SIZE_RANGE, 1, "HingeWidth",
                                   "Breite des Scharnierfelds (X)")
        self.height_mm = self._spin(s.height_mm, hinge.SIZE_RANGE, 1, "HingeHeight",
                                    "Höhe des Scharnierfelds (Y)")
        self.horizontal = QCheckBox("Schlitze waagrecht")
        self.horizontal.setObjectName("HingeHorizontal")
        self.horizontal.setChecked(s.horizontal)
        self.horizontal.setToolTip("An: Schlitze waagrecht – das Teil biegt sich um eine "
                                   "waagrechte Achse, die Höhe ist die Biegestrecke. Aus: "
                                   "Schlitze senkrecht, die Breite ist die Biegestrecke")
        self.cut = self._spin(s.cut_mm, hinge.CUT_RANGE, 1, "HingeCut",
                              "Gewünschte Schlitzlänge (links) – wird so angepasst, dass die "
                              "Schlitze das Feld genau füllen. Länger = weicher")
        self.bridge = self._spin(s.bridge_mm, hinge.BRIDGE_RANGE, 1, "HingeBridge",
                                 "Steg = Material zwischen zwei Schlitzen einer Linie (rechts). "
                                 "Kürzer = weicher, unter 1,5 mm reißt er leicht")
        self.pitch = self._spin(s.pitch_mm, hinge.PITCH_RANGE, 2, "HingePitch",
                                "Abstand der Schlitzlinien (links). Kleiner = weicher, aber "
                                "dünne Stege verkohlen; für 3 mm Sperrholz meist 1,5–3 mm")
        self.thickness = self._spin(s.thickness_mm, hinge.THICKNESS_RANGE, 2, "HingeThickness",
                                    "Materialdicke (rechts) – für die Biege-Anzeige und den "
                                    "Biegerechner")
        self.open_edges = QCheckBox("Halbe Schlitze bis zum Rand")
        self.open_edges.setObjectName("HingeOpenEdges")
        self.open_edges.setChecked(s.open_edges)
        self.open_edges.setToolTip("An: jede zweite Linie läuft bis an den Feldrand (weicher). "
                                   "Aus: überall ein Steg am Rand (fester, Rand bleibt ganz)")
        self.frame = QCheckBox("Rahmen mitschneiden")
        self.frame.setObjectName("HingeFrame")
        self.frame.setChecked(s.frame)
        self.frame.setToolTip("Das Teil als Rechteck ausschneiden – mit Rand links und rechts "
                              "der Biegestrecke")
        self.margin = self._spin(s.margin_mm, hinge.MARGIN_RANGE, 1, "HingeMargin",
                                 "Rand ohne Schlitze auf beiden Seiten der Biegestrecke (nur "
                                 "mit Rahmen)")
        # bend helper: inner radius and angle -> width across the bend
        self.radius = self._spin(10.0, (0.0, 500.0), 1, "HingeRadius",
                                 "Innenradius der Rundung (z. B. Ecke einer Box)")
        self.angle = QDoubleSpinBox()
        self.angle.setObjectName("HingeAngle")
        self.angle.setRange(1.0, 360.0)
        self.angle.setDecimals(0)
        self.angle.setSuffix(" °")
        self.angle.setValue(90.0)
        self.angle.setToolTip("Biegewinkel (90° = Ecke einer Box, 180° = Halbrund)")
        self.calc = QPushButton("Breite berechnen")
        self.calc.setObjectName("HingeCalc")
        self.calc.setToolTip("Biegestrecke = (Innenradius + halbe Materialdicke) × Winkel – "
                             "setzt die Breite (bei waagrechten Schlitzen die Höhe)")
        self.calc.clicked.connect(self.apply_bend)
        if touch:
            self.angle.setMinimumHeight(TOUCH_PX)
            self.calc.setMinimumHeight(TOUCH_PX)
            self.pattern.setMinimumHeight(TOUCH_PX)
        name = getattr(active_layer, "name", "")
        self._active_fills = layer_fills(active_layer)
        self.new_layer = QCheckBox(f"Neue Ebene „{CUT_LAYER_NAME}“ zum Schneiden anlegen")
        self.new_layer.setObjectName("HingeNewLayer")
        self.new_layer.setChecked(self._active_fills or bool(getattr(active_layer, "locked", False)))
        self.new_layer.setToolTip("Aus: Schnitte auf die aktive Ebene" + (f" „{name}“" if name else "")
                                  + " – sie muss schneiden (keine Füllung)")
        for cb in (self.horizontal, self.open_edges, self.frame, self.new_layer):
            if touch:
                cb.setMinimumHeight(TOUCH_PX)
        form.addRow("Muster", self.pattern)
        form.addRow("Breite × Höhe", self._row(self.width_mm, QLabel("×"), self.height_mm))
        # compact rows so the dialog stays on a 720 px tablet screen in touch mode
        form.addRow("", self._row(self.horizontal, self.open_edges))
        form.addRow("Schlitz / Steg", self._row(self.cut, self.bridge))
        form.addRow("Linienabstand / Dicke", self._row(self.pitch, self.thickness))
        form.addRow("Rahmen / Rand", self._row(self.frame, self.margin))
        form.addRow("Biegung (Radius / Winkel)", self._row(self.radius, self.angle, self.calc))
        form.addRow("", self.new_layer)
        self.preview = HingePreview()
        self.preview.setObjectName("HingePreview")
        form.addRow(self.preview)
        self.info = QLabel()
        self.info.setObjectName("HingeInfo")
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
        for sb in (self.width_mm, self.height_mm, self.cut, self.bridge, self.pitch,
                   self.thickness, self.margin):
            sb.valueChanged.connect(self._update)
        for cb in (self.horizontal, self.open_edges, self.frame, self.new_layer):
            cb.toggled.connect(self._update)
        self.pattern.currentIndexChanged.connect(self._update)
        self._update()

    @staticmethod
    def _row(*widgets) -> QWidget:
        w = QWidget()
        lay = QHBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        for x in widgets:
            lay.addWidget(x, 0 if isinstance(x, (QLabel, QPushButton)) else 1)
        return w

    def _spin(self, value: float, rng, decimals: int, name: str, tip: str) -> QDoubleSpinBox:
        sb = QDoubleSpinBox()
        sb.setObjectName(name)
        sb.setRange(*rng)
        sb.setDecimals(decimals)
        sb.setSingleStep(1.0 if decimals <= 1 else 0.1)
        sb.setSuffix(" mm")
        sb.setValue(value)
        sb.setToolTip(tip)
        if self.touch:
            sb.setMinimumHeight(TOUCH_PX)
        return sb

    def spec(self) -> hinge.HingeSpec:
        return hinge.HingeSpec(width_mm=self.width_mm.value(), height_mm=self.height_mm.value(),
                               pattern=self.pattern.currentData(),
                               horizontal=self.horizontal.isChecked(),
                               cut_mm=self.cut.value(), bridge_mm=self.bridge.value(),
                               pitch_mm=self.pitch.value(), thickness_mm=self.thickness.value(),
                               open_edges=self.open_edges.isChecked(),
                               frame=self.frame.isChecked(),
                               margin_mm=self.margin.value()).normalized()

    def fill_layer(self) -> bool:
        """True: insert on a new cut layer."""
        return self.new_layer.isChecked()

    def apply_bend(self) -> None:
        """Set the size across the bend from the bend helper."""
        w = hinge.width_for(self.radius.value(), self.angle.value(), self.thickness.value())
        target = self.height_mm if self.horizontal.isChecked() else self.width_mm
        target.setValue(round(w, 1))

    def _update(self) -> None:
        s = self.spec()
        self.margin.setEnabled(s.frame)
        try:
            text = hinge.describe(s)
            cuts = hinge.part_cuts(replace(s, x=0.0, y=0.0))
        except ValueError as exc:
            self.preview.set_cuts([], (1.0, 1.0), False)
            self.info.setText(str(exc))
            self.ok_button.setEnabled(False)
            return
        fits = hinge.fits(s)
        self.preview.set_cuts(cuts, s.part_size(), fits)
        if not fits:
            text += " – passt nicht auf die Arbeitsfläche"
        for w in hinge.warnings(s):
            text += f" – {w}"
        if not self.new_layer.isChecked() and self._active_fills:
            text += " – Achtung: aktive Ebene füllt, die Schlitze würden graviert statt geschnitten"
        self.info.setText(text)
        self.ok_button.setEnabled(fits)


def cut_layer(doc, active, spec: hinge.HingeSpec) -> Layer:
    """New cut layer „Scharnier“ (no fill) with the material thickness noted."""
    return Layer(CUT_LAYER_NAME, color=doc.next_layer_color(),
                 power=active.power if active else 50.0,
                 speed=active.speed if active else 1500.0,
                 fill_mode="none", thickness_mm=spec.normalized().thickness_mm)


def insert_hinge(editor, spec: hinge.HingeSpec, new_layer: bool = False,
                 center: tuple[float, float] | None = None) -> list[str]:
    """Insert the hinge cuts as one re-editable group (one undo step, optionally
    with a new cut layer). Raises ``ValueError`` (field too short, too many
    slits, does not fit, layer locked)."""
    doc = editor.document
    s = hinge.centered(spec, center)
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
    shapes = tag(hinge.hinge_shapes(s, layer_id), replace(s, x=0.0, y=0.0))
    stack = editor.undo_stack
    stack.beginMacro("Flex-Scharnier einfügen")
    try:
        if layer is not None:
            stack.push(AddLayerCommand(doc, layer, 0))
        stack.push(AddShapesCommand(doc, shapes, "Flex-Scharnier"))
    finally:
        stack.endMacro()
    ids = [sh.id for sh in shapes]
    editor.set_selection(ids)
    return ids


def selection_field(editor) -> tuple[tuple[float, float], tuple[float, float]] | None:
    """(centre, (w, h)) of the selected objects (rotation-aware outline), None without
    a selection."""
    from .generated import unit_frame
    doc = editor.document
    parts = [doc.shape(i) for i in (getattr(editor, "selection", ()) or ()) if doc.has_shape(i)]
    if not parts:
        return None
    return unit_frame(parts, 0.0)


__all__ = ["CUT_LAYER_NAME", "HingeDialog", "HingePreview", "cut_layer", "insert_hinge",
           "selection_field"]
