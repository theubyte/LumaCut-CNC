"""Pfade vereinfachen (LightBurn *Optimize Selected Shapes*): Knoten reduzieren, Kurven in Linien."""

from __future__ import annotations

import math
import time

import pytest
from _pi_guard import pi_check

from lumacut_canvas import pathops, pathsimplify
from lumacut_canvas.commands import AddShapesCommand
from lumacut_canvas.editor import CanvasEditor
from lumacut_canvas.model import Document, Geometry, Shape, simplify_polyline
from lumacut_canvas.shape_paths import shape_polygons
from lumacut_job.planner import optimized_document_gcode


@pytest.fixture
def doc(qapp):
    return Document()


def circle_pts(cx, cy, r, n=720, start=0.0):
    return [(cx + r * math.cos(start + 2 * math.pi * k / n), cy + r * math.sin(start + 2 * math.pi * k / n))
            for k in range(n)]


def dense_square(x, y, w, per_edge=50):
    """Quadrat mit vielen kollinearen Zwischenknoten (wie aus einem Import)."""
    pts = []
    corners = [(x, y), (x + w, y), (x + w, y + w), (x, y + w)]
    for a, b in zip(corners, corners[1:] + corners[:1]):
        for k in range(per_edge):
            t = k / per_edge
            pts.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))
    return pts


def seg_dist(p, a, b):
    dx, dy = b[0] - a[0], b[1] - a[1]
    L = dx * dx + dy * dy
    t = 0.0 if L == 0 else max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / L))
    return math.hypot(p[0] - a[0] - t * dx, p[1] - a[1] - t * dy)


def max_deviation(orig_polys, new_polys):
    worst = 0.0
    segs = [(p[i], p[i + 1]) for p in new_polys for i in range(len(p) - 1)]
    for poly in orig_polys:
        for pt in poly:
            worst = max(worst, min(seg_dist(pt, a, b) for a, b in segs))
    return worst


def area(s):
    return pathops.shape_area(s).area


# ---------------------------------------------------------------- Engine
def test_dense_circle_polygon_loses_most_nodes_within_tolerance(doc):
    lid = doc.active_layer_id
    s = Shape.from_points("polygon", circle_pts(50, 50, 20), lid)
    out = pathsimplify.simplify_shape(s, 0.05)
    assert out is not None and out.kind == "polygon" and out.id != s.id
    assert 40 < len(out.points) < 120                       # 720 → ~80
    assert max_deviation(shape_polygons(s), shape_polygons(out)) <= 0.05 + 1e-6
    assert area(out) == pytest.approx(area(s), rel=0.01)
    coarse = pathsimplify.simplify_shape(s, 0.5)
    assert len(coarse.points) < len(out.points)
    assert max_deviation(shape_polygons(s), shape_polygons(coarse)) <= 0.5 + 1e-6


def test_collinear_nodes_removed_exactly_and_ring_stays_closed(doc):
    s = Shape.from_points("polygon", dense_square(10, 10, 20), doc.active_layer_id)
    assert len(s.points) == 200
    out = pathsimplify.simplify_shape(s, 0.01)
    assert len(out.points) == 4 and out.kind == "polygon"
    assert sorted((round(x, 6), round(y, 6)) for x, y in out.abs_points()) == \
        [(10, 10), (10, 30), (30, 10), (30, 30)]
    assert area(out) == pytest.approx(400)
    # Start mitten auf einer Kante: auch dieser Knoten fällt weg
    mid = Shape.from_points("polygon", [(20, 10), (30, 10), (30, 30), (10, 30), (10, 10)],
                            doc.active_layer_id)
    assert len(pathsimplify.simplify_shape(mid, 0.01).points) == 4


def test_open_path_keeps_its_ends_and_stays_open(doc):
    pts = [(x / 10, 5 * math.sin(x / 50)) for x in range(0, 1001)]
    s = Shape.from_points("path", pts, doc.active_layer_id)
    out = pathsimplify.simplify_shape(s, 0.02)
    assert out.kind == "path" and len(out.points) < 150      # 1001 → ~100
    got = out.abs_points()
    assert got[0] == pytest.approx(pts[0]) and got[-1] == pytest.approx(pts[-1])
    assert max_deviation([pts], [got]) <= 0.02 + 1e-6
    straight = Shape.from_points("path", [(0, 0), (5, 0), (10, 0)], doc.active_layer_id)
    assert [tuple(p) for p in pathsimplify.simplify_shape(straight, 0.01).abs_points()] == \
        [(0, 0), (10, 0)]


def test_unchanged_shapes_return_none(doc):
    lid = doc.active_layer_id
    tri = Shape.from_points("polygon", [(0, 0), (10, 0), (5, 8)], lid)
    assert pathsimplify.simplify_shape(tri, 0.5) is None
    for s in (Shape("rect", Geometry(0, 0, 10, 10), lid), Shape("ellipse", Geometry(0, 0, 10, 10), lid),
              Shape("line", Geometry(0, 0, 10, 0), lid), Shape("text", Geometry(0, 0, 10, 5), lid, text="A")):
        assert not pathsimplify.can_simplify(s) and pathsimplify.simplify_shape(s) is None
    code = Shape.from_points("polygon", dense_square(0, 0, 10), lid)
    code.generator = {"type": "arc_text"}
    assert pathsimplify.simplify_shape(code) is None


def test_small_ring_never_collapses_and_holes_survive(doc):
    lid = doc.active_layer_id
    outer = dense_square(0, 0, 40)
    hole = circle_pts(20, 20, 0.05, n=12)                   # winziges Loch, kleiner als die Toleranz
    big_hole = circle_pts(20, 20, 8, n=360)[::-1]
    s = Shape.from_points("polygon", outer + big_hole + hole, lid,
                          rings=[len(outer), len(outer) + len(big_hole)])
    out = pathsimplify.simplify_shape(s, 0.2)
    assert len(out.rings) == 2
    sizes = [b - a for a, b in out.ring_ranges()]
    assert sizes[0] == 4 and sizes[1] < 60 and sizes[2] >= 3
    assert area(out) == pytest.approx(area(s), rel=0.01)


def test_layer_groups_and_rotation_are_kept(doc):
    lid = doc.active_layer_id
    s = Shape.from_points("polygon", circle_pts(60, 40, 15, start=0.3) + [(80, 40)], lid)
    s.geom = Geometry(s.geom.x, s.geom.y, s.geom.w, s.geom.h, 33.0)
    s.groups = ("g1", "g2")
    out = pathsimplify.simplify_shape(s, 0.05)
    assert out.layer_id == lid and out.groups == ("g1", "g2") and out.geom.rot == 33.0
    assert max_deviation(shape_polygons(s), shape_polygons(out)) <= 0.05 + 1e-6
    b0, b1 = s.bounds(), out.bounds()
    assert (b1.x, b1.y, b1.w, b1.h) == pytest.approx((b0.x, b0.y, b0.w, b0.h), abs=0.06)


def test_curved_paths_skipped_unless_fit_to_lines(doc):
    lid = doc.active_layer_id
    pts = [(0, 0), (10, 10), (20, 0), (30, 10), (40, 0)]
    s = Shape.from_points("path", pts, lid, curves=[0, 1, 2, 3])
    s.geom = Geometry(s.geom.x, s.geom.y, s.geom.w, s.geom.h, 20.0)
    res = pathsimplify.simplify_shapes([s], 0.05)
    assert res.changed == 0 and res.curves_skipped == 1 and "1 mit Kurven übersprungen" in res.readout()
    res = pathsimplify.simplify_shapes([s], 0.05, fit_lines=True)
    (out,) = res.add
    assert res.curves_fitted == 1 and out.kind == "path" and not out.curves and out.geom.rot == 0
    assert max_deviation(shape_polygons(s), shape_polygons(out)) <= 0.05 + 0.03
    assert "in Linien umgewandelt" in res.readout()
    # Kurven-Polygon bleibt geschlossen
    poly = Shape.from_points("polygon", [(0, 0), (20, 0), (20, 20), (0, 20)], lid, curves=[0, 1, 2, 3])
    (closed,) = pathsimplify.simplify_shapes([poly], 0.05, fit_lines=True).add
    assert closed.kind == "polygon" and area(closed) == pytest.approx(area(poly), rel=0.01)


def test_result_readout_counts_nodes(doc):
    lid = doc.active_layer_id
    sq = Shape.from_points("polygon", dense_square(0, 0, 10), lid)        # 200 → 4
    tri = Shape.from_points("polygon", [(0, 0), (10, 0), (5, 8)], lid)    # bleibt
    rect = Shape("rect", Geometry(0, 0, 5, 5), lid)                       # zählt nicht
    res = pathsimplify.simplify_shapes([sq, tri, rect], 0.05)
    assert (res.shapes, res.nodes_before, res.nodes_after, res.changed) == (2, 203, 7, 1)
    assert res.readout() == "Knoten: 203 → 7 (−97 %) · 1 von 2 Form(en) vereinfacht"
    assert pathsimplify.simplify_shapes([rect]).readout() == "Keine Pfade oder Polygone zum Vereinfachen"


def test_many_shapes_are_fast(doc):
    lid = doc.active_layer_id
    shapes = [Shape.from_points("polygon", circle_pts(10 + (k % 20) * 12, 10 + (k // 20) * 12, 5, n=360),
                                lid) for k in range(200)]
    t = time.perf_counter()
    res = pathsimplify.simplify_shapes(shapes, 0.05)
    assert time.perf_counter() - t < 5.0
    assert res.changed == 200 and res.nodes_after < res.nodes_before / 4


def test_model_simplify_polyline_unchanged_for_freehand():
    pts = [(0, 0), (1, 0.001), (2, 0)]
    assert simplify_polyline(pts, 0.01) == [(0.0, 0.0), (2.0, 0.0)]
    assert pathsimplify.simplify_ring([(0, 0), (0, 0), (10, 0), (10, 10)], 0.1) == \
        [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0)]


def test_gcode_gets_fewer_moves_and_passes_pi_guard(doc):
    lid = doc.active_layer_id
    s = Shape.from_points("polygon", circle_pts(100, 100, 30), lid)
    doc.add_shape(s)
    before = optimized_document_gcode(doc)
    (out,) = pathsimplify.simplify_shapes(doc.shapes, 0.05).add
    doc.remove_shape(s.id)
    doc.add_shape(out)
    after = optimized_document_gcode(doc)
    pi_check(after)
    n_before = sum(1 for ln in before.splitlines() if ln.startswith("G1"))
    n_after = sum(1 for ln in after.splitlines() if ln.startswith("G1"))
    assert n_after < n_before / 4
    assert not any(ln.split()[0] in ("G2", "G3") for ln in after.splitlines() if ln.strip())


# ---------------------------------------------------------------- Editor / UI
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


def test_dialog_readout_tolerance_fit_lines_and_ok_state(qapp, doc):
    from PySide6.QtWidgets import QDialogButtonBox
    from lumacut_canvas.pathjoin_ui import SimplifyDialog
    lid = doc.active_layer_id
    sq = Shape.from_points("polygon", dense_square(0, 0, 10), lid)
    curvy = Shape.from_points("path", [(0, 0), (10, 10), (20, 0)], lid, curves=[0, 1])
    dlg = SimplifyDialog([sq, curvy])
    assert dlg.tolerance.value() == pytest.approx(0.05)
    assert dlg.readout.text() == ("Knoten: 203 → 7 (−97 %) · 1 von 2 Form(en) vereinfacht · "
                                  "1 mit Kurven übersprungen")
    assert dlg.buttons.button(QDialogButtonBox.Ok).isEnabled()
    dlg.fit_lines.setChecked(True)
    assert "in Linien umgewandelt" in dlg.readout.text()
    assert dlg.values() == {"tolerance_mm": pytest.approx(0.05), "fit_lines": True}
    dlg.deleteLater()
    tri = Shape.from_points("polygon", [(0, 0), (10, 0), (5, 8)], lid)
    dlg = SimplifyDialog([tri])
    assert not dlg.buttons.button(QDialogButtonBox.Ok).isEnabled()
    dlg.tolerance.setValue(5.0)                     # zu grob: Ring würde kollabieren → bleibt
    assert not dlg.buttons.button(QDialogButtonBox.Ok).isEnabled()
    dlg.deleteLater()


def test_editor_simplify_one_undo_step_keeps_stacking_and_selection(ed):
    lid = ed.document.active_layer_id
    a = Shape.from_points("polygon", circle_pts(50, 50, 10), lid)
    keep = Shape("rect", Geometry(200, 200, 10, 10), lid)
    b = Shape.from_points("path", [(x, 100 + math.sin(x / 5)) for x in range(0, 100)], lid)
    ids = _add(ed, [a, keep, b])
    seen = []
    ed.path_ops.cleanup.ask_simplify = lambda shapes: seen.append(len(shapes)) or \
        {"tolerance_mm": 0.05, "fit_lines": False}
    msgs = []
    ed.statusMessage.connect(msgs.append)
    ed.set_selection([a.id, keep.id])
    ed.actions_by_name["path_simplify"].trigger()
    assert seen == [1]                                     # nur das Polygon der Auswahl
    shapes = ed.document.shapes
    assert [s.kind for s in shapes] == ["polygon", "rect", "path"]
    assert shapes[0].id != a.id and shapes[1].id == keep.id and shapes[2].id == b.id
    assert len(shapes[0].points) < 100
    assert sorted(ed.selection) == sorted([keep.id, shapes[0].id])
    assert ed.undo_stack.undoText() == "Pfade vereinfachen"
    assert msgs[-1].startswith("Pfade vereinfachen: Knoten: 720 → ")
    ed.undo_stack.undo()
    assert [s.id for s in ed.document.shapes] == ids
    ed.set_selection([])                                   # ohne Auswahl: alles Bearbeitbare
    ed.actions_by_name["path_simplify"].trigger()
    assert seen == [1, 2] and ed.selection == []
    assert [s.kind for s in ed.document.shapes] == ["polygon", "rect", "path"]
    assert all(s.id not in (a.id, b.id) for s in ed.document.shapes)
    assert ed.actions_by_name["path_simplify"].shortcut().toString() == "Alt+O"


def test_editor_simplify_cancel_locked_and_nothing_to_do(ed):
    lid = ed.document.active_layer_id
    a = Shape.from_points("polygon", circle_pts(50, 50, 10), lid)
    ids = _add(ed, [a])
    ed.path_ops.cleanup.ask_simplify = lambda shapes: None           # Abbrechen
    ed.set_selection([])
    ed.actions_by_name["path_simplify"].trigger()
    assert [s.id for s in ed.document.shapes] == ids
    msgs = []
    ed.statusMessage.connect(msgs.append)
    ed.document.update_layer(lid, locked=True)
    ed.path_ops.cleanup.ask_simplify = lambda shapes: pytest.fail("kein Dialog erwartet")
    ed.actions_by_name["path_simplify"].trigger()
    assert "keine Pfade oder Polygone im Dokument" in msgs[-1]
    assert [s.id for s in ed.document.shapes] == ids


def test_simplify_in_path_menu_and_context_menu(ed):
    from PySide6.QtCore import QPointF
    _add(ed, [Shape("rect", Geometry(10, 10, 20, 10), ed.document.active_layer_id)])
    texts = [a.text() for a in ed.path_ops_button.menu().actions() if a.text()]
    assert "Pfade vereinfachen …" in texts
    menu = ed.build_context_menu(QPointF(20, 15))
    sub = next(a.menu() for a in menu.actions() if a.menu() is not None
               and a.menu().objectName() == "PathOpsMenu")
    assert "Pfade vereinfachen …" in [a.text() for a in sub.actions()]


def test_main_window_alt_o_is_unique_and_simplifies_imported_svg_circle(qapp, tmp_path):
    from PySide6.QtCore import QSettings
    from PySide6.QtGui import QKeySequence
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(tmp_path))
    QSettings.setDefaultFormat(QSettings.IniFormat)
    main = pytest.importorskip("main")
    from PySide6.QtGui import QAction
    w = main.LumaCutStudio()
    w.import_tools.interactive = False
    try:
        owners = [a for a in w.findChildren(QAction) if a.shortcut() == QKeySequence("Alt+O")]
        assert [a.text() for a in owners] == ["Pfade vereinfachen …"]
        assert all("&O" not in m.title() for m in (a.menu() for a in w.menuBar().actions()) if m)
        d = " ".join(f"{'M' if k == 0 else 'L'}{x:.4f} {y:.4f}" for k, (x, y) in
                     enumerate(circle_pts(25, 25, 20, n=500))) + " Z"
        svg = tmp_path / "circle.svg"
        svg.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="50mm" height="50mm" '
                       f'viewBox="0 0 50 50"><path d="{d}"/></svg>')
        ids = w.import_tools.import_path(svg)
        assert len(ids) == 1
        before = w.canvas.document.shape(ids[0])
        w.canvas.path_ops.cleanup.ask_simplify = lambda shapes: {"tolerance_mm": 0.05, "fit_lines": True}
        w.canvas.set_selection(ids)
        w.canvas.actions_by_name["path_simplify"].trigger()
        (after,) = w.canvas.document.shapes
        assert after.kind == before.kind and len(after.points) < len(before.points) / 3
        assert area(after) == pytest.approx(area(before), rel=0.01)
    finally:
        w.canvas.undo_stack.setClean()
        w.close()
