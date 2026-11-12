"""Verschachteln (LightBurn *Nesting* – Quick Nest / True Nest, xTool „Intelligentes
Verschachteln“): Abstände und Randabstand garantiert, Startecke, Material-Rechteck,
Drehung, echte Form gegen Hüllbox, enthaltene Objekte, ausgesparte Objekte, Gruppen,
gedrehte Ellipsen am Rand der Arbeitsfläche, Teile, die nicht passen, Ablesewerte,
G-Code (gleiche Schnittlänge, Pi-Wächter), Stege und Datei, Dialog, Editor (ein
Undo-Schritt, Abbrechen, gesperrte Ebene, Meldungen), Menüs und Kürzel im Hauptfenster."""

from __future__ import annotations

import math

import pytest
from _pi_guard import pi_check
from shapely.geometry import Point

from lumacut_canvas import nesting, ngon
from lumacut_canvas.commands import AddShapesCommand
from lumacut_canvas.editor import CanvasEditor
from lumacut_canvas.model import Document, Geometry, Layer, Shape, constrain_geometry
from lumacut_canvas.toolpath import parse_gcode
from lumacut_canvas.workarea import WORK_HEIGHT_MM, WORK_WIDTH_MM, Rect
from lumacut_job.planner import optimized_document_gcode

EPS = 1e-6


@pytest.fixture
def doc(qapp):
    return Document()


def add(doc, *shapes):
    return [doc.add_shape(s).id for s in shapes]


def rects(doc, n, w, h, x=10.0, y=10.0):
    lid = doc.active_layer_id
    return add(doc, *[Shape("rect", Geometry(x, y, w, h), lid) for _ in range(n)])


def apply(doc, res):
    for i, g in res.moves.items():
        doc.set_geometry(i, g)


def fps(doc, ids):
    return [nesting.shape_footprint(doc.shape(i)) for i in ids]


def min_gap(doc, ids):
    f = fps(doc, ids)
    return min(f[a].distance(f[b]) for a in range(len(f)) for b in range(a + 1, len(f)))


def edge_gap(doc, ids, r: Rect):
    out = []
    for f in fps(doc, ids):
        x0, y0, x1, y1 = f.bounds
        out.append(min(x0 - r.x, y0 - r.y, r.right - x1, r.bottom - y1))
    return min(out)


# --- Abstände, Ecke, Bereich ------------------------------------------------------------

def test_rectangles_keep_spacing_and_margin_and_start_at_the_machine_origin(doc):
    ids = rects(doc, 12, 40, 25)
    res = nesting.nest(doc, ids, spacing=2.0, margin=3.0)
    assert res.total == res.placed == 12 and not res.unplaced
    apply(doc, res)
    assert min_gap(doc, ids) >= 2.0 - EPS
    work = Rect(0, 0, WORK_WIDTH_MM, WORK_HEIGHT_MM)
    assert edge_gap(doc, ids, work) >= 3.0 - EPS
    # Start oben rechts (Nullpunkt der Maschine): eine Reihe entlang der Oberkante
    u = res.used
    assert u.right == pytest.approx(WORK_WIDTH_MM - 3.0, abs=2 * res.res)
    assert u.y == pytest.approx(3.0, abs=2 * res.res)
    assert u.h < 60          # 12 Teile à 40 mm passen in zwei Reihen (keine Drehung nötig)
    assert res.res == pytest.approx(max(0.25, (WORK_WIDTH_MM - 4.0) / nesting.MAX_CELLS))


@pytest.mark.parametrize("corner", nesting.CORNERS)
def test_every_start_corner_anchors_the_parts_there(doc, corner):
    ids = rects(doc, 5, 30, 20)
    res = nesting.nest(doc, ids, corner=corner, spacing=1.0, margin=2.0)
    u, tol = res.used, 2 * res.res
    if corner.startswith("top"):
        assert u.y == pytest.approx(2.0, abs=tol)
    else:
        assert u.bottom == pytest.approx(WORK_HEIGHT_MM - 2.0, abs=tol)
    if corner.endswith("right"):
        assert u.right == pytest.approx(WORK_WIDTH_MM - 2.0, abs=tol)
    else:
        assert u.x == pytest.approx(2.0, abs=tol)
    assert u.h == pytest.approx(20.0) and u.w == pytest.approx(5 * 30 + 4 * 1.0, abs=5 * tol)


def test_spacing_is_tight_within_the_raster(doc):
    ids = rects(doc, 2, 50, 20)
    res = nesting.nest(doc, ids, spacing=4.0, margin=0.0, rotation="none")
    apply(doc, res)
    gap = min_gap(doc, ids)
    assert 4.0 - EPS <= gap <= 4.0 + 3 * res.res
    res0 = nesting.nest(doc, ids, spacing=0.0, margin=0.0, rotation="none")
    apply(doc, res0)
    assert 0.0 <= min_gap(doc, ids) <= 3 * res0.res     # 0 mm: Kanten liegen fast aneinander


def test_selected_rectangle_is_the_material_and_stays(doc):
    lid = doc.active_layer_id
    (mat,) = add(doc, Shape("rect", Geometry(150, 120, 120, 80), lid))
    ids = rects(doc, 6, 30, 20)
    assert nesting.container_candidate(doc, ids + [mat]) == mat
    before = doc.shape(mat).geom.copy()
    res = nesting.nest(doc, ids + [mat], container_id=mat, spacing=2.0, margin=2.0)
    assert mat not in res.moves and res.total == 6 and res.placed == 6
    apply(doc, res)
    assert doc.shape(mat).geom == before
    mr = doc.shape(mat).bounds()
    assert edge_gap(doc, ids, mr) >= 2.0 - EPS
    assert res.used.right == pytest.approx(mr.right - 2.0, abs=2 * res.res)
    assert res.used.y == pytest.approx(mr.y + 2.0, abs=2 * res.res)
    assert res.container == mr


def test_container_candidate_rules(doc):
    lid = doc.active_layer_id
    small = add(doc, Shape("rect", Geometry(10, 10, 20, 20), lid))[0]
    big_parts = rects(doc, 3, 40, 40)
    assert nesting.container_candidate(doc, big_parts + [small]) is None   # zu klein
    assert nesting.container_candidate(doc, big_parts) is None             # nur gleich große Teile
    (mat,) = add(doc, Shape("rect", Geometry(0, 0, 200, 200), lid))
    assert nesting.container_candidate(doc, [mat]) is None                 # nichts zu verschachteln
    assert nesting.container_candidate(doc, big_parts + [mat]) == mat
    doc.shape(mat).geom = Geometry(0, 0, 200, 200, 30.0)
    assert nesting.container_candidate(doc, big_parts + [mat]) is None     # gedreht
    doc.shape(mat).geom = Geometry(0, 0, 200, 200)
    doc.shape(mat).groups = ("g",)
    assert nesting.container_candidate(doc, big_parts + [mat]) is None     # gruppiert


# --- Drehen, Form -------------------------------------------------------------------------

def test_rotation_lets_a_long_part_fit_and_none_leaves_it_in_place(doc):
    lid = doc.active_layer_id
    (mat,) = add(doc, Shape("rect", Geometry(200, 10, 60, 320), lid))
    (bar,) = add(doc, Shape("rect", Geometry(10, 10, 300, 20), lid))
    res = nesting.nest(doc, [bar, mat], container_id=mat, rotation="none")
    assert res.placed == 0 and res.unplaced == [[bar]] and bar not in res.moves
    assert res.readout() == "0 von 1 Teil(en) verschachtelt · 1 passen nicht (bleiben an ihrer Stelle)"
    res = nesting.nest(doc, [bar, mat], container_id=mat, rotation="90")
    assert res.placed == 1 and res.rotated == 1
    apply(doc, res)
    g = doc.shape(bar).geom
    assert g.rot in (90.0, 270.0) and (g.w, g.h) == (300, 20)
    b = doc.shape(bar).bounds()
    assert b.w == pytest.approx(20) and b.h == pytest.approx(300)
    assert edge_gap(doc, [bar], doc.shape(mat).bounds()) >= 2.0 - EPS


def test_true_shape_interlocks_triangles_better_than_bounding_boxes(doc):
    lid = doc.active_layer_id
    tri = [(0, 0), (60, 0), (0, 40)]
    ids = add(doc, *[Shape.from_points("polygon", [(x + 20, y + 20) for x, y in tri], lid)
                     for _ in range(8)])
    true = nesting.nest(doc, ids, rotation="90", form="true", spacing=1.0)
    box = nesting.nest(doc, ids, rotation="90", form="box", spacing=1.0)
    assert true.placed == box.placed == 8
    assert true.used.w * true.used.h < 0.8 * box.used.w * box.used.h
    assert true.utilization > box.utilization
    apply(doc, true)
    assert min_gap(doc, ids) >= 1.0 - EPS


def test_45_degree_steps_and_rotated_ellipses_stay_inside_the_work_area(doc):
    lid = doc.active_layer_id
    ids = add(doc, *[Shape("ellipse", Geometry(10, 10, 20 + 3 * (k % 5), 15), lid) for k in range(30)])
    ids += add(doc, *[ngon.make_shape(lid, 100, 100, 12, 5, 0.4) for _ in range(30)])
    res = nesting.nest(doc, ids, rotation="45", corner="bottom_left")
    assert res.placed == 60 and res.rotated > 0
    # die Objektbox gedrehter Ellipsen ist größer als ihr Umriss – sie muss trotzdem
    # in der Arbeitsfläche liegen, sonst schöbe das Dokument das Teil zurück
    for i, g in res.moves.items():
        assert constrain_geometry(g) == g
    apply(doc, res)
    assert min_gap(doc, ids) >= 2.0 - EPS
    assert edge_gap(doc, ids, Rect(0, 0, WORK_WIDTH_MM, WORK_HEIGHT_MM)) >= 2.0 - EPS
    assert any(doc.shape(i).geom.rot % 90 for i in ids)


# --- Einheiten, Hindernisse ---------------------------------------------------------------

def test_engraving_inside_a_plate_moves_with_it_unless_switched_off(doc):
    lid = doc.active_layer_id
    plate, logo, other = add(doc, Shape("rect", Geometry(100, 100, 60, 40), lid),
                             Shape("ellipse", Geometry(120, 110, 20, 20), lid),
                             Shape("rect", Geometry(10, 200, 30, 30), lid))
    res = nesting.nest(doc, [plate, logo, other], rotation="none")
    assert res.total == 2
    p0, l0 = doc.shape(plate).geom, doc.shape(logo).geom
    p1, l1 = res.moves[plate], res.moves[logo]
    assert (l1.x - p1.x, l1.y - p1.y) == pytest.approx((l0.x - p0.x, l0.y - p0.y))
    res = nesting.nest(doc, [plate, logo, other], rotation="90")
    p1, l1 = res.moves[plate], res.moves[logo]
    assert math.dist(p1.center(), l1.center()) == pytest.approx(math.dist(p0.center(), l0.center()))
    off = nesting.nest(doc, [plate, logo, other], keep_contained=False, rotation="none")
    assert off.total == 3
    apply(doc, off)
    assert min_gap(doc, [plate, logo, other]) >= 2.0 - EPS


def test_groups_move_as_one_part(doc):
    lid = doc.active_layer_id
    a, b = add(doc, Shape("rect", Geometry(10, 10, 20, 20), lid), Shape("rect", Geometry(50, 10, 20, 20), lid))
    for i in (a, b):
        doc.shape(i).groups = ("g1",)
    (c,) = rects(doc, 1, 30, 30, 100, 100)
    res = nesting.nest(doc, [a, b, c], rotation="none")
    assert res.total == 2
    ga, gb = res.moves[a], res.moves[b]
    assert (gb.x - ga.x, gb.y - ga.y) == pytest.approx((40.0, 0.0))
    apply(doc, res)
    # Gruppenteile behalten ihre 20 mm Lücke, zum dritten Teil gilt der Abstand
    f = fps(doc, [a, b, c])
    assert min(f[0].distance(f[2]), f[1].distance(f[2])) >= 2.0 - EPS


def test_other_objects_are_kept_free_and_hidden_layers_ignored(doc):
    lid = doc.active_layer_id
    (obst,) = add(doc, Shape("ellipse", Geometry(WORK_WIDTH_MM - 80, 0, 80, 60), lid))
    hidden = doc.add_layer(Layer("Versteckt", visible=False))
    add(doc, Shape("rect", Geometry(0, 100, 360, 100), hidden.id))
    ids = rects(doc, 6, 40, 30, 10, 250)
    res = nesting.nest(doc, ids, spacing=2.0)
    assert res.obstacles == 1 and res.placed == 6
    assert res.readout().endswith(" · 1 andere(s) Objekt(e) ausgespart")
    apply(doc, res)
    ob = nesting.shape_footprint(doc.shape(obst))
    assert min(ob.distance(f) for f in fps(doc, ids)) >= 2.0 - EPS
    over = nesting.nest(doc, ids, avoid_others=False)
    assert over.obstacles == 0 and over.used.right == pytest.approx(WORK_WIDTH_MM - 2.0, abs=2 * over.res)


def test_open_lines_and_text_nest_with_spacing(doc):
    lid = doc.active_layer_id
    t = Shape("text", Geometry(10, 10, 60, 20), lid, text="LumaCut")
    line = Shape("line", Geometry(20, 50, 80, 30), lid)
    path = Shape.from_points("path", [(10, 100), (40, 130), (70, 100)], lid)
    ids = add(doc, t, line, path, *[Shape("rect", Geometry(200, 200, 25, 25), lid) for _ in range(4)])
    res = nesting.nest(doc, ids, spacing=3.0)
    assert res.placed == 7
    apply(doc, res)
    assert min_gap(doc, ids) >= 3.0 - EPS


def test_parts_that_do_not_fit_stay_in_place(doc):
    lid = doc.active_layer_id
    (mat,) = add(doc, Shape("rect", Geometry(0, 0, 100, 60), lid))
    ids = rects(doc, 6, 40, 25, 200, 200)
    res = nesting.nest(doc, ids + [mat], container_id=mat, spacing=2.0, margin=2.0, rotation="none")
    assert res.placed == 4 and len(res.unplaced) == 2   # 2 × 2 Teile à 40 × 25 mm in 100 × 60
    assert all(i not in res.moves for u in res.unplaced for i in u)
    assert "· 2 passen nicht (bleiben an ihrer Stelle)" in res.readout()


def test_readout_and_invalid_options(doc):
    assert nesting.nest(doc, []).readout() == "Keine Teile zum Verschachteln"
    ids = rects(doc, 2, 40, 20)
    # 100 mm Bereich: Raster 0,25 mm geht in 40 + 2 mm auf – Abstand exakt 2 mm
    res = nesting.nest(doc, ids, spacing=2.0, margin=2.0, rotation="none", area=Rect(0, 0, 100, 100))
    assert res.res == 0.25
    assert res.readout() == "2 von 2 Teil(en) verschachtelt · belegt 82,0 × 20,0 mm · Materialnutzung 98 %"
    for kw in ({"rotation": "30"}, {"corner": "middle"}, {"form": "circle"}):
        with pytest.raises(ValueError):
            nesting.nest(doc, ids, **kw)
    assert nesting.nest(doc, ids, area=Rect(0, 0, 10, 10)).unplaced == [[ids[0]], [ids[1]]]
    assert nesting.nest(doc, ids, margin=60.0, area=Rect(0, 0, 100, 100)).placed == 0


# --- Unverändert weiterverarbeitet ------------------------------------------------------

def test_gcode_cut_length_unchanged_pi_guard_tabs_and_file(doc):
    lid = doc.active_layer_id
    doc.update_layer(lid, kerf_mm=0.1, tab_count=2, tab_width_mm=1.0)
    ids = add(doc, *[ngon.make_shape(lid, 60, 60, 15, 5, 0.4) for _ in range(5)])
    ids += add(doc, *[Shape("rect", Geometry(150, 150, 40, 20), lid) for _ in range(3)])
    star = doc.shape(ids[0])
    star.tabs = ((0.5, 0.0),)
    before_tabs = star.tab_points()
    before = parse_gcode(optimized_document_gcode(doc, scan_offsets=None)).cut_length_mm
    res = nesting.nest(doc, ids, rotation="90")
    apply(doc, res)
    g = optimized_document_gcode(doc, scan_offsets=None)
    pi_check(g)
    assert parse_gcode(g).cut_length_mm == pytest.approx(before, rel=1e-3)
    s = doc.shape(ids[0])
    (old_tab,) = before_tabs
    (new_tab,) = s.tab_points()
    assert new_tab != pytest.approx(old_tab)          # Steg wandert mit dem Teil
    assert nesting.shape_footprint(s).exterior.distance(Point(new_tab)) < 0.05
    again = Document.from_dict(doc.to_dict())
    assert [x.geom for x in again.shapes] == [x.geom for x in doc.shapes]
    assert [x.kind for x in again.shapes] == [x.kind for x in doc.shapes]


# --- Dialog / Editor ----------------------------------------------------------------------

@pytest.fixture
def ed(qapp):
    e = CanvasEditor()
    e.resize(1000, 700)
    e.show()
    qapp.processEvents()
    yield e
    e.undo_stack.setClean()
    e.close()


def _add(ed, shapes):
    ed.undo_stack.push(AddShapesCommand(ed.document, list(shapes)))
    return [s.id for s in shapes]


def test_dialog_defaults_values_and_material_choice(qapp):
    from PySide6.QtWidgets import QDialogButtonBox
    from lumacut_canvas.nesting_ui import NestDialog
    dlg = NestDialog(3, None)
    assert dlg.values() == {"container": "work", "spacing": pytest.approx(2.0),
                            "margin": pytest.approx(2.0), "rotation": "90", "corner": "top_right",
                            "form": "true", "keep_contained": True, "avoid_others": True}
    assert not dlg.container.model().item(dlg.container.findData("rect")).isEnabled()
    assert dlg.readout.text() == "3 Teil(e) ausgewählt"
    assert dlg.buttons.button(QDialogButtonBox.Ok).text() == "Verschachteln"
    assert [dlg.rotation.itemText(i) for i in range(dlg.rotation.count())] == \
        ["Nicht drehen", "In 90°-Schritten", "In 45°-Schritten"]
    assert dlg.corner.itemText(0) == "Oben rechts (Nullpunkt)"
    dlg.deleteLater()
    vals = {"container": "rect", "spacing": 1.5, "margin": 0.0, "rotation": "45",
            "corner": "bottom_left", "form": "box", "keep_contained": False, "avoid_others": False}
    dlg = NestDialog(2, Rect(0, 0, 300, 200.5), values=vals)
    assert dlg.values() == {**vals, "spacing": pytest.approx(1.5), "margin": pytest.approx(0.0)}
    assert dlg.readout.text() == "2 Teil(e) ausgewählt · Material 300,0 × 200,5 mm"
    dlg.deleteLater()
    dlg = NestDialog(0, None)
    assert not dlg.buttons.button(QDialogButtonBox.Ok).isEnabled()
    dlg.deleteLater()


def test_editor_nest_one_undo_step_keeps_selection_and_values(ed):
    lid = ed.document.active_layer_id
    mat = Shape("rect", Geometry(100, 100, 150, 100), lid)
    parts = [Shape("rect", Geometry(10, 10, 30, 20), lid) for _ in range(4)]
    keep = Shape("ellipse", Geometry(300, 300, 10, 10), lid)
    _add(ed, [mat, *parts, keep])
    seen = []
    ed.arranger.nester.ask = lambda n, cont: seen.append((n, cont)) or \
        {"container": "rect", "spacing": 2.0, "margin": 2.0, "rotation": "none",
         "corner": "top_left", "form": "true", "keep_contained": True, "avoid_others": True}
    msgs = []
    ed.statusMessage.connect(msgs.append)
    sel = [mat.id] + [p.id for p in parts]
    ed.set_selection(sel)
    ed.actions_by_name["nest"].trigger()
    assert seen == [(4, mat.bounds())]
    assert ed.undo_stack.undoText() == "Verschachteln"
    assert sorted(ed.selection) == sorted(sel)
    xs = sorted(round(ed.document.shape(p.id).bounds().x, 3) for p in parts)
    assert xs[0] == pytest.approx(102.0, abs=0.5) and ed.document.shape(mat.id).geom == mat.geom
    assert ed.document.shape(keep.id).geom == Geometry(300, 300, 10, 10)
    assert msgs[-1].startswith("Verschachteln: 4 von 4 Teil(en) verschachtelt · belegt ")
    assert ed.arranger.nester.last["corner"] == "top_left"
    ed.undo_stack.undo()
    assert all(ed.document.shape(p.id).geom == Geometry(10, 10, 30, 20) for p in parts)
    assert ed.actions_by_name["nest"].shortcut().toString() == "Alt+Shift+N"


def test_editor_nothing_selected_cancel_material_only_and_locked_layer(ed):
    lid = ed.document.active_layer_id
    mat = Shape("rect", Geometry(100, 100, 150, 100), lid)
    part = Shape("rect", Geometry(10, 10, 30, 20), lid)
    _add(ed, [mat, part])
    msgs = []
    ed.statusMessage.connect(msgs.append)
    ed.arranger.nester.ask = lambda n, cont: pytest.fail("kein Dialog erwartet")
    ed.set_selection([])
    ed.actions_by_name["nest"].trigger()
    assert msgs[-1] == "Zum Verschachteln Teile auswählen (optional ein Rechteck als Material)."
    ed.arranger.nester.ask = lambda n, cont: None                       # Abbrechen
    ed.set_selection([mat.id, part.id])
    ed.actions_by_name["nest"].trigger()
    assert ed.undo_stack.undoText() != "Verschachteln"
    assert ed.document.shape(part.id).geom == Geometry(10, 10, 30, 20)
    ed.document.update_layer(lid, locked=True)
    ed.arranger.nester.ask = lambda n, cont: pytest.fail("kein Dialog erwartet")
    ed.actions_by_name["nest"].trigger()
    assert msgs[-1] == "Zum Verschachteln Teile auswählen (optional ein Rechteck als Material)."


def test_dialog_offers_the_material_rectangle_from_the_selection(ed):
    lid = ed.document.active_layer_id
    mat = Shape("rect", Geometry(100, 100, 150, 100), lid)
    part = Shape("rect", Geometry(10, 10, 30, 20), lid)
    _add(ed, [mat, part])
    ed.set_selection([mat.id, part.id])
    from lumacut_canvas.nesting_ui import NestDialog
    shown = []
    orig = NestDialog.exec
    NestDialog.exec = lambda self: shown.append(self.values()) or 0
    try:
        ed.arranger.nester.ask(1, mat.bounds())
        ed.arranger.nester.last = {"container": "work", "spacing": 5.0}
        ed.arranger.nester.ask(1, mat.bounds())
        ed.arranger.nester.ask(1, None)
    finally:
        NestDialog.exec = orig
    assert shown[0]["container"] == "rect" and shown[1]["container"] == "rect"
    assert shown[1]["spacing"] == pytest.approx(5.0) and shown[2]["container"] == "work"


def test_nest_in_arrange_menu_and_context_menu(ed):
    from PySide6.QtCore import QPointF
    _add(ed, [Shape("rect", Geometry(10, 10, 20, 10), ed.document.active_layer_id)])
    texts = [a.text() for a in ed.arrange_button.menu().actions() if a.text()]
    assert texts[-1] == "Verschachteln …" and texts[-2] == "Entlang Pfad kopieren …"
    assert texts[-3] == "Kreis-Array …"
    menu = ed.build_context_menu(QPointF(20, 15))
    sub = next(a.menu() for a in menu.actions() if a.menu() is not None
               and a.menu().objectName() == "ArrangeMenu")
    assert "Verschachteln …" in [a.text() for a in sub.actions()]


def test_main_window_alt_shift_n_is_unique_and_nests_parts(qapp, tmp_path):
    from PySide6.QtCore import QSettings
    from PySide6.QtGui import QAction, QKeySequence
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(tmp_path))
    QSettings.setDefaultFormat(QSettings.IniFormat)
    main = pytest.importorskip("main")
    w = main.LumaCutStudio()
    try:
        owners = [a for a in w.findChildren(QAction) if a.shortcut() == QKeySequence("Alt+Shift+N")]
        assert [a.text() for a in owners] == ["Verschachteln …"]
        c = w.canvas
        lid = c.document.active_layer_id
        shapes = [ngon.make_shape(lid, 150, 150, 20, 6) for _ in range(5)]
        c.undo_stack.push(AddShapesCommand(c.document, shapes))
        c.arranger.nester.ask = lambda n, cont: {"rotation": "90"}
        c.set_selection([s.id for s in shapes])
        owners[0].trigger()
        ids = [s.id for s in shapes]
        assert min_gap(c.document, ids) >= 2.0 - EPS
        assert c.undo_stack.undoText() == "Verschachteln"
    finally:
        w.canvas.undo_stack.setClean()
        w.close()
