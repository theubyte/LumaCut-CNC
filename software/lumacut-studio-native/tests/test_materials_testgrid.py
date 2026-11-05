"""Materialtest-Raster → eigenes Preset; Menü und Design-Feld im Hauptfenster."""

import pytest

from lumacut_canvas.model import Document, Layer
from lumacut_job.material_test import MaterialTestSpec, add_material_test
from lumacut_materials import load_db
from lumacut_materials.db import MaterialError
from lumacut_materials.testgrid import is_test_cell, preset_from_test_cell, find_test_cells


@pytest.fixture(scope="module")
def db():
    return load_db()


def _grid_doc():
    doc = Document()
    add_material_test(doc, MaterialTestSpec(columns=3, rows=2, line_interval_mm=0))
    return doc


def test_cells_are_recognized():
    doc = _grid_doc()
    cells = find_test_cells(doc)
    assert len(cells) == 6
    assert not any(l.name == "Test Beschriftung" for l in cells)
    assert not is_test_cell(Layer(name="Ebene 1"))


def test_preset_takes_layer_values(db):
    cell = find_test_cells(_grid_doc())[2]
    cell.passes = 3
    p = preset_from_test_cell(db, cell, "basswood_plywood", "cut", 4.0)
    assert (p.power_pct, p.speed_mm_min, p.passes) == (cell.power, cell.speed, 3)
    assert p.source == "test" and "Test P" in p.name and p.thickness_mm == 4.0
    assert p.depth_per_pass_mm * 3 >= 4.0
    assert p.laser_id


def test_preset_rejects_bad_input(db):
    cell = find_test_cells(_grid_doc())[0]
    with pytest.raises(MaterialError):
        preset_from_test_cell(db, Layer(name="Ebene 1"), "mdf", "cut", 3)
    with pytest.raises(MaterialError):
        preset_from_test_cell(db, cell, "pvc_vinyl", "cut", 3)
    with pytest.raises(MaterialError):
        preset_from_test_cell(db, cell, "mdf", "cut", None)
    with pytest.raises(MaterialError):
        preset_from_test_cell(db, cell, "stainless_steel", "cut", 1)


def test_engrave_preset_from_fill_grid(db):
    doc = Document()
    add_material_test(doc, MaterialTestSpec(columns=2, rows=2, line_interval_mm=0.2))
    p = preset_from_test_cell(db, find_test_cells(doc)[0], "slate", "engrave_surface")
    assert p.op == "engrave_surface" and p.line_interval_mm


@pytest.fixture
def editor(qapp):
    from lumacut_canvas.editor import CanvasEditor
    ed = CanvasEditor()
    yield ed
    ed.undo_stack.setClean()


def test_dialog_saves_active_test_cell_and_applies_it(editor, tmp_path, db):
    from lumacut_materials.dialog import MaterialLibraryDialog
    from lumacut_materials.presets import PresetStore
    doc = editor.document
    add_material_test(doc, MaterialTestSpec(columns=2, rows=2, line_interval_mm=0))
    best = find_test_cells(doc)[1]
    doc.set_active_layer(best.id) if hasattr(doc, "set_active_layer") else setattr(doc, "active_layer_id", best.id)
    store = PresetStore(tmp_path / "p.json")
    dlg = MaterialLibraryDialog(editor, store=store, db=db)
    dlg.select("birch_plywood", 3, "cut")
    assert dlg.test_cell_layer() is best
    p = dlg.save_test_cell(name="Birke 3 getestet")
    assert p is not None and p.source == "test"
    assert PresetStore(tmp_path / "p.json").get("Birke 3 getestet").power_pct == best.power
    # Anwenden auf eine andere Ebene: zugewiesen (nicht verknüpft), ein Undo-Schritt
    target = Layer(name="Teile")
    doc.add_layer(target)
    from lumacut_materials.dialog import apply_preset
    n = editor.undo_stack.count()
    apply_preset(editor, p, target.id, db=db)
    t = doc.layer(target.id)
    assert (t.power, t.speed, t.thickness_mm) == (best.power, best.speed, 3.0)
    assert t.material_ref.startswith("lib:birch_plywood/cut/") and not t.material_link
    assert editor.undo_stack.count() == n + 1
    dlg.close()


def test_dialog_without_test_cells_returns_none(editor, tmp_path, db, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    from lumacut_materials.dialog import MaterialLibraryDialog
    from lumacut_materials.presets import PresetStore
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    dlg = MaterialLibraryDialog(editor, store=PresetStore(tmp_path / "p.json"), db=db)
    dlg.select("mdf", 3, "cut")
    assert dlg.save_test_cell(name="x") is None
    dlg.close()


def test_main_window_menu_and_design_material_field(qapp, tmp_path):
    from PySide6.QtCore import QSettings
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(tmp_path))
    QSettings.setDefaultFormat(QSettings.IniFormat)
    main = pytest.importorskip("main")
    win = main.LumaCutStudio()
    tools = win.material_tools
    assert tools.test_action.text().startswith("Testzelle")
    # Die Schnellwahl im Design-Bereich ersetzt die eine Materialwahl der
    # Hauptansicht (lumacut_canvas.material_picker, Anforderungen §9.1).
    assert tools.quick is None
    picker = win.material_picker
    assert picker.list.count() > 10
    assert picker.select("mdf|3")
    lid = win.canvas.document.active_layer_id
    layer = win.canvas.document.layer(lid)
    assert layer.material_link and layer.material_ref.startswith("lib:mdf/cut/")
    win.canvas.undo_stack.undo()
    assert not win.canvas.document.layer(lid).material_ref
    win.canvas.undo_stack.setClean()
    win.close()


# --- Achsen-Parameter (Linienabstand, Durchgänge) ----------------------------------------

def _axis_grid(**kw):
    doc = Document()
    add_material_test(doc, MaterialTestSpec(**kw))
    return find_test_cells(doc)


def test_power_speed_grid_keeps_planned_interval(db):
    cells = _axis_grid(columns=2, rows=2, line_interval_mm=0.2)
    from lumacut_materials.testgrid import tested_axes
    assert tested_axes(cells) == set()
    old = preset_from_test_cell(db, cells[0], "slate", "engrave_surface")
    new = preset_from_test_cell(db, cells[0], "slate", "engrave_surface", cells=cells)
    assert new.to_dict() == old.to_dict()


def test_interval_axis_takes_cell_interval(db):
    cells = _axis_grid(column_param="interval", row_param="power", columns=3, rows=2,
                       line_interval_mm=0.1, interval_max=0.3)
    cell = max(cells, key=lambda c: c.line_interval_mm)
    p = preset_from_test_cell(db, cell, "slate", "engrave_surface", cells=cells)
    assert p.line_interval_mm == pytest.approx(cell.line_interval_mm) == pytest.approx(0.3)
    assert "A0.3mm" in p.name
    # Schneiden kennt keinen Zeilenabstand
    c = preset_from_test_cell(db, cell, "basswood_plywood", "cut", 3.0, cells=cells)
    assert c.line_interval_mm is None


def test_passes_axis_takes_cell_passes(db):
    cells = _axis_grid(column_param="passes", row_param="power", columns=3, rows=2,
                       passes_max=3, line_interval_mm=0)
    cell = [c for c in cells if c.passes == 3][0]
    p = preset_from_test_cell(db, cell, "basswood_plywood", "cut", 3.0, cells=cells)
    assert p.passes == 3 and p.depth_per_pass_mm == pytest.approx(1.0) and "3×" in p.name


def test_tested_values_fit_pi_limits(db):
    from lumacut_materials.remote import preset_to_material
    cells = _axis_grid(column_param="interval", row_param="power", columns=2, rows=1,
                       line_interval_mm=0.1, interval_max=0.2)
    cell = cells[0]
    cell.line_interval_mm, cell.passes = 12.0, 99  # von Hand verstellt
    p = preset_from_test_cell(db, cell, "slate", "engrave_surface", cells=cells)
    assert p.line_interval_mm == 5.0 and p.passes == 30
    m = preset_to_material(p.to_dict())
    assert m["interval_mm"] == 5.0 and m["passes"] == 30
    # ohne Zeilenabstand bleibt das Feld weg (Pi setzt 0,1)
    q = preset_from_test_cell(db, cells[1], "basswood_plywood", "cut", 3.0, cells=cells)
    assert "interval_mm" not in preset_to_material(q.to_dict())


def test_dialog_saves_interval_cell(editor, tmp_path, db):
    from lumacut_materials.dialog import MaterialLibraryDialog
    from lumacut_materials.presets import PresetStore
    doc = editor.document
    add_material_test(doc, MaterialTestSpec(column_param="interval", row_param="passes", columns=2,
                                            rows=2, line_interval_mm=0.1, interval_max=0.2,
                                            passes_max=2))
    best = find_test_cells(doc)[-1]
    dlg = MaterialLibraryDialog(editor, store=PresetStore(tmp_path / "p.json"), db=db)
    dlg.select("slate", None, "engrave_surface")
    p = dlg.save_test_cell(name="Schiefer getestet", layer=best)
    assert p is not None
    assert p.line_interval_mm == pytest.approx(best.line_interval_mm) and p.passes == best.passes
    dlg.close()
