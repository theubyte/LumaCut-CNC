"""Material-Grundlage: Durchgänge/Tiefe je Ebene, Serialisierung, G-Code-Hook."""

import pytest

from lumacut_canvas.gcode import depth_comment_hook, document_to_gcode
from lumacut_canvas.material import (BUILTIN_MATERIALS, Material, builtin_material,
                                     derived_passes, layer_pass_plan, material_from_preset,
                                     material_layer_attrs, passes_for_depth, plan_passes)
from lumacut_canvas.model import Document, Geometry, Layer, Shape


def test_passes_for_depth_ceil_and_clamp():
    assert passes_for_depth(3.0, 1.0) == 3          # exakt, kein Fließkomma-Extra
    assert passes_for_depth(3.0, 0.7) == 5
    assert passes_for_depth(0.3, 1.0) == 1
    assert passes_for_depth(0.9, 0.3) == 3
    assert passes_for_depth(100.0, 0.1) == 30       # PASSES_RANGE
    assert passes_for_depth(3.0, 0.0) == 1


def test_plan_passes_lists_depths_and_total():
    p = plan_passes(3.0, 0.8)
    assert p.passes == 4 and p.pass_depths == (0.8, 0.8, 0.8, 0.6)
    assert p.total_mm == pytest.approx(3.0) and p.reaches_target
    assert p.cumulative[-1] == pytest.approx(3.0)
    # Override: zu wenige Durchgänge -> Ziel nicht erreicht, zu viele -> Nachschnitte mit 0.
    few = plan_passes(3.0, 0.8, passes=2)
    assert few.total_mm == pytest.approx(1.6) and not few.reaches_target
    more = plan_passes(3.0, 1.0, passes=5)
    assert more.pass_depths == (1.0, 1.0, 1.0, 0.0, 0.0) and more.reaches_target
    with pytest.raises(ValueError):
        plan_passes(3.0, 0.0)


def test_layer_plan_uses_target_or_thickness_and_respects_override():
    layer = Layer("Schneiden", thickness_mm=4.0, depth_per_pass_mm=1.5, passes=1)
    assert derived_passes(layer) == 3
    assert layer_pass_plan(layer).passes == 1        # eingestellter Wert gilt
    layer.passes = 3
    assert layer_pass_plan(layer).reaches_target
    layer.target_depth_mm = 1.0                      # Gravur statt Durchschnitt
    assert derived_passes(layer) == 1
    assert layer_pass_plan(Layer("x")) is None and derived_passes(Layer("x")) is None


def test_builtin_presets_are_labelled_starting_values():
    assert len(BUILTIN_MATERIALS) >= 3
    for m in BUILTIN_MATERIALS:
        assert m.thickness_mm > 0 and m.depth_per_pass_mm > 0
        assert "Startwert" in m.notes and "nicht validiert" in m.notes
        assert Material.from_dict(m.to_dict()) == m


def test_material_attrs_derive_passes_and_editor_applies_in_one_undo_step(qapp):
    from lumacut_canvas.editor import CanvasEditor

    m = builtin_material("MDF 3 mm")
    attrs = material_layer_attrs(m)
    assert attrs["passes"] == 4 and attrs["thickness_mm"] == 3.0 and attrs["material"] == m.name
    assert "power" not in material_layer_attrs(m, apply_settings=False)
    ed = CanvasEditor()
    try:
        lid = ed.document.active_layer_id
        before = ed.document.layer(lid).to_dict()
        ed.apply_material(m, target_depth_mm=1.5)
        layer = ed.document.layer(lid)
        assert (layer.material, layer.passes, layer.target_depth_mm) == (m.name, 2, 1.5)
        assert ed.undo_stack.count() == 1
        ed.undo_stack.undo()
        assert ed.document.layer(lid).to_dict() == before
    finally:
        ed.undo_stack.setClean()
        ed.close()


def test_from_lumacut_materials_preset():
    class P:  # wie lumacut_materials.presets.Preset
        name, thickness_mm, depth_per_pass_mm = "Birke 4", 4.0, 0.9
        power_pct, speed_mm_min, z_step_mm = 90.0, 280.0, 0.5
    m = material_from_preset(P())
    assert (m.name, m.thickness_mm, m.depth_per_pass_mm, m.z_step) == ("Birke 4", 4.0, 0.9, 0.5)


def test_serialization_backward_compatible_and_versioned():
    doc = Document()
    plain = doc.to_dict()["layers"][0]
    assert not {"material", "thickness_mm", "target_depth_mm", "depth_per_pass_mm"} & set(plain)
    lid = doc.active_layer_id
    doc.update_layer(lid, material="MDF", thickness_mm=3.0, depth_per_pass_mm=99.0)
    data = doc.to_dict()
    assert data["version"] == 3 and data["layers"][0]["depth_per_pass_mm"] == 10.0  # begrenzt
    again = Document.from_dict(data)
    assert again.to_dict() == data
    data["version"] = 2                              # alte Datei ohne Material-Felder
    for k in ("material", "thickness_mm", "depth_per_pass_mm"):
        del data["layers"][0][k]
    old = Document.from_dict(data)
    assert old.layers[0].depth_per_pass_mm == 0 and old.layers[0].material == ""


def _doc_with_rect(**layer):
    doc = Document()
    doc.update_layer(doc.active_layer_id, **layer)
    doc.add_shape(Shape("rect", Geometry(10, 10, 20, 10), doc.active_layer_id))
    return doc


def test_gcode_unchanged_by_default_and_hook_adds_depths(qapp):
    base = document_to_gcode(_doc_with_rect(passes=3))
    planned = _doc_with_rect(passes=3, thickness_mm=2.5, depth_per_pass_mm=1.0)
    assert document_to_gcode(planned) == base                 # Material ändert nichts
    out = document_to_gcode(planned, pass_hook=depth_comment_hook)
    assert "; DEPTH 1.000 TOTAL 1.000" in out and "; DEPTH 0.500 TOTAL 2.500" in out
    assert [l for l in out.splitlines() if not l.startswith("; DEPTH")] == base.splitlines()
    # Ebenen ohne Planung rufen den Hook nicht auf.
    assert document_to_gcode(_doc_with_rect(passes=3), pass_hook=depth_comment_hook) == base
    with pytest.raises(ValueError):
        document_to_gcode(planned, pass_hook=lambda *a: ["G0 Z1\nM3"])
