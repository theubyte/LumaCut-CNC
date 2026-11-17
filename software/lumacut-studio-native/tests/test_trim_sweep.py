"""Trimmen durch Ziehen über mehrere Stücke (LightBurn *Trim Shapes* mit gedrückter Taste):
Modell (TrimIndex.sweep), mehrere Formen / mehrere Stücke einer Form, zusammenhängende
Stücke, geschlossene Formen ganz weg, Stapelreihenfolge, G-Code, Werkzeug mit Vorschau,
ein Undo-Schritt, Auswahl, gesperrte Ebenen, Abbruch, Touch, Tippen unverändert."""

from __future__ import annotations

import pytest
from _pi_guard import pi_check
from PySide6.QtCore import QPointF, Qt

from lumacut_canvas import pathtrim
from lumacut_canvas.commands import AddShapesCommand
from lumacut_canvas.editor import CanvasEditor
from lumacut_canvas.model import Document, Geometry, Shape
from lumacut_canvas.tools import Tool
from lumacut_canvas.toolpath import parse_gcode
from lumacut_job.planner import optimized_document_gcode

NO = Qt.NoModifier


@pytest.fixture
def doc(qapp):
    return Document()


def seg(lid, *pts):
    return Shape.from_points("path", list(pts), lid)


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


def apply(doc, sw):
    for sid, add in sw.replace:
        at = [s.id for s in doc.shapes].index(sid)
        doc.remove_shape(sid)
        for k, s in enumerate(add):
            doc.add_shape(s, at + k)


# ------------------------------------------------------------------ Modell
def test_sweep_across_two_lines_removes_both_inner_pieces(doc):
    g = grid(doc.active_layer_id)
    sw = pathtrim.TrimIndex(g).sweep((30, 5), (30, 55))
    assert sw.ok and sw.skipped == 0 and len(sw.pieces) == 2
    assert sw.length_mm == pytest.approx(40.0)
    assert sorted(sw.pieces) == [[(20.0, 20.0), (40.0, 20.0)], [(20.0, 40.0), (40.0, 40.0)]]
    assert [sid for sid, _ in sw.replace] == [g[0].id, g[1].id]       # Stapelreihenfolge
    (a,), (b,) = (add for _, add in sw.replace)
    assert pieces(a) == [[(10, 20), (20, 20)], [(40, 20), (50, 20)]]
    assert pieces(b) == [[(10, 40), (20, 40)], [(40, 40), (50, 40)]]
    assert a.kind == "path" and a.layer_id == g[0].layer_id


def test_sweep_same_result_as_two_taps(doc):
    g = grid(doc.active_layer_id)
    sw = pathtrim.TrimIndex(g).sweep((30, 5), (30, 55))
    for sid, add in sw.replace:
        tap = pathtrim.TrimIndex(g).pick((30, 20 if sid == g[0].id else 40), 0.5)
        assert [pieces(s) for s in tap.add] == [pieces(s) for s in add]


def test_two_pieces_of_one_open_path(doc):
    lid = doc.active_layer_id
    u = seg(lid, (0, 0), (40, 0), (40, 10), (0, 10))          # offenes „U“ (90 mm)
    cut = seg(lid, (20, -5), (20, 15))
    sw = pathtrim.TrimIndex([u, cut], [u.id]).sweep((10, -5), (10, 15))
    assert len(sw.pieces) == 2 and sw.length_mm == pytest.approx(40.0)
    ((sid, (new,)),) = sw.replace
    assert sid == u.id and pieces(new) == [[(20, 0), (40, 0), (40, 10), (20, 10)]]


def test_neighbour_pieces_of_a_ring_merge_into_one(doc):
    lid = doc.active_layer_id
    rect = Shape("rect", Geometry(0, 0, 40, 20), lid)
    cuts = [seg(lid, (10, -5), (10, 25)), seg(lid, (30, -5), (30, 25))]
    sw = pathtrim.TrimIndex([rect, *cuts], [rect.id]).sweep((20, -5), (45, 10))
    # unteres Mittelstück (20 mm) + rechtes „U“ (40 mm) hängen zusammen -> ein Linienzug
    assert len(sw.pieces) == 1 and sw.length_mm == pytest.approx(60.0)
    ((_sid, (new,)),) = sw.replace
    assert new.kind == "path" and len(new.ring_ranges()) == 1
    assert length(pieces(new)[0]) == pytest.approx(60.0)
    # linkes „U“ (über den Ringstart) + unteres Mittelstück: auch über den Start ein Stück
    sw = pathtrim.TrimIndex([rect, *cuts], [rect.id]).sweep((-5, 10), (20, -5))
    assert len(sw.pieces) == 1 and sw.length_mm == pytest.approx(60.0)
    ((_sid, (new,)),) = sw.replace
    assert len(new.ring_ranges()) == 1 and length(pieces(new)[0]) == pytest.approx(60.0)


def test_whole_closed_shape_gone_when_every_piece_is_crossed(doc):
    lid = doc.active_layer_id
    rect = Shape("rect", Geometry(0, 0, 40, 20), lid)
    bar = seg(lid, (20, -10), (20, 30))
    sw = pathtrim.TrimIndex([rect, bar]).sweep((-5, 10), (45, 10))
    rep = dict(sw.replace)
    assert rep[rect.id] == []                                   # beide Hälften gekreuzt
    assert pieces(rep[bar.id][0]) == [[(20, -10), (20, 0)], [(20, 20), (20, 30)]]
    assert sw.length_mm == pytest.approx(120.0 + 20.0)


def test_polygon_hole_crossed_alone_stays_polygon_outer(doc):
    lid = doc.active_layer_id
    poly = Shape.from_points("polygon", [(0, 0), (40, 0), (40, 40), (0, 40),
                                         (10, 10), (30, 10), (30, 30), (10, 30)], lid, rings=[4])
    bar = seg(lid, (20, 5), (20, 35))
    sw = pathtrim.TrimIndex([poly, bar], [poly.id]).sweep((15, 15), (15, 35))
    ((_sid, add),) = sw.replace
    kinds = sorted(s.kind for s in add)
    assert kinds == ["path", "polygon"]                         # Außenring bleibt geschlossen
    hole_rest = next(s for s in add if s.kind == "path")
    assert length(pieces(hole_rest)[0]) == pytest.approx(40.0)    # rechte Lochhälfte bleibt
    assert sw.length_mm == pytest.approx(40.0)


def test_nothing_crossed_untrimmable_and_cutters_only(doc):
    lid = doc.active_layer_id
    g = grid(lid)
    idx = pathtrim.TrimIndex(g)
    assert not idx.sweep((100, 100), (120, 120)).ok
    assert not idx.sweep((30, 30), (30, 30)).ok                 # Länge null
    lone = seg(lid, (100, 100), (140, 100))
    sw = pathtrim.TrimIndex([lone]).sweep((120, 90), (120, 110))
    assert not sw.ok and sw.skipped == 1 and sw.replace == []
    # nicht editierbare Formen (gesperrt / Text / erzeugt) werden nur geschnitten
    sw = pathtrim.TrimIndex(g, [g[0].id]).sweep((30, 5), (30, 55))
    assert [sid for sid, _ in sw.replace] == [g[0].id]
    text = Shape("text", Geometry(60, 0, 30, 10), lid, text="AB")
    sw = pathtrim.TrimIndex([text]).sweep((55, 5), (95, 5))
    assert not sw.ok


def test_fence_along_a_line_takes_the_overlapped_piece(doc):
    g = grid(doc.active_layer_id)
    sw = pathtrim.TrimIndex(g).sweep((25, 20), (35, 20))       # entlang der Linie
    ((sid, (new,)),) = sw.replace
    assert sid == g[0].id and pieces(new) == [[(10, 20), (20, 20)], [(40, 20), (50, 20)]]


def test_gcode_shorter_by_all_pieces_and_pi_safe(doc):
    for s in grid(doc.active_layer_id):
        doc.add_shape(s)
    before = optimized_document_gcode(doc)
    apply(doc, pathtrim.TrimIndex(doc.shapes).sweep((30, 5), (30, 55)))
    after = optimized_document_gcode(doc)
    assert parse_gcode(after).cut_length_mm == pytest.approx(parse_gcode(before).cut_length_mm - 40.0, abs=0.01)
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


def drag(ed, a, b, release=True):
    ed.tools.press(QPointF(*a), NO)
    ed.tools.move(QPointF((a[0] + b[0]) / 2, (a[1] + b[1]) / 2), NO, True)
    ed.tools.move(QPointF(*b), NO, True)
    if release:
        ed.tools.release(QPointF(*b), NO)


def test_drag_preview_then_one_undo_step(ed):
    g = _add(ed, grid(ed.document.active_layer_id))
    ids = [s.id for s in ed.document.shapes]
    ed.set_tool(Tool.TRIM)
    item = ed.trim_tool.item
    drag(ed, (30, 5), (30, 55), release=False)
    assert item.isVisible() and item.ok and item.fence == [(30.0, 5.0), (30.0, 55.0)]
    assert len(item.pieces) == 2 and len(ed.document.shapes) == 4   # erst beim Loslassen
    item.update()
    n0 = ed.undo_stack.count()
    ed.tools.release(QPointF(30, 55), NO)
    assert ed.undo_stack.count() == n0 + 1 and ed.undo_stack.undoText() == "Trimmen"
    assert not item.isVisible()
    assert not ed.document.has_shape(g[0].id) and not ed.document.has_shape(g[1].id)
    assert [s.id for s in ed.document.shapes][2:] == ids[2:]         # Stapelplatz bleibt
    assert pieces(ed.document.shapes[0]) == [[(10, 20), (20, 20)], [(40, 20), (50, 20)]]
    assert "2 Stücke (40.0 mm) von 2 Form(en)" in ed.msgs[-1]
    ed.undo_stack.undo()
    assert [s.id for s in ed.document.shapes] == ids
    ed.undo_stack.redo()
    assert len(ed.document.shapes) == 4 and not ed.document.has_shape(g[0].id)


def test_drag_preview_follows_the_finger(ed):
    _add(ed, grid(ed.document.active_layer_id))
    ed.set_tool(Tool.TRIM)
    item = ed.trim_tool.item
    drag(ed, (30, 5), (30, 30), release=False)                     # nur die erste Linie
    assert len(item.pieces) == 1 and item.piece == [(20.0, 20.0), (40.0, 20.0)]
    ed.tools.move(QPointF(30, 55), NO, True)
    assert len(item.pieces) == 2 and item.piece == []
    ed.tools.move(QPointF(60, 5), NO, True)                        # kreuzt nichts: grau
    assert item.isVisible() and not item.ok and item.pieces == []
    ed.tools.release(QPointF(60, 5), NO)
    assert "kreuzt kein Stück" in ed.msgs[-1] and len(ed.document.shapes) == 4


def test_selection_follows_and_tap_still_works(ed):
    lid = ed.document.active_layer_id
    g = _add(ed, grid(lid))
    ed.set_selection([g[0].id, g[3].id])
    ed.set_tool(Tool.TRIM)
    drag(ed, (30, 5), (30, 55))
    new0 = ed.document.shapes[0].id
    assert set(ed.selection) == {new0, g[3].id}
    n0 = ed.undo_stack.count()
    ed.tools.press(QPointF(20.2, 30), NO)                          # danach wieder Tippen
    ed.tools.release(QPointF(20.2, 30), NO)
    assert ed.undo_stack.count() == n0 + 1 and "20.0 mm entfernt" in ed.msgs[-1]


def test_locked_untrimmable_and_abort(ed):
    lid = ed.document.active_layer_id
    (lone,) = _add(ed, [seg(lid, (100, 100), (140, 100))])
    ed.set_tool(Tool.TRIM)
    n0 = ed.undo_stack.count()
    drag(ed, (120, 90), (120, 110))
    assert "ohne Kreuzung" in ed.msgs[-1] and ed.undo_stack.count() == n0
    _add(ed, grid(lid))
    ed.document.update_layer(lid, locked=True)
    n0 = ed.undo_stack.count()
    drag(ed, (30, 5), (30, 55))
    assert "gesperrt" in ed.msgs[-1] and ed.undo_stack.count() == n0
    ed.document.update_layer(lid, locked=False)
    drag(ed, (30, 5), (30, 55), release=False)
    ed.tools.abort_drag()                                          # zweiter Finger zoomt
    assert not ed.trim_tool.item.isVisible()
    ed.tools.release(QPointF(30, 55), NO)
    assert ed.undo_stack.count() == n0 and all(len(s.points) == 2 for s in ed.document.shapes)


def test_touch_mode_sweep(ed):
    _add(ed, grid(ed.document.active_layer_id))
    ed.set_touch_mode(True, persist=False)
    try:
        ed.set_tool(Tool.TRIM)
        drag(ed, (30, 5), (30, 55), release=False)
        assert ed.trim_tool.item.touch and len(ed.trim_tool.item.pieces) == 2
        ed.tools.release(QPointF(30, 55), NO)
        assert sum(len(s.ring_ranges()) for s in ed.document.shapes) == 6
    finally:
        ed.set_touch_mode(False, persist=False)


def test_save_load_no_new_key(ed, tmp_path):
    from lumacut_canvas.document_io import load_document, save_document
    _add(ed, grid(ed.document.active_layer_id))
    ed.set_tool(Tool.TRIM)
    drag(ed, (30, 5), (30, 55))
    p = tmp_path / "s.lcs"
    save_document(ed.document, p)
    again = load_document(p)
    assert [pieces(s) for s in again.shapes] == [pieces(s) for s in ed.document.shapes]
    assert '"trim' not in p.read_text(encoding="utf-8") and '"sweep' not in p.read_text(encoding="utf-8")
