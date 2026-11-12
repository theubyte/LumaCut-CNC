"""Ecken abrunden / abschrägen (LightBurn *Radius*-Werkzeug, xTool „Eckenradius“ für
Polygone / Sterne): Bogen- und Fasengeometrie, Begrenzung an kurzen Kanten, Mindestwinkel,
Außen- / Innenecken, offene / geschlossene Pfade, Löcher, Drehung, Rechtecke (Eckenradius),
Kurven / Codes übersprungen, manuelle Stege, G-Code mit Kerf / Stegen / Füllung und Pi-Wächter,
Dialog, Editor (ein Undo-Schritt, Auswahl, Abbrechen, gesperrte Ebene, Menüs) und Kürzel
im Hauptfenster."""

from __future__ import annotations

import math
import re

import pytest
from _pi_guard import pi_check
from shapely.geometry import Polygon

from lumacut_canvas import corners, ngon, pathfillet, tabs
from lumacut_canvas.commands import AddShapesCommand
from lumacut_canvas.editor import CanvasEditor
from lumacut_canvas.model import Document, Geometry, Shape
from lumacut_canvas.shape_paths import shape_polygons
from lumacut_canvas.toolpath import parse_gcode
from lumacut_job.planner import optimized_document_gcode

SQUARE = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]


def burned(g: str) -> float:
    return parse_gcode(g).cut_length_mm


def perimeter(pts, closed=True):
    seq = pts + pts[:1] if closed else pts
    return sum(math.dist(a, b) for a, b in zip(seq, seq[1:]))


def area(pts):
    return Polygon(pts).area


def world_rings(shape):
    out = []
    for poly in shape_polygons(shape):
        out.append(poly[:-1] if len(poly) > 1 and poly[0] == poly[-1] else poly)
    return out


def circle_pts(cx, cy, r, n=720):
    return [(cx + r * math.cos(2 * math.pi * k / n), cy + r * math.sin(2 * math.pi * k / n))
            for k in range(n)]


@pytest.fixture
def doc(qapp):
    return Document()


@pytest.fixture
def ed(qapp):
    e = CanvasEditor()
    e.resize(1000, 700)
    e.show()
    qapp.processEvents()
    yield e
    e.undo_stack.setClean()
    e.close()


# --- Geometrie ------------------------------------------------------------------------

def test_round_square_corners_are_tangent_arcs_within_tolerance():
    res = pathfillet.fillet_points(SQUARE, 2.0, True)
    assert res.corners == 4 and res.clamped == 0
    pts = res.points
    # Berührpunkte auf den Kanten, 2 mm von der Ecke
    for p in [(2, 0), (8, 0), (10, 2), (10, 8), (8, 10), (2, 10), (0, 8), (0, 2)]:
        assert min(math.dist(p, q) for q in pts) < 1e-9
    # Bogenpunkte liegen auf dem Kreis um (2, 2) / (8, 2) / …, Radius 2
    centres = [(2, 2), (8, 2), (8, 8), (2, 8)]
    for q in pts:
        if 0 < q[0] < 10 and 0 < q[1] < 10:
            assert min(abs(math.dist(q, c) - 2.0) for c in centres) < 1e-9
    # Sehnen weichen höchstens 0,02 mm vom Bogen ab
    for a, b in zip(pts, pts[1:] + pts[:1]):
        m = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
        if 0 < m[0] < 10 and 0 < m[1] < 10 and not (2 <= m[0] <= 8 or 2 <= m[1] <= 8):
            assert min(abs(math.dist(m, c) - 2.0) for c in centres) <= 0.02 + 1e-9
    assert perimeter(pts) == pytest.approx(4 * 6 + 2 * math.pi * 2, abs=0.05)   # Sehnen etwas kürzer
    assert area(pts) == pytest.approx(100 - (4 - math.pi) * 4, abs=0.2)


def test_chamfer_square_gives_straight_bevels():
    res = pathfillet.fillet_points(SQUARE, 2.0, True, mode="chamfer")
    assert res.corners == 4 and len(res.points) == 8
    assert area(res.points) == pytest.approx(92.0)
    assert perimeter(res.points) == pytest.approx(4 * 6 + 4 * 2 * math.sqrt(2))


def test_radius_is_clamped_on_short_edges():
    res = pathfillet.fillet_points(SQUARE, 8.0, True)
    assert res.corners == 4 and res.clamped == 4
    assert area(res.points) == pytest.approx(math.pi * 25, abs=0.5)      # Kreis mit r = 5 (Sehnen)
    # nur eine Ecke abgerundet (Mindestwinkel lässt die anderen nicht zu) → ganze Kante
    tri = [(0, 0), (40, 0), (0, 3)]
    one = pathfillet.fillet_points(tri, 50.0, True, corners="all", min_angle_deg=120)
    assert one.corners == 1 and one.clamped == 1


def test_min_angle_keeps_flattened_circles_and_selects_real_corners():
    circ = circle_pts(0, 0, 10)
    res = pathfillet.fillet_points(circ, 2.0, True)
    assert res.corners == 0 and res.points == circ
    octagon = [(10 * math.cos(k * math.pi / 4), 10 * math.sin(k * math.pi / 4)) for k in range(8)]
    assert pathfillet.fillet_points(octagon, 1.0, True).corners == 8               # 45° Knick
    assert pathfillet.fillet_points(octagon, 1.0, True, min_angle_deg=50).corners == 0


def test_star_outer_inner_and_all_corners_both_orientations():
    star = ngon.make_shape("L", 50, 50, 20, 5, 0.38)
    for pts in (star.abs_points(), star.abs_points()[::-1]):
        outer = pathfillet.fillet_points(pts, 1.0, True, corners="outer")
        inner = pathfillet.fillet_points(pts, 1.0, True, corners="inner")
        both = pathfillet.fillet_points(pts, 1.0, True)
        assert (outer.corners, inner.corners, both.corners) == (5, 5, 10)
        # Spitzen abgerundet: der weiteste Punkt liegt näher am Mittelpunkt
        far = max(math.dist(p, (50, 50)) for p in outer.points)
        assert far < 20 - 1.0
        near = min(math.dist(p, (50, 50)) for p in inner.points)
        assert near > 20 * 0.38 + 0.1
    res = pathfillet.fillet_shape(star, 1.0, corners="outer")
    assert res.shape.kind == "polygon" and res.shape.id != star.id
    assert ngon.spec_of(res.shape) is None                 # wie LightBurns Convert to Path


def test_open_path_keeps_its_ends_and_closed_loop_path_rounds_the_start():
    p = Shape.from_points("path", [(0, 0), (10, 0), (10, 10), (20, 10)], "L")
    res = pathfillet.fillet_shape(p, 2.0, corners="outer")       # offene Pfade: jede Ecke
    assert res.corners == 2
    pts = res.shape.abs_points()
    assert pts[0] == pytest.approx((0, 0)) and pts[-1] == pytest.approx((20, 10))
    assert res.shape.kind == "path"
    loop = Shape.from_points("path", SQUARE + [SQUARE[0]], "L")
    res = pathfillet.fillet_shape(loop, 2.0)
    assert res.corners == 4
    pts = res.shape.abs_points()
    assert pts[0] == pytest.approx(pts[-1])
    assert all(min(math.dist(c, q) for q in pts) > 0.5 for c in SQUARE)


def test_holes_are_rounded_and_rings_kept():
    outer = [(0, 0), (40, 0), (40, 40), (0, 40)]
    hole = [(10, 10), (10, 30), (30, 30), (30, 10)]
    s = Shape.from_points("polygon", outer + hole, "L", rings=[4])
    res = pathfillet.fillet_shape(s, 3.0)
    assert res.corners == 8
    out = res.shape
    assert len(out.rings) == 1
    rings = [out.abs_points()[a:b] for a, b in out.ring_ranges()]
    assert area(rings[0]) == pytest.approx(1600 - (4 - math.pi) * 9, abs=0.3)
    assert area(rings[1]) == pytest.approx(400 - (4 - math.pi) * 9, abs=0.3)


def test_rotation_layer_groups_kept_and_world_outline_matches():
    s = Shape.from_points("polygon", [(100, 100), (160, 100), (160, 130), (100, 130)], "L")
    s.geom = Geometry(s.geom.x, s.geom.y, s.geom.w, s.geom.h, 30.0)
    s.groups = ("g1",)
    res = pathfillet.fillet_shape(s, 5.0)
    out = res.shape
    assert out.geom.rot == pytest.approx(30.0) and out.layer_id == "L" and out.groups == ("g1",)
    assert out.geom.center() == pytest.approx(s.geom.center())
    (ring,) = world_rings(out)
    assert area(ring) == pytest.approx(1800 - (4 - math.pi) * 25, abs=0.5)
    (orig,) = world_rings(s)
    # jede abgerundete Kontur liegt innerhalb des Originals
    assert Polygon(orig).buffer(1e-6).contains(Polygon(ring))


def test_rectangles_get_their_corner_radius_or_a_chamfer_polygon():
    rect = Shape("rect", Geometry(0, 0, 30, 20, 15.0), "L")
    res = pathfillet.fillet_shape(rect, 3.0)
    assert res.shape.kind == "rect" and res.shape.id == rect.id
    assert res.shape.corner_radius == pytest.approx(3.0) and res.corners == 4 and res.clamped == 0
    big = pathfillet.fillet_shape(rect, 25.0)
    assert corners.effective_radius(big.shape) == pytest.approx(10.0) and big.clamped == 4
    assert pathfillet.fillet_shape(rect, 3.0, corners="inner").shape is None
    ch = pathfillet.fillet_shape(rect, 3.0, mode="chamfer")
    assert ch.shape.kind == "polygon" and len(ch.shape.points) == 8
    assert ch.shape.geom.rot == pytest.approx(15.0)
    (ring,) = world_rings(ch.shape)
    assert area(ring) == pytest.approx(600 - 4 * 4.5)
    rounded = corners.with_corner_radius(rect, 2.0)
    assert pathfillet.fillet_shape(rounded, 3.0, mode="chamfer").shape is None


def test_skipped_kinds_curves_and_codes():
    curvy = Shape.from_points("path", [(0, 0), (10, 10), (20, 0)], "L", curves=[0, 1])
    code = Shape.from_points("polygon", SQUARE, "L")
    code.generator = {"type": "qr", "text": "x"}
    ell = Shape("ellipse", Geometry(0, 0, 10, 10), "L")
    line = Shape.from_points("path", [(0, 0), (10, 0)], "L")
    tri = Shape.from_points("polygon", [(0, 0), (10, 0), (5, 8)], "L")
    res = pathfillet.fillet_shapes([curvy, code, ell, line, tri], 1.0)
    assert res.shapes == 3 and res.curves_skipped == 1 and res.changed == 1
    assert res.remove == [tri.id] and res.corners == 3
    assert not pathfillet.can_fillet(code) and not pathfillet.can_fillet(ell)
    assert pathfillet.fillet_shape(tri, 0.0).shape is None
    with pytest.raises(ValueError):
        pathfillet.fillet_shape(tri, 1.0, mode="bogus")


def test_readout_texts():
    tri = Shape.from_points("polygon", [(0, 0), (10, 0), (5, 8)], "L")
    sq = Shape.from_points("polygon", SQUARE, "L")
    curvy = Shape.from_points("path", [(0, 0), (10, 10), (20, 0)], "L", curves=[0])
    assert pathfillet.fillet_shapes([], 1.0).readout() == "Keine Polygone, Pfade oder Rechtecke mit Ecken"
    assert pathfillet.fillet_shapes([tri, sq, curvy], 1.0).readout() == \
        "7 Ecke(n) abgerundet in 2 von 3 Form(en) · 1 mit Kurven übersprungen"
    assert pathfillet.fillet_shapes([sq], 8.0, "chamfer").readout() == \
        "4 Ecke(n) abgeschrägt in 1 von 1 Form(en) · 4 mit kleinerem Radius (Kante zu kurz)"
    assert pathfillet.fillet_shapes([sq], 1.0, corners="inner").readout() == \
        "Keine passenden Ecken in 1 Form(en)"


def test_manual_tabs_follow_the_new_outline():
    s = Shape.from_points("polygon", [(0, 0), (40, 0), (40, 20), (0, 20)], "L")
    s = tabs.with_tab_points(s, [(20, 0), (40, 10)])
    out = pathfillet.fillet_shape(s, 3.0).shape
    got = sorted(out.tab_points())
    assert len(got) == 2
    assert got[0] == pytest.approx((20, 0), abs=1e-6) and got[1] == pytest.approx((40, 10), abs=1e-6)


def test_arc_segments_follow_the_chord_tolerance():
    assert pathfillet.arc_segments(2.0, math.pi / 2) == math.ceil(
        (math.pi / 2) / (2 * math.acos(1 - 0.02 / 2.0)))
    assert pathfillet.arc_segments(0.01, math.pi / 2) == 2
    assert pathfillet.arc_segments(50.0, 1e-4) == 1


# --- G-Code ---------------------------------------------------------------------------

def test_gcode_burns_the_rounded_perimeter_g1_only_and_passes_the_pi_guard(doc):
    lid = doc.active_layer_id
    star = ngon.make_shape(lid, 100, 100, 30, 5, 0.38)
    (out,) = pathfillet.fillet_shapes([star], 2.0).add
    doc.add_shape(out)
    g = optimized_document_gcode(doc, scan_offsets=None)
    pi_check(g)
    assert not re.search(r"^G[23]\b", g, re.M)
    (ring,) = world_rings(out)
    assert burned(g) == pytest.approx(perimeter(ring), abs=0.05)
    assert burned(g) < 2 * 5 * 30 * math.sqrt(1 + 0.38 ** 2 - 2 * 0.38 * math.cos(math.pi / 5))


def test_kerf_tabs_and_hatch_on_a_rounded_shape(doc):
    lid = doc.active_layer_id
    doc.update_layer(lid, kerf_mm=0.1, tab_count=4, tab_width_mm=1.0)
    sq = Shape.from_points("polygon", [(50, 50), (110, 50), (110, 90), (50, 90)], lid)
    (out,) = pathfillet.fillet_shapes([sq], 5.0).add
    doc.add_shape(out)
    g = optimized_document_gcode(doc, scan_offsets=None)
    pi_check(g)
    plain = 2 * (50 + 30) + 2 * math.pi * 5
    assert plain < burned(g) + 4 * 1.0 < plain + 2.0
    fill = Document()
    fl = fill.active_layer_id
    fill.update_layer(fl, fill_mode="hatch", hatch_outline=False, line_interval_mm=0.5)
    fill.add_shape(pathfillet.fillet_shapes(
        [Shape.from_points("polygon", [(50, 50), (110, 50), (110, 90), (50, 90)], fl)], 5.0).add[0])
    hatched = burned(optimized_document_gcode(fill, scan_offsets=None))
    assert hatched == pytest.approx((2400 - (4 - math.pi) * 25) / 0.5, rel=0.03)


def test_file_round_trip_of_a_filleted_shape(doc):
    lid = doc.active_layer_id
    (out,) = pathfillet.fillet_shapes([ngon.make_shape(lid, 60, 60, 20, 6)], 2.0).add
    doc.add_shape(out)
    again = Document.from_dict(doc.to_dict())
    (s,) = again.shapes
    assert s.kind == "polygon" and s.regular == () and len(s.points) == len(out.points)
    assert [c for p in s.abs_points() for c in p] == pytest.approx([c for p in out.abs_points() for c in p])


# --- Dialog / Editor ------------------------------------------------------------------

def _add(ed, shapes):
    ed.undo_stack.push(AddShapesCommand(ed.document, list(shapes)))
    return [s.id for s in shapes]


def test_dialog_defaults_readout_values_and_ok_state(qapp):
    from PySide6.QtWidgets import QDialogButtonBox
    from lumacut_canvas.pathfillet_ui import FilletDialog
    sq = Shape.from_points("polygon", SQUARE, "L")
    dlg = FilletDialog([sq])
    assert dlg.values() == {"radius_mm": pytest.approx(2.0), "mode": "round", "corners": "all",
                            "min_angle_deg": pytest.approx(10.0)}
    assert dlg.readout.text() == "4 Ecke(n) abgerundet in 1 von 1 Form(en)"
    assert dlg.buttons.button(QDialogButtonBox.Ok).isEnabled()
    dlg.mode.setCurrentIndex(dlg.mode.findData("chamfer"))
    assert dlg.readout.text().startswith("4 Ecke(n) abgeschrägt")
    dlg.radius.setValue(6.0)
    assert "4 mit kleinerem Radius" in dlg.readout.text()
    dlg.corners.setCurrentIndex(dlg.corners.findData("inner"))
    assert not dlg.buttons.button(QDialogButtonBox.Ok).isEnabled()
    dlg.deleteLater()
    dlg = FilletDialog([sq], values={"radius_mm": 1.5, "mode": "chamfer", "corners": "outer",
                                     "min_angle_deg": 30})
    assert dlg.values() == {"radius_mm": pytest.approx(1.5), "mode": "chamfer", "corners": "outer",
                            "min_angle_deg": pytest.approx(30)}
    assert [dlg.mode.itemText(i) for i in range(dlg.mode.count())] == ["Abrunden", "Abschrägen"]
    dlg.deleteLater()


def test_editor_fillet_one_undo_step_keeps_stacking_and_selection(ed):
    lid = ed.document.active_layer_id
    a = ngon.make_shape(lid, 60, 60, 20, 5, 0.4)
    keep = Shape("ellipse", Geometry(200, 200, 10, 10), lid)
    rect = Shape("rect", Geometry(100, 100, 30, 20), lid)
    ids = _add(ed, [a, keep, rect])
    seen = []
    ed.path_ops.fillet.ask = lambda shapes: seen.append([s.id for s in shapes]) or \
        {"radius_mm": 2.0, "mode": "round", "corners": "outer", "min_angle_deg": 10}
    msgs = []
    ed.statusMessage.connect(msgs.append)
    ed.set_selection([a.id, keep.id])
    ed.actions_by_name["path_fillet"].trigger()
    assert seen == [[a.id]]                                   # nur der Stern der Auswahl
    shapes = ed.document.shapes
    assert [s.kind for s in shapes] == ["polygon", "ellipse", "rect"]
    assert shapes[0].id != a.id and shapes[1].id == keep.id and shapes[2].id == rect.id
    assert sorted(ed.selection) == sorted([keep.id, shapes[0].id])
    assert ed.undo_stack.undoText() == "Ecken abrunden"
    assert msgs[-1] == "Ecken abrunden: 5 Ecke(n) abgerundet in 1 von 1 Form(en)"
    assert ed.path_ops.fillet.last["corners"] == "outer"
    ed.undo_stack.undo()
    assert [s.id for s in ed.document.shapes] == ids
    ed.undo_stack.redo()
    ed.undo_stack.undo()
    ed.set_selection([])                                      # ohne Auswahl: alles Bearbeitbare
    ed.path_ops.fillet.ask = lambda shapes: seen.append([s.id for s in shapes]) or \
        {"radius_mm": 3.0, "mode": "chamfer", "corners": "all", "min_angle_deg": 10}
    ed.actions_by_name["path_fillet"].trigger()
    assert seen[-1] == [a.id, rect.id] and ed.selection == []
    shapes = ed.document.shapes
    assert [s.kind for s in shapes] == ["polygon", "ellipse", "polygon"]
    assert len(shapes[2].points) == 8
    assert ed.undo_stack.undoText() == "Ecken abschrägen"
    assert ed.actions_by_name["path_fillet"].shortcut().toString() == "Alt+Shift+R"


def test_editor_fillet_rectangle_keeps_id_and_radius_field(ed):
    lid = ed.document.active_layer_id
    rect = Shape("rect", Geometry(100, 100, 30, 20), lid)
    _add(ed, [rect])
    ed.path_ops.fillet.ask = lambda shapes: {"radius_mm": 4.0, "mode": "round", "corners": "all",
                                             "min_angle_deg": 10}
    ed.set_selection([rect.id])
    ed.actions_by_name["path_fillet"].trigger()
    (s,) = ed.document.shapes
    assert s.id == rect.id and s.kind == "rect" and s.corner_radius == pytest.approx(4.0)
    assert ed.selection == [rect.id]
    ed.undo_stack.undo()
    assert ed.document.shapes[0].corner_radius == 0.0


def test_editor_cancel_locked_layer_and_nothing_to_do(ed):
    lid = ed.document.active_layer_id
    a = Shape.from_points("polygon", SQUARE, lid)
    ids = _add(ed, [a])
    ed.path_ops.fillet.ask = lambda shapes: None                       # Abbrechen
    ed.actions_by_name["path_fillet"].trigger()
    assert [s.id for s in ed.document.shapes] == ids and ed.undo_stack.undoText() != "Ecken abrunden"
    msgs = []
    ed.statusMessage.connect(msgs.append)
    ed.document.update_layer(lid, locked=True)
    ed.path_ops.fillet.ask = lambda shapes: pytest.fail("kein Dialog erwartet")
    ed.actions_by_name["path_fillet"].trigger()
    assert msgs[-1] == "Ecken abrunden: keine Polygone, Pfade oder Rechtecke im Dokument"
    ed.document.update_layer(lid, locked=False)
    ed.path_ops.fillet.ask = lambda shapes: {"radius_mm": 1.0, "mode": "round", "corners": "inner",
                                             "min_angle_deg": 10}
    ed.actions_by_name["path_fillet"].trigger()                      # keine Innenecken
    assert [s.id for s in ed.document.shapes] == ids
    assert msgs[-1] == "Ecken abrunden: Keine passenden Ecken in 1 Form(en)"


def test_fillet_in_path_menu_and_context_menu(ed):
    from PySide6.QtCore import QPointF
    _add(ed, [Shape("rect", Geometry(10, 10, 20, 10), ed.document.active_layer_id)])
    texts = [a.text() for a in ed.path_ops_button.menu().actions() if a.text()]
    assert texts.index("Ecken abrunden …") == texts.index("Versatz …") + 1
    menu = ed.build_context_menu(QPointF(20, 15))
    sub = next(a.menu() for a in menu.actions() if a.menu() is not None
               and a.menu().objectName() == "PathOpsMenu")
    assert "Ecken abrunden …" in [a.text() for a in sub.actions()]


def test_main_window_alt_shift_r_is_unique_and_rounds_an_imported_svg_star(qapp, tmp_path):
    from PySide6.QtCore import QSettings
    from PySide6.QtGui import QAction, QKeySequence
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(tmp_path))
    QSettings.setDefaultFormat(QSettings.IniFormat)
    main = pytest.importorskip("main")
    w = main.LumaCutStudio()
    w.import_tools.interactive = False
    try:
        owners = [a for a in w.findChildren(QAction) if a.shortcut() == QKeySequence("Alt+Shift+R")]
        assert [a.text() for a in owners] == ["Ecken abrunden …"]
        star = ngon.unit_outline(5, 0.38)
        pts = " ".join(f"{25 + 20 * x:.4f},{25 + 20 * y:.4f}" for x, y in star)
        svg = tmp_path / "star.svg"
        svg.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="50mm" height="50mm" '
                       f'viewBox="0 0 50 50"><polygon points="{pts}"/></svg>')
        ids = w.import_tools.import_path(svg)
        assert len(ids) == 1
        before = w.canvas.document.shape(ids[0])
        w.canvas.path_ops.fillet.ask = lambda shapes: {"radius_mm": 1.0, "mode": "round",
                                                       "corners": "outer", "min_angle_deg": 10}
        w.canvas.set_selection(ids)
        w.canvas.actions_by_name["path_fillet"].trigger()
        (after,) = w.canvas.document.shapes
        assert after.kind == "polygon" and len(after.points) > len(before.points)
        (r0,) = world_rings(before)
        (r1,) = world_rings(after)
        assert area(r1) < area(r0) and Polygon(r0).buffer(1e-6).contains(Polygon(r1))
    finally:
        w.canvas.undo_stack.setClean()
        w.close()
