"""Werkzeug „Passmarken“ (LightBurn *Print and Cut*): Design an zwei Marken ausrichten –
Modell (fit_marks / MarkFit), Geometrie aller Formen, Fehler, G-Code, Werkzeug mit
Fang / Vorschau / Undo / Tasten, Zahlen-Dialog, Menüs, Hauptfenster."""

from __future__ import annotations

import math

import pytest
from _pi_guard import pi_check
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QKeyEvent

from lumacut_canvas import icons, marks
from lumacut_canvas.commands import AddShapesCommand
from lumacut_canvas.editor import CanvasEditor
from lumacut_canvas.marks import MarkError, fit_marks
from lumacut_canvas.marks_ui import MarksDialog
from lumacut_canvas.model import Document, Geometry, Layer, Shape, rotate_point
from lumacut_canvas.tools import TOOL_LABELS, TOOL_SHORTCUTS, Tool
from lumacut_canvas.toolpath import parse_gcode
from lumacut_canvas.workarea import screen_to_user
from lumacut_job.planner import optimized_document_gcode

NO = Qt.NoModifier


def world(shape):
    """Stützpunkte inkl. Drehung."""
    g = shape.geom
    cx, cy = g.center()
    return [rotate_point(x, y, cx, cy, g.rot) for x, y in shape.abs_points()]


def close(a, b, tol=1e-6):
    return all(math.dist(p, q) < tol for p, q in zip(a, b)) and len(a) == len(b)


def turned(p, c, deg):
    return rotate_point(p[0], p[1], c[0], c[1], deg)


# ------------------------------------------------------------------ Modell
def test_one_pair_only_moves():
    f = fit_marks([(10, 20)], [(13.5, 18.25)])
    assert f.pairs == 1 and f.angle_deg == 0 and f.scale == 1
    assert f.map_point((10, 20)) == pytest.approx((13.5, 18.25))
    assert f.map_point((50, 60)) == pytest.approx((53.5, 58.25))
    g = f.map_geometry(Geometry(0, 0, 10, 5, 30))
    assert (g.x, g.y, g.w, g.h, g.rot) == pytest.approx((3.5, -1.75, 10, 5, 30))


def test_two_pairs_rigid_rotation_hits_both_marks():
    a1, a2 = (20.0, 30.0), (120.0, 30.0)
    b1 = (25.0, 40.0)
    b2 = turned((125.0, 40.0), b1, 4.0)
    f = fit_marks([a1, a2], [b1, b2])
    assert f.pairs == 2 and f.angle_deg == pytest.approx(4.0) and f.scale == 1.0
    assert f.ratio == pytest.approx(1.0) and f.error_mm == pytest.approx(0.0, abs=1e-9)
    assert f.map_point(a1) == pytest.approx(b1) and f.map_point(a2) == pytest.approx(b2)
    assert not f.is_identity


def test_rigid_with_a_longer_distance_splits_the_error_and_keeps_size():
    f = fit_marks([(0, 0), (100, 0)], [(10, 10), (111, 10)])
    assert f.scale == 1.0 and f.ratio == pytest.approx(1.01) and f.error_mm == pytest.approx(0.5)
    assert f.map_point((0, 0)) == pytest.approx((10.5, 10))       # Mitte auf Mitte
    assert f.map_point((100, 0)) == pytest.approx((110.5, 10))
    g = f.map_geometry(Geometry(10, 10, 30, 20))
    assert (g.w, g.h) == pytest.approx((30, 20))


def test_scale_mode_hits_both_marks_and_scales_uniformly():
    b1, b2 = (10.0, 10.0), turned((112.0, 10.0), (10.0, 10.0), -7.0)
    f = fit_marks([(0, 0), (100, 0)], [b1, b2], scale=True)
    assert f.scale == pytest.approx(1.02) and f.error_mm == 0.0 and f.angle_deg == pytest.approx(-7.0)
    assert f.map_point((0, 0)) == pytest.approx(b1) and f.map_point((100, 0)) == pytest.approx(b2)
    g = f.map_geometry(Geometry(10, 10, 30, 20))
    assert (g.w, g.h) == pytest.approx((30.6, 20.4)) and g.rot == pytest.approx(-7.0)


def test_every_shape_kind_follows_the_points_exactly():
    lid = "L"
    poly = Shape.from_points("polygon", [(10, 10), (60, 12), (40, 50)], lid)
    poly.geom.rot = 20
    path = Shape.from_points("path", [(5, 5), (25, 30), (45, 8)], lid)
    rect = Shape("rect", Geometry(30, 40, 20, 10, 33), lid)
    line = Shape("line", Geometry(5, 5, 20, -10), lid)
    text = Shape("text", Geometry(70, 70, 40, 10, -12), lid, text="Hallo")
    for sc in (False, True):
        b2 = turned((20 + 103.0, 30.0), (20.0, 30.0), 9.0)
        f = fit_marks([(10, 10), (110, 10)], [(20, 30), b2], scale=sc)
        for s in (poly, path):
            t = s.copy()
            t.geom = f.map_geometry(s.geom)
            assert close([f.map_point(p) for p in world(s)], world(t))
        for s in (rect, line, text):
            t = s.copy()
            t.geom = f.map_geometry(s.geom)
            assert close([f.map_point(p) for p in s.geom.corner_points()], t.geom.corner_points())


def test_tabs_and_start_point_follow():
    s = Shape.from_points("polygon", [(10, 10), (50, 10), (50, 40), (10, 40)], "L")
    s.tabs = ((0.5, 0.0),)
    s.start = (1.0, 0.5)
    f = fit_marks([(10, 10), (50, 40)], [(30, 20), turned((70, 50), (30, 20), 12.0)])
    t = s.copy()
    t.geom = f.map_geometry(s.geom)
    assert close([f.map_point(p) for p in s.tab_points()], t.tab_points())
    assert f.map_point(s.start_point()) == pytest.approx(t.start_point())


def test_angle_and_summary_in_display_convention():
    f = fit_marks([(0, 0), (10, 0)], [(0, 0), (0, 10)])          # nach unten = im Uhrzeigersinn
    assert f.angle_deg == pytest.approx(90.0)
    assert "gedreht -90.00°" in marks.summary(f)
    f = fit_marks([(100, 100)], [(90, 105)])                         # 10 mm nach links
    assert marks.summary(f) == "ΔX +10.00 mm, ΔY +5.00 mm"
    s = marks.summary(fit_marks([(0, 0), (100, 0)], [(0, 0), (102, 0)], scale=True))
    assert "Maßstab 102.00 %" in s
    s = marks.summary(fit_marks([(0, 0), (100, 0)], [(0, 0), (102, 0)]))
    assert "Abstand Ist/Soll 102.00 %" in s and "Abweichung je Marke 1.00 mm" in s


@pytest.mark.parametrize("soll, ist, text", [
    ([], [], "mindestens ein"),
    ([(0, 0), (3, 0)], [(0, 0), (3, 0)], "Soll-Punkte liegen zu dicht"),
    ([(0, 0), (30, 0)], [(0, 0), (2, 0)], "Ist-Punkte liegen zu dicht"),
    ([(0, 0), (100, 0)], [(0, 0), (115, 0)], "+15.0 %"),
    ([(0, 0), (100, 0)], [(0, 0), (80, 0)], "-20.0 %"),
    ([(0, float("nan"))], [(0, 0)], "ungültige"),
])
def test_implausible_marks_are_refused(soll, ist, text):
    with pytest.raises(MarkError) as e:
        fit_marks(soll, ist)
    assert text in str(e.value)


def test_identity_and_work_area_helpers():
    f = fit_marks([(0, 0), (50, 0)], [(0, 0), (50, 0)])
    assert f.is_identity
    assert marks.inside_work_area([Geometry(10, 10, 20, 20)])
    assert not marks.inside_work_area([Geometry(350, 10, 20, 20)])
    assert marks.bounds_of([]) is None and marks.inside_work_area([])


def test_gcode_follows_the_moved_design_and_stays_pi_safe():
    doc = Document()
    doc.add_shape(Shape("rect", Geometry(40, 40, 30, 20), doc.active_layer_id))
    before = optimized_document_gcode(doc)
    f = fit_marks([(40, 40), (70, 60)], [(50, 45), turned((80, 65), (50, 45), 5.0)])
    s = doc.shapes[0]
    doc.set_geometry(s.id, f.map_geometry(s.geom))
    after = optimized_document_gcode(doc)
    assert after != before
    tb, ta = parse_gcode(before), parse_gcode(after)
    assert ta.cut_length_mm == pytest.approx(tb.cut_length_mm, abs=0.02)
    pi_check(after)
    # gleiche Kanten, nur bewegt: jeder Schnittpunkt liegt auf einer bewegten Rechteckecke
    corners = [f.map_point(p) for p in Geometry(40, 40, 30, 20).corner_points()]
    xs = sorted(round(c[0], 1) for c in corners)
    cut = [m for m in ta.moves if m.kind == "cut"] or [m for m in ta.moves if m.power > 0]
    assert cut
    ends = {(round(m.x1, 1), round(m.y1, 1)) for m in cut}
    screen_like = {(round(x, 1), round(y, 1)) for x, y in corners}
    from lumacut_canvas.workarea import screen_to_machine
    machine_like = {tuple(round(v, 1) for v in screen_to_machine(x, y)) for x, y in corners}
    assert screen_like <= ends or machine_like <= ends, (sorted(ends), xs)


# ------------------------------------------------------------------ Werkzeug
@pytest.fixture
def ed(qapp):
    e = CanvasEditor()
    e.resize(1000, 700)
    e.show()
    qapp.processEvents()
    e.msgs = []
    e.statusMessage.connect(e.msgs.append)
    yield e
    e.undo_stack.setClean()
    e.close()


def _add(ed, shapes):
    ed.undo_stack.push(AddShapesCommand(ed.document, list(shapes)))
    return list(shapes)


def click(ed, x, y):
    ed.tools.press(QPointF(x, y), NO)
    ed.tools.release(QPointF(x, y), NO)


def key(ed, k):
    return ed.tools.key_press(QKeyEvent(QEvent.KeyPress, k, NO))


def design(ed):
    """Teil mit zwei kleinen Kreis-Marken (Mitten (20, 20) und (120, 80))."""
    lid = ed.document.active_layer_id
    return _add(ed, [Shape("ellipse", Geometry(18, 18, 4, 4), lid),
                     Shape("ellipse", Geometry(118, 78, 4, 4), lid),
                     Shape("rect", Geometry(40, 30, 50, 30), lid)])


def test_tool_action_label_shortcut_icon_strip(ed):
    a = ed.actions_by_name["tool_marks"]
    assert TOOL_LABELS[Tool.MARKS] == "Passmarken" and TOOL_SHORTCUTS[Tool.MARKS] == "Alt+Shift+M"
    assert a.shortcut().toString() == "Alt+Shift+M" and a.isCheckable() and not a.icon().isNull()
    assert "marks" in icons.available()
    strip = ed.tool_strip.actions()
    assert strip[-1] is a and strip.index(a) == strip.index(ed.actions_by_name["tool_trim"]) + 1
    a.trigger()
    assert ed.tools.tool == Tool.MARKS and a.isChecked() and ed.msgs[-1].startswith("Werkzeug: Passmarken")
    assert ed.view.viewport().cursor().shape() == Qt.CrossCursor


def test_four_taps_align_the_selection_in_one_undo_step(ed):
    m1, m2, part = design(ed)
    lid = ed.document.active_layer_id
    (other,) = _add(ed, [Shape("rect", Geometry(200, 200, 10, 10), lid)])
    ids = [m1.id, m2.id, part.id]
    ed.set_selection(ids)
    old = {i: ed.document.shape(i).geom.copy() for i in ids}
    ed.set_tool(Tool.MARKS)
    b1 = (23.37, 25.61)
    b2 = turned((123.37, 85.61), b1, 3.0)
    n0 = ed.undo_stack.count()
    click(ed, 20.4, 19.7)                      # fängt die Kreismitte (20, 20)
    assert ed.marks_tool.points == [pytest.approx((20, 20))]
    assert "Ist 1" in ed.msgs[-1]
    click(ed, *b1)                             # Ist: genau, kein 1-mm-Raster
    assert ed.marks_tool.points[1] == pytest.approx(b1)
    click(ed, 119.6, 80.3)
    click(ed, *b2)
    assert ed.undo_stack.count() == n0 + 1 and ed.undo_stack.undoText() == "Passmarken ausrichten"
    assert ed.marks_tool.points == [] and not ed.marks_tool.item.isVisible()
    f = fit_marks([(20, 20), (120, 80)], [b1, b2])
    assert ed.document.shape(m1.id).geom.center() == pytest.approx(b1, abs=1e-6)
    assert ed.document.shape(m2.id).geom.center() == pytest.approx(b2, abs=1e-6)
    g = ed.document.shape(part.id).geom
    assert close(g.corner_points(), [f.map_point(p) for p in old[part.id].corner_points()])
    assert ed.document.shape(other.id).geom.as_tuple() == (200, 200, 10, 10)
    assert "3 Objekt(e) ausgerichtet" in ed.msgs[-1] and "gedreht -3.00°" in ed.msgs[-1]
    assert "Strg+Z" in ed.msgs[-1]
    ed.undo_stack.undo()
    for i in ids:
        assert ed.document.shape(i).geom.as_tuple() == pytest.approx(old[i].as_tuple())
        assert ed.document.shape(i).geom.rot == old[i].rot


def test_without_selection_all_editable_objects_move_and_get_selected(ed):
    m1, m2, part = design(ed)
    lid = ed.document.add_layer(Layer(name="Gesperrt")).id
    (stay,) = _add(ed, [Shape("rect", Geometry(250, 250, 10, 10), lid)])
    ed.document.update_layer(lid, locked=True)
    ed.set_selection([])
    ed.set_tool(Tool.MARKS)
    click(ed, 20, 20)
    assert "alle 3 Objekt(e)" in ed.msgs[-1]
    click(ed, 25, 22)
    assert key(ed, Qt.Key_Return)              # Eingabe nach dem ersten Paar: nur verschieben
    assert ed.document.shape(part.id).geom.as_tuple() == pytest.approx((45, 32, 50, 30))
    assert sorted(ed.selection) == sorted([m1.id, m2.id, part.id])
    assert "ΔX -5.00 mm, ΔY +2.00 mm" in ed.msgs[-2] or "ΔX -5.00 mm, ΔY +2.00 mm" in ed.msgs[-1]
    assert ed.document.shape(stay.id).geom.as_tuple() == (250, 250, 10, 10)


def test_backspace_escape_and_selection_kept(ed):
    m1, m2, part = design(ed)
    ed.set_selection([part.id])
    ed.set_tool(Tool.MARKS)
    click(ed, 20, 20)
    click(ed, 30, 30)
    assert key(ed, Qt.Key_Backspace) and len(ed.marks_tool.points) == 1
    assert "Ist 1" in ed.msgs[-1]
    assert key(ed, Qt.Key_Escape) and ed.marks_tool.points == [] and ed.msgs[-1] == "Passmarken gelöscht"
    assert ed.selection == [part.id]           # erst die Punkte, die Auswahl bleibt
    assert not key(ed, Qt.Key_Return)          # ohne Punkte nichts
    key(ed, Qt.Key_Escape)
    assert ed.selection == []


def test_wrong_fourth_point_is_refused_and_can_be_set_again(ed):
    m1, m2, part = design(ed)
    ed.set_selection([part.id])
    ed.set_tool(Tool.MARKS)
    n0 = ed.undo_stack.count()
    for p in ((20, 20), (21, 21), (120, 80)):
        click(ed, *p)
    click(ed, 160.0, 120.0)                    # Abstand viel zu groß
    assert ed.undo_stack.count() == n0 and len(ed.marks_tool.points) == 3
    assert "weicht um" in ed.msgs[-1]
    click(ed, 121, 81)
    assert ed.undo_stack.count() == n0 + 1
    assert ed.document.shape(part.id).geom.as_tuple() == pytest.approx((41, 31, 50, 30))


def test_overlay_shows_points_arrows_and_ghost(ed):
    m1, m2, part = design(ed)
    ed.set_selection([part.id])
    ed.set_tool(Tool.MARKS)
    item = ed.marks_tool.item
    ed.tools.move(QPointF(50, 50), NO, False)          # ohne Punkt: nichts
    assert not item.isVisible()
    click(ed, 20, 20)
    ed.tools.move(QPointF(30, 25), NO, False)
    assert item.isVisible() and item.points == [pytest.approx((20, 20))]
    assert item.hover == pytest.approx((30, 25))
    assert len(item.ghost) == 1 and item.ghost[0][0] == pytest.approx((50, 35))
    ed.set_touch_mode(True, persist=False)
    try:
        item.update()
        ed.view.viewport().repaint()               # malt Punkte / Pfeile / Umriss ohne Fehler
    finally:
        ed.set_touch_mode(False, persist=False)
    click(ed, 30, 25)
    click(ed, 120, 80)
    ed.tools.move(QPointF(5, 5), NO, False)            # zu dicht: kein Umriss, Punkte bleiben
    assert item.ghost == [] and len(item.points) == 3


def test_drag_sets_the_point_on_release_and_abort_keeps_points(ed):
    design(ed)
    ed.set_tool(Tool.MARKS)
    click(ed, 20, 20)
    ed.tools.press(QPointF(40, 40), NO)
    ed.tools.move(QPointF(41, 42), NO, True)
    assert ed.marks_tool.item.hover == pytest.approx((41, 42))
    ed.tools.release(QPointF(42.25, 43.5), NO)
    assert ed.marks_tool.points[1] == pytest.approx((42.25, 43.5))
    ed.tools.press(QPointF(60, 60), NO)
    ed.tools.abort_drag()                      # zweiter Finger: Zug weg, Punkte bleiben
    assert len(ed.marks_tool.points) == 2
    ed.set_tool(Tool.SELECT)                   # Werkzeugwechsel löscht
    assert ed.marks_tool.points == [] and not ed.marks_tool.item.isVisible()


def test_soll_snaps_only_with_object_snap_and_never_to_the_grid(ed):
    design(ed)
    ed.set_tool(Tool.MARKS)
    ed.object_snap.set_enabled(False, persist=False)
    try:
        click(ed, 20.4, 19.7)
        assert ed.marks_tool.points[0] == pytest.approx((20.4, 19.7))
    finally:
        ed.object_snap.set_enabled(True, persist=False)


def test_locked_and_empty_documents(ed):
    ed.set_tool(Tool.MARKS)
    click(ed, 20, 20)
    click(ed, 30, 30)
    key(ed, Qt.Key_Return)
    assert "keine bewegbaren Objekte" in ed.msgs[-1]
    m1, m2, part = design(ed)
    ed.marks_tool.clear()
    click(ed, 20, 20)
    click(ed, 20, 20)
    key(ed, Qt.Key_Return)
    assert "nichts bewegt" in ed.msgs[-1]


def test_outside_work_area_is_refused_not_clamped(ed):
    lid = ed.document.active_layer_id
    (part,) = _add(ed, [Shape("rect", Geometry(300, 10, 40, 20), lid)])
    ed.set_selection([part.id])
    ed.set_tool(Tool.MARKS)
    n0 = ed.undo_stack.count()
    click(ed, 300, 10)
    click(ed, 330, 10)                         # rechte Kante bei 370 > 360 mm
    key(ed, Qt.Key_Return)
    assert ed.undo_stack.count() == n0 and "außerhalb der Arbeitsfläche" in ed.msgs[-1]
    assert ed.document.shape(part.id).geom.as_tuple() == (300, 10, 40, 20)
    assert len(ed.marks_tool.points) == 2      # Punkte bleiben zum Korrigieren
    key(ed, Qt.Key_Backspace)
    click(ed, 315, 10)
    key(ed, Qt.Key_Return)
    assert ed.document.shape(part.id).geom.as_tuple() == pytest.approx((315, 10, 40, 20))


def test_scale_action_and_context_menu(ed):
    m1, m2, part = design(ed)
    ed.set_selection([part.id])
    ed.set_tool(Tool.MARKS)
    menu = ed.build_context_menu(QPointF(200, 200))
    texts = [a.text() for a in menu.actions()]
    assert "Passmarken als Zahlen …" in texts and "Passmarken: Maßstab angleichen" in texts
    assert "Passmarken löschen" not in texts
    ed.actions_by_name["marks_scale"].trigger()
    assert ed.marks_tool.scale and "Maßstab angleichen an" in ed.msgs[-1]
    click(ed, 20, 20)
    menu = ed.build_context_menu(QPointF(200, 200))
    assert "Passmarken löschen" in [a.text() for a in menu.actions()]
    ed.actions_by_name["marks_clear"].trigger()
    assert ed.marks_tool.points == []
    for p in ((20, 20), (20, 20), (120, 80), (122, 80)):    # 102 % → skaliert
        click(ed, *p)
    f = fit_marks([(20, 20), (120, 80)], [(20, 20), (122, 80)], scale=True)
    g = ed.document.shape(part.id).geom
    assert f.scale > 1.01 and g.w == pytest.approx(50 * f.scale)
    assert f"Maßstab {f.scale * 100:.2f} %" in ed.msgs[-1]
    ed.marks_tool.set_scale(False)
    assert not ed.actions_by_name["marks_scale"].isChecked()


def test_arrange_menu_entries(ed):
    texts = [a.text() for a in ed.arrange_button.menu().actions() if a.text()]
    assert texts[:2] == ["Passmarken", "Passmarken als Zahlen …"]
    assert texts[-1] == "Verschachteln …"
    _add(ed, [Shape("rect", Geometry(10, 10, 20, 10), ed.document.active_layer_id)])
    menu = ed.build_context_menu(QPointF(20, 15))
    sub = next(a.menu() for a in menu.actions() if a.menu() is not None
               and a.menu().objectName() == "ArrangeMenu")
    sub.actions()[[a.text() for a in sub.actions()].index("Passmarken")].trigger()
    assert ed.tools.tool == Tool.MARKS


def test_numeric_dialog_prefill_info_and_apply(ed):
    m1, m2, part = design(ed)
    ed.set_selection([part.id])
    ed.set_tool(Tool.MARKS)
    click(ed, 20, 20)
    click(ed, 22, 21)
    dlg = MarksDialog(ed.marks_tool, ed)
    u, v = screen_to_user(20, 20)
    assert (dlg.spins[0][0].value(), dlg.spins[0][1].value()) == pytest.approx((u, v))
    assert (dlg.spins[1][0].value(), dlg.spins[1][1].value()) == pytest.approx(screen_to_user(22, 21))
    assert not dlg.second.isChecked() and not dlg.spins[2][0].isEnabled()
    assert dlg.info.text() == "ΔX -2.00 mm, ΔY +1.00 mm"
    dlg.second.setChecked(True)
    dlg.set_point(2, *screen_to_user(120, 80))
    dlg.set_point(3, *screen_to_user(120, 80))             # zu dicht an Ist 1? nein: 99 mm
    dlg.set_point(1, *screen_to_user(20, 20))
    assert dlg.buttons.button(dlg.buttons.StandardButton.Ok).isEnabled()
    dlg.set_point(3, *screen_to_user(20, 22))              # Ist-Abstand 2 mm
    assert "zu dicht" in dlg.info.text()
    assert not dlg.buttons.button(dlg.buttons.StandardButton.Ok).isEnabled()
    b2 = turned((122.0, 80.0), (22.0, 20.0), 2.0)
    dlg.set_point(1, *screen_to_user(22, 20))
    dlg.set_point(3, *screen_to_user(*b2))
    assert "gedreht -2.00°" in dlg.info.text()
    n0 = ed.undo_stack.count()
    assert dlg.apply()
    assert ed.undo_stack.count() == n0 + 1 and ed.marks_tool.points == []
    f = fit_marks([(20, 20), (120, 80)], [(22, 20), (round(b2[0], 2), round(b2[1], 2))])
    g = ed.document.shape(part.id).geom
    assert close(g.corner_points(), [f.map_point(p) for p in Geometry(40, 30, 50, 30).corner_points()],
                 tol=1e-6)


def test_numeric_dialog_without_points_uses_the_selection_box(ed):
    m1, m2, part = design(ed)
    ed.set_selection([part.id])
    dlg = MarksDialog(ed.marks_tool, ed)
    assert dlg.second.isChecked()
    assert (dlg.spins[0][0].value(), dlg.spins[0][1].value()) == pytest.approx(screen_to_user(40, 30))
    assert (dlg.spins[3][0].value(), dlg.spins[3][1].value()) == pytest.approx(screen_to_user(90, 60))
    assert "gedreht +0.00°" in dlg.info.text() or "ΔX +0.00 mm" in dlg.info.text()
    assert not dlg.apply()                                   # Soll = Ist: nichts bewegt
    assert "nichts bewegt" in ed.msgs[-1]


def test_hint_when_the_pi_places_the_job_at_the_head(ed):
    from lumacut_job.park_routine import JobStart, set_active_start
    m1, m2, part = design(ed)
    ed.set_selection([part.id])
    ed.set_tool(Tool.MARKS)
    click(ed, 20, 20)
    click(ed, 22, 20)
    key(ed, Qt.Key_Return)
    assert "Hinweis" not in ed.msgs[-1]                     # absolut: kein Hinweis
    set_active_start(JobStart(origin="current", target=(100.0, 100.0)))
    click(ed, 22, 20)
    click(ed, 24, 20)
    key(ed, Qt.Key_Return)
    assert "Startposition am Pi ist „Kopfposition“" in ed.msgs[-1] and "„Absolut“" in ed.msgs[-1]
    assert ed.document.shape(part.id).geom.x == pytest.approx(44)


def test_save_load_and_no_new_project_key(ed, tmp_path):
    from lumacut_canvas.document_io import load_document, save_document
    m1, m2, part = design(ed)
    ed.set_selection([part.id])
    ed.set_tool(Tool.MARKS)
    for p in ((20, 20), (25, 20), (120, 80), turned((125, 80), (25, 20), 1.0)):
        click(ed, *p)
    p = tmp_path / "m.lcs"
    save_document(ed.document, p)
    again = load_document(p)
    a, b = again.shape(part.id).geom, ed.document.shape(part.id).geom
    assert a.as_tuple() == pytest.approx(b.as_tuple()) and a.rot == pytest.approx(b.rot)
    import json
    plain = Document()
    plain.add_shape(Shape("rect", Geometry(40, 30, 50, 30, 10), plain.active_layer_id))
    q = tmp_path / "plain.lcs"
    save_document(plain, q)

    def keys(node, out=None):
        out = set() if out is None else out
        if isinstance(node, dict):
            for k, v in node.items():
                out.add(k)
                keys(v, out)
        elif isinstance(node, list):
            for v in node:
                keys(v, out)
        return out
    assert keys(json.loads(p.read_text(encoding="utf-8"))) == keys(json.loads(q.read_text(encoding="utf-8")))


def test_main_window_shortcut_unique(qapp, tmp_path):
    from PySide6.QtCore import QSettings
    from PySide6.QtGui import QAction, QKeySequence
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(tmp_path))
    QSettings.setDefaultFormat(QSettings.IniFormat)
    main = pytest.importorskip("main")
    w = main.LumaCutStudio()
    try:
        owners = [a for a in w.findChildren(QAction) if a.shortcut() == QKeySequence("Alt+Shift+M")]
        assert [a.text() for a in owners] == ["Passmarken"]
    finally:
        w.canvas.undo_stack.setClean()
        w.close()
