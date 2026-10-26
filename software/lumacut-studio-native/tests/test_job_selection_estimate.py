"""„Nur Auswahl senden“, Zeit je Ebene und Planer-Hinweise in der UI."""
import pytest

from _pi_guard import pi_check
from lumacut_canvas.model import Document, Geometry, Layer, Shape
from lumacut_job.estimate import estimate_gcode
from lumacut_job.planner import optimized_document_gcode
from lumacut_job.selection import selection_document


def _two_layer_doc():
    doc = Document()
    cut = doc.active_layer_id
    eng = doc.add_layer(Layer(name="Gravur", power=20.0, speed=3000.0, passes=1)).id
    a = doc.add_shape(Shape("rect", Geometry(20, 20, 40, 30), cut))
    b = doc.add_shape(Shape("rect", Geometry(100, 20, 40, 30), cut))
    c = doc.add_shape(Shape("ellipse", Geometry(200, 100, 30, 30), eng))
    return doc, a, b, c


def test_estimate_has_time_per_layer():
    doc, *_ = _two_layer_doc()
    est = estimate_gcode(optimized_document_gcode(doc))
    names = [n for n, _ in est.layers]
    assert sorted(names) == ["Gravur", "Schneiden"]
    assert sum(t for _, t in est.layers) == pytest.approx(est.total_time_s, rel=1e-9)
    assert all(t > 0 for _, t in est.layers)
    # Gravur ist 5× schneller eingestellt und kleiner → kürzer als Schneiden
    t = dict(est.layers)
    assert t["Gravur"] < t["Schneiden"]
    text = est.layer_summary()
    assert "Schneiden" in text and "Gravur" in text


def test_estimate_without_layer_comments_and_single_layer():
    est = estimate_gcode("G21\nG90\nM3 I\nG0 X40 Y40\nG1 X80 Y40 S500 F600\nM5 I\n")
    assert est.layers == [("Auftrag", pytest.approx(est.total_time_s))]
    assert est.layer_summary() == ""


def test_selection_document_keeps_layers_and_only_selected():
    doc, a, b, c = _two_layer_doc()
    sel = selection_document(doc, [b.id])
    assert [l.name for l in sel.layers] == [l.name for l in doc.layers]
    assert [s.id for s in sel.shapes] == [b.id]
    assert len(doc.shapes) == 3  # Original unverändert
    full = estimate_gcode(optimized_document_gcode(doc))
    part = estimate_gcode(optimized_document_gcode(sel))
    assert part.cut_length_mm == pytest.approx(140, rel=0.01)
    assert part.cut_length_mm < full.cut_length_mm
    pi_check(optimized_document_gcode(sel))
    with pytest.raises(ValueError):
        selection_document(doc, [])
    with pytest.raises(ValueError):
        selection_document(doc, ["gibt-es-nicht"])


def test_main_window_selection_only_and_lead_warning(qapp, monkeypatch, tmp_path):
    from PySide6.QtCore import QSettings
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(tmp_path))
    QSettings.setDefaultFormat(QSettings.IniFormat)
    main = pytest.importorskip("main")
    win = main.LumaCutStudio()
    tools = win.job_tools
    doc = win.canvas.document
    lid = doc.active_layer_id
    a = doc.add_shape(Shape("rect", Geometry(20, 20, 40, 30), lid))
    doc.add_shape(Shape("rect", Geometry(100, 20, 40, 30), lid))
    sent = []
    monkeypatch.setattr(win.machine_panel, "send_gcode",
                        lambda n, g, start=False: sent.append((n, g, start)))
    # Nur Auswahl ohne Auswahl: nichts senden, Meldung
    tools.set_selection_only(True)
    win.canvas.set_selection([])
    win._send_canvas_job()
    assert sent == [] and "nichts ausgewählt" in win.statusBar().currentMessage()
    win.canvas.set_selection([a.id])
    win._send_canvas_job()
    assert len(sent) == 1
    assert estimate_gcode(sent[0][1]).cut_length_mm == pytest.approx(140, rel=0.01)
    assert "Nur Auswahl" in win.statusBar().currentMessage()
    est = tools.show_estimate()
    assert est.cut_length_mm == pytest.approx(140, rel=0.01)
    tools.set_selection_only(False)
    assert tools.show_estimate().cut_length_mm == pytest.approx(280, rel=0.01)
    # Teil in engem Rahmen (andere Ebene): Anfahrt fällt weg → Hinweis
    doc.update_layer(lid, lead_in_mm=3.0)
    frame = doc.add_layer(Layer(name="Rahmen")).id
    doc.add_shape(Shape("rect", Geometry(19.8, 19.8, 40.4, 30.4), frame))
    tools.show_estimate()
    assert "Anfahrt" in win.statusBar().currentMessage()
    win._send_canvas_job()
    msg = win.statusBar().currentMessage()
    assert "Gesendet" in msg and "Anfahrt bei 1 Kontur weggelassen" in msg
    pi_check(sent[-1][1])
    win.canvas.undo_stack.setClean()
    win.close()
