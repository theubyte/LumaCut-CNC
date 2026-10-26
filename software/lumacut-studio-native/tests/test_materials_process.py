"""Kerf/Tabs/Lead-in-Startwerte je Material und Feature-Check gegen die Ebene."""

import pytest

from lumacut_canvas.model import Layer
from lumacut_materials import load_db
from lumacut_materials.db import MaterialError
from lumacut_materials.link import plan_layer_attrs
from lumacut_materials.process import (PROCESS_TABLE, layer_process_attrs, layer_process_fields,
                                       process_block, process_defaults)


@pytest.fixture(scope="module")
def db():
    return load_db()


def test_every_cuttable_material_has_process_block(db):
    for m in db.compatible():
        if m.can_cut:
            assert m.process == process_block(m.id), m.id
            assert m.id in PROCESS_TABLE
        else:
            assert m.process is None, m.id
    for m in db.incompatible():
        assert m.process is None


def test_defaults_grow_with_thickness_and_stay_plausible(db):
    for m in db.compatible():
        if not m.can_cut:
            continue
        thin, thick = min(m.thicknesses_mm), max(m.thicknesses_mm)
        a = process_defaults(db, m.id, thin)
        b = process_defaults(db, m.id, thick)
        assert 0.08 <= a.kerf_mm <= b.kerf_mm <= 0.8, m.id
        assert 0.2 <= a.tab_width_mm <= b.tab_width_mm <= 3.0
        assert a.tab_spacing_mm >= 20 and 0 <= a.lead_in_mm <= 2
        assert "Kerf" in a.summary()


def test_no_defaults_for_engrave_only_and_missing_thickness(db):
    assert process_defaults(db, "slate", 5) is None
    with pytest.raises(MaterialError):
        process_defaults(db, "mdf", 0)


def test_layer_has_cut_fields():
    assert set(layer_process_fields(Layer(name="x"))) == {"kerf_mm", "tab_width_mm",
                                                           "tab_spacing_mm", "lead_in_mm"}


def test_apply_sets_sizes_not_switches(db):
    d = process_defaults(db, "mdf", 3)
    attrs = plan_layer_attrs(db, "mdf", "cut", 3, layer=Layer(name="x"))
    assert attrs["kerf_mm"] == d.kerf_offset_mm == pytest.approx(d.kerf_mm / 2, abs=1e-3)
    assert attrs["tab_width_mm"] == d.tab_width_mm
    # Stegabstand/Anfahrt würden Stege/Anfahrt einschalten -> nur wenn schon aktiv
    assert "tab_spacing_mm" not in attrs and "lead_in_mm" not in attrs
    on = Layer(name="y", tab_spacing_mm=25.0, lead_in_mm=2.0)
    attrs = plan_layer_attrs(db, "mdf", "cut", 3, layer=on)
    assert attrs["tab_spacing_mm"] == d.tab_spacing_mm and attrs["lead_in_mm"] == d.lead_in_mm
    assert "kerf_mm" not in plan_layer_attrs(db, "mdf", "engrave_surface", 3,
                                             layer=Layer(name="x"))


def test_relink_keeps_manual_kerf(db):
    from PySide6.QtGui import QUndoStack
    from lumacut_canvas.commands import SetLayerAttrCommand, SetLayerAttrsCommand
    from lumacut_canvas.model import Document
    from lumacut_materials.link import install_link_hook
    install_link_hook(db)
    doc = Document()
    doc.add_layer(Layer(name="Teile"))
    lid = doc.layers[0].id
    st = QUndoStack()
    st.push(SetLayerAttrsCommand(doc, lid, plan_layer_attrs(db, "mdf", "cut", 3,
                                                            layer=doc.layer(lid))))
    st.push(SetLayerAttrCommand(doc, lid, "thickness_mm", 6.0))
    assert doc.layer(lid).kerf_mm == process_defaults(db, "mdf", 6).kerf_offset_mm
    st.push(SetLayerAttrCommand(doc, lid, "kerf_mm", 0.25))       # gemessen
    assert doc.layer(lid).material_link                           # Kerf löst nicht
    st.push(SetLayerAttrCommand(doc, lid, "thickness_mm", 3.0))
    layer = doc.layer(lid)
    assert layer.kerf_mm == 0.25 and layer.passes == plan_layer_attrs(db, "mdf", "cut", 3)["passes"]
    assert layer.tab_width_mm == process_defaults(db, "mdf", 3).tab_width_mm
