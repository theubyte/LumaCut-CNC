"""Living hinge clipped to a free shape – lumacut_job.hinge (outline) / hinge_qt / generated_qt."""

from __future__ import annotations

import itertools
import json
import math
from dataclasses import replace

import pytest
from _pi_guard import pi_check
from shapely.geometry import LineString, Point, Polygon

from lumacut_canvas.model import Document, Geometry, Shape
from lumacut_canvas.toolpath import parse_gcode
from lumacut_job import generated, hinge
from lumacut_job.hinge import HingeSpec


def _circle(cx, cy, r, n=96):
    return [(cx + r * math.cos(2 * math.pi * i / n), cy + r * math.sin(2 * math.pi * i / n))
            for i in range(n)]


def _disc_spec(**kw) -> HingeSpec:
    (x0, y0, w, h), outline = hinge.outline_from_rings([_circle(30, 30, 30)])
    return HingeSpec(width_mm=w, height_mm=h, outline=outline, **kw).normalized()


def _ring_spec(**kw) -> HingeSpec:
    (_x0, _y0, w, h), outline = hinge.outline_from_rings([_circle(30, 30, 30),
                                                          _circle(30, 30, 10, 48)])
    return HingeSpec(width_mm=w, height_mm=h, outline=outline, **kw).normalized()


def _geom(pts, closed):
    return Polygon(pts) if closed else LineString(pts)


def _length(pts, closed):
    pts = list(pts) + ([pts[0]] if closed else [])
    return sum(math.dist(p, q) for p, q in zip(pts, pts[1:]))


# --- outline ---------------------------------------------------------------------------------------

def test_normalize_outline_cleans_rings():
    raw = [[[0, 0], [2, 0.5], [0.5, 1], [0, 0]], [(0.1, 0.1), (0.2, 0.2)],
           [(0, 0), (float("nan"), 1), (1, 1)], "x", [(0.1, 0.1), (0.9, 0.1), (0.5, -3)]]
    out = hinge.normalize_outline(raw)
    assert out == (((0.0, 0.0), (1.0, 0.5), (0.5, 1.0)), ((0.1, 0.1), (0.9, 0.1), (0.5, 0.0)))
    assert hinge.normalize_outline(None) == () and hinge.normalize_outline(5) == ()
    s = HingeSpec(outline=raw).normalized()
    assert s.outline == out and s.clipped and not HingeSpec().normalized().clipped
    assert hash(s) == hash(HingeSpec(outline=out).normalized())


def test_outline_from_rings_box_rectangle_and_even_odd_hole():
    (x0, y0, w, h), ol = hinge.outline_from_rings([_circle(50, 40, 20)])
    assert (x0, y0, w, h) == pytest.approx((30, 20, 40, 40), abs=1e-6)
    assert len(ol) == 1 and all(0 <= u <= 1 and 0 <= v <= 1 for u, v in ol[0])
    # a plain axis-parallel rectangle needs no outline (the rectangular field is exact)
    box, ol = hinge.outline_from_rings([[(10, 10), (90, 10), (90, 50), (10, 50)]])
    assert box == pytest.approx((10, 10, 80, 40)) and ol == ()
    # a turned rectangle does
    box, ol = hinge.outline_from_rings([[(50, 0), (100, 50), (50, 100), (0, 50)]])
    assert box == pytest.approx((0, 0, 100, 100)) and len(ol) == 1
    # outer ring + hole (even-odd): two rings, the hole has no area
    s = _ring_spec()
    assert len(s.outline) == 2
    area = hinge.outline_area(s)
    assert area.area == pytest.approx(math.pi * (30 ** 2 - 10 ** 2), rel=0.01)
    assert not area.contains(Point(30, 30))
    assert hinge.outline_from_rings([]) == ((0.0, 0.0, 0.0, 0.0), ())
    assert hinge.outline_area(HingeSpec()) is None


def test_very_detailed_outline_is_simplified_to_the_point_cap():
    ring = _circle(100, 100, 80, n=12000)
    (_x0, _y0, w, h), ol = hinge.outline_from_rings([ring])
    assert w == pytest.approx(160, abs=0.01)
    assert sum(len(r) for r in ol) <= hinge.MAX_OUTLINE_POINTS
    s = HingeSpec(width_mm=w, height_mm=h, outline=ol)
    assert hinge.outline_area(s).area == pytest.approx(math.pi * 80 ** 2, rel=0.005)


# --- clipping ----------------------------------------------------------------------------------------

@pytest.mark.parametrize("pattern,open_edges", list(itertools.product(hinge.PATTERNS, (True, False))))
def test_clipped_cuts_stay_in_the_shape_and_never_touch(pattern, open_edges):
    s = _disc_spec(pattern=pattern, open_edges=open_edges, pitch_mm=2.5, cut_mm=15)
    cuts = hinge.part_cuts(s)
    assert cuts
    area = hinge.outline_area(s)
    edge = area.boundary
    geoms = [_geom(p, c) for p, c in cuts]
    for g in geoms:
        assert area.buffer(1e-6).contains(g)
        if not open_edges:
            assert g.distance(edge) >= s.bridge_mm - 1e-3
    for a, b in itertools.combinations(geoms, 2):
        if a.bounds[0] - b.bounds[2] > 1 or b.bounds[0] - a.bounds[2] > 1:
            continue
        assert a.distance(b) > 0.1
    touching = [g for g in geoms if g.distance(edge) < 1e-6]
    assert bool(touching) == open_edges          # open: cuts run out to the outline
    assert all(_length(p, c) >= hinge.MIN_SLIT - 1e-6 for p, c in cuts)


def test_clipping_keeps_inner_slits_unchanged_and_cuts_the_crossing_ones():
    s = _disc_spec()
    rect = [(tuple(p), c) for p, c in hinge.part_cuts(replace(s, outline=()))]
    clipped = hinge.part_cuts(s)
    area = hinge.outline_area(s)
    inner = [rc for rc in rect if area.contains(_geom(*rc))]
    assert inner and all(rc in clipped for rc in inner)
    assert len(clipped) > len(inner)                    # crossing slits become shorter pieces
    assert hinge.cut_length(s) == pytest.approx(sum(_length(p, c) for p, c in clipped))
    assert hinge.cut_length(s) < hinge.cut_length(replace(s, outline=()))


def test_diamonds_closed_inside_open_on_the_edge_or_cut_back_closed():
    s = _disc_spec(pattern="diamond", open_edges=True)
    cuts = hinge.part_cuts(s)
    edge = hinge.outline_area(s).boundary
    opened = [p for p, c in cuts if not c]
    assert opened and any(c for _p, c in cuts)
    for p in opened:   # half holes end on the outline
        assert Point(p[0]).distance(edge) < 1e-6 and Point(p[-1]).distance(edge) < 1e-6
    closed = hinge.part_cuts(replace(s, open_edges=False))
    assert closed and all(c for _p, c in closed)       # cut back to closed holes, never open
    assert len(closed) > len([1 for _p, c in cuts if c])


def test_hole_of_the_shape_gets_no_cut_and_frame_does_not_apply():
    s = replace(_ring_spec(open_edges=False), frame=True, margin_mm=8)
    assert s.part_size() == (s.width_mm, s.height_mm)       # no margin with an outline
    cuts = hinge.part_cuts(s)
    hole = Polygon(_circle(30, 30, 10, 48))
    assert all(_geom(p, c).distance(hole) >= s.bridge_mm - 1e-3 for p, c in cuts)
    # no rectangle frame among the cuts
    assert not any(c and len(p) == 4 and Polygon(p).area > 3000 for p, c in cuts)


def test_hinge_shapes_on_the_shape_place_and_too_small_shape_refused():
    s = hinge.centered(_disc_spec(), (100, 80))
    assert (s.x, s.y) == pytest.approx((70, 50))
    shapes = hinge.hinge_shapes(s, "L")
    assert len(shapes) == len(hinge.part_cuts(s))
    x0, y0, x1, y1 = generated.extent(shapes)
    assert x0 >= 70 - 1e-6 and x1 <= 130 + 1e-6 and y0 >= 50 - 1e-6 and y1 <= 110 + 1e-6
    assert len({sh.groups for sh in shapes}) == 1
    (_x, _y, w, h), thin = hinge.outline_from_rings([[(0, 0), (2, 0), (42, 40), (40, 40)]])
    tiny = HingeSpec(width_mm=w, height_mm=h, outline=thin, open_edges=False, bridge_mm=3)
    with pytest.raises(ValueError, match="zu klein"):
        hinge.hinge_shapes(hinge.centered(tiny), "L")
    with pytest.raises(ValueError, match="zu klein"):
        hinge.describe(tiny)


def test_describe_and_center_offset():
    s = _disc_spec(pattern="diamond", open_edges=False)
    text = hinge.describe(s)
    assert "auf die Form zugeschnitten" in text and "Steg zum Umriss" in text
    assert f"{len(hinge.part_cuts(s))} Schnitte" in text
    assert "bis an den Umriss" in hinge.describe(replace(s, open_edges=True))
    assert "Form" not in hinge.describe(HingeSpec())
    assert hinge.cut_center_offset(HingeSpec(60, 40, frame=True)) == pytest.approx((0, 0))
    ox, oy = hinge.cut_center_offset(s)
    assert abs(ox) < s.pitch_mm and abs(oy) < s.pitch_mm


def test_rectangular_hinges_are_unchanged():
    for spec in (HingeSpec(), HingeSpec(70, 40, pattern="diamond", frame=True, open_edges=False),
                 HingeSpec(50, 80, pattern="wave", horizontal=True)):
        s = spec.normalized()
        expect = [(tuple(hinge._to_xy(s, u, v) for u, v in sl.points), sl.closed)
                  for sl in hinge.slits(s)]
        got = hinge.part_cuts(s)
        assert got[:len(expect)] == expect and len(got) == len(expect) + (1 if s.frame else 0)
    meta = generated.make_meta(HingeSpec(), hinge.hinge_shapes(hinge.centered(HingeSpec()), "L"))
    assert "outline" not in meta["spec"]         # no new key for rectangular hinges
    assert generated.spec_from_meta(meta) == replace(HingeSpec().normalized(), x=0.0, y=0.0)


# --- generated object, scaling, file, G-code -------------------------------------------------------

def test_meta_json_round_trip_and_scaling_stretches_the_outline():
    s = hinge.centered(_disc_spec(pattern="wave"))
    shapes = generated.tag(hinge.hinge_shapes(s, "L"), s)
    meta = json.loads(json.dumps(shapes[0].generator))
    assert generated.spec_from_meta(meta) == replace(s, x=0.0, y=0.0)
    again = Shape.from_dict(json.loads(json.dumps(shapes[-1].to_dict())))
    assert generated.spec_from_meta(again.generator).outline == s.outline
    sc = generated.scaled_spec(s, (1.5, 1.0))
    assert (sc.width_mm, sc.height_mm, sc.outline) == (90.0, 60.0, s.outline)
    oval = hinge.outline_area(sc)
    assert oval.bounds == pytest.approx((0, 0, 90, 60), abs=0.05)
    assert all(oval.buffer(1e-6).contains(_geom(p, c)) for p, c in hinge.part_cuts(replace(sc, x=0.0, y=0.0)))


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
def test_gcode_pi_safe_cuts_every_clipped_slit_and_the_shape(qapp, pattern):
    from lumacut_job.planner import optimized_document_gcode
    s = hinge.centered(_disc_spec(pattern=pattern, open_edges=False), (100, 80))
    disc = Shape("ellipse", Geometry(70, 50, 60, 60), "L")
    doc = _doc([*generated.tag(hinge.hinge_shapes(s, "L"), s), disc], fill_mode="none")
    g = optimized_document_gcode(doc, scan_offsets=None)
    pi_check(g)
    assert parse_gcode(g).cut_length_mm == pytest.approx(
        hinge.cut_length(s) + math.pi * 60, abs=0.5)


def test_saved_project_keeps_the_outline(qapp, tmp_path):
    from lumacut_canvas.document_io import load_document, save_document
    from lumacut_job.planner import optimized_document_gcode
    s = hinge.centered(_ring_spec(pattern="diamond"))
    doc = _doc(generated.tag(hinge.hinge_shapes(s, "L"), s), fill_mode="none")
    p = save_document(doc, tmp_path / "ring.lcproj")
    back = load_document(p)
    meta = back.shapes[0].generator
    assert generated.spec_from_meta(meta).outline == s.outline
    assert optimized_document_gcode(back, scan_offsets=None) == optimized_document_gcode(
        doc, scan_offsets=None)


# --- dialog -------------------------------------------------------------------------------------------

def test_dialog_clip_switch_frame_disabled_and_preview_outline(qapp):
    from lumacut_job.hinge_qt import HingeDialog
    s = _disc_spec()
    dlg = HingeDialog(spec=s)
    assert not dlg.clip.isHidden() and dlg.clip.isChecked() and dlg.clipping()
    assert dlg.spec().outline == s.outline
    assert not dlg.frame.isEnabled() and not dlg.margin.isEnabled()
    assert dlg.preview.outline == s.outline and "zugeschnitten" in dlg.info.text()
    assert "Umriss" in dlg.clip.toolTip() and "streckt" in dlg.clip.toolTip()
    n_clip = len(dlg.preview.cuts)
    dlg.clip.setChecked(False)
    assert dlg.spec().outline == () and dlg.frame.isEnabled() and dlg.preview.outline == ()
    assert len(dlg.preview.cuts) > n_clip
    dlg.frame.setChecked(True)
    assert dlg.margin.isEnabled()
    dlg.clip.setChecked(True)
    assert not dlg.margin.isEnabled() and dlg.spec().part_size() == (s.width_mm, s.height_mm)
    dlg.width_mm.setValue(90)
    assert dlg.spec().outline == s.outline and dlg.spec().width_mm == 90
    dlg.deleteLater()
    plain = HingeDialog()
    assert plain.clip.isHidden() and not plain.clipping() and plain.spec().outline == ()
    plain.deleteLater()


def test_dialog_clip_touch_44_px_and_too_small_shape_disables_ok(qapp):
    from lumacut_job.hinge_qt import HingeDialog
    dlg = HingeDialog(spec=_disc_spec(), touch=True)
    assert dlg.clip.minimumHeight() >= 44
    dlg.deleteLater()
    (_x, _y, w, h), thin = hinge.outline_from_rings([[(0, 0), (2, 0), (42, 40), (40, 40)]])
    small = HingeDialog(spec=HingeSpec(width_mm=w, height_mm=h, outline=thin, open_edges=False))
    assert not small.ok_button.isEnabled() and "zu klein" in small.info.text()
    small.clip.setChecked(False)
    assert small.ok_button.isEnabled()
    small.deleteLater()


# --- main window ---------------------------------------------------------------------------------------

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


def _world_cuts(doc, ids):
    from lumacut_canvas.shape_paths import shape_polygons
    out = []
    for i in ids:
        sh = doc.shape(i)
        for pts in shape_polygons(sh):
            out.append(_geom(pts, False) if sh.kind == "path" else Polygon(pts))
    return out


def test_selection_outline_closed_shapes_only(win):
    from lumacut_job.hinge_qt import selection_outline
    doc, canvas = win.canvas.document, win.canvas
    lid = doc.active_layer_id
    ell = Shape("ellipse", Geometry(40, 50, 80, 40), lid)
    rect = Shape.from_points("polygon", [(150, 60), (190, 60), (190, 90), (150, 90)], lid)
    line = Shape.from_points("path", [(10, 10), (30, 30)], lid)
    for sh in (ell, rect, line):
        doc.add_shape(sh)
    canvas.set_selection([ell.id])
    center, size, outline = selection_outline(canvas)
    assert center == pytest.approx((80, 70), abs=1e-3) and size == pytest.approx((80, 40), abs=1e-3)
    assert outline
    canvas.set_selection([rect.id])
    assert selection_outline(canvas)[2] == ()
    canvas.set_selection([line.id])
    assert selection_outline(canvas) is None
    canvas.set_selection([line.id, ell.id])
    assert selection_outline(canvas)[2] == outline
    ell.geom = Geometry(40, 50, 80, 40, rot=90)
    canvas.set_selection([ell.id])
    _c, size, _o = selection_outline(canvas)
    assert size == pytest.approx((40, 80), abs=1e-3)


def test_window_hinge_on_selected_ellipse_one_undo_step(win, monkeypatch):
    from PySide6.QtWidgets import QDialog

    from lumacut_job import hinge_qt
    from lumacut_job.planner import optimized_document_gcode
    tools, doc, stack = win.job_tools, win.canvas.document, win.canvas.undo_stack
    doc.active_layer.fill_mode = "none"
    ell = Shape("ellipse", Geometry(40, 50, 80, 40), doc.active_layer_id)
    doc.add_shape(ell)
    win.canvas.set_selection([ell.id])
    seen = []
    monkeypatch.setattr(hinge_qt.HingeDialog, "exec", lambda self: (
        seen.append((self.clipping(), self.clip.isHidden())), QDialog.Accepted)[1])
    depth, n = stack.index(), len(doc.shapes)
    ids = tools.hinge()
    assert seen == [(True, False)] and ids and stack.index() == depth + 1
    assert doc.has_shape(ell.id) and len(doc.shapes) == n + len(ids)   # the ellipse stays
    oval = Polygon(_circle(0, 0, 1, 180)).buffer(0)
    from shapely.affinity import affine_transform
    oval = affine_transform(oval, [40, 0, 0, 20, 80, 70]).buffer(0.05)
    assert all(oval.contains(g) for g in _world_cuts(doc, ids))
    assert "auf die Form zugeschnitten" in win.statusBar().currentMessage()
    assert "Oval" in tools.hinge_action.toolTip()
    spec = generated.spec_from_meta(doc.shape(ids[0]).generator)
    assert spec.outline and spec.width_mm == pytest.approx(80, abs=0.01)
    pi_check(optimized_document_gcode(doc))
    stack.undo()
    assert len(doc.shapes) == n and doc.has_shape(ell.id)
    # switched off in the dialog: the plain rectangle over the ellipse's box
    win.canvas.set_selection([ell.id])
    monkeypatch.setattr(hinge_qt.HingeDialog, "exec", lambda self: (
        self.clip.setChecked(False), QDialog.Accepted)[1])
    ids = tools.hinge()
    assert generated.spec_from_meta(doc.shape(ids[0]).generator).outline == ()
    x0, y0, x1, y1 = generated.extent([doc.shape(i) for i in ids])
    assert ((x0 + x1) / 2, (y0 + y1) / 2) == pytest.approx((80, 70), abs=1e-6)


def test_window_selected_rectangle_keeps_the_old_field(win, monkeypatch):
    from PySide6.QtWidgets import QDialog

    from lumacut_job import hinge_qt
    tools, doc = win.job_tools, win.canvas.document
    doc.active_layer.fill_mode = "none"
    rect = Shape.from_points("polygon", [(50, 60), (130, 60), (130, 100), (50, 100)],
                             doc.active_layer_id)
    doc.add_shape(rect)
    win.canvas.set_selection([rect.id])
    seen = []
    monkeypatch.setattr(hinge_qt.HingeDialog, "exec", lambda self: (
        seen.append((self.clip.isHidden(), self.spec())), QDialog.Accepted)[1])
    ids = tools.hinge()
    hidden, spec = seen[0]
    assert hidden and spec.outline == () and (spec.width_mm, spec.height_mm) == (80, 40)
    assert len(ids) == len(hinge.slits(spec))


def test_re_edit_clipped_hinge_keeps_the_field_on_the_shape(win, monkeypatch):
    from lumacut_canvas.commands import SetGeometryCommand
    from lumacut_job.generated_qt import edit_dialog, generated_unit, unit_spec
    tools, doc, stack = win.job_tools, win.canvas.document, win.canvas.undo_stack
    doc.active_layer.fill_mode = "none"
    (x0, y0, w, h), outline = hinge.outline_from_rings([_circle(100, 80, 30)])
    spec = HingeSpec(width_mm=w, height_mm=h, outline=outline, pattern="diamond",
                     open_edges=False)
    ids = tools.hinge(spec, center=(100, 80))
    disc = Polygon(_circle(100, 80, 30, 180)).buffer(0.05)
    assert all(disc.contains(g) for g in _world_cuts(doc, ids))
    win.canvas.set_selection(ids[:1])
    unit = generated_unit(win.canvas)
    got = unit_spec(unit)
    assert got.outline == spec.normalized().outline
    dlg = edit_dialog(unit, got, doc.layer(unit.layer_id), win, touch=True)
    assert not dlg.clip.isHidden() and dlg.clip.isChecked() and dlg.clip.minimumHeight() >= 44
    dlg.deleteLater()
    # several pattern changes in a row never walk the hinge off the disc
    for change in (dict(pattern="lines", pitch_mm=3.1), dict(pattern="wave", pitch_mm=1.7),
                   dict(pattern="diamond", pitch_mm=2.4, open_edges=True)):
        cur = unit_spec(generated_unit(win.canvas))
        new_ids = tools.edit_generated(replace(cur, **change))
        assert all(disc.contains(g) for g in _world_cuts(doc, new_ids))
        win.canvas.set_selection(new_ids[:1])
    # moved and turned group: the field follows the group
    ids = list(win.canvas.selection)
    unit = generated_unit(win.canvas)
    old = {i: doc.shape(i).geom.copy() for i in unit.ids}
    moved = {i: g.translated(20, 10).rotated(90, 120, 90) for i, g in old.items()}
    stack.push(SetGeometryCommand(doc, old, moved, "Verschieben"))
    disc2 = Polygon(_circle(120, 90, 30, 180)).buffer(0.05)
    unit = generated_unit(win.canvas)
    new_ids = tools.edit_generated(replace(unit_spec(unit), pitch_mm=2.0, pattern="lines"))
    assert all(disc2.contains(g) for g in _world_cuts(doc, new_ids))
