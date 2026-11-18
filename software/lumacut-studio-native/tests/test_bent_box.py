"""Bent box with rounded corners (flex box, boxes.py „FlexBox“) – lumacut_job.bentbox / bentbox_qt."""

from __future__ import annotations

import math
from dataclasses import replace

import pytest
from _pi_guard import pi_check
from shapely.geometry import LineString, Polygon, box as sbox

from lumacut_canvas.model import Document, Shape
from lumacut_canvas.toolpath import parse_gcode
from lumacut_canvas.workarea import WORK_HEIGHT_MM, WORK_WIDTH_MM
from lumacut_job import bentbox, boxgen, generated, hinge
from lumacut_job.bentbox import BentBoxSpec


def _part(spec, name):
    return next(p for p in bentbox.parts(spec) if p.name == name)


def _cut_geom(pts, closed):
    return Polygon(pts) if closed else LineString(pts)


def _cut_length(pts, closed):
    pts = list(pts) + ([pts[0]] if closed else [])
    return sum(math.dist(p, q) for p, q in zip(pts, pts[1:]))


# --- spec ----------------------------------------------------------------------------------------

def test_spec_defaults_and_normalize_clamps():
    s = BentBoxSpec().normalized()
    assert (s.width_mm, s.depth_mm, s.height_mm, s.radius_mm, s.thickness_mm) == (
        100.0, 80.0, 50.0, 10.0, 3.0)
    assert s.kerf_mm == bentbox.DEFAULT_KERF and s.lid and not s.inner and not s.split
    assert (s.pattern, s.cut_mm, s.bridge_mm, s.pitch_mm) == ("lines", 20.0, 3.0, 2.0)
    n = BentBoxSpec(width_mm=1, depth_mm=5000, height_mm=float("nan"), radius_mm=0,
                    thickness_mm=50, finger_mm=0.1, kerf_mm=-1, spacing_mm=999, lid=0, inner=1,
                    pattern="spiral", pitch_mm=99, bridge_mm=0, split=1).normalized()
    assert n.width_mm == bentbox.SIZE_RANGE[0] and n.depth_mm == bentbox.SIZE_RANGE[1]
    assert n.height_mm == 50.0 and n.radius_mm == bentbox.RADIUS_RANGE[0]
    assert n.thickness_mm == bentbox.THICKNESS_RANGE[1] and n.finger_mm == bentbox.FINGER_RANGE[0]
    assert n.kerf_mm == 0.0 and n.spacing_mm == bentbox.SPACING_RANGE[1]
    assert n.lid is False and n.inner is True and n.split is True and n.pattern == "lines"
    assert n.pitch_mm == bentbox.PITCH_RANGE[1] and n.bridge_mm == bentbox.BRIDGE_RANGE[0]
    assert BentBoxSpec(radius_mm="abc").normalized().radius_mm == 10.0
    assert BentBoxSpec(pattern="diamond").normalized().pattern == "diamond"


def test_outer_inner_sizes_radius_arc_and_wall_length():
    s = BentBoxSpec(100, 80, 50, radius_mm=10, thickness_mm=3)
    assert s.outer() == (100, 80, 50) and s.inside() == pytest.approx((94, 74, 44))
    assert s.outer_radius() == 13.0
    # the corner hinge is the 90° arc of the neutral fibre (inner radius + t / 2)
    assert s.arc_mm() == pytest.approx(math.pi / 2 * 11.5)
    assert s.arc_mm() == pytest.approx(hinge.width_for(10, 90, 3))
    assert s.straights() == pytest.approx((74, 54))
    assert s.wall_length() == pytest.approx(2 * 74 + 2 * 54 + 2 * math.pi * 11.5)
    i = BentBoxSpec(100, 80, 50, thickness_mm=3, inner=True, lid=False)
    assert i.outer() == pytest.approx((106, 86, 53)) and i.inside() == pytest.approx((100, 80, 50))
    h = s.corner_hinge()
    assert h.width_mm == pytest.approx(s.arc_mm(), abs=1e-3) and h.height_mm == 50
    assert not h.open_edges and not h.frame and h.pitch_mm == 2.0


def test_wall_walks_around_the_box_from_the_middle_of_the_back():
    s = BentBoxSpec(100, 80, 50, radius_mm=10)
    lay = bentbox.wall_layout(s)
    assert [k for k, _a, _b in lay] == ["back", "corner", "right", "corner", "front", "corner",
                                        "left", "corner", "back"]
    assert lay[0][1] == 0.0 and lay[-1][2] == pytest.approx(s.wall_length())
    for (_k, _a, b), (_k2, a2, _b2) in zip(lay, lay[1:]):
        assert a2 == pytest.approx(b)
    lengths = {k: [] for k, *_ in lay}
    for k, a, b in lay:
        lengths[k].append(b - a)
    assert lengths["corner"] == pytest.approx([s.arc_mm()] * 4)
    assert lengths["front"] == pytest.approx([74]) and lengths["back"] == pytest.approx([37, 37])
    # the front middle is half way – there the two-part wall is split
    front = next((a, b) for k, a, b in lay if k == "front")
    assert (front[0] + front[1]) / 2 == pytest.approx(s.wall_length() / 2)


# --- joints ----------------------------------------------------------------------------------------

def _side_tabs(plate: Polygon, side: str, W: float, D: float, t: float):
    """Tab intervals of a kerf-free plate along one side (plate coordinates, y down)."""
    band = {"front": sbox(-1, -1, W + 1, t - 1e-6), "back": sbox(-1, D - t + 1e-6, W + 1, D + 1),
            "left": sbox(-1, -1, t - 1e-6, D + 1), "right": sbox(W - t + 1e-6, -1, W + 1, D + 1)}
    g = plate.intersection(band[side])
    geoms = list(getattr(g, "geoms", [g])) if not g.is_empty else []
    along = 0 if side in ("front", "back") else 1
    return sorted((round(x.bounds[along], 6), round(x.bounds[along + 2], 6)) for x in geoms)


def _flat(pairs):
    return [v for pair in pairs for v in pair]


@pytest.mark.parametrize("dims", [(100, 80, 50, 10), (150, 60, 40, 15), (60, 120, 70, 5),
                                  (80, 80, 40, 20)])
def test_folded_wall_notches_meet_the_plate_tabs_exactly(dims):
    W, D, H, r = dims
    s = BentBoxSpec(W, D, H, radius_mm=r, kerf_mm=0.0)
    t, R = s.thickness_mm, s.outer_radius()
    plate = Polygon(_part(s, "Boden").outline)
    L = s.wall_length()
    notches = bentbox.notches(s)
    lay = bentbox.wall_layout(s)
    sides = {"front": next(a for k, a, _b in lay if k == "front"),
             "right": next(a for k, a, _b in lay if k == "right"),
             "left": next(a for k, a, _b in lay if k == "left")}
    for side, x0 in sides.items():
        length = (W if side == "front" else D) - 2 * R
        got = [(round(p - x0 + R, 6), round(q - x0 + R, 6)) for p, q in notches
               if x0 - 1e-6 <= p and q <= x0 + length + 1e-6]
        want = _side_tabs(plate, side, W, D, t)
        assert _flat(got) == pytest.approx(_flat(want), abs=1e-6)
    # the back side is split by the seam at x = 0: wrap it around
    sw = W - 2 * R
    back = []
    for p, q in notches:
        if p >= L - sw / 2 - 1e-6:
            back.append((p - (L - sw / 2) + R, q - (L - sw / 2) + R))
        elif q <= sw / 2 + 1e-6:
            back.append((p + sw / 2 + R, q + sw / 2 + R))
    merged = []
    for p, q in sorted(back):
        if merged and abs(merged[-1][1] - p) < 1e-6:
            merged[-1] = (merged[-1][0], q)
        else:
            merged.append((p, q))
    assert _flat(merged) == pytest.approx(_flat(_side_tabs(plate, "back", W, D, t)), abs=1e-6)
    # never a notch where the wall bends
    for k, a, b in lay:
        if k == "corner":
            assert all(q <= a + 1e-6 or p >= b - 1e-6 for p, q in notches)


def test_tab_counts_are_odd_finger_counts_and_the_wall_owns_the_ends():
    s = BentBoxSpec(100, 80, 50, radius_mm=10, finger_mm=10)
    nx, ny = bentbox.side_counts(s)
    assert (nx, ny) == (boxgen.finger_count(74, 10, 3), boxgen.finger_count(54, 10, 3))
    assert nx % 2 == 1 and ny % 2 == 1
    # (n - 1) / 2 tabs per side, both plates: front/back nx, left/right ny
    assert len(bentbox.notches(s)) == (nx - 1) + (ny - 1) + 1     # the back tab over the seam is split
    assert bentbox.side_counts(BentBoxSpec(40, 40, 30, radius_mm=17)) == (1, 1)   # a round tube


def test_wall_outline_area_and_plate_shape_without_kerf():
    s = BentBoxSpec(100, 80, 50, radius_mm=10, kerf_mm=0.0)
    t, L, H = 3.0, s.wall_length(), 50.0
    wall = Polygon(_part(s, "Wand").outline)
    notch_len = sum(q - p for p, q in bentbox.notches(s))
    assert wall.area == pytest.approx(L * H - 2 * t * notch_len, abs=1e-6)
    assert wall.bounds == pytest.approx((0, 0, L, H), abs=1e-6)
    s_open = replace(s, lid=False)
    wall_open = Polygon(_part(s_open, "Wand").outline)
    assert wall_open.area == pytest.approx(L * H - t * notch_len, abs=1e-6)
    assert wall_open.intersection(sbox(0, 0, L, t)).area == pytest.approx(L * t)   # straight top
    plate = Polygon(_part(s, "Boden").outline)
    assert plate.bounds == pytest.approx((0, 0, 100, 80), abs=1e-6)
    inner = plate.intersection(sbox(t, t, 100 - t, 80 - t))
    rr = (94 * 74) - (4 - math.pi) * 10 ** 2
    assert inner.area == pytest.approx(rr, rel=2e-3)            # rounded with the inner radius
    assert not plate.contains(sbox(t + 0.5, t + 0.5, t + 1, t + 1))   # corner rounded away
    assert _part(s, "Deckel").outline == _part(s, "Boden").outline


def test_kerf_grows_every_part_by_half_the_kerf():
    s0 = BentBoxSpec(kerf_mm=0.0)
    s1 = BentBoxSpec(kerf_mm=0.2)
    for name in ("Wand", "Boden"):
        a = Polygon(_part(s0, name).outline)
        b = Polygon(_part(s1, name).outline)
        x0, y0, x1, y1 = a.bounds
        assert b.bounds == pytest.approx((0, 0, x1 + 0.2, y1 + 0.2), abs=1e-6)
        assert b.area > a.area
    # notches come out kerf narrower, the slits are not offset (only moved with the part)
    c0 = _part(s0, "Wand").cuts
    c1 = _part(s1, "Wand").cuts
    assert len(c0) == len(c1)
    for (p0, _), (p1, _) in zip(c0, c1):
        assert _cut_length(p0, False) == pytest.approx(_cut_length(p1, False))
        assert p1[0][0] - p0[0][0] == pytest.approx(0.1)


@pytest.mark.parametrize("pattern", bentbox.PATTERNS)
def test_hinge_cuts_lie_in_the_corners_inside_the_wall(pattern):
    s = BentBoxSpec(100, 80, 50, radius_mm=10, pattern=pattern, kerf_mm=0.0)
    wall = _part(s, "Wand")
    poly = Polygon(wall.outline)
    hs = s.corner_hinge()
    per_corner = hinge.slits(hs)
    assert len(wall.cuts) == 4 * len(per_corner)
    corners = [(a, b) for k, a, b in bentbox.wall_layout(s) if k == "corner"]
    for pts, closed in wall.cuts:
        g = _cut_geom(pts, closed)
        assert poly.contains(g)
        assert g.distance(poly.exterior) >= s.bridge_mm - 1e-6 or pattern == "diamond"
        xs = [x for x, _ in pts]
        assert any(a - 1e-6 <= min(xs) and max(xs) <= b + 1e-6 for a, b in corners)
    # cuts of one corner never touch each other
    geoms = [_cut_geom(p, c) for p, c in wall.cuts]
    for i, g in enumerate(geoms[:30]):
        assert all(g.distance(h) > 0.3 for h in geoms[i + 1:30])


def test_two_part_wall_splits_at_back_and_front_middle():
    one = BentBoxSpec(100, 80, 50, radius_mm=10, kerf_mm=0.0)
    two = replace(one, split=True)
    names = [p.name for p in bentbox.parts(two)]
    assert names == ["Wand 1", "Wand 2", "Boden", "Deckel"]
    w1, w2 = _part(two, "Wand 1"), _part(two, "Wand 2")
    L = one.wall_length()
    assert w1.size == pytest.approx((L / 2, 50)) and w2.size == pytest.approx((L / 2, 50))
    assert Polygon(w1.outline).area + Polygon(w2.outline).area == pytest.approx(
        Polygon(_part(one, "Wand").outline).area)
    assert len(w1.cuts) == len(w2.cuts) == 2 * len(hinge.slits(one.corner_hinge()))


def test_impossible_boxes_are_refused_in_german():
    with pytest.raises(ValueError, match="Radius höchstens"):
        bentbox.parts(BentBoxSpec(50, 40, 30, radius_mm=20))
    with pytest.raises(ValueError, match="zu klein"):
        bentbox.parts(BentBoxSpec(100, 80, 10, thickness_mm=3))
    with pytest.raises(ValueError, match="Linienabstand"):
        bentbox.parts(BentBoxSpec(radius_mm=3, thickness_mm=0.5, pitch_mm=4))
    bentbox.parts(BentBoxSpec(40, 40, 30, radius_mm=17))      # round tube is fine


# --- layout --------------------------------------------------------------------------------------

def test_layout_parts_apart_inside_the_work_area():
    s = BentBoxSpec(spacing_mm=4)
    placed, (lw, lh), fits = bentbox.layout(s)
    assert fits and len(placed) == 3
    polys = [Polygon(r) for _n, r, _c in placed]
    for a, b in zip(polys, polys[1:]):
        assert a.distance(b) >= 4 - 1e-6
    assert max(p.bounds[2] for p in polys) <= WORK_WIDTH_MM and lh <= WORK_HEIGHT_MM
    for _n, ring, cuts in placed:
        poly = Polygon(ring)
        assert all(poly.contains(_cut_geom(p, c)) for p, c in cuts)


def test_long_wall_needs_two_parts_and_too_big_is_refused():
    big = BentBoxSpec(200, 150, 60, radius_mm=20, lid=False)
    assert big.wall_length() > max(WORK_WIDTH_MM, WORK_HEIGHT_MM)
    _placed, _size, fits = bentbox.layout(big)
    assert not fits
    with pytest.raises(ValueError, match="zweiteilig"):
        bentbox.bentbox_shapes(bentbox.centered(big), "L")
    _placed, (lw, lh), fits = bentbox.layout(replace(big, split=True))
    assert fits and lw <= WORK_WIDTH_MM and lh <= WORK_HEIGHT_MM
    shapes = bentbox.bentbox_shapes(bentbox.centered(replace(big, split=True)), "L")
    assert len({sh.groups for sh in shapes}) == 1


def test_shapes_one_group_centred_cuts_before_outlines():
    s = bentbox.centered(BentBoxSpec())
    shapes = bentbox.bentbox_shapes(s, "L")
    n_cuts = sum(len(p.cuts) for p in bentbox.parts(s))
    assert len(shapes) == n_cuts + 3 and len({sh.groups for sh in shapes}) == 1
    assert all(sh.layer_id == "L" for sh in shapes)
    kinds = {sh.kind for sh in shapes}
    assert kinds == {"path", "polygon"}
    x0, y0, x1, y1 = generated.extent(shapes)
    assert ((x0 + x1) / 2, (y0 + y1) / 2) == pytest.approx((WORK_WIDTH_MM / 2, WORK_HEIGHT_MM / 2),
                                                           abs=0.5)


def test_readout_and_warnings():
    text = bentbox.describe(BentBoxSpec())
    assert "Außen 100.0 × 80.0 × 50.0" in text and "Ecken innen R 10.0" in text
    assert "Wand 328.3 mm lang (1 Teil)" in text and "3 Teile (mit Deckel)" in text
    assert "Zinken 7 / 5" in text and "Gerade Schlitze" in text
    assert "2 Teile" in bentbox.describe(BentBoxSpec(split=True))
    assert bentbox.warnings(BentBoxSpec()) == []
    assert any("einkleben" in w for w in bentbox.warnings(BentBoxSpec(40, 40, 30, radius_mm=17)))
    assert any("reißen" in w for w in bentbox.warnings(BentBoxSpec(bridge_mm=1.0)))
    assert any("brechen leicht" in w for w in bentbox.warnings(BentBoxSpec(finger_mm=2)))


# --- meta / files / G-code -----------------------------------------------------------------------

def test_generator_meta_round_trip_and_sizes_not_scaled():
    s = bentbox.centered(BentBoxSpec(90, 70, 40, radius_mm=12, pattern="wave", lid=False,
                                     kerf_mm=0.15, split=True))
    shapes = generated.tag(bentbox.bentbox_shapes(s, "L"), s)
    meta = shapes[0].generator
    assert meta["kind"] == "bentbox" and "x" not in meta["spec"]
    assert generated.spec_from_meta(meta) == replace(s, x=0.0, y=0.0)
    again = Shape.from_dict(shapes[-1].to_dict())
    assert generated.spec_from_meta(again.generator) == replace(s, x=0.0, y=0.0)
    assert generated.scaled_spec(s, (1.5, 0.7)) == s
    assert generated.LABELS["bentbox"] == "Flex-Box"


def _doc(shapes):
    doc = Document()
    lid = doc.active_layer_id
    for sh in shapes:
        sh.layer_id = lid
        doc.add_shape(sh)
    return doc


def test_gcode_is_pi_safe_and_cuts_every_part_and_slit_once(qapp):
    from lumacut_job.planner import optimized_document_gcode
    s = bentbox.centered(BentBoxSpec())
    shapes = bentbox.bentbox_shapes(s, "L")
    doc = _doc(shapes)
    g = optimized_document_gcode(doc, scan_offsets=None)
    pi_check(g)
    outlines = sum(Polygon(p.outline).length for p in bentbox.parts(s))
    slits = sum(_cut_length(pts, c) for p in bentbox.parts(s) for pts, c in p.cuts)
    assert parse_gcode(g).cut_length_mm == pytest.approx(outlines + slits, abs=0.2)


def test_saved_project_keeps_the_box_and_old_projects_are_unchanged(qapp, tmp_path):
    from lumacut_canvas.document_io import load_document, save_document
    from lumacut_job.planner import optimized_document_gcode
    plain = _doc([Shape.from_points("polygon", [(20, 20), (60, 20), (60, 50)], "L")])
    p0 = save_document(plain, tmp_path / "alt.lcproj")
    assert '"bentbox"' not in p0.read_text(encoding="utf-8")
    g0 = optimized_document_gcode(plain, scan_offsets=None)
    assert optimized_document_gcode(load_document(p0), scan_offsets=None) == g0
    s = bentbox.centered(BentBoxSpec(lid=False, pattern="diamond"))
    doc = _doc(generated.tag(bentbox.bentbox_shapes(s, "L"), s))
    p1 = save_document(doc, tmp_path / "flexbox.lcproj")
    back = load_document(p1)
    assert len(back.shapes) == len(doc.shapes)
    assert generated.spec_from_meta(back.shapes[0].generator) == replace(s, x=0.0, y=0.0)
    # same moves; coordinates may differ in the last printed digit (points are stored
    # normalised and rounded in the file)
    a = optimized_document_gcode(back, scan_offsets=None).splitlines()
    b = optimized_document_gcode(doc, scan_offsets=None).splitlines()
    assert len(a) == len(b)
    for la, lb in zip(a, b):
        wa, wb = la.split(), lb.split()
        assert [w[0] for w in wa] == [w[0] for w in wb]
        for x, y in zip(wa, wb):
            if x != y:
                assert x[0] in "XY" and abs(float(x[1:]) - float(y[1:])) <= 0.0011


# --- dialog --------------------------------------------------------------------------------------

def test_dialog_defaults_spec_and_material_thickness_of_the_layer(qapp):
    from lumacut_canvas.model import Layer
    from lumacut_job.bentbox_qt import BentBoxDialog
    dlg = BentBoxDialog()
    assert dlg.spec() == BentBoxSpec().normalized()
    assert dlg.ok_button.isEnabled() and "Außen 100.0" in dlg.info.text()
    assert len(dlg.preview.rings) == 3 and dlg.preview.fits
    assert sum(len(c) for _n, _r, c in dlg.preview.placed) == 4 * len(
        hinge.slits(BentBoxSpec().corner_hinge()))
    dlg.lid.setChecked(False)
    assert len(dlg.preview.rings) == 2 and "offen" in dlg.info.text()
    dlg.split.setChecked(True)
    assert len(dlg.preview.rings) == 3 and "2 Teile" in dlg.info.text()
    dlg.pattern.setCurrentIndex(bentbox.PATTERNS.index("wave"))
    assert dlg.spec().pattern == "wave" and "Wellen" in dlg.info.text()
    dlg.deleteLater()
    layer = Layer("Schnitt", thickness_mm=4.0)
    d2 = BentBoxDialog(active_layer=layer)
    assert d2.spec().thickness_mm == 4.0 and not d2.new_layer.isChecked()
    d2.deleteLater()
    spec = BentBoxSpec(90, 60, 40, radius_mm=12, thickness_mm=4, finger_mm=8, kerf_mm=0.15,
                       lid=False, inner=True, pattern="diamond", cut_mm=15, bridge_mm=2.5,
                       pitch_mm=1.5, split=True, spacing_mm=6)
    d3 = BentBoxDialog(spec=spec, active_layer=layer)
    assert d3.spec() == spec.normalized()
    d3.deleteLater()


def test_dialog_warnings_and_disabled_ok(qapp):
    from lumacut_canvas.model import Layer
    from lumacut_job.bentbox_qt import BentBoxDialog
    dlg = BentBoxDialog(active_layer=Layer("Gravur", fill_mode="hatch"))
    assert dlg.new_layer.isChecked()
    dlg.new_layer.setChecked(False)
    assert "graviert statt geschnitten" in dlg.info.text()
    dlg.width_mm.setValue(200)
    dlg.depth_mm.setValue(150)
    dlg.height_mm.setValue(60)
    dlg.radius.setValue(20)
    dlg.lid.setChecked(False)
    assert not dlg.ok_button.isEnabled() and "zweiteilig" in dlg.info.text()
    assert not dlg.preview.fits
    dlg.split.setChecked(True)
    assert dlg.ok_button.isEnabled()
    dlg.radius.setValue(90)
    assert not dlg.ok_button.isEnabled() and "Radius höchstens" in dlg.info.text()
    assert dlg.preview.rings == []
    dlg.deleteLater()
    d2 = BentBoxDialog(active_layer=Layer("Schnitt", kerf_mm=0.1))
    assert "doppelt" in d2.info.text()
    d2.kerf.setValue(0.0)
    assert "doppelt" not in d2.info.text()
    d2.bridge.setValue(1.0)
    assert "reißen" in d2.info.text()
    d2.deleteLater()


def test_dialog_touch_controls_are_44_px(qapp):
    from lumacut_job.bentbox_qt import BentBoxDialog
    dlg = BentBoxDialog(touch=True)
    for w in (dlg.width_mm, dlg.depth_mm, dlg.height_mm, dlg.radius, dlg.thickness, dlg.finger,
              dlg.kerf, dlg.spacing, dlg.pattern, dlg.cut, dlg.bridge, dlg.pitch, dlg.inner,
              dlg.lid, dlg.split, dlg.new_layer, *dlg.buttons.buttons()):
        assert w.minimumHeight() >= 44
    assert dlg.sizeHint().height() <= 720
    assert "Kerf-Versatz" in dlg.kerf.toolTip()
    dlg.deleteLater()
    mouse = BentBoxDialog()
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
    a = win.job_tools.bentbox_action
    assert a.objectName() == "bentbox_action" and a.text() == "Flex-Box (runde Ecken)…"
    assert a.shortcut() == QKeySequence("Alt+Shift+L")
    assert [b.text() for b in win.findChildren(QAction)
            if b is not a and b.shortcut() == a.shortcut()] == []
    assert "boxes.py" in a.toolTip()
    assert a in win.main_view.design_menu.actions() and a in win.main_view.job_menu.actions()


def test_window_insert_on_cut_layer_one_undo_step_and_gcode(win, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    from lumacut_job.planner import optimized_document_gcode
    tools, doc, stack = win.job_tools, win.canvas.document, win.canvas.undo_stack
    layer = doc.active_layer
    layer.fill_mode = "none"
    n_layers, n_shapes, depth = len(doc.layers), len(doc.shapes), stack.index()
    spec = BentBoxSpec(80, 60, 40)
    ids = tools.bentbox(spec)
    n_cuts = sum(len(p.cuts) for p in bentbox.parts(spec))
    assert len(ids) == n_cuts + 3 and len(doc.layers) == n_layers
    assert all(doc.shape(i).layer_id == layer.id for i in ids)
    assert len({doc.shape(i).groups for i in ids}) == 1
    assert sorted(win.canvas.selection) == sorted(ids)
    assert stack.index() == depth + 1
    assert "Flex-Box eingefügt (3 Teile" in win.statusBar().currentMessage()
    pi_check(optimized_document_gcode(doc))
    stack.undo()
    assert len(doc.shapes) == n_shapes
    warned = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: warned.append(a[2]))
    assert tools.bentbox(BentBoxSpec(200, 150, 60, radius_mm=20)) == []
    assert warned and "Arbeitsfläche" in warned[0] and len(doc.shapes) == n_shapes


def test_window_new_cut_layer_for_a_fill_or_locked_layer(win):
    tools, doc, stack = win.job_tools, win.canvas.document, win.canvas.undo_stack
    doc.active_layer.fill_mode = "hatch"
    n_layers, n_shapes = len(doc.layers), len(doc.shapes)
    ids = tools.bentbox(BentBoxSpec(thickness_mm=4, lid=False))
    assert len(doc.layers) == n_layers + 1
    new = doc.layer(doc.shape(ids[0]).layer_id)
    assert new.name == "Flex-Box" and new.fill_mode == "none" and new.thickness_mm == 4.0
    stack.undo()
    assert len(doc.layers) == n_layers and len(doc.shapes) == n_shapes
    doc.active_layer.fill_mode = "none"
    doc.active_layer.locked = True
    ids = tools.bentbox(BentBoxSpec())
    assert doc.layer(doc.shape(ids[0]).layer_id).name == "Flex-Box"


def test_window_dialog_cancel_and_accept(win, monkeypatch):
    from PySide6.QtWidgets import QDialog

    from lumacut_job import bentbox_qt
    doc = win.canvas.document
    doc.active_layer.fill_mode = "none"
    monkeypatch.setattr(bentbox_qt.BentBoxDialog, "exec", lambda self: QDialog.Rejected)
    n = len(doc.shapes)
    assert win.job_tools.bentbox() == [] and len(doc.shapes) == n
    monkeypatch.setattr(bentbox_qt.BentBoxDialog, "exec", lambda self: (
        self.height_mm.setValue(30), QDialog.Accepted)[1])
    ids = win.job_tools.bentbox()
    assert ids
    spec = generated.spec_from_meta(doc.shape(ids[0]).generator)
    assert spec.height_mm == 30


def test_re_edit_bent_box_keeps_place_layer_and_group(win, monkeypatch):
    from lumacut_canvas.commands import SetGeometryCommand
    from lumacut_job.generated_qt import edit_dialog, generated_unit, unit_spec
    tools, doc, stack = win.job_tools, win.canvas.document, win.canvas.undo_stack
    doc.active_layer.fill_mode = "none"
    ids = tools.bentbox(BentBoxSpec(80, 60, 40))
    group = doc.shape(ids[0]).groups[-1]
    old = {i: doc.shape(i).geom.copy() for i in ids}
    stack.push(SetGeometryCommand(doc, old, {i: g.translated(0, 10) for i, g in old.items()},
                                  "Verschieben"))
    win.canvas.set_selection(ids[:1])
    unit = generated_unit(win.canvas)
    assert unit.kind == "bentbox" and unit.label == "Flex-Box"
    got = unit_spec(unit)
    assert (got.width_mm, got.depth_mm, got.height_mm) == (80, 60, 40)
    dlg = edit_dialog(unit, got, doc.layer(unit.layer_id), win, touch=True)
    assert dlg.windowTitle() == "Flex-Box bearbeiten" and dlg.ok_button.text() == "Übernehmen"
    assert not dlg.new_layer.isVisible() and not dlg.new_layer.isChecked()
    assert dlg.radius.minimumHeight() >= 44 and dlg.spec() == got
    dlg.deleteLater()
    depth = stack.index()
    new_ids = tools.edit_generated(replace(got, radius_mm=12, pattern="wave"))
    assert new_ids and stack.index() == depth + 1
    u2 = generated.find_unit(doc, new_ids[0])
    assert u2.center == pytest.approx(unit.center, abs=1e-6) and u2.group == group
    assert u2.layer_id == unit.layer_id
    assert generated.spec_from_meta(doc.shape(new_ids[0]).generator).radius_mm == 12
    stack.undo()
    assert all(doc.has_shape(i) for i in ids)
    from lumacut_job import bentbox_qt
    opened = []
    monkeypatch.setattr(bentbox_qt.BentBoxDialog, "exec", lambda self: opened.append(
        (self.windowTitle(), self.kerf.minimumHeight())) or 0)
    win.canvas.set_touch_mode(True, persist=False)
    assert tools.edit_generated_at(ids[-1]) is True and opened == [("Flex-Box bearbeiten", 44)]
    win.canvas.set_touch_mode(False, persist=False)
    assert tools.edit_generated_at(ids[-1]) is True and opened[1][1] < 44
