"""Finger-joint box generator (xTool Studio „Box Generator“) – lumacut_job.boxgen / boxgen_qt."""

from __future__ import annotations

import itertools
import math
from dataclasses import replace

import pytest
from _pi_guard import pi_check
from shapely.geometry import Polygon
from shapely.ops import unary_union

from lumacut_canvas.model import Document, Shape
from lumacut_canvas.shape_paths import shape_polygons
from lumacut_canvas.toolpath import parse_gcode
from lumacut_canvas.workarea import WORK_HEIGHT_MM, WORK_WIDTH_MM
from lumacut_job import boxgen, generated
from lumacut_job.boxgen import BoxSpec


def _panel(spec, name):
    return next(p for p in boxgen.panels(spec) if p.name == name)


# --- finger count -----------------------------------------------------------------------------

def test_finger_count_is_odd_closest_and_at_least_three():
    assert boxgen.finger_count(94.0, 10.0, 3.0) == 9
    assert boxgen.finger_count(100.0, 10.0, 3.0) in (9, 11)
    for length, finger in itertools.product((20, 37.5, 74, 94, 150, 333), (4, 6, 10, 15, 25)):
        n = boxgen.finger_count(length, finger, 3.0)
        assert n % 2 == 1 and n >= 3
        odd = [k for k in range(1, 200, 2) if length / k >= 3.0]
        best = min(odd, key=lambda k: abs(length / k - finger))
        assert abs(length / n - finger) <= abs(length / best - finger) + 1e-9 or n == 3
    assert boxgen.finger_count(60.0, 100.0, 3.0) == 3          # wide fingers: still 3
    assert boxgen.finger_count(7.0, 2.0, 3.0) == 1             # too short for 3 × thickness
    assert boxgen.finger_count(0.0, 10.0, 3.0) == 1


def test_finger_segments_never_thinner_than_the_material():
    for length in (12.0, 20.0, 31.0, 50.0):
        n = boxgen.finger_count(length, 2.0, 6.0)
        assert n == 1 or length / n >= 6.0 - 1e-9


# --- spec ----------------------------------------------------------------------------------------

def test_spec_defaults_and_normalize_clamps():
    s = BoxSpec().normalized()
    assert (s.width_mm, s.depth_mm, s.height_mm, s.thickness_mm) == (100.0, 80.0, 50.0, 3.0)
    assert s.kerf_mm == boxgen.DEFAULT_KERF and s.lid and not s.inner
    n = BoxSpec(width_mm=1, depth_mm=5000, height_mm=float("nan"), thickness_mm=50,
                finger_mm=0.1, kerf_mm=-1, spacing_mm=999, lid=0, inner=1).normalized()
    assert n.width_mm == boxgen.SIZE_RANGE[0] and n.depth_mm == boxgen.SIZE_RANGE[1]
    assert n.height_mm == 50.0 and n.thickness_mm == boxgen.THICKNESS_RANGE[1]
    assert n.finger_mm == boxgen.FINGER_RANGE[0] and n.kerf_mm == 0.0
    assert n.spacing_mm == boxgen.SPACING_RANGE[1] and n.lid is False and n.inner is True
    assert BoxSpec(width_mm="abc").normalized().width_mm == 100.0


def test_outer_and_inner_sizes():
    s = BoxSpec(100, 80, 50, thickness_mm=3)
    assert s.outer() == (100, 80, 50) and s.inside() == pytest.approx((94, 74, 44))
    i = BoxSpec(100, 80, 50, thickness_mm=3, inner=True)
    assert i.outer() == pytest.approx((106, 86, 56)) and i.inside() == pytest.approx((100, 80, 50))
    o = BoxSpec(100, 80, 50, thickness_mm=3, inner=True, lid=False)
    assert o.outer() == pytest.approx((106, 86, 53)) and o.inside() == pytest.approx((100, 80, 50))
    assert BoxSpec(100, 80, 50, thickness_mm=4, lid=False).inside() == pytest.approx((92, 72, 46))


# --- panels --------------------------------------------------------------------------------------

def test_six_panels_with_lid_five_without():
    assert [p.name for p in boxgen.panels(BoxSpec())] == list(boxgen.PANEL_NAMES)
    assert [p.name for p in boxgen.panels(BoxSpec(lid=False))] == list(boxgen.PANEL_NAMES[:5])


def test_panel_sizes_without_kerf_are_the_outer_faces():
    s = BoxSpec(120, 70, 45, thickness_mm=4, kerf_mm=0)
    for p in boxgen.panels(s):
        xs = [x for x, _ in p.outline]
        ys = [y for _, y in p.outline]
        assert (min(xs), min(ys)) == pytest.approx((0, 0))
        assert (max(xs), max(ys)) == pytest.approx(p.size)
    assert {p.name: p.size for p in boxgen.panels(s)} == {
        "Vorne": (120, 45), "Hinten": (120, 45), "Links": (70, 45), "Rechts": (70, 45),
        "Boden": (120, 70), "Deckel": (120, 70)}


def test_every_edge_is_axis_parallel_and_corners_are_square():
    for p in boxgen.panels(BoxSpec(kerf_mm=0.2)):
        ring = p.outline
        assert Polygon(ring).is_valid
        for (x0, y0), (x1, y1) in zip(ring, ring[1:] + ring[:1]):
            assert abs(x0 - x1) < 1e-6 or abs(y0 - y1) < 1e-6


def _owner_counts(spec, xs, ys, zs):
    """For 3D points (arrays): how many panels contain each point (kerf 0)."""
    import numpy as np
    import shapely
    s = spec.normalized()
    W, D, H = s.outer()
    t = s.thickness_mm
    count = np.zeros(len(xs), dtype=int)
    for p in boxgen.panels(s):
        a, b = p.size
        poly = Polygon([(px, b - py) for px, py in p.outline])        # v up again
        if p.name in ("Vorne", "Hinten"):
            w = ys if p.name == "Vorne" else D - ys
            u, v = xs, zs
        elif p.name in ("Links", "Rechts"):
            w = xs if p.name == "Links" else W - xs
            u, v = ys, zs
        else:
            w = zs if p.name == "Boden" else H - zs
            u, v = xs, ys
        inside = shapely.contains_xy(poly, u, v)
        count += ((w > 0) & (w < t) & inside).astype(int)
    return count


@pytest.mark.parametrize("spec", [
    BoxSpec(100, 80, 50, thickness_mm=3, finger_mm=10, kerf_mm=0),
    BoxSpec(60, 140, 35, thickness_mm=4, finger_mm=7, kerf_mm=0),
    BoxSpec(100, 80, 50, thickness_mm=3, finger_mm=10, kerf_mm=0, lid=False),
    BoxSpec(40, 40, 40, thickness_mm=6, finger_mm=25, kerf_mm=0),
    BoxSpec(30, 30, 20, thickness_mm=5, finger_mm=2, kerf_mm=0, inner=True),
])
def test_assembled_box_fills_the_shell_exactly_once(spec):
    """Fold the flat panels back into 3D: every point of the walls belongs to exactly one
    panel (fingers meet slots, no overlap, no hole), the inside stays empty."""
    import numpy as np
    s = spec.normalized()
    W, D, H = s.outer()
    t = s.thickness_mm
    def coords(L):
        n = int(L / (t / 2.0))
        return (np.arange(n) + 0.37) * L / n          # off every segment border
    X, Y, Z = np.meshgrid(coords(W), coords(D), coords(H), indexing="ij")
    xs, ys, zs = X.ravel(), Y.ravel(), Z.ravel()
    on_wall = (xs < t) | (xs > W - t) | (ys < t) | (ys > D - t) | (zs < t)
    if s.lid:
        on_wall |= zs > H - t
    c = _owner_counts(s, xs, ys, zs)
    assert (c[on_wall] == 1).all(), list(zip(xs[on_wall][c[on_wall] != 1][:5],
                                              ys[on_wall][c[on_wall] != 1][:5],
                                              zs[on_wall][c[on_wall] != 1][:5]))
    assert (c[~on_wall] == 0).all()
    assert on_wall.sum() > 100 and (~on_wall).sum() > 0


def test_open_box_walls_have_a_straight_top_edge():
    s = BoxSpec(100, 80, 50, kerf_mm=0, lid=False)
    for name in ("Vorne", "Hinten", "Links", "Rechts"):
        p = _panel(s, name)
        top = [pt for pt in p.outline if abs(pt[1]) < 1e-9]       # y = 0 is the top on screen
        xs = sorted(x for x, _ in top)
        if name in ("Vorne", "Hinten"):
            assert xs == pytest.approx([0, 100])                  # whole width, corners included
        else:
            assert xs == pytest.approx([3, 77])                   # corners belong to front / back


def _pieces(geom):
    return sum(1 for g in getattr(geom, "geoms", [geom]) if g.area > 1e-6)


def test_tab_counts_match_their_slots():
    s = BoxSpec(100, 80, 50, kerf_mm=0)
    nx = boxgen.finger_count(94, 10, 3)
    front, bottom = _panel(s, "Vorne"), _panel(s, "Boden")
    assert front.fingers["bottom"] == bottom.fingers["bottom"] == nx
    # front: (nx + 1) / 2 fingers along its lower edge, the bottom plate (nx - 1) / 2 tabs
    fp = Polygon(front.outline)
    strip = fp.intersection(Polygon([(3, 47), (97, 47), (97, 50), (3, 50)]))
    assert _pieces(strip) == (nx + 1) // 2
    bp = Polygon(bottom.outline)
    strip = bp.intersection(Polygon([(3, 77), (97, 77), (97, 80), (3, 80)]))
    assert _pieces(strip) == (nx - 1) // 2


def test_kerf_grows_every_panel_by_half_the_kerf_all_round():
    base = {p.name: Polygon(p.outline) for p in boxgen.panels(BoxSpec(kerf_mm=0))}
    for p in boxgen.panels(BoxSpec(kerf_mm=0.2)):
        a, b = p.size
        xs = [x for x, _ in p.outline]
        ys = [y for _, y in p.outline]
        assert (max(xs) - min(xs), max(ys) - min(ys)) == pytest.approx((a + 0.2, b + 0.2))
        want = base[p.name].buffer(0.1, join_style=2, mitre_limit=10.0)
        got = Polygon([(x - 0.1, y - 0.1) for x, y in p.outline])
        assert got.symmetric_difference(want).area < 1e-6


def test_too_small_box_is_refused_in_german():
    with pytest.raises(ValueError, match="zu klein"):
        boxgen.panels(BoxSpec(10, 10, 10, thickness_mm=6))


# --- layout --------------------------------------------------------------------------------------

def test_layout_panels_apart_inside_the_work_area():
    s = BoxSpec(100, 80, 50, spacing_mm=4)
    placed, (lw, lh), fits = boxgen.layout(s)
    assert fits and lw <= WORK_WIDTH_MM and lh <= WORK_HEIGHT_MM
    polys = [Polygon(r) for _, r in placed]
    for a, b in itertools.combinations(polys, 2):
        assert a.distance(b) >= 4 - 1e-6
    u = unary_union(polys).bounds
    assert u[0] >= -1e-9 and u[1] >= -1e-9
    assert (u[2], u[3]) == pytest.approx((lw, lh))
    # same panels, only moved / turned
    for (name, ring), p in zip(placed, boxgen.panels(s)):
        assert name == p.name
        assert Polygon(ring).area == pytest.approx(Polygon(p.outline).area)
        assert Polygon(ring).length == pytest.approx(Polygon(p.outline).length)


def test_layout_turns_tall_panels_when_that_is_needed_to_fit():
    s = BoxSpec(60, 60, 300, thickness_mm=3)              # tall walls only fit lying down
    placed, (lw, lh), fits = boxgen.layout(s)
    assert fits
    wall = Polygon(dict(placed)["Vorne"]).bounds
    assert wall[2] - wall[0] > wall[3] - wall[1]


def test_box_too_big_for_the_work_area_is_refused():
    s = BoxSpec(300, 250, 200)
    _placed, _size, fits = boxgen.layout(s)
    assert not fits
    with pytest.raises(ValueError, match="passen nicht auf die Arbeitsfläche"):
        boxgen.box_shapes(boxgen.centered(s), "L")


def test_box_shapes_one_group_closed_polygons_centred():
    s = boxgen.centered(BoxSpec())
    shapes = boxgen.box_shapes(s, "L")
    assert len(shapes) == 6 and {sh.kind for sh in shapes} == {"polygon"}
    assert len({sh.groups for sh in shapes}) == 1 and all(len(sh.groups) == 1 for sh in shapes)
    assert all(sh.layer_id == "L" and not sh.rings for sh in shapes)
    b = unary_union([Polygon(shape_polygons(sh)[0]) for sh in shapes]).bounds
    assert ((b[0] + b[2]) / 2, (b[1] + b[3]) / 2) == pytest.approx(
        (WORK_WIDTH_MM / 2, WORK_HEIGHT_MM / 2), abs=1e-3)
    want = sorted(round(Polygon(p.outline).area, 3) for p in boxgen.panels(s))
    assert sorted(round(Polygon(shape_polygons(sh)[0]).area, 3) for sh in shapes) == want


def test_describe_reads_sizes_parts_and_fingers():
    text = boxgen.describe(BoxSpec(100, 80, 50, lid=False))
    assert "Außen 100.0 × 80.0 × 50.0 mm" in text and "innen 94.0 × 74.0 × 47.0 mm" in text
    assert "5 Teile (offen)" in text and "Zinken 9 / 7 / 5" in text


# --- generated object, file, G-code ----------------------------------------------------------------

def test_generator_meta_round_trip_without_position():
    s = boxgen.centered(BoxSpec(90, 60, 40, thickness_mm=4, finger_mm=8, kerf_mm=0.15, lid=False))
    shapes = generated.tag(boxgen.box_shapes(s, "L"), s)
    meta = shapes[0].generator
    assert meta["kind"] == "box" and "x" not in meta["spec"] and "y" not in meta["spec"]
    assert generated.spec_from_meta(meta) == replace(s, x=0.0, y=0.0)
    again = Shape.from_dict(shapes[0].to_dict())
    assert generated.spec_from_meta(again.generator) == replace(s, x=0.0, y=0.0)
    assert generated.scaled_spec(s, (1.5, 0.7)) == s           # box sizes never follow the handles
    assert generated.LABELS["box"] == "Box"


def _doc(shapes, **layer):
    doc = Document()
    lid = doc.active_layer_id
    if layer:
        doc.update_layer(lid, **layer)
    for sh in shapes:
        sh.layer_id = lid
        doc.add_shape(sh)
    return doc


def test_gcode_is_pi_safe_and_cuts_every_panel_once(qapp):
    from lumacut_job.planner import optimized_document_gcode
    s = boxgen.centered(BoxSpec(kerf_mm=0.1))
    shapes = boxgen.box_shapes(s, "L")
    doc = _doc(shapes)
    g = optimized_document_gcode(doc, scan_offsets=None)
    pi_check(g)
    perimeter = sum(Polygon(shape_polygons(sh)[0]).length for sh in shapes)
    assert parse_gcode(g).cut_length_mm == pytest.approx(perimeter, abs=0.1)


def test_saved_project_keeps_the_box_and_old_projects_are_unchanged(qapp, tmp_path):
    from lumacut_canvas.document_io import load_document, save_document
    from lumacut_job.planner import optimized_document_gcode
    plain = _doc([Shape.from_points("polygon", [(20, 20), (60, 20), (60, 50)], "L")])
    p0 = save_document(plain, tmp_path / "alt.lcproj")
    assert '"box"' not in p0.read_text(encoding="utf-8")
    g0 = optimized_document_gcode(plain, scan_offsets=None)
    assert optimized_document_gcode(load_document(p0), scan_offsets=None) == g0
    s = boxgen.centered(BoxSpec(lid=False))
    doc = _doc(generated.tag(boxgen.box_shapes(s, "L"), s))
    p1 = save_document(doc, tmp_path / "box.lcproj")
    back = load_document(p1)
    assert len(back.shapes) == 5
    assert generated.spec_from_meta(back.shapes[0].generator) == replace(s, x=0.0, y=0.0)
    assert optimized_document_gcode(back, scan_offsets=None) == optimized_document_gcode(
        doc, scan_offsets=None)


# --- dialog --------------------------------------------------------------------------------------

def test_dialog_defaults_spec_and_material_thickness_of_the_layer(qapp):
    from lumacut_canvas.model import Layer
    from lumacut_job.boxgen_qt import BoxDialog
    dlg = BoxDialog()
    assert dlg.spec() == BoxSpec().normalized()
    assert dlg.ok_button.isEnabled() and "Außen 100.0" in dlg.info.text()
    assert len(dlg.preview.rings) == 6 and dlg.preview.fits
    dlg.lid.setChecked(False)
    assert len(dlg.preview.rings) == 5 and "offen" in dlg.info.text()
    dlg.deleteLater()
    layer = Layer("Schnitt", thickness_mm=4.0)
    d2 = BoxDialog(active_layer=layer)
    assert d2.spec().thickness_mm == 4.0 and not d2.new_layer.isChecked()
    d2.deleteLater()
    spec = BoxSpec(90, 60, 40, thickness_mm=4, finger_mm=8, kerf_mm=0.15, lid=False, inner=True,
                   spacing_mm=6)
    d3 = BoxDialog(spec=spec, active_layer=layer)
    assert d3.spec() == spec.normalized()
    d3.deleteLater()


def test_dialog_warnings_and_disabled_ok(qapp):
    from lumacut_canvas.model import Layer
    from lumacut_job.boxgen_qt import BoxDialog
    dlg = BoxDialog(active_layer=Layer("Gravur", fill_mode="hatch"))
    assert dlg.new_layer.isChecked()
    dlg.new_layer.setChecked(False)
    assert "graviert statt geschnitten" in dlg.info.text()
    dlg.width_mm.setValue(300)
    dlg.depth_mm.setValue(250)
    dlg.height_mm.setValue(200)
    assert not dlg.ok_button.isEnabled() and "passt nicht" in dlg.info.text()
    assert not dlg.preview.fits
    dlg.width_mm.setValue(10)
    dlg.depth_mm.setValue(10)
    dlg.height_mm.setValue(10)
    dlg.thickness.setValue(6)
    assert not dlg.ok_button.isEnabled() and "zu klein" in dlg.info.text()
    assert dlg.preview.rings == []
    dlg.deleteLater()
    d2 = BoxDialog(active_layer=Layer("Schnitt", kerf_mm=0.1))
    assert "doppelt" in d2.info.text()
    d2.kerf.setValue(0.0)
    assert "doppelt" not in d2.info.text()
    d2.kerf.setValue(0.1)
    d2.finger.setValue(2.0)
    assert "brechen leicht" in d2.info.text()
    d2.deleteLater()


def test_dialog_touch_controls_are_44_px(qapp):
    from lumacut_job.boxgen_qt import BoxDialog
    dlg = BoxDialog(touch=True)
    for w in (dlg.width_mm, dlg.depth_mm, dlg.height_mm, dlg.thickness, dlg.finger, dlg.kerf,
              dlg.spacing, dlg.inner, dlg.lid, dlg.new_layer, *dlg.buttons.buttons()):
        assert w.minimumHeight() >= 44
    assert dlg.kerf.toolTip() and "Kerf-Versatz" in dlg.kerf.toolTip()
    dlg.deleteLater()
    mouse = BoxDialog()
    assert mouse.width_mm.minimumHeight() < 44
    mouse.deleteLater()


# --- main window -----------------------------------------------------------------------------------

@pytest.fixture
def win(qapp, monkeypatch, tmp_path):
    from PySide6.QtCore import QSettings
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(tmp_path))
    QSettings.setDefaultFormat(QSettings.IniFormat)
    main = pytest.importorskip("main")
    w = main.LumaCutStudio()
    yield w
    w.canvas.undo_stack.setClean()
    w.close()
    w.deleteLater()
    qapp.processEvents()


def test_window_action_shortcut_menus(win):
    from PySide6.QtGui import QAction, QKeySequence
    a = win.job_tools.box_action
    assert a.objectName() == "box_generator_action" and a.text() == "Box-Generator…"
    assert a.shortcut() == QKeySequence("Alt+Shift+B")
    assert [b.text() for b in win.findChildren(QAction)
            if b is not a and b.shortcut() == a.shortcut()] == []
    assert "xTool" in a.toolTip()
    assert a in win.main_view.design_menu.actions() and a in win.main_view.job_menu.actions()


def test_window_insert_on_cut_layer_one_undo_step_and_gcode(win, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    from lumacut_job.planner import optimized_document_gcode
    tools, doc, stack = win.job_tools, win.canvas.document, win.canvas.undo_stack
    layer = doc.active_layer
    layer.fill_mode = "none"
    n_layers, n_shapes, depth = len(doc.layers), len(doc.shapes), stack.index()
    ids = tools.box(BoxSpec(80, 60, 40))
    assert len(ids) == 6 and len(doc.layers) == n_layers
    assert all(doc.shape(i).layer_id == layer.id for i in ids)
    assert len({doc.shape(i).groups for i in ids}) == 1
    assert sorted(win.canvas.selection) == sorted(ids)
    assert stack.index() == depth + 1
    assert "Box eingefügt (6 Teile" in win.statusBar().currentMessage()
    g = optimized_document_gcode(doc)
    pi_check(g)
    stack.undo()
    assert len(doc.shapes) == n_shapes
    warned = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: warned.append(a[2]))
    assert tools.box(BoxSpec(300, 250, 200)) == []
    assert warned and "Arbeitsfläche" in warned[0] and len(doc.shapes) == n_shapes


def test_window_new_cut_layer_for_a_fill_or_locked_layer(win):
    tools, doc, stack = win.job_tools, win.canvas.document, win.canvas.undo_stack
    doc.active_layer.fill_mode = "hatch"
    n_layers, n_shapes = len(doc.layers), len(doc.shapes)
    ids = tools.box(BoxSpec(thickness_mm=4, lid=False))
    assert len(ids) == 5 and len(doc.layers) == n_layers + 1
    new = doc.layer(doc.shape(ids[0]).layer_id)
    assert new.name == "Box" and new.fill_mode == "none" and new.thickness_mm == 4.0
    stack.undo()
    assert len(doc.layers) == n_layers and len(doc.shapes) == n_shapes
    doc.active_layer.fill_mode = "none"
    doc.active_layer.locked = True
    ids = tools.box(BoxSpec())
    assert doc.layer(doc.shape(ids[0]).layer_id).name == "Box"


def test_window_dialog_cancel_and_accept(win, monkeypatch):
    from PySide6.QtWidgets import QDialog

    from lumacut_job import boxgen_qt
    doc = win.canvas.document
    doc.active_layer.fill_mode = "none"
    seen = []
    monkeypatch.setattr(boxgen_qt.BoxDialog, "exec",
                        lambda self: seen.append(self) or QDialog.Rejected)
    n = len(doc.shapes)
    assert win.job_tools.box() == [] and len(doc.shapes) == n
    monkeypatch.setattr(boxgen_qt.BoxDialog, "exec", lambda self: (
        self.height_mm.setValue(30), QDialog.Accepted)[1])
    ids = win.job_tools.box()
    assert len(ids) == 6
    spec = generated.spec_from_meta(doc.shape(ids[0]).generator)
    assert spec.height_mm == 30


def test_re_edit_box_keeps_place_layer_and_group(win, monkeypatch):
    from lumacut_canvas.commands import SetGeometryCommand
    from lumacut_job.generated_qt import edit_dialog, generated_unit, unit_spec
    tools, doc, stack = win.job_tools, win.canvas.document, win.canvas.undo_stack
    doc.active_layer.fill_mode = "none"
    ids = tools.box(BoxSpec(80, 60, 40))
    group = doc.shape(ids[0]).groups[-1]
    old = {i: doc.shape(i).geom.copy() for i in ids}
    stack.push(SetGeometryCommand(doc, old, {i: g.translated(-30, 10) for i, g in old.items()},
                                  "Verschieben"))
    win.canvas.set_selection(ids[:1])
    unit = generated_unit(win.canvas)
    assert unit.kind == "box" and unit.label == "Box"
    got = unit_spec(unit)
    assert (got.width_mm, got.depth_mm, got.height_mm) == (80, 60, 40)
    dlg = edit_dialog(unit, got, doc.layer(unit.layer_id), win, touch=True)
    assert dlg.windowTitle() == "Box bearbeiten" and dlg.ok_button.text() == "Übernehmen"
    assert not dlg.new_layer.isVisible() and not dlg.new_layer.isChecked()
    assert dlg.width_mm.minimumHeight() >= 44 and dlg.spec() == got
    dlg.deleteLater()
    depth = stack.index()
    new_ids = tools.edit_generated(replace(got, lid=False))
    assert len(new_ids) == 5 and stack.index() == depth + 1
    u2 = generated.find_unit(doc, new_ids[0])
    assert u2.center == pytest.approx(unit.center, abs=1e-6) and u2.group == group
    assert u2.layer_id == unit.layer_id
    stack.undo()
    assert all(doc.has_shape(i) for i in ids)
    # double click on a panel opens the box dialog, in touch mode with 44 px controls
    from lumacut_job import boxgen_qt
    opened = []
    monkeypatch.setattr(boxgen_qt.BoxDialog, "exec", lambda self: opened.append(
        (self.windowTitle(), self.kerf.minimumHeight())) or 0)
    win.canvas.set_touch_mode(True, persist=False)
    assert tools.edit_generated_at(ids[2]) is True and opened == [("Box bearbeiten", 44)]
    win.canvas.set_touch_mode(False, persist=False)
    assert tools.edit_generated_at(ids[2]) is True and opened[1][1] < 44


def test_panels_of_a_box_scale_with_their_size():
    """Same pattern on a bigger box: more fingers, same finger width (± one odd step)."""
    small = boxgen.panels(BoxSpec(60, 60, 40, finger_mm=10))
    big = boxgen.panels(BoxSpec(180, 60, 40, finger_mm=10))
    assert big[0].fingers["bottom"] > small[0].fingers["bottom"]
    for p in big:
        for edge, n in p.fingers.items():
            if n > 1:
                length = {"Vorne": (174, 40), "Hinten": (174, 40), "Links": (54, 40),
                          "Rechts": (54, 40), "Boden": (174, 54), "Deckel": (174, 54)}[p.name]
                L = length[0] if edge in ("bottom", "top") else (
                    40 if p.name in ("Vorne", "Hinten", "Links", "Rechts") else length[1])
                assert 10 * 2 / 3 - 1e-9 <= L / n <= 10 * 2 + 1e-9
    assert math.isclose(sum(Polygon(p.outline).area for p in small[:2]),
                        2 * Polygon(small[0].outline).area)
