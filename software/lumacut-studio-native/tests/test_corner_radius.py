"""Eckenradius für Rechtecke (LightBurn *Shape Properties › Corner Radius*): Modell und
Datei, Umriss (abgerundet / nach innen gewölbt, Drehung, Spiegeln, Skalieren), G-Code mit
Kerf / Stegen / Füllung, Knoten bearbeiten, Kombinieren, Boole / Versatz, manuelle Stege,
SVG-Export, xTool-Import, Feld „Ecken“ in der Eigenschaftsleiste."""

from __future__ import annotations

import json
import math
import re

import pytest
from _pi_guard import pi_check

from lumacut_canvas import corners, nodes, pathops, pathsplit, tabs
from lumacut_canvas.commands import AddShapesCommand, SetGeometryCommand
from lumacut_canvas.editor import CanvasEditor
from lumacut_canvas.model import Document, Geometry, Shape, rotate_point
from lumacut_canvas.shape_paths import shape_path, shape_polygons
from lumacut_canvas.toolpath import parse_gcode
from lumacut_canvas.workarea import Rect
from lumacut_job.planner import PlanReport, optimized_document_gcode


def rect(lid="L", x=50.0, y=50.0, w=40.0, h=20.0, rot=0.0, r=0.0):
    return Shape("rect", Geometry(x, y, w, h, rot), lid, corner_radius=r)


def perimeter(w, h, r):
    """Umfang eines Rechtecks mit Eckenradius |r| (Viertelbögen gleich lang, ob innen oder außen)."""
    r = abs(r)
    return 2 * (w + h) - 8 * r + 2 * math.pi * r


def burned(g: str) -> float:
    return parse_gcode(g).cut_length_mm


def box_of(poly):
    xs, ys = [p[0] for p in poly], [p[1] for p in poly]
    return min(xs), min(ys), max(xs), max(ys)


def chord_error(poly, centre, radius, pick):
    """Größter Abstand der Sehnen zum Kreis (Punkte und Sehnenmitten) im Eckbereich ``pick``."""
    err = 0.0
    for a, b in zip(poly, poly[1:]):
        if pick(a) and pick(b):
            for q in (a, b, ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)):
                err = max(err, abs(math.dist(q, centre) - radius))
    return err


@pytest.fixture
def doc(qapp):
    return Document()


@pytest.fixture
def ed(qapp):
    e = CanvasEditor()
    e.resize(1280, 720)
    e.show()
    qapp.processEvents()
    yield e
    e.undo_stack.setClean()
    e.close()


# --- Modell ---------------------------------------------------------------------------

def test_effective_radius_clamps_to_half_the_short_side():
    assert corners.effective_radius(rect(r=5)) == 5
    assert corners.effective_radius(rect(r=50)) == 10             # halbe kürzere Seite
    assert corners.effective_radius(rect(r=-50)) == -10
    assert corners.effective_radius(rect(r=0)) == 0
    assert corners.effective_radius(rect(w=-40, h=-20, r=7)) == 7  # gespiegelt
    assert corners.effective_radius(Shape("ellipse", Geometry(0, 0, 10, 10), "L", corner_radius=3)) == 0
    assert corners.effective_radius(rect(r=float("nan"))) == 0
    assert corners.clamp_radius(rect(), 12.3) == 10 and corners.clamp_radius(rect(), -3.25) == -3.25
    assert corners.clamp_radius(rect(w=1000, h=1000), 999) == corners.RADIUS_LIMIT_MM
    assert corners.clamp_radius(rect(), 1e-9) == 0.0
    assert corners.is_rounded(rect(r=1)) and not corners.is_rounded(rect())


def test_file_round_trip_and_old_files_unchanged(doc):
    lid = doc.active_layer_id
    plain = rect(lid)
    assert "radius" not in plain.to_dict()                        # alte Dateien bleiben gleich
    s = rect(lid, r=4.5)
    d = s.to_dict()
    assert d["radius"] == 4.5
    back = Shape.from_dict(json.loads(json.dumps(d)))
    assert back.corner_radius == 4.5 and back.kind == "rect"
    assert Shape.from_dict({**d, "radius": "kaputt"}).corner_radius == 0.0
    assert Shape.from_dict({**d, "radius": float("inf")}).corner_radius == 0.0
    assert Shape.from_dict({**d, "kind": "ellipse"}).corner_radius == 0.0   # nur Rechtecke
    # Kopien (Duplizieren, Arrays, Einfügen) behalten den Radius
    assert s.copy(new_identity=True).corner_radius == 4.5
    doc.add_shape(s)
    again = Document.from_dict(json.loads(json.dumps(doc.to_dict())))
    assert again.shapes[0].corner_radius == 4.5


# --- Umriss ---------------------------------------------------------------------------

def test_zero_radius_outline_is_the_plain_rectangle():
    (poly,) = shape_polygons(rect())
    assert poly == [(50.0, 50.0), (90.0, 50.0), (90.0, 70.0), (50.0, 70.0), (50.0, 50.0)]


def test_rounded_outline_arcs_box_and_start():
    s = rect(r=5)
    (poly,) = shape_polygons(s)
    assert poly[0] == pytest.approx((55.0, 50.0)) and poly[-1] == pytest.approx(poly[0])
    assert box_of(poly) == pytest.approx((50, 50, 90, 70))
    # jede Ecke ein Viertelkreis (Sehnenfehler ≤ 0,02 mm wie Ellipsen)
    for cx, cy in ((55, 55), (85, 55), (85, 65), (55, 65)):
        err = chord_error(poly, (cx, cy), 5, lambda p, cx=cx, cy=cy: (
            (p[0] - cx) * (cx - 70) >= -1e-9 and (p[1] - cy) * (cy - 60) >= -1e-9))
        assert err <= 0.02
    # die Ecke selbst liegt außerhalb: Abstand der Ecke zum Umriss = r·(√2 − 1)
    d, _q, _k = tabs.nearest_on_rings([poly], (50.0, 50.0))
    assert d == pytest.approx(5 * (math.sqrt(2) - 1), abs=0.02)
    # Uhrzeigersinn (Bildschirm) wie addRect: Fläche mit Vorzeichen > 0 in y-nach-unten
    area2 = sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(poly, poly[1:]))
    assert area2 > 0 and area2 / 2 == pytest.approx(800 - (4 - math.pi) * 25, abs=0.3)


def test_negative_radius_bites_into_the_corners():
    s = rect(r=-6)
    (poly,) = shape_polygons(s)
    assert box_of(poly) == pytest.approx((50, 50, 90, 70))       # Box bleibt die Rechteckbox
    area = abs(sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(poly, poly[1:]))) / 2
    assert area == pytest.approx(800 - math.pi * 36, abs=0.3)     # vier Viertelkreise fehlen
    near = [p for p in poly if math.dist(p, (50, 50)) < 6.5]
    assert near and all(math.dist(p, (50, 50)) == pytest.approx(6, abs=1e-4) for p in near)
    length = sum(math.dist(a, b) for a, b in zip(poly, poly[1:]))
    assert length == pytest.approx(perimeter(40, 20, 6), abs=0.02)


def test_radius_stays_in_mm_when_scaling_and_clamps_when_shrinking():
    s = rect(r=5)
    s.geom = s.geom.mapped(s.geom.bounds(), Rect(50, 50, 120, 60))  # 3-fach
    assert s.corner_radius == 5
    (poly,) = shape_polygons(s)
    length = sum(math.dist(a, b) for a, b in zip(poly, poly[1:]))
    assert length == pytest.approx(perimeter(120, 60, 5), abs=0.02)
    s.geom = s.geom.mapped(s.geom.bounds(), Rect(50, 50, 12, 6))    # kleiner als 2·r
    assert s.corner_radius == 5 and corners.effective_radius(s) == 3
    (poly,) = shape_polygons(s)
    assert box_of(poly) == pytest.approx((50, 50, 62, 56))
    # zurück vergrößert: wieder 5 mm (der gewünschte Radius bleibt gespeichert)
    s.geom = s.geom.mapped(s.geom.bounds(), Rect(50, 50, 40, 20))
    assert corners.effective_radius(s) == 5


def test_rotated_and_mirrored_rounded_rect():
    s = rect(r=5, rot=30)
    (poly,) = shape_polygons(s)
    plain = shape_polygons(rect(r=5))[0]
    rotated = [rotate_point(x, y, 70, 60, 30) for x, y in plain]
    assert len(poly) == len(rotated)
    assert max(math.dist(a, b) for a, b in zip(poly, rotated)) < 1e-6
    m = rect(x=90, y=70, w=-40, h=-20, r=5)                         # gespiegelt (negative Box)
    assert box_of(shape_polygons(m)[0]) == pytest.approx((50, 50, 90, 70))


# --- G-Code ---------------------------------------------------------------------------

def test_gcode_burns_the_rounded_perimeter_and_passes_the_pi_guard(doc):
    lid = doc.active_layer_id
    doc.add_shape(rect(lid, r=5))
    doc.add_shape(rect(lid, y=100, r=-4, rot=15))
    g = optimized_document_gcode(doc, scan_offsets=None)
    assert burned(g) == pytest.approx(perimeter(40, 20, 5) + perimeter(40, 20, 4), abs=0.05)
    assert not re.search(r"^G[23]\b", g, re.M)                  # Bögen als G1-Geraden
    pi_check(g)
    # Radius 0: dieselbe Ausgabe wie ein Rechteck ohne Eigenschaft
    sharp = Document()
    sharp.add_shape(rect(sharp.active_layer_id))
    zero = Document()
    zero.add_shape(rect(zero.active_layer_id, r=0.0))
    for d in (sharp, zero):
        d.layers[0].id = "same"
        d.shapes[0].layer_id = "same"
        d.shapes[0].id = "s"
    assert optimized_document_gcode(sharp, scan_offsets=None) == optimized_document_gcode(zero, scan_offsets=None)


def test_kerf_and_automatic_tabs_on_a_rounded_rect(doc):
    lid = doc.active_layer_id
    doc.update_layer(lid, kerf_mm=0.2, tab_count=4, tab_width_mm=1.5)
    doc.add_shape(rect(lid, r=5))
    g = optimized_document_gcode(doc, scan_offsets=None)
    # Kerf 0,2 mm nach außen: Radius 5,2 mm, Seiten je +0,4 mm
    per = 2 * (40.4 + 20.4) - 8 * 5.2 + 2 * math.pi * 5.2
    assert burned(g) == pytest.approx(per - 4 * 1.5, abs=0.05)
    pi_check(g)


def test_fill_follows_the_rounded_corners(doc):
    lid = doc.active_layer_id
    doc.update_layer(lid, fill_mode="hatch", hatch_outline=False, line_interval_mm=0.5)
    doc.add_shape(rect(lid))
    sharp = burned(optimized_document_gcode(doc, scan_offsets=None))
    doc.shapes[0].corner_radius = 8
    rounded = burned(optimized_document_gcode(doc, scan_offsets=None))
    # weniger Fläche: (4 − π)·r² ≈ 54,9 mm² → ≈ 110 mm weniger Füllweg bei 0,5 mm
    assert sharp - rounded == pytest.approx((4 - math.pi) * 64 / 0.5, rel=0.05)


def test_estimate_plans_the_rounded_outline(doc):
    from lumacut_job.estimate import estimate_gcode
    lid = doc.active_layer_id
    doc.add_shape(rect(lid))
    sharp = estimate_gcode(optimized_document_gcode(doc, scan_offsets=None))
    doc.shapes[0].corner_radius = 5
    est = estimate_gcode(optimized_document_gcode(doc, scan_offsets=None))
    assert est.cut_length_mm == pytest.approx(perimeter(40, 20, 5), abs=0.05)
    assert est.cut_length_mm < sharp.cut_length_mm and est.moves > sharp.moves


# --- Pfad-Operationen -----------------------------------------------------------------

def test_node_edit_converts_to_polygon_with_the_same_outline():
    s = tabs.with_tab_points(rect(r=5, rot=20), [])
    ring = tabs.closed_rings(s)[0]
    mid = ((ring[1][0] + ring[2][0]) / 2, (ring[1][1] + ring[2][1]) / 2)
    s = tabs.with_tab_points(s, [mid])
    poly = nodes.to_editable(s)
    assert poly.kind == "polygon" and poly.corner_radius == 0 and poly.geom.rot == 20
    assert 8 < len(poly.points) < 200
    a, b = shape_polygons(s)[0], shape_polygons(poly)[0]
    assert max(tabs.nearest_on_rings([b], p)[0] for p in a) < 0.03
    assert poly.tab_points() == pytest.approx(s.tab_points())    # Stege bleiben am Umriss
    assert "radius" not in poly.to_dict()
    sharp = nodes.to_editable(rect())
    assert sharp.points == ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0))


def test_combine_keeps_the_rounded_corners():
    a, b = rect(r=5), rect(x=120, r=-3, rot=10)
    res = pathsplit.combine([a, b])
    ((ids, out),) = res.groups
    assert ids == [a.id, b.id] and out.kind == "polygon" and len(out.ring_ranges()) == 2
    polys = shape_polygons(out)
    for src, got in zip((a, b), polys):
        want = shape_polygons(src)[0]
        assert max(tabs.nearest_on_rings([got], p)[0] for p in want) < 0.03
    assert res.overlaps == 0


def test_boolean_and_offset_use_the_rounded_outline(qapp):
    s = rect(r=5)
    assert pathops.shape_area(s).area == pytest.approx(800 - (4 - math.pi) * 25, abs=0.05)
    (grown,) = pathops.offset([s], 1.0)
    assert pathops.shape_area(grown).area == pytest.approx(42 * 22 - (4 - math.pi) * 36, abs=0.2)
    cut = pathops.boolean([s, rect(x=70, y=40, w=40, h=40)], "subtract")
    assert len(cut) == 1 and pathops.shape_area(cut[0]).area == pytest.approx(
        20 * 20 - (4 - math.pi) * 25 / 2, abs=0.1)


def test_manual_tabs_follow_a_radius_change():
    s = tabs.with_tab_points(rect(), [(50.0, 50.0), (70.0, 50.0)])   # Ecke und Kantenmitte
    r = corners.with_corner_radius(s, 8)
    assert r.corner_radius == 8 and len(r.tabs) == 2
    pts = r.tab_points()
    assert pts[1] == pytest.approx((70.0, 50.0))
    ring = tabs.closed_rings(r)[0]
    assert all(tabs.nearest_on_rings([ring], p)[0] < 1e-6 for p in pts)  # Ecke → auf dem Bogen
    assert math.dist(pts[0], (58, 58)) == pytest.approx(8, abs=0.02)
    with pytest.raises(ValueError):
        corners.with_corner_radius(Shape("ellipse", Geometry(0, 0, 5, 5), "L"), 1)


def test_svg_export_has_true_curves(doc, tmp_path):
    from lumacut_canvas.export import export_svg
    doc.add_shape(rect(doc.active_layer_id, r=5))
    out = tmp_path / "r.svg"
    export_svg(doc, out)
    text = out.read_text(encoding="utf-8")
    (d,) = re.findall(r'<path[^>]* d="([^"]+)"', text)
    assert d.startswith("M55,50 L85,50 C") and d.count("C") == 8     # 2 Bézierbögen je Ecke
    assert shape_path(doc.shapes[0]).elementCount() > 10


def test_xtool_rounded_rect_imports_as_rect_and_scales_when_fitted(qapp):
    from lumacut_import.placement import place_shapes
    big = rect(x=0, y=0, w=720, h=40, r=10)                       # doppelt so breit wie die Fläche
    (placed,), s = place_shapes([big])
    assert s == pytest.approx(0.5) and placed.corner_radius == pytest.approx(5)
    assert placed.geom.w == pytest.approx(360)


# --- Eigenschaftsleiste -----------------------------------------------------------------

def _add(ed, shapes):
    ed.undo_stack.push(AddShapesCommand(ed.document, shapes))
    return shapes


def test_field_only_for_rectangles(ed, qapp):
    lid = ed.document.active_layer_id
    a, b = _add(ed, [rect(lid), rect(lid, y=100)])
    (e,) = _add(ed, [Shape("ellipse", Geometry(150, 50, 20, 20), lid)])
    cc = ed.property_bar.corner_controls
    ed.set_selection([a.id])
    qapp.processEvents()
    assert cc.isVisible() and cc.radius.value() == 0
    ed.set_selection([a.id, b.id])
    assert cc.isVisible()
    ed.set_selection([a.id, e.id])
    assert not cc.isVisible()
    ed.set_selection([e.id])
    assert not cc.isVisible()
    ed.set_selection([])
    assert not cc.isVisible()
    assert "LightBurn" in cc.radius.toolTip() and cc.radius.minimum() < 0


def test_field_sets_radius_with_one_undo_step(ed, qapp):
    lid = ed.document.active_layer_id
    a, b = _add(ed, [rect(lid), rect(lid, y=100, w=10, h=6)])
    msgs = []
    ed.statusMessage.connect(msgs.append)
    ed.set_selection([a.id, b.id])
    n = ed.undo_stack.count()
    ed.property_bar.corner_controls.radius.setValue(4.0)
    assert ed.undo_stack.count() == n + 1
    doc = ed.document
    assert doc.shape(a.id).corner_radius == 4 and doc.shape(b.id).corner_radius == 3   # begrenzt
    assert "Eckenradius 3 … 4 mm" in msgs[-1] and "2 Rechtecke" in msgs[-1]
    assert "begrenzt" in msgs[-1]
    item = ed.scene.items_by_id[a.id]
    assert item._path.elementCount() > 10                         # Canvas zeigt die Bögen
    ed.undo_stack.undo()
    assert doc.shape(a.id).corner_radius == 0 and doc.shape(b.id).corner_radius == 0
    assert ed.scene.items_by_id[a.id]._path.elementCount() == 5
    ed.undo_stack.redo()
    assert doc.shape(a.id).corner_radius == 4
    # Auswahl und Stapelreihenfolge bleiben
    assert [s.id for s in doc.shapes] == [a.id, b.id] and set(ed.selection) == {a.id, b.id}


def test_negative_radius_and_scaling_in_the_property_bar(ed, qapp):
    lid = ed.document.active_layer_id
    (a,) = _add(ed, [rect(lid)])
    msgs = []
    ed.statusMessage.connect(msgs.append)
    ed.set_selection([a.id])
    pb = ed.property_bar
    pb.corner_controls.radius.setValue(-5.0)
    assert ed.document.shape(a.id).corner_radius == -5 and "nach innen gewölbt" in msgs[-1]
    pb.ratio.setChecked(False)
    pb.w.setValue(80.0)                                            # Breite ändern: Radius bleibt
    s = ed.document.shape(a.id)
    assert abs(s.geom.w) == pytest.approx(80) and s.corner_radius == -5
    assert pb.corner_controls.radius.value() == pytest.approx(-5)


def test_locked_layer_hides_the_field(ed, qapp):
    lid = ed.document.active_layer_id
    (a,) = _add(ed, [rect(lid)])
    ed.set_selection([a.id])
    ed.document.update_layer(lid, locked=True)
    ed.property_bar.refresh()
    assert not ed.property_bar.corner_controls.isVisible()
    assert ed.property_bar.corner_controls.apply(5.0) == []


def test_editor_save_load_and_touch_mode(ed, qapp, tmp_path):
    lid = ed.document.active_layer_id
    (a,) = _add(ed, [rect(lid, r=6)])
    path = ed.save_file(tmp_path / "ecken.lcs")
    ed.undo_stack.setClean()
    ed.load_file(path)
    (s,) = ed.document.shapes
    assert s.corner_radius == 6
    ed.set_selection([s.id])
    ed.set_touch_mode(True, persist=False)
    qapp.processEvents()
    spin = ed.property_bar.corner_controls.radius
    assert spin.isVisible() and spin.height() >= 34
    ed.set_touch_mode(False, persist=False)
