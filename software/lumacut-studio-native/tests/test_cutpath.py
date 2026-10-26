"""Kerf-Versatz, Haltestege und An-/Abfahrt (lumacut_job.cutpath + Planer)."""
import json
import math

import pytest

from _pi_guard import pi_check
from lumacut_canvas.export import JobLayer, job_layers
from lumacut_canvas.gcode import layers_to_gcode
from lumacut_canvas.model import CUT_LAYER_FIELDS, Document, Geometry, Layer, Shape
from lumacut_job.cutpath import (CutOptions, apply_cut_options, corner_positions, in_work_area,
                                 make_lead, nesting_depth, offset_closed, offset_ring, signed_area,
                                 split_tabs)
from lumacut_job.estimate import estimate_gcode
from lumacut_job.planner import (is_closed, optimize_layers, optimized_document_gcode,
                                 point_in_polygon)


def square(x, y, s, ccw=True):
    sq = [(x, y), (x + s, y), (x + s, y + s), (x, y + s), (x, y)]
    return sq if ccw else list(reversed(sq))


def bbox(p):
    xs, ys = [q[0] for q in p], [q[1] for q in p]
    return min(xs), min(ys), max(xs), max(ys)


def circle(cx, cy, r, n=64):
    pts = [(cx + r * math.cos(2 * math.pi * k / n), cy + r * math.sin(2 * math.pi * k / n))
           for k in range(n)]
    return pts + [pts[0]]


def length(p):
    return sum(math.dist(a, b) for a, b in zip(p, p[1:]))


def layer(polys, **opts):
    return JobLayer("l", "Schneiden", 80, 600, 1, polys, **opts)


# --- Kerf --------------------------------------------------------------------

@pytest.mark.parametrize("ccw", [True, False])
def test_kerf_outer_grows_hole_shrinks(ccw):
    outer, hole = square(50, 50, 100, ccw), square(80, 80, 20, ccw)
    out, warn = offset_closed([outer, hole], 0.1)
    assert not warn and len(out) == 2
    assert bbox(out[0]) == pytest.approx((49.9, 49.9, 150.1, 150.1), abs=1e-6)
    assert bbox(out[1]) == pytest.approx((80.1, 80.1, 99.9, 99.9), abs=1e-6)
    for o, src in zip(out, (outer, hole)):
        assert is_closed(o)
        assert (signed_area(o[:-1]) > 0) == (signed_area(src[:-1]) > 0)  # Laufrichtung bleibt
    # Mitre-Ecken: Rechteck bleibt Rechteck (5 Punkte), keine Rundung
    assert len(out[0]) == 5


def test_kerf_negative_and_island_in_hole():
    outer, hole, island = square(50, 50, 100), square(70, 70, 60), square(90, 90, 20)
    assert nesting_depth([outer, hole, island]) == [0, 1, 2]
    out, _ = offset_closed([outer, hole, island], -0.5)
    assert bbox(out[0]) == pytest.approx((50.5, 50.5, 149.5, 149.5))
    assert bbox(out[1]) == pytest.approx((69.5, 69.5, 130.5, 130.5))
    assert bbox(out[2]) == pytest.approx((90.5, 90.5, 109.5, 109.5))


def test_kerf_open_path_unchanged_and_degenerate_hole_kept():
    line = [(10, 10), (60, 10)]
    outer, tiny = square(50, 50, 100), square(90, 90, 0.4)
    out, warn = offset_closed([line, outer, tiny], 0.3)
    assert out[0] == line
    assert out[2] == tiny and warn  # zu kleines Loch: unverändert + Warnung


def test_kerf_shrink_splits_into_pieces():
    # Hantel: zwei Quadrate, schmaler Steg 0,4 mm → beim Verkleinern zwei Teile
    ring = [(10, 10), (30, 10), (30, 19.8), (40, 19.8), (40, 10), (60, 10), (60, 30), (40, 30),
            (40, 20.2), (30, 20.2), (30, 30), (10, 30), (10, 10)]
    parts = offset_ring(ring, -0.5)
    assert len(parts) == 2 and all(is_closed(p) for p in parts)


def test_kerf_curve_offset_radius():
    out, _ = offset_closed([circle(100, 100, 20)], 0.2)
    assert all(math.dist(p, (100, 100)) == pytest.approx(20.2, abs=0.05) for p in out[0])


# --- Haltestege ----------------------------------------------------------------

def test_tabs_even_and_off_corners():
    sq = square(50, 50, 40)  # Umfang 160, Ecken bei 0/40/80/120
    pieces = split_tabs(sq, 4, 2.0)
    assert len(pieces) == 5  # 4 Lücken; Start/Ende bleibt geschnitten
    cut = sum(length(p) for p in pieces)
    assert cut == pytest.approx(160 - 4 * 2.0)
    corners = corner_positions(sq)
    assert corners == pytest.approx([0, 40, 80, 120])
    # Lücken liegen mittig auf den Seiten (20, 60, 100, 140) – fern der Ecken
    gaps = [(a[-1], b[0]) for a, b in zip(pieces, pieces[1:])]
    for g0, g1 in gaps:
        assert math.dist(g0, g1) == pytest.approx(2.0)
        for c in [(50, 50), (90, 50), (90, 90), (50, 90)]:
            assert math.dist(g0, c) > 1.0 and math.dist(g1, c) > 1.0


def test_tab_shifted_away_from_corner():
    # Rechteck 30 × 10: ein Steg bei L/2 = 40 = Ecke → wird verschoben
    r = [(0 + 20, 20), (50, 20), (50, 30), (20, 30), (20, 20)]
    (a, b) = split_tabs(r, 1, 2.0)
    gap_mid = ((a[-1][0] + b[0][0]) / 2, (a[-1][1] + b[0][1]) / 2)
    assert math.dist(gap_mid, (50, 30)) >= 1.5 - 1e-6


def test_tabs_spacing_mode_and_min_length():
    sq = square(50, 50, 40)
    assert len(split_tabs(sq, 0, 2.0, spacing=50.0)) == 4  # 160 // 50 = 3 Stege
    assert split_tabs(square(50, 50, 2), 4, 1.0) == [square(50, 50, 2)]  # Umfang 8 < 10
    assert len(split_tabs(square(50, 50, 5), 20, 2.0)) == 6  # max. L / (2·Breite) = 5 Stege
    line = [(0, 0), (50, 0)]
    assert split_tabs(line, 3, 2.0) == [line]


# --- An-/Abfahrt -----------------------------------------------------------------

@pytest.mark.parametrize("arc", [False, True])
@pytest.mark.parametrize("ccw", [True, False])
def test_lead_in_on_waste_side(arc, ccw):
    outer, hole = square(100, 100, 60, ccw), square(120, 120, 20, ccw)
    lin = make_lead(outer, True, 3.0, arc, True)
    assert lin[-1] == outer[0]
    assert all(not point_in_polygon(q, outer) for q in lin[:-1])  # außen
    hin = make_lead(hole, False, 3.0, arc, True)
    assert hin[-1] == hole[0]
    assert all(point_in_polygon(q, hole) for q in hin[:-1])  # im Loch (Abfall)
    lout = make_lead(outer, True, 3.0, arc, False)
    assert lout[0] == outer[-1] and all(not point_in_polygon(q, outer) for q in lout[1:])
    # tangential (Bogen) bzw. 45° zur ersten Kante
    t = (outer[1][0] - outer[0][0], outer[1][1] - outer[0][1])
    d = (lin[-1][0] - lin[-2][0], lin[-1][1] - lin[-2][1])
    cosang = (t[0] * d[0] + t[1] * d[1]) / (math.hypot(*t) * math.hypot(*d))
    assert cosang > (0.95 if arc else 0.70)


def test_lead_clipped_to_work_area_and_small_holes():
    # Kontur an der Arbeitsflächen-Ecke: Anfahrt außen hätte keinen Platz
    from lumacut_canvas.workarea import to_machine
    x0, y0 = to_machine(0, 0)
    corner_sq = square(x0, y0, 20)
    lead = make_lead(corner_sq, True, 5.0, False, True)
    assert lead is None or all(in_work_area(q) for q in lead)
    small_hole = square(100, 100, 1.0)
    lead = make_lead(small_hole, False, 5.0, True, True)
    assert lead is None or all(point_in_polygon(q, small_hole) for q in lead[:-1])


def test_apply_cut_options_kinds_and_open_paths():
    sq = square(100, 100, 40)
    line = [(10, 10), (40, 10)]
    opts = CutOptions(tab_count=2, tab_width_mm=2, lead_in_mm=2, lead_out_mm=1)
    res = apply_cut_options([line, sq], opts)
    assert res.kinds == ["cut", "lead_in", "cut", "tab", "tab", "lead_out"]
    assert res.polylines[0] == line
    assert res.polylines[1][-1] == res.polylines[2][0]
    assert res.polylines[4][-1] == res.polylines[5][0]


# --- Planer + G-Code ---------------------------------------------------------------

def _doc_with_part(**cut):
    doc = Document()
    lid = doc.active_layer_id
    doc.update_layer(lid, **cut)
    doc.add_shape(Shape("rect", Geometry(60, 60, 80, 50), lid))
    doc.add_shape(Shape("ellipse", Geometry(80, 70, 20, 20), lid))  # Loch
    return doc


def test_planner_applies_options_and_gcode_is_pi_safe(qapp):
    doc = _doc_with_part(kerf_mm=0.1, tab_count=3, tab_width_mm=1.5, lead_in_mm=2.0,
                         lead_in_arc=True, lead_out_mm=1.0)
    (lay,) = optimize_layers(job_layers(doc))
    assert set(lay.poly_kinds) >= {"cut", "lead_in", "lead_out", "tab"}
    assert len(lay.poly_kinds) == len(lay.polylines)
    g = optimized_document_gcode(doc)
    pi_check(g)
    assert g.count("M3 I") == 1
    for line in g.splitlines():
        if line.startswith("G1"):
            assert " S" in line and " F" in line
        if line.startswith("G0"):
            assert " S" not in line
    # Loch (Ellipse) zuerst geschnitten, obwohl jetzt mit Stegen und Anfahrt
    plain = optimized_document_gcode(_doc_with_part())
    assert estimate_gcode(g).cut_length_mm < estimate_gcode(plain).cut_length_mm + 20
    # Anfahrt direkt an Kontur: weniger G0 als Polylinien
    assert g.count("G0 ") < len(lay.polylines)


def test_tabs_leave_laser_off_gaps_in_gcode(qapp):
    doc = _doc_with_part(tab_count=4, tab_width_mm=3.0)
    g = optimized_document_gcode(doc)
    plain = optimized_document_gcode(_doc_with_part())
    est, est0 = estimate_gcode(g), estimate_gcode(plain)
    # 2 Konturen × 4 Stege × 3 mm weniger Schnitt
    assert est0.cut_length_mm - est.cut_length_mm == pytest.approx(24.0, abs=0.5)
    pi_check(g)


def test_no_options_output_unchanged(qapp):
    doc = _doc_with_part()
    layers = optimize_layers(job_layers(doc))
    assert layers[0].poly_kinds == ()
    assert layers_to_gcode(layers) == optimized_document_gcode(doc)


def test_kerf_with_z_step_layer(qapp):
    doc = _doc_with_part(kerf_mm=0.1, lead_in_mm=1.0)
    doc.update_layer(doc.active_layer_id, passes=3, z_step=0.5)
    g = optimized_document_gcode(doc)
    pi_check(g)
    assert g.count("G0 Z-0.500 F600") == 2


def test_out_of_area_kerf_is_rejected(qapp):
    doc = Document()
    lid = doc.active_layer_id
    doc.update_layer(lid, kerf_mm=1.0)
    doc.add_shape(Shape("rect", Geometry(0, 0, 50, 50), lid))
    with pytest.raises(ValueError):
        optimized_document_gcode(doc)


# --- Modell / Serialisierung -------------------------------------------------------

def test_layer_cut_fields_roundtrip_and_backward_compat():
    l = Layer(name="A", kerf_mm=0.12, tab_count=3, tab_width_mm=1.5, tab_spacing_mm=0,
              lead_in_mm=2, lead_in_arc=True, lead_out_mm=1)
    d = l.to_dict()
    assert {k for k in CUT_LAYER_FIELDS if k in d} == {"kerf_mm", "tab_count", "tab_width_mm",
                                                       "lead_in_mm", "lead_in_arc", "lead_out_mm"}
    back = Layer.from_dict(json.loads(json.dumps(d)))
    assert all(getattr(back, k) == getattr(l, k) for k in CUT_LAYER_FIELDS)
    # Alte Dateien ohne Felder → Standardwerte; Standard wird nicht geschrieben
    old = Layer.from_dict({"name": "alt", "power": 20})
    assert old.kerf_mm == 0 and old.tab_count == 0 and old.lead_in_mm == 0
    assert not any(k in Layer(name="x").to_dict() for k in CUT_LAYER_FIELDS)
    # Bereiche werden begrenzt
    clamped = Layer(name="c", kerf_mm=9, tab_count=99, lead_in_mm=-3).normalized()
    assert (clamped.kerf_mm, clamped.tab_count, clamped.lead_in_mm) == (2.0, 24, 0.0)


def test_document_update_layer_normalizes_cut_fields():
    doc = Document()
    doc.update_layer(doc.active_layer_id, kerf_mm=-5, tab_width_mm=50)
    l = doc.active_layer
    assert l.kerf_mm == -2.0 and l.tab_width_mm == 10.0
    d = Document.from_dict(doc.to_dict())
    assert d.active_layer.kerf_mm == -2.0
