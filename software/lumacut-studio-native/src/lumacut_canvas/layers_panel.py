"""Ebenen-Panel: Liste der Ebenen und Parameter der aktiven Ebene.

Jede Zeile zeigt Farbe, Name und die Laser-Einstellung der Ebene in
Kurzform ("80 % · 600 mm/min · 1×"), damit die Zuordnung Ebene → Parameter
ohne Klicken sichtbar ist. Darunter werden die Parameter der aktiven Ebene
bearbeitet. Alle Änderungen laufen über den Undo-Stack des Editors.

Der Abschnitt „Material der Ebene“ wählt ein Material (eingebaute
Startwerte aus :data:`material.BUILTIN_MATERIALS`, eigene Presets aus
``lumacut_materials`` falls vorhanden, oder „ohne Material“) und stellt
Dicke, Zieltiefe und Tiefe je Durchgang ein. Die Durchgänge werden daraus
automatisch abgeleitet, solange der Nutzer sie nicht überschreibt; ein
Abzeichen zeigt „auto“ bzw. „manuell“, „Auto“ setzt sie zurück. Darunter
steht der Tiefenplan je Durchgang mit Warnung, wenn die Zieltiefe nicht
erreicht wird. Jede Änderung ist genau ein Undo-Schritt.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Callable

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QUndoStack
from PySide6.QtWidgets import (QColorDialog, QGridLayout, QComboBox, QDoubleSpinBox, QFormLayout, QFrame, QGroupBox,
                               QCheckBox, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
                               QPushButton, QScrollArea, QSizePolicy, QSpinBox, QToolButton, QVBoxLayout, QWidget)

from . import hatch as _hatch
from . import icons, theme
from .fit import enable_touch_scroll
from .commands import (AddLayerCommand, MoveLayerCommand, RemoveLayerCommand, SetLayerAttrCommand,
                       SetLayerAttrsCommand)
from .material import (BUILTIN_MATERIALS, DEPTH_PER_PASS_RANGE, THICKNESS_RANGE, Material,
                       builtin_material, derived_passes, layer_pass_plan,
                       material_from_preset, material_layer_attrs)
from .model import FILL_LAYER_FIELDS, MATERIAL_LAYER_FIELDS, PASSES_RANGE, POWER_RANGE, SPEED_RANGE, Document, Layer

# Undo-Beschriftungen der Füll-Felder (ohne commands.py anzufassen).
for _k, _v in {"line_interval_mm": "Linienabstand", "hatch_angle": "Schraffurwinkel",
               "fill_mode": "Füllmodus"}.items():
    SetLayerAttrCommand.LABELS.setdefault(_k, _v)

class _FillParamCommand(SetLayerAttrCommand):
    """Linienabstand/Winkel: aufeinanderfolgende Änderungen = ein Undo-Schritt."""

    def mergeWith(self, other) -> bool:  # noqa: N802 - Qt API
        if (isinstance(other, _FillParamCommand) and other.layer_id == self.layer_id
                and other.attr == self.attr):
            self.new = other.new
            return True
        return False


NO_MATERIAL = "— ohne Material —"
START_VALUES_HINT = ("Eingebaute Materialien sind editierbare Startwerte, nicht validiert – "
                     "vor dem Schneiden einen Materialtest machen.")


def layer_summary(layer: Layer) -> str:
    text = f"{layer.power:g} % · {layer.speed:g} mm/min · {layer.passes}×"
    if layer.fill_mode != "none":
        text += f" · {_hatch.FILL_LABELS[layer.fill_mode]} {_mm(layer.line_interval_mm)} mm"
    return f"{text} · {layer.material}" if layer.material else text


def _mm(v: float) -> str:
    return f"{v:.2f}".rstrip("0").rstrip(".").replace(".", ",")


def passes_are_auto(layer: Any) -> bool | None:
    """True: Durchgänge = abgeleiteter Wert; False: manuell überschrieben;
    None: keine Tiefenplanung (Durchgänge sind dann ein freier Wert)."""
    d = derived_passes(layer)
    return None if d is None else int(layer.passes) == d


def pass_plan_text(layer: Any) -> tuple[str, bool]:
    """Kurzer Tiefenplan der Ebene und ob gewarnt werden muss."""
    plan = layer_pass_plan(layer)
    if plan is None:
        if getattr(layer, "material", "") or getattr(layer, "thickness_mm", 0):
            return "Keine Tiefenplanung – „Tiefe/Durchgang“ setzen.", False
        return "", False
    cut = [d for d in plan.pass_depths if d > 0]
    extra = plan.passes - len(cut)
    if len(cut) <= 6:
        steps = " + ".join(_mm(d) for d in cut) or "0"
    else:
        steps = f"{len(cut)} × ≤ {_mm(plan.depth_per_pass_mm)}"
    text = f"{plan.passes}× · {steps} = {_mm(plan.total_mm)} mm"
    if extra:
        text += f" (+{extra} Nachschnitt)"
    if not plan.reaches_target:
        return (f"⚠ {text}\nZieltiefe {_mm(plan.depth_mm)} mm nicht erreicht – "
                "Durchgänge erhöhen."), True
    return f"✓ {text}", False


def _default_presets() -> list:
    """Eigene Presets aus ``lumacut_materials`` (nur lesen), sonst leer."""
    try:
        from lumacut_materials.dialog import default_preset_path
        from lumacut_materials.presets import PresetStore
        return list(PresetStore(default_preset_path()).presets)
    except Exception:  # noqa: BLE001 – Adapter optional / Datei kaputt
        return []


class _LayerRow(QWidget):
    def __init__(self, panel: "LayersPanel", layer: Layer, count: int) -> None:
        super().__init__()
        self.setObjectName("LayerRow")
        self.panel = panel
        self.layer_id = layer.id
        lay = QHBoxLayout(self)
        lay.setContentsMargins(6, 4, 4, 4)
        lay.setSpacing(6)
        swatch = QFrame()
        swatch.setFixedSize(6, 30)
        swatch.setStyleSheet(f"background: {layer.color}; border-radius: 3px;")
        lay.addWidget(swatch)
        text = QVBoxLayout()
        text.setSpacing(0)
        name = QLabel(f"{layer.name}  <span style='color:#93a1b5;font-weight:400'>({count})</span>")
        name.setObjectName("LayerName")
        summary = QLabel(layer_summary(layer))
        summary.setObjectName("LayerSummary")
        summary.setToolTip(layer_summary(layer))
        # Schmales Panel: Texte werden gekürzt statt das Panel zu verbreitern.
        for lab in (name, summary):
            lab.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
            lab.setMinimumWidth(40)
        text.addWidget(name)
        text.addWidget(summary)
        lay.addLayout(text, 1)
        self.eye = self._toggle("eye" if layer.visible else "eye_off",
                                "Ausblenden" if layer.visible else "Einblenden",
                                lambda: panel.toggle(self.layer_id, "visible"))
        self.lock = self._toggle("lock" if layer.locked else "unlock",
                                 "Entsperren" if layer.locked else "Sperren",
                                 lambda: panel.toggle(self.layer_id, "locked"))
        lay.addWidget(self.eye)
        lay.addWidget(self.lock)

    def _toggle(self, icon_name: str, tip: str, slot) -> QToolButton:
        b = QToolButton()
        b.setIcon(icons.icon(icon_name))
        b.setIconSize(QSize(24, 24) if self.panel.touch_mode else QSize(18, 18))
        b.setToolTip(tip)
        b.setAutoRaise(True)
        b.clicked.connect(slot)
        return b


class LayersPanel(QWidget):
    def __init__(self, document: Document, undo_stack: QUndoStack, parent: QWidget | None = None,
                 presets: Callable[[], list] | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("LayersPanel")
        self.setAttribute(Qt.WA_StyledBackground, True)
        # Eigenes Stylesheet wie CanvasEditor: unabhängig davon, wann/wie das
        # Hauptfenster seine Styles setzt.
        self.setStyleSheet(theme.CANVAS_QSS)
        self.doc = document
        self.stack = undo_stack
        self._signature: tuple | None = None
        self._updating = False
        self._preset_source = presets or _default_presets
        self._presets: list = []
        self.touch_mode = False

        # Inhalt in einer Scrollfläche: auf kleinen Bildschirmen (Surface Pro)
        # senkrecht scrollbar statt abgeschnitten; mit dem Finger ziehbar.
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.scroll = QScrollArea()
        self.scroll.setObjectName("LayersScroll")
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        content = QWidget()
        content.setObjectName("LayersContent")
        content.setAttribute(Qt.WA_StyledBackground, True)
        self.scroll.setWidget(content)
        outer.addWidget(self.scroll)
        enable_touch_scroll(self.scroll)

        root = QVBoxLayout(content)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)
        head = QGridLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.setHorizontalSpacing(6)
        head.setVerticalSpacing(6)
        title = QLabel("Ebenen")
        title.setObjectName("SectionTitle")
        self._head, self._head_title, self._head_buttons = head, title, []
        for icon_name, tip, slot in (("plus", "Neue Ebene", self.add_layer),
                                     ("up", "Ebene nach oben", lambda: self.move_active(-1)),
                                     ("down", "Ebene nach unten", lambda: self.move_active(1)),
                                     ("delete", "Ebene löschen (mit Objekten)", self.remove_active)):
            b = QToolButton()
            b.setIcon(icons.icon(icon_name))
            b.setIconSize(QSize(18, 18))
            b.setToolTip(tip)
            b.clicked.connect(slot)
            self._head_buttons.append(b)
        self._layout_head()
        root.addLayout(head)

        self.list = QListWidget()
        self.list.setSpacing(1)
        self.list.setMinimumHeight(140)
        self.list.currentRowChanged.connect(self._row_changed)
        self.list.itemDoubleClicked.connect(lambda _: (self.name.setFocus(), self.name.selectAll()))
        root.addWidget(self.list, 1)
        hint = QLabel("Oben liegende Ebenen werden zuletzt gelasert. Neue Objekte landen auf der aktiven Ebene.")
        hint.setObjectName("Hint")
        hint.setWordWrap(True)
        root.addWidget(hint)

        root.addWidget(self._build_material_box())

        self.params = QGroupBox("Laser-Einstellung der Ebene")
        form = QFormLayout(self.params)
        form.setRowWrapPolicy(QFormLayout.WrapLongRows)  # schmal: Feld unter die Beschriftung
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        form.setHorizontalSpacing(10)
        form.setVerticalSpacing(8)
        self.name = QLineEdit()
        self.name.editingFinished.connect(self._name_edited)
        self.color = QPushButton()
        self.color.setObjectName("ColorButton")
        self.color.setToolTip("Ebenenfarbe wählen")
        self.color.clicked.connect(self._pick_color)
        self.power = QDoubleSpinBox()
        self.power.setRange(*POWER_RANGE)
        self.power.setDecimals(0)
        self.power.setSuffix(" %")
        self.speed = QDoubleSpinBox()
        self.speed.setRange(*SPEED_RANGE)
        self.speed.setDecimals(0)
        self.speed.setSingleStep(50)
        self.speed.setSuffix(" mm/min")
        self.passes = QSpinBox()
        self.passes.setRange(*PASSES_RANGE)
        self.passes.setSuffix(" ×")
        for spin, attr in ((self.power, "power"), (self.speed, "speed"), (self.passes, "passes")):
            spin.setKeyboardTracking(False)
            spin.setAlignment(Qt.AlignRight)
            spin.valueChanged.connect(lambda v, a=attr: self._param_edited(a, v))
        form.addRow("Name", self.name)
        form.addRow("Farbe", self.color)
        form.addRow("Leistung", self.power)
        form.addRow("Geschwindigkeit", self.speed)
        passes_row = QHBoxLayout()
        passes_row.setSpacing(6)
        passes_row.addWidget(self.passes, 1)
        self.pass_badge = QLabel()
        self.pass_badge.setObjectName("PassBadge")
        self.pass_badge.setAlignment(Qt.AlignCenter)
        self.pass_badge.setMinimumWidth(64)
        passes_row.addWidget(self.pass_badge)
        self.auto_passes = QPushButton("Auto")
        self.auto_passes.setObjectName("AutoPasses")
        self.auto_passes.setToolTip("Durchgänge wieder aus Zieltiefe und Tiefe/Durchgang ableiten")
        self.auto_passes.clicked.connect(self.reset_passes)
        passes_row.addWidget(self.auto_passes)
        form.addRow("Durchgänge", passes_row)
        self.pass_plan = QLabel()
        self.pass_plan.setObjectName("PassPlan")
        self.pass_plan.setWordWrap(True)
        form.addRow(self.pass_plan)
        root.addWidget(self.params)
        root.addWidget(self._build_fill_box())

        self.reload_presets()
        self.doc.add_listener(self.refresh)
        self.refresh()

    def _build_material_box(self) -> QGroupBox:
        box = QGroupBox("Material der Ebene")
        self.material_box = box
        form = QFormLayout(box)
        form.setRowWrapPolicy(QFormLayout.WrapLongRows)
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        form.setHorizontalSpacing(10)
        form.setVerticalSpacing(8)
        self.material = QComboBox()
        self.material.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.material.setMinimumContentsLength(8)
        self.material.setToolTip(START_VALUES_HINT)
        self.material.activated.connect(self._material_chosen)
        self.thickness = self._mm_spin(THICKNESS_RANGE, 0.5, "–")
        self.thickness.setToolTip("Materialdicke")
        self.target_depth = self._mm_spin(THICKNESS_RANGE, 0.5, "= Dicke")
        self.target_depth.setToolTip("Zieltiefe; „= Dicke“ schneidet ganz durch")
        self.depth_per_pass = self._mm_spin(DEPTH_PER_PASS_RANGE, 0.05, "aus")
        self.depth_per_pass.setToolTip("Tiefe, die ein Durchgang abträgt; „aus“ = keine Tiefenplanung")
        for spin, attr in ((self.thickness, "thickness_mm"), (self.target_depth, "target_depth_mm"),
                           (self.depth_per_pass, "depth_per_pass_mm")):
            spin.valueChanged.connect(lambda v, a=attr: self._material_field_edited(a, v))
        form.addRow("Material", self.material)
        form.addRow("Dicke", self.thickness)
        form.addRow("Zieltiefe", self.target_depth)
        form.addRow("Tiefe/Durchg.", self.depth_per_pass)
        note = QLabel(START_VALUES_HINT)
        note.setObjectName("Hint")
        note.setWordWrap(True)
        form.addRow(note)
        return box

    def _build_fill_box(self) -> QGroupBox:
        """Vektor-Füllung der Ebene (Schraffur/Kreuzschraffur, hatch.py)."""
        box = QGroupBox("Füllung der Ebene")
        self.fill_box = box
        form = QFormLayout(box)
        form.setRowWrapPolicy(QFormLayout.WrapLongRows)
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        form.setHorizontalSpacing(10)
        form.setVerticalSpacing(8)
        self.fill_mode = QComboBox()
        for mode in _hatch.FILL_MODES:
            self.fill_mode.addItem(_hatch.FILL_LABELS[mode], mode)
        self.fill_mode.setToolTip("Geschlossene Objekte (Rechteck, Ellipse, Polygon, Text) mit "
                                  "parallelen Linien füllen; Löcher bleiben frei")
        self.fill_mode.activated.connect(self._fill_mode_chosen)
        self.fill_interval = QDoubleSpinBox()
        self.fill_interval.setRange(*_hatch.INTERVAL_RANGE)
        self.fill_interval.setDecimals(2)
        self.fill_interval.setSingleStep(0.05)
        self.fill_interval.setSuffix(" mm")
        self.fill_interval.setToolTip("Abstand der Schraffurlinien")
        self.fill_angle = QDoubleSpinBox()
        self.fill_angle.setRange(0.0, 179.0)
        self.fill_angle.setDecimals(0)
        self.fill_angle.setSingleStep(15)
        self.fill_angle.setWrapping(True)
        self.fill_angle.setSuffix(" °")
        self.fill_angle.setToolTip("Linienwinkel (0° = waagerecht); Kreuzschraffur zusätzlich +90°")
        for spin, attr in ((self.fill_interval, "line_interval_mm"), (self.fill_angle, "hatch_angle")):
            spin.setKeyboardTracking(False)
            spin.setAlignment(Qt.AlignRight)
            spin.valueChanged.connect(lambda v, a=attr: self._param_edited(a, v))
        self.fill_outline = QCheckBox("Kontur mitlasern")
        self.fill_outline.setToolTip("Aus: nur die Füllung lasern (z. B. Text gravieren)")
        self.fill_bidir = QCheckBox("Bidirektional")
        self.fill_bidir.setToolTip("Jede zweite Linie rückwärts – kürzere Leerfahrten")
        for box_, attr in ((self.fill_outline, "hatch_outline"), (self.fill_bidir, "hatch_bidirectional")):
            box_.toggled.connect(lambda on, a=attr: self._fill_flag_toggled(a, on))
        form.addRow("Füllmodus", self.fill_mode)
        form.addRow("Linienabstand", self.fill_interval)
        form.addRow("Winkel", self.fill_angle)
        form.addRow(self.fill_outline)    # untereinander: passt auch in schmale Seitenleisten
        form.addRow(self.fill_bidir)
        return box

    def _show_fill(self, layer: Layer) -> None:
        self.fill_mode.setCurrentIndex(max(0, self.fill_mode.findData(layer.fill_mode)))
        self.fill_interval.setValue(layer.line_interval_mm)
        self.fill_angle.setValue(layer.hatch_angle)
        self.fill_outline.setChecked(layer.hatch_outline)
        self.fill_bidir.setChecked(layer.hatch_bidirectional)
        on = layer.fill_mode != "none"
        for w in (self.fill_interval, self.fill_angle, self.fill_outline, self.fill_bidir):
            w.setEnabled(on)

    def _fill_mode_chosen(self, index: int) -> None:
        layer = self.doc.active_layer
        mode = self.fill_mode.itemData(index)
        if self._updating or layer is None or mode == layer.fill_mode:
            return
        attrs = {"fill_mode": mode}
        if mode == "crosshatch" and layer.fill_mode == "none" and layer.hatch_angle == 0:
            attrs["hatch_angle"] = 45.0   # übliche Kreuzschraffur 45°/135°
        self.stack.push(SetLayerAttrsCommand(self.doc, layer.id, attrs,
                                             f"Füllmodus: {_hatch.FILL_LABELS[mode]}"))

    def _fill_flag_toggled(self, attr: str, on: bool) -> None:
        layer = self.doc.active_layer
        if self._updating or layer is None or getattr(layer, attr) == on:
            return
        label = "Kontur mitlasern" if attr == "hatch_outline" else "Bidirektional"
        self.stack.push(SetLayerAttrsCommand(self.doc, layer.id, {attr: bool(on)}, label))

    @staticmethod
    def _mm_spin(rng: tuple[float, float], step: float, zero_text: str) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setRange(*rng)
        spin.setDecimals(2)
        spin.setSingleStep(step)
        spin.setSuffix(" mm")
        spin.setSpecialValueText(zero_text)
        spin.setKeyboardTracking(False)
        spin.setAlignment(Qt.AlignRight)
        return spin

    def reload_presets(self) -> None:
        """Presets neu von der Quelle lesen (z. B. nach dem Speichern im Bibliotheks-Dialog)."""
        try:
            self._presets = [p for p in self._preset_source() if getattr(p, "name", "")]
        except Exception:  # noqa: BLE001
            self._presets = []
        self._signature = None
        if hasattr(self, "pass_plan"):
            self.refresh()

    def _layout_head(self) -> None:
        """Kopfzeile: Maus = Titel und Knöpfe in einer Zeile; Touch = Knöpfe in
        eigener Zeile unter dem Titel (sonst wäre das Panel zu breit)."""
        head = self._head
        for w in (self._head_title, *self._head_buttons):
            head.removeWidget(w)
        head.setColumnStretch(0, 1)
        if self.touch_mode:
            head.addWidget(self._head_title, 0, 0, 1, 5)
            for i, b in enumerate(self._head_buttons):
                head.addWidget(b, 1, i + 1)
        else:
            head.addWidget(self._head_title, 0, 0)
            for i, b in enumerate(self._head_buttons):
                head.addWidget(b, 0, i + 1)

    def set_touch_mode(self, on: bool) -> None:
        """Größere Zeilen, Knöpfe und Eingabefelder für Finger (Theme-QSS mit
        ``touch="true"``); vgl. :meth:`CanvasEditor.set_touch_mode`."""
        on = bool(on)
        if on == self.touch_mode:
            return
        self.touch_mode = on
        self._layout_head()
        self.setProperty("touch", "true" if on else "false")
        self.setStyleSheet("")
        self.setStyleSheet(theme.CANVAS_QSS)
        size = QSize(24, 24) if on else QSize(18, 18)
        for b in self.findChildren(QToolButton):
            b.setIconSize(size)
        self._signature = None
        self.refresh()

    def showEvent(self, event) -> None:  # noqa: N802
        # Ein Hauptfenster mit setPalette() vererbt seine Palette beim
        # Einhängen und überschreibt damit die QSS-Farben der Kinder. Einmal
        # neu polieren, sobald das Panel endgültig im Fenster sitzt.
        if not getattr(self, "_restyled", False):
            self._restyled = True
            self.setStyleSheet("")
            self.setStyleSheet(theme.CANVAS_QSS)
        super().showEvent(event)

    # --- Anzeige ----------------------------------------------------------
    def _make_signature(self) -> tuple:
        counts = {l.id: 0 for l in self.doc.layers}
        for s in self.doc.shapes:
            counts[s.layer_id] = counts.get(s.layer_id, 0) + 1
        return (self.doc.active_layer_id,
                tuple((l.id, l.name, l.color, l.power, l.speed, l.passes, l.visible, l.locked,
                       *(getattr(l, f) for f in MATERIAL_LAYER_FIELDS + FILL_LAYER_FIELDS),
                       counts[l.id])
                      for l in self.doc.layers))

    def refresh(self) -> None:
        """Nur neu aufbauen, wenn sich Ebenen tatsächlich geändert haben
        (Dokument meldet auch jede Mausbewegung beim Verschieben)."""
        sig = self._make_signature()
        if sig == self._signature:
            return
        self._signature = sig
        self._updating = True
        self.list.clear()
        counts = {entry[0]: entry[-1] for entry in sig[1]}
        for layer in self.doc.layers:
            item = QListWidgetItem()
            item.setData(Qt.UserRole, layer.id)
            row = _LayerRow(self, layer, counts[layer.id])
            item.setSizeHint(QSize(0, 56 if self.touch_mode else 46))
            self.list.addItem(item)
            self.list.setItemWidget(item, row)
        active = self.doc.active_layer
        if active is not None:
            self.list.setCurrentRow(self.doc.layer_index(active.id))
            self.params.setEnabled(True)
            if not self.name.hasFocus():
                self.name.setText(active.name)
            self.color.setStyleSheet(f"background: {active.color};")
            self.power.setValue(active.power)
            self.speed.setValue(active.speed)
            self.passes.setValue(active.passes)
            self.material_box.setEnabled(True)
            self._show_material(active)
            self.fill_box.setEnabled(True)
            self._show_fill(active)
        else:
            self.params.setEnabled(False)
            self.material_box.setEnabled(False)
            self.fill_box.setEnabled(False)
        self._updating = False

    def _show_material(self, layer: Layer) -> None:
        combo = self.material
        combo.clear()
        combo.addItem(NO_MATERIAL, ("none", ""))
        for m in BUILTIN_MATERIALS:
            combo.addItem(m.name, ("builtin", m.name))
            combo.setItemData(combo.count() - 1, m.notes or START_VALUES_HINT, Qt.ToolTipRole)
        if self._presets:
            combo.insertSeparator(combo.count())
            for p in self._presets:
                combo.addItem(f"{p.name} (Preset)", ("preset", p.name))
                summary = getattr(p, "summary", None)
                if callable(summary):
                    combo.setItemData(combo.count() - 1, summary(), Qt.ToolTipRole)
        idx = 0
        if layer.material:
            idx = next((i for i in range(combo.count())
                        if (combo.itemData(i) or ("", ""))[1] == layer.material), -1)
            if idx < 0:   # Material aus Datei, das hier nicht in der Liste steht
                combo.insertItem(1, f"{layer.material} (eigene Werte)", ("current", layer.material))
                idx = 1
        combo.setCurrentIndex(idx)
        self.thickness.setValue(layer.thickness_mm)
        self.target_depth.setValue(layer.target_depth_mm)
        self.depth_per_pass.setValue(layer.depth_per_pass_mm)
        auto = passes_are_auto(layer)
        self.pass_badge.setVisible(auto is not None)
        self.pass_badge.setText("auto" if auto else "manuell")
        self.pass_badge.setProperty("auto", "true" if auto else "false")
        self.pass_badge.setToolTip("Aus Zieltiefe ÷ Tiefe/Durchgang abgeleitet" if auto else
                                   "Von Hand überschrieben – „Auto“ setzt den abgeleiteten Wert")
        self.auto_passes.setVisible(auto is not None)
        self.auto_passes.setEnabled(auto is False)
        text, warn = pass_plan_text(layer)
        self.pass_plan.setText(text)
        self.pass_plan.setVisible(bool(text))
        self.pass_plan.setProperty("warn", "true" if warn else "false")
        for w in (self.pass_badge, self.pass_plan):   # dynamische Property neu polieren
            w.style().unpolish(w)
            w.style().polish(w)

    # --- Aktionen ---------------------------------------------------------
    def _row_changed(self, row: int) -> None:
        if self._updating or row < 0:
            return
        lid = self.list.item(row).data(Qt.UserRole)
        self.doc.set_active_layer(lid)  # Auswahl der aktiven Ebene ist kein Undo-Schritt

    def add_layer(self) -> None:
        n = len(self.doc.layers) + 1
        layer = Layer(name=f"Ebene {n}", color=self.doc.next_layer_color())
        idx = self.doc.layer_index(self.doc.active_layer_id) if self.doc.active_layer_id else 0
        self.stack.push(AddLayerCommand(self.doc, layer, idx))

    def remove_active(self) -> None:
        if self.doc.active_layer_id and len(self.doc.layers) > 1:
            self.stack.push(RemoveLayerCommand(self.doc, self.doc.active_layer_id))

    def move_active(self, delta: int) -> None:
        lid = self.doc.active_layer_id
        if lid is None:
            return
        idx = self.doc.layer_index(lid)
        if 0 <= idx + delta < len(self.doc.layers):
            self.stack.push(MoveLayerCommand(self.doc, lid, idx + delta))

    def toggle(self, layer_id: str, attr: str) -> None:
        value = not getattr(self.doc.layer(layer_id), attr)
        self.stack.push(SetLayerAttrCommand(self.doc, layer_id, attr, value))

    def _param_edited(self, attr: str, value: float) -> None:
        if self._updating or self.doc.active_layer is None:
            return
        layer = self.doc.active_layer
        value = int(value) if attr == "passes" else float(value)
        if getattr(layer, attr) != value:
            cls = _FillParamCommand if attr in FILL_LAYER_FIELDS else SetLayerAttrCommand
            self.stack.push(cls(self.doc, layer.id, attr, value))

    # --- Material -----------------------------------------------------------
    def _material_for(self, kind: str, name: str) -> Material | None:
        if kind == "builtin":
            return builtin_material(name)
        if kind == "preset":
            for p in self._presets:
                if p.name == name:
                    return material_from_preset(p)
        return None

    def _material_chosen(self, index: int) -> None:
        layer = self.doc.active_layer
        if self._updating or layer is None or index < 0:
            return
        kind, name = self.material.itemData(index) or ("", "")
        if kind == "none":
            if not layer.material and not layer.thickness_mm and not layer.depth_per_pass_mm:
                return
            attrs = {"material": "", "thickness_mm": 0.0, "target_depth_mm": 0.0,
                     "depth_per_pass_mm": 0.0}
            self.stack.push(SetLayerAttrsCommand(self.doc, layer.id, attrs, "Material entfernen"))
            return
        m = self._material_for(kind, name)
        if m is None or m.name == layer.material:
            return
        # Wie CanvasEditor.apply_material: ein Undo-Schritt, Zieltiefe bleibt.
        attrs = material_layer_attrs(m, layer.target_depth_mm, apply_settings=True)
        self.stack.push(SetLayerAttrsCommand(self.doc, layer.id, attrs, f"Material: {m.name}"))

    def _material_field_edited(self, attr: str, value: float) -> None:
        layer = self.doc.active_layer
        if self._updating or layer is None:
            return
        value = round(float(value), 3)
        if abs(getattr(layer, attr) - value) < 1e-9:
            return
        attrs: dict[str, Any] = {attr: value}
        # Automatische Durchgänge folgen der Änderung; ein manueller Wert bleibt.
        if passes_are_auto(layer) is not False:
            fields = {f: getattr(layer, f) for f in MATERIAL_LAYER_FIELDS}
            fields.update(attrs, passes=layer.passes)
            n = derived_passes(SimpleNamespace(**fields))
            if n is not None and n != layer.passes:
                attrs["passes"] = n
        labels = {"thickness_mm": "Materialdicke", "target_depth_mm": "Zieltiefe",
                  "depth_per_pass_mm": "Tiefe je Durchgang"}
        self.stack.push(SetLayerAttrsCommand(self.doc, layer.id, attrs, labels[attr]))

    def reset_passes(self) -> None:
        """Durchgänge auf den abgeleiteten Wert zurücksetzen (ein Undo-Schritt)."""
        layer = self.doc.active_layer
        n = derived_passes(layer) if layer is not None else None
        if n is not None and n != layer.passes:
            self.stack.push(SetLayerAttrCommand(self.doc, layer.id, "passes", n))

    def _name_edited(self) -> None:
        layer = self.doc.active_layer
        name = self.name.text().strip()
        if layer is not None and name and name != layer.name:
            self.stack.push(SetLayerAttrCommand(self.doc, layer.id, "name", name))

    def _pick_color(self) -> None:
        layer = self.doc.active_layer
        if layer is None:
            return
        c = QColorDialog.getColor(QColor(layer.color), self, "Ebenenfarbe")
        if c.isValid() and c.name() != layer.color:
            self.stack.push(SetLayerAttrCommand(self.doc, layer.id, "color", c.name()))
