"""Variabler Text (LightBurn „Variable Text“): Zähler, Datum/Uhrzeit und
CSV-Serienbrief werden beim Senden ausgewertet; das Projekt behält die Vorlage."""

import datetime as dt
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _pi_guard import pi_check  # noqa: E402

from lumacut_canvas.model import Document, Geometry, Shape  # noqa: E402
from lumacut_job import vartext as vt  # noqa: E402

NOW = dt.datetime(2026, 11, 3, 9, 5, 7)


def _aspect(text, family, bold, italic):  # 0.5 mm Breite je Zeichen bei 1 mm Höhe
    return 0.5 * max(1, len(text))


def _vt_shape(text, x=10.0, y=10.0, w=None, h=4.0, layer="L", **spec):
    w = h * _aspect(text, "", False, False) if w is None else w
    s = Shape("text", Geometry(x, y, w, h), layer, text=text)
    s.generator = vt.make_meta(vt.VarTextSpec(**spec))
    return s


def _doc(*shapes):
    d = Document()
    lid = d.active_layer_id
    for s in shapes:
        s.layer_id = lid
        d.add_shape(s)
    return d


# --- placeholders ----------------------------------------------------------------

def test_counter_date_time_and_braces():
    ev = lambda t, **k: vt.evaluate(t, now=NOW, **k)  # noqa: E731
    assert ev("Nr. {n}", value=7) == "Nr. 7"
    assert ev("{n:3}|{n}", value=7, pad=2) == "007|07"
    assert ev("{n:4}", value=-12) == "-0012"
    assert ev("{date}") == "03.11.2026"
    assert ev("{date:%Y-%m-%d} {time}") == "2026-11-03 09:05"
    assert ev("{time:%H:%M:%S} KW{date:%V} T{date:%j} {date:%y}") == "09:05:07 KW45 T307 26"
    assert ev("{{n}} 100%") == "{n} 100%"
    assert ev("{date:%d%%}") == "03%"
    assert ev("ohne") == "ohne" and not vt.has_placeholders("a {{b}}")
    assert vt.uses_counter("x{n:2}") and not vt.uses_counter("{date}")
    assert vt.uses_csv("{Name}") and vt.uses_csv("{csv:2}") and not vt.uses_csv("{n} {row}")


@pytest.mark.parametrize("tmpl, match", [
    ("{n:x}", "Stellenzahl"), ("{n:99}", "Stellenzahl"), ("{date:%A}", "%"),
    ("{}", "Leerer Platzhalter"), ("{Name}", "CSV"), ("{csv:}", "Spalte"),
])
def test_placeholder_errors(tmpl, match):
    with pytest.raises(vt.VarTextError, match=match):
        vt.evaluate(tmpl, now=NOW)
    assert issubclass(vt.VarTextError, ValueError)


def test_csv_columns_rows_and_errors():
    t = vt.parse_csv("Name;Ort;Nr\nAnna; Köln ;1\n\nBernd;Bonn\n")
    assert t.delimiter == ";" and t.header == ["Name", "Ort", "Nr"]
    assert t.rows == [["Anna", "Köln", "1"], ["Bernd", "Bonn"]]
    assert vt.evaluate("{Name} aus {ort}", table=t, row=1) == "Anna aus Köln"
    assert vt.evaluate("{csv:Name}/{csv:2}/{Nr}/{row}", table=t, row=2) == "Bernd/Bonn//2"
    assert t.row_dict(1) == {"Name": "Anna", "Ort": "Köln", "Nr": "1"} and t.row_dict(9) == {}
    with pytest.raises(vt.VarTextError, match="Spalte"):
        vt.evaluate("{Telefon}", table=t, row=1)
    with pytest.raises(vt.VarTextError, match="CSV-Zeile 3"):
        vt.evaluate("{Name}", table=t, row=3)
    assert vt.parse_csv("a,b\n1,2\n").delimiter == ","
    assert vt.parse_csv("a\tb\n1\t2\n").rows == [["1", "2"]]
    assert vt.parse_csv('a,b\n"x, y",2\n').rows == [["x, y", "2"]]
    with pytest.raises(vt.VarTextError, match="leer"):
        vt.parse_csv("\n \n")


def test_load_csv_encodings_cache_and_missing(tmp_path):
    p = tmp_path / "liste.csv"
    p.write_bytes("\ufeffName;Größe\nJürgen;L\n".encode("utf-8"))
    t = vt.load_csv(str(p))
    assert t.header == ["Name", "Größe"] and t.rows == [["Jürgen", "L"]]
    assert vt.load_csv(str(p)) is t                          # cached
    p.write_bytes("Name;Größe\nMüller;XL\nZweite;S\n".encode("cp1252"))
    t2 = vt.load_csv(str(p))
    assert t2.rows[0] == ["Müller", "XL"] and len(t2.rows) == 2
    with pytest.raises(vt.VarTextError, match="nicht gefunden"):
        vt.load_csv(str(tmp_path / "fehlt.csv"))
    with pytest.raises(vt.VarTextError, match="Keine"):
        vt.load_csv("")


def test_spec_meta_and_advance():
    s = vt.VarTextSpec(series="S", start=5, step=2, current=9, csv_path="x.csv", csv_row=3)
    sh = Shape("text", Geometry(0, 0, 10, 5), "L", text="{n}")
    assert not vt.is_variable(sh) and vt.series_key(sh) == f"#{sh.id}"
    sh.generator = vt.make_meta(s)
    assert vt.is_variable(sh) and vt.spec_of(sh) == s and vt.series_key(sh) == "S"
    assert vt.advanced_spec(s, 3) == vt.VarTextSpec("S", 5, 2, 0, 15, True, "x.csv", 6, True)
    one = vt.advanced_spec(vt.VarTextSpec(per_copy=False, current=1), 5)
    assert one.current == 2 and one.csv_row == 1            # no CSV: row stays
    keep = vt.advanced_spec(vt.VarTextSpec(csv_path="a.csv", advance_row=False), 2)
    assert keep.csv_row == 1 and keep.current == 3
    sh.generator = {"kind": "vartext", "version": 1, "spec": {"current": "7", "zukunft": 1}}
    assert vt.spec_of(sh).current == 7
    sh.generator = {"kind": "vartext", "version": 99, "spec": {}}
    with pytest.raises(vt.VarTextError, match="neueren"):
        vt.spec_of(sh)
    big = vt.VarTextSpec(pad=50, csv_row=0, step=10**9).normalized()
    assert big.pad == 12 and big.csv_row == 1 and big.step == vt.STEP_RANGE[1]


# --- job document ----------------------------------------------------------------

def test_evaluate_document_texts_widths_and_original_untouched():
    a = _vt_shape("Nr. {n:3}", x=10, y=10, series="A", current=7)
    plain = Shape("rect", Geometry(50, 50, 5, 5), "L")
    doc = _doc(a, plain)
    out, usage = vt.evaluate_document(doc, _aspect, NOW)
    assert out is not doc and [s.kind for s in out.shapes] == ["text", "rect"]
    t = out.shapes[0]
    assert t.text == "Nr. 007" and t.id == a.id and out.shapes[1] is plain
    assert t.geom.h == 4 and t.geom.w == pytest.approx(4 * 0.5 * 7)
    assert t.geom.x == pytest.approx(10)                         # left edge stays
    assert a.text == "Nr. {n:3}" and a.geom.w == pytest.approx(4 * 0.5 * 9)  # original
    assert out.layers == doc.layers and out.active_layer_id == doc.active_layer_id
    assert usage and usage.series[0].texts == ["Nr. 007"] and usage.series[0].copies == 1
    assert usage.summary() == "Variabler Text: Nr. 007"
    plain_doc = _doc(Shape("text", Geometry(0, 0, 5, 2), "L", text="{n}"))
    same, none = vt.evaluate_document(plain_doc, _aspect)
    assert same is plain_doc and not none and none.summary() == ""


def test_rotated_text_keeps_left_anchor_and_stretch():
    import math
    s = _vt_shape("{n}", x=20, y=20, w=8, h=4, current=1234)  # stretch 8 / (4 * 1.5)
    s.geom.rot = 90
    out, _ = vt.evaluate_document(_doc(s), _aspect, NOW)
    g = out.shapes[0].geom
    assert g.w == pytest.approx(4 * 2.0 * 8 / 6) and g.h == 4 and g.rot == 90

    def left_mid(geom):
        cx, cy = geom.x + geom.w / 2, geom.y + geom.h / 2
        a = math.radians(geom.rot)
        return cx - math.cos(a) * geom.w / 2, cy - math.sin(a) * geom.w / 2

    old, new = left_mid(s.geom), left_mid(g)
    assert new[0] == pytest.approx(old[0]) and new[1] == pytest.approx(old[1])
    assert (g.x, g.y) != (s.geom.x, s.geom.y)


def test_copies_reading_order_csv_rows_and_blank_rows(tmp_path):
    csv = tmp_path / "namen.csv"
    csv.write_text("Name;Ort\nAnna;A\n;B\n\nBen;C\nCleo;D\n", encoding="utf-8")
    common = dict(series="S", current=10, step=5, csv_path=str(csv), csv_row=1)
    b = _vt_shape("{Name} {n}", x=40, y=10.5, **common)        # same row as a (right)
    a = _vt_shape("{Name} {n}", x=5, y=10, **common)
    c = _vt_shape("{Name} {n}", x=5, y=30, **common)
    doc = _doc(b, a, c)
    out, usage = vt.evaluate_document(doc, _aspect, NOW)
    u = usage.series[0]
    assert u.ids == [a.id, b.id, c.id]                         # reading order
    assert u.texts == ["Anna 10", " 15", "Ben 20"]             # empty line skipped
    assert {s.id: s.text for s in out.shapes} == {a.id: "Anna 10", b.id: " 15", c.id: "Ben 20"}
    assert u.next_spec().current == 25 and u.next_spec().csv_row == 4
    # a copy that evaluates to blanks is left out of the job
    rect = Shape("rect", Geometry(0, 0, 2, 2), "L")
    blank = _vt_shape("{Name}", x=5, y=60, series="T", csv_path=str(csv), csv_row=2)
    out3, u3 = vt.evaluate_document(_doc(blank, rect), _aspect)
    assert [s.kind for s in out3.shapes] == ["rect"] and u3.series[0].copies == 1
    # row past the end → error, never a job with a wrong text
    end = _vt_shape("{Name}", series="E", csv_path=str(csv), csv_row=5)
    with pytest.raises(ValueError, match="CSV-Zeile 5"):
        vt.evaluate_document(_doc(end), _aspect)
    with pytest.raises(ValueError, match="keine CSV-Datei"):
        vt.evaluate_document(_doc(_vt_shape("{Name}")), _aspect)


def test_per_copy_off_independent_series_and_hidden_layer():
    from lumacut_canvas.model import Layer
    a1 = _vt_shape("{n}", x=0, y=0, series="A", current=3, per_copy=False)
    a2 = _vt_shape("{n}", x=0, y=20, series="A", current=3, per_copy=False)
    solo = _vt_shape("S{n}", x=50, y=0, current=100)           # no series id: own series
    doc = _doc(a1, a2, solo)
    hidden = doc.add_layer(Layer(name="Versteckt", visible=False))
    h = _vt_shape("{n}", x=80, y=80, layer=hidden.id, series="A", current=3, per_copy=False)
    doc.add_shape(h)
    out, usage = vt.evaluate_document(doc, _aspect, NOW)
    by_key = {u.key: u for u in usage.series}
    assert by_key["A"].texts == ["3", "3"] and by_key["A"].copies == 2
    assert by_key["A"].next_spec().current == 4
    assert by_key[f"#{solo.id}"].texts == ["S100"]
    assert next(s for s in out.shapes if s.id == h.id).text == "{n}"   # hidden: not evaluated


def test_roundtrip_keeps_template_and_settings():
    s = _vt_shape("Los {n:4} {date}", series="R", current=42, csv_row=3)
    doc = _doc(s)
    data = doc.to_dict()
    d2 = Document()
    d2.load_dict(data)
    s2 = d2.shapes[0]
    assert s2.text == "Los {n:4} {date}" and vt.is_variable(s2)
    assert vt.spec_of(s2) == vt.spec_of(s) and vt.spec_of(s2).current == 42


def test_gcode_contains_evaluated_text(qapp):
    from lumacut_job.planner import optimized_document_gcode
    s = _vt_shape("A{n:2}", x=20, y=20, h=8, current=7)
    doc = _doc(s)
    out, _ = vt.evaluate_document(doc, now=NOW)
    lit = _doc(Shape("text", Geometry(20, 20, s.geom.w, 8), "L", text="A07"))
    from lumacut_canvas.shape_paths import text_aspect
    lit.shapes[0].geom = out.shapes[0].geom.copy()
    g_eval = optimized_document_gcode(out)
    assert g_eval == optimized_document_gcode(lit)
    assert g_eval != optimized_document_gcode(doc)              # template not lasered
    assert text_aspect("A07", s.font_family, s.font_bold, s.font_italic) > 0
    pi_check(g_eval)


# --- marker / tracker ------------------------------------------------------------

def test_marker_roundtrip():
    from lumacut_job.vartext_qt import gcode_token, mark_gcode, usage_token
    s = _vt_shape("{n}", series="M")
    _, usage = vt.evaluate_document(_doc(s), _aspect, NOW)
    tok = usage_token(usage)
    assert len(tok) == 12 and tok == usage_token(vt.evaluate_document(_doc(s), _aspect, NOW)[1])
    g = mark_gcode("; HEADER\nG0 X1\n", tok)
    assert g.splitlines() == ["; HEADER", f"; VARIABLE TEXT {tok}", "G0 X1"]
    assert gcode_token(g) == tok and gcode_token("G0 X1\n") == "" and gcode_token("") == ""
    pi_check(mark_gcode("; LUMACUT\nM3 I\nG1 X2 Y2 F600 S10\nM5\n", tok))


class _Editor:
    def __init__(self, doc):
        from PySide6.QtGui import QUndoStack
        self.document = doc
        self.undo_stack = QUndoStack()
        self.selection = []


def _make_panel(signal=True):
    from PySide6.QtCore import QObject, Signal

    class Panel(QObject):
        command_finished = Signal(str, bool)

        def __init__(self):
            super().__init__()
            self.sent = []
            self._upload_gen = 0
            self._uploaded = None
            self.refuse = False
            self.dispatch = True

        def send_gcode(self, name, gcode, start=False):
            if self.refuse:
                return False
            self.sent.append((name, gcode, start))
            if self.dispatch:
                self._upload_gen += 1
            return None

    class Plain:
        def __init__(self):
            self.sent = []

        def send_gcode(self, name, gcode, start=False):
            self.sent.append((name, gcode, start))

    return Panel() if signal else Plain()


def _build(tracker, doc):
    from lumacut_job.planner import optimized_document_gcode
    out, usage = vt.evaluate_document(doc, _aspect, NOW)
    return tracker.remember(optimized_document_gcode(out), usage)


def test_tracker_advances_only_after_successful_upload(qapp):
    from lumacut_job.vartext_qt import VarTextTracker
    s = _vt_shape("{n}", series="K", current=1)
    s2 = _vt_shape("{n}", y=30, series="K", current=1)
    doc = _doc(s, s2)
    ed = _Editor(doc)
    panel = _make_panel()
    reports = []
    tr = VarTextTracker(ed, panel, reports.append)
    cur = lambda: [vt.spec_of(x).current for x in doc.shapes]  # noqa: E731
    g = _build(tr, doc)
    # upload failed (another file uploaded / error) → nothing
    panel.send_gcode("a.gcode", g)
    panel._uploaded = None
    panel.command_finished.emit("Senden", False)
    assert cur() == [1, 1]
    # refused by the park wrapper → nothing, and a late signal is ignored
    panel.refuse = True
    assert panel.send_gcode("a.gcode", g) is False
    panel.command_finished.emit("Senden", True)
    assert cur() == [1, 1]
    panel.refuse = False
    # not dispatched (e.g. not connected) → nothing
    panel.dispatch = False
    panel.send_gcode("a.gcode", g)
    panel._uploaded = "a.gcode"
    panel.command_finished.emit("Senden", True)
    assert cur() == [1, 1]
    panel.dispatch = True
    # uploaded but the start failed → not lasered, keep the values
    panel.send_gcode("a.gcode", g, start=True)
    panel._uploaded = "a.gcode"
    panel.command_finished.emit("Senden & Starten", False)
    assert cur() == [1, 1]
    # other command labels are ignored
    panel.send_gcode("a.gcode", g)
    panel.command_finished.emit("Rahmen", True)
    assert cur() == [1, 1]
    panel.command_finished.emit("Senden & Starten", True)
    assert cur() == [3, 3]                                   # two copies, step 1
    assert reports and "weitergeschaltet" in reports[-1]
    assert [x.text for x in doc.shapes] == ["{n}", "{n}"]    # templates stay
    # re-sending the old job (history) does not advance again
    panel.send_gcode("a.gcode", g)
    panel.command_finished.emit("Senden", True)
    assert cur() == [3, 3]
    # undo rewinds the counter (one step)
    ed.undo_stack.undo()
    assert cur() == [1, 1]
    ed.undo_stack.redo()
    # plain G-code without marker never advances
    panel.send_gcode("b.gcode", "G0 X1\n")
    panel._uploaded = "b.gcode"
    panel.command_finished.emit("Senden", True)
    assert cur() == [3, 3]
    # a newly built job works again
    g2 = _build(tr, doc)
    assert g2 != g
    panel.send_gcode("c.gcode", g2, start=True)
    panel._uploaded = "c.gcode"
    panel.command_finished.emit("Auftrag starten", True)
    assert cur() == [5, 5]


def test_tracker_without_signal_advances_on_dispatch(qapp):
    from lumacut_job.vartext_qt import VarTextTracker
    s = _vt_shape("{n}", current=4, step=3)
    doc = _doc(s)
    ed = _Editor(doc)
    panel = _make_panel(signal=False)
    tr = VarTextTracker(ed, panel)
    panel.send_gcode("x.gcode", _build(tr, doc))
    assert vt.spec_of(doc.shapes[0]).current == 7 and len(panel.sent) == 1


def test_apply_vartext_undo_and_locked_layer(qapp):
    from lumacut_job.vartext_qt import apply_vartext, describe
    a = Shape("text", Geometry(0, 0, 10, 4), "L", text="Alt")
    r = Shape("rect", Geometry(0, 0, 2, 2), "L")
    doc = _doc(a, r)
    ed = _Editor(doc)
    with pytest.raises(ValueError, match="Textobjekt"):
        apply_vartext(ed, [r.id], vt.VarTextSpec())
    ids = apply_vartext(ed, [a.id, r.id], vt.VarTextSpec(current=5), "Nr {n}")
    s = doc.shape(a.id)
    assert ids == [a.id] and s.text == "Nr {n}" and vt.is_variable(s) and vt.spec_of(s).series
    assert "5" in describe(vt.spec_of(s), s.text)
    assert ed.undo_stack.count() == 1
    apply_vartext(ed, [a.id], None)
    assert not vt.is_variable(doc.shape(a.id)) and doc.shape(a.id).text == "Nr {n}"
    ed.undo_stack.undo()
    ed.undo_stack.undo()
    assert doc.shape(a.id).text == "Alt" and doc.shape(a.id).generator is None
    doc.layer(doc.shape(a.id).layer_id).locked = True
    with pytest.raises(ValueError, match="gesperrt"):
        apply_vartext(ed, [a.id], vt.VarTextSpec())


def test_dialog_preview_csv_table_and_reset(qapp, tmp_path):
    from lumacut_job.vartext_qt import VarTextDialog
    p = tmp_path / "gaeste.csv"
    p.write_text("Vorname,Tisch\nAda,1\nBob,2\nCem,3\n", encoding="utf-8")
    dlg = VarTextDialog("{Vorname} T{Tisch} #{n:2}", vt.VarTextSpec(series="Q", current=4),
                        copies=2)
    assert "CSV" in dlg.preview.text() and "⚠" in dlg.preview.text()
    dlg.csv_path.setText(str(p))
    assert dlg.table.rowCount() == 3 and dlg.table.columnCount() == 2
    assert "3 Datenzeilen" in dlg.csv_info.text() and "{Vorname}" in dlg.csv_info.text()
    assert dlg.preview_texts() == ["Ada T1 #04", "Bob T2 #05"]
    assert dlg.preview.text().startswith("Nächster Auftrag (2 Kopien): Ada T1 #04 | Bob T2 #05")
    dlg.table.cellClicked.emit(2, 0)                         # row 3 + 1 copy: past the end
    assert dlg.csv_row.value() == 3 and "CSV-Zeile 4" in dlg.preview.text()
    assert dlg.table.selectionModel().selectedRows()[0].row() == 2
    dlg.per_copy.setChecked(False)
    assert dlg.preview_texts() == ["Cem T3 #04"] and "Cem" in dlg.preview.text()
    dlg.current.setValue(99)
    dlg.reset_button.click()
    assert dlg.current.value() == 1
    spec = dlg.spec()
    assert (spec.series, spec.csv_path, spec.csv_row, spec.per_copy) == ("Q", str(p), 3, False)
    assert dlg.template_text() is None
    dlg.template.setText("{n}")
    assert dlg.template_text() == "{n}"
    dlg.enabled.setChecked(False)
    assert not dlg.is_enabled() and "wörtlich" in dlg.preview.text()
    assert not dlg.template.isEnabled()
    dlg.deleteLater()


def test_generated_unit_ignores_variable_text():
    from lumacut_job.generated import find_unit
    s = _vt_shape("{n}")
    s.groups = ("g1",)
    doc = _doc(s, )
    assert find_unit(doc, s.id) is None


# --- serial numbers integration ----------------------------------------------------

def test_serial_variable_mode_keeps_template_and_series():
    from lumacut_job.serial import SerialSpec, serial_shapes
    src = Shape("text", Geometry(10, 20, 6, 4), "L1", text="T{n}")
    shapes = serial_shapes(src, SerialSpec("T{n:2}", start=8, step=2, count=4, columns=2,
                                           variable=True), _aspect)
    assert [s.text for s in shapes] == ["T{n:2}"] * 4
    specs = {vt.spec_of(s) for s in shapes}
    assert len(specs) == 1
    spec = specs.pop()
    assert (spec.current, spec.start, spec.step, spec.per_copy) == (8, 8, 2, True) and spec.series
    doc = _doc(*shapes)
    _, usage = vt.evaluate_document(doc, _aspect, NOW)
    assert usage.series[0].texts == ["T08", "T10", "T12", "T14"]
    assert usage.series[0].next_spec().current == 16
    # literal batch from a variable source drops the variable-text marker
    vsrc = _vt_shape("{n}", series="X")
    lit = serial_shapes(vsrc, SerialSpec("{n}", count=2), _aspect)
    assert [s.text for s in lit] == ["1", "2"] and not any(vt.is_variable(s) for s in lit)


# --- window ------------------------------------------------------------------------

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


def test_window_action_job_gcode_send_and_advance(win, tmp_path):
    from PySide6.QtGui import QAction, QKeySequence

    from lumacut_job.vartext_qt import gcode_token
    tools = win.job_tools
    a = tools.vartext_action
    assert a.objectName() == "variable_text_action" and a.text() == "Variabler Text…"
    assert a.shortcut() == QKeySequence("Alt+V")
    clash = [b.text() for b in win.findChildren(QAction)
             if b is not a and b.shortcut() == a.shortcut()]
    assert clash == []
    assert a in win.main_view.design_menu.actions() and a in win.main_view.job_menu.actions()
    doc = win.canvas.document
    lid = doc.active_layer_id
    r = doc.add_shape(Shape("rect", Geometry(5, 5, 10, 10), lid))
    t = doc.add_shape(Shape("text", Geometry(40, 40, 20, 8), lid, text="Nr. {n:3}"))
    win.canvas.set_selection([r.id])
    assert tools.variable_text(vt.VarTextSpec()) == []
    assert "Textobjekt" in win.statusBar().currentMessage()
    win.canvas.set_selection([t.id])
    assert tools.variable_text(vt.VarTextSpec(current=41)) == [t.id]
    assert "wird beim Senden" in win.statusBar().currentMessage()
    g, note = tools.job_gcode()
    assert gcode_token(g) and "Variabler Text: Nr. 041" in note
    pi_check(g)
    jd = tools.job_document()
    assert next(s for s in jd.shapes if s.id == t.id).text == "Nr. 041"
    assert doc.shape(t.id).text == "Nr. {n:3}"
    # simulate the panel: successful upload of exactly this job
    panel = win.machine_panel if hasattr(win, "machine_panel") else tools.machine
    tr = tools.vartext_tracker
    assert tr is not None and tr.panel is panel
    tr._awaiting = ("job.gcode", gcode_token(g), tr._pending[gcode_token(g)])
    panel._uploaded = "job.gcode"
    tr._finished("Senden", True)
    assert vt.spec_of(doc.shape(t.id)).current == 42
    assert "weitergeschaltet" in win.statusBar().currentMessage()
    # save / load keeps the template and the advanced counter
    data = doc.to_dict()
    assert any(s.get("text") == "Nr. {n:3}" and (s.get("generator") or {}).get("kind") == "vartext"
               and s["generator"]["spec"]["current"] == 42 for s in data["objects"])
    # switching off: literal text again
    win.canvas.set_selection([t.id])
    tools.variable_text(vt.VarTextSpec(), enabled=False)
    assert not vt.is_variable(doc.shape(t.id))
    g3, note3 = tools.job_gcode()
    assert not gcode_token(g3) and "Variabler Text" not in note3


def test_window_errors_block_job_and_double_click_edits_template(win):
    doc = win.canvas.document
    lid = doc.active_layer_id
    t = doc.add_shape(Shape("text", Geometry(40, 40, 20, 8), lid, text="{Name}"))
    win.canvas.set_selection([t.id])
    win.job_tools.variable_text(vt.VarTextSpec())
    with pytest.raises(ValueError, match="CSV"):
        win.job_tools.job_gcode()
    assert win.job_tools.edit_generated_at(t.id) is False
    assert win._build_canvas_job() is None
    assert "Senden nicht möglich" in win.statusBar().currentMessage()


def test_window_serial_variable_mode(win):
    from lumacut_job.serial import SerialSpec
    doc = win.canvas.document
    lid = doc.active_layer_id
    t = doc.add_shape(Shape("text", Geometry(40, 40, 20, 8), lid, text="S{n}"))
    win.canvas.set_selection([t.id])
    ids = win.job_tools.serial_numbers(SerialSpec("S{n:2}", start=1, count=3, columns=3,
                                                  variable=True))
    assert len(ids) == 3 and all(doc.shape(i).text == "S{n:2}" for i in ids)
    win.canvas.set_selection(ids[:1])
    tools = win.job_tools
    g, note = tools.job_gcode()
    assert "S01 … S03" in note
    pi_check(g)


def test_serial_dialog_variable_checkbox(qapp):
    from lumacut_job.serial import SerialSpec
    from lumacut_job.serial_qt import SerialDialog
    dlg = SerialDialog("Nr {n}")
    assert not dlg.variable.isChecked() and dlg.spec().variable is False
    dlg.variable.setChecked(True)
    assert dlg.spec().variable is True
    assert SerialSpec(variable=1).normalized().variable is True
    dlg.deleteLater()
