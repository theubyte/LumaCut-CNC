"""Variabler Text (round 44): Weiterschalten nach dem Senden ist kein
Rückgängig-Schritt, und Rückgängig/Wiederholen älterer Schritte zählt den
Zähler / die CSV-Zeile nie zurück (LightBurn: eine gelaserte Seriennummer
kommt nicht wieder). Eine bewusste Änderung im Dialog („Auf Start“) gilt."""

import datetime as dt
import hashlib
import json
from dataclasses import asdict

import pytest

from lumacut_canvas.commands import AddShapesCommand, SetGeometryCommand, SetTextCommand
from lumacut_canvas.model import Document, Geometry, Shape
from lumacut_job import vartext as vt

NOW = dt.datetime(2026, 11, 9, 9, 0, 0)


def _aspect(text, family, bold, italic):
    return 0.5 * max(1, len(text))


class _Editor:
    def __init__(self, doc):
        from PySide6.QtGui import QUndoStack
        self.document = doc
        self.undo_stack = QUndoStack()
        self.selection = []


def _text(text="{n}", x=10.0, y=10.0, **spec):
    s = Shape("text", Geometry(x, y, 2.0 * len(text), 4.0), "L", text=text)
    s.generator = vt.make_meta(vt.VarTextSpec(**spec))
    return s


def _setup(*shapes):
    d = Document()
    for s in shapes:
        s.layer_id = d.active_layer_id
        d.add_shape(s)
    return d, _Editor(d)


def _cur(doc):
    return [vt.spec_of(s).current for s in doc.shapes if vt.is_variable(s)]


def _rows(doc):
    return [vt.spec_of(s).csv_row for s in doc.shapes if vt.is_variable(s)]


def _send(ed):
    """Build the job and advance like a successful upload."""
    from lumacut_job.vartext_qt import advance
    _, usage = vt.evaluate_document(ed.document, _aspect, NOW)
    return advance(ed, usage)


def _move(ed, sid, dx=5.0):
    g = ed.document.shape(sid).geom
    ng = g.copy()
    ng.x += dx
    ed.undo_stack.push(SetGeometryCommand(ed.document, {sid: g.copy()}, {sid: ng}, "Verschieben"))


# --- model ------------------------------------------------------------------------

def test_epoch_field_defaults_and_is_left_out_of_old_metas():
    assert vt.VarTextSpec().epoch == ""
    meta = vt.make_meta(vt.VarTextSpec(series="S", current=7))
    assert "epoch" not in meta["spec"]                     # files of old specs unchanged
    assert meta["spec"] == {k: v for k, v in asdict(vt.VarTextSpec(series="S", current=7)).items()
                            if k != "epoch"}
    s = _text(series="S")
    assert vt.spec_of(s).epoch == ""
    s.generator = vt.make_meta(vt.VarTextSpec(series="S", epoch="e1"))
    assert vt.spec_of(s).epoch == "e1" and s.generator["spec"]["epoch"] == "e1"
    assert vt.new_epoch() != vt.new_epoch() and len(vt.new_epoch()) == 12
    # advanced spec keeps the epoch
    assert vt.advanced_spec(vt.VarTextSpec(epoch="e1"), 2).epoch == "e1"


def test_usage_token_unchanged_for_specs_without_epoch():
    from lumacut_job.vartext_qt import usage_token
    s = _text(series="M")
    doc, _ = _setup(s)
    _, usage = vt.evaluate_document(doc, _aspect, NOW)
    old = [(u.key, {k: v for k, v in asdict(u.spec).items() if k != "epoch"}, u.ids, u.texts)
           for u in usage.series]
    expected = hashlib.sha1(json.dumps(old, sort_keys=True).encode("utf-8")).hexdigest()[:12]
    assert usage_token(usage) == expected
    s.generator = vt.make_meta(vt.VarTextSpec(series="M", epoch="x"))
    _, usage2 = vt.evaluate_document(doc, _aspect, NOW)
    assert usage_token(usage2) != expected


# --- advance --------------------------------------------------------------------------

def test_advance_is_not_an_undo_step_but_marks_the_project_changed(qapp):
    s = _text(series="K", current=1)
    doc, ed = _setup(s)
    ed.undo_stack.setClean()
    specs = _send(ed)
    assert [x.current for x in specs] == [2] and _cur(doc) == [2]
    assert ed.undo_stack.count() == 0 and not ed.undo_stack.canUndo()
    assert not ed.undo_stack.isClean()                     # closing asks to save the counter
    ed.undo_stack.setClean()                               # saved
    assert ed.undo_stack.isClean()


def test_undo_of_an_older_edit_keeps_the_advanced_counter(qapp):
    a = _text(series="K", current=1)
    b = _text(y=30.0, series="K", current=1)
    doc, ed = _setup(a, b)
    _move(ed, a.id)                                        # an edit before the job
    _send(ed)
    assert _cur(doc) == [3, 3]                             # two copies
    ed.undo_stack.undo()                                   # undo the move
    assert doc.shape(a.id).geom.x == pytest.approx(10.0)
    assert _cur(doc) == [3, 3]                             # not rewound
    ed.undo_stack.redo()
    assert doc.shape(a.id).geom.x == pytest.approx(15.0) and _cur(doc) == [3, 3]
    # the next job lasers 3, 4 – no duplicate serial numbers
    out, _ = vt.evaluate_document(doc, _aspect, NOW)
    assert sorted(s.text for s in out.shapes) == ["3", "4"]


def test_text_edit_undo_and_several_jobs(qapp):
    a = _text("Nr {n:3}", series="K", current=5, step=2)
    doc, ed = _setup(a)
    ed.undo_stack.push(SetTextCommand(doc, a.id, "No {n:3}"))
    _send(ed)
    ed.undo_stack.push(SetTextCommand(doc, a.id, "#{n:3}"))
    _send(ed)
    assert _cur(doc) == [9]
    ed.undo_stack.undo()
    ed.undo_stack.undo()
    assert doc.shape(a.id).text == "Nr {n:3}" and _cur(doc) == [9]
    ed.undo_stack.redo()
    ed.undo_stack.redo()
    assert doc.shape(a.id).text == "#{n:3}" and _cur(doc) == [9]


def test_csv_row_is_kept_too(qapp, tmp_path):
    p = tmp_path / "g.csv"
    p.write_text("Name\nAda\nBob\nCem\n", encoding="utf-8")
    a = _text("{Name}", series="C", csv_path=str(p), csv_row=1)
    doc, ed = _setup(a)
    _move(ed, a.id)
    _send(ed)
    assert _rows(doc) == [2]
    ed.undo_stack.undo()
    assert _rows(doc) == [2]
    out, _ = vt.evaluate_document(doc, _aspect, NOW)
    assert [s.text for s in out.shapes] == ["Bob"]


def test_deleted_and_restored_copy_gets_the_advanced_value(qapp):
    from lumacut_canvas.commands import DeleteShapesCommand
    a = _text(series="K", current=1)
    b = _text(y=30.0, series="K", current=1)
    doc, ed = _setup(a, b)
    ed.undo_stack.push(DeleteShapesCommand(doc, [b.id]))
    _send(ed)                                              # one copy lasered: 1
    assert _cur(doc) == [2]
    ed.undo_stack.undo()                                   # b comes back with its old copy
    assert _cur(doc) == [2, 2]


def test_pasted_copy_of_an_old_state_is_synced(qapp):
    a = _text(series="K", current=1)
    doc, ed = _setup(a)
    old_copy = doc.shape(a.id).copy()                      # clipboard before the job
    _move(ed, a.id)
    _send(ed)
    old_copy.id = "pasted"
    old_copy.geom.y = 40.0
    ed.undo_stack.push(AddShapesCommand(doc, [old_copy]))
    assert _cur(doc) == [2, 2]


def test_other_series_and_plain_texts_untouched(qapp):
    a = _text(series="K", current=1)
    b = _text(y=30.0, series="Z", current=50)
    c = Shape("text", Geometry(0, 60, 10, 4), "L", text="fest")
    doc, ed = _setup(a, b, c)
    doc.shape(b.id).layer_id = doc.active_layer_id
    _move(ed, a.id)
    from lumacut_job.vartext_qt import advance
    _, usage = vt.evaluate_document(doc, _aspect, NOW)
    usage.series = [u for u in usage.series if u.key == "K"]   # only K in the job
    advance(ed, usage)
    ed.undo_stack.undo()
    assert vt.spec_of(doc.shape(a.id)).current == 2
    assert vt.spec_of(doc.shape(b.id)).current == 50
    assert doc.shape(c.id).generator is None and doc.shape(c.id).text == "fest"


# --- dialog changes (new epoch) -------------------------------------------------------

def test_dialog_reset_wins_and_undoing_it_restores_the_advanced_value(qapp):
    from lumacut_job.vartext_qt import apply_vartext
    a = _text("Nr {n}", series="K", current=1)
    doc, ed = _setup(a)
    _move(ed, a.id)
    _send(ed)
    _send(ed)
    assert _cur(doc) == [3]
    old_epoch = vt.spec_of(doc.shape(a.id)).epoch
    apply_vartext(ed, [a.id], vt.VarTextSpec(series="K", current=1))      # „Auf Start“
    assert _cur(doc) == [1] and vt.spec_of(doc.shape(a.id)).epoch != old_epoch
    ed.undo_stack.undo()                                   # undo the reset
    assert _cur(doc) == [3]
    ed.undo_stack.redo()
    assert _cur(doc) == [1]
    _send(ed)                                              # lasered 1 after the reset
    assert _cur(doc) == [2]
    ed.undo_stack.undo()                                   # undo the reset again
    assert _cur(doc) == [3]                                # values of the old epoch
    ed.undo_stack.redo()
    assert _cur(doc) == [2]                                # and of the new one
    ed.undo_stack.undo()
    ed.undo_stack.undo()                                   # also undo the move
    assert _cur(doc) == [3]


def test_apply_always_sets_a_new_epoch(qapp):
    from lumacut_job.vartext_qt import apply_vartext
    a = _text(series="K", current=4)
    doc, ed = _setup(a)
    apply_vartext(ed, [a.id], vt.VarTextSpec(series="K", current=4))
    e1 = vt.spec_of(doc.shape(a.id)).epoch
    apply_vartext(ed, [a.id], vt.VarTextSpec(series="K", current=4))
    e2 = vt.spec_of(doc.shape(a.id)).epoch
    assert e1 and e2 and e1 != e2


# --- ledger lifetime ---------------------------------------------------------------------

def test_ledger_not_recorded_without_history_and_cleared_with_it(qapp):
    from lumacut_job.vartext_qt import ledger_of
    a = _text(series="K", current=1)
    doc, ed = _setup(a)
    _send(ed)                                              # empty history: nothing to protect
    assert ledger_of(ed).values == {} and _cur(doc) == [2]
    _move(ed, a.id)
    _send(ed)
    assert ledger_of(ed).values == {("K", ""): (3, 1)}
    ed.undo_stack.clear()                                  # new / opened project
    assert ledger_of(ed).values == {}


def test_ledger_skips_texts_from_a_newer_version(qapp):
    from lumacut_job.vartext_qt import ledger_of
    a = _text(series="K", current=1)
    doc, ed = _setup(a)
    _move(ed, a.id)
    _send(ed)
    doc.shape(a.id).generator = {"kind": "vartext", "version": 99, "spec": {"series": "K"}}
    assert ledger_of(ed).sync() == []


# --- window --------------------------------------------------------------------------------

@pytest.fixture
def win(qapp, monkeypatch, tmp_path):
    from PySide6.QtCore import QSettings
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(tmp_path))
    QSettings.setDefaultFormat(QSettings.IniFormat)
    main = pytest.importorskip("main")
    w = main.LumaCutStudio()
    yield w
    w.canvas.undo_stack.setClean()
    w.close()
    w.deleteLater()
    qapp.processEvents()


def test_window_send_then_ctrl_z_keeps_the_counter(win):
    from lumacut_job.vartext_qt import gcode_token
    tools = win.job_tools
    ed = win.canvas
    doc = ed.document
    lid = doc.active_layer_id
    t = doc.add_shape(Shape("text", Geometry(40, 40, 20, 8), lid, text="Nr. {n:3}"))
    ed.set_selection([t.id])
    assert tools.variable_text(vt.VarTextSpec(current=41)) == [t.id]
    ed.undo_stack.setClean()                               # saved project
    g, _ = tools.job_gcode()
    tr = tools.vartext_tracker
    tr._awaiting = ("job.gcode", gcode_token(g), tr._pending[gcode_token(g)])
    tr.panel._uploaded = "job.gcode"
    tr._finished("Senden", True)
    assert vt.spec_of(doc.shape(t.id)).current == 42
    msg = win.statusBar().currentMessage()
    assert "weitergeschaltet" in msg and "kein Rückgängig-Schritt" in msg
    assert not ed.undo_stack.isClean() and "•" in ed.title()
    ed.undo_stack.undo()                                   # undoes the dialog step, not the job
    assert not vt.is_variable(doc.shape(t.id))
    ed.undo_stack.redo()
    assert vt.spec_of(doc.shape(t.id)).current == 42       # the redo copy had 41
    g2, note = tools.job_gcode()
    assert "Nr. 042" in note
