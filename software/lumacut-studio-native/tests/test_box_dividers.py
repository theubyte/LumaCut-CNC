"""Box generator dividers (slotted egg-crate inserts) – lumacut_job.boxgen / boxgen_qt."""

from __future__ import annotations

from dataclasses import replace

import pytest
from _pi_guard import pi_check
from shapely.geometry import Polygon

from lumacut_canvas.model import Document, Shape
from lumacut_canvas.shape_paths import shape_polygons
from lumacut_canvas.toolpath import parse_gcode
from lumacut_job import boxgen, generated
from lumacut_job.boxgen import BoxSpec

OLD_META_KEYS = {"width_mm", "depth_mm", "height_mm", "thickness_mm", "finger_mm", "kerf_mm",
                 "lid", "inner", "spacing_mm"}


def _dividers(spec):
    return [p for p in boxgen.panels(spec) if p.name.startswith("Trennwand")]


def _box_panels(spec):
    return [p for p in boxgen.panels(spec) if not p.name.startswith("Trennwand")]


# --- spec ----------------------------------------------------------------------------------------

def test_spec_defaults_to_no_dividers_and_clamps_counts():
    s = BoxSpec().normalized()
    assert (s.dividers_x, s.dividers_y) == (0, 0)
    n = BoxSpec(dividers_x=99, dividers_y=-3).normalized()
    assert (n.dividers_x, n.dividers_y) == (boxgen.DIVIDER_RANGE[1], 0)
    assert BoxSpec(dividers_x="abc", dividers_y=float("nan")).normalized().dividers_x == 0
    assert BoxSpec(dividers_x=2.6).normalized().dividers_x == 3
    assert isinstance(BoxSpec(dividers_y=1.0).normalized().dividers_y, int)


def test_equal_compartments_and_divider_positions():
    s = BoxSpec(100, 80, 50, thickness_mm=3, dividers_x=2, dividers_y=1)
    cw, cd = s.compartments()
    assert cw == pytest.approx((94 - 3) / 2) and cd == pytest.approx((74 - 6) / 3)
    xs, ys = boxgen.divider_positions(s)
    assert xs == pytest.approx([cw + 1.5])
    assert ys == pytest.approx([cd + 1.5, 2 * cd + 3 + 1.5])
    # compartments between walls / dividers are all the same
    edges = [0.0] + [e for y in ys for e in (y - 1.5, y + 1.5)] + [74.0]
    widths = [b - a for a, b in zip(edges[::2], edges[1::2])]
    assert widths == pytest.approx([cd] * 3)
    assert BoxSpec().compartments() == pytest.approx(BoxSpec().inside()[:2])


# --- panels --------------------------------------------------------------------------------------

def test_box_panels_are_unchanged_by_dividers():
    for kw in ({}, {"lid": False}, {"inner": True, "kerf_mm": 0.2}):
        plain = boxgen.panels(BoxSpec(**kw))
        with_div = boxgen.panels(BoxSpec(dividers_x=2, dividers_y=3, **kw))
        assert _box_panels(BoxSpec(dividers_x=2, dividers_y=3, **kw)) == plain
        assert len(with_div) == len(plain) + 5
    names = [p.name for p in _dividers(BoxSpec(dividers_x=2, dividers_y=1))]
    assert names == ["Trennwand quer 1", "Trennwand quer 2", "Trennwand längs 1"]


def test_divider_size_is_the_inside_and_slots_are_half_height():
    s = BoxSpec(100, 80, 50, thickness_mm=3, kerf_mm=0, dividers_x=1, dividers_y=2)
    iw, id_, ih = s.inside()
    xs, ys = boxgen.divider_positions(s)
    for p in _dividers(s):
        poly = Polygon(p.outline)
        assert poly.is_valid
        across = p.name.startswith("Trennwand quer")
        assert p.size == pytest.approx((iw if across else id_, ih))
        minx, miny, maxx, maxy = poly.bounds
        assert (minx, miny, maxx, maxy) == pytest.approx((0, 0, p.size[0], ih))
        slots = xs if across else ys
        assert p.fingers == {"slots": len(slots)}
        # area: full rectangle minus slots of t × ih/2
        assert poly.area == pytest.approx(p.size[0] * ih - len(slots) * 3 * ih / 2)
        for c in slots:
            # screen y down: quer slotted from the top (y < ih/2), längs from the bottom
            probe_in = (c, ih * 0.25) if across else (c, ih * 0.75)
            probe_mat = (c, ih * 0.75) if across else (c, ih * 0.25)
            assert not poly.contains(Polygon.from_bounds(*probe_in, *probe_in).buffer(0.1))
            assert poly.contains(Polygon.from_bounds(*probe_mat, *probe_mat).buffer(0.1))
            assert not poly.contains(Polygon.from_bounds(c - 1.4, ih * 0.5 - 0.1 if across else
                                                         ih * 0.5 + 0.1, c + 1.4,
                                                         ih * 0.5 - 0.1 if across else
                                                         ih * 0.5 + 0.1).buffer(0.05))
        for (x0, y0), (x1, y1) in zip(p.outline, p.outline[1:] + p.outline[:1]):
            assert abs(x0 - x1) < 1e-6 or abs(y0 - y1) < 1e-6


def _divider_counts(spec, xs3, ys3, zs3):
    """3D points: how many dividers contain each one (kerf 0)."""
    import numpy as np
    import shapely
    s = spec.normalized()
    t = s.thickness_mm
    px, py = boxgen.divider_positions(s)
    count = np.zeros(len(xs3), dtype=int)
    across = [p for p in _dividers(s) if p.name.startswith("Trennwand quer")]
    along = [p for p in _dividers(s) if p.name.startswith("Trennwand längs")]
    for p, c in zip(across, py):
        b = p.size[1]
        poly = Polygon([(x, b - y) for x, y in p.outline])
        w = ys3 - t - c
        inside = shapely.contains_xy(poly, xs3 - t, zs3 - t)
        count += ((abs(w) < t / 2) & inside).astype(int)
    for p, c in zip(along, px):
        b = p.size[1]
        poly = Polygon([(x, b - y) for x, y in p.outline])
        w = xs3 - t - c
        inside = shapely.contains_xy(poly, ys3 - t, zs3 - t)
        count += ((abs(w) < t / 2) & inside).astype(int)
    return count


@pytest.mark.parametrize("spec", [
    BoxSpec(100, 80, 50, thickness_mm=3, kerf_mm=0, dividers_x=2, dividers_y=1),
    BoxSpec(120, 90, 40, thickness_mm=4, kerf_mm=0, lid=False, dividers_x=1, dividers_y=3),
    BoxSpec(80, 60, 30, thickness_mm=3, kerf_mm=0, inner=True, dividers_y=2),
])
def test_assembled_dividers_fill_their_walls_once_and_never_touch_the_box(spec):
    """Fold everything into 3D: each divider wall (incl. every crossing) is filled by exactly one
    part, nothing overlaps a box panel, the compartments stay empty."""
    import numpy as np
    from test_box_generator import _owner_counts
    s = spec.normalized()
    W, D, H = s.outer()
    t = s.thickness_mm
    iw, id_, ih = s.inside()

    def coords(L):
        n = int(L / (t / 3.0))
        return (np.arange(n) + 0.37) * L / n

    X, Y, Z = np.meshgrid(coords(W), coords(D), coords(H), indexing="ij")
    xs3, ys3, zs3 = X.ravel(), Y.ravel(), Z.ravel()
    px, py = boxgen.divider_positions(s)
    inner = (xs3 > t) & (xs3 < W - t) & (ys3 > t) & (ys3 < D - t) & (zs3 > t) & (zs3 < t + ih)
    in_div = np.zeros(len(xs3), dtype=bool)
    for c in px:
        in_div |= abs(xs3 - t - c) < t / 2
    for c in py:
        in_div |= abs(ys3 - t - c) < t / 2
    dc = _divider_counts(s, xs3, ys3, zs3)
    assert (dc[inner & in_div] == 1).all()
    assert (dc[~(inner & in_div)] == 0).all()
    assert (_owner_counts(s, xs3, ys3, zs3)[dc > 0] == 0).all()
    assert (inner & ~in_div).sum() > 0 and (inner & in_div).sum() > 50


def test_kerf_grows_dividers_and_narrows_their_slots():
    k = 0.2
    s0 = BoxSpec(dividers_x=1, dividers_y=1, kerf_mm=0)
    s1 = replace(s0, kerf_mm=k)
    for a, b in zip(_dividers(s0), _dividers(s1)):
        pa, pb = Polygon(a.outline), Polygon(b.outline)
        assert pb.bounds == pytest.approx((0, 0, pa.bounds[2] + k, pa.bounds[3] + k))
        # slot width t − kerf: the grown outline minus the plain one is a k/2 band all round
        assert pb.area == pytest.approx(Polygon(a.outline).buffer(k / 2, join_style=2).area,
                                        rel=1e-6)
    ring = _dividers(s1)[0].outline
    xs = sorted({round(x, 4) for x, _ in ring})
    slot = [b - a for a, b in zip(xs, xs[1:]) if b - a < 3.0]
    assert slot == pytest.approx([3.0 - k])


def test_too_many_dividers_are_refused_in_german():
    with pytest.raises(ValueError, match="Zu viele Trennwände"):
        boxgen.panels(BoxSpec(60, 60, 40, thickness_mm=3, dividers_y=10))
    with pytest.raises(ValueError, match="mindestens 6.0 mm"):
        boxgen.panels(BoxSpec(60, 60, 40, thickness_mm=6, dividers_x=5))
    assert len(boxgen.panels(BoxSpec(60, 60, 40, thickness_mm=3, dividers_y=5))) == 11


def test_describe_reads_dividers_and_compartments():
    text = boxgen.describe(BoxSpec(100, 80, 50, dividers_x=2, dividers_y=1))
    assert "9 Teile (mit Deckel)" in text
    assert "Trennwände 2 quer / 1 längs (gesteckt): 6 Fächer je 45.5 × 22.7 mm" in text
    assert "Trennwände" not in boxgen.describe(BoxSpec())


def test_layout_keeps_dividers_apart_on_the_sheet():
    placed, (lw, lh), fits = boxgen.layout(BoxSpec(dividers_x=2, dividers_y=2))
    assert fits and len(placed) == 10
    polys = [Polygon(r) for _n, r in placed]
    for i, a in enumerate(polys):
        for b in polys[i + 1:]:
            assert a.distance(b) >= 4.0 - 1e-6


# --- generated object, file, G-code ----------------------------------------------------------------

def _doc(shapes):
    doc = Document()
    lid = doc.active_layer_id
    for sh in shapes:
        sh.layer_id = lid
        doc.add_shape(sh)
    return doc


def test_meta_without_dividers_has_the_old_keys_and_round_trips_with_them():
    s = boxgen.centered(BoxSpec())
    meta = generated.tag(boxgen.box_shapes(s, "L"), s)[0].generator
    assert set(meta["spec"]) == OLD_META_KEYS
    d = boxgen.centered(BoxSpec(dividers_x=1, dividers_y=2))
    shapes = generated.tag(boxgen.box_shapes(d, "L"), d)
    assert len(shapes) == 9
    meta = Shape.from_dict(shapes[0].to_dict()).generator
    assert meta["spec"]["dividers_x"] == 1 and meta["spec"]["dividers_y"] == 2
    assert generated.spec_from_meta(meta) == replace(d, x=0.0, y=0.0)
    old = {"kind": "box", "version": 1, "spec": {k: v for k, v in meta["spec"].items()
                                                 if k in OLD_META_KEYS}}
    assert generated.spec_from_meta(old).dividers_x == 0


def test_gcode_is_pi_safe_and_cuts_every_divider_once(qapp):
    from lumacut_job.planner import optimized_document_gcode
    s = boxgen.centered(BoxSpec(dividers_x=1, dividers_y=1))
    shapes = boxgen.box_shapes(s, "L")
    g = optimized_document_gcode(_doc(shapes), scan_offsets=None)
    pi_check(g)
    perimeter = sum(Polygon(shape_polygons(sh)[0]).length for sh in shapes)
    assert parse_gcode(g).cut_length_mm == pytest.approx(perimeter, abs=0.1)
    plain = boxgen.centered(BoxSpec())
    g0 = optimized_document_gcode(_doc(boxgen.box_shapes(plain, "L")), scan_offsets=None)
    g1 = optimized_document_gcode(_doc(boxgen.box_shapes(replace(plain, dividers_x=0), "L")),
                                  scan_offsets=None)
    assert g0 == g1


# --- dialog --------------------------------------------------------------------------------------

def test_dialog_divider_fields_preview_and_readout(qapp):
    from lumacut_job.boxgen_qt import BoxDialog
    dlg = BoxDialog()
    assert dlg.dividers_x.value() == 0 and dlg.dividers_x.text() == "keine"
    assert dlg.spec() == BoxSpec().normalized()
    dlg.dividers_x.setValue(2)
    dlg.dividers_y.setValue(1)
    assert dlg.spec().dividers_x == 2 and dlg.spec().dividers_y == 1
    assert len(dlg.preview.rings) == 9 and "6 Fächer" in dlg.info.text()
    assert "Trennwand quer 1" in [n for n, _r in dlg.preview.rings]
    assert dlg.ok_button.isEnabled()
    dlg.dividers_y.setValue(20)
    assert not dlg.ok_button.isEnabled() and "Zu viele Trennwände" in dlg.info.text()
    dlg.dividers_y.setValue(1)
    dlg.kerf.setValue(0.0)
    assert "sitzen locker" in dlg.info.text()
    dlg.dividers_x.setValue(0)
    dlg.dividers_y.setValue(0)
    assert "sitzen locker" not in dlg.info.text()
    assert "Schlitze" in dlg.dividers_x.toolTip()
    dlg.deleteLater()
    spec = BoxSpec(90, 60, 40, dividers_x=1, dividers_y=3)
    d2 = BoxDialog(spec=spec)
    assert d2.spec() == spec.normalized()
    d2.deleteLater()


def test_dialog_divider_fields_44_px_in_touch_mode(qapp):
    from lumacut_job.boxgen_qt import BoxDialog
    dlg = BoxDialog(touch=True)
    assert dlg.dividers_x.minimumHeight() >= 44 and dlg.dividers_y.minimumHeight() >= 44
    dlg.deleteLater()
    mouse = BoxDialog()
    assert mouse.dividers_x.minimumHeight() < 44
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


def test_window_insert_and_re_edit_dividers(win, tmp_path):
    from lumacut_canvas.document_io import load_document, save_document
    from lumacut_job.generated_qt import generated_unit, unit_spec
    tools, doc, stack = win.job_tools, win.canvas.document, win.canvas.undo_stack
    doc.active_layer.fill_mode = "none"
    depth = stack.index()
    ids = tools.box(BoxSpec(100, 80, 50, dividers_x=1, dividers_y=1))
    assert len(ids) == 8 and stack.index() == depth + 1
    assert len({doc.shape(i).groups for i in ids}) == 1
    assert "Box eingefügt (8 Teile" in win.statusBar().currentMessage()
    assert "Trennwände" in tools.box_action.toolTip()
    win.canvas.set_selection(ids[-1:])
    unit = generated_unit(win.canvas)
    got = unit_spec(unit)
    assert (got.dividers_x, got.dividers_y) == (1, 1)
    new_ids = tools.edit_generated(replace(got, dividers_y=0))
    assert len(new_ids) == 7 and stack.index() == depth + 2
    assert generated.find_unit(doc, new_ids[0]).center == pytest.approx(unit.center, abs=1e-6)
    path = save_document(doc, tmp_path / "fach.lcproj")
    back = load_document(path)
    spec = generated.spec_from_meta(back.shapes[0].generator)
    assert (spec.dividers_x, spec.dividers_y) == (1, 0)
    stack.undo()
    assert all(doc.has_shape(i) for i in ids)
