"""Dialog/Aktion „Schnittoptionen“ (Kerf, Haltestege, An-/Abfahrt)."""

import pytest
from _pi_guard import pi_check
from PySide6.QtWidgets import QDialogButtonBox

from lumacut_canvas.commands import AddShapesCommand
from lumacut_canvas.model import CUT_LAYER_DEFAULTS, Geometry, Shape
from lumacut_job.cut_qt import CutOptionsDialog, apply_cut_options, summary
from lumacut_job.planner import optimized_document_gcode


@pytest.fixture
def editor(qapp):
    from lumacut_canvas.editor import CanvasEditor
    ed = CanvasEditor()
    yield ed
    ed.undo_stack.setClean()
    ed.close()
    ed.deleteLater()
    qapp.processEvents()


def test_dialog_roundtrip_and_defaults(editor):
    layer = editor.document.active_layer
    dlg = CutOptionsDialog(layer)
    assert dlg.values() == CUT_LAYER_DEFAULTS
    dlg.kerf.setValue(0.075)
    dlg.tab_count.setValue(4)
    dlg.lead_in.setValue(2.0)
    dlg.lead_arc.setChecked(True)
    v = dlg.values()
    assert v["kerf_mm"] == pytest.approx(0.075) and v["tab_count"] == 4 and v["lead_in_arc"]
    dlg.findChild(QDialogButtonBox).button(QDialogButtonBox.RestoreDefaults).click()
    assert dlg.values() == CUT_LAYER_DEFAULTS
    assert dlg.tab_count.text() == "aus"


def test_apply_is_one_undo_step(editor):
    doc = editor.document
    lid = doc.active_layer.id
    n = editor.undo_stack.count()
    vals = dict(CUT_LAYER_DEFAULTS, kerf_mm=0.1, tab_count=2, lead_out_mm=1.5)
    assert apply_cut_options(editor, lid, vals)
    assert editor.undo_stack.count() == n + 1
    layer = doc.layer(lid)
    assert (layer.kerf_mm, layer.tab_count, layer.lead_out_mm) == (0.1, 2, 1.5)
    assert summary(layer) == "Kerf +0.10 mm, 2 Stege, Abfahrt 1.5 mm"
    assert not apply_cut_options(editor, lid, vals)  # unverändert -> kein Undo-Schritt
    editor.undo_stack.undo()
    assert doc.layer(lid).kerf_mm == 0.0 and summary(doc.layer(lid)) == ""


def test_job_tools_action_changes_gcode(qapp):
    from main import LumaCutStudio
    win = LumaCutStudio()
    try:
        tools = win.job_tools
        assert tools.cut_action.text() == "Schnittoptionen…"
        ed = win.canvas
        doc = ed.document
        lid = doc.active_layer.id
        ed.undo_stack.push(AddShapesCommand(doc, [Shape("rect", Geometry(50, 50, 40, 30), lid)],
                                            "Rechteck"))
        before = optimized_document_gcode(doc)
        assert tools.cut_options(dict(CUT_LAYER_DEFAULTS, tab_count=4, lead_in_mm=2.0))
        after = optimized_document_gcode(doc)
        assert after != before
        assert after.count("M3 I") == 1
        pi_check(after)
        assert "Anfahrt" in win.statusBar().currentMessage() or "Stege" in win.statusBar().currentMessage()
    finally:
        win.canvas.undo_stack.setClean()
        win.close()
        win.deleteLater()
        qapp.processEvents()
