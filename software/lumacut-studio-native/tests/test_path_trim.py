"""Überstände abschneiden (Trim an Kreuzungen): Modell, Dialog, Editor, G-Code."""

from __future__ import annotations

import pytest
from _pi_guard import pi_check

from lumacut_canvas import pathjoin, pathtrim
from lumacut_canvas.commands import AddShapesCommand
from lumacut_canvas.editor import CanvasEditor
from lumacut_canvas.model import Document, Geometry, Shape
from lumacut_job.planner import optimized_document_gcode


@pytest.fixture
def doc(qapp):
    return Document()


def seg(doc, a, b):
    return Shape.from_points("path", [a, b], doc.active_layer_id)


def hash_lines(doc, over=2.0):
    """Zwei waagerechte und zwei senkrechte Linien (#) mit ``over`` mm Überstand."""
    return [seg(doc, (20 - over, 20), (40 + over, 20)), seg(doc, (20 - over, 40), (40 + over, 40)),
            seg(doc, (20, 20 - over), (20, 40 + over)), seg(doc, (40, 20 - over), (40, 40 + over))]


def ends(shape):
    pts = shape.abs_points()
    return pts[0], pts[-1]


def test_hash_overshoots_are_cut_to_the_crossings(doc):
    shapes = hash_lines(doc)
    res = pathtrim.trim_stubs(shapes, 3.0)
    assert res.changed and res.stubs == 8 and res.length_mm == pytest.approx(16.0)
    assert sorted(res.remove) == sorted(s.id for s in shapes)
    got = sorted((tuple(round(c, 6) for c in x), tuple(round(c, 6) for c in y))
                 for x, y in (sorted(ends(s)) for s in res.add))
    assert got == [((20, 20), (20, 40)), ((20, 20), (40, 20)), ((20, 40), (40, 40)), ((40, 20), (40, 40))]
    assert "8 Überstand" in res.summary() and "16.0 mm" in res.summary()
    for s in res.add:
        assert s.kind == "path" and s.layer_id == shapes[0].layer_id
        a, b = ends(s)
        assert abs(a[0] - b[0]) == pytest.approx(20) or abs(a[1] - b[1]) == pytest.approx(20)


def test_stub_longer_than_limit_stays(doc):
    shapes = hash_lines(doc, over=5.0)
    res = pathtrim.trim_stubs(shapes, 3.0)
    assert not res.changed and res.stubs == 0 and "keine Überstände" in res.summary()
    res = pathtrim.trim_stubs(shapes, 5.0)
    assert res.stubs == 8


def test_corner_and_t_junction_ends_are_never_stubs(doc):
    ell = [seg(doc, (0, 0), (30, 0)), seg(doc, (0, 0), (0, 30))]      # Ecke
    tee = [seg(doc, (50, 0), (80, 0)), seg(doc, (65, 0), (65, 25))]    # T-Stoß
    assert not pathtrim.trim_stubs(ell + tee, 5.0).changed


def test_equal_arms_of_a_cross_are_not_guessed(doc):
    cross = [seg(doc, (0, 10), (20, 10)), seg(doc, (10, 0), (10, 20))]
    assert not pathtrim.trim_stubs(cross, 20.0).changed


def test_one_overshooting_line_only_that_one_changes(doc):
    a = seg(doc, (0, 10), (32, 10))       # 2 mm über die senkrechte Linie bei x = 30
    b = seg(doc, (30, 0), (30, 25))       # Enden 10 / 15 mm von der Kreuzung: bleiben
    res = pathtrim.trim_stubs([a, b], 3.0)
    assert res.remove == [a.id] and res.stubs == 1
    (new,) = res.add
    assert ends(new)[1] == pytest.approx((30, 10)) and ends(new)[0] == pytest.approx((0, 10))


def test_closed_shape_outline_trims_a_line_through_it(doc):
    rect = Shape("rect", Geometry(10, 10, 20, 20), doc.active_layer_id)
    line = seg(doc, (8, 20), (32, 20))     # ragt 2 mm links und rechts aus dem Rechteck
    res = pathtrim.trim_stubs([rect, line], 3.0)
    assert res.remove == [line.id] and res.stubs == 2
    a, b = ends(res.add[0])
    assert a == pytest.approx((10, 20)) and b == pytest.approx((30, 20))


def test_open_shape_unchanged_when_nothing_to_trim_and_closed_never_changed(doc):
    rect = Shape("rect", Geometry(10, 10, 20, 20), doc.active_layer_id)
    far = seg(doc, (100, 100), (120, 100))
    res = pathtrim.trim_stubs([rect, far])
    assert not res.changed and res.open_found == 1 and res.add == []


def test_attributes_kept_and_multi_piece_path(doc):
    lines = hash_lines(doc)
    lines[0].groups = ("g1",)
    lines[0].priority = 3
    lines[0].reverse = True
    res = pathtrim.trim_stubs(lines, 3.0)
    new = next(s for s, old in zip(res.add, res.remove) if old == lines[0].id)
    assert new.groups == ("g1",) and new.priority == 3 and new.reverse is True


def test_rotated_line_uses_world_coordinates(doc):
    a = Shape("line", Geometry(0, 10, 32, 0), doc.active_layer_id)
    a.geom.rot = 0.0
    b = seg(doc, (30, 0), (30, 25))
    res = pathtrim.trim_stubs([a, b], 3.0)
    assert res.remove == [a.id]


def test_generated_and_range_clamping(doc):
    shapes = hash_lines(doc)
    shapes[0].generator = {"type": "x"}
    res = pathtrim.trim_stubs(shapes, 1000)       # auf 50 mm begrenzt
    assert shapes[0].id not in res.remove and res.changed
    assert pathtrim.trim_stubs(shapes, -5).stubs == 0       # auf 0,1 mm begrenzt


def test_trim_then_join_makes_a_closed_square(doc):
    over = 1.5
    sq = [seg(doc, (-over, 0), (20 + over, 0)), seg(doc, (20, -over), (20, 20 + over)),
          seg(doc, (20 + over, 20), (-over, 20)), seg(doc, (0, 20 + over), (0, -over))]
    assert not pathjoin.auto_join(sq).closed
    res = pathtrim.trim_stubs(sq, 3.0)
    assert res.stubs == 8
    joined = pathjoin.auto_join(res.add)
    assert joined.closed == 1 and joined.add[0].kind == "polygon"


def burn_mm(gcode):
    """Summe der G1-Strecken (mm) eines einfachen absoluten G-Codes."""
    import math
    x = y = 0.0
    total = 0.0
    for ln in gcode.splitlines():
        t = ln.split()
        if not t or t[0] not in ("G0", "G1"):
            continue
        nx = next((float(w[1:]) for w in t if w[0] == "X"), x)
        ny = next((float(w[1:]) for w in t if w[0] == "Y"), y)
        if t[0] == "G1":
            total += math.hypot(nx - x, ny - y)
        x, y = nx, ny
    return total


def test_job_gcode_shorter_and_pi_safe(doc):
    shapes = hash_lines(doc)
    res = pathtrim.trim_stubs(shapes, 3.0)
    for s in shapes:
        doc.add_shape(s) if hasattr(doc, "add_shape") else doc.shapes.append(s)
    before = optimized_document_gcode(doc)
    for s in shapes:
        doc.remove_shape(s.id) if hasattr(doc, "remove_shape") else doc.shapes.remove(s)
    for s in res.add:
        doc.add_shape(s) if hasattr(doc, "add_shape") else doc.shapes.append(s)
    after = optimized_document_gcode(doc)
    assert before != after
    assert burn_mm(after) == pytest.approx(burn_mm(before) - 16.0)
    pi_check(after)


# ------------------------------------------------------------------ Dialog / Editor
def _ed(qapp):
    return CanvasEditor(Document())


@pytest.fixture
def ed(qapp):
    e = _ed(qapp)
    yield e
    e.undo_stack.setClean()
    e.close()


def _add(ed, shapes):
    ed.undo_stack.push(AddShapesCommand(ed.document, list(shapes)))
    return [s.id for s in shapes]


def test_dialog_readout_and_ok_state(qapp, doc):
    from PySide6.QtWidgets import QDialogButtonBox
    from lumacut_canvas.pathjoin_ui import TrimDialog
    dlg = TrimDialog(hash_lines(doc, over=5.0))
    ok = dlg.buttons.button(QDialogButtonBox.Ok)
    assert dlg.max_mm.value() == 3.0 and not ok.isEnabled()
    assert "keine Überstände" in dlg.readout.text()
    dlg.max_mm.setValue(6.0)
    assert ok.isEnabled() and "8 Überstand" in dlg.readout.text()
    assert dlg.values() == {"max_mm": 6.0}


def test_editor_trim_selection_undo_and_notify(ed):
    shapes = hash_lines(ed.document)
    rect = Shape("rect", Geometry(70, 10, 10, 10), ed.document.active_layer_id)
    ids = _add(ed, shapes + [rect])
    seen = []
    ed.path_ops.cleanup.ask_trim = lambda sh: seen.append(len(sh)) or {"max_mm": 3.0}
    msgs = []
    ed.statusMessage.connect(msgs.append)
    ed.set_selection(ids[:4])
    ed.actions_by_name["path_trim"].trigger()
    assert seen == [4]
    kinds = [s.kind for s in ed.document.shapes]
    assert kinds.count("path") == 4 and ed.document.shapes[-1].id == rect.id
    assert all(s.id not in ids[:4] for s in ed.document.shapes if s.kind == "path")
    assert msgs[-1].startswith("Überstände abschneiden: 8 Überstand")
    assert ed.undo_stack.undoText() == "Überstände abschneiden"
    assert len(ed.selection) == 4
    ed.undo_stack.undo()
    assert [s.id for s in ed.document.shapes] == ids
    assert ed.actions_by_name["path_trim"].shortcut().toString() == "Alt+Shift+O"


def test_editor_trim_cancel_nothing_and_locked(ed):
    ids = _add(ed, hash_lines(ed.document))
    ed.path_ops.cleanup.ask_trim = lambda sh: None
    ed.set_selection(ids)
    ed.actions_by_name["path_trim"].trigger()
    assert [s.id for s in ed.document.shapes] == ids
    msgs = []
    ed.statusMessage.connect(msgs.append)
    ed.document.update_layer(ed.document.active_layer_id, locked=True)
    ed.path_ops.cleanup.ask_trim = lambda sh: pytest.fail("kein Dialog erwartet")
    ed.actions_by_name["path_trim"].trigger()
    assert "keine offenen Pfade" in msgs[-1]


def test_trim_in_path_menu_and_context_menu(ed):
    from PySide6.QtCore import QPointF
    _add(ed, [Shape("rect", Geometry(10, 10, 20, 10), ed.document.active_layer_id)])
    assert "Überstände abschneiden …" in [a.text() for a in ed.path_ops_button.menu().actions() if a.text()]
    menu = ed.build_context_menu(QPointF(20, 15))
    sub = next(a.menu() for a in menu.actions() if a.menu() is not None
               and a.menu().objectName() == "PathOpsMenu")
    assert "Überstände abschneiden …" in [a.text() for a in sub.actions()]


def test_main_window_shortcut_unique(qapp, tmp_path):
    from PySide6.QtCore import QSettings
    from PySide6.QtGui import QAction, QKeySequence
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(tmp_path))
    QSettings.setDefaultFormat(QSettings.IniFormat)
    main = pytest.importorskip("main")
    w = main.LumaCutStudio()
    try:
        owners = [a for a in w.findChildren(QAction) if a.shortcut() == QKeySequence("Alt+Shift+O")]
        assert [a.text() for a in owners] == ["Überstände abschneiden …"]
    finally:
        w.canvas.undo_stack.setClean()
        w.close()
