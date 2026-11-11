"""Optimierungseinstellungen / Schnittreihenfolge (wie LightBurn „Optimization Settings“).

Engine (corners, best direction, direction order, off = drawing order), the
project setting ``Document.cut_order`` (model, file, copies), the planner /
G-code / estimate path, dialog, undo and the main-window action.
"""

import math
import re

import pytest
from _pi_guard import pi_check
from PySide6.QtWidgets import QDialogButtonBox

from lumacut_canvas.commands import AddShapesCommand
from lumacut_canvas.export import JobLayer, job_layers
from lumacut_canvas.gcode import layers_to_gcode
from lumacut_canvas.model import CUT_ORDER_DIRECTIONS, CutOrder, Document, Geometry, Layer, Shape
from lumacut_canvas.workarea import to_machine
from lumacut_job.optimize_qt import (DIRECTION_LABELS, OptimizeDialog, SetCutOrderCommand,
                                     apply_cut_order, order_hint, summary)
from lumacut_job.planner import (CORNER_MIN_TURN_DEG, DIRECTIONS, corner_indices,
                                 optimize_layers, optimized_document_gcode, order_polylines,
                                 travel_length)


def square(x, y, s):
    return [(x, y), (x + s, y), (x + s, y + s), (x, y + s), (x, y)]


def square_mid(x, y, s):
    """Square with a collinear node in the middle of every side."""
    h = s / 2
    return [(x, y), (x + h, y), (x + s, y), (x + s, y + h), (x + s, y + s), (x + h, y + s),
            (x, y + s), (x, y + h), (x, y)]


def circle(cx, cy, r, n=72):
    pts = [(cx + r * math.cos(2 * math.pi * i / n), cy + r * math.sin(2 * math.pi * i / n))
           for i in range(n)]
    return pts + [pts[0]]


def polygon(cx, cy, r, n):
    pts = [(cx + r * math.cos(2 * math.pi * i / n), cy + r * math.sin(2 * math.pi * i / n))
           for i in range(n)]
    return pts + [pts[0]]


def idx_of(ordered, poly):
    return next(i for i, q in enumerate(ordered) if set(q) == set(poly))


def g0_points(gcode):
    out = []
    for line in gcode.splitlines():
        if line.startswith("G0"):
            x = re.search(r"X(-?[\d.]+)", line)
            y = re.search(r"Y(-?[\d.]+)", line)
            if x and y:
                out.append((float(x.group(1)), float(y.group(1))))
    return out


@pytest.fixture
def editor(qapp):
    from lumacut_canvas.editor import CanvasEditor
    ed = CanvasEditor()
    yield ed
    ed.undo_stack.setClean()
    ed.close()
    ed.deleteLater()
    qapp.processEvents()


# --- Ecken ------------------------------------------------------------------

def test_corner_indices_square_circle_and_polygons():
    assert corner_indices(square(0, 0, 10)[:-1]) == [0, 1, 2, 3]
    # collinear side nodes are no corners
    assert corner_indices(square_mid(0, 0, 10)[:-1]) == [0, 2, 4, 6]
    assert corner_indices(circle(0, 0, 10)[:-1]) == []
    assert len(corner_indices(polygon(0, 0, 10, 6)[:-1])) == 6      # 60° turns
    assert corner_indices(polygon(0, 0, 10, 12)[:-1]) == []         # 30° < 40°
    assert len(corner_indices(polygon(0, 0, 10, 12)[:-1], 25.0)) == 12
    assert CORNER_MIN_TURN_DEG == 40.0


def test_corner_indices_skip_duplicate_points_and_tiny_rings():
    ring = [(0, 0), (0, 0), (10, 0), (10, 10), (10, 10), (0, 10)]
    assert corner_indices(ring) == [0, 1, 2, 3, 4, 5]   # duplicates sit on the corners
    ring = [(0, 0), (5, 0), (5, 0), (10, 0), (10, 10), (0, 10)]
    assert 1 not in corner_indices(ring) and 2 not in corner_indices(ring)
    assert corner_indices([(0, 0), (1, 0)]) == []
    assert corner_indices([(1, 1)] * 4) == []


def test_corners_move_the_start_to_the_nearest_corner():
    sq = square_mid(100, 100, 20)
    start = (110, 90)                     # right above the top side's middle node
    (plain,) = order_polylines([sq], start)
    assert plain[0] == (110, 100)
    (corner,) = order_polylines([sq], start, corners=True)
    assert corner[0] in ((100, 100), (120, 100))
    assert corner[0] == corner[-1] and len(corner) == len(sq)
    assert set(corner) == set(sq)


def test_corners_fall_back_to_nearest_point_without_corners():
    c = circle(150, 150, 10)
    a = order_polylines([c], (150, 130))
    b = order_polylines([c], (150, 130), corners=True)
    assert a == b


def test_corners_need_best_start_and_leave_open_paths_alone():
    sq = square_mid(100, 100, 20)
    (no_best,) = order_polylines([sq], (110, 90), best_start=False, corners=True)
    assert no_best == sq
    line = [(100, 50), (40, 50)]
    (out,) = order_polylines([line], (30, 50), corners=True)
    assert out == [(40, 50), (100, 50)]


def test_corners_with_kerf_offset_start_at_a_corner():
    jl = JobLayer("l", "L", 50, 600, 1, [square_mid(100, 100, 20)], kerf_mm=0.1,
                  cut_order=CutOrder(corners=True))
    (o,) = optimize_layers([jl], (110, 90))
    first = o.polylines[0][0]
    assert first == pytest.approx((99.9, 99.9)) or first == pytest.approx((120.1, 99.9))


def test_corners_with_tabs_and_lead_in_stay_valid():
    jl = JobLayer("l", "L", 50, 600, 1, [square_mid(100, 100, 20)], tab_count=2,
                  lead_in_mm=2.0, cut_order=CutOrder(corners=True))
    (o,) = optimize_layers([jl], (110, 90))
    assert o.poly_kinds[0] == "lead_in"
    pi_check(layers_to_gcode([o]))


# --- Richtung offener Pfade ---------------------------------------------------

def test_best_direction_off_keeps_open_paths_as_drawn():
    line = [(100, 50), (40, 50)]
    (rev,) = order_polylines([line], (30, 50))
    assert rev[0] == (40, 50)
    (kept,) = order_polylines([line], (30, 50), best_direction=False)
    assert kept == line


def test_best_direction_off_still_orders_by_nearest_start():
    near = [(50, 50), (60, 50)]
    far = [(200, 50), (45, 60)]   # far start, near end
    out = order_polylines([far, near], (40, 50), best_direction=False)
    assert out[0] == near and out[1] == far


# --- In Richtung schneiden ----------------------------------------------------

def grid(cols=3, rows=3, size=10, gap=10, x0=50, y0=50):
    return [square(x0 + c * (size + gap), y0 + r * (size + gap), size)
            for r in range(rows) for c in range(cols)]


@pytest.mark.parametrize("direction,key,reverse", [
    ("top_bottom", lambda p: min(y for _, y in p), False),
    ("bottom_top", lambda p: max(y for _, y in p), True),
    ("left_right", lambda p: max(x for x, _ in p), True),   # machine X grows to the left
    ("right_left", lambda p: min(x for x, _ in p), False),
])
def test_direction_order_cuts_row_by_row(direction, key, reverse):
    polys = grid()
    out = order_polylines(polys, (300, 300), direction=direction)
    keys = [key(p) for p in out]
    assert keys == sorted(keys, reverse=reverse)
    assert len(out) == 9 and all(len(p) == 5 for p in out)


def test_direction_order_snakes_inside_a_row_with_reduce_travel():
    polys = grid()
    out = order_polylines(polys, (300, 45), direction="top_bottom")
    xs = [min(x for x, _ in p) for p in out]
    # first row from the head's side (right in machine X), then the next row nearest first
    assert xs[:3] == [90, 70, 50]
    assert xs[3] == 50


def test_direction_order_without_reduce_travel_sorts_by_front_edge():
    polys = grid()
    out = order_polylines(polys, (300, 45), direction="top_bottom", reduce_travel=False)
    rows = [min(y for _, y in p) for p in out]
    assert rows == sorted(rows)


def test_direction_row_takes_shorter_shapes_of_the_same_line():
    tall = square(100, 100, 10)                                 # y 100..110
    short = [(130, 104), (136, 104), (136, 110), (130, 110), (130, 104)]   # same text line
    below = square(115, 113, 10)                                # next line, y 113..123
    out = order_polylines([below, short, tall], (140, 100), direction="top_bottom")
    assert idx_of(out, below) == 2


def test_direction_order_keeps_inner_shapes_first():
    frame = square(40, 40, 100)
    hole = square(60, 120, 10)          # near the bottom of the frame
    top_part = square(200, 40, 10)
    out = order_polylines([frame, hole, top_part], (30, 30), direction="top_bottom")
    assert idx_of(out, hole) < idx_of(out, frame)
    out = order_polylines([frame, hole, top_part], (30, 30), direction="top_bottom",
                          inside_first=False)
    assert idx_of(out, frame) < idx_of(out, hole)


def test_unknown_direction_is_ignored():
    polys = grid()
    assert (order_polylines(polys, (300, 300), direction="diagonal")
            == order_polylines(polys, (300, 300)))
    assert set(DIRECTIONS) == set(CUT_ORDER_DIRECTIONS) - {""}


def test_all_off_keeps_drawing_order_start_and_direction():
    polys = [square_mid(300, 50, 5), [(100, 50), (40, 50)], square(40, 50, 5)]
    opts = CutOrder(enabled=False).planner_options()
    assert order_polylines(polys, (30, 30), **opts) == polys


# --- CutOrder (Modell) ----------------------------------------------------------

def test_cut_order_defaults_and_dict():
    d = CutOrder()
    assert d.is_default and d.to_dict() == {}
    assert (d.enabled, d.inside_first, d.reduce_travel, d.best_start, d.corners,
            d.best_direction, d.direction) == (True, True, True, True, False, True, "")
    c = CutOrder(corners=True, direction="left_right", inside_first=False)
    assert c.to_dict() == {"inside_first": False, "corners": True, "direction": "left_right"}
    assert CutOrder.from_dict(c.to_dict()) == c
    assert not c.is_default


def test_cut_order_from_dict_cleans_bad_values():
    assert CutOrder.from_dict(None) == CutOrder()
    assert CutOrder.from_dict("x") == CutOrder()
    c = CutOrder.from_dict({"direction": "diagonal", "corners": 1, "enabled": 0, "foo": 3})
    assert c.direction == "" and c.corners is True and c.enabled is False


def test_planner_options():
    assert CutOrder().planner_options() == {
        "inside_first": True, "reduce_travel": True, "best_start": True, "corners": False,
        "best_direction": True, "direction": ""}
    off = CutOrder(enabled=False, corners=True, direction="top_bottom").planner_options()
    assert not any(v for v in off.values())
    assert CutOrder(best_start=False, corners=True).planner_options()["corners"] is False
    assert CutOrder(corners=True).planner_options()["corners"] is True


def test_document_file_round_trip_and_old_files(tmp_path):
    from lumacut_canvas.document_io import load_document, save_document
    doc = Document()
    assert "cut_order" not in doc.to_dict()        # old files stay byte-identical
    doc.set_cut_order(CutOrder(direction="top_bottom", corners=True))
    data = doc.to_dict()
    assert data["cut_order"] == {"corners": True, "direction": "top_bottom"}
    path = save_document(doc, tmp_path / "p.lcproj")
    back = load_document(path)
    assert back.cut_order == doc.cut_order
    # loading a file without the key resets to the default
    back.load_dict(Document().to_dict())
    assert back.cut_order == CutOrder()


def test_set_cut_order_notifies_only_on_change():
    doc = Document()
    calls = []
    doc.add_listener(lambda: calls.append(1))
    doc.set_cut_order(CutOrder())
    assert calls == []
    doc.set_cut_order(CutOrder(reduce_travel=False))
    assert calls == [1]


def test_new_document_in_editor_resets(editor):
    editor.document.set_cut_order(CutOrder(enabled=False))
    fresh = Document()
    editor.document.load_dict(fresh.to_dict())
    assert editor.document.cut_order == CutOrder()


def test_copies_keep_cut_order(qapp):
    from lumacut_job import vartext as vt
    from lumacut_job.selection import selection_document
    doc = Document()
    lid = doc.active_layer_id
    rect = doc.add_shape(Shape("rect", Geometry(10, 10, 20, 20), lid))
    text = Shape("text", Geometry(50, 50, 14, 4), lid, text="Nr. {n:3}")
    text.generator = vt.make_meta(vt.VarTextSpec(series="A", current=7))
    doc.add_shape(text)
    doc.set_cut_order(CutOrder(direction="bottom_top"))
    assert selection_document(doc, [rect.id]).cut_order == doc.cut_order
    out, usage = vt.evaluate_document(doc, lambda *a: 0.5 * max(1, len(a[0])))
    assert out is not doc and usage
    assert out.cut_order == doc.cut_order


# --- Planer / G-Code ------------------------------------------------------------

def two_squares_doc(far_first=True):
    doc = Document()
    lid = doc.active_layer_id
    # Machine origin top right: the planner starts at machine (30, 30) = screen top right.
    a = Shape("rect", Geometry(10, 300, 20, 20), lid)    # far from the start (bottom left)
    b = Shape("rect", Geometry(320, 5, 20, 20), lid)     # next to the start
    for s in ((a, b) if far_first else (b, a)):
        doc.add_shape(s)
    return doc


def test_job_layers_carry_cut_order_and_optimize_uses_it(qapp):
    doc = two_squares_doc()
    (jl,) = job_layers(doc)
    assert jl.cut_order == CutOrder()
    doc.set_cut_order(CutOrder(enabled=False))
    (jl,) = job_layers(doc)
    assert jl.cut_order == CutOrder(enabled=False)
    (o,) = optimize_layers([jl])
    assert o.polylines == jl.polylines
    # keywords override the layer's settings
    (o2,) = optimize_layers([jl], reduce_travel=True)
    assert o2.polylines != jl.polylines


def test_default_cut_order_output_unchanged(qapp):
    doc = two_squares_doc()
    layers = job_layers(doc)
    legacy = [JobLayer(**{**l.__dict__, "cut_order": None}) for l in layers]
    assert layers_to_gcode(optimize_layers(layers)) == layers_to_gcode(optimize_layers(legacy))
    assert optimized_document_gcode(doc) == layers_to_gcode(optimize_layers(legacy))


def test_disabled_cuts_in_drawing_order_and_travels_more(qapp):
    doc = two_squares_doc(far_first=True)
    opt = optimized_document_gcode(doc)
    doc.set_cut_order(CutOrder(enabled=False))
    raw = optimized_document_gcode(doc)
    pi_check(raw)
    far = to_machine(10, 300)
    near = to_machine(340, 5)
    first_raw = g0_points(raw)[0]
    first_opt = g0_points(opt)[0]
    assert math.dist(first_raw, far) < 30 and math.dist(first_opt, near) < 30

    def travel(g):
        pts = [(30.0, 30.0)] + g0_points(g)
        return sum(math.dist(a, b) for a, b in zip(pts, pts[1:]))
    assert travel(raw) > travel(opt)


def test_disabled_keeps_fill_blocks_in_object_order(qapp):
    doc = Document()
    lay = doc.active_layer
    doc.update_layer(lay.id, fill_mode="hatch", hatch_outline=False)
    doc.add_shape(Shape("rect", Geometry(300, 280, 20, 20), lay.id))
    doc.add_shape(Shape("rect", Geometry(20, 20, 20, 20), lay.id))
    (jl,) = job_layers(doc)
    (opt,) = optimize_layers([jl])
    doc.set_cut_order(CutOrder(enabled=False))
    (jl2,) = job_layers(doc)
    (raw,) = optimize_layers([jl2])
    assert raw.fills == jl2.fills
    assert opt.fills[0] != jl.fills[0]


def test_direction_order_through_the_document(qapp):
    doc = Document()
    lid = doc.active_layer_id
    for y in (200, 20, 110):
        for x in (20, 150, 280):
            doc.add_shape(Shape("rect", Geometry(x, y, 20, 20), lid))
    doc.set_cut_order(CutOrder(direction="top_bottom"))
    g = optimized_document_gcode(doc)
    pi_check(g)
    ys = [y for _, y in g0_points(g)][:9]
    assert ys == sorted(ys)
    doc.set_cut_order(CutOrder(direction="bottom_top"))
    ys = [y for _, y in g0_points(optimized_document_gcode(doc))][:9]
    assert ys == sorted(ys, reverse=True)


def test_estimate_follows_the_setting(qapp):
    from lumacut_job.estimate import estimate_gcode
    doc = two_squares_doc(far_first=True)
    doc.add_shape(Shape("rect", Geometry(25, 250, 20, 20), doc.active_layer_id))
    doc.add_shape(Shape("rect", Geometry(300, 20, 20, 20), doc.active_layer_id))
    opt = estimate_gcode(optimized_document_gcode(doc), park=False)
    doc.set_cut_order(CutOrder(enabled=False))
    raw = estimate_gcode(optimized_document_gcode(doc), park=False)
    assert raw.travel_length_mm > opt.travel_length_mm
    assert raw.cut_length_mm == pytest.approx(opt.cut_length_mm, rel=1e-6)


def test_corners_through_the_document_start_on_a_corner(qapp):
    doc = Document()
    lid = doc.active_layer_id
    doc.add_shape(Shape("polygon", Geometry(100, 100, 40, 40), lid,
                        points=[(0, 0), (0.5, 0), (1, 0), (1, 1), (0, 1)]))
    doc.set_cut_order(CutOrder(corners=True))
    (o,) = optimize_layers(job_layers(doc))
    ring = o.polylines[0][:-1]
    assert 0 in corner_indices(ring)


# --- Dialog / Undo ---------------------------------------------------------------

def test_dialog_values_enabled_states_and_reset(qapp):
    dlg = OptimizeDialog(CutOrder())
    assert dlg.value() == CutOrder()
    assert [dlg.direction.itemText(i) for i in range(dlg.direction.count())] == [
        DIRECTION_LABELS[k] for k in CUT_ORDER_DIRECTIONS]
    assert dlg.direction.currentText() == "aus"
    assert dlg.corners.isEnabled()          # best start on -> corners selectable
    dlg.best_start.setChecked(False)
    assert not dlg.corners.isEnabled()
    dlg.best_start.setChecked(True)
    dlg.reduce_travel.setChecked(False)
    assert not dlg.best_start.isEnabled() and not dlg.best_direction.isEnabled()
    assert "Zeichenreihenfolge" in dlg.hint.text()
    dlg.direction.setCurrentIndex(dlg.direction.findData("left_right"))
    assert dlg.best_start.isEnabled()
    dlg.enabled.setChecked(False)
    for w in (dlg.inside_first, dlg.reduce_travel, dlg.best_start, dlg.corners,
              dlg.best_direction, dlg.direction):
        assert not w.isEnabled()
    assert dlg.hint.text().startswith("Achtung")
    dlg.findChild(QDialogButtonBox).button(QDialogButtonBox.RestoreDefaults).click()
    assert dlg.value() == CutOrder()
    assert dlg.hint.text() == ""
    dlg.deleteLater()


def test_dialog_loads_and_returns_settings(qapp):
    order = CutOrder(inside_first=False, corners=True, best_direction=False,
                     direction="right_left")
    dlg = OptimizeDialog(order)
    assert dlg.value() == order
    assert dlg.direction.currentText() == "von rechts nach links"
    assert "Innere Formen zuerst" in dlg.hint.text()
    dlg.deleteLater()


def test_hint_and_summary_texts():
    assert order_hint(CutOrder()) == ""
    assert summary(CutOrder()) == "Standard"
    assert summary(CutOrder(enabled=False)) == "Optimierung aus (Zeichenreihenfolge)"
    assert summary(CutOrder(corners=True, direction="top_bottom")) == (
        "in Richtung von oben nach unten, Start an Ecken")
    assert summary(CutOrder(inside_first=False, reduce_travel=False)) == (
        "innere Formen nicht zuerst, Leerfahrten nicht verkürzt")
    assert summary(CutOrder(best_start=False, best_direction=False)) == (
        "Startpunkt wie gezeichnet, Richtung wie gezeichnet")


def test_apply_is_one_undo_step(editor):
    doc = editor.document
    n = editor.undo_stack.count()
    new = CutOrder(direction="top_bottom")
    assert apply_cut_order(editor, new)
    assert editor.undo_stack.count() == n + 1 and doc.cut_order == new
    assert not apply_cut_order(editor, new)
    assert editor.undo_stack.count() == n + 1
    editor.undo_stack.undo()
    assert doc.cut_order == CutOrder()
    editor.undo_stack.redo()
    assert doc.cut_order == new
    assert SetCutOrderCommand(doc, CutOrder()).text() == "Optimierungseinstellungen"


def test_main_window_action_changes_gcode_and_status(qapp):
    from main import LumaCutStudio
    win = LumaCutStudio()
    try:
        tools = win.job_tools
        a = tools.optimize_action
        assert a.text() == "Optimierung…" and a.shortcut().toString() == "Alt+Shift+K"
        assert a.objectName() == "optimize_settings_action"
        ed = win.canvas
        doc = ed.document
        lid = doc.active_layer.id
        ed.undo_stack.push(AddShapesCommand(doc, [Shape("rect", Geometry(10, 300, 20, 20), lid),
                                                  Shape("rect", Geometry(320, 5, 20, 20), lid)],
                                            "Rechtecke"))
        before = tools.job_gcode(ask_inputs=False)[0]
        assert tools.optimize_settings(CutOrder(enabled=False))
        assert "Optimierung aus" in win.statusBar().currentMessage()
        after = tools.job_gcode(ask_inputs=False)[0]
        assert after != before
        pi_check(after)
        assert not tools.optimize_settings(CutOrder(enabled=False))
        assert win.statusBar().currentMessage() == "Optimierung unverändert"
        ed.undo_stack.undo()
        assert doc.cut_order == CutOrder()
        assert tools.job_gcode(ask_inputs=False)[0] == before
    finally:
        win.canvas.undo_stack.setClean()
        win.close()
        win.deleteLater()
        qapp.processEvents()
