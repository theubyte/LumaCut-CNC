"""Text auf Pfad und Entlang Pfad kopieren: Pfad-Kurve, Platzierung, Objekte, Dialoge, Menüs."""

import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _pi_guard import pi_check  # noqa: E402

from lumacut_canvas import alongpath  # noqa: E402
from lumacut_canvas.alongpath import PathCurve, normalize_closed  # noqa: E402
from lumacut_canvas.model import Document, Geometry, Shape  # noqa: E402
from lumacut_canvas.workarea import WORK_HEIGHT_MM, WORK_WIDTH_MM  # noqa: E402
from lumacut_job import pathtext  # noqa: E402
from lumacut_job.arctext import Glyph  # noqa: E402
from lumacut_job.pathtext import PathTextSpec  # noqa: E402

W, H = 4.0, 5.0


def box(ch="A", w=W, h=H):
    return Glyph(ch, w, (((0.0, -h), (w, -h), (w, 0.0), (0.0, 0.0)),))


def ring_glyph(ch="O", w=W, h=H):
    outer = ((0.0, -h), (w, -h), (w, 0.0), (0.0, 0.0))
    inner = ((1.0, -h + 1), (1.0, -1.0), (w - 1, -1.0), (w - 1, -h + 1))
    return Glyph(ch, w, (outer, inner))


def circle_pts(cx, cy, r, n=360, ccw=False):
    pts = [(cx + r * math.cos(2 * math.pi * k / n), cy + r * math.sin(2 * math.pi * k / n))
           for k in range(n)]
    return pts[::-1] if ccw else pts


def dist(p, q):
    return math.hypot(p[0] - q[0], p[1] - q[1])


def flat(pts):
    return [c for p in pts for c in p]


def ang_diff(a, b):
    return (a - b + 180.0) % 360.0 - 180.0


def doc_with(*shapes):
    d = Document()
    for s in shapes:
        s.layer_id = d.active_layer_id
        d.add_shape(s)
    return d


def rect(x, y, w, h, rot=0.0):
    return Shape("rect", Geometry(x, y, w, h, rot), "?")


def ellipse(x, y, w, h):
    return Shape("ellipse", Geometry(x, y, w, h), "?")


def line(x0, y0, x1, y1):
    return Shape("line", Geometry(x0, y0, x1 - x0, y1 - y0), "?")


def glyph_box(p):
    xs = [x for r in p.rings for x, _ in r]
    ys = [y for r in p.rings for _, y in r]
    return min(xs), min(ys), max(xs), max(ys)


# --- PathCurve ------------------------------------------------------------------------------
def test_open_curve_length_points_tangents_and_extrapolation():
    c = PathCurve([(0, 0), (30, 0), (30, 40)])
    assert c.length == pytest.approx(70.0) and not c.closed
    assert c.point_at(15) == pytest.approx((15, 0))
    assert c.point_at(50) == pytest.approx((30, 20))
    assert c.angle_at(10) == pytest.approx(0.0) and c.angle_at(40) == pytest.approx(90.0)
    assert c.point_at(-5) == pytest.approx((-5, 0))        # vor dem Anfang geradlinig weiter
    assert c.point_at(80) == pytest.approx((30, 50))       # hinter dem Ende geradlinig weiter
    assert c.chord_angle(25, 35) == pytest.approx(45.0)    # über den Knick: Sehne
    assert c.chord_angle(5, 5) == pytest.approx(0.0)       # entartet: Tangente


def test_closed_curve_wraps_and_reversed_keeps_start():
    sq = [(0, 0), (10, 0), (10, 10), (0, 10)]
    c = PathCurve(sq, True)
    assert c.closed and c.length == pytest.approx(40.0)
    assert c.point_at(45) == pytest.approx((5, 0)) and c.point_at(-5) == pytest.approx((0, 5))
    r = c.reversed()
    assert r.closed and r.length == pytest.approx(40.0) and r.point_at(0) == pytest.approx((0, 0))
    assert r.point_at(5) == pytest.approx((0, 5)) and r.angle_at(5) == pytest.approx(90.0)
    o = PathCurve([(0, 0), (10, 0)]).reversed()
    assert o.point_at(0) == pytest.approx((10, 0)) and o.angle_at(1) == pytest.approx(180.0)
    with pytest.raises(ValueError):
        PathCurve([(1, 1), (1, 1)])
    assert not PathCurve([(0, 0), (5, 0)], True).closed   # zwei Punkte sind kein Ring


def test_normalize_closed_starts_top_centre_clockwise():
    sq = normalize_closed([(0, 0), (0, 10), (10, 10), (10, 0)])      # gegen den Uhrzeigersinn
    assert sq[0] == pytest.approx((5, 0)) and sq[1] == pytest.approx((10, 0))
    assert alongpath.signed_area(sq) > 0 and len(sq) == 5
    circ = normalize_closed(circle_pts(50, 50, 20, ccw=True) + [circle_pts(50, 50, 20)[0]])
    assert circ[0] == pytest.approx((50, 30), abs=0.01) and circ[1][0] > circ[0][0]
    star = [(50, 10), (55, 40), (80, 40), (60, 55), (70, 85), (50, 65), (30, 85), (40, 55),
            (20, 40), (45, 40)]
    assert normalize_closed(star)[0] == pytest.approx((50, 10))       # obere Spitze
    tri = normalize_closed([(0, 10), (10, 0), (20, 10)])               # Spitze genau auf der Mitte
    assert tri[0] == pytest.approx((10, 0)) and len(tri) == 3


def test_shape_curve_per_kind(qapp):
    r = alongpath.shape_curve(rect(10, 20, 40, 10))
    assert r.closed and r.length == pytest.approx(100.0) and r.point_at(0) == pytest.approx((30, 20))
    assert r.angle_at(1) == pytest.approx(0.0)
    rr = alongpath.shape_curve(rect(10, 20, 40, 10, rot=90))
    assert rr.length == pytest.approx(100.0) and rr.point_at(0) == pytest.approx((30, 5), abs=1e-6)
    rounded = Shape("rect", Geometry(0, 0, 40, 20), "?", corner_radius=5.0)
    assert alongpath.shape_curve(rounded).length == pytest.approx(120 - 40 + 10 * math.pi, abs=0.05)
    e = alongpath.shape_curve(ellipse(0, 0, 40, 40))
    assert e.length == pytest.approx(40 * math.pi, rel=1e-3)
    assert e.point_at(0) == pytest.approx((20, 0), abs=1e-6)
    assert e.point_at(e.length / 4) == pytest.approx((40, 20), abs=0.01)   # im Uhrzeigersinn
    ln = alongpath.shape_curve(line(40, 10, 10, 50))
    assert not ln.closed and ln.point_at(0) == pytest.approx((40, 10)) and ln.length == pytest.approx(50)
    open_path = Shape.from_points("path", [(0, 0), (20, 0), (20, 20)], "?")
    assert not alongpath.shape_curve(open_path).closed
    # Polygon mit Loch: der längste Ring zählt
    poly = Shape.from_points("polygon", [(0, 0), (40, 0), (40, 40), (0, 40),
                                         (10, 10), (10, 20), (20, 20)], "?", rings=[4])
    assert alongpath.shape_curve(poly).length == pytest.approx(160.0)


def test_shape_curve_rejects_text_images_codes_and_tiny_paths(qapp):
    txt = Shape("text", Geometry(0, 0, 30, 10), "?", text="A")
    code = rect(0, 0, 10, 10)
    code.generator = {"kind": "qr"}
    for s in (txt, code):
        assert not alongpath.can_be_path(s)
        with pytest.raises(ValueError):
            alongpath.shape_curve(s)
    with pytest.raises(ValueError, match="zu kurz"):
        alongpath.shape_curve(line(0, 0, 0.5, 0))
    assert not alongpath.can_be_path(line(5, 5, 5, 5))


def test_pick_path_prefers_single_open_then_largest():
    a, b, c = rect(0, 0, 10, 10), ellipse(0, 0, 100, 100), line(0, 0, 20, 0)
    t = Shape("text", Geometry(0, 0, 30, 10), "?", text="A")
    d = doc_with(a, b, c, t)
    assert alongpath.pick_path(d, [a.id, t.id]) == a.id
    assert alongpath.pick_path(d, [a.id, b.id]) == b.id          # größte Box
    assert alongpath.pick_path(d, [a.id, b.id, c.id]) == c.id    # offene Linie gewinnt
    a.groups = ("g",)
    assert alongpath.pick_path(d, [a.id, t.id]) is None          # Gruppen und Text nie
    assert alongpath.pick_path(d, ["missing"]) is None


def test_stations_open_closed_and_start():
    o = PathCurve([(0, 0), (90, 0)])
    assert alongpath.stations(o, 4) == pytest.approx([0, 30, 60, 90])
    c = PathCurve([(0, 0), (10, 0), (10, 10), (0, 10)], True)
    assert alongpath.stations(c, 4) == pytest.approx([0, 10, 20, 30])
    assert alongpath.stations(c, 4, 12.5) == pytest.approx([5, 15, 25, 35])
    assert len(alongpath.stations(o, 1)) == 2 and len(alongpath.stations(o, 10_000)) == 500


# --- Entlang Pfad kopieren (Engine) -----------------------------------------------------------
def test_copy_along_open_line_centres_and_rotation():
    part = rect(0, 0, 4, 2)
    d = doc_with(part)
    res = alongpath.copy_along(d, [part.id], PathCurve([(20, 50), (20, 110)]), 4)
    assert res.count == 4 and len(res.shapes) == 4 and res.step_mm == pytest.approx(20.0)
    centres = [s.geom.center() for s in res.shapes]
    assert flat(centres) == pytest.approx(flat([(20, 50), (20, 70), (20, 90), (20, 110)]))
    assert all(s.geom.rot == pytest.approx(90.0) for s in res.shapes)    # Pfad zeigt nach unten
    assert all(s.id != part.id for s in res.shapes) and part.geom.as_tuple() == (0, 0, 4, 2)
    upright = alongpath.copy_along(d, [part.id], PathCurve([(20, 50), (20, 110)]), 3, rotate=False)
    assert all(s.geom.rot == 0.0 for s in upright.shapes)
    assert "3 Kopie(n) im Abstand 30.0 mm" in upright.readout() and "offen" in upright.readout()


def test_copy_along_circle_like_a_rotated_circular_array():
    part = rect(0, 0, 6, 3)
    d = doc_with(part)
    curve = alongpath.shape_curve(ellipse(50, 50, 80, 80), [circle_pts(90, 90, 40) + [(130, 90)]])
    res = alongpath.copy_along(d, [part.id], curve, 4)
    assert res.closed and res.step_mm == pytest.approx(curve.length / 4)
    cs = [s.geom.center() for s in res.shapes]
    for got, want in zip(cs, [(90, 50), (130, 90), (90, 130), (50, 90)]):
        assert dist(got, want) < 0.05
    rots = [s.geom.rot for s in res.shapes]
    for got, want in zip(rots, [0, 90, 180, 270]):
        assert abs(ang_diff(got, want)) < 1.0
    shifted = alongpath.copy_along(d, [part.id], curve, 4, start_pct=12.5)
    c0 = shifted.shapes[0].geom.center()
    assert dist(c0, (90 + 40 * math.sin(math.radians(45)), 90 - 40 * math.cos(math.radians(45)))) < 0.1


def test_copy_along_keeps_unit_together_with_new_groups():
    a, b = rect(0, 0, 4, 4), rect(6, 0, 4, 4)
    a.groups = b.groups = ("g1",)
    d = doc_with(a, b)
    res = alongpath.copy_along(d, [a.id, b.id], PathCurve([(50, 50), (150, 50)]), 3)
    assert len(res.shapes) == 6
    pairs = [res.shapes[i:i + 2] for i in range(0, 6, 2)]
    groups = {p[0].groups for p in pairs}
    assert len(groups) == 3 and all(p[0].groups == p[1].groups != ("g1",) for p in pairs)
    for p, x in zip(pairs, (50, 100, 150)):
        assert p[0].geom.center() == pytest.approx((x - 3, 50))     # Abstand innerhalb bleibt
        assert p[1].geom.center() == pytest.approx((x + 3, 50))
    with pytest.raises(ValueError):
        alongpath.copy_along(d, [], PathCurve([(0, 0), (10, 0)]), 3)


def test_copy_selection_splits_path_and_objects(qapp):
    part, path = rect(0, 0, 4, 4), line(20, 20, 120, 20)
    d = doc_with(part, path)
    res = alongpath.copy_selection(d, [part.id, path.id], 5)
    assert len(res.shapes) == 5 and res.shapes[-1].geom.center() == pytest.approx((120, 20))
    with pytest.raises(ValueError, match="Pfad"):
        alongpath.copy_selection(doc_with(Shape("text", Geometry(0, 0, 5, 5), "?", text="x")),
                                 [], 3)
    with pytest.raises(ValueError, match="außer dem Pfad"):
        alongpath.copy_selection(d, [path.id], 3)
    calls = []
    res = alongpath.copy_selection(d, [part.id, path.id], 2,
                                   outline=lambda s: calls.append(s.id) or [[(0, 0), (0, 50)]])
    assert calls == [path.id] and res.shapes[1].geom.center() == pytest.approx((0, 50))


# --- Text auf Pfad (Engine) -------------------------------------------------------------------
def test_text_on_horizontal_line_centred_upright_on_the_baseline():
    curve = PathCurve([(20, 50), (120, 50)])
    res = pathtext.place_on_path([box("A"), box("B"), box("C")], curve, PathTextSpec())
    assert res.span_mm == pytest.approx(12.0) and res.overhang_mm == 0.0 and not res.closed
    xs = [p.anchor[0] for p in res.placements]
    assert xs == pytest.approx([66, 70, 74])
    for p in res.placements:
        assert p.rotation_deg == pytest.approx(0.0)
        x0, y0, x1, y1 = glyph_box(p)
        assert y1 == pytest.approx(50.0) and y0 == pytest.approx(45.0)     # Grundlinie auf der Linie
        assert x1 - x0 == pytest.approx(W)
    assert "Textlänge 12.0 mm auf 100.0 mm Pfad (offen, 12 %)" == res.readout()


@pytest.mark.parametrize("align,first,last", [("start", 2, 10), ("end", -10, -2),
                                              ("center", -4, 4)])
def test_align_relative_to_position(align, first, last):
    curve = PathCurve([(0, 50), (100, 50)])
    res = pathtext.place_on_path([box(), box(), box()], curve,
                                 PathTextSpec(position_pct=40.0, align=align))
    assert res.placements[0].anchor[0] == pytest.approx(40 + first)
    assert res.placements[-1].anchor[0] == pytest.approx(40 + last)


def test_distance_flip_spacing_and_overhang_on_a_line():
    curve = PathCurve([(20, 50), (120, 50)])
    up = pathtext.place_on_path([box()], curve, PathTextSpec(distance_mm=3.0))
    assert glyph_box(up.placements[0])[3] == pytest.approx(47.0)
    down = pathtext.place_on_path([box()], curve, PathTextSpec(distance_mm=-H / 2))
    y0, y1 = glyph_box(down.placements[0])[1::2]
    assert (y0 + y1) / 2 == pytest.approx(50.0)                       # mittig auf dem Pfad
    flip = pathtext.place_on_path([box("A"), box("B")], curve, PathTextSpec(flip=True))
    assert all(abs(ang_diff(p.rotation_deg, 180)) < 1e-6 for p in flip.placements)
    assert flip.placements[0].anchor[0] > flip.placements[1].anchor[0]   # läuft nach links
    assert glyph_box(flip.placements[0])[1] == pytest.approx(50.0)       # unter der Linie
    sp = pathtext.place_on_path([box(), box()], curve, PathTextSpec(spacing_mm=2.0))
    assert sp.span_mm == pytest.approx(10.0)
    assert sp.placements[1].anchor[0] - sp.placements[0].anchor[0] == pytest.approx(6.0)
    over = pathtext.place_on_path([box()] * 5, curve, PathTextSpec(position_pct=100.0, align="start"))
    assert over.overhang_mm == pytest.approx(20.0) and "ragt 20.0 mm" in over.readout()
    assert over.placements[-1].anchor[0] == pytest.approx(138.0)        # verlängert, nicht abgeschnitten


def test_closed_circle_top_and_flipped_bottom_read_left_to_right():
    curve = PathCurve(normalize_closed(circle_pts(100, 100, 40, n=720)), True)
    glyphs = [box(c) for c in "ABCDE"]
    top = pathtext.place_on_path(glyphs, curve, PathTextSpec())
    mid = top.placements[2]
    assert mid.anchor == pytest.approx((100, 60), abs=0.01) and abs(mid.rotation_deg) < 0.5
    assert top.placements[0].anchor[0] < top.placements[-1].anchor[0]
    assert top.placements[0].rotation_deg < 0 < top.placements[-1].rotation_deg
    for p in top.placements:
        assert dist(p.anchor, (100, 100)) == pytest.approx(40.0, abs=0.05)
        assert glyph_box(p)[1] < 60.5                                   # außen auf dem Kreis
    bottom = pathtext.place_on_path(glyphs, curve, PathTextSpec(flip=True))
    mid = bottom.placements[2]
    assert mid.anchor == pytest.approx((100, 140), abs=0.01) and abs(ang_diff(mid.rotation_deg, 0)) < 0.5
    assert bottom.placements[0].anchor[0] < bottom.placements[-1].anchor[0]   # links nach rechts
    assert glyph_box(mid)[1] == pytest.approx(135.0, abs=0.05)                # innen
    right = pathtext.place_on_path(glyphs, curve, PathTextSpec(position_pct=25.0))
    assert right.placements[2].anchor == pytest.approx((140, 100), abs=0.01)
    assert right.placements[2].rotation_deg == pytest.approx(90.0, abs=0.5)
    out = pathtext.place_on_path(glyphs, curve, PathTextSpec(distance_mm=2.0))
    assert dist(out.placements[2].anchor, (100, 100)) == pytest.approx(42.0, abs=0.05)
    assert top.closed and top.overhang_mm == 0.0 and "geschlossen" in top.readout()


def test_text_wraps_across_the_start_of_a_closed_path():
    curve = PathCurve(normalize_closed([(0, 0), (40, 0), (40, 40), (0, 40)]), True)
    res = pathtext.place_on_path([box(), box(), box()], curve, PathTextSpec(position_pct=0.0))
    assert flat(p.anchor for p in res.placements) == pytest.approx([16, 0, 20, 0, 24, 0])
    res = pathtext.place_on_path([box(), box(), box()], curve,
                                 PathTextSpec(position_pct=0.0, align="end"))
    assert res.placements[0].anchor == pytest.approx((10, 0))


def test_upright_letters_and_corner_uses_the_chord():
    curve = PathCurve([(0, 50), (50, 50), (50, 100)])
    corner = pathtext.place_on_path([box()], curve, PathTextSpec(position_pct=50.0))
    assert corner.placements[0].rotation_deg == pytest.approx(45.0)
    upright = pathtext.place_on_path([box()] * 4, curve, PathTextSpec(rotate=False,
                                                                     position_pct=80.0))
    assert all(p.rotation_deg == 0.0 for p in upright.placements)
    # aufrecht, aber trotzdem senkrecht zum Pfad angehoben (Pfad läuft hier nach unten)
    raised = pathtext.place_on_path([box()], curve, PathTextSpec(rotate=False, position_pct=80.0,
                                                                 distance_mm=3.0))
    assert raised.placements[0].anchor == pytest.approx((53.0, 80.0))


def test_errors_and_spec_normalisation():
    small = PathCurve(normalize_closed(circle_pts(50, 50, 3)), True)
    with pytest.raises(ValueError, match="länger als der Umfang"):
        pathtext.place_on_path([box()] * 10, small, PathTextSpec())
    with pytest.raises(ValueError, match="Kein Text"):
        pathtext.place_on_path([], small, PathTextSpec())
    s = PathTextSpec(text="a\nb", height_mm=0, spacing_mm=999, position_pct=150, distance_mm=-500,
                     align="x").normalized()
    assert s.text == "a b" and s.height_mm == 1.0 and s.spacing_mm == 50.0
    assert s.position_pct == 100.0 and s.distance_mm == -100.0 and s.align == "center"
    assert PathTextSpec().normalized(True).position_pct == 0.0
    assert PathTextSpec(flip=True).normalized(True).position_pct == 50.0
    assert PathTextSpec(flip=True).normalized(False).position_pct == 50.0
    assert PathTextSpec().normalized().position_pct is None


def test_pathtext_shapes_grouped_polygons_with_holes_on_the_path():
    curve = PathCurve([(20, 50), (120, 50)])
    shapes, res = pathtext.pathtext_shapes([ring_glyph(), Glyph(" ", 2.0), box()], curve,
                                           PathTextSpec(), "L1")
    assert len(shapes) == 2 and len(res.placements) == 3
    assert all(s.kind == "polygon" and s.layer_id == "L1" for s in shapes)
    assert len({s.groups for s in shapes}) == 1 and len(shapes[0].groups) == 1
    assert shapes[0].rings == (4,) and shapes[1].rings == ()
    b = shapes[0].bounds()
    assert b.y + b.h == pytest.approx(50.0) and b.x == pytest.approx(70 - 5)
    with pytest.raises(ValueError, match="Arbeitsfläche"):
        pathtext.pathtext_shapes([box()], PathCurve([(0, 2), (100, 2)]), PathTextSpec(), "L1")
    with pytest.raises(ValueError, match="sichtbaren"):
        pathtext.pathtext_shapes([Glyph(" ", 3.0)], curve, PathTextSpec(), "L1")


# --- Qt: Glyphen, Dialog, Fenster -------------------------------------------------------------
@pytest.fixture
def win(qapp, monkeypatch, tmp_path):
    from PySide6.QtCore import QSettings
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(tmp_path))
    QSettings.setDefaultFormat(QSettings.IniFormat)
    main = pytest.importorskip("main")
    w = main.LumaCutStudio()
    msgs = []
    monkeypatch.setattr(w.job_tools, "_msg", lambda text, ms=8000: msgs.append(text))
    w.msgs = msgs
    yield w
    w.canvas.undo_stack.setClean()
    w.close()
    w.deleteLater()
    qapp.processEvents()


def _add(ed, *shapes):
    from lumacut_canvas.commands import AddShapesCommand
    for s in shapes:
        if s.layer_id == "?":
            s.layer_id = ed.document.active_layer_id
    ed.undo_stack.push(AddShapesCommand(ed.document, list(shapes)))
    return shapes


def test_window_text_on_circle_one_undo_step_and_gcode(win):
    from lumacut_job.planner import optimized_document_gcode
    ed = win.canvas
    doc = ed.document
    circle, = _add(ed, ellipse(110, 80, 100, 100))
    ed.set_selection([circle.id])
    depth = ed.undo_stack.index()
    ids = win.job_tools.path_text(PathTextSpec(text="LumaCut Studio", height_mm=8.0))
    assert len(ids) == 13 and ed.undo_stack.index() == depth + 1
    assert sorted(ed.selection) == sorted(ids) and doc.has_shape(circle.id)
    parts = [doc.shape(i) for i in ids]
    assert len({p.groups for p in parts}) == 1 and all(p.kind == "polygon" for p in parts)
    bs = [p.bounds() for p in parts]
    cx = (min(b.x for b in bs) + max(b.x + b.w for b in bs)) / 2
    assert cx == pytest.approx(160.0, abs=1.5)                     # oben mittig auf dem Kreis
    assert min(b.y for b in bs) > 80 - 12 and max(b.y + b.h for b in bs) < 80 + 30
    assert "Text auf Pfad: 13 Zeichen gruppiert" in win.msgs[-1]
    gcode = optimized_document_gcode(doc)
    assert gcode.count("G1 ") > 50
    pi_check(gcode)
    ed.undo_stack.undo()
    assert not any(doc.has_shape(i) for i in ids) and doc.has_shape(circle.id)


def test_window_replace_selected_text_and_delete_path(win):
    from lumacut_job.pathtext_qt import spec_from_text_shape, split_selection
    ed = win.canvas
    doc = ed.document
    path = Shape.from_points("path", [(40, 120), (90, 90), (140, 120), (190, 90)], "?")
    txt = Shape("text", Geometry(60, 40, 60, 12), "?", text="Hallo")
    _add(ed, path, txt)
    ed.set_selection([txt.id, path.id])
    assert split_selection(doc, ed.selection) == (path.id, txt.id)
    pre = spec_from_text_shape(txt)
    assert pre.text == "Hallo" and 5.0 < pre.height_mm < 12.0
    depth = ed.undo_stack.index()
    ids = win.job_tools.path_text(pre, replace=True, remove_path=True)
    assert len(ids) == 5 and not doc.has_shape(txt.id) and not doc.has_shape(path.id)
    assert ed.undo_stack.index() == depth + 1
    assert "Text ersetzt" in win.msgs[-1] and "Pfad gelöscht" in win.msgs[-1]
    ed.undo_stack.undo()
    assert doc.has_shape(txt.id) and doc.has_shape(path.id) and not any(doc.has_shape(i) for i in ids)


def test_window_needs_a_path_and_reports_errors(win, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    ed = win.canvas
    doc = ed.document
    txt, = _add(ed, Shape("text", Geometry(60, 40, 60, 12), "?", text="Hallo"))
    ed.set_selection([txt.id])
    n = len(doc.shapes)
    assert win.job_tools.path_text(PathTextSpec()) == [] and len(doc.shapes) == n
    assert "bitte einen Pfad auswählen" in win.msgs[-1]
    warned = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: warned.append(a[2]))
    small, = _add(ed, ellipse(100, 100, 6, 6))
    ed.set_selection([small.id])
    assert win.job_tools.path_text(PathTextSpec(text="Viel zu lang")) == []
    assert warned and "länger als der Umfang" in warned[-1] and len(doc.shapes) == n + 1
    edge, = _add(ed, line(5, 2, 200, 2))
    ed.set_selection([edge.id])
    assert win.job_tools.path_text(PathTextSpec(text="Rand")) == []
    assert "Arbeitsfläche" in warned[-1]
    doc.active_layer.locked = True
    big, = _add(ed, ellipse(100, 100, 80, 80))
    doc.active_layer.locked = False
    ed.set_selection([big.id])
    doc.active_layer.locked = True
    try:
        from lumacut_job.pathtext_qt import insert_path_text
        with pytest.raises(ValueError, match="gesperrt"):
            insert_path_text(ed, PathTextSpec(text="X"), big.id)
    finally:
        doc.active_layer.locked = False


def test_dialog_defaults_side_readout_and_validation(qapp):
    from lumacut_job.pathtext_qt import PathTextDialog
    closed = PathCurve(normalize_closed(circle_pts(100, 100, 40)), True)
    dlg = PathTextDialog(closed, spec=PathTextSpec(text="Hallo"), can_replace=True)
    assert dlg.windowTitle() == "Text auf Pfad"
    assert dlg.position.value() == 0.0 and dlg.ok_button.isEnabled() and dlg.replace_source()
    assert "geschlossen" in dlg.info.text() and not dlg.remove_path()
    dlg.side.setCurrentIndex(1)
    assert dlg.position.value() == 50.0 and dlg.spec().flip
    dlg.position.setValue(30.0)
    dlg.side.setCurrentIndex(0)
    assert dlg.position.value() == 30.0                      # eigene Lage bleibt
    dlg.text.setText("")
    assert not dlg.ok_button.isEnabled() and "Text eingeben" in dlg.info.text()
    dlg.text.setText("X" * 120)
    assert not dlg.ok_button.isEnabled() and "länger als der Umfang" in dlg.info.text()
    dlg.text.setText("Hi")
    dlg.rotate.setChecked(False)
    dlg.distance.setValue(-4.0)
    dlg.align.setCurrentIndex(dlg.align.findData("start"))
    dlg.delete_path.setChecked(True)
    s = dlg.spec()
    assert (s.text, s.rotate, s.distance_mm, s.align, s.position_pct) == ("Hi", False, -4.0, "start", 30.0)
    assert dlg.remove_path() and dlg.ok_button.isEnabled()
    dlg.deleteLater()
    open_dlg = PathTextDialog(PathCurve([(20, 50), (120, 50)]))
    assert open_dlg.position.value() == 50.0 and not open_dlg.replace_source()
    assert open_dlg.replace.isHidden()
    open_dlg.side.setCurrentIndex(1)
    assert open_dlg.position.value() == 50.0                 # offen: Lage bleibt
    open_dlg.deleteLater()


def test_dialog_from_the_action(win, monkeypatch):
    from PySide6.QtWidgets import QDialog

    from lumacut_job import pathtext_qt
    ed = win.canvas
    line_shape, = _add(ed, line(30, 100, 230, 100))
    ed.set_selection([line_shape.id])
    seen = []

    def fake_exec(self):
        seen.append((self.curve.closed, self.position.value()))
        self.text.setText("ABC")
        return QDialog.Accepted
    monkeypatch.setattr(pathtext_qt.PathTextDialog, "exec", fake_exec)
    ids = win.job_tools.path_text_action.trigger() or ed.selection
    assert seen == [(False, 50.0)] and len(ids) == 3
    monkeypatch.setattr(pathtext_qt.PathTextDialog, "exec", lambda self: QDialog.Rejected)
    ed.set_selection([line_shape.id])
    assert win.job_tools.path_text() == []


def test_action_shortcut_design_menu_and_unique(win):
    from PySide6.QtGui import QAction, QKeySequence
    a = win.job_tools.path_text_action
    assert a.objectName() == "path_text_action" and a.text() == "Text auf Pfad…"
    assert a in win.main_view.design_menu.actions()
    acts = win.main_view.design_menu.actions()
    assert acts.index(a) == acts.index(win.job_tools.arc_action) + 1
    owners = [x for x in win.findChildren(QAction) if x.shortcut() == QKeySequence("Alt+Shift+P")]
    assert owners == [a]
    owners = [x for x in win.findChildren(QAction) if x.shortcut() == QKeySequence("Alt+Shift+C")]
    assert [x.text() for x in owners] == ["Entlang Pfad kopieren …"]


def test_path_text_is_usable_downstream_fill_and_save(win, tmp_path):
    """Buchstaben sind gewöhnliche Polygone: Füllen, Speichern / Laden, Zerlegen."""
    from lumacut_canvas.document_io import load_document, save_document
    ed = win.canvas
    doc = ed.document
    circle, = _add(ed, ellipse(110, 80, 100, 100))
    ed.set_selection([circle.id])
    ids = win.job_tools.path_text(PathTextSpec(text="OBO", height_mm=10.0, flip=True))
    assert len(ids) == 3
    assert doc.shape(ids[0]).rings                       # „O“ mit Loch
    f = tmp_path / "t.lcs"
    save_document(doc, f)
    back = load_document(f)
    for i in ids:
        assert back.shape(i).rings == doc.shape(i).rings and back.shape(i).groups == doc.shape(i).groups
        flat = [c for p in back.shape(i).points for c in p]
        assert flat == pytest.approx([c for p in doc.shape(i).points for c in p], abs=1e-6)


# --- Canvas: Entlang Pfad kopieren -------------------------------------------------------------
@pytest.fixture
def ed(qapp):
    from lumacut_canvas.editor import CanvasEditor
    e = CanvasEditor()
    e.resize(1000, 700)
    e.show()
    qapp.processEvents()
    yield e
    e.undo_stack.setClean()
    e.close()


def test_editor_copy_along_one_undo_step_and_selection(ed):
    part, circle = _add(ed, rect(10, 10, 6, 3), ellipse(100, 100, 80, 80))
    msgs = []
    ed.statusMessage.connect(msgs.append)
    tool = ed.arranger.along
    asked = []
    tool.ask = lambda curve: asked.append(curve) or {"count": 8, "rotate": True, "start_pct": 0.0}
    ed.set_selection([part.id, circle.id])
    depth = ed.undo_stack.index()
    ed.actions_by_name["copy_along_path"].trigger()
    assert asked and asked[0].closed
    doc = ed.document
    assert len(doc.shapes) == 10 and ed.undo_stack.index() == depth + 1
    assert len(ed.selection) == 8 and part.id not in ed.selection
    cs = [doc.shape(i).geom.center() for i in ed.selection]
    assert all(dist(c, (140, 140)) == pytest.approx(40, abs=0.05) for c in cs)
    assert "8 Kopie(n)" in msgs[-1] and tool.last["count"] == 8
    ed.undo_stack.undo()
    assert len(doc.shapes) == 2


def test_editor_copy_along_refuses_outside_and_without_path(ed):
    part, edge = _add(ed, rect(10, 10, 10, 10), line(2, 2, 200, 2))
    msgs = []
    ed.statusMessage.connect(msgs.append)
    tool = ed.arranger.along
    tool.ask = lambda curve: {"count": 5, "rotate": False, "start_pct": 0.0}
    ed.set_selection([part.id, edge.id])
    assert tool.copy() == [] and len(ed.document.shapes) == 2 and "außerhalb" in msgs[-1]
    ed.set_selection([part.id])
    assert tool.copy() == [] and "einen Pfad" in msgs[-1]
    tool.ask = lambda curve: None
    ed.set_selection([part.id, edge.id])
    assert tool.copy() == [] and len(ed.document.shapes) == 2


def test_copy_along_dialog_readout_start_and_values(qapp):
    from lumacut_canvas.alongpath_ui import CopyAlongDialog
    closed = PathCurve([(0, 0), (40, 0), (40, 40), (0, 40)], True)
    dlg = CopyAlongDialog(closed, values={"count": 4})
    assert dlg.start.isEnabled() and "Abstand 40.0 mm" in dlg.readout.text()
    dlg.count.setValue(8)
    assert "Abstand 20.0 mm" in dlg.readout.text() and "geschlossen" in dlg.readout.text()
    dlg.rotate.setChecked(False)
    dlg.start.setValue(10.0)
    assert dlg.values() == {"count": 8, "rotate": False, "start_pct": 10.0}
    dlg.deleteLater()
    dlg = CopyAlongDialog(PathCurve([(0, 0), (90, 0)]), values={"count": 4})
    assert not dlg.start.isEnabled() and "Abstand 30.0 mm" in dlg.readout.text()
    dlg.deleteLater()


def test_copy_along_in_arrange_and_context_menu(ed):
    from PySide6.QtCore import QPointF
    a = ed.actions_by_name["copy_along_path"]
    assert a.shortcut().toString() == "Alt+Shift+C" and a.text() == "Entlang Pfad kopieren …"
    texts = [x.text() for x in ed.arrange_button.menu().actions() if x.text()]
    assert texts.index("Entlang Pfad kopieren …") == texts.index("Kreis-Array …") + 1
    _add(ed, rect(10, 10, 20, 10))
    menu = ed.build_context_menu(QPointF(20, 15))
    sub = next(x.menu() for x in menu.actions() if x.menu() is not None
               and x.menu().objectName() == "ArrangeMenu")
    assert "Entlang Pfad kopieren …" in [x.text() for x in sub.actions()]


def test_copies_along_a_line_cut_once_each_and_existing_gcode_unchanged(ed):
    from lumacut_canvas.toolpath import parse_gcode
    from lumacut_job.planner import optimized_document_gcode
    part, path = _add(ed, rect(10, 10, 10, 6), line(40, 60, 240, 60))
    before = optimized_document_gcode(ed.document, scan_offsets=None)
    pi_check(before)
    tool = ed.arranger.along
    tool.ask = lambda curve: {"count": 5, "rotate": True, "start_pct": 0.0}
    ed.set_selection([part.id, path.id])
    assert len(tool.copy()) == 5
    g = optimized_document_gcode(ed.document, scan_offsets=None)
    pi_check(g)
    assert parse_gcode(g).cut_length_mm == pytest.approx(6 * 32 + 200, rel=1e-3)
    ed.undo_stack.undo()
    assert optimized_document_gcode(ed.document, scan_offsets=None) == before


def test_work_area_constants_are_large_enough_for_the_tests():
    assert WORK_WIDTH_MM > 240 and WORK_HEIGHT_MM > 200
