"""Verzerren (LightBurn *Warp Selection* / *Deform*, xTool „Verzerren“): Hülle (bilinear)
mit Wölbung, Perspektive (Geraden bleiben gerade), adaptive Unterteilung mit Fehlergrenze,
alle Formarten (Rechteck, Ellipse, Polygon mit Löchern, Linie, Freihand mit Kurven,
gedrehte Objekte, Umriss- und Einlinien-Text), Stege / Startpunkt / Ebene / Gruppen /
Priorität / Richtung, abgelehnte Vierecke (überschlagen, gespiegelt, konkav, zu starke
Wölbung, flache Auswahl, NaN), Bilder unverändert, Arbeitsfläche, G-Code mit Pi-Wächter,
Dialog (Vorschau mit ziehbaren Ecken, Schnellwahl, Touch), Editor (ein Undo-Schritt,
Stapel, Auswahl, gesperrte Ebene, Abbrechen), Menüs, Speichern / Laden, Hauptfenster."""

from __future__ import annotations

import math
import re

import pytest
from PySide6.QtGui import QColor, QImage
from shapely.geometry import LineString, Point, Polygon

from _pi_guard import pi_check
from lumacut_canvas import tabs, warp
from lumacut_canvas.commands import AddShapesCommand
from lumacut_canvas.editor import CanvasEditor
from lumacut_canvas.linefont import LINE_FONT_SANS
from lumacut_canvas.model import Document, Geometry, ImageSettings, RasterImage, Shape
from lumacut_canvas.shape_paths import shape_polygons, text_aspect
from lumacut_canvas.startpoint import with_start
from lumacut_canvas.toolpath import parse_gcode
from lumacut_canvas.workarea import Rect
from lumacut_import.image import grayscale_png
from lumacut_job.planner import optimized_document_gcode

FAMILY = "DejaVu Sans"
BOX = Rect(100.0, 100.0, 60.0, 40.0)
TRAPEZ = ((10.0, 0.0), (-10.0, 0.0), (0.0, 0.0), (0.0, 0.0))   # oben 20 mm schmaler


def rings(shape, tol=None):
    out = []
    for poly in shape_polygons(shape, *(() if tol is None else (tol,))):
        out.append(poly[:-1] if len(poly) > 1 and poly[0] == poly[-1] else poly)
    return out


def burned(g: str) -> float:
    return parse_gcode(g).cut_length_mm


def perimeter(pts, closed=True):
    seq = pts + pts[:1] if closed else pts
    return sum(math.dist(a, b) for a, b in zip(seq, seq[1:]))


def rect(x=100.0, y=100.0, w=60.0, h=40.0, layer="L", **kw):
    return Shape("rect", Geometry(x, y, w, h, kw.pop("rot", 0.0)), layer, **kw)


def assert_close_to_exact(poly, src_pts, w, closed, tol=0.012, n=400):
    """Jeder exakt abgebildete Punkt der Quelle liegt ≤ tol neben dem Ergebnis."""
    seq = src_pts + src_pts[:1] if closed else src_pts
    line = LineString(poly + poly[:1] if closed else poly)
    worst = 0.0
    for a, b in zip(seq, seq[1:]):
        for k in range(n + 1):
            t = k / n
            p = w.map((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))
            worst = max(worst, line.distance(Point(p)))
    assert worst <= tol


# --- Abbildung -------------------------------------------------------------------------

def test_identity_and_corners_map_onto_the_quad(qapp):
    w = warp.warp_from_offsets(BOX, ((0, 0),) * 4)
    assert w.is_identity() and w.problem() == ""
    assert w.map((130.0, 120.0)) == pytest.approx((130.0, 120.0))
    for mode in warp.MODES:
        w = warp.warp_from_offsets(BOX, ((5, -3), (-2, 4), (6, 7), (-4, -1)), mode)
        assert w.problem() == "" and not w.is_identity()
        for c, q in zip(warp.box_corners(BOX), w.quad):
            assert w.map(c) == pytest.approx(q, abs=1e-9)
    assert warp.warp_from_offsets(BOX, TRAPEZ).quad[0] == (110.0, 100.0)


def test_envelope_maps_the_box_edges_linearly_and_rect_stays_four_points(qapp):
    w = warp.warp_from_offsets(BOX, TRAPEZ)
    assert w.map((130.0, 100.0)) == pytest.approx((130.0, 100.0))      # Mitte oben
    assert w.map((100.0, 120.0)) == pytest.approx((105.0, 120.0))      # Mitte links
    (out,) = warp.warp_shapes([rect()], w).add
    assert out.kind == "polygon" and len(out.points) == 4
    assert sorted(rings(out)[0]) == sorted([(110, 100), (150, 100), (160, 140), (100, 140)])


def test_envelope_bends_a_diagonal_within_the_tolerance(qapp):
    w = warp.warp_from_offsets(BOX, ((0, 0), (0, -20), (0, 0), (0, 0)))
    line = Shape("line", Geometry(100, 140, 60, -40), "L")
    (out,) = warp.warp_shapes([line], w).add
    assert out.kind == "path" and len(out.points) > 8               # gebogen, fein unterteilt
    (poly,) = rings(out)
    assert poly[0] == pytest.approx((100, 140)) and poly[-1] == pytest.approx((160, 80))
    mid = w.map((130.0, 120.0))
    assert LineString(poly).distance(LineString([(100, 140), (160, 80)])) < 1e-6
    assert abs(mid[1] - 110.0) > 1.0                               # nicht mehr auf der Sehne
    assert_close_to_exact(poly, [(100, 140), (160, 100)], w, closed=False)


def test_perspective_keeps_lines_straight_and_centre_on_the_diagonals(qapp):
    offs = ((10, 0), (-10, 0), (0, 0), (0, 0))
    w = warp.warp_from_offsets(BOX, offs, "perspective")
    line = Shape("line", Geometry(100, 140, 60, -40), "L")
    (out,) = warp.warp_shapes([line], w).add
    assert len(out.points) == 2
    (r,) = warp.warp_shapes([rect()], w).add
    assert len(r.points) == 4
    c = w.map((130.0, 120.0))
    q = w.quad
    d1, d2 = LineString([q[0], q[2]]), LineString([q[1], q[3]])
    x = d1.intersection(d2)
    assert c == pytest.approx((x.x, x.y), abs=1e-9)
    # Perspektive staucht zur kurzen Seite: die Mitte rückt nach oben
    assert c[1] < 120.0
    env = warp.warp_from_offsets(BOX, offs).map((130.0, 120.0))
    assert env == pytest.approx((130.0, 120.0))


def test_bulge_turns_the_envelope_into_an_arch(qapp):
    w = warp.warp_from_offsets(BOX, ((0, 0),) * 4, bulge_top=6.0, bulge_bottom=6.0)
    assert w.problem() == ""
    assert w.map((130.0, 100.0)) == pytest.approx((130.0, 94.0))
    assert w.map((130.0, 140.0)) == pytest.approx((130.0, 134.0))
    assert w.map((100.0, 100.0)) == pytest.approx((100.0, 100.0))   # Ecken bleiben
    res = warp.warp_shapes([rect()], w)
    (out,) = res.add
    b = out.bounds()
    assert b.x == pytest.approx(100) and b.w == pytest.approx(60)
    assert b.y == pytest.approx(94, abs=0.01) and b.bottom == pytest.approx(140)
    assert_close_to_exact(rings(out)[0], [(100, 100), (160, 100), (160, 140), (100, 140)], w, True)
    # Tonne: oben nach oben, unten nach unten
    w2 = warp.warp_from_offsets(BOX, ((0, 0),) * 4, bulge_top=5.0, bulge_bottom=-5.0)
    assert w2.map((130.0, 140.0)) == pytest.approx((130.0, 145.0))
    # Perspektive kennt keine Wölbung
    w3 = warp.warp_from_offsets(BOX, ((0, 0),) * 4, "perspective", 5.0, 5.0)
    assert w3.bulge_top == 0 and w3.is_identity()


def test_ellipse_polygon_with_hole_and_rotated_freehand_curve(qapp):
    w = warp.warp_from_offsets(BOX, ((8, 2), (-6, -4), (3, 5), (-2, 1)))
    circ = Shape("ellipse", Geometry(110, 105, 30, 30), "L")
    ring = Shape.from_points("polygon", [(120, 110), (155, 110), (155, 138), (120, 138),
                                         (130, 118), (145, 118), (145, 130), (130, 130)], "L",
                             rings=[4])
    free = Shape.from_points("path", [(102, 135), (115, 104), (128, 132), (140, 106)], "L",
                             curves=[0, 1, 2])
    free.geom = Geometry(free.geom.x, free.geom.y, free.geom.w, free.geom.h, 15.0)
    res = warp.warp_shapes([circ, ring, free], w)
    a, b, c = res.add
    assert a.kind == "polygon" and len(a.points) > 60
    assert_close_to_exact(rings(a)[0], rings(circ, warp.FLATTEN_MM)[0], w, True)
    assert b.kind == "polygon" and len(b.rings) == 1                 # Loch bleibt Ring
    pb = Polygon(rings(b)[0], [rings(b)[1]])
    assert pb.is_valid and pb.area > 0
    assert c.kind == "path" and c.curves == () and c.geom.rot == 0
    assert_close_to_exact(rings(c)[0], rings(free, warp.FLATTEN_MM)[0], w, False, n=40)
    assert res.readout().startswith("3 Objekt(e) verzerrt (2 geschlossene Form(en), 1 offene Linie(n))")


def test_outline_text_becomes_polygon_and_single_line_text_an_open_path(qapp):
    t = Shape("text", Geometry(100, 100, 12 * text_aspect("Ab", FAMILY), 12), "L", text="Ab",
              font_family=FAMILY)
    lt = Shape("text", Geometry(100, 120, 10 * text_aspect("Ab", LINE_FONT_SANS), 10), "L",
               text="Ab", font_family=LINE_FONT_SANS)
    box = warp.selection_box([t, lt])
    w = warp.warp_from_offsets(box, ((3, 0), (-3, 0), (0, 0), (0, 0)), bulge_top=2.0)
    a, b = warp.warp_shapes([t, lt], w).add
    assert a.kind == "polygon" and len(a.rings) >= 2               # A mit Loch, b mit Loch
    assert b.kind == "path" and len(b.rings) + 1 == len(rings(lt))  # ein Ring je Strich
    for src, dst in zip(rings(lt), rings(b)):
        assert dst[0] == pytest.approx(w.map(src[0]), abs=1e-6)


def test_attributes_tabs_and_start_point_follow(qapp):
    s = rect(layer="L2", groups=("g1",), priority=3, reverse=True)
    s = tabs.with_tab_points(s, [(130.0, 100.0), (160.0, 120.0)])
    s = with_start(s, (100.0, 120.0))
    w = warp.warp_from_offsets(BOX, TRAPEZ, bulge_top=4.0)
    (out,) = warp.warp_shapes([s], w).add
    assert (out.layer_id, out.groups, out.priority, out.reverse) == ("L2", ("g1",), 3, True)
    got = out.tab_points()
    assert len(got) == 2
    for p, q in zip(got, (w.map((130.0, 100.0)), w.map((160.0, 120.0)))):
        assert math.dist(p, q) < 0.02
    assert math.dist(out.start_point(), w.map((100.0, 120.0))) < 0.02
    assert out.id != s.id


@pytest.mark.parametrize("offs, bulge, word", [
    (((70, 0), (-70, 0), (0, 0), (0, 0)), 0.0, "konvex"),          # oben überschlagen
    (((60, 0), (-60, 0), (0, 0), (0, 0)), 0.0, "konvex"),          # oben auf einen Punkt
    (((0, 0), (0, 0), (-50, -30), (0, 0)), 0.0, "konvex"),          # konkav
    (((70, 0), (-70, 0), (70, 0), (-70, 0)), 0.0, "konvex"),        # gespiegelt
    (((0, 0),) * 4, -50.0, "Wölbung"),          # Oberkante unter die Unterkante
])
def test_refused_quads(qapp, offs, bulge, word):
    w = warp.warp_from_offsets(BOX, offs, bulge_top=bulge)
    res = warp.warp_shapes([rect()], w)
    assert word in res.problem and res.add == [] and res.readout() == res.problem


def test_flat_selection_nan_and_degenerate_perspective(qapp):
    flat = Shape("line", Geometry(100, 100, 50, 0), "L")
    w = warp.warp_from_offsets(flat.bounds(), ((0, 0), (0, -5), (0, 0), (0, 0)))
    assert "Breite und Höhe" in w.problem()
    w = warp.warp_from_offsets(BOX, ((math.nan, 0), (0, 0), (0, 0), (0, 0)))
    assert "Ungültige" in w.problem()
    # flache Linie zusammen mit einer Fläche geht (gemeinsame Box)
    w = warp.warp_from_offsets(warp.selection_box([flat, rect()]), TRAPEZ)
    res = warp.warp_shapes([flat, rect()], w)
    assert res.problem == "" and [s.kind for s in res.add] == ["path", "polygon"]


def test_images_are_left_alone_and_counted(qapp):
    img = QImage(10, 10, QImage.Format_RGB32)
    img.fill(QColor(90, 90, 90))
    png = grayscale_png(img)
    im = Shape("image", Geometry(100, 100, 20, 20), "L",
               image=RasterImage(png[0], png[1], png[2], ImageSettings()))
    w = warp.warp_from_offsets(warp.selection_box([im, rect()]), TRAPEZ)
    res = warp.warp_shapes([im, rect()], w)
    assert res.images == 1 and len(res.add) == 1 and im.id not in res.remove
    assert "1 Bild(er) bleiben unverändert" in res.readout()
    assert not warp.can_warp(im) and warp.warp_shape(im, w) is None


def test_outside_work_area_is_flagged(qapp):
    s = rect(x=0.0, y=0.0, w=40.0, h=30.0)
    w = warp.warp_from_offsets(s.bounds(), ((-5, 0), (0, 0), (0, 0), (0, 0)))
    res = warp.warp_shapes([s], w)
    assert not res.inside and "Arbeitsfläche" in res.readout()
    w = warp.warp_from_offsets(s.bounds(), ((5, 0), (0, 0), (0, 0), (0, 0)))
    assert warp.warp_shapes([s], w).inside


def test_presets(qapp):
    assert warp.preset_offsets("top_narrow", BOX) == ((6.0, 0.0), (-6.0, 0.0), (0.0, 0.0), (0.0, 0.0))
    assert warp.preset_offsets("bottom_narrow", BOX)[2] == (-6.0, 0.0)
    assert warp.preset_offsets("rise_right", BOX)[1] == (0.0, -4.0)
    assert warp.preset_offsets("reset", BOX) == ((0.0, 0.0),) * 4


# --- G-Code ----------------------------------------------------------------------------

def test_gcode_burns_the_warped_outline_and_fills_it(qapp):
    doc = Document()
    lid = doc.active_layer_id
    w = warp.warp_from_offsets(BOX, TRAPEZ, bulge_top=5.0)
    (out,) = warp.warp_shapes([rect(layer=lid)], w).add
    doc.add_shape(out)
    g = optimized_document_gcode(doc, scan_offsets=None)
    pi_check(g)
    assert not re.search(r"^G[23]\b", g, re.M)
    assert burned(g) == pytest.approx(perimeter(rings(out)[0]), abs=0.05)
    doc.update_layer(lid, fill_mode="hatch", line_interval_mm=0.5)
    gf = optimized_document_gcode(doc, scan_offsets=None)
    pi_check(gf)
    area = Polygon(rings(out)[0]).area
    assert burned(gf) == pytest.approx(area / 0.5, rel=0.05)


def test_gcode_of_warped_single_line_text_lasers_strokes_once(qapp):
    doc = Document()
    lid = doc.active_layer_id
    doc.update_layer(lid, fill_mode="hatch", line_interval_mm=0.2)
    lt = Shape("text", Geometry(100, 120, 10 * text_aspect("LUMA", LINE_FONT_SANS), 10), lid,
               text="LUMA", font_family=LINE_FONT_SANS)
    w = warp.warp_from_offsets(lt.bounds(), ((4, 0), (-4, 0), (0, 0), (0, 0)), bulge_top=3.0,
                               bulge_bottom=3.0)
    (out,) = warp.warp_shapes([lt], w).add
    doc.add_shape(out)
    g = optimized_document_gcode(doc, scan_offsets=None)
    pi_check(g)
    strokes = sum(perimeter(r, closed=False) for r in rings(out))
    assert burned(g) == pytest.approx(strokes, abs=0.1)


# --- Dialog ----------------------------------------------------------------------------

def test_dialog_starts_unchanged_presets_modes_and_ok_state(qapp):
    from PySide6.QtWidgets import QDialogButtonBox
    from lumacut_canvas.warp_ui import WarpDialog
    dlg = WarpDialog([rect()])
    ok = dlg.buttons.button(QDialogButtonBox.Ok)
    assert not ok.isEnabled() and dlg.readout.text().startswith("Ecken ziehen")
    assert dlg.values() == {"mode": "envelope", "offsets": ((0.0, 0.0),) * 4,
                            "bulge_top": 0.0, "bulge_bottom": 0.0}
    dlg.preset_buttons["top_narrow"].click()
    assert dlg.offsets()[0] == (6.0, 0.0) and ok.isEnabled()
    assert dlg.readout.text().startswith("1 Objekt(e) verzerrt")
    assert len(dlg.preview.outlines) == 1 and dlg.preview.quad[0] == (106.0, 100.0)
    dlg.preset_buttons["arch"].click()
    assert dlg.values()["bulge_top"] == pytest.approx(6.0) and dlg.values()["bulge_bottom"] == pytest.approx(6.0)
    dlg.mode.setCurrentIndex(dlg.mode.findData("perspective"))
    assert not dlg.bulge_top.isEnabled() and ok.isEnabled()
    dlg.mode.setCurrentIndex(dlg.mode.findData("envelope"))
    dlg.bulge_top.setValue(-60.0)
    assert "Wölbung" in dlg.readout.text() and not ok.isEnabled()
    dlg.preset_buttons["reset"].click()
    assert dlg.values() == {"mode": "envelope", "offsets": ((0.0, 0.0),) * 4,
                            "bulge_top": 0.0, "bulge_bottom": 0.0}
    assert not ok.isEnabled()
    dlg.spins[1][0].setValue(-70.0)
    dlg.spins[0][0].setValue(70.0)
    assert "konvex" in dlg.readout.text() and not ok.isEnabled()
    dlg.deleteLater()


def test_dialog_corner_drag_by_mouse_moves_the_offsets(qapp):
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest
    from lumacut_canvas.warp_ui import WarpDialog
    dlg = WarpDialog([rect()])
    dlg.show()
    qapp.processEvents()
    pv = dlg.preview
    start = pv.to_screen(pv.quad[1]).toPoint()
    assert pv.corner_at(pv.to_screen(pv.quad[1])) == 1
    k = pv._frame()[0]
    QTest.mousePress(pv, Qt.LeftButton, Qt.NoModifier, start)
    QTest.mouseMove(pv, start + QPoint(-int(round(10 * k)), int(round(5 * k))))
    QTest.mouseRelease(pv, Qt.LeftButton, Qt.NoModifier, start + QPoint(-int(round(10 * k)), int(round(5 * k))))
    dx, dy = dlg.offsets()[1]
    assert dx == pytest.approx(-10.0, abs=0.6) and dy == pytest.approx(5.0, abs=0.6)
    assert dlg.offsets()[0] == (0.0, 0.0) and pv.drag is None
    assert pv.quad[1] == pytest.approx((160 + dx, 100 + dy))
    dlg.close()
    dlg.deleteLater()


def test_dialog_touch_sizes(qapp):
    from lumacut_canvas.warp_ui import WarpDialog
    dlg = WarpDialog([rect()], touch=True)
    assert dlg.preview.handle_px == 22.0 and dlg.preview.minimumWidth() >= 320
    assert dlg.spins[0][0].minimumHeight() >= 44 and dlg.bulge_top.minimumHeight() >= 44
    assert all(b.minimumHeight() >= 44 for b in dlg.preset_buttons.values())
    assert WarpDialog([rect()]).preview.handle_px == 10.0
    dlg.deleteLater()


# --- Editor ----------------------------------------------------------------------------

@pytest.fixture
def ed(qapp):
    e = CanvasEditor()
    e.resize(1000, 700)
    e.show()
    qapp.processEvents()
    yield e
    e.undo_stack.setClean()
    e.close()
    e.deleteLater()


def _add(ed, shapes):
    ed.undo_stack.push(AddShapesCommand(ed.document, list(shapes)))
    return [s.id for s in shapes]


def test_editor_warp_one_undo_step_keeps_stacking_and_selection(ed):
    lid = ed.document.active_layer_id
    a = rect(layer=lid)
    other = Shape("ellipse", Geometry(250, 250, 10, 10), lid)
    b = Shape("ellipse", Geometry(110, 110, 20, 20), lid)
    ids = _add(ed, [a, other, b])
    seen = []
    ed.path_ops.warp.ask = lambda shapes: seen.append([s.id for s in shapes]) or {
        "mode": "perspective", "offsets": TRAPEZ, "bulge_top": 0.0, "bulge_bottom": 0.0}
    msgs = []
    ed.statusMessage.connect(msgs.append)
    ed.set_selection([b.id, a.id])
    ed.actions_by_name["path_warp"].trigger()
    assert seen == [[a.id, b.id]]
    shapes = ed.document.shapes
    assert [s.kind for s in shapes] == ["polygon", "ellipse", "polygon"]
    assert shapes[1].id == other.id and shapes[0].id != a.id
    assert sorted(ed.selection) == sorted([shapes[0].id, shapes[2].id])
    assert ed.undo_stack.undoText() == "Verzerren"
    assert msgs[-1].startswith("Verzerren: 2 Objekt(e) verzerrt (2 geschlossene Form(en))")
    assert ed.path_ops.warp.last_mode == "perspective"
    ed.undo_stack.undo()
    assert [s.id for s in ed.document.shapes] == ids
    ed.undo_stack.redo()
    assert len(ed.document.shapes) == 3


def test_editor_nothing_selected_images_locked_cancel_and_outside(ed):
    lid = ed.document.active_layer_id
    msgs = []
    ed.statusMessage.connect(msgs.append)
    ed.path_ops.warp.ask = lambda shapes: pytest.fail("kein Dialog erwartet")
    ed.actions_by_name["path_warp"].trigger()
    assert msgs[-1].startswith("Verzerren: Formen, Linien oder Text auswählen")
    s = rect(x=0.0, y=0.0, w=40.0, h=30.0, layer=lid)
    ids = _add(ed, [s])
    ed.set_selection(ids)
    ed.document.update_layer(lid, locked=True)
    ed.actions_by_name["path_warp"].trigger()
    assert msgs[-1].startswith("Verzerren: Formen")
    ed.document.update_layer(lid, locked=False)
    ed.set_selection(ids)
    ed.path_ops.warp.ask = lambda shapes: None
    ed.actions_by_name["path_warp"].trigger()
    assert [x.id for x in ed.document.shapes] == ids
    ed.path_ops.warp.ask = lambda shapes: {"mode": "envelope", "offsets": ((-5, 0), (0, 0), (0, 0), (0, 0)),
                                           "bulge_top": 0.0, "bulge_bottom": 0.0}
    ed.actions_by_name["path_warp"].trigger()
    assert [x.id for x in ed.document.shapes] == ids and "außerhalb der Arbeitsfläche" in msgs[-1]
    ed.path_ops.warp.ask = lambda shapes: {"mode": "envelope", "offsets": ((40, 0), (-40, 0), (0, 0), (0, 0)),
                                           "bulge_top": 0.0, "bulge_bottom": 0.0}
    ed.actions_by_name["path_warp"].trigger()
    assert [x.id for x in ed.document.shapes] == ids and "konvex" in msgs[-1]


def test_action_menus_tooltip_and_touch_context_menu(ed, qapp):
    from PySide6.QtCore import QPointF
    a = ed.actions_by_name["path_warp"]
    assert a.text() == "Verzerren …" and a.shortcut().toString() == "Alt+Shift+W"
    assert "Warp" in a.toolTip() and "verzerren" in ed.path_ops_button.toolTip()
    texts = [x.text() for x in ed.path_ops_button.menu().actions() if x.text()]
    assert texts.index("Verzerren …") == texts.index("Ecken abrunden …") + 1
    _add(ed, [rect(x=10, y=10, w=20, h=10, layer=ed.document.active_layer_id)])
    ed.set_touch_mode(True, persist=False)
    try:
        menu = ed.build_context_menu(QPointF(20, 15))
        sub = next(x.menu() for x in menu.actions() if x.menu() is not None
                   and x.menu().objectName() == "PathOpsMenu")
        act = next(x for x in sub.actions() if x.text() == "Verzerren …")
        sub.popup(ed.mapToGlobal(ed.rect().center()))
        qapp.processEvents()
        assert sub.actionGeometry(act).height() >= 44
        sub.close()
    finally:
        ed.set_touch_mode(False, persist=False)


def test_save_load_keeps_the_warped_shape_without_new_keys(ed, tmp_path):
    from lumacut_canvas.document_io import load_into, save_document
    lid = ed.document.active_layer_id
    ids = _add(ed, [rect(layer=lid)])
    ed.set_selection(ids)
    ed.path_ops.warp.ask = lambda shapes: {"mode": "envelope", "offsets": TRAPEZ,
                                           "bulge_top": 4.0, "bulge_bottom": 0.0}
    ed.actions_by_name["path_warp"].trigger()
    (s,) = ed.document.shapes
    d = s.to_dict()
    plain = Shape.from_points("polygon", [(0, 0), (1, 0), (1, 1)], lid, rings=[]).to_dict()
    assert set(d) <= set(plain) | {"rings"}
    p = save_document(ed.document, tmp_path / "w.lcut")
    doc = Document()
    load_into(doc, p)
    (t,) = doc.shapes
    assert t.kind == "polygon"
    assert [c for p in rings(t)[0] for c in p] == pytest.approx([c for p in rings(s)[0] for c in p])


def test_main_window_alt_shift_w_is_unique_and_warps(qapp, tmp_path):
    from PySide6.QtCore import QSettings
    from PySide6.QtGui import QAction, QKeySequence
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(tmp_path))
    QSettings.setDefaultFormat(QSettings.IniFormat)
    main = pytest.importorskip("main")
    w = main.LumaCutStudio()
    try:
        owners = [a for a in w.findChildren(QAction) if a.shortcut() == QKeySequence("Alt+Shift+W")]
        assert [a.text() for a in owners] == ["Verzerren …"]
        ed = w.canvas
        ids = _add(ed, [rect(layer=ed.document.active_layer_id)])
        ed.set_selection(ids)
        ed.path_ops.warp.ask = lambda shapes: {"mode": "envelope", "offsets": TRAPEZ,
                                               "bulge_top": 0.0, "bulge_bottom": 0.0}
        owners[0].trigger()
        (s,) = ed.document.shapes
        assert s.kind == "polygon" and s.bounds().w == pytest.approx(60)
    finally:
        w.canvas.undo_stack.setClean()
        w.close()
