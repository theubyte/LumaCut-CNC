"""Variable text: the canvas shows the value every object gets in the next job."""

import datetime as dt
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lumacut_canvas.model import Geometry, Shape  # noqa: E402
from lumacut_job import vartext as vt  # noqa: E402
from test_variable_text import NOW, _aspect, _doc, _vt_shape  # noqa: E402


# --- pure evaluation ----------------------------------------------------------------------
def test_preview_values_match_the_job_document():
    a = _vt_shape("Nr. {n:3}", x=10, y=10, current=7, series="s", per_copy=True)
    b = _vt_shape("Nr. {n:3}", x=60, y=10, current=7, series="s", per_copy=True)
    c = _vt_shape("Nr. {n:3}", x=10, y=40, current=7, series="s", per_copy=True)
    plain = Shape("text", Geometry(10, 80, 20, 4), "L", text="{n} wörtlich")
    doc = _doc(c, b, a, plain)
    values = vt.preview_values(doc, NOW)
    assert {k: v.text for k, v in values.items()} == {a.id: "Nr. 007", b.id: "Nr. 008",
                                                      c.id: "Nr. 009"}
    assert all(not v.error for v in values.values())
    job, usage = vt.evaluate_document(doc, aspect=_aspect, now=NOW)
    texts = {s.id: s.text for s in job.shapes}
    assert all(texts[k] == v.text for k, v in values.items())
    assert usage.series[0].texts == ["Nr. 007", "Nr. 008", "Nr. 009"]
    assert doc.shape(a.id).text == "Nr. {n:3}"            # never changes the document


def test_preview_values_date_hidden_layer_and_per_series_errors(tmp_path):
    ok = _vt_shape("{date:%Y-%m-%d} #{n}", current=3, series="d")
    bad = _vt_shape("{Name}", y=40, series="csv")           # CSV column without a file
    csv = tmp_path / "n.csv"
    csv.write_text("Name\nAnna\nBert\n", encoding="utf-8")
    merge = _vt_shape("Hallo {Name}", y=70, series="m", csv_path=str(csv), csv_row=2)
    doc = _doc(ok, bad, merge)
    values = vt.preview_values(doc, NOW)
    assert values[ok.id] == vt.PreviewValue("2026-11-03 #3")
    assert values[bad.id].text == "" and "CSV" in values[bad.id].error
    assert values[merge.id].text == "Hallo Bert"
    with pytest.raises(vt.VarTextError):                    # the job itself still refuses
        vt.evaluate_document(doc, aspect=_aspect, now=NOW)
    doc.update_layer(doc.active_layer_id, visible=False)
    assert vt.preview_values(doc, NOW) == {}
    assert vt.uses_clock("{time}") and vt.uses_clock("x {date:%Y}")
    assert not vt.uses_clock("{n} {Name}")


def test_evaluate_document_unchanged_by_refactor():
    a = _vt_shape("A{n}", current=5, step=2, series="x", per_copy=True)
    b = _vt_shape("A{n}", x=50, current=5, step=2, series="x", per_copy=True)
    blank = _vt_shape("{n:0}", y=50, series="y")
    doc = _doc(a, b, blank)
    blank.generator = vt.make_meta(vt.VarTextSpec(series="y"))
    job, usage = vt.evaluate_document(doc, aspect=lambda *a: 0.5 * max(1, len(a[0])), now=NOW)
    assert [u.texts for u in usage.series] == [["A5", "A7"], ["1"]]
    assert [s.text for s in job.shapes] == ["A5", "A7", "1"]


# --- labels -------------------------------------------------------------------------------
def test_label_text():
    from lumacut_job.vartext_preview import MAX_CHARS, label_text
    assert label_text(vt.PreviewValue("Nr. 007")) == "→ Nr. 007"
    assert label_text(vt.PreviewValue("a\nb")) == "→ a ⏎ b"
    assert label_text(vt.PreviewValue("", "keine CSV")) == "⚠ keine CSV"
    assert "nicht gelasert" in label_text(vt.PreviewValue("  "))
    long = label_text(vt.PreviewValue("x" * 200))
    assert len(long) == MAX_CHARS and long.endswith("…")


def _editor(doc):
    from lumacut_canvas.editor import CanvasEditor
    return CanvasEditor(doc)


def test_overlay_labels_under_each_object_and_paint(qapp):
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QImage, QPainter

    from lumacut_job.vartext_preview import (ERROR_COLOR, OK_COLOR, OVERLAY_KEY, VarTextValues)
    a = _vt_shape("Nr. {n:3}", x=20, y=20, h=6, current=41, series="s")
    bad = _vt_shape("{Name}", x=20, y=60, series="b")
    doc = _doc(a, bad)
    ed = _editor(doc)
    ov = VarTextValues(ed)
    assert ed.overlay(OVERLAY_KEY) is ov
    la, lb = ov.label_for(a.id), ov.label_for(bad.id)
    assert la.text == "→ Nr. 041" and la.color == OK_COLOR
    assert lb.text.startswith("⚠") and lb.color == ERROR_COLOR
    b = a.bounds()
    assert la.box.top() > b.y + b.h and la.box.left() == pytest.approx(b.x)
    assert la.path.boundingRect().height() == pytest.approx(max(1.6, min(5.0, 6 * 0.35)), rel=0.05)
    assert la.box.contains(la.path.boundingRect())
    img = QImage(400, 400, QImage.Format_ARGB32)
    img.fill(0)
    p = QPainter(img)
    p.scale(1, 1)
    ov.paint(p, QRectF(0, 0, 360, 340))
    p.end()
    assert img.pixelColor(int(la.box.center().x()), int(la.box.center().y())).alpha() > 0
    ed.grab()


def test_label_moves_above_at_the_bottom_edge(qapp):
    from lumacut_canvas.workarea import WORK_HEIGHT_MM
    from lumacut_job.vartext_preview import VarTextValues
    a = _vt_shape("{n}", x=20, y=WORK_HEIGHT_MM - 5, h=4, series="s")
    ov = VarTextValues(_editor(_doc(a)))
    assert ov.label_for(a.id).box.bottom() < WORK_HEIGHT_MM - 5


def test_overlay_follows_document_changes_and_disable(qapp):
    from PySide6.QtCore import QCoreApplication
    from lumacut_job.vartext_preview import OVERLAY_KEY, VarTextValues
    a = _vt_shape("Nr. {n}", current=1, series="s")
    doc = _doc(a)
    ed = _editor(doc)
    ov = VarTextValues(ed)
    assert ov.label_for(a.id).text == "→ Nr. 1"
    doc.shape(a.id).generator = vt.make_meta(vt.VarTextSpec(series="s", current=5))
    ed.documentChanged.emit()
    assert ov._timer.isActive() and ov.label_for(a.id).text == "→ Nr. 1"   # debounced
    ov._timer.timeout.emit()
    assert ov.label_for(a.id).text == "→ Nr. 5"
    ov.set_enabled(False)
    assert ov.labels == [] and ed.overlay(OVERLAY_KEY) is None
    ov.set_enabled(True)
    assert ed.overlay(OVERLAY_KEY) is ov
    doc.remove_shape(a.id)
    ov.rebuild()
    assert ov.labels == [] and ed.overlay(OVERLAY_KEY) is None
    QCoreApplication.processEvents()


def test_clock_timer_only_with_date_or_time(qapp):
    from lumacut_job.vartext_preview import VarTextValues
    a = _vt_shape("Nr. {n}", series="s")
    doc = _doc(a)
    ov = VarTextValues(_editor(doc))
    assert not ov._clock.isActive()
    t = _vt_shape("{time}", y=50, series="t")
    t.layer_id = doc.active_layer_id
    doc.add_shape(t)
    ov.rebuild()
    assert ov._clock.isActive()
    ov.set_enabled(False)
    assert not ov._clock.isActive()


def test_settings_roundtrip(tmp_path):
    from PySide6.QtCore import QSettings
    from lumacut_job.vartext_preview import load_enabled, save_enabled
    s = QSettings(str(tmp_path / "s.ini"), QSettings.IniFormat)
    assert load_enabled(None) is True and load_enabled(s) is True
    save_enabled(s, False)
    s.sync()
    assert load_enabled(QSettings(str(tmp_path / "s.ini"), QSettings.IniFormat)) is False
    save_enabled(s, True)
    assert load_enabled(s) is True


# --- window ---------------------------------------------------------------------------------
@pytest.fixture
def win(qapp, tmp_path):
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


def test_window_shows_next_values_and_follows_selection_mode(win):
    from lumacut_job.vartext_preview import OVERLAY_KEY
    tools = win.job_tools
    ov = tools.vartext_values
    doc = win.canvas.document
    lid = doc.active_layer_id
    t1 = doc.add_shape(Shape("text", Geometry(40, 40, 20, 8), lid, text="Nr. {n:3}"))
    t2 = doc.add_shape(Shape("text", Geometry(40, 80, 20, 8), lid, text="Nr. {n:3}"))
    win.canvas.set_selection([t1.id, t2.id])
    tools.variable_text(vt.VarTextSpec(current=41, per_copy=True))
    ov.rebuild()
    assert win.canvas.overlay(OVERLAY_KEY) is ov
    assert [ov.label_for(i).text for i in (t1.id, t2.id)] == ["→ Nr. 041", "→ Nr. 042"]
    jd = tools.job_document()
    assert {s.id: s.text for s in jd.shapes if s.kind == "text"} == {t1.id: "Nr. 041",
                                                                       t2.id: "Nr. 042"}
    # „Nur Auswahl“: only the selected copy is in the job – and gets the first value
    win.canvas.set_selection([t2.id])
    tools.set_selection_only(True)
    ov.rebuild()
    assert ov.label_for(t1.id) is None and ov.label_for(t2.id).text == "→ Nr. 041"
    win.canvas.set_selection([])
    ov.rebuild()                                     # no selection: no job, no labels
    assert ov.labels == []
    tools.set_selection_only(False)
    ov.rebuild()
    assert len(ov.labels) == 2
    tools.set_vartext_values_shown(False)
    assert ov.labels == [] and not ov.enabled
    tools.set_vartext_values_shown(True)
    assert len(ov.labels) == 2


def test_dialog_has_show_values_checkbox(qapp):
    from lumacut_job.vartext_qt import VarTextDialog
    d = VarTextDialog("Nr. {n}", vt.VarTextSpec(), show_values=False)
    assert not d.show_values.isChecked()
    assert VarTextDialog("x").show_values.isChecked()
