"""Eine Materialwahl wie Android (Anforderungen 2026-10-26 §9.1)."""
from __future__ import annotations

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parent))

from lumacut_canvas.material_picker import (MaterialChoice, apply_choice, layer_operation,  # noqa: E402
                                            material_choices)
from lumacut_canvas.model import Layer  # noqa: E402
from lumacut_materials import load_db  # noqa: E402
from lumacut_materials.presets import Preset  # noqa: E402


@pytest.fixture(scope="module")
def db():
    return load_db()


def test_choices_group_material_and_thickness(db):
    cs = material_choices(db)
    keys = {c.key for c in cs}
    assert "mdf|3" in keys and "birch_plywood|4" in keys
    assert all(db.material(c.material_id).compatible for c in cs)
    mdf = next(c for c in cs if c.key == "mdf|3")
    assert mdf.title == "MDF · 3 mm" and mdf.processes == ["Schneiden", "Gravieren"]
    assert [c.name for c in cs] == sorted((c.name for c in cs), key=str.lower)


def test_search_filters_by_name_process_thickness(db):
    assert {c.material_id for c in material_choices(db, query="mdf")} == {"mdf"}
    assert all("Schneiden" in c.processes for c in material_choices(db, query="schneiden"))
    assert all(c.thickness_mm == 0.5 for c in material_choices(db, query="0,5 mm"))


def test_pi_presets_add_thickness_and_win(db):
    p = Preset(name="MDF 7", material_id="mdf", op="cut", laser_id="", thickness_mm=7.0,
               power_pct=90, speed_mm_min=150, passes=3)
    c = next(c for c in material_choices(db, [p]) if c.key == "mdf|7")
    assert c.presets == {"cut": p}


def _doc_editor():
    from lumacut_canvas.editor import CanvasEditor
    return CanvasEditor()


def test_layer_operation_mapping(db):
    c = next(c for c in material_choices(db) if c.key == "mdf|3")
    assert layer_operation(Layer(name="Schneiden"), [], c) == "cut"
    assert layer_operation(Layer(name="Gravieren"), [], c) == "engrave_surface"
    assert layer_operation(Layer(name="Linie"), [], c) == "engrave_surface"
    assert layer_operation(Layer(name="Ebene 2", fill_mode="hatch"), [], c) == "engrave_surface"
    slate = next(c for c in material_choices(db) if c.material_id == "slate")
    assert layer_operation(Layer(name="Schneiden"), [], slate) == "engrave_surface"


def test_apply_sets_all_layers_one_undo_step(qapp, db):
    ed = _doc_editor()
    doc = ed.document
    doc.add_layer(Layer(name="Gravieren"))
    c = next(c for c in material_choices(db) if c.key == "birch_plywood|3")
    ops = apply_choice(ed, db, c)
    assert sorted(ops.values()) == ["cut", "engrave_surface"]
    for layer in doc.layers:
        assert layer.material == "Birken-Sperrholz" and layer.thickness_mm == 3.0
        assert layer.material_ref.startswith(f"lib:birch_plywood/{ops[layer.id]}/")
    ed.undo_stack.undo()
    assert all(not layer.material for layer in doc.layers)


def test_apply_uses_pi_entry(qapp, db):
    ed = _doc_editor()
    p = Preset(name="MDF Pi", material_id="mdf", op="cut", laser_id="", thickness_mm=3.0,
               power_pct=77, speed_mm_min=321, passes=2)
    c = next(c for c in material_choices(db, [p]) if c.key == "mdf|3")
    apply_choice(ed, db, c)
    layer = ed.document.active_layer
    assert (layer.power, layer.speed, layer.passes) == (77.0, 321.0, 2)


def test_unknown_material_entry_from_pi(db):
    p = Preset(name="Pi-Spezial", material_id="xyz", op="cut", laser_id="", thickness_mm=2.0,
               power_pct=50, speed_mm_min=500, passes=1)
    c = next(c for c in material_choices(db, [p]) if c.key == "xyz|2")
    assert isinstance(c, MaterialChoice) and c.name == "Pi-Spezial" and c.processes == ["Schneiden"]


def test_main_window_single_selector_layer_panel_readonly(qapp, tmp_path, monkeypatch):
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication
    monkeypatch.delenv("LUMACUT_KEY", raising=False)
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(tmp_path))
    QSettings.setDefaultFormat(QSettings.IniFormat)
    main = pytest.importorskip("main")
    win = main.LumaCutStudio()
    try:
        win.resize(1280, 720)
        win.show()
        QApplication.processEvents()
        picker, lp = win.material_picker, win.layers_panel
        assert win.material_tools.quick is None
        assert picker.list.sizeHintForRow(0) >= 48 and picker.search.minimumHeight() >= 44
        # Ebenen-Panel: keine zweite Auswahl, nur Ergebnis
        assert not lp.material.isVisibleTo(win) and lp.material_summary.isVisibleTo(win)
        assert not lp.thickness.isVisibleTo(win)
        assert "Kein Material" in lp.material_summary.text()
        assert "Kein Kontakt zum Pi" in picker.source.text()
        assert picker.select("mdf|3")
        assert "MDF · 3 mm" in lp.material_summary.text() and "mm/min" in lp.material_summary.text()
        assert picker.chosen_label.text() == "Gewählt: MDF · 3 mm"
        assert QSettings().value("material/choice") == "mdf|3"
        win.main_view.set_more(True)
        assert lp.thickness.isVisibleTo(win) and not lp.material.isVisibleTo(win)
    finally:
        win.canvas.undo_stack.setClean()
        win.scan_panel.shutdown()
        win.machine_panel.shutdown()
        win.close()
