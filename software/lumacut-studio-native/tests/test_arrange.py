"""Ausrichten, Verteilen, Raster- und Kreis-Array (Modell + Editor, Undo, Gruppen)."""

import pytest
from PySide6.QtCore import QPointF

from lumacut_canvas import arrange
from lumacut_canvas.commands import AddShapesCommand, SetGroupsCommand
from lumacut_canvas.editor import CanvasEditor
from lumacut_canvas.model import Document, Geometry, Shape
from lumacut_canvas.workarea import WORK_HEIGHT_MM, WORK_WIDTH_MM


def doc_with(*geoms):
    doc = Document()
    lid = doc.active_layer_id
    shapes = [doc.add_shape(Shape("rect", g, lid)) for g in geoms]
    return doc, [s.id for s in shapes]


def apply(doc, new):
    for i, g in new.items():
        doc.set_geometry(i, g)


def test_align_left_right_centre_to_selection():
    doc, ids = doc_with(Geometry(10, 10, 20, 10), Geometry(50, 40, 10, 10), Geometry(30, 80, 40, 5))
    apply(doc, arrange.align(doc, ids, "left"))
    assert [doc.shape(i).bounds().x for i in ids] == [10, 10, 10]
    apply(doc, arrange.align(doc, ids, "right"))
    assert {doc.shape(i).bounds().right for i in ids} == {50}
    apply(doc, arrange.align(doc, ids, "vcenter"))
    cy = {round(doc.shape(i).bounds().y + doc.shape(i).bounds().h / 2, 6) for i in ids}
    assert cy == {47.5}  # Mitte der Auswahl 10..85


def test_single_object_aligns_to_work_area():
    doc, ids = doc_with(Geometry(10, 10, 20, 10))
    apply(doc, arrange.align(doc, ids, "hcenter"))
    b = doc.shape(ids[0]).bounds()
    assert b.x + b.w / 2 == pytest.approx(WORK_WIDTH_MM / 2)
    apply(doc, arrange.align(doc, ids, "bottom"))
    assert doc.shape(ids[0]).bounds().bottom == pytest.approx(WORK_HEIGHT_MM)


def test_groups_move_as_one_unit():
    doc, ids = doc_with(Geometry(10, 10, 10, 10), Geometry(30, 20, 10, 10), Geometry(100, 50, 10, 10))
    for i in ids[:2]:
        doc.shape(i).groups = ("g1",)
    assert len(arrange.units_of(doc, ids)) == 2
    apply(doc, arrange.align(doc, ids, "top"))
    # Gruppe (Oberkante 10) bleibt in sich unverändert, das Einzelobjekt geht nach oben.
    assert doc.shape(ids[0]).bounds().y == 10 and doc.shape(ids[1]).bounds().y == 20
    assert doc.shape(ids[2]).bounds().y == 10


def test_distribute_equal_gaps_keeps_outer_units():
    doc, ids = doc_with(Geometry(0, 0, 10, 10), Geometry(15, 0, 30, 10), Geometry(100, 0, 20, 10))
    apply(doc, arrange.distribute(doc, ids, "h"))
    b = [doc.shape(i).bounds() for i in ids]
    assert b[0].x == 0 and b[2].x == 100
    assert b[1].x - b[0].right == pytest.approx(b[2].x - b[1].right)
    assert arrange.distribute(doc, ids[:2], "h") == {}


def test_grid_array_counts_spacing_and_new_ids():
    doc, ids = doc_with(Geometry(10, 10, 20, 10))
    copies = arrange.grid_array(doc, ids, cols=3, rows=2, gap_x=5, gap_y=2)
    assert len(copies) == 5
    xs = sorted({round(c.bounds().x, 6) for c in copies})
    ys = sorted({round(c.bounds().y, 6) for c in copies})
    assert xs == [10, 35, 60] and ys == [10, 22]
    assert len({c.id for c in copies} | set(ids)) == 6


def test_grid_array_of_group_keeps_groups_per_copy():
    doc, ids = doc_with(Geometry(10, 10, 10, 10), Geometry(25, 10, 10, 10))
    for i in ids:
        doc.shape(i).groups = ("g1",)
    copies = arrange.grid_array(doc, ids, cols=3, rows=1)
    gids = [c.groups[0] for c in copies]
    assert len(set(gids)) == 2 and "g1" not in gids
    assert all(gids.count(g) == 2 for g in set(gids))


def test_circular_array_rotates_around_centre():
    doc, ids = doc_with(Geometry(95, 45, 10, 10))  # Mitte (100, 50)
    copies = arrange.circular_array(doc, ids, count=4, cx=100, cy=100)
    centres = sorted((round(c.geom.center()[0], 6), round(c.geom.center()[1], 6)) for c in copies)
    assert centres == [(50, 100), (100, 150), (150, 100)]
    assert sorted(round(c.geom.rot) for c in copies) == [-90, 90, 180]
    upright = arrange.circular_array(doc, ids, count=4, cx=100, cy=100, rotate=False)
    assert all(c.geom.rot == 0 for c in upright)
    arc = arrange.circular_array(doc, ids, count=3, cx=100, cy=100, angle_deg=180)
    assert sorted(round(c.geom.center()[1], 6) for c in arc) == [100, 150]


def test_outside_count():
    doc, ids = doc_with(Geometry(300, 10, 50, 10))
    assert arrange.outside_count(arrange.grid_array(doc, ids, cols=2, rows=1)) == 1


@pytest.fixture
def ed(qapp):
    e = CanvasEditor()
    e.resize(1000, 700)
    e.show()
    qapp.processEvents()
    yield e
    e.undo_stack.setClean()
    e.close()


def _add(ed, *geoms):
    lid = ed.document.active_layer_id
    shapes = [Shape("rect", g, lid) for g in geoms]
    ed.undo_stack.push(AddShapesCommand(ed.document, shapes))
    ed.set_selection([s.id for s in shapes])
    return [s.id for s in shapes]


def test_editor_actions_are_one_undo_step(ed):
    ids = _add(ed, Geometry(10, 10, 20, 10), Geometry(40, 40, 10, 10), Geometry(80, 5, 10, 30))
    n = ed.undo_stack.count()
    ed.actions_by_name["align_top"].trigger()
    assert {ed.document.shape(i).bounds().y for i in ids} == {5}
    assert ed.undo_stack.count() == n + 1
    ed.actions_by_name["distribute_h"].trigger()
    assert ed.undo_stack.count() == n + 2
    ed.undo_stack.undo()
    ed.undo_stack.undo()
    assert ed.document.shape(ids[0]).bounds().y == 10


def test_editor_grid_and_circular_array(ed):
    ids = _add(ed, Geometry(10, 10, 20, 10))
    ed.arranger.ask_grid = lambda: {"cols": 2, "rows": 2, "gap_x": 5.0, "gap_y": 5.0}
    n_shapes = len(ed.document.shapes)
    ed.actions_by_name["array_grid"].trigger()
    assert len(ed.document.shapes) == n_shapes + 3
    assert len(ed.selection) == 4
    ed.undo_stack.undo()
    assert len(ed.document.shapes) == n_shapes
    ed.set_selection(ids)
    ed.arranger.ask_circular = lambda cx, cy: {"count": 6, "cx": cx, "cy": cy, "angle_deg": 360.0,
                                               "rotate": True}
    ed.actions_by_name["array_circular"].trigger()
    # Vorschlag-Mitte liegt unter der Auswahl → Kopien oberhalb von y=0 → abgelehnt.
    assert len(ed.document.shapes) == n_shapes
    ed.arranger.ask_circular = lambda cx, cy: {"count": 6, "cx": 150.0, "cy": 150.0, "angle_deg": 360.0,
                                               "rotate": True}
    ed.set_selection(ids)
    ed.translate_selection(120, 30)  # Mitte (140, 45) → Radius ~106 mm, passt
    ed.actions_by_name["array_circular"].trigger()
    assert len(ed.document.shapes) == n_shapes + 5


def test_arrange_menu_in_bar_and_context_menu(ed):
    _add(ed, Geometry(10, 10, 20, 10))
    assert ed.arrange_button.menu().objectName() == "ArrangeMenu"
    menu = ed.build_context_menu(QPointF(20, 15))
    subs = [a.menu() for a in menu.actions() if a.menu() is not None]
    assert subs and subs[0].objectName() == "ArrangeMenu"
    assert ed.actions_by_name["array_grid"] in subs[0].actions()
