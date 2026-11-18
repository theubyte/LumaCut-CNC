"""Living hinge (flex / kerf-bend pattern) generator – lumacut_job.hinge / hinge_qt."""

from __future__ import annotations

import itertools
import math
from dataclasses import replace

import pytest
from _pi_guard import pi_check
from shapely.geometry import LineString, Polygon, box as sbox

from lumacut_canvas.model import Document, Shape
from lumacut_canvas.toolpath import parse_gcode
from lumacut_canvas.workarea import WORK_HEIGHT_MM, WORK_WIDTH_MM
from lumacut_job import generated, hinge
from lumacut_job.hinge import HingeSpec


def _geom(sl):
    return Polygon(sl.points) if sl.closed else LineString(sl.points)


# --- spec ----------------------------------------------------------------------------------------

def test_spec_defaults_and_normalize_clamps():
    s = HingeSpec().normalized()
    assert (s.width_mm, s.height_mm, s.pattern, s.horizontal) == (60.0, 50.0, "lines", False)
    assert (s.cut_mm, s.bridge_mm, s.pitch_mm, s.thickness_mm) == (20.0, 3.0, 2.0, 3.0)
    assert s.open_edges and not s.frame and s.margin_mm == 10.0
    n = HingeSpec(width_mm=1, height_mm=5000, pattern="spiral", cut_mm=float("nan"), bridge_mm=0,
                  pitch_mm=99, thickness_mm=50, margin_mm=-3, horizontal=1, open_edges=0,
                  frame=1).normalized()
    assert n.width_mm == hinge.SIZE_RANGE[0] and n.height_mm == hinge.SIZE_RANGE[1]
    assert n.pattern == "lines" and n.cut_mm == 20.0 and n.bridge_mm == hinge.BRIDGE_RANGE[0]
    assert n.pitch_mm == hinge.PITCH_RANGE[1] and n.thickness_mm == hinge.THICKNESS_RANGE[1]
    assert n.margin_mm == 0.0 and n.horizontal is True and n.open_edges is False and n.frame is True
    assert HingeSpec(width_mm="abc").normalized().width_mm == 60.0
    assert HingeSpec(pattern="wave").normalized().pattern == "wave"


def test_across_along_and_part_size():
    s = HingeSpec(80, 40)
    assert (s.across(), s.along(), s.part_size()) == (80, 40, (80, 40))
    h = HingeSpec(80, 40, horizontal=True, frame=True, margin_mm=5)
    assert (h.across(), h.along(), h.part_size()) == (40, 80, (80, 50))
    assert HingeSpec(80, 40, frame=True, margin_mm=5).part_size() == (90, 40)


# --- layout of the slits -----------------------------------------------------------------------------

def test_columns_pitch_apart_centred_with_half_pitch_margin():
    for width, pitch in itertools.product((5, 13.3, 60, 101), (0.5, 1.5, 2, 3.7, 20)):
        cols = hinge.columns(HingeSpec(width_mm=width, pitch_mm=pitch))
        assert cols == sorted(cols)
        assert all(b - a == pytest.approx(pitch) for a, b in zip(cols, cols[1:]))
        assert cols[0] == pytest.approx(width - cols[-1], abs=1e-5)
        if len(cols) > 1:
            assert cols[0] >= pitch / 2 - 1e-6
    assert hinge.columns(HingeSpec(width_mm=5, pitch_mm=20)) == [2.5]
    assert len(hinge.columns(HingeSpec(width_mm=60, pitch_mm=2))) == 30


def test_slit_plan_nearest_count_fills_the_field_exactly():
    for height, cut, bridge in itertools.product((12, 50, 77.7, 300), (5, 20, 33), (1, 3, 6)):
        s = HingeSpec(height_mm=height, cut_mm=cut, bridge_mm=bridge)
        if height - 2 * bridge < 1.0:
            with pytest.raises(ValueError, match="zu kurz"):
                hinge.slit_plan(s)
            continue
        n, la = hinge.slit_plan(s)
        assert n == max(1, round((height - bridge) / (cut + bridge)))
        assert n * la + (n + 1) * bridge == pytest.approx(height) and la >= 1.0
    with pytest.raises(ValueError, match="zu kurz"):
        hinge.slit_plan(HingeSpec(height_mm=6, bridge_mm=3))


def test_odd_lines_bridge_in_the_middle_of_the_even_slits_and_open_edges():
    s = HingeSpec(width_mm=10, height_mm=50, cut_mm=20, bridge_mm=3, pitch_mm=2)
    n, la = hinge.slit_plan(s)
    cuts = hinge.slits(s)
    cols = hinge.columns(s)
    even = sorted(p for sl in cuts if sl.points[0][0] == cols[0] for p in (sl.points[0][1], sl.points[-1][1]))
    odd = sorted(p for sl in cuts if sl.points[0][0] == cols[1] for p in (sl.points[0][1], sl.points[-1][1]))
    assert len(even) == 2 * n and even[0] == pytest.approx(3.0) and even[-1] == pytest.approx(47.0)
    assert odd[0] == 0.0 and odd[-1] == 50.0
    # every odd bridge sits in the middle of an even slit
    for k in range(n):
        mid = 3.0 + la / 2 + k * (la + 3.0)
        assert any(a == pytest.approx(mid - 1.5) and b == pytest.approx(mid + 1.5)
                   for a, b in zip(odd[1::2], odd[2::2]))
    closed = hinge.slits(replace(s, open_edges=False))
    ys = [p[1] for sl in closed for p in sl.points]
    assert min(ys) == pytest.approx(3.0) and max(ys) == pytest.approx(47.0)


def test_straight_slits_are_open_axis_parallel_paths_and_turn_horizontal():
    cuts = hinge.slits(HingeSpec())
    assert all(not sl.closed and len(sl.points) == 2 for sl in cuts)
    assert all(sl.points[0][0] == sl.points[1][0] for sl in cuts)
    s = hinge.centered(HingeSpec(80, 40, horizontal=True))
    for pts, closed in hinge.part_cuts(s):
        assert not closed and pts[0][1] == pytest.approx(pts[1][1])      # along X now
    xs = [p[0] for pts, _ in hinge.part_cuts(s) for p in pts]
    assert min(xs) == pytest.approx(s.x) and max(xs) == pytest.approx(s.x + 80)


@pytest.mark.parametrize("pattern", hinge.PATTERNS)
@pytest.mark.parametrize("open_edges", (True, False))
def test_cuts_stay_in_the_field_and_never_touch_each_other(pattern, open_edges):
    s = HingeSpec(width_mm=20, height_mm=45, pattern=pattern, open_edges=open_edges,
                  cut_mm=12, bridge_mm=2.5, pitch_mm=2.0)
    cuts = hinge.slits(s)
    field = sbox(0, 0, 20, 45).buffer(1e-6)
    geoms = [_geom(sl) for sl in cuts]
    assert all(field.contains(g) for g in geoms)
    for a, b in itertools.combinations(geoms, 2):
        assert a.distance(b) >= min(0.39 * s.pitch_mm, s.bridge_mm) - 1e-6
    assert all(g.is_valid and (g.length if isinstance(g, LineString) else g.area) > 0 for g in geoms)


def test_wave_slits_are_s_curves_on_their_line():
    s = HingeSpec(pattern="wave")
    _n, la = hinge.slit_plan(s)
    cols = hinge.columns(s)
    for sl in hinge.slits(s):
        u = sl.points[0][0]
        assert u in cols and sl.points[-1][0] == pytest.approx(u, abs=1e-5) and not sl.closed
        dev = max(abs(x - u) for x, _ in sl.points)
        assert dev == pytest.approx(hinge.WAVE_AMPLITUDE * s.pitch_mm, rel=0.05)
        assert all(math.dist(p, q) <= hinge.STEP_MM * 1.5 for p, q in zip(sl.points, sl.points[1:]))


def test_diamond_holes_closed_inside_and_open_half_holes_at_the_edge():
    s = HingeSpec(pattern="diamond", width_mm=10, height_mm=50)
    cuts = hinge.slits(s)
    inner = [sl for sl in cuts if sl.closed]
    edge = [sl for sl in cuts if not sl.closed]
    assert inner and all(len(sl.points) == 4 for sl in inner)
    assert all(Polygon(sl.points).bounds[2] - Polygon(sl.points).bounds[0] == pytest.approx(
        2 * hinge.DIAMOND_HALF * s.pitch_mm) for sl in inner)
    assert edge and all(sl.points[0][1] in (0.0, 50.0) and sl.points[-1][1] == sl.points[0][1]
                        for sl in edge)
    shut = hinge.slits(replace(s, open_edges=False))
    assert all(sl.closed for sl in shut)


def test_frame_is_a_closed_rectangle_with_margin_around_the_field():
    s = hinge.centered(HingeSpec(60, 50, frame=True, margin_mm=8))
    cuts = hinge.part_cuts(s)
    frame_pts, closed = cuts[-1]
    assert closed and Polygon(frame_pts).bounds == pytest.approx((s.x, s.y, s.x + 76, s.y + 50))
    slits_x = [p[0] for pts, _ in cuts[:-1] for p in pts]
    assert min(slits_x) >= s.x + 8 + s.pitch_mm / 2 - 1e-6
    assert max(slits_x) <= s.x + 68 - s.pitch_mm / 2 + 1e-6


def test_refused_too_many_slits_and_too_big():
    with pytest.raises(ValueError, match="Schlitze"):
        hinge.slits(HingeSpec(width_mm=1000, height_mm=1000, pitch_mm=0.5, cut_mm=5))
    big = HingeSpec(width_mm=WORK_WIDTH_MM + 10, height_mm=50)
    assert not hinge.fits(big)
    with pytest.raises(ValueError, match="passt nicht auf die Arbeitsfläche"):
        hinge.hinge_shapes(hinge.centered(big), "L")
    edge = HingeSpec(width_mm=WORK_WIDTH_MM - 20, frame=True, margin_mm=20)
    assert not hinge.fits(edge) and hinge.fits(replace(edge, margin_mm=10))


# --- bend, readout -------------------------------------------------------------------------------------

def test_bend_radius_and_width_for_are_inverse():
    for r, a, t in itertools.product((0, 5, 12.5, 40), (30, 90, 180), (1.5, 3, 6)):
        w = hinge.width_for(r, a, t)
        assert hinge.bend_radius(w, a, t) == pytest.approx(r)
    assert hinge.width_for(10, 90, 3) == pytest.approx(11.5 * math.pi / 2)
    assert hinge.bend_radius(1, 180, 6) == 0.0


def test_describe_and_warnings():
    text = hinge.describe(HingeSpec())
    assert "Gerade Schlitze: 30 Linien" in text and "Schnittlänge" in text
    assert "Biegung 90° um Innenradius ≈ 36.7 mm" in text and "Teil 60.0 × 50.0 mm" in text
    assert hinge.warnings(HingeSpec()) == []
    w = hinge.warnings(HingeSpec(pitch_mm=0.6, bridge_mm=1.0))
    assert any("verbrennen" in x for x in w) and any("reißen" in x for x in w)
    assert any("steif" in x for x in hinge.warnings(HingeSpec(cut_mm=5, bridge_mm=4)))
    assert any("biegt sich schwer" in x for x in hinge.warnings(HingeSpec(pitch_mm=8)))
    assert "Rauten" in hinge.describe(HingeSpec(pattern="diamond"))
    assert hinge.cut_length(HingeSpec()) == pytest.approx(
        sum(LineString(sl.points).length for sl in hinge.slits(HingeSpec())))


def test_hinge_shapes_one_group_centred():
    s = hinge.centered(HingeSpec(pattern="diamond", frame=True))
    shapes = hinge.hinge_shapes(s, "L")
    assert {sh.kind for sh in shapes} == {"path", "polygon"}
    assert len({sh.groups for sh in shapes}) == 1 and all(len(sh.groups) == 1 for sh in shapes)
    x0, y0, x1, y1 = generated.extent(shapes)
    assert ((x0 + x1) / 2, (y0 + y1) / 2) == pytest.approx((WORK_WIDTH_MM / 2, WORK_HEIGHT_MM / 2))
    assert (x1 - x0, y1 - y0) == pytest.approx(s.part_size())


# --- generated object, file, G-code ----------------------------------------------------------------

def test_generator_meta_round_trip_and_scaling_keeps_the_slits():
    s = hinge.centered(HingeSpec(70, 40, pattern="wave", cut_mm=15, bridge_mm=2, pitch_mm=1.5,
                                 frame=True, margin_mm=6, open_edges=False))
    shapes = generated.tag(hinge.hinge_shapes(s, "L"), s)
    meta = shapes[0].generator
    assert meta["kind"] == "hinge" and "x" not in meta["spec"]
    assert generated.spec_from_meta(meta) == replace(s, x=0.0, y=0.0)
    again = Shape.from_dict(shapes[-1].to_dict())
    assert generated.spec_from_meta(again.generator) == replace(s, x=0.0, y=0.0)
    sc = generated.scaled_spec(s, (1.5, 0.5))
    assert (sc.width_mm, sc.height_mm, sc.margin_mm) == (105.0, 20.0, 9.0)
    assert (sc.cut_mm, sc.bridge_mm, sc.pitch_mm) == (15.0, 2.0, 1.5)
    hz = generated.scaled_spec(replace(s, horizontal=True), (1.0, 2.0))
    assert hz.margin_mm == 12.0
    assert generated.LABELS["hinge"] == "Flex-Scharnier"


def _doc(shapes, **layer):
    doc = Document()
    lid = doc.active_layer_id
    if layer:
        doc.update_layer(lid, **layer)
    for sh in shapes:
        sh.layer_id = lid
        doc.add_shape(sh)
    return doc


@pytest.mark.parametrize("pattern", hinge.PATTERNS)
def test_gcode_is_pi_safe_cuts_every_slit_once_and_the_frame_last(qapp, pattern):
    from lumacut_job.planner import optimized_document_gcode
    s = hinge.centered(HingeSpec(pattern=pattern, frame=True, margin_mm=5))
    doc = _doc(hinge.hinge_shapes(s, "L"))
    g = optimized_document_gcode(doc, scan_offsets=None)
    pi_check(g)
    w, h = s.part_size()
    assert parse_gcode(g).cut_length_mm == pytest.approx(hinge.cut_length(s) + 2 * (w + h), abs=0.1)
    moves = [ln for ln in g.splitlines() if ln.startswith(("G0", "G1"))]
    tail = moves[-4:]
    assert all(ln.startswith("G1") for ln in tail)
    def x_of(ln):
        return round(float(ln.split("X")[1].split()[0]), 3)
    all_x = [x_of(ln) for ln in moves if "X" in ln]
    assert {x_of(ln) for ln in tail} == {min(all_x), max(all_x)}     # frame outline
    assert max(all_x) - min(all_x) == pytest.approx(w, abs=1e-3)


def test_saved_project_keeps_the_hinge_and_old_projects_are_unchanged(qapp, tmp_path):
    from lumacut_canvas.document_io import load_document, save_document
    from lumacut_job.planner import optimized_document_gcode
    plain = _doc([Shape.from_points("polygon", [(20, 20), (60, 20), (60, 50)], "L")])
    p0 = save_document(plain, tmp_path / "alt.lcproj")
    assert '"hinge"' not in p0.read_text(encoding="utf-8")
    g0 = optimized_document_gcode(plain, scan_offsets=None)
    assert optimized_document_gcode(load_document(p0), scan_offsets=None) == g0
    s = hinge.centered(HingeSpec(pattern="diamond"))
    doc = _doc(generated.tag(hinge.hinge_shapes(s, "L"), s))
    p1 = save_document(doc, tmp_path / "flex.lcproj")
    back = load_document(p1)
    assert len(back.shapes) == len(doc.shapes)
    assert generated.spec_from_meta(back.shapes[0].generator) == replace(s, x=0.0, y=0.0)
    assert optimized_document_gcode(back, scan_offsets=None) == optimized_document_gcode(
        doc, scan_offsets=None)


# --- dialog --------------------------------------------------------------------------------------

def test_dialog_defaults_pattern_and_layer_thickness(qapp):
    from lumacut_canvas.model import Layer
    from lumacut_job.hinge_qt import HingeDialog
    dlg = HingeDialog()
    assert dlg.spec() == HingeSpec().normalized()
    assert dlg.ok_button.isEnabled() and "30 Linien" in dlg.info.text()
    assert len(dlg.preview.cuts) == len(hinge.slits(HingeSpec())) and dlg.preview.fits
    assert not dlg.margin.isEnabled()
    dlg.frame.setChecked(True)
    assert dlg.margin.isEnabled() and len(dlg.preview.cuts) == len(hinge.slits(HingeSpec())) + 1
    dlg.pattern.setCurrentIndex(hinge.PATTERNS.index("diamond"))
    assert dlg.spec().pattern == "diamond" and "Rauten" in dlg.info.text()
    dlg.deleteLater()
    d2 = HingeDialog(active_layer=Layer("Schnitt", thickness_mm=4.0))
    assert d2.spec().thickness_mm == 4.0 and not d2.new_layer.isChecked()
    d2.deleteLater()
    spec = HingeSpec(90, 40, pattern="wave", horizontal=True, cut_mm=12, bridge_mm=2,
                     pitch_mm=1.5, thickness_mm=4, open_edges=False, frame=True, margin_mm=7)
    d3 = HingeDialog(spec=spec)
    assert d3.spec() == spec.normalized()
    d3.deleteLater()


def test_dialog_warnings_and_disabled_ok(qapp):
    from lumacut_canvas.model import Layer
    from lumacut_job.hinge_qt import HingeDialog
    dlg = HingeDialog(active_layer=Layer("Gravur", fill_mode="hatch"))
    assert dlg.new_layer.isChecked()
    dlg.new_layer.setChecked(False)
    assert "graviert statt geschnitten" in dlg.info.text()
    dlg.width_mm.setValue(WORK_WIDTH_MM + 50)
    assert not dlg.ok_button.isEnabled() and "passt nicht" in dlg.info.text()
    dlg.width_mm.setValue(60)
    dlg.height_mm.setValue(6)
    dlg.bridge.setValue(3)
    assert not dlg.ok_button.isEnabled() and "zu kurz" in dlg.info.text()
    assert dlg.preview.cuts == []
    dlg.height_mm.setValue(50)
    dlg.pitch.setValue(0.6)
    assert dlg.ok_button.isEnabled() and "verbrennen" in dlg.info.text()
    dlg.deleteLater()


def test_dialog_bend_helper_sets_the_size_across_the_bend(qapp):
    from lumacut_job.hinge_qt import HingeDialog
    dlg = HingeDialog()
    dlg.radius.setValue(20)
    dlg.angle.setValue(90)
    dlg.thickness.setValue(3)
    dlg.calc.click()
    assert dlg.width_mm.value() == pytest.approx(round(21.5 * math.pi / 2, 1))
    assert dlg.height_mm.value() == 50
    dlg.horizontal.setChecked(True)
    dlg.angle.setValue(180)
    dlg.calc.click()
    assert dlg.height_mm.value() == pytest.approx(round(21.5 * math.pi, 1))
    dlg.deleteLater()


def test_dialog_touch_controls_are_44_px(qapp):
    from lumacut_job.hinge_qt import HingeDialog
    dlg = HingeDialog(touch=True)
    for w in (dlg.pattern, dlg.width_mm, dlg.height_mm, dlg.horizontal, dlg.cut, dlg.bridge,
              dlg.pitch, dlg.thickness, dlg.open_edges, dlg.frame, dlg.margin, dlg.radius,
              dlg.angle, dlg.calc, dlg.new_layer, *dlg.buttons.buttons()):
        assert w.minimumHeight() >= 44
    assert "1,5–3 mm" in dlg.pitch.toolTip()
    dlg.deleteLater()
    mouse = HingeDialog()
    assert mouse.width_mm.minimumHeight() < 44 and mouse.calc.minimumHeight() < 44
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
    a = win.job_tools.hinge_action
    assert a.objectName() == "hinge_action" and a.text() == "Flex-Scharnier…"
    assert a.shortcut() == QKeySequence("Alt+Shift+H")
    assert [b.text() for b in win.findChildren(QAction)
            if b is not a and b.shortcut() == a.shortcut()] == []
    assert "LightBurn" in a.toolTip() and "xTool" in a.toolTip()
    assert a in win.main_view.design_menu.actions() and a in win.main_view.job_menu.actions()


def test_window_insert_on_cut_layer_one_undo_step_and_gcode(win, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    from lumacut_job.planner import optimized_document_gcode
    tools, doc, stack = win.job_tools, win.canvas.document, win.canvas.undo_stack
    layer = doc.active_layer
    layer.fill_mode = "none"
    n_layers, n_shapes, depth = len(doc.layers), len(doc.shapes), stack.index()
    ids = tools.hinge(HingeSpec(40, 30, frame=True))
    assert len(ids) == len(hinge.slits(HingeSpec(40, 30))) + 1 and len(doc.layers) == n_layers
    assert all(doc.shape(i).layer_id == layer.id for i in ids)
    assert len({doc.shape(i).groups for i in ids}) == 1
    assert sorted(win.canvas.selection) == sorted(ids)
    assert stack.index() == depth + 1
    assert "Flex-Scharnier eingefügt" in win.statusBar().currentMessage()
    pi_check(optimized_document_gcode(doc))
    stack.undo()
    assert len(doc.shapes) == n_shapes
    warned = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: warned.append(a[2]))
    assert tools.hinge(HingeSpec(WORK_WIDTH_MM + 50, 30)) == []
    assert warned and "Arbeitsfläche" in warned[0] and len(doc.shapes) == n_shapes


def test_window_new_cut_layer_for_a_fill_or_locked_layer(win):
    tools, doc, stack = win.job_tools, win.canvas.document, win.canvas.undo_stack
    doc.active_layer.fill_mode = "hatch"
    n_layers, n_shapes = len(doc.layers), len(doc.shapes)
    ids = tools.hinge(HingeSpec(30, 30, thickness_mm=4))
    assert ids and len(doc.layers) == n_layers + 1
    new = doc.layer(doc.shape(ids[0]).layer_id)
    assert new.name == "Scharnier" and new.fill_mode == "none" and new.thickness_mm == 4.0
    stack.undo()
    assert len(doc.layers) == n_layers and len(doc.shapes) == n_shapes
    doc.active_layer.fill_mode = "none"
    doc.active_layer.locked = True
    ids = tools.hinge(HingeSpec(30, 30))
    assert doc.layer(doc.shape(ids[0]).layer_id).name == "Scharnier"


def test_window_dialog_cancel_accept_and_selection_size(win, monkeypatch):
    from PySide6.QtWidgets import QDialog

    from lumacut_job import hinge_qt
    tools, doc = win.job_tools, win.canvas.document
    doc.active_layer.fill_mode = "none"
    monkeypatch.setattr(hinge_qt.HingeDialog, "exec", lambda self: QDialog.Rejected)
    n = len(doc.shapes)
    assert tools.hinge() == [] and len(doc.shapes) == n
    monkeypatch.setattr(hinge_qt.HingeDialog, "exec", lambda self: (
        self.height_mm.setValue(30), QDialog.Accepted)[1])
    ids = tools.hinge()
    assert generated.spec_from_meta(doc.shape(ids[0]).generator).height_mm == 30
    win.canvas.undo_stack.undo()
    # with a selected rectangle the field starts with its size and sits on it
    rect = Shape.from_points("polygon", [(50, 60), (130, 60), (130, 100), (50, 100)],
                             doc.active_layer_id)
    doc.add_shape(rect)
    win.canvas.set_selection([rect.id])
    seen = []
    monkeypatch.setattr(hinge_qt.HingeDialog, "exec", lambda self: (
        seen.append(self.spec()), QDialog.Accepted)[1])
    ids = tools.hinge()
    assert (seen[0].width_mm, seen[0].height_mm) == (80, 40)
    x0, y0, x1, y1 = generated.extent([doc.shape(i) for i in ids])
    assert ((x0 + x1) / 2, (y0 + y1) / 2) == pytest.approx((90, 80), abs=1e-6)


def test_re_edit_hinge_keeps_place_layer_and_group(win, monkeypatch):
    from lumacut_canvas.commands import SetGeometryCommand
    from lumacut_job.generated_qt import edit_dialog, generated_unit, unit_spec
    tools, doc, stack = win.job_tools, win.canvas.document, win.canvas.undo_stack
    doc.active_layer.fill_mode = "none"
    ids = tools.hinge(HingeSpec(40, 30, frame=True))
    group = doc.shape(ids[0]).groups[-1]
    old = {i: doc.shape(i).geom.copy() for i in ids}
    stack.push(SetGeometryCommand(doc, old, {i: g.translated(-30, 10) for i, g in old.items()},
                                  "Verschieben"))
    win.canvas.set_selection(ids[:1])
    unit = generated_unit(win.canvas)
    assert unit.kind == "hinge" and unit.label == "Flex-Scharnier" and not unit.scaled
    got = unit_spec(unit)
    assert (got.width_mm, got.height_mm, got.frame) == (40, 30, True)
    dlg = edit_dialog(unit, got, doc.layer(unit.layer_id), win, touch=True)
    assert dlg.windowTitle() == "Flex-Scharnier bearbeiten" and dlg.ok_button.text() == "Übernehmen"
    assert not dlg.new_layer.isVisible() and not dlg.new_layer.isChecked()
    assert dlg.pitch.minimumHeight() >= 44 and dlg.spec() == got
    dlg.deleteLater()
    depth = stack.index()
    new_ids = tools.edit_generated(replace(got, pattern="wave", frame=False))
    assert stack.index() == depth + 1
    u2 = generated.find_unit(doc, new_ids[0])
    assert u2.center == pytest.approx(unit.center, abs=1e-6) and u2.group == group
    assert u2.layer_id == unit.layer_id
    assert generated.spec_from_meta(doc.shape(new_ids[0]).generator).pattern == "wave"
    stack.undo()
    assert all(doc.has_shape(i) for i in ids)
    from lumacut_job import hinge_qt
    opened = []
    monkeypatch.setattr(hinge_qt.HingeDialog, "exec", lambda self: opened.append(
        (self.windowTitle(), self.bridge.minimumHeight())) or 0)
    win.canvas.set_touch_mode(True, persist=False)
    assert tools.edit_generated_at(ids[2]) is True and opened == [("Flex-Scharnier bearbeiten", 44)]
    win.canvas.set_touch_mode(False, persist=False)
    assert tools.edit_generated_at(ids[2]) is True and opened[1][1] < 44
