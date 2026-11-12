"""Eckenradius in der PropertyBar (LightBurn *Shape Properties › Corner Radius*):
Feld „Ecken“, sichtbar solange nur Rechtecke ausgewählt sind.

Ein Schritt im Feld ist ein Undo-Schritt für alle ausgewählten Rechtecke; der
Wert gilt in mm (Anzeige in mm oder Zoll wie die anderen Längenfelder) und wird
je Rechteck auf die halbe kürzere Seite begrenzt.
"""

from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget

from . import corners
from .edit_commands import ReplaceShapeCommand
from .model import Shape
from .unit_ui import LengthSpin

TIP = ("Eckenradius aller vier Ecken (wie LightBurn „Corner Radius“): positiv = abgerundet, "
       "negativ = nach innen gewölbt. Bleibt beim Skalieren gleich groß und wird auf die "
       "halbe kürzere Seite begrenzt; 0 = scharfe Ecken.")


class CornerRadiusControls(QWidget):
    """Sichtbar, solange nur (bearbeitbare) Rechtecke ausgewählt sind."""

    def __init__(self, editor) -> None:
        super().__init__()
        self.setObjectName("CornerRadiusControls")
        self.ed = editor
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        self.label = QLabel("Ecken")
        self.label.setToolTip(TIP)
        self.radius = LengthSpin(-corners.RADIUS_LIMIT_MM, corners.RADIUS_LIMIT_MM)
        self.radius.setObjectName("CornerRadius")
        self.radius.setToolTip(TIP)
        self.radius.valueChanged.connect(self._edited)
        lay.addSpacing(8)
        lay.addWidget(self.label)
        lay.addWidget(self.radius)
        self._updating = False
        self.setVisible(False)

    def rects(self) -> list[Shape]:
        doc = self.ed.document
        shapes = [doc.shape(i) for i in self.ed.selection if doc.has_shape(i)]
        if not shapes or any(s.kind != "rect" for s in shapes):
            return []
        return [s for s in shapes if doc.is_editable(s.id)]

    def refresh(self) -> None:
        rects = self.rects()
        self.setVisible(bool(rects))
        if not rects or self.radius.hasFocus():
            return
        self._updating = True
        try:
            self.radius.setValue(corners.effective_radius(rects[0]))
        finally:
            self._updating = False

    def _edited(self, value: float) -> None:
        if self._updating:
            return
        self.apply(value)

    def apply(self, value: float) -> list[Shape]:
        """Radius ``value`` (mm) auf alle ausgewählten Rechtecke setzen (ein Undo-Schritt)."""
        rects = self.rects()
        new = [corners.with_corner_radius(s, value) for s in rects]
        new = [n for n, s in zip(new, rects) if n.corner_radius != s.corner_radius or n.tabs != s.tabs]
        if not new:
            return []
        stack = self.ed.undo_stack
        label = "Eckenradius"
        if len(new) == 1:
            stack.push(ReplaceShapeCommand(self.ed.document, new[0], label))
        else:
            stack.beginMacro(label)
            try:
                for s in new:
                    stack.push(ReplaceShapeCommand(self.ed.document, s, label))
            finally:
                stack.endMacro()
        text = corners.describe(new)
        if any(abs(n.corner_radius) < abs(value) - 1e-6 for n in new):
            text += " · auf die halbe kürzere Seite begrenzt"
        lost = sum(len(s.tabs) for s in rects) - sum(len(s.tabs) for s in self.rects())
        if lost > 0:
            text += f" · {lost} manuelle(r) Steg(e) entfernt"
        self.ed.notify(text)
        return new
