"""Variable text: keyboard input ``{input:Name}`` typed in at send (EzCad keyboard text,
LightBurn users ask for it): one dialog per send / start / „G-Code speichern“, the last
value is kept for the session and used by the canvas labels, frame and estimate."""

import datetime as dt
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _pi_guard import pi_check  # noqa: E402

from lumacut_canvas.model import Geometry, Shape  # noqa: E402
from lumacut_job import vartext as vt  # noqa: E402
from test_variable_text import NOW, _aspect, _doc, _vt_shape  # noqa: E402


# --- pure evaluation ----------------------------------------------------------------------

def test_input_fields_labels_defaults_and_aliases():
    t = "Für {input:Name} aus {eingabe:Ort=Berlin}, {INPUT:name} #{n}"
    assert vt.input_fields(t) == [vt.InputField("Name", ""), vt.InputField("Ort", "Berlin")]
    assert vt.uses_input(t) and not vt.uses_input("{n} {Name} {csv:input}")
    assert vt.input_fields("{input:A=x=y} {{input:B}}") == [vt.InputField("A", "x=y")]
    assert not vt.uses_csv(t)                        # input is no CSV column
    assert vt.uses_csv("{Input2}") and vt.uses_csv("{csv:input}")


@pytest.mark.parametrize("tmpl, match", [
    ("{input}", "Bezeichnung fehlt"), ("{input:}", "Bezeichnung fehlt"),
    ("{eingabe: =x}", "Bezeichnung fehlt"), ("{input:" + "x" * 41 + "}", "40 Zeichen"),
])
def test_input_placeholder_errors(tmpl, match):
    with pytest.raises(vt.VarTextError, match=match):
        vt.evaluate(tmpl, now=NOW)
    with pytest.raises(vt.VarTextError, match=match):
        vt.input_fields(tmpl)
    assert vt.uses_input(tmpl)


def test_evaluate_with_inputs_store_default_and_stand_in():
    t = "Für {input:Name} aus {eingabe:Ort=Berlin}"
    assert vt.evaluate(t, now=NOW) == "Für ‹Name› aus Berlin"
    assert vt.evaluate(t, now=NOW, inputs={"name": "Anna", "ORT": "Ulm"}) == "Für Anna aus Ulm"
    vt.set_input_values({"Name": "Bert"})
    assert vt.input_values() == {"name": "Bert"}
    assert vt.evaluate(t, now=NOW) == "Für Bert aus Berlin"
    assert vt.evaluate(t, now=NOW, inputs={}) == "Für ‹Name› aus Berlin"   # explicit wins
    vt.set_input_values({"Ort": ""})                  # typed empty stays empty
    assert vt.evaluate(t, now=NOW) == "Für Bert aus "
    vt.clear_input_values()
    assert vt.input_values() == {} and vt.evaluate("{input:Name}") == "‹Name›"


def test_clean_input_one_line_and_length():
    assert vt.clean_input("Anna\r\nMaria\tX\x07") == "Anna Maria X"
    assert len(vt.clean_input("x" * 500)) == vt.MAX_INPUT_CHARS
    vt.set_input_values({"N": "a\nb"})
    assert vt.evaluate("{input:N}") == "a b"
    assert vt.evaluate("{input:N}", inputs={"N": "c\nd"}) == "c d"


def test_document_inputs_reading_order_visible_layers_and_series():
    top = _vt_shape("{input:Name} {n}", y=10, series="a")
    low = _vt_shape("{input:Datum=heute} {input:name=X}", y=50, series="b")
    bad = _vt_shape("{input:}", y=30, series="c")
    plain = Shape("text", Geometry(10, 5, 20, 4), "L", text="{input:Literal}")
    doc = _doc(low, bad, top, plain)
    assert vt.document_inputs(doc) == [vt.InputField("Name", ""), vt.InputField("Datum", "heute")]
    doc.layers[0].visible = False
    assert vt.document_inputs(doc) == []


def test_evaluate_document_and_preview_share_the_typed_value():
    a = _vt_shape("Für {input:Name}", x=10, y=10, series="s")
    b = _vt_shape("Für {input:Name}", x=70, y=10, series="s")
    c = _vt_shape("{input:Name}", y=40, series="t")
    doc = _doc(a, b, c)
    job, usage = vt.evaluate_document(doc, aspect=_aspect, now=NOW, inputs={"Name": "Anna"})
    assert {s.id: s.text for s in job.shapes} == {a.id: "Für Anna", b.id: "Für Anna",
                                                  c.id: "Anna"}
    assert job.shape(a.id).geom.w == pytest.approx(4.0 * 0.5 * len("Für Anna"))
    assert "Für Anna" in usage.summary()
    vt.set_input_values({"name": "Bo"})
    assert {k: v.text for k, v in vt.preview_values(doc, NOW).items()} == {
        a.id: "Für Bo", b.id: "Für Bo", c.id: "Bo"}
    job, _ = vt.evaluate_document(doc, aspect=_aspect, now=NOW, inputs={"Name": " "})
    assert [s.id for s in job.shapes] == [a.id, b.id]        # blank copy left out
    assert doc.shape(a.id).text == "Für {input:Name}"        # template unchanged


def test_input_with_counter_csv_and_date(tmp_path):
    csv = tmp_path / "n.csv"
    csv.write_text("Name;Input\nAnna;1\n", encoding="utf-8")
    s = _vt_shape("{Name}/{csv:Input}/{input:Gast} {n:2} {date}", series="m",
                  csv_path=str(csv), current=3)
    job, usage = vt.evaluate_document(_doc(s), aspect=_aspect, now=NOW, inputs={"gast": "Cem"})
    assert job.shapes[0].text == "Anna/1/Cem 03 03.11.2026"
    assert usage.series[0].next_spec().current == 4


def test_old_templates_unchanged():
    assert vt.evaluate("Nr. {n:3} {date} {{input:x}}", value=7, now=NOW) == "Nr. 007 03.11.2026 {input:x}"
    assert vt.input_fields("Nr. {n}") == [] and vt.document_inputs(_doc(_vt_shape("{n}"))) == []


# --- dialog -------------------------------------------------------------------------------

def test_input_dialog_prefills_last_value_then_default(qapp):
    from lumacut_job.vartext_qt import HELP, VarTextInputDialog
    assert "{input:Name}" in HELP
    vt.set_input_values({"Name": "Anna"})
    dlg = VarTextInputDialog([vt.InputField("Name"), vt.InputField("Ort", "Berlin"),
                              vt.InputField("Gruß")])
    assert dlg.windowTitle() == "Eingaben für den Auftrag"
    assert [e.text() for e in dlg.edits] == ["Anna", "Berlin", ""]
    assert dlg.edits[2].placeholderText() == "‹Gruß›"
    assert "Leer: Gruß" in dlg.hint.text()
    dlg.edits[2].setText("Hallo")
    assert dlg.hint.text() == ""
    assert dlg.edits[0].maxLength() == vt.MAX_INPUT_CHARS
    assert dlg.values() == {"Name": "Anna", "Ort": "Berlin", "Gruß": "Hallo"}
    dlg.deleteLater()


# --- window -------------------------------------------------------------------------------

@pytest.fixture
def win(qapp, monkeypatch, tmp_path):
    from PySide6.QtCore import QSettings
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(tmp_path))
    QSettings.setDefaultFormat(QSettings.IniFormat)
    main = pytest.importorskip("main")
    w = main.LumaCutStudio()
    w.machine_panel._confirm = lambda *_: True
    w.workflow_adapter.confirm = lambda *_: True
    w.scan_panel.ask = False
    yield w
    w.canvas.undo_stack.setClean()
    w.scan_panel.shutdown()
    w.machine_panel.shutdown()
    w.close()
    w.deleteLater()
    qapp.processEvents()


def _variable(win, text, y=40):
    doc = win.canvas.document
    t = doc.add_shape(Shape("text", Geometry(40, y, 20, 8), doc.active_layer_id, text=text))
    win.canvas.set_selection([t.id])
    win.job_tools.variable_text(vt.VarTextSpec())
    win.canvas.set_selection([])
    return t


def test_send_asks_once_and_lasers_the_typed_value(win, monkeypatch):
    tools = win.job_tools
    asked = []
    tools.vartext_input_prompt = lambda fields: asked.append(fields) or {"Name": "Anna"}
    t = _variable(win, "Für {input:Name}")
    sent = []
    monkeypatch.setattr(win.machine_panel, "send_gcode",
                        lambda name, gcode, start=False: sent.append((gcode, start)))
    win._send_canvas_job()
    assert asked == [[vt.InputField("Name")]] and len(sent) == 1
    pi_check(sent[0][0])
    assert "Für Anna" in win.statusBar().currentMessage()
    assert vt.input_values() == {"name": "Anna"}
    assert win.canvas.document.shape(t.id).text == "Für {input:Name}"
    # canvas label, job document, estimate and frame: last typed value, no new question
    ov = tools.vartext_values
    ov.rebuild()
    assert ov.label_for(t.id).text == "→ Für Anna"
    assert next(s.text for s in tools.job_document().shapes if s.id == t.id) == "Für Anna"
    tools.show_estimate()
    assert "Für Anna" in win.statusBar().currentMessage()
    assert tools.frame_program() and len(asked) == 1
    # one-click start asks again (next part, next name)
    tools.vartext_input_prompt = lambda fields: asked.append(fields) or {"Name": "Bert"}
    assert win.workflow_adapter._send_and_start()
    assert len(asked) == 2 and sent[-1][1] is True and sent[-1][0] != sent[0][0]
    pi_check(sent[-1][0])
    assert vt.input_values() == {"name": "Bert"}


def test_cancel_blocks_send_start_and_save(win, monkeypatch, tmp_path):
    tools = win.job_tools
    tools.vartext_input_prompt = lambda fields: None
    _variable(win, "{input:Name}")
    sent = []
    monkeypatch.setattr(win.machine_panel, "send_gcode",
                        lambda name, gcode, start=False: sent.append(gcode))
    assert win._build_canvas_job() is None
    assert "abgebrochen" in win.statusBar().currentMessage()
    assert not win.workflow_adapter._send_and_start()
    out = tmp_path / "job.gcode"
    assert tools.save_gcode(str(out)) == "" and not out.exists()
    assert "Speichern nicht möglich" in win.statusBar().currentMessage()
    assert sent == [] and vt.input_values() == {}
    # estimate never asks: stand-in until something was typed
    tools.vartext_input_prompt = lambda fields: pytest.fail("estimate must not ask")
    assert tools.estimate().total_time_s > 0
    tools.show_estimate()
    assert "‹Name›" in win.statusBar().currentMessage()


def test_save_gcode_asks_and_no_question_without_input(win, tmp_path):
    tools = win.job_tools
    tools.vartext_input_prompt = lambda fields: pytest.fail("no {input:} – no question")
    _variable(win, "Nr. {n:3}")
    g, note = tools.job_gcode()
    assert "Nr. 001" in note
    _variable(win, "{eingabe:Gast=Team}", y=80)
    tools.vartext_input_prompt = lambda fields: {f.label: f.default.upper() for f in fields}
    out = tmp_path / "job.gcode"
    assert tools.save_gcode(str(out)) == str(out)
    assert "TEAM" in win.statusBar().currentMessage()
    pi_check(out.read_text(encoding="utf-8"))


def test_selection_only_asks_only_for_selected_inputs(win):
    tools = win.job_tools
    a = _variable(win, "{input:Name}", y=20)
    _variable(win, "{input:Ort}", y=80)
    asked = []
    tools.vartext_input_prompt = lambda fields: asked.append([f.label for f in fields]) or {}
    tools.job_gcode()
    assert asked == [["Name", "Ort"]]
    win.canvas.set_selection([a.id])
    tools.set_selection_only(True)
    tools.job_gcode()
    assert asked[-1] == ["Name"]
    tools.set_selection_only(False)


def test_typed_value_reschedules_previews(win):
    tools = win.job_tools
    t = _variable(win, "{input:Name}")
    ov = tools.vartext_values
    ov.rebuild()
    assert ov.label_for(t.id).text == "→ ‹Name›"
    tools.vartext_input_prompt = lambda fields: {"Name": "Cem"}
    tools.ask_vartext_inputs()
    assert ov.label_for(t.id).text == "→ Cem"
