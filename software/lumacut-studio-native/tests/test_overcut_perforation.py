"""Überschnitt (Overcut) und Perforation je Ebene (lumacut_job.cutpath + Planer + Dialog)."""
import json
import math

import pytest

from _pi_guard import pi_check
from lumacut_canvas.export import job_layers
from lumacut_canvas.model import CUT_LAYER_DEFAULTS, CUT_LAYER_FIELDS, Document, Geometry, Layer, Shape
from lumacut_job.cutpath import (KIND_CUT, KIND_LEAD_IN, KIND_LEAD_OUT, KIND_PERF, KIND_TAB,
                                 CutOptions, apply_cut_options, overcut_path, perforate,
                                 point_in_polygon, rotate_start, split_tabs)
from lumacut_job.estimate import estimate_gcode
from lumacut_job.planner import optimize_layers, optimized_document_gcode


def square(x, y, s):
    return [(x, y), (x + s, y), (x + s, y + s), (x, y + s), (x, y)]


def length(p):
    return sum(math.dist(a, b) for a, b in zip(p, p[1:]))


def close(a, b, tol=1e-6):
    return math.dist(a, b) < tol


# --- perforate ---------------------------------------------------------------------

def test_perforate_straight_line_pattern():
    pieces = perforate([(0, 0), (10, 0)], 2.0, 1.0)
    assert [p[0][0] for p in pieces] == pytest.approx([0, 3, 6, 9])
    assert [length(p) for p in pieces] == pytest.approx([2, 2, 2, 1])


def test_perforate_follows_corners_and_keeps_vertices():
    l_shape = [(0, 0), (5, 0), (5, 5)]
    pieces = perforate(l_shape, 4.0, 2.0)
    assert len(pieces) == 2
    assert pieces[0] == [(0, 0), (4.0, 0.0)]
    assert pieces[1][0] == pytest.approx((5.0, 1.0))
    assert length(pieces[1]) == pytest.approx(4.0)
    # über eine Ecke laufendes Stück behält den Eckpunkt
    pieces = perforate(l_shape, 6.0, 1.0)
    assert (5, 0) in pieces[0] and length(pieces[0]) == pytest.approx(6.0)


def test_perforate_off_short_and_tiny_rest():
    line = [(0, 0), (10, 0)]
    assert perforate(line, 0.0, 1.0) == [line]
    assert perforate(line, 2.0, 0.0) == [line]
    assert perforate(line, 12.0, 1.0) == [line]
    # Rest von 0,005 mm nach der letzten Lücke fällt weg
    pieces = perforate([(0, 0), (6.005, 0)], 2.0, 2.0)
    assert len(pieces) == 2 and all(length(p) == pytest.approx(2.0) for p in pieces)


def test_dot_line_with_short_cuts():
    pieces = perforate([(0, 0), (20, 0)], 0.2, 0.8)
    assert len(pieces) == 20
    assert sum(length(p) for p in pieces) == pytest.approx(4.0)


# --- overcut -----------------------------------------------------------------------

def test_overcut_path_and_rotate_start():
    sq = square(100, 100, 40)
    ext = overcut_path(sq, 5.0)
    assert ext[0] == sq[0] and ext[-1] == pytest.approx((105.0, 100.0))
    assert length(overcut_path(sq, 999)) == pytest.approx(160.0)
    assert overcut_path([(0, 0), (5, 0)], 3.0) == []
    assert overcut_path(sq, 0.0) == []
    rot = rotate_start(sq, 50.0)
    assert rot[0] == pytest.approx((140.0, 110.0)) and rot[-1] == rot[0]
    assert length(rot) == pytest.approx(160.0)


def test_overcut_extends_closed_contours_only():
    sq = square(100, 100, 40)
    line = [(10, 10), (40, 10)]
    res = apply_cut_options([line, sq], CutOptions(overcut_mm=3.0))
    assert res.kinds == [KIND_CUT, KIND_CUT]
    assert res.polylines[0] == line
    cut = res.polylines[1]
    assert cut[0] == sq[0] and length(cut) == pytest.approx(163.0)
    assert cut[-1] == pytest.approx((103.0, 100.0))


def test_overcut_stops_before_first_tab():
    sq = square(100, 100, 40)
    opts = CutOptions(overcut_mm=50.0, tab_count=4, tab_width_mm=2.0)
    res = apply_cut_options([sq], opts)
    pieces = split_tabs(sq, 4, 2.0)
    first = length(pieces[0])
    last = res.polylines[-1]
    assert length(last) == pytest.approx(length(pieces[-1]) + first - 0.5)
    # Gesamtschnitt = Umfang − Stege + Überschnitt (Steg bleibt stehen)
    total = sum(length(p) for p in res.polylines)
    assert total == pytest.approx(160 - 8 + first - 0.5)


def test_overcut_with_lead_out_starts_at_overcut_end():
    sq = square(100, 100, 40)
    res = apply_cut_options([sq], CutOptions(overcut_mm=2.0, lead_in_mm=2.0, lead_out_mm=2.0))
    assert res.kinds == [KIND_LEAD_IN, KIND_CUT, KIND_LEAD_OUT]
    lin, cut, lout = res.polylines
    assert close(lin[-1], cut[0]) and close(cut[-1], lout[0])
    assert length(cut) == pytest.approx(162.0)
    assert all(not point_in_polygon(q, sq) for q in lout[1:])  # Abfallseite (außen)


# --- Perforation in der Ebene ------------------------------------------------------

def test_perforation_kinds_open_paths_and_leads():
    sq = square(100, 100, 40)
    line = [(10, 10), (40, 10)]
    opts = CutOptions(perf_cut_mm=3.0, perf_skip_mm=1.0, lead_in_mm=2.0)
    res = apply_cut_options([line, sq], opts)
    kinds = res.kinds
    assert kinds[0] == KIND_CUT and kinds[1] == KIND_PERF       # Linie perforiert
    i = kinds.index(KIND_LEAD_IN)
    assert kinds[i + 1] == KIND_CUT and set(kinds[i + 2:]) == {KIND_PERF}
    assert close(res.polylines[i][-1], res.polylines[i + 1][0])  # Anfahrt schließt an
    assert length(res.polylines[i]) == pytest.approx(2.0, abs=1e-6)  # Anfahrt durchgehend
    cut = sum(length(p) for p, k in zip(res.polylines, kinds) if k != KIND_LEAD_IN)
    assert cut == pytest.approx(3 * 8 - 1 + 3 * 40, abs=1e-6)  # 30 mm Linie: 8 Stücke, letztes 2 mm


def test_perforation_on_tab_pieces_and_overcut():
    sq = square(100, 100, 40)
    res = apply_cut_options([sq], CutOptions(perf_cut_mm=2.0, perf_skip_mm=2.0, overcut_mm=4.0,
                                             tab_count=2, tab_width_mm=2.0))
    assert KIND_TAB in res.kinds and KIND_PERF in res.kinds
    assert all(length(p) <= 2.0 + 1e-6 for p in res.polylines)


def test_options_active_flags():
    assert not CutOptions().active
    assert CutOptions(overcut_mm=1).active
    assert CutOptions(perf_cut_mm=1).active and CutOptions(perf_cut_mm=1).perforated
    assert not CutOptions(perf_cut_mm=1, perf_skip_mm=0).perforated
    assert not CutOptions(perf_cut_mm=1, perf_skip_mm=0).active


# --- Planer + G-Code ---------------------------------------------------------------

def _doc(**cut):
    doc = Document()
    lid = doc.active_layer_id
    doc.update_layer(lid, **cut)
    doc.add_shape(Shape("rect", Geometry(60, 60, 80, 50), lid))
    doc.add_shape(Shape("line", Geometry(60, 150, 100, 0), lid))
    return doc


def test_perforated_gcode_is_pi_safe_and_cuts_less(qapp):
    plain = optimized_document_gcode(_doc())
    g = optimized_document_gcode(_doc(perf_cut_mm=3.0, perf_skip_mm=2.0))
    pi_check(g)
    assert g.count("M3 I") == 1
    e0, e = estimate_gcode(plain), estimate_gcode(g)
    assert e.cut_length_mm == pytest.approx(e0.cut_length_mm * 3 / 5, rel=0.03)
    assert g.count("G0 ") > plain.count("G0 ") + 50
    for line in g.splitlines():
        if line.startswith("G0"):
            assert " S" not in line


def test_overcut_gcode_adds_length(qapp):
    plain = optimized_document_gcode(_doc())
    g = optimized_document_gcode(_doc(overcut_mm=1.5))
    pi_check(g)
    assert estimate_gcode(g).cut_length_mm - estimate_gcode(plain).cut_length_mm == \
        pytest.approx(1.5, abs=0.01)
    assert g.count("G0 ") == plain.count("G0 ")


def test_dot_mode_with_passes(qapp):
    doc = _doc(perf_cut_mm=0.2, perf_skip_mm=0.8)
    doc.update_layer(doc.active_layer_id, passes=2)
    (lay,) = optimize_layers(job_layers(doc))
    assert len(lay.poly_kinds) == len(lay.polylines) and KIND_PERF in lay.poly_kinds
    g = optimized_document_gcode(doc)
    pi_check(g)
    first, second = g.split("; PASS 2 OF 2")
    assert first.split("; PASS 1 OF 2")[1].count("G1 ") == second.count("G1 ")


# --- Modell / Dialog ---------------------------------------------------------------

def test_layer_fields_roundtrip_defaults_and_clamp():
    l = Layer(name="A", overcut_mm=1.25, perf_cut_mm=3.0, perf_skip_mm=0.5)
    d = l.to_dict()
    assert {k for k in CUT_LAYER_FIELDS if k in d} == {"overcut_mm", "perf_cut_mm", "perf_skip_mm"}
    back = Layer.from_dict(json.loads(json.dumps(d)))
    assert (back.overcut_mm, back.perf_cut_mm, back.perf_skip_mm) == (1.25, 3.0, 0.5)
    old = Layer.from_dict({"name": "alt"})
    assert (old.overcut_mm, old.perf_cut_mm, old.perf_skip_mm) == (0.0, 0.0, 1.0)
    assert not any(k in Layer(name="x").to_dict() for k in CUT_LAYER_FIELDS)
    c = Layer(name="c", overcut_mm=99, perf_cut_mm=-1, perf_skip_mm=999).normalized()
    assert (c.overcut_mm, c.perf_cut_mm, c.perf_skip_mm) == (10.0, 0.0, 50.0)


def test_dialog_and_summary(qapp):
    from PySide6.QtWidgets import QDialogButtonBox
    from lumacut_job.cut_qt import CutOptionsDialog, summary
    layer = Layer(name="Schneiden")
    dlg = CutOptionsDialog(layer)
    assert dlg.values() == CUT_LAYER_DEFAULTS
    assert dlg.overcut.text() == "aus" and dlg.perf_cut.text() == "aus"
    assert not dlg.perf_skip.isEnabled()
    dlg.overcut.setValue(0.8)
    dlg.perf_cut.setValue(2.5)
    assert dlg.perf_skip.isEnabled()
    dlg.perf_skip.setValue(1.5)
    v = dlg.values()
    assert (v["overcut_mm"], v["perf_cut_mm"], v["perf_skip_mm"]) == pytest.approx((0.8, 2.5, 1.5))
    dlg.findChild(QDialogButtonBox).button(QDialogButtonBox.RestoreDefaults).click()
    assert dlg.values() == CUT_LAYER_DEFAULTS
    s = summary(Layer(name="x", overcut_mm=0.8, perf_cut_mm=2.5, perf_skip_mm=1.5))
    assert s == "Überschnitt 0.8 mm, Perforation 2.5/1.5 mm"
    assert summary(Layer(name="x", perf_skip_mm=2.0)) == ""
