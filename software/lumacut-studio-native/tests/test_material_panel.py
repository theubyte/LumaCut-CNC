"""Material-Abschnitt im Ebenen-Panel (offscreen)."""

from types import SimpleNamespace

import pytest
from PySide6.QtGui import QUndoStack

from lumacut_canvas.layers_panel import (NO_MATERIAL, START_VALUES_HINT, LayersPanel,
                                         pass_plan_text, passes_are_auto)
from lumacut_canvas.material import BUILTIN_MATERIALS
from lumacut_canvas.model import Document, Layer

PRESET = SimpleNamespace(name="Mein MDF", thickness_mm=4.0, depth_per_pass_mm=0.8, power_pct=90.0,
                         speed_mm_min=200.0, z_step_mm=0.1, summary=lambda: "90 %, 200 mm/min")


@pytest.fixture
def panel(qapp):
    doc = Document()
    stack = QUndoStack()
    p = LayersPanel(doc, stack, presets=lambda: [PRESET])
    p.resize(320, 800)
    p.show()
    qapp.processEvents()
    yield p
    p.close()


def choose(panel, text):
    i = panel.material.findText(text)
    assert i >= 0, text
    panel.material.setCurrentIndex(i)
    panel.material.activated.emit(i)


def test_combo_lists_none_builtins_and_presets(panel):
    items = [panel.material.itemText(i) for i in range(panel.material.count())]
    assert items[0] == NO_MATERIAL and panel.material.currentIndex() == 0
    for m in BUILTIN_MATERIALS:
        assert m.name in items
    assert "Mein MDF (Preset)" in items
    assert "nicht validiert" in START_VALUES_HINT
    i = panel.material.findText(BUILTIN_MATERIALS[0].name)
    assert "Startwert" in panel.material.itemData(i, 3)            # Qt.ToolTipRole
    assert panel.pass_plan.isHidden() and panel.pass_badge.isHidden()


def test_choose_builtin_is_one_undo_step_and_auto_passes(panel):
    doc, stack = panel.doc, panel.stack
    layer = doc.active_layer
    choose(panel, "Pappelsperrholz 3 mm")
    assert stack.count() == 1
    assert (layer.material, layer.thickness_mm, layer.depth_per_pass_mm, layer.passes) == (
        "Pappelsperrholz 3 mm", 3.0, 1.0, 3)
    assert (layer.power, layer.speed) == (100.0, 300.0)
    assert panel.thickness.value() == 3.0 and panel.passes.value() == 3
    assert panel.pass_badge.text() == "auto" and not panel.auto_passes.isEnabled()
    assert panel.pass_plan.text() == "✓ 3× · 1 + 1 + 1 = 3 mm"
    assert "Pappelsperrholz" in panel.list.itemWidget(panel.list.item(0)).findChildren(
        type(panel.pass_plan))[1].text()                            # Zeilen-Kurzinfo
    stack.undo()
    assert (layer.material, layer.thickness_mm, layer.passes) == ("", 0.0, 1)
    assert panel.material.currentIndex() == 0


def test_fields_update_auto_passes_and_manual_override(panel):
    stack, layer = panel.stack, panel.doc.active_layer
    choose(panel, "Pappelsperrholz 3 mm")
    panel.target_depth.setValue(2.0)                                # Gravurtiefe statt Durchschnitt
    assert (layer.target_depth_mm, layer.passes) == (2.0, 2) and stack.count() == 2
    panel.depth_per_pass.setValue(0.75)
    assert layer.passes == 3 and stack.count() == 3
    assert panel.pass_plan.text() == "✓ 3× · 0,75 + 0,75 + 0,5 = 2 mm"
    panel.passes.setValue(1)                                        # manuell überschreiben
    assert passes_are_auto(layer) is False
    assert panel.pass_badge.text() == "manuell" and panel.auto_passes.isEnabled()
    assert panel.pass_plan.property("warn") == "true" and panel.pass_plan.text().startswith("⚠")
    panel.thickness.setValue(4.0)                                   # manueller Wert bleibt
    assert layer.passes == 1
    panel.auto_passes.click()
    assert layer.passes == 3 and panel.pass_badge.text() == "auto"
    n = stack.count()
    stack.undo()
    assert layer.passes == 1 and stack.count() == n
    panel.passes.setValue(5)                                        # mehr als nötig: Nachschnitt
    assert "(+2 Nachschnitt)" in panel.pass_plan.text()


def test_no_material_clears_and_preset_applies(panel):
    layer = panel.doc.active_layer
    choose(panel, "Mein MDF (Preset)")
    assert (layer.material, layer.thickness_mm, layer.depth_per_pass_mm, layer.passes) == (
        "Mein MDF", 4.0, 0.8, 5)
    assert (layer.power, layer.speed, layer.z_step) == (90.0, 200.0, 0.1)
    choose(panel, NO_MATERIAL)
    assert (layer.material, layer.thickness_mm, layer.depth_per_pass_mm) == ("", 0.0, 0.0)
    assert panel.pass_plan.isHidden() and panel.stack.count() == 2
    choose(panel, NO_MATERIAL)                                      # nichts zu tun
    assert panel.stack.count() == 2


def test_unknown_material_from_file_and_layer_switch(qapp):
    doc = Document()
    kork = doc.active_layer_id
    doc.update_layer(kork, material="Kork 2 mm", thickness_mm=2.0)
    zwei = doc.add_layer(Layer(name="Zwei")).id
    p = LayersPanel(doc, QUndoStack(), presets=lambda: 1 / 0)       # Quelle kaputt -> leer
    doc.set_active_layer(kork)
    assert p.material.currentText() == "Kork 2 mm (eigene Werte)"
    assert "Tiefe/Durchgang" in p.pass_plan.text()
    doc.set_active_layer(zwei)
    assert p.material.currentIndex() == 0 and p.thickness.value() == 0.0
    assert not any("Preset" in p.material.itemText(i) for i in range(p.material.count()))
    p.close()


def test_pass_plan_text_long_plans():
    layer = SimpleNamespace(material="x", thickness_mm=10.0, target_depth_mm=0.0,
                            depth_per_pass_mm=1.0, passes=10)
    assert pass_plan_text(layer) == ("✓ 10× · 10 × ≤ 1 = 10 mm", False)
    assert pass_plan_text(SimpleNamespace(material="", thickness_mm=0.0, target_depth_mm=0.0,
                                          depth_per_pass_mm=0.0, passes=1)) == ("", False)
