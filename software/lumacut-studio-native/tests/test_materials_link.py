"""Materialbibliothek ↔ Ebene: zuweisen, verknüpfen, Neuplanung bei Dickenänderung."""

import pytest

from lumacut_canvas.commands import (SetLayerAttrCommand, SetLayerAttrsCommand,
                                     derived_layer_attrs, register_layer_attr_hook,
                                     unregister_layer_attr_hook)
from lumacut_canvas.material import derived_passes
from lumacut_canvas.model import Document, Layer
from lumacut_materials import load_db
from lumacut_materials.link import (install_link_hook, layer_attr_hook, link_status, make_ref,
                                    parse_ref, plan_layer_attrs, preset_layer_attrs)
from lumacut_materials.presets import make_preset

LASER = "lasertree_lt80w_aa_pro"


@pytest.fixture(scope="module")
def db():
    return load_db()


@pytest.fixture
def stack(qapp, db):
    from PySide6.QtGui import QUndoStack
    install_link_hook(db)
    return QUndoStack()


def _doc():
    doc = Document()
    return doc, doc.active_layer_id


def test_ref_roundtrip():
    ref = make_ref("mdf", "cut", LASER)
    assert parse_ref(ref) == ("mdf", "cut", LASER)
    for bad in ("", "MDF", "lib:mdf/cut", "lib://x"):
        assert parse_ref(bad) is None


def test_layer_link_fields_persist_and_normalize():
    layer = Layer(name="A", material="MDF", material_ref=make_ref("mdf", "cut", LASER),
                  material_link=True, thickness_mm=3)
    d = layer.to_dict()
    assert d["material_ref"].startswith("lib:") and d["material_link"] is True
    assert Layer.from_dict(d) == layer
    assert "material_ref" not in Layer(name="B").to_dict()
    assert Layer(name="C", material_link=True).normalized().material_link is False


@pytest.mark.parametrize("t", [1.5, 3, 4, 5, 6, 8, 10])
def test_planned_passes_match_canvas_depth_plan(db, t):
    m = db.material("basswood_plywood")
    if t not in m.thicknesses_mm:
        pytest.skip("Dicke nicht in Tabelle")
    attrs = plan_layer_attrs(db, "basswood_plywood", "cut", t, LASER)
    layer = Layer(name="x").normalized()
    for k, v in attrs.items():
        setattr(layer, k, v)
    layer = layer.normalized()
    assert derived_passes(layer) == attrs["passes"]


def test_linked_thickness_change_replans_in_one_undo_step(stack, db):
    doc, lid = _doc()
    stack.push(SetLayerAttrsCommand(doc, lid, plan_layer_attrs(db, "basswood_plywood", "cut", 3, LASER)))
    before = doc.layer(lid).to_dict()
    p3 = doc.layer(lid).passes
    n = stack.count()
    # So ändert das Ebenen-Panel die Dicke (inkl. eigener Durchgangs-Ableitung nicht nötig)
    stack.push(SetLayerAttrsCommand(doc, lid, {"thickness_mm": 6.0}, "Materialdicke"))
    assert stack.count() == n + 1
    layer = doc.layer(lid)
    exp = plan_layer_attrs(db, "basswood_plywood", "cut", 6, LASER)
    assert (layer.power, layer.speed, layer.passes, layer.z_step) == (
        exp["power"], exp["speed"], exp["passes"], exp["z_step"])
    assert layer.passes > p3 and layer.material_link
    assert derived_passes(layer) == layer.passes
    stack.undo()
    assert doc.layer(lid).to_dict() == before
    stack.redo()
    assert doc.layer(lid).thickness_mm == 6.0


def test_single_attr_command_also_replans(stack, db):
    doc, lid = _doc()
    stack.push(SetLayerAttrsCommand(doc, lid, plan_layer_attrs(db, "mdf", "cut", 3, LASER)))
    speed3 = doc.layer(lid).speed
    stack.push(SetLayerAttrCommand(doc, lid, "thickness_mm", 6.0))
    assert doc.layer(lid).speed < speed3
    stack.undo()
    assert doc.layer(lid).speed == speed3 and doc.layer(lid).thickness_mm == 3.0


def test_panel_style_thickness_edit_with_passes_keeps_linked_plan(stack, db):
    """Das Panel schickt bei Auto-Durchgängen ``passes`` mit – das ist keine
    manuelle Änderung, solange es zum neuen Plan passt; Werte aus dem Befehl
    haben Vorrang, Leistung/Geschwindigkeit kommen aus der Neuplanung."""
    doc, lid = _doc()
    stack.push(SetLayerAttrsCommand(doc, lid, plan_layer_attrs(db, "basswood_plywood", "cut", 3, LASER)))
    stale = doc.layer(lid).passes + 1
    stack.push(SetLayerAttrsCommand(doc, lid, {"thickness_mm": 6.0, "passes": stale}, "Materialdicke"))
    layer = doc.layer(lid)
    exp = plan_layer_attrs(db, "basswood_plywood", "cut", 6, LASER)
    assert layer.thickness_mm == 6.0 and layer.material_link
    assert (layer.passes, layer.speed) == (exp["passes"], exp["speed"])


def test_manual_change_unlinks_and_assign_does_not_follow(stack, db):
    doc, lid = _doc()
    stack.push(SetLayerAttrsCommand(doc, lid, plan_layer_attrs(db, "mdf", "cut", 3, LASER)))
    stack.push(SetLayerAttrCommand(doc, lid, "power", 80.0))
    assert doc.layer(lid).material_link is False and doc.layer(lid).power == 80.0
    speed = doc.layer(lid).speed
    stack.push(SetLayerAttrCommand(doc, lid, "thickness_mm", 6.0))
    assert doc.layer(lid).speed == speed
    stack.undo()
    stack.undo()
    assert doc.layer(lid).material_link is True

    doc2, lid2 = _doc()
    stack.push(SetLayerAttrsCommand(doc2, lid2, plan_layer_attrs(db, "mdf", "cut", 3, LASER, link=False)))
    speed = doc2.layer(lid2).speed
    stack.push(SetLayerAttrCommand(doc2, lid2, "thickness_mm", 6.0))
    assert doc2.layer(lid2).speed == speed
    assert "zugewiesen" in link_status(doc2.layer(lid2))


def test_other_material_clears_reference(stack, db):
    doc, lid = _doc()
    stack.push(SetLayerAttrsCommand(doc, lid, plan_layer_attrs(db, "mdf", "cut", 3, LASER)))
    stack.push(SetLayerAttrsCommand(doc, lid, {"material": "Pappe", "thickness_mm": 2.0}))
    layer = doc.layer(lid)
    assert layer.material_ref == "" and layer.material_link is False
    stack.undo()
    assert doc.layer(lid).material_ref.startswith("lib:mdf/")


def test_engrave_depth_change_replans(stack, db):
    doc, lid = _doc()
    stack.push(SetLayerAttrsCommand(doc, lid, plan_layer_attrs(db, "basswood_plywood", "engrave_deep", 3, LASER)))
    p0 = doc.layer(lid).passes
    stack.push(SetLayerAttrCommand(doc, lid, "target_depth_mm", 2.0))
    layer = doc.layer(lid)
    assert layer.passes >= p0 and layer.material_link
    assert derived_passes(layer) == layer.passes


def test_unplannable_thickness_unlinks(stack, db):
    doc, lid = _doc()
    stack.push(SetLayerAttrsCommand(doc, lid, plan_layer_attrs(db, "paper", "cut", 0.2, LASER)))
    stack.push(SetLayerAttrCommand(doc, lid, "thickness_mm", 40.0))
    layer = doc.layer(lid)
    assert layer.thickness_mm == 40.0
    assert layer.material_link is False or layer.passes >= 1


def test_hook_errors_never_block_changes(qapp):
    doc, lid = _doc()

    def broken(layer, changes):
        raise RuntimeError("kaputt")

    register_layer_attr_hook(broken)
    try:
        assert derived_layer_attrs(doc.layer(lid), {"power": 20.0}) == {}

        def override(layer, changes):
            return {"passes": 7, "speed": 1.0, "__override__": ("passes",)}

        register_layer_attr_hook(override)
        assert derived_layer_attrs(doc.layer(lid), {"passes": 2, "speed": 900.0}) == {"passes": 7}
        unregister_layer_attr_hook(override)
        cmd = SetLayerAttrCommand(doc, lid, "power", 20.0)
        cmd.redo()
        assert doc.layer(lid).power == 20.0
    finally:
        unregister_layer_attr_hook(broken)


def test_layers_without_reference_are_untouched(db):
    layer = Layer(name="frei", thickness_mm=3).normalized()
    assert layer_attr_hook(layer, {"thickness_mm": 6.0}) == {}


def test_preset_attrs_assign_with_reference(db):
    p = make_preset(db, "birch_plywood", "cut", 3.0, LASER)
    attrs = preset_layer_attrs(db, p)
    assert attrs["material_link"] is False and attrs["material_ref"] == make_ref("birch_plywood", "cut", p.laser_id)
    layer = Layer(name="x")
    for k, v in attrs.items():
        setattr(layer, k, v)
    assert derived_passes(layer.normalized()) == p.passes


def test_layers_panel_thickness_spin_replans_linked_layer(stack, db):
    """Echter UI-Pfad: Dicke im Ebenen-Panel ändern → ein Undo-Schritt, neu geplant."""
    from lumacut_canvas.layers_panel import LayersPanel
    doc, lid = _doc()
    panel = LayersPanel(doc, stack, presets=lambda: [])
    stack.push(SetLayerAttrsCommand(doc, lid, plan_layer_attrs(db, "basswood_plywood", "cut", 3, LASER)))
    before = doc.layer(lid).to_dict()
    n = stack.count()
    panel._material_field_edited("thickness_mm", 8.0)
    layer = doc.layer(lid)
    exp = plan_layer_attrs(db, "basswood_plywood", "cut", 8, LASER)
    assert stack.count() == n + 1
    assert (layer.passes, layer.speed, layer.z_step) == (exp["passes"], exp["speed"], exp["z_step"])
    assert layer.material_link
    stack.undo()
    assert doc.layer(lid).to_dict() == before
    panel.deleteLater()
