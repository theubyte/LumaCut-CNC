"""Vieleck / Stern (LightBurn *Polygon*-Werkzeug, xTool „Polygon“ / „Stern“): Umriss,
Modell und Datei, Erkennung nach Bearbeitungen, Seiten / Innenradius ändern, G-Code mit
Kerf / Stegen / Füllung, Boole / Versatz, Knoten / Vereinfachen / Kombinieren, Werkzeug
(Ziehen vom Mittelpunkt, Umschalt dreht, Tippen, Arbeitsfläche, gesperrte Ebene) und
Felder „Seiten“ / „Stern“ / „Innen“ in der Eigenschaftsleiste."""

from __future__ import annotations

import json
import math
import re

import pytest
from _pi_guard import pi_check
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QKeyEvent

from lumacut_canvas import ngon, nodes, pathops, pathsimplify, pathsplit, tabs
from lumacut_canvas.commands import AddShapesCommand, SetGeometryCommand
from lumacut_canvas.editor import CanvasEditor
from lumacut_canvas.model import Document, Geometry, Shape
from lumacut_canvas.shape_paths import shape_polygons
from lumacut_canvas.toolpath import parse_gcode
from lumacut_canvas.tools import TOOL_LABELS, TOOL_SHORTCUTS, Tool
from lumacut_canvas.workarea import WORK_HEIGHT_MM, WORK_WIDTH_MM
from lumacut_job.planner import optimized_document_gcode

NO = Qt.NoModifier
SHIFT = Qt.ShiftModifier


def burned(g: str) -> float:
    return parse_gcode(g).cut_length_mm


def polygon_perimeter(n, radius):
    return 2 * n * radius * math.sin(math.pi / n)


def star_perimeter(n, radius, inner):
    return 2 * n * radius * math.sqrt(1 + inner ** 2 - 2 * inner * math.cos(math.pi / n))


def polygon_area(n, radius):
    return n / 2 * radius ** 2 * math.sin(2 * math.pi / n)


def star_area(n, radius, inner):
    return n * radius * radius * inner * math.sin(math.pi / n)


def outline(shape):
    (poly,) = shape_polygons(shape)
    return poly[:-1] if poly[0] == poly[-1] else poly


def signed_area(pts):
    return sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(pts, pts[1:] + pts[:1])) / 2


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


# --- Umriss ---------------------------------------------------------------------------

def test_normalize_clamps_sides_and_inner_radius():
    assert ngon.normalize(6, 0) == (6, 0.0)
    assert ngon.normalize(2, 0) == (3, 0.0) and ngon.normalize(1000, 0) == (ngon.MAX_SIDES, 0.0)
    assert ngon.normalize(5.4, 0.5) == (5, 0.5)
    assert ngon.normalize(5, 0.01) == (5, ngon.INNER_MIN) and ngon.normalize(5, 2) == (5, ngon.INNER_MAX)
    assert ngon.normalize(5, -1) == (5, 0.0) and ngon.normalize(5, float("nan")) == (5, 0.0)
    assert ngon.normalize("x", None) == (ngon.DEFAULT_SIDES, 0.0)
    assert not ngon.is_star((5, 0.0)) and ngon.is_star((5, 0.4)) and not ngon.is_star(None)


@pytest.mark.parametrize("n", [3, 4, 5, 6, 8, 12, 100])
def test_regular_polygon_outline(n):
    pts = ngon.unit_outline(n)
    assert len(pts) == n and pts[0] == pytest.approx((0, -1))        # erste Spitze oben
    assert all(math.hypot(*p) == pytest.approx(1) for p in pts)
    sides = [math.dist(a, b) for a, b in zip(pts, pts[1:] + pts[:1])]
    assert max(sides) - min(sides) < 1e-9
    assert sides[0] == pytest.approx(2 * math.sin(math.pi / n))
    assert signed_area(pts) > 0                                       # im Uhrzeigersinn (Y unten)
    assert abs(signed_area(pts)) == pytest.approx(polygon_area(n, 1))


def test_star_outline_alternates_outer_and_inner_points():
    pts = ngon.unit_outline(5, 0.4)
    assert len(pts) == 10
    radii = [math.hypot(*p) for p in pts]
    assert radii[0::2] == pytest.approx([1] * 5) and radii[1::2] == pytest.approx([0.4] * 5)
    # Innenecke genau zwischen zwei Spitzen
    assert math.degrees(math.atan2(pts[1][0], -pts[1][1])) == pytest.approx(36)
    assert abs(signed_area(pts)) == pytest.approx(star_area(5, 1, 0.4))


def test_make_shape_centre_radius_and_box():
    hexagon = ngon.make_shape("L", 100, 80, 20)                        # Standard: Sechseck
    assert hexagon.kind == "polygon" and hexagon.regular == (6, 0.0)
    assert hexagon.geom.as_tuple() == pytest.approx((100 - 10 * math.sqrt(3), 60, 20 * math.sqrt(3), 40))
    assert ngon.centre_of(hexagon) == pytest.approx((100, 80))
    assert ngon.outer_radius(hexagon) == pytest.approx(20)
    pentagon = ngon.make_shape("L", 50, 50, 10, 5)
    b = pentagon.geom
    assert b.y == pytest.approx(40) and b.y + b.h == pytest.approx(50 + 10 * math.cos(math.pi / 5))
    assert ngon.centre_of(pentagon) == pytest.approx((50, 50))
    assert all(math.dist(p, (50, 50)) == pytest.approx(10) for p in outline(pentagon))
    rotated = ngon.make_shape("L", 50, 50, 10, 5, rot=90)
    assert ngon.centre_of(rotated) == pytest.approx((50, 50))
    pts = outline(rotated)
    assert all(math.dist(p, (50, 50)) == pytest.approx(10) for p in pts)
    assert pts[0] == pytest.approx((60, 50))                            # Spitze nach rechts


# --- Modell und Datei --------------------------------------------------------------------

def test_file_round_trip_and_old_polygons_unchanged(doc):
    lid = doc.active_layer_id
    plain = Shape.from_points("polygon", [(0, 0), (10, 0), (5, 8)], lid)
    assert "regular" not in plain.to_dict()                           # alte Dateien bleiben gleich
    s = ngon.make_shape(lid, 50, 50, 10, 5, 0.38)
    d = s.to_dict()
    assert d["regular"] == {"sides": 5, "inner": 0.38}
    back = Shape.from_dict(json.loads(json.dumps(d)))
    assert back.regular == (5, 0.38) and ngon.spec_of(back) == (5, 0.38)
    assert max(math.dist(p, q) for p, q in zip(outline(back), outline(s))) < 1e-4
    for bad in ({"sides": "x"}, {"sides": 2}, {"sides": 101}, {"sides": 5, "inner": 1.5},
                {"sides": 5, "inner": float("nan")}, "kaputt", None):
        assert Shape.from_dict({**d, "regular": bad}).regular == ()
    assert Shape.from_dict({**d, "kind": "path"}).regular == ()        # nur Polygone
    assert s.copy(new_identity=True).regular == (5, 0.38)
    doc.add_shape(s)
    again = Document.from_dict(json.loads(json.dumps(doc.to_dict())))
    assert ngon.spec_of(again.shapes[0]) == (5, 0.38)


def test_spec_survives_move_scale_rotate_but_not_point_edits():
    s = ngon.make_shape("L", 100, 100, 20, 7)
    moved = Shape(**{**s.__dict__, "geom": s.geom.translated(30, -10)})
    assert ngon.spec_of(moved) == (7, 0.0)
    stretched = Shape(**{**s.__dict__, "geom": Geometry(s.geom.x, s.geom.y, s.geom.w * 2, s.geom.h, 33)})
    assert ngon.spec_of(stretched) == (7, 0.0)
    # waagerecht gespiegelte Punktreihenfolge: dasselbe symmetrische Vieleck
    mirrored = Shape(**{**s.__dict__, "points": tuple((1 - u, v) for u, v in reversed(s.points))})
    assert ngon.spec_of(mirrored) == (7, 0.0)
    flipped = Shape(**{**s.__dict__, "points": tuple((u, 1 - v) for u, v in s.points)})
    assert ngon.spec_of(flipped) is None                              # Spitze unten: kein Vieleck mehr
    moved_node = nodes.move_node(s, 0, (100, 70))
    assert moved_node.regular and ngon.spec_of(moved_node) is None
    assert ngon.spec_of(Shape(**{**s.__dict__, "curves": (0,)})) is None
    assert ngon.spec_of(Shape(**{**s.__dict__, "regular": (8, 0.0)})) is None
    assert ngon.spec_of(Shape.from_points("polygon", [(0, 0), (10, 0), (5, 8)], "L")) is None
    assert ngon.spec_of(Shape("rect", Geometry(0, 0, 5, 5), "L")) is None
    assert ngon.with_spec(moved_node, 5) is moved_node                # kein Vieleck: unverändert


def test_with_spec_keeps_centre_rotation_radius_and_stretch():
    s = ngon.make_shape("L", 100, 100, 20, 6, rot=20)
    p = ngon.with_spec(s, 5)
    assert p.id == s.id and p.regular == (5, 0.0) and p.geom.rot == 20
    assert ngon.centre_of(p) == pytest.approx((100, 100))
    assert all(math.dist(q, (100, 100)) == pytest.approx(20) for q in outline(p))
    star = ngon.with_spec(p, inner=0.5)
    assert star.regular == (5, 0.5) and len(star.points) == 10
    radii = sorted(round(math.dist(q, (100, 100)), 6) for q in outline(star))
    assert radii[0] == pytest.approx(10) and radii[-1] == pytest.approx(20)
    assert ngon.with_spec(star, inner=0).regular == (5, 0.0)
    assert ngon.with_spec(s, 6, 0.0) is s                             # unverändert
    # gestreckt (Breite × 2): Maßstab je Achse bleibt
    g = s.geom
    wide = Shape(**{**ngon.make_shape("L", 100, 100, 20, 6).__dict__,
                    "geom": Geometry(g.x - 20, 80, 2 * 20 * math.sqrt(3), 40)})
    eight = ngon.with_spec(wide, 8)
    _, _, w8, h8 = ngon.unit_box(8)
    assert eight.geom.w == pytest.approx(40 * w8) and eight.geom.h == pytest.approx(20 * h8)
    assert ngon.centre_of(eight) == pytest.approx(ngon.centre_of(wide))


def test_with_spec_drops_manual_tabs():
    s = ngon.make_shape("L", 100, 100, 20, 6)
    ring = tabs.closed_rings(s)[0]
    mid = ((ring[0][0] + ring[1][0]) / 2, (ring[0][1] + ring[1][1]) / 2)
    s = tabs.with_tab_points(s, [mid])
    assert len(s.tabs) == 1 and ngon.spec_of(s) == (6, 0.0)
    assert ngon.with_spec(s, 5).tabs == ()


def test_describe_and_label():
    a = ngon.make_shape("L", 50, 50, 10, 6)
    b = ngon.make_shape("L", 90, 50, 10, 5, 0.4)
    assert ngon.describe([a]) == "Vieleck 6 Ecken"
    assert ngon.describe([b]) == "Stern 5 Zacken · innen 40 %"
    assert ngon.describe([a, b]) == "Vieleck 6 Ecken … · 2 Objekte"
    assert ngon.describe([Shape("rect", Geometry(0, 0, 1, 1), "L")]) == ""


# --- G-Code und Pfad-Operationen ---------------------------------------------------------

def test_gcode_burns_the_polygon_and_star_perimeter_g1_only(doc):
    lid = doc.active_layer_id
    doc.add_shape(ngon.make_shape(lid, 60, 60, 20, 6))
    doc.add_shape(ngon.make_shape(lid, 150, 60, 25, 5, 0.38, rot=15))
    g = optimized_document_gcode(doc, scan_offsets=None)
    assert burned(g) == pytest.approx(polygon_perimeter(6, 20) + star_perimeter(5, 25, 0.38), abs=0.05)
    assert not re.search(r"^G[23]\b", g, re.M)
    pi_check(g)


def test_regular_field_does_not_change_the_gcode(doc):
    lid = doc.active_layer_id
    s = ngon.make_shape(lid, 60, 60, 20, 8)
    doc.add_shape(s)
    with_field = optimized_document_gcode(doc, scan_offsets=None)
    doc.shapes[0] = Shape(**{**s.__dict__, "regular": ()})
    assert optimized_document_gcode(doc, scan_offsets=None) == with_field


def test_kerf_tabs_and_fill_on_a_star(doc):
    lid = doc.active_layer_id
    doc.update_layer(lid, kerf_mm=0.1, tab_count=4, tab_width_mm=1.0)
    doc.add_shape(ngon.make_shape(lid, 100, 100, 30, 5, 0.5))
    g = optimized_document_gcode(doc, scan_offsets=None)
    pi_check(g)
    plain = star_perimeter(5, 30, 0.5)
    assert plain < burned(g) + 4 * 1.0 < plain + 2.0                # Kerf außen, 4 Stege fehlen
    fill = Document()
    fl = fill.active_layer_id
    fill.update_layer(fl, fill_mode="hatch", hatch_outline=False, line_interval_mm=0.5)
    fill.add_shape(ngon.make_shape(fl, 100, 100, 30, 5, 0.5))
    hatched = burned(optimized_document_gcode(fill, scan_offsets=None))
    assert hatched == pytest.approx(star_area(5, 30, 0.5) / 0.5, rel=0.05)


def test_boolean_offset_and_area(qapp):
    hexagon = ngon.make_shape("L", 100, 100, 20, 6)
    assert pathops.shape_area(hexagon).area == pytest.approx(polygon_area(6, 20), rel=1e-6)
    star = ngon.make_shape("L", 100, 100, 20, 5, 0.4)
    assert pathops.shape_area(star).area == pytest.approx(star_area(5, 20, 0.4), rel=1e-6)
    (grown,) = pathops.offset([hexagon], 1.0)
    assert grown.regular == () or ngon.spec_of(grown) is None
    assert pathops.shape_area(grown).area > polygon_area(6, 20)
    cut = pathops.boolean([hexagon, ngon.make_shape("L", 100, 100, 5, 4)], "subtract")
    assert len(cut) == 1 and ngon.spec_of(cut[0]) is None
    assert pathops.shape_area(cut[0]).area == pytest.approx(polygon_area(6, 20) - polygon_area(4, 5), rel=1e-6)


def test_simplify_and_combine_give_plain_polygons():
    circle_like = ngon.make_shape("L", 100, 100, 40, 100)
    simple = pathsimplify.simplify_shape(circle_like, 0.5)
    assert simple is not None and len(simple.points) < 100 and ngon.spec_of(simple) is None
    res = pathsplit.combine([ngon.make_shape("L", 50, 50, 10, 6), ngon.make_shape("L", 100, 50, 10, 5, 0.4)])
    ((_, out),) = res.groups
    assert len(out.ring_ranges()) == 2 and ngon.spec_of(out) is None


def test_svg_export_of_a_star(doc, tmp_path):
    from lumacut_canvas.export import export_svg
    doc.add_shape(ngon.make_shape(doc.active_layer_id, 50, 50, 10, 5, 0.4))
    out = tmp_path / "s.svg"
    export_svg(doc, out)
    text = out.read_text(encoding="utf-8")
    assert len(re.findall(r"<(?:path|polygon)\b", text)) == 1


# --- Werkzeug --------------------------------------------------------------------------

def drag(ed, a, b, mods=NO):
    ed.tools.press(QPointF(*a), mods)
    ed.tools.move(QPointF((a[0] + b[0]) / 2, (a[1] + b[1]) / 2), mods, True)
    ed.tools.move(QPointF(*b), mods, True)
    ed.tools.release(QPointF(*b), mods)


def test_tool_action_shortcut_icon_and_strip(ed):
    a = ed.actions_by_name["tool_ngon"]
    assert TOOL_SHORTCUTS[Tool.NGON] == "S" and a.shortcut().toString() == "S"
    assert TOOL_LABELS[Tool.NGON] == "Vieleck / Stern"
    assert a in ed.tool_strip.actions() and a.isCheckable() and not a.icon().isNull()
    strip = ed.tool_strip.actions()
    assert strip.index(a) == strip.index(ed.actions_by_name["tool_polygon"]) + 1
    msgs = []
    ed.statusMessage.connect(msgs.append)
    a.trigger()
    assert ed.tools.tool == Tool.NGON and "vom Mittelpunkt aus ziehen" in msgs[-1]
    ed.tools.press(QPointF(100, 100), NO)
    ed.tools.move(QPointF(100, 80), NO, True)
    assert msgs[-1] == "Vieleck 6 Ecken · Radius 20.0 mm"
    ed.tools.release(QPointF(100, 80), NO)


def test_drag_from_the_centre_draws_a_hexagon_one_undo_step(ed):
    ed.set_tool(Tool.NGON)
    d = ed.document
    ed.tools.press(QPointF(100.2, 99.8), NO)
    ed.tools.move(QPointF(100, 85), NO, True)
    assert len(d.shapes) == 1 and ed.undo_stack.count() == 0          # Vorschau, kein Undo-Schritt
    ed.tools.move(QPointF(100, 70), NO, True)
    ed.tools.release(QPointF(100, 70), NO)
    (s,) = d.shapes
    assert ed.undo_stack.count() == 1 and ed.selection == [s.id]
    assert ngon.spec_of(s) == (6, 0.0) and s.geom.rot == 0
    assert ngon.centre_of(s) == pytest.approx((100, 100))              # Raster 1 mm
    assert ngon.outer_radius(s) == pytest.approx(30)
    assert ed.property_bar.title.text() == "Vieleck"
    ed.undo_stack.undo()
    assert d.shapes == []
    ed.undo_stack.redo()
    assert ngon.spec_of(d.shapes[0]) == (6, 0.0)


def test_shift_turns_the_first_point_towards_the_mouse(ed):
    ed.set_tool(Tool.NGON)
    drag(ed, (100, 100), (130, 101), SHIFT)                           # fast waagerecht → 90°
    (s,) = ed.document.shapes
    assert s.geom.rot == pytest.approx(90)
    assert outline(s)[0] == pytest.approx((100 + ngon.outer_radius(s), 100))
    assert ngon.centre_of(s) == pytest.approx((100, 100))


def test_click_places_20mm_and_stays_inside_the_work_area(ed):
    ed.set_tool(Tool.NGON)
    ed.tools.press(QPointF(60, 60), NO)
    ed.tools.release(QPointF(60, 60), NO)
    (s,) = ed.document.shapes
    assert ngon.centre_of(s) == pytest.approx((60, 60)) and ngon.outer_radius(s) == pytest.approx(10)
    assert ed.undo_stack.count() == 1
    drag(ed, (2, 2), (40, 40))                                        # Mittelpunkt am Rand
    b = ed.document.shapes[-1].bounds()
    assert b.x >= -1e-6 and b.y >= -1e-6
    assert b.x + b.w <= WORK_WIDTH_MM + 1e-6 and b.y + b.h <= WORK_HEIGHT_MM + 1e-6
    assert ngon.spec_of(ed.document.shapes[-1]) == (6, 0.0)


def test_escape_cancels_and_locked_layer_refuses(ed):
    ed.set_tool(Tool.NGON)
    ed.tools.press(QPointF(100, 100), NO)
    ed.tools.move(QPointF(120, 100), NO, True)
    assert len(ed.document.shapes) == 1
    ed.tools.key_press(QKeyEvent(QEvent.KeyPress, Qt.Key_Escape, NO))
    ed.tools.release(QPointF(120, 100), NO)
    assert ed.document.shapes == [] and ed.undo_stack.count() == 0
    ed.document.update_layer(ed.document.active_layer_id, locked=True)
    drag(ed, (100, 100), (120, 100))
    assert ed.document.shapes == []


def test_tool_uses_the_spec_from_the_property_bar(ed):
    ed.set_tool(Tool.NGON)
    bar = ed.property_bar.ngon_controls
    assert bar.isVisible() and not bar.inner.isEnabled()              # ohne Auswahl: Vorgabe
    bar.sides.setValue(5)
    bar.star.setChecked(True)
    bar.inner.setValue(38)
    assert ed.tools.ngon_spec == (5, 0.38) and ed.undo_stack.count() == 0
    drag(ed, (100, 100), (100, 75))
    (s,) = ed.document.shapes
    assert ngon.spec_of(s) == (5, 0.38) and ed.property_bar.title.text() == "Stern"
    ed.set_tool(Tool.SELECT)
    ed.set_selection([])
    assert not bar.isVisible()


# --- Eigenschaftsleiste ----------------------------------------------------------------

def _add(ed, shapes):
    ed.undo_stack.push(AddShapesCommand(ed.document, shapes))
    return shapes


def test_fields_only_for_regular_polygons(ed, qapp):
    lid = ed.document.active_layer_id
    a, b, plain, r = _add(ed, [ngon.make_shape(lid, 60, 60, 15, 6), ngon.make_shape(lid, 120, 60, 15, 5, 0.4),
                               Shape.from_points("polygon", [(0, 0), (10, 0), (5, 8)], lid),
                               Shape("rect", Geometry(200, 50, 20, 10), lid)])
    bar = ed.property_bar.ngon_controls
    ed.set_selection([a.id])
    assert bar.isVisible() and bar.sides.value() == 6 and not bar.star.isChecked()
    ed.set_selection([b.id])
    assert bar.star.isChecked() and bar.inner.value() == 40 and bar.inner.isEnabled()
    ed.set_selection([a.id, b.id])
    assert bar.isVisible()
    for sel in ([plain.id], [r.id], [a.id, plain.id]):
        ed.set_selection(sel)
        assert not bar.isVisible()
    ed.set_selection([a.id])
    ed.document.update_layer(lid, locked=True)
    ed.property_bar.refresh()
    assert not bar.isVisible() and bar.apply(sides=5) == []


def test_sides_star_and_inner_are_undo_steps_keeping_the_centre(ed, qapp):
    lid = ed.document.active_layer_id
    (a,) = _add(ed, [ngon.make_shape(lid, 100, 100, 20, 6, rot=10)])
    ed.set_selection([a.id])
    bar = ed.property_bar.ngon_controls
    msgs = []
    ed.statusMessage.connect(msgs.append)
    n0 = ed.undo_stack.count()
    bar.sides.setValue(8)
    s = ed.document.shape(a.id)
    assert ngon.spec_of(s) == (8, 0.0) and ed.undo_stack.count() == n0 + 1
    assert ngon.centre_of(s) == pytest.approx((100, 100)) and s.geom.rot == 10
    assert ed.selection == [a.id]
    bar.star.setChecked(True)
    assert ngon.spec_of(ed.document.shape(a.id)) == (8, 0.5) and ed.undo_stack.count() == n0 + 2
    assert ed.property_bar.title.text() == "Stern"
    bar.inner.setValue(30)
    assert ngon.spec_of(ed.document.shape(a.id)) == (8, 0.3)
    assert msgs[-1] == "Stern 8 Zacken · innen 30 %"
    ed.undo_stack.undo()
    ed.undo_stack.undo()
    assert ngon.spec_of(ed.document.shape(a.id)) == (8, 0.0)
    assert bar.sides.value() == 8 and not bar.star.isChecked()
    ed.undo_stack.undo()
    assert ngon.spec_of(ed.document.shape(a.id)) == (6, 0.0)
    ed.undo_stack.redo()
    assert ngon.spec_of(ed.document.shape(a.id)) == (8, 0.0)


def test_multi_selection_changes_only_the_edited_value(ed, qapp):
    lid = ed.document.active_layer_id
    a, b = _add(ed, [ngon.make_shape(lid, 60, 60, 15, 6), ngon.make_shape(lid, 120, 60, 15, 5, 0.4)])
    ed.set_selection([a.id, b.id])
    n0 = ed.undo_stack.count()
    new = ed.property_bar.ngon_controls.apply(sides=7)
    assert len(new) == 2 and ed.undo_stack.count() == n0 + 1         # ein Makro
    assert ngon.spec_of(ed.document.shape(a.id)) == (7, 0.0)
    assert ngon.spec_of(ed.document.shape(b.id)) == (7, 0.4)          # Stern bleibt Stern
    assert ed.property_bar.ngon_controls.apply(sides=7) == []          # nichts zu tun
    ed.undo_stack.undo()
    assert ngon.spec_of(ed.document.shape(a.id)) == (6, 0.0)
    assert ngon.spec_of(ed.document.shape(b.id)) == (5, 0.4)


def test_scaled_polygon_keeps_its_fields(ed, qapp):
    lid = ed.document.active_layer_id
    (a,) = _add(ed, [ngon.make_shape(lid, 100, 100, 20, 6)])
    g = a.geom
    ed.undo_stack.push(SetGeometryCommand(ed.document, {a.id: g.copy()},
                                          {a.id: Geometry(g.x, g.y, g.w * 1.5, g.h * 1.5)}, "Skalieren"))
    ed.set_selection([a.id])
    bar = ed.property_bar.ngon_controls
    assert bar.isVisible()
    bar.sides.setValue(4)
    s = ed.document.shape(a.id)
    assert ngon.outer_radius(s) == pytest.approx(30)


def test_editor_save_load_and_touch_mode(ed, qapp, tmp_path):
    lid = ed.document.active_layer_id
    _add(ed, [ngon.make_shape(lid, 100, 100, 20, 5, 0.38)])
    path = ed.save_file(tmp_path / "stern.lcs")
    ed.undo_stack.setClean()
    ed.load_file(path)
    (s,) = ed.document.shapes
    assert ngon.spec_of(s) == (5, 0.38)
    ed.set_selection([s.id])
    ed.set_touch_mode(True, persist=False)
    qapp.processEvents()
    bar = ed.property_bar.ngon_controls
    assert bar.sides.isVisible() and bar.sides.height() >= 34 and bar.inner.height() >= 34
    assert bar.star.height() >= 40
    ed.set_touch_mode(False, persist=False)
