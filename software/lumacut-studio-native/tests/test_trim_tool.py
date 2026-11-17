"""Werkzeug „Trimmen“ (LightBurn *Trim Shapes* per Klick): Stück zwischen Kreuzungen
entfernen – Modell (TrimIndex), offene / geschlossene / gedrehte Formen, Attribute,
G-Code, Werkzeug mit Vorschau, Undo, gesperrte Ebenen, Touch, Menüs, Hauptfenster."""

from __future__ import annotations

import pytest
from _pi_guard import pi_check
from PySide6.QtCore import QPointF, Qt

from lumacut_canvas import icons, pathtrim
from lumacut_canvas.commands import AddShapesCommand
from lumacut_canvas.editor import CanvasEditor
from lumacut_canvas.model import Document, Geometry, Shape
from lumacut_canvas.tools import TOOL_LABELS, TOOL_SHORTCUTS, Tool
from lumacut_canvas.toolpath import parse_gcode
from lumacut_job.planner import optimized_document_gcode

NO = Qt.NoModifier


@pytest.fixture
def doc(qapp):
    return Document()


def seg(lid, a, b):
    return Shape.from_points("path", [a, b], lid)


def grid(lid):
    """# aus zwei waagerechten und zwei senkrechten 40-mm-Linien (Kreuzungen bei 20 / 40)."""
    return [seg(lid, (10, 20), (50, 20)), seg(lid, (10, 40), (50, 40)),
            seg(lid, (20, 10), (20, 50)), seg(lid, (40, 10), (40, 50))]


def pieces(shape):
    pts = shape.abs_points()
    return [[tuple(round(c, 6) for c in p) for p in pts[a:b]] for a, b in shape.ring_ranges()]


def length(pts):
    import math
    return sum(math.dist(a, b) for a, b in zip(pts, pts[1:]))


# ------------------------------------------------------------------ Modell
def test_inner_piece_between_two_crossings_is_removed(doc):
    g = grid(doc.active_layer_id)
    pick = pathtrim.TrimIndex(g).pick((30, 20), 0.5)
    assert pick.ok and pick.shape is g[0] and pick.length_mm == pytest.approx(20.0)
    assert pick.removed == [(20.0, 20.0), (40.0, 20.0)]
    assert pick.remove == [g[0].id]
    (new,) = pick.add
    assert new.kind == "path" and new.layer_id == g[0].layer_id
    assert pieces(new) == [[(10, 20), (20, 20)], [(40, 20), (50, 20)]]


def test_end_piece_up_to_the_first_crossing(doc):
    g = grid(doc.active_layer_id)
    pick = pathtrim.TrimIndex(g).pick((14, 20.3), 0.5)
    assert pick.ok and pick.length_mm == pytest.approx(10.0)
    assert pieces(pick.add[0]) == [[(20, 20), (50, 20)]]


def test_last_piece_removes_the_shape(doc):
    lid = doc.active_layer_id
    a, b = seg(lid, (0, 10), (30, 10)), seg(lid, (10, 0), (10, 30))
    idx = pathtrim.TrimIndex([a, b])
    pick = idx.pick((20, 10), 0.5)
    assert pick.ok and pieces(pick.add[0]) == [[(0, 10), (10, 10)]]
    # Linie ohne Kreuzung innen: nichts zu trimmen, das ganze Objekt löscht Entf
    lone = seg(lid, (100, 100), (120, 100))
    pick = pathtrim.TrimIndex([lone, a]).pick((110, 100), 0.5)
    assert not pick.ok and "kreuzt keine andere Form" in pick.reason and pick.add == []
    # nur noch ein Stück zwischen zwei Kreuzungen und dem Ende -> Stück fällt, Rest bleibt
    c = seg(lid, (10, 10), (20, 10))
    pick = pathtrim.TrimIndex([c, seg(lid, (15, 0), (15, 20))]).pick((12, 10), 0.5)
    assert pick.ok and pieces(pick.add[0]) == [[(15, 10), (20, 10)]]


def test_whole_open_shape_gone_when_nothing_is_left(doc):
    lid = doc.active_layer_id
    # Linie, deren beide Enden auf Kreuzungen liegen, plus eine innere Kreuzung
    line = seg(lid, (0, 0), (20, 0))
    cut = seg(lid, (10, -5), (10, 5))
    pick = pathtrim.TrimIndex([line, cut]).pick((5, 0), 0.5)
    assert pick.ok and pieces(pick.add[0]) == [[(10, 0), (20, 0)]]
    (rest,) = pick.add
    pick2 = pathtrim.TrimIndex([rest, cut]).pick((15, 0), 0.5)
    assert not pick2.ok          # das Reststück kreuzt nichts mehr innen


def test_rectangle_piece_turns_into_an_open_path(doc):
    lid = doc.active_layer_id
    rect = Shape("rect", Geometry(0, 0, 30, 30), lid)
    line = seg(lid, (-5, 10), (40, 10))
    rect.groups, rect.priority, rect.reverse = ("g",), 2, True
    pick = pathtrim.TrimIndex([rect, line]).pick((15, 0.2), 0.5)
    assert pick.ok and pick.length_mm == pytest.approx(50.0)
    (new,) = pick.add
    assert new.kind == "path" and new.groups == ("g",) and new.priority == 2 and new.reverse is True
    assert length(new.abs_points()) == pytest.approx(70.0)
    (p,) = pieces(new)
    assert p[0] == (30, 10) and p[-1] == (0, 10)
    # das untere Stück (wickelt über den Ringstart)
    pick = pathtrim.TrimIndex([rect, line]).pick((15, 30), 0.5)
    assert pick.ok and pick.length_mm == pytest.approx(70.0)
    assert length(pick.add[0].abs_points()) == pytest.approx(50.0)


def test_ellipse_arc_and_closed_shape_needing_two_crossings(doc):
    lid = doc.active_layer_id
    e = Shape("ellipse", Geometry(0, 0, 30, 30), lid)
    line = seg(lid, (-5, 10), (40, 10))
    pick = pathtrim.TrimIndex([e, line]).pick((15, 0), 0.5)
    import math
    assert pick.ok and pick.length_mm == pytest.approx(2 * 15 * math.acos(5 / 15), abs=0.05)
    assert [s.kind for s in pick.add] == ["path"]
    pick = pathtrim.TrimIndex([e]).pick((15, 0), 0.5)
    assert not pick.ok and "zweimal" in pick.reason


def test_polygon_hole_stays_closed_polygon(doc):
    lid = doc.active_layer_id
    pg = Shape.from_points("polygon", [(0, 0), (30, 0), (30, 30), (0, 30),
                                       (10, 10), (20, 10), (20, 20), (10, 20)], lid, rings=[4])
    pick = pathtrim.TrimIndex([pg, seg(lid, (-5, 5), (40, 5))]).pick((15, 0), 0.5)
    assert pick.ok and pick.length_mm == pytest.approx(40.0)
    poly, path = pick.add
    assert poly.kind == "polygon" and pieces(poly) == [[(10, 10), (20, 10), (20, 20), (10, 20)]]
    assert path.kind == "path" and length(path.abs_points()) == pytest.approx(80.0)


def test_other_ring_of_the_same_shape_cuts(doc):
    lid = doc.active_layer_id
    two = Shape.from_points("path", [(0, 10), (30, 10), (15, 0), (15, 20)], lid, rings=[2])
    pick = pathtrim.TrimIndex([two]).pick((25, 10), 0.5)
    assert pick.ok and pieces(pick.add[0]) == [[(0, 10), (15, 10)], [(15, 0), (15, 20)]]


def test_rotated_rectangle_in_world_coordinates(doc):
    lid = doc.active_layer_id
    rr = Shape("rect", Geometry(0, 0, 30, 30, 45), lid)
    pick = pathtrim.TrimIndex([rr, seg(lid, (-10, 15), (40, 15))]).pick((15, 15 - 21.2132), 0.5)
    assert pick.ok and pick.length_mm == pytest.approx(60.0, abs=0.01)


def test_text_images_generated_and_locked_are_cutters_only(doc):
    lid = doc.active_layer_id
    text = Shape("text", Geometry(0, 0, 40, 10), lid, text="I")
    gen = seg(lid, (0, 50), (40, 50))
    gen.generator = {"type": "qr"}
    line = seg(lid, (-5, 50), (45, 50))
    assert not pathtrim.can_trim(text) and not pathtrim.can_trim(gen) and pathtrim.can_trim(line)
    idx = pathtrim.TrimIndex([text, gen])
    assert idx.pick((20, 50), 0.5) is None
    lock = seg(lid, (0, 80), (40, 80))
    cross = seg(lid, (20, 70), (20, 90))
    idx = pathtrim.TrimIndex([lock, cross], editable=[cross.id])
    pick = idx.pick((10, 80), 0.5)
    assert pick is None or pick.shape is cross
    pick = idx.pick((20, 75), 0.5)
    assert pick.ok and pick.shape is cross            # die gesperrte Linie schneidet trotzdem


def test_nearest_and_topmost_shape_wins(doc):
    lid = doc.active_layer_id
    low = seg(lid, (0, 10), (40, 10))
    top = seg(lid, (0, 10), (40, 10))
    cross = seg(lid, (20, 0), (20, 20))
    pick = pathtrim.TrimIndex([low, top, cross]).pick((10, 10), 0.5)
    assert pick.shape is top
    pick = pathtrim.TrimIndex([low, cross]).pick((20.3, 15), 0.5)
    assert pick.shape is cross


def test_collinear_overlap_piece_can_be_trimmed(doc):
    lid = doc.active_layer_id
    a = seg(lid, (0, 0), (40, 0))
    b = seg(lid, (20, 0), (60, 0))              # überlappt a von 20 bis 40
    pick = pathtrim.TrimIndex([a, b]).pick((30, 0), 0.1)
    assert pick.ok and pick.length_mm == pytest.approx(20.0)
    assert pick.shape is b and pieces(pick.add[0]) == [[(40, 0), (60, 0)]]   # obere Form, Doppel weg


def test_gcode_shorter_by_the_piece_and_pi_safe(doc):
    g = grid(doc.active_layer_id)
    for s in g:
        doc.add_shape(s)
    before = optimized_document_gcode(doc)
    pick = pathtrim.TrimIndex(doc.shapes).pick((30, 20), 0.5)
    doc.remove_shape(pick.remove[0])
    for s in pick.add:
        doc.add_shape(s)
    after = optimized_document_gcode(doc)
    assert parse_gcode(after).cut_length_mm == pytest.approx(parse_gcode(before).cut_length_mm - 20.0, abs=0.01)
    pi_check(after)


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


def test_tool_action_label_shortcut_icon_strip(ed):
    a = ed.actions_by_name["tool_trim"]
    assert TOOL_LABELS[Tool.TRIM] == "Trimmen" and TOOL_SHORTCUTS[Tool.TRIM] == "Alt+Shift+X"
    assert a.shortcut().toString() == "Alt+Shift+X" and a.isCheckable() and not a.icon().isNull()
    assert "trim" in icons.available()
    strip = ed.tool_strip.actions()
    assert strip.index(a) == strip.index(ed.actions_by_name["tool_measure"]) + 1
    a.trigger()
    assert ed.tools.tool == Tool.TRIM and a.isChecked() and ed.msgs[-1].startswith("Werkzeug: Trimmen")
    assert ed.view.viewport().cursor().shape() == Qt.CrossCursor


def test_hover_preview_and_tap_trims_with_one_undo_step(ed):
    g = _add(ed, grid(ed.document.active_layer_id))
    ids = [s.id for s in ed.document.shapes]
    ed.set_tool(Tool.TRIM)
    item = ed.trim_tool.item
    ed.tools.move(QPointF(30, 20.2), NO, False)
    assert item.isVisible() and item.ok and item.piece == [(20.0, 20.0), (40.0, 20.0)]
    ed.tools.move(QPointF(150, 150), NO, False)
    assert not item.isVisible()
    item.show_piece([(0, 0), (1, 1)], False)
    item.update()
    n0 = ed.undo_stack.count()
    click(ed, 30, 20.2)
    assert ed.undo_stack.count() == n0 + 1 and ed.undo_stack.undoText() == "Trimmen"
    assert not ed.document.has_shape(g[0].id) and len(ed.document.shapes) == 4
    new = ed.document.shapes[0]                       # an der Stelle des Originals im Stapel
    assert pieces(new) == [[(10, 20), (20, 20)], [(40, 20), (50, 20)]]
    assert "20.0 mm entfernt" in ed.msgs[-1]
    click(ed, 20.2, 30)                               # zweites Stück: eigener Undo-Schritt
    assert ed.undo_stack.count() == n0 + 2
    ed.undo_stack.undo()
    ed.undo_stack.undo()
    assert [s.id for s in ed.document.shapes] == ids


def test_closed_rect_tap_and_selection_follows(ed):
    lid = ed.document.active_layer_id
    rect, line = _add(ed, [Shape("rect", Geometry(50, 50, 30, 30), lid), seg(lid, (45, 60), (90, 60))])
    ed.set_selection([rect.id])
    ed.set_tool(Tool.TRIM)
    click(ed, 65, 50)
    assert not ed.document.has_shape(rect.id) and ed.document.shapes[0].kind == "path"
    assert ed.selection == [ed.document.shapes[0].id]
    assert "jetzt offener Pfad" in ed.msgs[-1]


def test_nothing_no_crossing_locked_and_drag(ed):
    lid = ed.document.active_layer_id
    ed.set_tool(Tool.TRIM)
    click(ed, 100, 100)
    assert "keine Linie" in ed.msgs[-1]
    (lone,) = _add(ed, [seg(lid, (100, 100), (140, 100))])
    n0 = ed.undo_stack.count()
    click(ed, 120, 100)
    assert "kreuzt keine andere Form" in ed.msgs[-1] and ed.undo_stack.count() == n0
    _add(ed, [seg(lid, (120, 90), (120, 110))])
    ed.tools.press(QPointF(110, 105), NO)            # Ziehen ist kein Tippen (kreuzt nichts)
    ed.tools.move(QPointF(130, 130), NO, True)
    ed.tools.release(QPointF(130, 130), NO)
    assert ed.document.has_shape(lone.id)
    ed.document.update_layer(lid, locked=True)
    n0 = ed.undo_stack.count()
    click(ed, 110, 100)
    assert "gesperrt" in ed.msgs[-1] and ed.undo_stack.count() == n0 and ed.document.has_shape(lone.id)


def test_cancel_and_hidden_layer(ed):
    lid = ed.document.active_layer_id
    _add(ed, grid(lid))
    ed.set_tool(Tool.TRIM)
    ed.tools.move(QPointF(30, 20), NO, False)
    assert ed.trim_tool.item.isVisible()
    ed.tools.cancel()
    assert not ed.trim_tool.item.isVisible()
    ed.tools.press(QPointF(30, 20), NO)
    ed.tools.abort_drag()
    ed.tools.release(QPointF(30, 20), NO)
    assert len(ed.document.shapes) == 4 and all(len(s.points) == 2 for s in ed.document.shapes)
    ed.document.update_layer(lid, visible=False)
    click(ed, 30, 20)
    assert all(len(s.points) == 2 for s in ed.document.shapes)


def test_touch_mode_reaches_further(ed):
    lid = ed.document.active_layer_id
    _add(ed, grid(lid))
    mouse = ed.trim_tool.tolerance_mm()
    ed.set_touch_mode(True, persist=False)
    try:
        assert ed.trim_tool.tolerance_mm() > mouse
        ed.set_tool(Tool.TRIM)
        off = 0.7 * ed.trim_tool.tolerance_mm()
        click(ed, 30, 20 + off)
        assert len(ed.document.shapes[0].ring_ranges()) == 2
    finally:
        ed.set_touch_mode(False, persist=False)


def test_tool_in_path_menu_and_context_menu(ed):
    _add(ed, [Shape("rect", Geometry(10, 10, 20, 10), ed.document.active_layer_id)])
    texts = [a.text() for a in ed.path_ops_button.menu().actions() if a.text()]
    assert texts.index("Trimmen") == texts.index("Offene Formen auswählen") + 1
    menu = ed.build_context_menu(QPointF(20, 15))
    sub = next(a.menu() for a in menu.actions() if a.menu() is not None
               and a.menu().objectName() == "PathOpsMenu")
    sub.actions()[[a.text() for a in sub.actions()].index("Trimmen")].trigger()
    assert ed.tools.tool == Tool.TRIM


def test_save_load_and_no_new_project_key(ed, tmp_path):
    from lumacut_canvas.document_io import load_document, save_document
    lid = ed.document.active_layer_id
    _add(ed, grid(lid))
    ed.set_tool(Tool.TRIM)
    click(ed, 30, 20)
    p = tmp_path / "t.lcs"
    save_document(ed.document, p)
    again = load_document(p)
    assert [pieces(s) for s in again.shapes] == [pieces(s) for s in ed.document.shapes]
    assert '"trim' not in p.read_text(encoding="utf-8")


def test_main_window_shortcut_unique(qapp, tmp_path):
    from PySide6.QtCore import QSettings
    from PySide6.QtGui import QAction, QKeySequence
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(tmp_path))
    QSettings.setDefaultFormat(QSettings.IniFormat)
    main = pytest.importorskip("main")
    w = main.LumaCutStudio()
    try:
        owners = [a for a in w.findChildren(QAction) if a.shortcut() == QKeySequence("Alt+Shift+X")]
        assert [a.text() for a in owners] == ["Trimmen"]
    finally:
        w.canvas.undo_stack.setClean()
        w.close()
