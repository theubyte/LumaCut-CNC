"""Pfade verbinden / schließen, Duplikate löschen, offene Formen (Modell, Editor, Import, G-Code)."""

from __future__ import annotations

import math

import pytest
from _pi_guard import pi_check

from lumacut_canvas import pathjoin, pathops
from lumacut_canvas.commands import AddShapesCommand
from lumacut_canvas.editor import CanvasEditor
from lumacut_canvas.export import job_layers, layer_fill_blocks
from lumacut_canvas.model import Document, Geometry, Shape
from lumacut_canvas.shape_paths import shape_polygons
from lumacut_job.cutpath import CutOptions, apply_cut_options
from lumacut_job.planner import optimize_layers, optimized_document_gcode


@pytest.fixture
def doc(qapp):
    return Document()


def seg(doc, a, b, layer=None):
    return Shape.from_points("path", [a, b], layer or doc.active_layer_id)


def square_segments(doc, x, y, w, gap=0.0, layer=None):
    """Quadrat aus vier losen Strecken (DXF-LINEs), letzte Ecke um ``gap`` versetzt."""
    p = [(x, y), (x + w, y), (x + w, y + w), (x, y + w)]
    return [seg(doc, p[0], p[1], layer), seg(doc, p[2], p[1], layer),   # eine Strecke rückwärts
            seg(doc, p[2], p[3], layer), seg(doc, p[3], (x + gap, y), layer)]


def area(s):
    return pathops.shape_area(s).area


def test_segment_soup_square_becomes_one_closed_polygon(doc):
    parts = square_segments(doc, 10, 10, 20)
    res = pathjoin.auto_join(parts)
    assert res.changed and sorted(res.remove) == sorted(s.id for s in parts)
    (poly,) = res.add
    assert poly.kind == "polygon" and len(poly.points) == 4 and not poly.rings
    assert area(poly) == pytest.approx(400)
    assert res.closed == 1 and res.open_chains == 0 and res.open_left == 0
    assert res.pieces == 4
    assert "1 geschlossene Kontur" in res.summary()


def test_gap_within_and_beyond_tolerance(doc):
    near = pathjoin.auto_join(square_segments(doc, 0, 0, 10, gap=0.04))
    assert near.closed == 1
    # Ende in die Mitte der Lücke gezogen: Fläche fast unverändert
    assert area(near.add[0]) == pytest.approx(100, abs=0.5)
    far = pathjoin.auto_join(square_segments(doc, 0, 0, 10, gap=0.2))
    assert far.closed == 0 and far.open_chains == 1
    (path,) = far.add
    assert path.kind == "path" and len(path.points) == 5      # eine Kette, offen
    assert pathjoin.auto_join(square_segments(doc, 0, 0, 10, gap=0.2), 0.3).closed == 1


def test_nested_rings_become_polygon_with_hole_and_island(doc):
    shapes = (square_segments(doc, 0, 0, 100) + square_segments(doc, 20, 20, 60)
              + square_segments(doc, 40, 40, 20))
    res = pathjoin.auto_join(shapes)
    assert res.closed == 2                     # Rahmen mit Loch + Insel im Loch
    frame, island = sorted(res.add, key=lambda s: -s.bounds().w)
    assert len(frame.rings) == 1 and area(frame) == pytest.approx(10000 - 3600)
    assert not island.rings and area(island) == pytest.approx(400)


def test_fill_leaves_the_joined_hole_free(doc):
    lid = doc.active_layer_id
    doc.update_layer(lid, fill_mode="hatch", line_interval_mm=1.0)
    for s in square_segments(doc, 0, 0, 40) + square_segments(doc, 10, 10, 20):
        doc.add_shape(s)
    assert layer_fill_blocks(doc, doc.layer(lid)) == []      # offene Pfade: keine Füllung
    res = pathjoin.auto_join(doc.shapes)
    for i in res.remove:
        doc.remove_shape(i)
    for s in res.add:
        doc.add_shape(s)
    blocks = layer_fill_blocks(doc, doc.layer(lid))
    segs = [sg for _ids, ss in blocks for sg in ss]
    assert segs
    for (x0, y0), (x1, y1) in segs:
        if abs(y0 - 20) < 0.6:
            lo, hi = sorted((x0, x1))
            assert not (lo < 20 < hi)                          # Loch bleibt frei


def test_layers_groups_generators_and_closed_shapes_are_respected(doc):
    from lumacut_canvas.model import Layer
    other = doc.add_layer(Layer(name="Gravur"))
    a = seg(doc, (0, 0), (10, 0))
    b = seg(doc, (10, 0), (10, 10), layer=other.id)          # andere Ebene: nicht verbinden
    c = seg(doc, (10, 10), (20, 10))
    a.groups = ("g1", "inner")
    rect = Shape("rect", Geometry(0, 0, 10, 10), doc.active_layer_id)
    code = seg(doc, (0, 0), (5, 5))
    code.generator = {"type": "qr"}
    res = pathjoin.auto_join([a, b, c, rect, code])
    assert not res.changed and res.open_left == 3
    d = seg(doc, (10, 0), (20, 0))
    d.groups = ("g1",)
    res = pathjoin.auto_join([a, d])
    (joined,) = res.add
    assert joined.groups == ("g1",)                           # gemeinsamer Gruppen-Anfang
    assert res.open_chains == 1 and res.pieces == 2


def test_rotated_line_and_curved_path_use_their_real_outline(doc):
    lid = doc.active_layer_id
    line = Shape("line", Geometry(0, 0, 10, 0), lid)
    line.geom.rot = 90.0                                       # senkrecht um (5, 0)
    ends = pathjoin.open_pieces(line)[0]
    assert ends[0] == pytest.approx((5, -5)) and ends[1] == pytest.approx((5, 5))
    curved = Shape.from_points("path", [(5, 5), (15, 8), (25, 5)], lid, curves=[0, 1])
    res = pathjoin.auto_join([line, curved])
    (path,) = res.add
    assert path.kind == "path" and len(path.points) > 4       # Kurve abgeflacht
    pts = path.abs_points()
    assert {tuple(round(v, 6) for v in pts[0]), tuple(round(v, 6) for v in pts[-1])} == \
        {(5.0, -5.0), (25.0, 5.0)}


def test_multi_ring_path_keeps_unjoined_rings(doc):
    lid = doc.active_layer_id
    two = Shape.from_points("path", [(0, 0), (10, 0), (50, 50), (60, 50)], lid, rings=[2])
    more = seg(doc, (10, 0), (10, 10))
    res = pathjoin.auto_join([two, more])
    assert sorted(res.remove) == sorted([two.id, more.id])
    assert len(res.add) == 2 and res.open_chains == 1 and res.open_left == 1
    lengths = sorted(len(s.points) for s in res.add)
    assert lengths == [2, 3]


def test_close_paths_move_and_line_modes(doc):
    lid = doc.active_layer_id
    pts = [(0, 0), (10, 0), (10, 10), (0, 10), (0.3, 0.2)]
    p = Shape.from_points("path", pts, lid, curves=[1, 4])
    moved = pathjoin.close_paths([p], 0.5, "move")
    (m,) = moved.add
    assert m.kind == "polygon" and len(m.points) == 4
    assert m.abs_points()[0] == pytest.approx((0.15, 0.1))
    assert m.curves == (1,)                                   # Kurvensegment bleibt
    lined = pathjoin.close_paths([p], 0.5, "line")
    (ln,) = lined.add
    assert len(ln.points) == 5 and ln.curves == (1,)          # neue Schließstrecke gerade
    assert pathjoin.close_paths([p], 0.3, "move").closed == 0
    res = pathjoin.close_paths([p, seg(doc, (0, 0), (5, 0)), Shape("rect", Geometry(0, 0, 5, 5), lid)])
    assert (res.open_found, res.closed, res.left_open) == (2, 1, 1)
    assert res.summary() == "Offene Formen: 2 · geschlossen: 1 · bleiben offen: 1"
    with pytest.raises(ValueError):
        pathjoin.close_paths([p], 0.5, "glue")


def test_close_rotated_path_keeps_outline(doc):
    p = Shape.from_points("path", [(0, 0), (20, 0), (20, 10), (0, 10), (0, 0.01)], doc.active_layer_id)
    p.geom.rot = 30.0
    (c,) = pathjoin.close_paths([p], 0.5, "line").add
    assert c.geom.rot == 0
    before = shape_polygons(p)[0]
    after = shape_polygons(c)[0]
    for q in before:
        assert min(math.dist(q, r) for r in after) < 0.02


def test_duplicates_are_found_independent_of_start_direction_and_kind(doc):
    lid = doc.active_layer_id
    r = Shape("rect", Geometry(10, 10, 20, 10), lid)
    poly = Shape.from_points("polygon", [(30, 20), (30, 10), (10, 10), (10, 20)], lid)   # andere Richtung
    path = seg(doc, (0, 0), (5, 5))
    back = seg(doc, (5, 5), (0, 0))
    other_layer = Shape("rect", Geometry(10, 10, 20, 10), "elsewhere")
    shifted = Shape("rect", Geometry(10.05, 10, 20, 10), lid)
    open_square = Shape.from_points("path", [(10, 10), (30, 10), (30, 20), (10, 20), (10, 10)], lid)
    code = Shape("rect", Geometry(10, 10, 20, 10), lid, generator={"type": "qr"})
    dupes = pathjoin.find_duplicates([r, poly, path, back, other_layer, shifted, open_square, code])
    assert dupes == [poly.id, back.id]


def _ed(qapp):
    e = CanvasEditor()
    e.resize(1000, 700)
    e.show()
    qapp.processEvents()
    return e


@pytest.fixture
def ed(qapp):
    e = _ed(qapp)
    yield e
    e.undo_stack.setClean()
    e.close()


def _add(ed, shapes):
    ed.undo_stack.push(AddShapesCommand(ed.document, list(shapes)))
    return [s.id for s in shapes]


def test_editor_join_is_one_undo_step_and_works_without_selection(ed):
    lid = ed.document.active_layer_id
    keep = Shape("rect", Geometry(200, 200, 10, 10), lid)
    ids = _add(ed, square_segments(ed.document, 10, 10, 30) + [keep])
    msgs = []
    ed.statusMessage.connect(msgs.append)
    ed.set_selection([])
    ed.actions_by_name["path_join"].trigger()
    assert len(ed.document.shapes) == 2 and ed.document.has_shape(keep.id)
    new = ed.document.shape(ed.selection[0])
    assert new.kind == "polygon" and ed.undo_stack.undoText() == "Pfade verbinden"
    assert msgs[-1].startswith("Pfade verbinden: 4 Form(en) → 1 geschlossene")
    ed.undo_stack.undo()
    assert [s.id for s in ed.document.shapes] == ids
    ed.set_selection([keep.id])
    ed.actions_by_name["path_join"].trigger()
    assert "keine offenen Pfade" in msgs[-1] and len(ed.document.shapes) == 5
    assert ed.actions_by_name["path_join"].shortcut().toString() == "Alt+J"


def test_editor_join_skips_locked_layers(ed):
    lid = ed.document.active_layer_id
    _add(ed, square_segments(ed.document, 10, 10, 30))
    ed.document.update_layer(lid, locked=True)
    ed.set_selection([])
    ed.actions_by_name["path_join"].trigger()
    assert len(ed.document.shapes) == 4


def test_editor_close_paths_dialog_and_action(ed, qapp):
    lid = ed.document.active_layer_id
    near = Shape.from_points("path", [(0, 0), (10, 0), (10, 10), (0.2, 0)], lid)
    far = Shape.from_points("path", [(50, 50), (60, 50), (60, 60), (52, 50)], lid)
    ids = _add(ed, [near, far])
    dlg = pathjoin_ui_dialog([near, far])
    assert dlg.readout.text() == "Offene Formen: 2 · geschlossen: 1 · bleiben offen: 1"
    dlg.tolerance.setValue(2.5)
    assert "geschlossen: 2" in dlg.readout.text()
    dlg.tolerance.setValue(0.1)
    from PySide6.QtWidgets import QDialogButtonBox
    assert not dlg.buttons.button(QDialogButtonBox.Ok).isEnabled()
    dlg.mode.setCurrentIndex(1)
    assert dlg.values() == {"tolerance_mm": 0.1, "mode": "line"}
    dlg.deleteLater()
    seen = []
    ed.path_ops.cleanup.ask_close = lambda shapes: seen.append(len(shapes)) or \
        {"tolerance_mm": 0.5, "mode": "move"}
    ed.set_selection(ids)
    ed.actions_by_name["path_close"].trigger()
    assert seen == [2]
    kinds = [s.kind for s in ed.document.shapes]
    assert kinds == ["polygon", "path"]                       # an der alten Stelle ersetzt
    assert ed.undo_stack.undoText() == "Pfade schließen"
    ed.undo_stack.undo()
    assert [s.id for s in ed.document.shapes] == ids
    ed.path_ops.cleanup.ask_close = lambda shapes: None
    ed.actions_by_name["path_close"].trigger()
    assert [s.id for s in ed.document.shapes] == ids


def pathjoin_ui_dialog(shapes):
    from lumacut_canvas.pathjoin_ui import ClosePathsDialog
    return ClosePathsDialog(shapes)


def test_editor_delete_duplicates_and_select_open(ed):
    lid = ed.document.active_layer_id
    a = Shape("rect", Geometry(10, 10, 20, 20), lid)
    b = Shape("rect", Geometry(10, 10, 20, 20), lid)
    line = Shape("line", Geometry(50, 50, 10, 0), lid)
    line2 = Shape("line", Geometry(50, 50, 10, 0), lid)
    ids = _add(ed, [a, b, line, line2])
    ed.set_selection([])
    ed.actions_by_name["delete_duplicates"].trigger()
    assert [s.id for s in ed.document.shapes] == [a.id, line.id]
    assert ed.undo_stack.undoText() == "Duplikate löschen"
    ed.undo_stack.undo()
    assert [s.id for s in ed.document.shapes] == ids
    ed.set_selection([b.id, line.id])                          # nur innerhalb der Auswahl
    ed.actions_by_name["delete_duplicates"].trigger()
    assert len(ed.document.shapes) == 4
    ed.actions_by_name["select_open"].trigger()
    assert sorted(ed.selection) == sorted([line.id, line2.id])
    assert ed.actions_by_name["delete_duplicates"].shortcut().toString() == "Alt+Shift+D"


def test_cleanup_actions_in_path_menu_and_context_menu(ed):
    from PySide6.QtCore import QPointF
    _add(ed, [Shape("rect", Geometry(10, 10, 20, 10), ed.document.active_layer_id)])
    texts = [a.text() for a in ed.path_ops_button.menu().actions() if a.text()]
    for t in ("Pfade verbinden", "Pfade schließen (Toleranz) …", "Duplikate löschen",
              "Offene Formen auswählen"):
        assert t in texts
    menu = ed.build_context_menu(QPointF(20, 15))
    sub = next(a.menu() for a in menu.actions() if a.menu() is not None
               and a.menu().objectName() == "PathOpsMenu")
    assert "Pfade verbinden" in [a.text() for a in sub.actions()]


def test_joined_part_gets_kerf_tabs_and_inside_first_gcode(doc):
    """Gefügtes DXF-Teil schneidet wie ein gezeichnetes: Loch zuerst, Kerf, Stege, Pi-sicher."""
    lid = doc.active_layer_id
    doc.update_layer(lid, kerf_mm=0.1, tab_count=2, tab_width_mm=1.0)
    for s in square_segments(doc, 60, 60, 80) + square_segments(doc, 90, 90, 20):
        doc.add_shape(s)
    (raw,) = optimize_layers(job_layers(doc))
    assert "tab" not in raw.poly_kinds                         # offene Strecken: keine Stege
    res = pathjoin.auto_join(doc.shapes)
    for i in res.remove:
        doc.remove_shape(i)
    for s in res.add:
        doc.add_shape(s)
    (lay,) = optimize_layers(job_layers(doc))
    assert lay.poly_kinds.count("tab") >= 2
    g = optimized_document_gcode(doc)
    pi_check(g)
    assert g.count("M3 I") == 1
    # Loch vor der Außenkontur: erster Schnitt liegt innerhalb des Lochs (Maschinen-mm)
    from lumacut_canvas.workarea import to_machine
    hx = sorted((to_machine(90, 90)[0], to_machine(110, 110)[0]))
    xs = [p[0] for p in lay.polylines[0]]
    assert hx[0] - 0.5 <= min(xs) and max(xs) <= hx[1] + 0.5


def test_cut_options_treat_joined_ring_as_closed(doc):
    (poly,) = pathjoin.auto_join(square_segments(doc, 0, 0, 30)).add
    ring = [tuple(p) for p in shape_polygons(poly)[0]]
    assert ring[0] == ring[-1]
    res = apply_cut_options([ring], CutOptions(tab_count=2, tab_width_mm=1.0))
    assert res.kinds.count("tab") == 2


def test_import_hint_for_open_dxf_contours(qapp, tmp_path):
    ezdxf = pytest.importorskip("ezdxf")
    d = ezdxf.new()
    msp = d.modelspace()
    for a, b in (((0, 0), (40, 0)), ((40, 0), (40, 30)), ((40, 30), (0, 30)), ((0, 30), (0, 0)),
                 ((100, 0), (120, 0))):
        msp.add_line(a, b)
    p = tmp_path / "soup.dxf"
    d.saveas(p)
    from lumacut_import.placement import import_file
    from lumacut_import.qt import open_shapes_hint
    res = import_file(p, "L1")
    assert len(res.shapes) == 5
    assert open_shapes_hint(res.shapes) == \
        " · 5 offene Kontur(en), 4 davon verbindbar – Pfad › „Pfade verbinden“ (Alt+J)"
    assert open_shapes_hint([Shape("rect", Geometry(0, 0, 5, 5), "L1")]) == ""
    lone = [Shape.from_points("path", [(0, 0), (5, 0)], "L1")]
    assert open_shapes_hint(lone) == " · 1 offene Kontur(en)"


def test_main_window_import_message_mentions_open_contours(qapp, tmp_path):
    from PySide6.QtCore import QSettings
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(tmp_path))
    QSettings.setDefaultFormat(QSettings.IniFormat)
    main = pytest.importorskip("main")
    w = main.LumaCutStudio()
    w.import_tools.interactive = False
    try:
        svg = tmp_path / "lines.svg"
        svg.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="50mm" height="50mm" '
                       'viewBox="0 0 50 50"><path d="M0 0 L40 0"/><path d="M40 0 L40 40"/>'
                       '<path d="M40 40 L0 0"/></svg>')
        msgs = []
        w.canvas.statusMessage.connect(msgs.append)
        ids = w.import_tools.import_path(svg)
        assert len(ids) == 3
        assert any("3 offene Kontur(en), 3 davon verbindbar" in m for m in msgs)
        w.canvas.actions_by_name["path_join"].trigger()
        (tri,) = w.canvas.document.shapes
        assert tri.kind == "polygon" and area(tri) == pytest.approx(800, rel=1e-3)
    finally:
        w.canvas.undo_stack.setClean()
        w.close()
