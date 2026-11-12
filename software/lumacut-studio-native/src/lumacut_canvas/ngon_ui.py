"""Vieleck / Stern in der PropertyBar (LightBurn *Polygon* › Anzahl Seiten, xTool
„Polygon“ / „Stern“): Felder „Seiten“, „Stern“ und „Innen“.

Sichtbar, solange nur (bearbeitbare) Vielecke / Sterne ausgewählt sind oder das
Werkzeug „Vieleck / Stern“ aktiv ist. Eine Änderung gilt für alle ausgewählten Vielecke
/ Sterne (ein Undo-Schritt) und wird zugleich die Vorgabe des Werkzeugs für das
nächste Objekt (wie LightBurn, das die zuletzt gewählte Seitenzahl behält).
"""

from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QLabel, QSpinBox, QToolButton, QWidget

from . import ngon
from .edit_commands import ReplaceShapeCommand
from .model import Shape

SIDES_TIP = ("Anzahl der Ecken des Vielecks bzw. der Zacken des Sterns (3–100). Mittelpunkt, "
             "Größe und Drehung bleiben.")
STAR_TIP = "Stern statt Vieleck: zwischen zwei Spitzen liegt eine Innenecke."
INNER_TIP = ("Innenradius des Sterns in Prozent des Außenradius (5–95 %): klein = spitze "
             "Zacken, groß = flache Zacken. Klassischer fünfzackiger Stern ≈ 38 %.")


class NgonControls(QWidget):
    def __init__(self, editor) -> None:
        super().__init__()
        self.setObjectName("NgonControls")
        self.ed = editor
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        self.sides_label = QLabel("Seiten")
        self.sides_label.setToolTip(SIDES_TIP)
        self.sides = QSpinBox()
        self.sides.setObjectName("NgonSides")
        self.sides.setRange(ngon.MIN_SIDES, ngon.MAX_SIDES)
        self.sides.setKeyboardTracking(False)
        self.sides.setToolTip(SIDES_TIP)
        self.sides.setFixedWidth(64)
        self.sides.valueChanged.connect(self._sides_edited)
        self.star = QToolButton()
        self.star.setObjectName("NgonStar")
        self.star.setText("Stern")
        self.star.setCheckable(True)
        self.star.setToolTip(STAR_TIP)
        self.star.toggled.connect(self._star_toggled)
        self.inner_label = QLabel("Innen")
        self.inner_label.setToolTip(INNER_TIP)
        self.inner = QSpinBox()
        self.inner.setObjectName("NgonInner")
        self.inner.setRange(round(ngon.INNER_MIN * 100), round(ngon.INNER_MAX * 100))
        self.inner.setSuffix(" %")
        self.inner.setKeyboardTracking(False)
        self.inner.setToolTip(INNER_TIP)
        self.inner.setFixedWidth(76)
        self.inner.setValue(round(ngon.DEFAULT_STAR_INNER * 100))
        self.inner.valueChanged.connect(self._inner_edited)
        lay.addSpacing(8)
        for w in (self.sides_label, self.sides, self.star, self.inner_label, self.inner):
            lay.addWidget(w)
        self._updating = False
        self.setVisible(False)

    # --- Zustand --------------------------------------------------------------
    def targets(self) -> list[Shape]:
        """Ausgewählte Vielecke / Sterne – leer, sobald etwas anderes mit ausgewählt ist."""
        doc = self.ed.document
        shapes = [doc.shape(i) for i in self.ed.selection if doc.has_shape(i)]
        if not shapes or any(ngon.spec_of(s) is None for s in shapes):
            return []
        if not all(doc.is_editable(s.id) for s in shapes):
            return []
        return shapes

    def _tool_active(self) -> bool:
        from .tools import Tool
        tools = getattr(self.ed, "tools", None)
        return tools is not None and tools.tool == Tool.NGON

    def refresh(self) -> None:
        targets = self.targets()
        self.setVisible(bool(targets) or self._tool_active())
        spec = ngon.spec_of(targets[0]) if targets else self.ed.tools.ngon_spec
        if self.sides.hasFocus() or self.inner.hasFocus():
            return
        self._updating = True
        try:
            self.sides.setValue(spec[0])
            self.star.setChecked(ngon.is_star(spec))
            if ngon.is_star(spec):
                self.inner.setValue(round(spec[1] * 100))
            self.inner.setEnabled(ngon.is_star(spec))
            self.inner_label.setEnabled(ngon.is_star(spec))
        finally:
            self._updating = False

    # --- Eingaben -------------------------------------------------------------
    def _sides_edited(self, value: int) -> None:
        if not self._updating:
            self.apply(sides=value)

    def _star_toggled(self, on: bool) -> None:
        self.inner.setEnabled(on)
        self.inner_label.setEnabled(on)
        if not self._updating:
            self.apply(inner=self.inner.value() / 100 if on else 0.0)

    def _inner_edited(self, value: int) -> None:
        if not self._updating and self.star.isChecked():
            self.apply(inner=value / 100)

    def apply(self, sides=None, inner=None) -> list[Shape]:
        """Seiten / Innenradius setzen (``None`` = je Objekt unverändert): Vorgabe des
        Werkzeugs und alle ausgewählten Vielecke / Sterne (ein Undo-Schritt)."""
        tools = self.ed.tools
        cur = tools.ngon_spec
        tools.ngon_spec = ngon.normalize(cur[0] if sides is None else sides,
                                         cur[1] if inner is None else inner)
        targets = self.targets()
        if not targets:
            if self._tool_active():
                self.ed.notify(f"Vieleck / Stern: nächstes Objekt {ngon.label(tools.ngon_spec)}")
            return []
        new = [ngon.with_spec(s, sides, inner) for s in targets]
        new = [n for n, s in zip(new, targets) if n is not s]
        if not new:
            return []
        stack = self.ed.undo_stack
        label = "Vieleck / Stern"
        if len(new) == 1:
            stack.push(ReplaceShapeCommand(self.ed.document, new[0], label))
        else:
            stack.beginMacro(label)
            try:
                for s in new:
                    stack.push(ReplaceShapeCommand(self.ed.document, s, label))
            finally:
                stack.endMacro()
        text = ngon.describe(new)
        lost = sum(len(s.tabs) for s in targets if any(n.id == s.id for n in new))
        if lost:
            text += f" · {lost} manuelle(r) Steg(e) entfernt"
        self.ed.notify(text)
        return new
