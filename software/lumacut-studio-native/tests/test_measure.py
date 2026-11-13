"""Werkzeug „Messen“ (M): Abstand / ΔX / ΔY / Winkel zwischen zwei gefangenen Punkten."""

import math
import sys
from pathlib import Path

import pytest
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _pi_guard import pi_check  # noqa: E402

from lumacut_canvas import icons, measure, measure_ui, units  # noqa: E402
from lumacut_canvas.commands import AddShapesCommand  # noqa: E402
from lumacut_canvas.editor import CanvasEditor  # noqa: E402
from lumacut_canvas.measure import Measurement  # noqa: E402
from lumacut_canvas.model import Geometry, Shape  # noqa: E402
from lumacut_canvas.tools import TOOL_LABELS, TOOL_SHORTCUTS, Tool  # noqa: E402
from lumacut_canvas.unit_ui import display_units  # noqa: E402
from lumacut_canvas.workarea import WORK_WIDTH_MM  # noqa: E402

NO = Qt.NoModifier
SHIFT = Qt.ShiftModifier
ALT = Qt.AltModifier
ZOOM = 4.0  # px/mm → Objektfang 7 px = 1.75 mm


# --- Rechnen (Qt-frei) ---------------------------------------------------------
def test_length_deltas_follow_the_displayed_origin_top_right():
    m = Measurement(10.0, 20.0, 40.0, 60.0)
    assert m.length == pytest.approx(50.0)
    # Nullpunkt oben rechts: nach rechts auf dem Bildschirm = X wird kleiner.
    assert m.dx == pytest.approx(-30.0) and m.dy == pytest.approx(40.0)
    assert m.start == (10.0, 20.0) and m.end == (40.0, 60.0) and m.midpoint() == (25.0, 40.0)
    assert not m.is_point and Measurement(5, 5, 5, 5).is_point


@pytest.mark.parametrize("end, angle", [((20, 10), 0.0), ((10, 0), 90.0), ((0, 10), 180.0),
                                        ((10, 20), -90.0), ((20, 0), 45.0), ((0, 20), -135.0)])
def test_angle_is_on_screen_counter_clockwise_from_right(end, angle):
    assert Measurement(10, 10, *end).angle == pytest.approx(angle)
    assert Measurement(10, 10, 10, 10).angle == 0.0


def test_constrain_snaps_direction_to_15_degree_steps_by_projection():
    x, y = measure.constrain((0.0, 0.0), (10.0, 1.0))
    assert (x, y) == pytest.approx((10.0, 0.0))
    x, y = measure.constrain((10.0, 10.0), (20.0, 2.0))  # ≈ 38.7° nach oben → 45°
    assert math.degrees(math.atan2(-(y - 10), x - 10)) == pytest.approx(45.0)
    assert math.hypot(x - 10, y - 10) == pytest.approx((10 + 8) / math.sqrt(2))
    x, y = measure.constrain((0, 0), (10, -2.9))  # 16.2° → 15°
    assert math.degrees(math.atan2(-y, x)) == pytest.approx(15.0)
    assert measure.constrain((3, 4), (3, 4)) == (3, 4)


def test_texts_in_mm_and_inch_with_real_minus_and_no_negative_zero():
    m = Measurement(10, 10, 40, 50)
    assert measure.label_lines(m, units.MM) == ["50.00 mm", "ΔX \u221230.00 mm   ΔY 40.00 mm",
                                                "Winkel \u221253.1°"]
    assert measure.readout(m, units.MM) == ("Messen: Abstand 50.00 mm · ΔX \u221230.00 mm · "
                                            "ΔY 40.00 mm · Winkel \u221253.1°")
    assert measure.clipboard_text(m, units.MM) == "50.00 mm"
    assert units.parse_length(measure.clipboard_text(m, units.MM), units.MM) == pytest.approx(50.0)
    inch = Measurement(0, 0, 25.4, 0)
    assert measure.label_lines(inch, units.INCH)[:2] == ["1.000 in", "ΔX \u22121.000 in   ΔY 0.000 in"]
    assert measure.clipboard_text(inch, units.INCH) == "1.000 in"
    tiny = Measurement(0, 0, 0.001, -0.001)  # rundet auf 0.00 – ohne Minus
    assert "\u2212" not in measure.label_lines(tiny, units.MM)[1]
    assert measure.format_angle(-0.01) == "0.0°" and measure.format_angle(-179.99) == "180.0°"


# --- Editor ------------------------------------------------------------------
@pytest.fixture
def ed(qapp):
    display_units().set_unit(units.MM)
    e = CanvasEditor()
    e.resize(1000, 700)
    e.show()
    qapp.processEvents()
    e.view.set_zoom(ZOOM)
    e.object_snap.set_enabled(True, persist=False)
    msgs = []
    e.statusMessage.connect(msgs.append)
    e.msgs = msgs
    yield e
    display_units().set_unit(units.MM)
    e.undo_stack.setClean()
    e.close()


def add(ed, *shapes):
    for s in shapes:
        s.layer_id = ed.document.active_layer_id
    ed.undo_stack.push(AddShapesCommand(ed.document, list(shapes)))
    return [ed.document.shape(s.id) for s in shapes]


def rect(x, y, w, h, rot=0.0):
    return Shape("rect", Geometry(x, y, w, h, rot), "?")


def drag(ed, a, b, mods=NO, release=True):
    t = ed.tools
    t.press(QPointF(*a), mods)
    t.move(QPointF((a[0] + b[0]) / 2, (a[1] + b[1]) / 2), mods, True)
    t.move(QPointF(*b), mods, True)
    if release:
        t.release(QPointF(*b), mods)


def tap(ed, p, mods=NO):
    ed.tools.press(QPointF(*p), mods)
    ed.tools.release(QPointF(*p), mods)


def key(ed, k, mods=NO):
    ev = QKeyEvent(QEvent.KeyPress, k, mods)
    return ed.tools.key_press(ev)


def test_tool_label_shortcut_icon_and_strip_position(ed):
    a = ed.actions_by_name["tool_measure"]
    assert TOOL_LABELS[Tool.MEASURE] == "Messen" and TOOL_SHORTCUTS[Tool.MEASURE] == "M"
    assert a.shortcut().toString() == "M" and a.isCheckable() and not a.icon().isNull()
    assert "measure" in icons.available()
    strip = ed.tool_strip.actions()
    assert strip[-1] is a and strip.index(a) == strip.index(ed.actions_by_name["tool_start"]) + 1
    assert strip.index(ed.actions_by_name["tool_start"]) == strip.index(ed.actions_by_name["tool_tabs"]) + 1
    a.trigger()
    assert ed.tools.tool == Tool.MEASURE and a.isChecked()
    assert ed.msgs[-1].startswith("Werkzeug: Messen") and "Umschalt = 15°" in ed.msgs[-1]
    assert ed.view.viewport().cursor().shape() == Qt.CrossCursor


def test_drag_snaps_to_object_corners_and_shows_overlay(ed):
    add(ed, rect(20.4, 30.6, 40, 20))
    ed.set_tool(Tool.MEASURE)
    drag(ed, (20.9, 31.0), (60.0, 50.2), release=False)  # Ecken (20.4, 30.6) und (60.4, 50.6)
    mt = ed.measure_tool
    m = mt.measurement
    assert (m.x1, m.y1, m.x2, m.y2) == pytest.approx((20.4, 30.6, 60.4, 50.6))
    assert "Fang: Ecke" in ed.msgs[-1] and ed.msgs[-1].startswith("Messen: Abstand 44.72 mm")
    assert ed.object_snap.guides.isVisible()
    ed.tools.release(QPointF(60.0, 50.2), NO)
    m = mt.measurement
    assert m.length == pytest.approx(math.hypot(40, 20))
    assert m.dx == pytest.approx(-40.0) and m.dy == pytest.approx(20.0)
    assert m.angle == pytest.approx(-math.degrees(math.atan2(20, 40)))
    assert ed.msgs[-1] == ("Messen: Abstand 44.72 mm · ΔX \u221240.00 mm · ΔY 20.00 mm · Winkel "
                           "\u221226.6°  (Strg+C kopiert den Abstand, Esc löscht)")
    # Bleibt stehen: Strecke, zwei Marken, Schild; Fang-Hilfslinien weg.
    assert mt.line.isVisible() and all(mk.isVisible() for mk in mt.markers)
    assert mt.label.isVisible() and mt.label.lines[0] == "44.72 mm"
    assert mt.label.pos() == QPointF(40.4, 40.6)
    assert mt.markers[1].pos() == QPointF(60.4, 50.6)
    assert not ed.object_snap.guides.isVisible() and ed.object_snap.targets is None
    assert not mt.active and ed.tools._mode is None


def test_snaps_to_centre_and_edge_midpoint_and_falls_back_to_grid(ed):
    add(ed, rect(20.4, 30.6, 40, 20))
    ed.set_tool(Tool.MEASURE)
    drag(ed, (40.0, 40.0), (60.0, 40.0))  # Mitte (40.4, 40.6) → Kantenmitte (60.4, 40.6)
    m = ed.measure_tool.measurement
    assert (m.x1, m.y1, m.x2, m.y2) == pytest.approx((40.4, 40.6, 60.4, 40.6))
    assert m.length == pytest.approx(20.0) and m.angle == pytest.approx(0.0)
    drag(ed, (100.3, 100.4), (150.6, 120.2))  # weit weg von Objekten: 1-mm-Raster
    m = ed.measure_tool.measurement
    assert (m.x1, m.y1, m.x2, m.y2) == pytest.approx((100, 100, 151, 120))


def test_alt_suspends_object_snap_grid_stays(ed):
    add(ed, rect(20.4, 30.6, 40, 20))
    ed.set_tool(Tool.MEASURE)
    drag(ed, (20.9, 31.0), (60.0, 50.2), ALT)
    m = ed.measure_tool.measurement
    assert (m.x1, m.y1, m.x2, m.y2) == pytest.approx((21, 31, 60, 50))
    ed.object_snap.set_enabled(False, persist=False)
    drag(ed, (20.9, 31.0), (60.0, 50.2))
    m = ed.measure_tool.measurement
    assert (m.x1, m.y1, m.x2, m.y2) == pytest.approx((21, 31, 60, 50))


def test_without_grid_points_are_free(ed):
    ed.actions_by_name["snap"].trigger()  # Raster-Fang aus
    try:
        ed.set_tool(Tool.MEASURE)
        drag(ed, (100.3, 100.4), (150.6, 120.2))
        m = ed.measure_tool.measurement
        assert (m.x1, m.y1, m.x2, m.y2) == pytest.approx((100.3, 100.4, 150.6, 120.2))
    finally:
        ed.actions_by_name["snap"].trigger()


def test_shift_constrains_to_15_degree_steps(ed):
    ed.set_tool(Tool.MEASURE)
    drag(ed, (100, 100), (150, 87), SHIFT)  # ≈ 14.6° → 15°
    m = ed.measure_tool.measurement
    assert m.angle == pytest.approx(15.0)
    drag(ed, (100, 100), (120, 141), SHIFT)  # ≈ −64° → −60°
    assert ed.measure_tool.measurement.angle == pytest.approx(-60.0)
    drag(ed, (100, 100), (101, 140), SHIFT)
    m = ed.measure_tool.measurement
    assert m.angle == pytest.approx(-90.0) and m.x2 == pytest.approx(100.0)


def test_two_taps_measure_and_end_follows_the_pointer(ed):
    add(ed, rect(20.4, 30.6, 40, 20))
    ed.set_tool(Tool.MEASURE)
    mt = ed.measure_tool
    tap(ed, (20.9, 31.0))
    assert mt.pending and mt.active and "Startpunkt gesetzt" in ed.msgs[-1]
    assert mt.measurement.is_point and mt.markers[0].isVisible() and not mt.line.isVisible()
    ed.tools.move(QPointF(60.0, 50.2), NO, False)  # Maus ohne Taste: Ende folgt, fängt
    assert mt.measurement.end == pytest.approx((60.4, 50.6)) and "Fang: Ecke" in ed.msgs[-1]
    assert mt.line.isVisible() and ed.object_snap.targets is not None
    ed.tools.move(QPointF(100.2, 30.9), SHIFT, False)
    assert mt.measurement.angle == pytest.approx(0.0)
    tap(ed, (60.0, 50.2))
    assert not mt.pending and not mt.active
    assert mt.measurement.length == pytest.approx(math.hypot(40, 20))
    assert ed.object_snap.targets is None
    ed.tools.move(QPointF(150, 150), NO, False)  # danach bleibt die Messung stehen
    assert mt.measurement.end == pytest.approx((60.4, 50.6))
    tap(ed, (100, 100))  # ein neuer Tipp beginnt eine neue Messung
    assert mt.pending and mt.measurement.start == (100.0, 100.0)


def test_mouse_double_click_sets_the_end_point(ed):
    ed.set_tool(Tool.MEASURE)
    mt = ed.measure_tool
    tap(ed, (100, 100))
    ed.tools.move(QPointF(130, 140), NO, False)
    # Qt: zweites Drücken eines schnellen Doppelklicks kommt als Doppelklick.
    ed.tools.double_click(QPointF(130, 140))
    assert ed.tools._mode == "measure"
    ed.tools.release(QPointF(130, 140), NO)
    assert not mt.pending and mt.measurement.length == pytest.approx(50.0)
    # Touch: zwei Tipps (Messung fertig), danach meldet die Ansicht einen Doppeltipp.
    tap(ed, (10, 10))
    tap(ed, (10, 40))
    ed.tools.double_click(QPointF(10, 40))
    assert not mt.active and ed.tools._mode is None
    assert mt.measurement.length == pytest.approx(30.0)


def test_escape_clears_measurement_then_selection(ed):
    s, = add(ed, rect(20, 30, 40, 20))
    ed.set_selection([s.id])
    ed.set_tool(Tool.MEASURE)
    mt = ed.measure_tool
    drag(ed, (100, 100), (130, 140))
    assert key(ed, Qt.Key_Escape)
    assert mt.measurement is None and not mt.label.isVisible() and not mt.line.isVisible()
    assert ed.msgs[-1] == "Messung gelöscht" and ed.selection == [s.id]
    tap(ed, (100, 100))
    assert key(ed, Qt.Key_Escape) and not mt.pending and mt.measurement is None
    assert key(ed, Qt.Key_Escape) and ed.selection == []  # nichts mehr zu löschen: wie sonst


def test_measurement_kept_until_the_tool_changes(ed):
    ed.set_tool(Tool.MEASURE)
    mt = ed.measure_tool
    drag(ed, (100, 100), (130, 140))
    ed.view.set_zoom(8.0)
    assert mt.measurement is not None and mt.label.isVisible()
    ed.set_tool(Tool.SELECT)
    assert mt.measurement is None and not mt.label.isVisible() and not any(m.isVisible() for m in mt.markers)
    ed.set_tool(Tool.MEASURE)
    tap(ed, (100, 100))
    ed.set_tool(Tool.RECT)
    assert not mt.pending and mt.measurement is None


def test_copy_puts_the_distance_on_the_clipboard(ed):
    s, = add(ed, rect(20, 30, 40, 20))
    ed.set_selection([s.id])
    ed.copy_selection()
    shapes_clip = list(ed._clipboard)
    ed.set_tool(Tool.MEASURE)
    drag(ed, (100, 100), (130, 140))
    ed.actions_by_name["copy"].trigger()  # Strg+C im Werkzeug
    assert QApplication.clipboard().text() == "50.00 mm"
    assert "in die Zwischenablage kopiert" in ed.msgs[-1]
    assert [c.id for c in ed._clipboard] == [c.id for c in shapes_clip]  # Objekt-Ablage unverändert
    QApplication.clipboard().setText("x")
    ed.actions_by_name["measure_copy"].trigger()
    assert QApplication.clipboard().text() == "50.00 mm"
    key(ed, Qt.Key_Escape)
    ed.copy_selection()  # ohne Messung: normales Kopieren der Auswahl
    assert QApplication.clipboard().text() == "50.00 mm" and ed._clipboard
    assert not ed.measure_tool.copy()


def test_context_menu_offers_copy_and_clear(ed):
    ed.set_tool(Tool.MEASURE)
    menu = ed.build_context_menu(QPointF(300, 300))
    assert "Messung kopieren" not in [a.text() for a in menu.actions()]
    drag(ed, (100, 100), (130, 140))
    menu = ed.build_context_menu(QPointF(300, 300))
    texts = [a.text() for a in menu.actions()]
    assert texts[:2] == ["Messung kopieren", "Messung löschen"]
    ed.actions_by_name["measure_clear"].trigger()
    assert ed.measure_tool.measurement is None and ed.msgs[-1] == "Messung gelöscht"
    ed.set_tool(Tool.SELECT)
    menu = ed.build_context_menu(QPointF(300, 300))
    assert "Messung kopieren" not in [a.text() for a in menu.actions()]


def test_unit_change_relabels_in_inch(ed):
    ed.set_tool(Tool.MEASURE)
    ed.actions_by_name["snap"].trigger()  # Raster aus: 50.8 mm = 2 in
    try:
        drag(ed, (100, 100), (150.8, 100))
    finally:
        ed.actions_by_name["snap"].trigger()
    mt = ed.measure_tool
    display_units().set_unit(units.INCH)
    assert mt.label.lines[0] == "2.000 in"
    assert mt.label.lines[1] == "ΔX \u22122.000 in   ΔY 0.000 in"
    ed.copy_selection()
    assert QApplication.clipboard().text() == "2.000 in"
    display_units().set_unit(units.MM)
    assert mt.label.lines[0] == "50.80 mm"


def test_touch_mode_reach_14px_and_bigger_overlay(ed):
    add(ed, rect(20.4, 30.6, 40, 20))
    ed.set_tool(Tool.MEASURE)
    mt = ed.measure_tool
    drag(ed, (22.4, 32.6), (100, 100))  # 2 mm × 2 mm neben der Ecke: außerhalb 1.75 mm
    assert mt.measurement.start == pytest.approx((22.0, 33.0))
    small_r, small_box = mt.markers[0].radius(), mt.label.boundingRect()
    ed.set_touch_mode(True, persist=False)
    try:
        assert mt.measurement is not None  # bleibt beim Umschalten stehen
        assert mt.markers[0].radius() > small_r
        assert mt.label.boundingRect().height() > small_box.height()
        drag(ed, (22.4, 32.6), (100, 100))  # 14 px = 3.5 mm Reichweite
        assert mt.measurement.start == pytest.approx((20.4, 30.6))
    finally:
        ed.set_touch_mode(False, persist=False)


def test_second_finger_aborts_a_running_measurement(ed):
    ed.set_tool(Tool.MEASURE)
    mt = ed.measure_tool
    drag(ed, (100, 100), (130, 140), release=False)
    ed.tools.abort_drag()
    assert mt.measurement is None and not mt.active and ed.tools._mode is None
    assert not ed.object_snap.guides.isVisible()


def test_label_sits_beside_the_line(ed):
    ed.set_tool(Tool.MEASURE)
    mt = ed.measure_tool
    drag(ed, (100, 100), (150, 100))  # waagerecht: Schild mittig darüber
    r = mt.label.boundingRect()
    assert r.bottom() < 0 and r.center().x() == pytest.approx(0.0, abs=1.5)
    drag(ed, (100, 100), (100, 150))  # senkrecht: rechts daneben
    r = mt.label.boundingRect()
    assert r.left() > 0 and r.center().y() == pytest.approx(0.0, abs=1.5)
    drag(ed, (100, 100), (150, 150))  # nach rechts unten: oben rechts
    r = mt.label.boundingRect()
    assert r.left() > 0 and r.bottom() < 0


def test_not_a_document_object_no_undo_no_gcode_change_not_saved(ed, tmp_path):
    from lumacut_job.planner import optimized_document_gcode
    add(ed, rect(20.4, 30.6, 40, 20), rect(100, 100, 30, 30))
    before = optimized_document_gcode(ed.document, scan_offsets=None)
    n_undo, n_shapes = ed.undo_stack.count(), len(ed.document.shapes)
    clean = ed.undo_stack.isClean()
    ed.set_tool(Tool.MEASURE)
    drag(ed, (20.9, 31.0), (100.2, 100.3))
    tap(ed, (50, 50))
    tap(ed, (70, 90))
    assert ed.measure_tool.measurement is not None
    assert ed.undo_stack.count() == n_undo and ed.undo_stack.isClean() == clean
    assert len(ed.document.shapes) == n_shapes and ed.selection == []
    after = optimized_document_gcode(ed.document, scan_offsets=None)
    assert after == before  # byte-identisch
    pi_check(after)
    path = ed.save_file(tmp_path / "m.lcs")
    text = path.read_text(encoding="utf-8")
    assert "measure" not in text.lower() and "Messen" not in text
    ed.load_file(path)
    assert ed.measure_tool.measurement is None
    assert optimized_document_gcode(ed.document, scan_offsets=None) == before


def test_locked_or_hidden_active_layer_still_measures(ed):
    lid = ed.document.active_layer_id
    ed.document.update_layer(lid, locked=True)
    ed.set_tool(Tool.MEASURE)
    drag(ed, (100, 100), (100, 130))
    assert ed.measure_tool.measurement.length == pytest.approx(30.0)
    assert not ed.document.shapes


def test_roi_request_takes_precedence(ed):
    ed.set_tool(Tool.MEASURE)
    drag(ed, (100, 100), (130, 140))
    got = []
    ed.roiSelected.connect(lambda *r: got.append(r))
    ed.request_roi()
    assert ed.measure_tool.measurement is None
    drag(ed, (10, 10), (50, 40))
    assert got and got[0][2:] == pytest.approx((40, 30))
    assert ed.measure_tool.measurement is None


def test_measure_outside_work_area_reports_user_coordinates(ed):
    ed.set_tool(Tool.MEASURE)
    drag(ed, (WORK_WIDTH_MM - 10, 0), (WORK_WIDTH_MM + 10, 0))
    m = ed.measure_tool.measurement
    assert m.dx == pytest.approx(-20.0) and m.length == pytest.approx(20.0)


def test_overlay_items_paint(ed, qapp):
    ed.set_tool(Tool.MEASURE)
    drag(ed, (100, 100), (130, 140))
    ed.view.viewport().repaint()
    qapp.processEvents()
    img = ed.view.grab().toImage()
    assert not img.isNull()
    assert isinstance(ed.measure_tool.label, measure_ui.MeasureLabel)


# --- Hauptfenster ---------------------------------------------------------------
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


def test_main_window_m_is_unique_design_menu_and_status_bar(win):
    from PySide6.QtGui import QAction, QKeySequence
    owners = [a for a in win.findChildren(QAction) if a.shortcut() == QKeySequence("M")]
    assert [a.text() for a in owners] == ["Messen"]
    a = win.canvas.actions_by_name["tool_measure"]
    acts = win.main_view.design_menu.actions()
    assert a in acts and acts.index(a) == len(acts) - 1 and acts[-2].isSeparator()
    a.trigger()
    ed = win.canvas
    ed.view.set_zoom(ZOOM)
    drag(ed, (100, 100), (130, 140))
    assert win.statusBar().currentMessage().startswith("Messen: Abstand 50.00 mm")


def test_help_lists_measure_shortcut(win):
    from lumacut_job.help_qt import collect_shortcuts
    rows = {n: k for n, k, _ in collect_shortcuts(win)}
    assert rows["Messen"] == "M"
    assert any(n.startswith("Messen: Abstand kopieren") for n in rows)
