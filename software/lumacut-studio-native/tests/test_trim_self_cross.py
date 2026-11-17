"""Trimmen an Selbstkreuzungen (Acht, Schleife eines Pfads) und Stege / Startpunkt beim
Trimmen: Selbstkreuzungen als Schnittstellen, Schlaufe einer Acht bleibt geschlossen,
Drehung, Kurven, Ziehen, Stege / Startpunkt auf Konturen, die geschlossen bleiben,
Hinweis in der Statuszeile, G-Code, Werkzeug, Undo, Speichern ohne neuen Schlüssel."""

from __future__ import annotations

import math

import pytest
from _pi_guard import pi_check
from PySide6.QtCore import QPointF, Qt
from shapely.geometry import Polygon as SPolygon

from lumacut_canvas import pathtrim, startpoint, tabs
from lumacut_canvas.commands import AddShapesCommand
from lumacut_canvas.editor import CanvasEditor
from lumacut_canvas.model import Document, Geometry, Shape
from lumacut_canvas.shape_paths import shape_polygons
from lumacut_canvas.toolpath import parse_gcode
from lumacut_canvas.tools import Tool
from lumacut_job.planner import optimized_document_gcode

NO = Qt.NoModifier
SQ2 = math.sqrt(2.0)


@pytest.fixture
def doc(qapp):
    return Document()


def seg(lid, *pts):
    return Shape.from_points("path", list(pts), lid)


def bowtie(lid, x=0.0, y=0.0):
    """Acht aus geraden Linien (Schleife links / rechts, Kreuzung bei (x+10, y+10))."""
    return Shape.from_points("polygon", [(x, y), (x + 20, y + 20), (x + 20, y), (x, y + 20)], lid)


def world(shape):
    return [tuple(round(c, 6) for c in p) for p in pathtrim._world_points(shape)]


def area(shape):
    return sum(SPolygon(r).area for r in shape_polygons(shape))


def length(pts):
    return sum(math.dist(a, b) for a, b in zip(pts, pts[1:]))


def near_all(pts, ref, tol=1e-6):
    return all(any(math.dist(p, q) <= tol for q in ref) for p in pts)


# ------------------------------------------------------------- Selbstkreuzungen
def test_self_cuts_figure_eight_and_simple_rings():
    ring = [(0, 0), (20, 20), (20, 0), (0, 20), (0, 0)]
    cuts = pathtrim.self_cuts(ring, True)
    assert cuts == pytest.approx([10 * SQ2, 20 * SQ2 + 20 + 10 * SQ2])     # beide Durchgänge
    assert pathtrim.self_cuts([(0, 0), (40, 0), (40, 20), (0, 20), (0, 0)], True) == []
    # doppelte Punkte sind keine Kreuzung
    assert pathtrim.self_cuts([(0, 0), (10, 0), (10, 0), (20, 0), (20, 5)], False) == []
    # offener Pfad mit Schleife: Kreuzung bei (20, 0)
    loop = [(0, 0), (30, 0), (20, -10), (20, 10)]
    assert pathtrim.self_cuts(loop, False) == pytest.approx([20.0, 40 + 10 * SQ2])
    assert pathtrim.self_cuts(loop[:2], False) == []


def test_self_cuts_through_a_shared_vertex():
    # Acht, deren Kreuzung ein Knoten ist, der zweimal durchlaufen wird
    ring = [(10, 10), (0, 0), (0, 20), (10, 10), (20, 20), (20, 0), (10, 10)]
    total = length(ring)
    cuts = pathtrim._merge([d % total for d in pathtrim.self_cuts(ring, True)], 0.05)
    assert cuts == pytest.approx([0.0, total / 2])               # Ringstart = Kreuzung
    poly = Shape.from_points("polygon", ring[:-1], "L")
    pick = pathtrim.TrimIndex([poly]).pick((20, 10), 0.5)
    assert pick.ok and length(pick.removed) == pytest.approx(total / 2)
    assert [s.kind for s in pick.add] == ["polygon"] and area(pick.add[0]) == pytest.approx(100.0)


def test_tap_on_one_loop_keeps_the_other_closed(doc):
    b = bowtie(doc.active_layer_id)
    b.groups, b.priority, b.reverse = ("g1",), 3, True
    pick = pathtrim.TrimIndex([b]).pick((20, 10), 0.5)          # rechte Schlaufe
    assert pick.ok and pick.remove == [b.id]
    assert length(pick.removed) == pytest.approx(20 + 20 * SQ2)
    (rest,) = pick.add
    assert rest.kind == "polygon" and len(rest.ring_ranges()) == 1
    assert sorted(world(rest)) == [(0.0, 0.0), (0.0, 20.0), (10.0, 10.0)]
    assert area(rest) == pytest.approx(100.0)
    assert (rest.layer_id, rest.groups, rest.priority, rest.reverse) == (b.layer_id, ("g1",), 3, True)


def test_figure_eight_was_untrimmable_alone_simple_ring_still_is(doc):
    lid = doc.active_layer_id
    assert pathtrim.TrimIndex([bowtie(lid)]).pick((0, 10), 0.5).ok
    rect = Shape("rect", Geometry(50, 0, 30, 20), lid)
    pick = pathtrim.TrimIndex([rect]).pick((65, 0), 0.5)
    assert not pick.ok and "kreuzt keine andere Form" in pick.reason


def test_loop_of_an_open_path(doc):
    lid = doc.active_layer_id
    loop = seg(lid, (0, 0), (30, 0), (20, -10), (20, 10))
    pick = pathtrim.TrimIndex([loop]).pick((25, -5), 0.5)       # die Schlaufe
    assert pick.ok and length(pick.removed) == pytest.approx(10 + 10 + 10 * SQ2)
    (rest,) = pick.add
    assert rest.kind == "path"
    pts = rest.abs_points()
    assert [[tuple(round(c, 6) for c in p) for p in pts[a:b]] for a, b in rest.ring_ranges()] == \
        [[(0, 0), (20, 0)], [(20, 0), (20, 10)]]
    # Ende hinter der eigenen Kreuzung: wie ein Überstand
    pick = pathtrim.TrimIndex([loop]).pick((20, 5), 0.5)
    assert pick.ok and length(pick.removed) == pytest.approx(10.0)


def test_self_crossing_combined_with_other_cutters(doc):
    lid = doc.active_layer_id
    b = bowtie(lid)
    bar = seg(lid, (15, -5), (15, 25))                           # kreuzt die rechte Schlaufe zweimal
    pick = pathtrim.TrimIndex([b, bar], [b.id]).pick((20, 10), 0.5)
    assert pick.ok and length(pick.removed) == pytest.approx(5 * SQ2 + 20 + 5 * SQ2)
    (rest,) = pick.add                                           # Schlaufe offen -> Pfad
    assert rest.kind == "path"
    assert length(rest.abs_points()) == pytest.approx(20 + 30 * SQ2)


def test_sweep_across_both_loops_removes_the_shape_or_one_loop(doc):
    lid = doc.active_layer_id
    b = bowtie(lid)
    sw = pathtrim.TrimIndex([b]).sweep((-5, 10), (25, 10))
    assert dict(sw.replace)[b.id] == []
    sw = pathtrim.TrimIndex([b]).sweep((15, 10), (25, 10))       # nur die rechte Schlaufe
    ((_sid, (rest,)),) = sw.replace
    assert rest.kind == "polygon" and area(rest) == pytest.approx(100.0)


def test_rotated_and_curved_figure_eight(doc):
    lid = doc.active_layer_id
    b = bowtie(lid, 50, 50)
    b.geom.rot = 90.0
    pts = pathtrim._world_points(b)                              # gedreht: Schlaufen oben / unten
    lobe_mid = ((pts[1][0] + pts[2][0]) / 2, (pts[1][1] + pts[2][1]) / 2)
    pick = pathtrim.TrimIndex([b]).pick(lobe_mid, 0.5)
    assert pick.ok and pick.add[0].kind == "polygon" and area(pick.add[0]) == pytest.approx(100.0)
    keep = SPolygon([pts[0], pts[3], (60.0, 60.0)])              # die andere Schlaufe, gedreht
    assert SPolygon(pathtrim._world_points(pick.add[0])).symmetric_difference(keep).area < 1e-6
    curved = Shape.from_points("polygon", [(0, 0), (20, 20), (20, 0), (0, 20)], lid)
    curved.curves = (0, 2)
    rings = pathtrim.shape_rings(curved)
    assert len(pathtrim.self_cuts(rings[0][0], True)) >= 2
    pick = pathtrim.TrimIndex([curved]).pick((20, 10), 0.5)
    assert pick.ok and [s.kind for s in pick.add] == ["polygon"]


def test_stub_trimming_unchanged_by_self_crossings(doc):
    loop = seg(doc.active_layer_id, (0, 0), (30, 0), (20, -10), (20, 10))
    assert not pathtrim.trim_stubs([loop], 50.0).changed


# ------------------------------------------------------------- Stege / Startpunkt
def holed(lid):
    return Shape.from_points("polygon", [(0, 0), (40, 0), (40, 40), (0, 40),
                                         (10, 10), (30, 10), (30, 30), (10, 30)], lid, rings=[4])


def test_tabs_and_start_kept_on_rings_that_stay_closed(doc):
    lid = doc.active_layer_id
    poly = tabs.with_tab_points(holed(lid), [(20.0, 0.0), (40.0, 25.0), (10.0, 20.0)])
    poly = startpoint.with_start(poly, (0.0, 15.0))
    bar = seg(lid, (20, 5), (20, 35))
    pick = pathtrim.TrimIndex([poly, bar], [poly.id]).pick((15, 10), 0.5)   # linke Lochhälfte
    outer = next(s for s in pick.add if s.kind == "polygon")
    assert near_all(outer.tab_points(), [(20.0, 0.0), (40.0, 25.0)]) and len(outer.tabs) == 2
    assert outer.start_point() == pytest.approx((0.0, 15.0))
    hole_rest = next(s for s in pick.add if s.kind == "path")
    assert hole_rest.tabs == () and hole_rest.start == ()
    assert pathtrim.dropped_marks([poly], pick.add) == (1, 0)
    assert pathtrim.marks_note(1, 0) == " (1 Steg auf offenen / entfernten Stücken entfallen)"
    assert pathtrim.marks_note(0, 0) == ""
    assert "2 Stege und 1 Startpunkt" in pathtrim.marks_note(2, 1)


def test_tabs_follow_the_loop_that_stays(doc):
    b = bowtie(doc.active_layer_id)
    b = tabs.with_tab_points(b, [(0.0, 10.0), (20.0, 10.0)])    # je Schlaufe ein Steg
    b = startpoint.with_start(b, (20.0, 5.0))                   # Start auf der rechten Schlaufe
    pick = pathtrim.TrimIndex([b]).pick((20, 15), 0.5)
    (rest,) = pick.add
    assert near_all(rest.tab_points(), [(0.0, 10.0)]) and len(rest.tabs) == 1
    assert rest.start == ()
    assert pathtrim.dropped_marks([b], pick.add) == (1, 1)
    # Start auf der bleibenden Schlaufe bleibt
    b2 = startpoint.with_start(bowtie(doc.active_layer_id), (0.0, 5.0))
    (rest2,) = pathtrim.TrimIndex([b2]).pick((20, 15), 0.5).add
    assert rest2.start_point() == pytest.approx((0.0, 5.0))


def test_opened_contour_drops_marks_and_untouched_shapes_unchanged(doc):
    lid = doc.active_layer_id
    rect = tabs.with_tab_points(Shape("rect", Geometry(0, 0, 40, 20), lid), [(20.0, 20.0)])
    bar = seg(lid, (20, -5), (20, 25))
    pick = pathtrim.TrimIndex([rect, bar], [rect.id]).pick((10, 0), 0.5)
    (new,) = pick.add
    assert new.kind == "path" and new.tabs == ()
    assert pathtrim.dropped_marks([rect], pick.add) == (1, 0)
    # ohne Stege / Startpunkt: dieselben Ersatzformen wie bisher (keine Kopie)
    plain = [Shape.from_points("path", [(0, 0), (1, 0)], lid)]
    assert pathtrim._carry_marks(bowtie(lid), plain) is plain


def test_gcode_of_the_remaining_loop_with_its_tab_and_pi_safe(doc):
    lid = doc.active_layer_id
    doc.update_layer(lid, tab_width_mm=2.0)
    b = tabs.with_tab_points(bowtie(lid, 50, 50), [(50.0, 60.0)])
    doc.add_shape(b)
    pick = pathtrim.TrimIndex(doc.shapes).pick((70, 60), 0.5)
    doc.remove_shape(b.id)
    for s in pick.add:
        doc.add_shape(s)
    g = optimized_document_gcode(doc, scan_offsets=None)
    assert parse_gcode(g).cut_length_mm == pytest.approx(20 + 20 * SQ2 - 2.0, abs=1e-3)
    pi_check(g)


# ------------------------------------------------------------- Werkzeug
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


def test_tool_tap_on_figure_eight_keeps_closed_loop_and_undo(ed):
    lid = ed.document.active_layer_id
    (b,) = _add(ed, [tabs.with_tab_points(bowtie(lid, 50, 50), [(50.0, 60.0), (70.0, 60.0)])])
    ed.set_selection([b.id])
    ed.set_tool(Tool.TRIM)
    ed.tools.move(QPointF(70, 60), NO, False)                    # Vorschau der Schlaufe
    assert ed.trim_tool.item.isVisible() and ed.trim_tool.item.ok
    n0 = ed.undo_stack.count()
    click(ed, 70, 60)
    assert ed.undo_stack.count() == n0 + 1
    (rest,) = ed.document.shapes
    assert rest.kind == "polygon" and len(rest.tabs) == 1 and ed.selection == [rest.id]
    msg = ed.msgs[-1]
    assert "Stück der Kontur von" in msg and "offener Pfad" not in msg
    assert "1 Steg auf offenen / entfernten Stücken entfallen" in msg
    ed.undo_stack.undo()
    assert [s.id for s in ed.document.shapes] == [b.id] and len(ed.document.shapes[0].tabs) == 2


def test_tool_sweep_over_a_path_loop_and_notes(ed):
    lid = ed.document.active_layer_id
    (loop,) = _add(ed, [seg(lid, (50, 50), (80, 50), (70, 40), (70, 60))])
    ed.set_tool(Tool.TRIM)
    ed.tools.press(QPointF(75, 35), NO)
    ed.tools.move(QPointF(75, 40), NO, True)
    ed.tools.move(QPointF(75, 47), NO, True)
    assert len(ed.trim_tool.item.pieces) == 1
    ed.tools.release(QPointF(75, 47), NO)
    (rest,) = ed.document.shapes
    assert length(rest.abs_points()) == pytest.approx(30.0)
    assert "1 Stück" in ed.msgs[-1] and "entfallen" not in ed.msgs[-1]


def test_save_load_keeps_carried_tabs_no_new_key(ed, tmp_path):
    from lumacut_canvas.document_io import load_document, save_document
    lid = ed.document.active_layer_id
    _add(ed, [tabs.with_tab_points(bowtie(lid, 50, 50), [(50.0, 60.0)])])
    ed.set_tool(Tool.TRIM)
    click(ed, 70, 60)
    p = tmp_path / "t.lcs"
    save_document(ed.document, p)
    again = load_document(p)
    (s,) = again.shapes
    assert s.kind == "polygon" and near_all(s.tab_points(), [(50.0, 60.0)], 1e-4)
    text = p.read_text(encoding="utf-8")
    assert '"self' not in text and '"trim' not in text
