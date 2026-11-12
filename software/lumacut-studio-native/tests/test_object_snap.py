"""Objektfang „An Objekten fangen“: Fangpunkte, Ausrichtung, Werkzeuge, Schalter."""

import sys
from pathlib import Path

import pytest
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QKeyEvent

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _pi_guard import pi_check  # noqa: E402

from lumacut_canvas import objsnap, objsnap_ui  # noqa: E402
from lumacut_canvas.commands import AddShapesCommand  # noqa: E402
from lumacut_canvas.editor import CanvasEditor  # noqa: E402
from lumacut_canvas.model import Document, Geometry, Layer, Shape  # noqa: E402
from lumacut_canvas.objsnap import SnapTargets  # noqa: E402
from lumacut_canvas.tools import Tool  # noqa: E402
from lumacut_canvas.workarea import WORK_HEIGHT_MM, WORK_WIDTH_MM, Rect  # noqa: E402

NO = Qt.NoModifier
SHIFT = Qt.ShiftModifier
ALT = Qt.AltModifier
ZOOM = 4.0  # px/mm → Fangabstand 7 px = 1.75 mm


# --- Hilfen ------------------------------------------------------------------
def labels(pts):
    return sorted(lbl for *_, lbl in pts)


def has_point(pts, x, y, label=None):
    return any(abs(px - x) < 1e-6 and abs(py - y) < 1e-6 and (label is None or lbl == label)
               for px, py, lbl in pts)


def doc_with(*shapes):
    d = Document()
    for s in shapes:
        s.layer_id = d.active_layer_id
        d.add_shape(s)
    return d


@pytest.fixture
def ed(qapp):
    e = CanvasEditor()
    e.resize(1000, 700)
    e.show()
    qapp.processEvents()
    e.view.set_zoom(ZOOM)
    yield e
    e.undo_stack.setClean()
    e.close()


def add(ed, *shapes):
    for s in shapes:
        s.layer_id = s.layer_id if s.layer_id != "?" else ed.document.active_layer_id
    ed.undo_stack.push(AddShapesCommand(ed.document, list(shapes)))
    return [ed.document.shape(s.id) for s in shapes]


def rect(x, y, w, h, rot=0.0, layer="?", **kw):
    return Shape("rect", Geometry(x, y, w, h, rot), layer, **kw)


def drag(ed, a, b, mods=NO, release=True):
    t = ed.tools
    t.press(QPointF(*a), mods)
    t.move(QPointF((a[0] + b[0]) / 2, (a[1] + b[1]) / 2), mods, True)
    t.move(QPointF(*b), mods, True)
    if release:
        t.release(QPointF(*b), mods)


# --- Fangpunkte je Objektart ---------------------------------------------------
def test_rect_points_corners_edge_midpoints_and_centre():
    pts = objsnap.shape_points(rect(10, 20, 40, 10))
    assert labels(pts) == sorted(["Mitte"] + ["Ecke"] * 4 + ["Kantenmitte"] * 4)
    for x, y in ((10, 20), (50, 20), (50, 30), (10, 30)):
        assert has_point(pts, x, y, "Ecke")
    for x, y in ((30, 20), (50, 25), (30, 30), (10, 25)):
        assert has_point(pts, x, y, "Kantenmitte")
    assert has_point(pts, 30, 25, "Mitte")


def test_rotated_rect_points_follow_rotation():
    pts = objsnap.shape_points(rect(10, 10, 20, 20, rot=45))
    # Quadrat um (20, 20) um 45° gedreht: Ecken liegen auf den Achsen.
    r = 200 ** 0.5
    for x, y in ((20, 20 - r), (20 + r, 20), (20, 20 + r), (20 - r, 20)):
        assert has_point(pts, x, y, "Ecke")
    assert not has_point(pts, 10, 10)


def test_rounded_rect_has_no_corner_points():
    pts = objsnap.shape_points(rect(0, 0, 40, 20, corner_radius=5.0))
    assert "Ecke" not in labels(pts)
    assert labels(pts).count("Kantenmitte") == 4


def test_ellipse_quadrants_and_line_ends():
    e = objsnap.shape_points(Shape("ellipse", Geometry(0, 0, 40, 20), "l"))
    assert labels(e) == sorted(["Mitte"] + ["Quadrant"] * 4)
    assert has_point(e, 20, 0, "Quadrant") and has_point(e, 40, 10, "Quadrant")
    ln = objsnap.shape_points(Shape("line", Geometry(5, 5, 30, 10), "l"))
    assert has_point(ln, 5, 5, "Endpunkt") and has_point(ln, 35, 15, "Endpunkt")
    assert has_point(ln, 20, 10, "Mitte")


def test_polygon_nodes_straight_edge_midpoints_and_curves_skipped():
    tri = Shape.from_points("polygon", [(0, 0), (40, 0), (20, 30)], "l")
    pts = objsnap.shape_points(tri)
    assert labels(pts).count("Knoten") == 3 and labels(pts).count("Kantenmitte") == 3
    assert has_point(pts, 30, 15, "Kantenmitte") and has_point(pts, 10, 15, "Kantenmitte")
    curved = Shape.from_points("polygon", [(0, 0), (40, 0), (20, 30)], "l", curves=[1])
    assert labels(objsnap.shape_points(curved)).count("Kantenmitte") == 2


def test_open_path_has_no_closing_midpoint_and_rings_are_separate():
    path = Shape.from_points("path", [(0, 0), (10, 0), (10, 10)], "l")
    pts = objsnap.shape_points(path)
    assert labels(pts).count("Kantenmitte") == 2 and not has_point(pts, 5, 5, "Kantenmitte")
    two = Shape.from_points("polygon", [(0, 0), (30, 0), (30, 30), (0, 30),
                                        (10, 10), (20, 10), (20, 20), (10, 20)], "l", rings=[4])
    p2 = objsnap.shape_points(two)
    assert labels(p2).count("Knoten") == 8 and labels(p2).count("Kantenmitte") == 8
    assert has_point(p2, 15, 10, "Kantenmitte") and not has_point(p2, 5, 15)  # kein Ring-Übergang


def test_text_codes_and_dense_paths_only_contribute_box_corners():
    txt = objsnap.shape_points(Shape("text", Geometry(0, 0, 30, 10), "l", text="Hi"))
    assert labels(txt) == sorted(["Mitte"] + ["Ecke"] * 4)
    many = [(i, (i * 7) % 13) for i in range(objsnap.MAX_NODES_PER_SHAPE + 5)]
    dense = Shape.from_points("path", many, "l")
    assert labels(objsnap.shape_points(dense)) == sorted(["Mitte"] + ["Ecke"] * 4)
    code = Shape.from_points("polygon", [(0, 0), (5, 0), (5, 5)], "l")
    code.generator = {"type": "qr"}
    assert "Knoten" not in labels(objsnap.shape_points(code))


# --- Ziele des Dokuments --------------------------------------------------------
def test_targets_exclude_hidden_layers_and_excluded_ids_but_keep_locked_layers():
    d = Document()
    a = rect(10, 10, 20, 20)
    b = rect(100, 100, 20, 20)
    c = rect(200, 200, 20, 20)
    for s in (a, b, c):
        s.layer_id = d.active_layer_id
        d.add_shape(s)
    lock = Layer(name="gesperrt", locked=True)
    hid = Layer(name="aus", visible=False)
    d.layers.extend([lock, hid])
    d.set_shape_layer(b.id, lock.id)
    d.set_shape_layer(c.id, hid.id)
    t = SnapTargets.from_document(d, exclude=[a.id], work_area=False)
    assert has_point(t.points, 100, 100, "Ecke")      # gesperrt zählt (liegt auf dem Material)
    assert not has_point(t.points, 200, 200)          # ausgeblendet nicht
    assert not has_point(t.points, 10, 10)            # gezogenes Objekt nicht
    assert not any(abs(v - 200) < 1e-9 for v, *_ in t.xs)


def test_targets_group_centre_and_work_area():
    a, b = rect(0, 0, 10, 10), rect(30, 0, 10, 10)
    a.groups = b.groups = ("g1",)
    t = SnapTargets.from_document(doc_with(a, b))
    assert has_point(t.points, 20, 5, "Gruppenmitte")
    assert has_point(t.points, WORK_WIDTH_MM / 2, WORK_HEIGHT_MM / 2, "Mitte der Arbeitsfläche")
    assert has_point(t.points, WORK_WIDTH_MM, 0, "Ecke der Arbeitsfläche")
    assert any(abs(v - 40) < 1e-9 for v, *_ in t.xs)  # rechte Kante der Gruppenbox
    t2 = SnapTargets.from_document(doc_with(rect(0, 0, 10, 10)), work_area=False)
    assert not has_point(t2.points, WORK_WIDTH_MM / 2, WORK_HEIGHT_MM / 2)


def test_targets_are_capped(monkeypatch):
    monkeypatch.setattr(objsnap, "MAX_POINTS", 20)
    shapes = [rect(i * 12, 0, 10, 10) for i in range(10)]
    t = SnapTargets.from_document(doc_with(*shapes), work_area=False)
    assert len(t.points) == 20
    assert len(t.xs) == 30  # Boxen aller Objekte bleiben für die Ausrichtung


# --- Fangen -----------------------------------------------------------------------
def test_snap_point_prefers_nearest_point_within_tolerance():
    t = SnapTargets.from_document(doc_with(rect(10.3, 20.7, 40, 10)), work_area=False)
    s = t.snap_point(11.0, 21.2, 1.0)
    assert (s.x, s.y, s.label, s.point) == (pytest.approx(10.3), pytest.approx(20.7), "Ecke",
                                            (pytest.approx(10.3), pytest.approx(20.7)))
    assert s.snapped_x and s.snapped_y and s.guides == []
    near = t.snap_point(10.6, 22.0, 1.0)  # Ecke 1.33 entfernt, linke Kante 0.3: nur x
    assert near.snapped_x and not near.snapped_y and near.point is None


def test_snap_point_aligns_per_axis_with_guides():
    t = SnapTargets.from_document(doc_with(rect(10.3, 20.7, 40, 10)), work_area=False)
    s = t.snap_point(10.8, 80.0, 1.0)  # unter der linken Kante, kein Punkt in der Nähe
    assert s.snapped_x and not s.snapped_y and s.point is None
    assert s.x == pytest.approx(10.3) and s.y == 80.0 and s.label == "Kante"
    (x1, y1, x2, y2), = s.guides
    assert x1 == x2 == pytest.approx(10.3) and y1 == pytest.approx(20.7) and y2 == pytest.approx(80.0)
    s2 = t.snap_point(30.4, 70.0, 1.0)  # senkrechte Mitte
    assert s2.x == pytest.approx(30.3) and s2.label == "Mitte"
    none = t.snap_point(120.0, 120.0, 1.0)
    assert not none.snapped and none.guides == [] and (none.x, none.y) == (120.0, 120.0)
    assert not t.snap_point(11.0, 21.0, 0.0).snapped  # Toleranz 0 = aus


def test_snap_box_aligns_edges_and_centres():
    t = SnapTargets.from_document(doc_with(rect(10.3, 20.7, 40, 10)), work_area=False)
    # Linke Kante der gezogenen Box nahe an der rechten Kante (50.3) des Rechtecks.
    ddx, ddy, s = t.snap_box(Rect(50.9, 60.0, 20, 20), 1.0)
    assert ddx == pytest.approx(-0.6) and ddy == 0.0 and s.snapped_x and not s.snapped_y
    (x1, y1, x2, y2), = s.guides
    assert x1 == x2 == pytest.approx(50.3) and y1 == pytest.approx(20.7) and y2 == pytest.approx(80.0)
    # Mitte auf Mitte (y): Box 10 hoch bei y 21.5 → Mitte 26.5 vs. 25.7 und obere Kante 21.5 vs. 20.7 –
    # gleich weit; die zuerst geprüfte (obere Kante) gewinnt bei Gleichstand.
    _, ddy2, s2 = t.snap_box(Rect(100, 21.2, 10, 10), 1.0)
    assert s2.snapped_y and ddy2 == pytest.approx(-0.5)
    # Nur die kleinere Abweichung zählt (rechte Kante 0.2 statt linke 0.9).
    ddx3, _, _ = t.snap_box(Rect(9.4, 100, 40.7, 5), 1.0)
    assert ddx3 == pytest.approx(0.2)


def test_snap_box_axes_and_nothing_in_reach():
    t = SnapTargets.from_document(doc_with(rect(10.3, 20.7, 40, 10)), work_area=False)
    ddx, ddy, s = t.snap_box(Rect(50.9, 21.0, 20, 20), 1.0, axes=(False, True))
    assert ddx == 0.0 and not s.snapped_x and s.snapped_y and ddy == pytest.approx(-0.3)
    assert len(s.guides) == 1 and s.guides[0][1] == s.guides[0][3]
    ddx, ddy, s = t.snap_box(Rect(150, 150, 20, 20), 1.0)
    assert (ddx, ddy, s.snapped) == (0.0, 0.0, False)


def test_tolerance_in_screen_pixels():
    assert objsnap.tolerance_mm(4.0) == pytest.approx(7 / 4)
    assert objsnap.tolerance_mm(4.0, touch=True) == pytest.approx(14 / 4)
    assert objsnap.tolerance_mm(40.0) < objsnap.tolerance_mm(2.0)


# --- Werkzeuge im Editor ------------------------------------------------------------
def test_draw_rect_from_a_corner_of_another_object(ed):
    (r,) = add(ed, rect(20.4, 30.6, 40, 20))
    ed.set_tool(Tool.RECT)
    drag(ed, (60.9, 50.2), (90.0, 80.0))  # Start 0.5 / 0.4 mm neben der Ecke unten rechts
    new = ed.document.shapes[-1]
    assert new.id != r.id
    assert (new.geom.x, new.geom.y) == (pytest.approx(60.4), pytest.approx(50.6))
    assert new.geom.x + new.geom.w == pytest.approx(90.0)  # Ende ohne Objekt: 1-mm-Raster
    assert ed.undo_stack.count() == 2
    assert not ed.object_snap.guides.isVisible() and ed.object_snap.targets is None


def test_draw_end_aligns_with_edge_and_shows_guide_while_dragging(ed):
    add(ed, rect(20.4, 30.6, 40, 20))
    ed.set_tool(Tool.LINE)
    drag(ed, (100, 100), (150.0, 31.0), release=False)
    g = ed.object_snap.guides
    assert g.isVisible() and ed.object_snap.last.label == "Kante"
    line = ed.document.shape(ed.tools._preview_id)
    ends = line.geom.corner_points()
    assert (150.0, pytest.approx(30.6)) in ends  # Endpunkt auf Höhe der Oberkante, x im Raster
    ed.tools.release(QPointF(150.0, 31.0), NO)
    assert not g.isVisible()
    assert (150.0, pytest.approx(30.6)) in ed.document.shapes[-1].geom.corner_points()


def test_object_snap_off_falls_back_to_grid(ed):
    add(ed, rect(20.4, 30.6, 40, 20))
    ed.actions_by_name["object_snap"].trigger()
    assert not ed.object_snap.enabled and not ed.actions_by_name["object_snap"].isChecked()
    ed.set_tool(Tool.RECT)
    drag(ed, (60.9, 50.2), (90.0, 80.0))
    g = ed.document.shapes[-1].geom
    assert (g.x, g.y) == (61.0, 50.0)
    ed.actions_by_name["object_snap"].trigger()
    assert ed.object_snap.enabled


def test_alt_suspends_object_snap_during_a_drag(ed):
    add(ed, rect(20.4, 30.6, 40, 20))
    ed.set_tool(Tool.RECT)
    drag(ed, (60.9, 50.2), (90.0, 80.0), mods=ALT)
    g = ed.document.shapes[-1].geom
    assert (g.x, g.y) == (61.0, 50.0)
    assert not ed.object_snap.suspended  # nach dem Zug zurückgesetzt


def test_move_aligns_selection_edge_to_other_object(ed):
    a, b = add(ed, rect(20.4, 30.6, 40, 20), rect(150, 150, 30, 30))
    ed.set_selection([b.id])
    # b nach links unter a ziehen: linke Kante 0.4 neben a.x (20.4) → rastet ein.
    drag(ed, (165, 165), (165 - 129.2, 165 + 20), release=False)
    assert ed.object_snap.guides.isVisible()
    ed.tools.release(QPointF(165 - 129.2, 185), NO)
    g = ed.document.shape(b.id).geom
    assert g.x == pytest.approx(20.4)
    assert g.y == pytest.approx(170.0)  # y ohne Objekt in Reichweite: Raster
    assert ed.undo_stack.undoText() == "Verschieben"
    ed.undo_stack.undo()
    assert ed.document.shape(b.id).geom.x == pytest.approx(150)
    assert ed.document.shape(a.id).geom.x == pytest.approx(20.4)


def test_move_centre_to_centre_and_group_moves_as_one(ed):
    a, b, c = add(ed, rect(50.3, 50.3, 40, 40), rect(200, 200, 10, 10), rect(215, 200, 10, 10))
    for s in (b, c):
        ed.document.set_groups(s.id, ("g",))
    ed.set_selection([b.id])
    assert sorted(ed.selection) == sorted([b.id, c.id])
    # Gruppenbox 200..225 × 200..210 (Mitte 212.5 / 205) auf die Mitte von a (70.3 / 70.3)
    drag(ed, (205, 205), (205 - 141.9, 205 - 134.4))
    gb, gc = ed.document.shape(b.id).geom, ed.document.shape(c.id).geom
    assert (gb.x + 12.5, gb.y + 5) == (pytest.approx(70.3), pytest.approx(70.3))
    assert gc.x - gb.x == pytest.approx(15)


def test_shift_move_keeps_locked_axis(ed):
    a, b = add(ed, rect(20.4, 30.6, 40, 20), rect(150, 31, 30, 30))
    ed.set_selection([b.id])
    t = ed.tools
    t.press(QPointF(165, 45), NO)  # Umschalt erst beim Ziehen (Umschalt-Klick ändert die Auswahl)
    t.move(QPointF(150, 45.0), SHIFT, True)
    t.move(QPointF(135, 45.0), SHIFT, True)  # waagerecht; Oberkante 31 nahe 30.6
    t.release(QPointF(135, 45.0), SHIFT)
    g = ed.document.shape(b.id).geom
    assert g.y == pytest.approx(31.0) and g.x == pytest.approx(120.0)


def test_resize_handle_snaps_to_other_edge(ed):
    a, b = add(ed, rect(100.6, 20, 30, 30), rect(20, 20, 40, 30))
    ed.set_selection([b.id])
    ed.tools.press(QPointF(60, 35), NO)  # rechter Mittelgriff (3)
    assert ed.tools._mode == "resize"
    ed.tools.move(QPointF(80, 35), NO, True)
    ed.tools.move(QPointF(101.0, 35), NO, True)
    ed.tools.release(QPointF(101.0, 35), NO)
    g = ed.document.shape(b.id).geom
    assert g.x + g.w == pytest.approx(100.6) and g.x == pytest.approx(20)
    assert ed.undo_stack.undoText() == "Skalieren"


def test_node_drag_snaps_to_node_of_other_shape(ed):
    from lumacut_canvas import nodes
    tri = Shape.from_points("polygon", [(150.35, 150.35), (190, 150), (170, 190)], "?")
    sq = Shape.from_points("polygon", [(20, 20), (40, 20), (40, 40), (20, 40)], "?")
    add(ed, tri, sq)
    ed.set_tool(Tool.NODE)
    t = ed.tools
    t.press(QPointF(30, 30), NO)
    t.release(QPointF(30, 30), NO)
    assert ed.node_editor.shape_id == sq.id
    t.press(QPointF(40, 40), NO)
    assert ed.node_editor.node == 2
    t.move(QPointF(100, 100), NO, True)
    t.move(QPointF(150.9, 150.0), NO, True)
    t.release(QPointF(150.9, 150.0), NO)
    assert nodes.scene_points(ed.document.shape(sq.id))[2] == pytest.approx((150.35, 150.35))
    assert ed.object_snap.targets is None


def test_polygon_points_snap_and_keep_targets_between_clicks(ed):
    add(ed, rect(20.4, 30.6, 40, 20))
    ed.set_tool(Tool.POLYGON)
    t = ed.tools
    for p in ((60.0, 50.0), (100.0, 100.0), (20.0, 100.3)):
        t.press(QPointF(*p), NO)
        t.release(QPointF(*p), NO)
    assert ed.object_snap.targets is not None  # Polygon läuft noch
    t.move(QPointF(20.9, 120.0), NO, False)    # Vorschau-Punkt auf der linken Kante
    assert t._hover == (pytest.approx(20.4), 120.0)
    assert t._poly[0] == (pytest.approx(60.4), pytest.approx(50.6))
    assert t._poly[2][0] == pytest.approx(20.4)
    shape = t.finish_polygon()
    assert shape is not None and ed.object_snap.targets is None
    assert not ed.object_snap.guides.isVisible()


def test_ngon_centre_snaps_to_circle_centre(ed):
    (c,) = add(ed, Shape("ellipse", Geometry(80.3, 80.3, 40, 40), "?"))
    ed.set_tool(Tool.NGON)
    drag(ed, (100.6, 100.9), (100.6, 80.0))
    s = ed.document.shapes[-1]
    assert s.id != c.id
    cx, cy = s.geom.center()
    assert (cx, cy) == (pytest.approx(100.3, abs=0.6), pytest.approx(100.3, abs=0.6))
    pts = [(s.geom.x + u * s.geom.w, s.geom.y + v * s.geom.h) for u, v in s.points]
    mx = sum(p[0] for p in pts) / len(pts)
    assert mx == pytest.approx(100.3, abs=1e-6)


def test_text_click_snaps_to_corner(ed, monkeypatch):
    from PySide6.QtWidgets import QInputDialog
    add(ed, rect(20.4, 30.6, 40, 20))
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: ("Hallo", True)))
    ed.set_tool(Tool.TEXT)
    ed.tools.press(QPointF(20.9, 51.0), NO)
    ed.tools.release(QPointF(20.9, 51.0), NO)
    txt = ed.document.shapes[-1]
    assert txt.kind == "text" and (txt.geom.x, txt.geom.y) == (pytest.approx(20.4), pytest.approx(50.6))
    assert ed.object_snap.targets is None


def test_hidden_layer_is_ignored_locked_layer_snaps(ed):
    d = ed.document
    lock, hid = Layer(name="Material", locked=True), Layer(name="aus", visible=False)
    d.layers.extend([lock, hid])
    add(ed, rect(20.4, 30.6, 40, 20, layer=lock.id), rect(200.4, 200.6, 40, 20, layer=hid.id))
    ed.set_tool(Tool.RECT)
    drag(ed, (20.9, 31.0), (50, 60))
    assert ed.document.shapes[-1].geom.x == pytest.approx(20.4)
    drag(ed, (200.9, 201.0), (250, 260))
    assert ed.document.shapes[-1].geom.x == pytest.approx(201.0)


def test_zoom_and_touch_mode_change_the_reach(ed):
    add(ed, rect(20.4, 30.6, 40, 20))
    ed.set_tool(Tool.RECT)
    drag(ed, (62.4, 52.6), (90, 80))  # 2 mm × 2 mm neben der Ecke: außerhalb 1.75 mm
    assert ed.document.shapes[-1].geom.x == pytest.approx(62.0)
    ed.undo_stack.undo()  # sonst fängt die eigene Ecke (62, 53)
    ed.set_touch_mode(True, persist=False)
    assert ed.object_snap.tolerance() == pytest.approx(14 / ZOOM)
    drag(ed, (62.4, 52.6), (90, 80))
    assert ed.document.shapes[-1].geom.x == pytest.approx(60.4)
    ed.set_touch_mode(False, persist=False)


def test_escape_cancels_and_hides_guides(ed):
    add(ed, rect(20.4, 30.6, 40, 20))
    ed.set_tool(Tool.RECT)
    drag(ed, (60.9, 50.2), (90, 80), release=False)
    assert ed.object_snap.guides.isVisible()
    ed.tools.key_press(QKeyEvent(QEvent.KeyPress, Qt.Key_Escape, NO))
    assert not ed.object_snap.guides.isVisible() and ed.object_snap.targets is None
    assert len(ed.document.shapes) == 1


def test_status_names_the_snap(ed):
    msgs = []
    ed.statusMessage.connect(msgs.append)
    add(ed, rect(20.4, 30.6, 40, 20))
    ed.set_tool(Tool.RECT)
    drag(ed, (60.9, 50.2), (90, 80))
    assert "Fang: Ecke" in msgs


def test_rubber_band_and_roi_never_object_snap(ed):
    add(ed, rect(20.4, 30.6, 40, 20))
    ed.set_selection([])
    drag(ed, (10, 10), (60.9, 50.2))  # Rahmenauswahl
    assert ed.object_snap.targets is None and not ed.object_snap.guides.isVisible()


def test_snapped_rects_share_an_edge_in_gcode(ed):
    a, = add(ed, rect(20.4, 30.6, 40, 20))
    ed.set_tool(Tool.RECT)
    drag(ed, (60.9, 30.2), (90, 50.6))
    b = ed.document.shapes[-1]
    assert b.geom.x == pytest.approx(60.4) and b.geom.y == pytest.approx(30.6)
    assert b.geom.y + b.geom.h == pytest.approx(50.6)
    from lumacut_canvas.toolpath import parse_gcode
    from lumacut_job.planner import optimized_document_gcode
    g = optimized_document_gcode(ed.document, scan_offsets=None)
    pi_check(g)
    assert parse_gcode(g).cut_length_mm == pytest.approx(2 * (40 + 20) + 2 * (29.6 + 20), rel=1e-3)


# --- Schalter, Einstellungen, Menüs ------------------------------------------------------
def test_action_in_action_bar_with_icon_and_shortcut(ed):
    a = ed.actions_by_name["object_snap"]
    assert a.text() == "An Objekten fangen" and a.isCheckable() and a.isChecked()
    assert a.shortcut().toString() == "Alt+Shift+S"
    assert a in ed.action_bar.actions()
    acts = ed.action_bar.actions()
    assert acts.index(a) == acts.index(ed.actions_by_name["snap"]) + 1
    assert not a.icon().isNull()
    from lumacut_canvas import icons
    assert "objsnap" in icons.available()


def test_choice_is_saved_in_settings(qapp, tmp_path):
    from PySide6.QtCore import QSettings
    st = QSettings(str(tmp_path / "s.ini"), QSettings.IniFormat)
    e = CanvasEditor(settings=st)
    try:
        assert e.object_snap.enabled
        e.actions_by_name["object_snap"].trigger()
        assert st.value(objsnap_ui.SETTINGS_KEY) in (False, "false")
    finally:
        e.close()
    e2 = CanvasEditor(settings=QSettings(str(tmp_path / "s.ini"), QSettings.IniFormat))
    try:
        assert not e2.object_snap.enabled and not e2.actions_by_name["object_snap"].isChecked()
    finally:
        e2.close()
    assert objsnap_ui.load_setting(None) is None


def test_main_window_alt_shift_s_is_unique(qapp, tmp_path):
    from PySide6.QtCore import QSettings
    from PySide6.QtGui import QAction, QKeySequence
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(tmp_path))
    QSettings.setDefaultFormat(QSettings.IniFormat)
    main = pytest.importorskip("main")
    w = main.LumaCutStudio()
    try:
        owners = [a for a in w.findChildren(QAction) if a.shortcut() == QKeySequence("Alt+Shift+S")]
        assert [a.text() for a in owners] == ["An Objekten fangen"]
        owners[0].trigger()
        assert not w.canvas.object_snap.enabled
        owners[0].trigger()
        assert w.canvas.object_snap.enabled
    finally:
        w.canvas.undo_stack.setClean()
        w.close()
