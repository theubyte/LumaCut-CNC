"""Scan-Versatz (LightBurn „Scanning Offset Adjustment“): Tabelle, Füllung, Bilder, Testmuster."""

from __future__ import annotations

import math

import pytest

from _pi_guard import pi_check


@pytest.fixture(autouse=True)
def _restore_active_table():
    from lumacut_job.scan_offset import active_table, set_active_table
    old = active_table()
    yield
    set_active_table(old)


def _doc(shapes=((10, 10, 20, 10),), **layer):
    from lumacut_canvas.model import Document, Geometry, Shape
    doc = Document()
    lid = doc.active_layer_id
    layer.setdefault("fill_mode", "hatch")
    layer.setdefault("line_interval_mm", 2.0)
    layer.setdefault("hatch_outline", False)
    doc.update_layer(lid, **layer)
    for x, y, w, h in shapes:
        doc.add_shape(Shape("rect", Geometry(x, y, w, h), lid))
    return doc


def _burns(g):
    """Powered moves as ((x0, y0), (x1, y1))."""
    out, pos = [], None
    for line in g.splitlines():
        if not line.startswith(("G0 ", "G1 ")):
            continue
        w = dict((t[0], float(t[1:])) for t in line.split()[1:])
        p = (w["X"], w["Y"])
        if line.startswith("G1") and w.get("S", 0) > 0 and pos is not None:
            out.append((pos, p))
        pos = p
    return out


def _table(*entries, enabled=True):
    from lumacut_job.scan_offset import ScanOffsetTable
    return ScanOffsetTable(enabled, list(entries)).normalized()


# --- Tabelle --------------------------------------------------------------------

def test_table_sorts_interpolates_and_clamps():
    t = _table((3000, 0.3), (1000, 0.1))
    assert t.entries == [(1000.0, 0.1), (3000.0, 0.3)]
    assert t.offset_for(2000) == pytest.approx(0.2)
    assert t.offset_for(1500) == pytest.approx(0.15)
    assert t.offset_for(100) == 0.1 and t.offset_for(6000) == 0.3   # nearest, no extrapolation
    assert t.active and "Scan-Versatz" in t.summary() and "0,30" in t.summary()
    assert _table((2000, 0.25)).offset_for(10) == 0.25
    off = _table((1000, 0.2), enabled=False)
    assert not off.active and off.offset_for(1000) == 0.0 and off.summary() == ""
    assert not _table().active and _table().offset_for(1000) == 0.0
    assert not _table((1000, 0.0)).active


@pytest.mark.parametrize("entries, text", [
    ([(1000, 0.1), (1000, 0.2)], "doppelt"),
    ([(0, 0.1)], "1..6000"),
    ([(7000, 0.1)], "1..6000"),
    ([(1000, 2.5)], "−2..2"),
    ([(1000, float("nan"))], "keine Zahl"),
    ([("x", 0.1)], "keine Zahl"),
    ([(1000,)], "braucht"),
    ([(i + 1, 0.1) for i in range(33)], "höchstens"),
])
def test_table_errors(entries, text):
    from lumacut_job.scan_offset import ScanOffsetTable
    with pytest.raises(ValueError, match=text):
        ScanOffsetTable(True, entries).normalized()


def test_table_json_round_trip_and_bad_input():
    from lumacut_job.scan_offset import ScanOffsetTable
    t = _table((1000, 0.1), (4000, -0.05), enabled=False)
    back = ScanOffsetTable.from_json(t.to_json())
    assert back == t and back.to_dict()["version"] == 1
    for bad in ("", "[1]", '{"entries": 3}', '{"entries": [[1000, 9]]}', "{"):
        with pytest.raises(ValueError):
            ScanOffsetTable.from_json(bad)


def test_active_table_default_is_off():
    from lumacut_job.scan_offset import active_table, set_active_table
    set_active_table(None)
    assert not active_table().active
    old = set_active_table(_table((1000, 0.2)))
    assert not old.active and active_table().offset_for(1000) == 0.2


# --- Geometrie ------------------------------------------------------------------

def test_segment_shift_is_half_against_travel_and_clamped():
    from lumacut_canvas.gcode import scan_offset_segment
    from lumacut_canvas.workarea import MACHINE_X_MAX, MACHINE_X_MIN
    a, b = (100.0, 50.0), (110.0, 50.0)
    assert scan_offset_segment(a, b, 0.4) == ((99.8, 50.0), (109.8, 50.0))
    assert scan_offset_segment(b, a, 0.4) == ((110.2, 50.0), (100.2, 50.0))
    assert scan_offset_segment(a, b, -0.4) == ((100.2, 50.0), (110.2, 50.0))
    assert scan_offset_segment(a, b, 0.0) == (a, b)
    assert scan_offset_segment(a, a, 0.4) == (a, a)
    # diagonal: along the line
    (p, q) = scan_offset_segment((0.0 + 100, 100.0), (103.0, 104.0), 1.0)
    assert p == pytest.approx((99.7, 99.6)) and q == pytest.approx((102.7, 103.6))
    # at the edge of travel the shift is shortened, never outside
    edge = (MACHINE_X_MIN + 0.05, 50.0)
    p, q = scan_offset_segment(edge, (MACHINE_X_MIN + 10, 50.0), 0.4)
    assert p[0] == pytest.approx(MACHINE_X_MIN) and q[0] == pytest.approx(MACHINE_X_MIN + 9.95)
    p, q = scan_offset_segment((MACHINE_X_MAX - 10, 50.0), (MACHINE_X_MAX, 50.0), -0.4)
    assert (p, q) == ((MACHINE_X_MAX - 10, 50.0), (MACHINE_X_MAX, 50.0))


# --- Vektor-Füllung ---------------------------------------------------------------

def test_hatch_lines_meet_after_compensation(qapp):
    from dataclasses import replace

    from lumacut_canvas.export import job_layers
    from lumacut_canvas.gcode import layers_to_gcode
    (jl,) = job_layers(_doc())
    base = layers_to_gcode([jl])
    assert layers_to_gcode([replace(jl, fill_scan_offset_mm=0.0)]) == base
    shifted = layers_to_gcode([replace(jl, fill_scan_offset_mm=0.3)])
    pi_check(shifted)
    b0, b1 = _burns(base), _burns(shifted)
    assert len(b0) == len(b1) > 2
    for (a, b), (c, d) in zip(b0, b1):
        u = (b[0] - a[0]) / math.dist(a, b)
        assert c[0] == pytest.approx(a[0] - 0.15 * u, abs=1e-3)
        assert d[0] == pytest.approx(b[0] - 0.15 * u, abs=1e-3)
        assert c[1] == pytest.approx(a[1]) and d[1] == pytest.approx(b[1])
    dirs = {round((b[0] - a[0]) / abs(b[0] - a[0])) for a, b in b1}
    assert dirs == {-1, 1}    # bidirectional: both directions shifted


def test_overscan_follows_the_shifted_line(qapp):
    from dataclasses import replace

    from lumacut_canvas.export import job_layers
    from lumacut_canvas.gcode import layers_to_gcode
    (jl,) = job_layers(_doc(fill_overscan_mm=2.0))
    g = layers_to_gcode([replace(jl, fill_scan_offset_mm=0.4)])
    pi_check(g)
    lines = g.splitlines()
    i = next(k for k, l in enumerate(lines) if l.startswith("G0 "))
    x0 = float(lines[i].split()[1][1:])
    x1 = float(lines[i + 1].split()[1][1:])
    x2 = float(lines[i + 2].split()[1][1:])
    assert abs(x1 - x0) == pytest.approx(2.0) and lines[i + 1].endswith("S0")
    (a, b), = [s for s in [_burns(g)[0]]]
    assert (a[0], b[0]) == (pytest.approx(x1), pytest.approx(x2))


def test_planner_uses_active_table_only_for_line_fills(qapp):
    from lumacut_job.planner import PlanReport, optimized_document_gcode
    from lumacut_job.scan_offset import set_active_table
    doc = _doc(speed=2000.0, hatch_outline=True)
    off_doc = _doc(fill_mode="offset", speed=2000.0)
    plain, plain_off = optimized_document_gcode(doc), optimized_document_gcode(off_doc)
    set_active_table(_table((1000, 0.1), (3000, 0.3)))
    rep = PlanReport()
    g = optimized_document_gcode(doc, report=rep)
    assert g != plain and "Scan-Versatz" in rep.message()
    assert optimized_document_gcode(doc, scan_offsets=None) == plain
    assert optimized_document_gcode(off_doc) == plain_off          # rings stay traced
    assert optimized_document_gcode(doc, scan_offsets=_table((1, 0.2), enabled=False)) == plain
    pi_check(g)
    # contours (last 5 powered moves = rectangle outline) are not shifted
    assert _burns(g)[-4:] == _burns(plain)[-4:]
    # fill lines moved by 0.2 / 2 at 2000 mm/min
    (a, b), (c, d) = _burns(plain)[0], _burns(g)[0]
    assert abs(c[0] - a[0]) == pytest.approx(0.1, abs=1e-3)
    # no fill: report stays empty
    rep = PlanReport()
    optimized_document_gcode(_doc(fill_mode="none"), report=rep)
    assert rep.message() == ""


def test_report_message_combines_with_skipped_leads():
    from lumacut_job.planner import PlanReport
    rep = PlanReport(skipped_leads=1, layers_with_skipped=["A"], scan_offset="Scan-Versatz x")
    assert rep.message().startswith("Anfahrt bei 1 Kontur") and rep.message().endswith("Scan-Versatz x")


# --- Bilder -----------------------------------------------------------------------

def _image_doc(x=100.0, w=20.0):
    from PySide6.QtGui import QColor, QImage

    from lumacut_canvas.model import Document, Geometry, ImageSettings, RasterImage, Shape
    from lumacut_import.image import grayscale_png
    doc = Document()
    img = QImage(20, 10, QImage.Format_RGB32)
    img.fill(QColor(0, 0, 0))
    png, pw, ph = grayscale_png(img)
    st = ImageSettings(line_interval_mm=0.5, speed_mm_min=3000.0, mode="threshold")
    doc.add_shape(Shape("image", Geometry(x, 100, w, 10), doc.active_layer_id,
                        image=RasterImage(png, pw, ph, st)))
    return doc


def test_image_rows_shift_half_against_travel(qapp):
    from lumacut_job.planner import optimized_document_gcode
    doc = _image_doc()
    base = optimized_document_gcode(doc, scan_offsets=None)
    g = optimized_document_gcode(doc, scan_offsets=_table((3000, 0.4)))
    pi_check(g)
    b0, b1 = _burns(base), _burns(g)
    assert len(b0) == len(b1) > 4
    dirs = set()
    for (a, b), (c, d) in zip(b0, b1):
        u = 1 if b[0] > a[0] else -1
        dirs.add(u)
        assert c[0] == pytest.approx(a[0] - 0.2 * u, abs=1e-3)
        assert d[0] == pytest.approx(b[0] - 0.2 * u, abs=1e-3)
    assert dirs == {-1, 1}


def test_image_offset_is_shortened_at_the_edge(qapp):
    from lumacut_canvas.workarea import MACHINE_X_MAX, MACHINE_X_MIN, WORK_WIDTH_MM
    from lumacut_job.images import image_job
    for x in (0.0, WORK_WIDTH_MM - 20.0):
        doc = _image_doc(x=x)
        shape = next(s for s in doc.shapes if s.kind == "image")
        job = image_job(shape, "", _table((3000, 2.0)))
        burns = _burns("\n".join(job.lines))
        xs = [p[0] for seg in burns for p in seg]
        assert MACHINE_X_MIN - 1e-6 <= min(xs) and max(xs) <= MACHINE_X_MAX + 1e-6


# --- Testmuster -------------------------------------------------------------------

def test_pattern_layers_and_gcode(qapp):
    from lumacut_job.scan_offset import ScanTestSpec, test_pattern_gcode, test_pattern_layers
    spec = ScanTestSpec(speeds=[1000, 3000], offset_min=0.0, offset_max=0.3, offset_step=0.1)
    assert spec.offsets() == [0.0, 0.1, 0.2, 0.3]
    layers = test_pattern_layers(spec)
    cells = [l for l in layers if l.fills]
    assert len(cells) == 8
    assert [l.fill_scan_offset_mm for l in cells[:4]] == [0.0, 0.1, 0.2, 0.3]
    assert {l.speed_mm_min for l in cells} == {1000.0, 3000.0}
    assert any(l.polylines and not l.fills for l in layers)      # labels
    g = test_pattern_gcode(spec)
    pi_check(g)
    assert "; SCAN OFFSET TEST" in g.splitlines()[1] and "+0.30" in g
    assert g.count("; LAYER Scan-Test F") == 8
    nolabel = test_pattern_gcode(ScanTestSpec(speeds=[1000], labels=False))
    assert "Beschriftung" not in nolabel
    pi_check(nolabel)


@pytest.mark.parametrize("kw, text", [
    (dict(speeds=[]), "1..10"),
    (dict(speeds=[1000, 1000]), "doppelt"),
    (dict(speeds=[9000]), "1..6000"),
    (dict(offset_min=0.5, offset_max=0.1), "von ≤ bis"),
    (dict(offset_step=0.001), "Schrittweite"),
    (dict(offset_min=-2, offset_max=2, offset_step=0.1), "1..12"),
    (dict(power=0), "Leistung"),
    (dict(line_interval_mm=5), "Linienabstand"),
    (dict(patch_w_mm=1), "Feld"),
    (dict(x=380), "Arbeitsfläche"),
])
def test_pattern_spec_errors(kw, text):
    from lumacut_job.scan_offset import ScanTestSpec
    with pytest.raises(ValueError, match=text):
        ScanTestSpec(**kw).validate()


# --- Qt ---------------------------------------------------------------------------

def test_settings_round_trip(qapp, tmp_path):
    from PySide6.QtCore import QSettings

    from lumacut_job.scan_offset_qt import SETTINGS_KEY, load_table, save_table
    st = QSettings(str(tmp_path / "s.ini"), QSettings.IniFormat)
    assert load_table(st) is None and load_table(None) is None
    t = _table((1000, 0.1), (5000, 0.35))
    save_table(st, t)
    save_table(None, t)
    assert load_table(st) == t
    st.setValue(SETTINGS_KEY, "kaputt")
    assert load_table(st) is None


def test_dialog_table_edit_and_errors(qapp):
    from PySide6.QtWidgets import QDialogButtonBox, QTableWidgetItem

    from lumacut_job.scan_offset_qt import ScanOffsetDialog
    dlg = ScanOffsetDialog(_table((1000, 0.1), (3000, 0.3)))
    assert dlg.grid.rowCount() == 2 and not dlg.test_btn.isEnabled()
    dlg.probe.setText("2000")
    assert "0,200" in dlg.check_label.text()
    dlg.add_row()
    assert dlg.grid.rowCount() == 3 and dlg.grid.item(2, 0).text() == "4000"
    dlg.grid.setItem(2, 1, QTableWidgetItem("0,45"))
    assert dlg.table().entries[-1] == (4000.0, 0.45)
    dlg.grid.setItem(2, 1, QTableWidgetItem("abc"))
    assert "Zeile 3" in dlg.error.text()
    assert not dlg.buttons.button(QDialogButtonBox.Ok).isEnabled()
    dlg.grid.selectRow(2)
    dlg.remove_selected()
    assert dlg.grid.rowCount() == 2 and dlg.buttons.button(QDialogButtonBox.Ok).isEnabled()
    dlg.enabled.setChecked(False)
    assert dlg.check_label.text() == "aus" and not dlg.table().enabled
    dlg.set_entries([])
    dlg.enabled.setChecked(True)
    assert "keine Einträge" in dlg.check_label.text()


def test_test_dialog_spec_and_callbacks(qapp):
    from lumacut_job.scan_offset_qt import ScanTestDialog
    got = []
    dlg = ScanTestDialog(None, None, send=got.append, save=None)
    assert dlg.send_btn.isEnabled() and not dlg.save_btn.isEnabled()
    assert "5 Reihen × 5 Felder" in dlg.info.text()
    dlg.speeds.setText("1500; 2500")
    assert dlg.spec().speeds == [1500.0, 2500.0]
    dlg.send_btn.click()
    assert got and got[0] == dlg.result_gcode and "F2500" in got[0]
    dlg.speeds.setText("schnell")
    assert not dlg.send_btn.isEnabled() and "Zahlen" in dlg.info.text()


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


def test_window_action_menu_job_note_and_test_pattern(win, tmp_path, monkeypatch):
    from lumacut_canvas.model import Geometry, Shape
    from lumacut_job.scan_offset import active_table
    tools = win.job_tools
    a = tools.scan_offset_action
    assert a.objectName() == "scan_offset_action" and a.text() == "Scan-Versatz…"
    assert a in win.main_view.job_menu.actions()
    doc = win.canvas.document
    lid = doc.active_layer_id
    doc.update_layer(lid, fill_mode="hatch", line_interval_mm=2.0, speed=2000.0)
    doc.add_shape(Shape("rect", Geometry(20, 20, 20, 10), lid))
    g0, note0 = tools.job_gcode()
    assert "Scan-Versatz" not in note0
    t = tools.scan_offset(_table((2000, 0.2)))
    assert t == active_table() and "Scan-Versatz" in win.statusBar().currentMessage()
    g1, note1 = tools.job_gcode()
    assert g1 != g0 and "Scan-Versatz" in note1
    assert tools.scan_offset(_table((2000, 0.2), enabled=False)) is not None
    assert tools.job_gcode()[0] == g0 and win.statusBar().currentMessage() == "Scan-Versatz aus"
    # test pattern: save and send (send without start)
    from lumacut_job.scan_offset import ScanTestSpec
    p = tmp_path / "t.gcode"
    g = tools.scan_test(ScanTestSpec(speeds=[1000]), "save", str(p))
    assert p.read_text(encoding="utf-8") == g and "gespeichert" in win.statusBar().currentMessage()
    sent = []
    monkeypatch.setattr(win.machine_panel, "send_gcode",
                        lambda name, gcode, start=False, **kw: sent.append((name, gcode, start)))
    tools.scan_test(ScanTestSpec(speeds=[1000]), "send")
    assert sent == [("scan-versatz-test.gcode", g, False)]
    assert tools.scan_test(ScanTestSpec(speeds=[]), "send") == ""
    assert "1..10" in win.statusBar().currentMessage()
