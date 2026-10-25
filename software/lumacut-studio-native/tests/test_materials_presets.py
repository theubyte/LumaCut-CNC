"""Presets: erzeugen, speichern, auf Ebenen anwenden."""

import pytest

from lumacut_canvas.model import Document
from lumacut_materials import load_db
from lumacut_materials.presets import Preset, PresetStore, apply_to_layer, make_preset


def test_make_preset_for_each_operation():
    db = load_db()
    m = db.material("basswood_solid")
    for op in m.operations():
        p = make_preset(db, m.id, op, thickness_mm=5)
        assert p.passes >= 1 and 1 <= p.power_pct <= 100 and p.speed_mm_min > 0
        assert p.laser_id == "lasertree_lt80w_aa_pro"
        assert p.summary()
    cut = make_preset(db, m.id, "cut", 5)
    assert cut.z_step_mm > 0 and cut.focus_start_mm < 0
    assert "5 mm" in cut.name
    p20 = make_preset(db, m.id, "cut", 5, laser_id="diode_20w")
    assert p20.passes <= cut.passes


def test_store_roundtrip(tmp_path):
    db = load_db()
    path = tmp_path / "sub" / "presets.json"
    store = PresetStore(path)
    p = make_preset(db, "mdf", "cut", 3, name="Mein MDF")
    store.put(p)
    store.put(make_preset(db, "mdf", "engrave_surface", name="Mein MDF"))  # ersetzt
    store.put(make_preset(db, "slate", "engrave_surface"))
    store.save()
    again = PresetStore(path)
    assert len(again.presets) == 2 and again.get("Mein MDF").op == "engrave_surface"
    again.remove("Mein MDF")
    assert "Mein MDF" not in again.names()
    (tmp_path / "x.json").write_text('{"format": "other"}', encoding="utf-8")
    with pytest.raises(ValueError):
        PresetStore(tmp_path / "x.json")


def test_from_dict_ignores_unknown_keys():
    d = make_preset(load_db(), "cork", "cut", 3).to_dict()
    d["future_field"] = 1
    assert Preset.from_dict(d).material_id == "cork"


def test_apply_to_layer():
    doc = Document()
    lid = doc.active_layer_id
    p = make_preset(load_db(), "basswood_plywood", "cut", 5)
    values = apply_to_layer(doc, lid, p)
    layer = doc.layer(lid)
    assert (layer.power, layer.speed, layer.passes) == (p.power_pct, p.speed_mm_min, p.passes)
    assert layer.z_step == pytest.approx(p.z_step_mm)
    assert values["z_step"] == p.z_step_mm
