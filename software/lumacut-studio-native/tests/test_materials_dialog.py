"""Materialbibliothek-Dialog und Menü (offscreen, ohne Pi)."""

import numpy as np
import pytest

from _pi_guard import pi_check


@pytest.fixture
def editor(qapp):
    from lumacut_canvas.editor import CanvasEditor
    ed = CanvasEditor()
    yield ed
    ed.undo_stack.setClean()


def _dialog(editor, tmp_path):
    from lumacut_materials.dialog import MaterialLibraryDialog
    from lumacut_materials.presets import PresetStore
    return MaterialLibraryDialog(editor, store=PresetStore(tmp_path / "p.json"))


def test_apply_cut_preset_is_one_undo_step(editor, tmp_path):
    dlg = _dialog(editor, tmp_path)
    dlg.select("basswood_plywood", 5, "cut", "lasertree_lt80w")
    p = dlg.preset
    assert p is not None and p.passes >= 2 and p.z_step_mm > 0
    assert "Fokus je Durchgang" in dlg.result.text()
    doc = editor.document
    lid = doc.active_layer_id
    before = doc.layer(lid).to_dict()
    n = editor.undo_stack.count()
    assert dlg.apply() == lid
    layer = doc.layer(lid)
    assert (layer.power, layer.speed, layer.passes) == (round(p.power_pct), round(p.speed_mm_min), p.passes)
    assert layer.z_step == pytest.approx(p.z_step_mm)
    assert editor.undo_stack.count() == n + 1
    editor.undo_stack.undo()
    assert doc.layer(lid).to_dict() == before


def test_operations_follow_material_and_incompatible_blocks(editor, tmp_path):
    dlg = _dialog(editor, tmp_path)
    dlg.select("stainless_steel")
    ops = [dlg.operation.itemData(i) for i in range(dlg.operation.count())]
    assert "cut" not in ops and ops
    dlg.select("pvc_vinyl")
    assert dlg.preset is None and not dlg.apply_btn.isEnabled()
    assert dlg.warnings.text()
    with pytest.raises(ValueError):
        dlg.select("unobtainium")


def test_save_preset_and_reload(editor, tmp_path):
    dlg = _dialog(editor, tmp_path)
    dlg.select("acrylic_black", 3, "cut")
    saved = dlg.save_preset("Acryl schwarz 3")
    assert saved and (tmp_path / "p.json").exists()
    dlg2 = _dialog(editor, tmp_path)
    assert "Acryl schwarz 3" in [dlg2.saved.itemText(i) for i in range(dlg2.saved.count())]


def test_relief_from_image_passes_pi_guard(editor, tmp_path):
    cv2 = pytest.importorskip("cv2")
    yy, xx = np.mgrid[0:60, 0:60]
    img = (255 * (((xx - 30) ** 2 + (yy - 30) ** 2) / 1800.0).clip(0, 1)).astype(np.uint8)
    path = tmp_path / "dome.png"
    cv2.imwrite(str(path), img)
    dlg = _dialog(editor, tmp_path)
    dlg.select("basswood_plywood", None, "relief")
    dlg.relief_depth.setValue(1.0)
    dlg.relief_width.setValue(10)
    code, stats = dlg.relief_gcode(path)
    assert stats.passes >= 2
    pi_check(code)


def test_main_window_has_material_menu(qapp, tmp_path):
    from PySide6.QtCore import QSettings
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(tmp_path))
    QSettings.setDefaultFormat(QSettings.IniFormat)
    main = pytest.importorskip("main")
    win = main.LumaCutStudio()
    titles = [a.text() for a in win.menuBar().actions()]
    assert "&Material" in titles
    dlg = win.material_tools.open()
    qapp.processEvents()
    assert dlg.isVisible() and dlg.editor is win.canvas
    dlg.select("basswood_plywood", 3, "cut")
    dlg.apply()
    assert win.canvas.document.active_layer.passes == dlg.preset.passes
    dlg.close()
    win.canvas.undo_stack.setClean()
    win.close()
