"""Rampe je Ebene (LightBurn *Ramp Length* / *Ramp Outer Only*): Leistung steigt am Anfang
jeder Schnittlinie stufenweise auf die Ebenen-Leistung und fällt am Ende wieder ab –
Modell, ``ramp_pieces``, ``apply_cut_options``, Planer, G-Code (Pi-Prüfung, nur G1, kein
zusätzliches G0, gleiche Brennlänge), Vorschau / Schätzung, Dialog, Hauptfenster."""

from __future__ import annotations

import json
import math

import pytest
from _pi_guard import pi_check

from lumacut_canvas.commands import AddShapesCommand
from lumacut_canvas.export import job_layers
from lumacut_canvas.model import (CUT_LAYER_DEFAULTS, CUT_LAYER_FIELDS, RAMP_RANGE, CutOrder,
                                  Document, Geometry, Layer, Shape)
from lumacut_canvas.toolpath import parse_gcode
from lumacut_job.cutpath import (KIND_CUT, KIND_LEAD_IN, KIND_LEAD_OUT, KIND_RAMP, KIND_TAB,
                                 KIND_TAB_OFF, KIND_TAB_PULSE, RAMP_MAX_STEPS, CutOptions,
                                 apply_cut_options, ramp_pieces, ramp_scale)
from lumacut_job.estimate import estimate_gcode
from lumacut_job.planner import PlanReport, optimize_layers, optimized_document_gcode


def square(x, y, s):
    return [(x, y), (x + s, y), (x + s, y + s), (x, y + s), (x, y)]


def length(p):
    return sum(math.dist(a, b) for a, b in zip(p, p[1:]))


def s_values(g: str) -> list[int]:
    return [int(ln.rsplit("S", 1)[1]) for ln in g.splitlines() if ln.startswith("G1 X")]


def no_arcs(g: str) -> bool:
    return not any(ln.split()[0] in ("G2", "G3", "G02", "G03") for ln in g.splitlines() if ln.strip())


def _doc(**cut):
    doc = Document()
    lid = doc.active_layer_id
    doc.update_layer(lid, power=80.0, **cut)
    doc.add_shape(Shape("rect", Geometry(60, 60, 80, 50), lid))
    doc.add_shape(Shape("line", Geometry(60, 150, 100, 0), lid))
    return doc


# --- Modell ------------------------------------------------------------------------------

def test_defaults_saved_only_when_set_and_round_trip():
    assert CUT_LAYER_DEFAULTS["ramp_mm"] == 0.0
    assert CUT_LAYER_DEFAULTS["ramp_start_power"] == 0.0
    assert CUT_LAYER_DEFAULTS["ramp_outer_only"] is False
    assert {"ramp_mm", "ramp_start_power", "ramp_outer_only"} <= set(CUT_LAYER_FIELDS)
    assert not any(k.startswith("ramp") for k in Layer(name="x").to_dict())
    l = Layer(name="A", ramp_mm=2.5, ramp_start_power=20.0, ramp_outer_only=True)
    d = l.to_dict()
    assert {k for k in CUT_LAYER_FIELDS if k in d} == {"ramp_mm", "ramp_start_power",
                                                       "ramp_outer_only"}
    back = Layer.from_dict(json.loads(json.dumps(d)))
    assert (back.ramp_mm, back.ramp_start_power, back.ramp_outer_only) == (2.5, 20.0, True)
    old = Layer.from_dict({"name": "alt"})
    assert (old.ramp_mm, old.ramp_start_power, old.ramp_outer_only) == (0.0, 0.0, False)


@pytest.mark.parametrize("raw, expect", [
    ({"ramp_mm": 99}, (RAMP_RANGE[1], 0.0, False)),
    ({"ramp_mm": -3, "ramp_start_power": 200}, (0.0, 95.0, False)),
    ({"ramp_mm": "x", "ramp_start_power": "y"}, (0.0, 0.0, False)),
    ({"ramp_mm": float("nan"), "ramp_start_power": float("inf")}, (0.0, 0.0, False)),
    ({"ramp_mm": None, "ramp_start_power": [1]}, (0.0, 0.0, False)),
    ({"ramp_mm": 1.23456, "ramp_outer_only": "yes"}, (1.235, 0.0, False)),
    ({"ramp_outer_only": 1}, (0.0, 0.0, False)),
    ({"ramp_outer_only": True}, (0.0, 0.0, True)),
])
def test_broken_values_and_clamping(raw, expect):
    l = Layer.from_dict({"name": "b", **raw})
    assert (l.ramp_mm, l.ramp_start_power, l.ramp_outer_only) == pytest.approx(expect)


def test_update_layer_normalizes():
    doc = Document()
    lid = doc.active_layer_id
    doc.update_layer(lid, ramp_mm=50.0, ramp_start_power=-5.0)
    lay = doc.layer(lid)
    assert (lay.ramp_mm, lay.ramp_start_power) == (20.0, 0.0)


# --- ramp_pieces -------------------------------------------------------------------------

def test_ramp_scale_linear_midpoints():
    assert [ramp_scale(k, 4, 0) for k in range(4)] == pytest.approx([0.125, 0.375, 0.625, 0.875])
    assert [ramp_scale(k, 4, 20) for k in range(4)] == pytest.approx([0.3, 0.5, 0.7, 0.9])
    assert ramp_scale(0, 1, 50) == pytest.approx(0.75)
    assert ramp_scale(0, 2, 500) == pytest.approx(1.0)   # geklemmt


def test_ramp_pieces_up_mid_down_continuous():
    line = [(0.0, 0.0), (10.0, 0.0)]
    pieces = ramp_pieces(line, 2.0, 2.0, 20.0)
    scales = [f for _, f in pieces]
    assert scales == pytest.approx([0.3, 0.5, 0.7, 0.9, 1.0, 0.9, 0.7, 0.5, 0.3])
    assert pieces[0][0][0] == line[0] and pieces[-1][0][-1] == line[-1]
    for (a, _), (b, _) in zip(pieces, pieces[1:]):
        assert a[-1] == pytest.approx(b[0])
    assert sum(length(p) for p, _ in pieces) == pytest.approx(10.0)
    assert [length(p) for p, _ in pieces[:4]] == pytest.approx([0.5] * 4)


def test_ramp_pieces_keeps_corners_and_direction():
    l_shape = [(0.0, 0.0), (1.0, 0.0), (1.0, 6.0)]
    pieces = ramp_pieces(l_shape, 2.0, 0.0, 0.0)
    pts = [q for p, _ in pieces for q in p]
    assert (1.0, 0.0) in pts
    assert pieces[-1][1] == 1.0 and pieces[-1][0][-1] == (1.0, 6.0)
    assert sum(length(p) for p, _ in pieces) == pytest.approx(7.0)


def test_ramp_pieces_short_line_shares_length():
    pieces = ramp_pieces([(0.0, 0.0), (2.0, 0.0)], 3.0, 3.0, 0.0)
    # je 1 mm Rampe (2 Stufen), kein volles Mittelstück; gleiche Stufen in der Mitte vereint
    assert [f for _, f in pieces] == pytest.approx([0.25, 0.75, 0.25])
    assert [length(p) for p, _ in pieces] == pytest.approx([0.5, 1.0, 0.5])


def test_ramp_pieces_step_limit_and_off():
    pieces = ramp_pieces([(0.0, 0.0), (100.0, 0.0)], 20.0, 0.0, 0.0)
    assert len(pieces) == RAMP_MAX_STEPS + 1
    line = [(0.0, 0.0), (5.0, 0.0)]
    assert ramp_pieces(line, 0.0, 0.0, 0.0) == [(line, 1.0)]
    assert ramp_pieces([(1.0, 1.0)], 2.0, 2.0, 0.0) == [([(1.0, 1.0)], 1.0)]
    assert ramp_pieces([(1.0, 1.0), (1.0, 1.0)], 2.0, 2.0, 0.0)[0][1] == 1.0


# --- apply_cut_options -------------------------------------------------------------------

def test_options_flags():
    assert not CutOptions().ramped and not CutOptions().active
    assert CutOptions(ramp_mm=1.0).ramped and CutOptions(ramp_mm=1.0).active
    assert not CutOptions(ramp_start_power=50.0, ramp_outer_only=True).active
    o = CutOptions(ramp_mm=1.0, perf_cut_mm=2.0, perf_skip_mm=1.0)
    assert not o.ramped and o.active
    assert not CutOptions(ramp_mm=1.0).shapes_contours   # Überlappungen dürfen weg


def test_closed_contour_ramps_up_and_down():
    sq = square(100, 100, 40)
    res = apply_cut_options([sq], CutOptions(ramp_mm=2.0), [0])
    assert res.kinds[0] == KIND_CUT and set(res.kinds[1:]) == {KIND_RAMP}
    assert len(res.power_scale) == len(res.polylines) and res.ramps == 1
    assert res.power_scale[:4] == pytest.approx([0.125, 0.375, 0.625, 0.875])
    assert res.power_scale[4] == 1.0
    assert res.power_scale[-4:] == pytest.approx([0.875, 0.625, 0.375, 0.125])
    assert res.polylines[0][0] == sq[0] and res.polylines[-1][-1] == sq[-1]
    assert sum(length(p) for p in res.polylines) == pytest.approx(160.0)
    for a, b in zip(res.polylines, res.polylines[1:]):
        assert a[-1] == pytest.approx(b[0])


def test_open_path_and_outer_only():
    line = [(10.0, 10.0), (30.0, 10.0)]
    outer, hole = square(100, 100, 40), square(110, 110, 10)
    res = apply_cut_options([line, hole, outer], CutOptions(ramp_mm=1.0, ramp_outer_only=True))
    assert res.ramps == 2    # Linie + Außenkontur, Loch ohne Rampe
    starts = [i for i, k in enumerate(res.kinds) if k != KIND_RAMP]
    assert len(starts) == 3
    hole_i = starts[1]
    assert res.polylines[hole_i] == hole and res.power_scale[hole_i] == 1.0
    res2 = apply_cut_options([line, hole, outer], CutOptions(ramp_mm=1.0))
    assert res2.ramps == 3


def test_no_ramp_leaves_result_unchanged():
    sq = square(100, 100, 40)
    a = apply_cut_options([sq], CutOptions(lead_in_mm=2.0, overcut_mm=1.0), [0])
    b = apply_cut_options([sq], CutOptions(lead_in_mm=2.0, overcut_mm=1.0,
                                           ramp_start_power=40.0, ramp_outer_only=True), [0])
    assert a.polylines == b.polylines and a.kinds == b.kinds
    assert a.power_scale == [] and b.power_scale == []


def test_leads_full_power_ramp_after_overcut():
    sq = square(100, 100, 40)
    opts = CutOptions(ramp_mm=2.0, lead_in_mm=3.0, lead_out_mm=3.0, overcut_mm=1.5)
    plain = apply_cut_options([sq], CutOptions(lead_in_mm=3.0, lead_out_mm=3.0, overcut_mm=1.5), [0])
    res = apply_cut_options([sq], opts, [0])
    assert res.kinds[0] == KIND_LEAD_IN and res.power_scale[0] == 1.0
    assert res.kinds[-1] == KIND_LEAD_OUT and res.power_scale[-1] == 1.0
    assert res.kinds[1] == KIND_CUT and res.power_scale[1] < 0.2
    assert res.power_scale[-2] < 0.2         # Ende des Überschnitts mit wenig Leistung
    assert res.polylines[-2][-1] == pytest.approx(plain.polylines[-2][-1])
    cut_len = sum(length(p) for p, k in zip(res.polylines, res.kinds) if k in (KIND_CUT, KIND_RAMP))
    assert cut_len == pytest.approx(160.0 + 1.5)
    assert res.polylines[0] == plain.polylines[0] and res.polylines[-1] == plain.polylines[-1]


def test_tabs_ramp_first_and_last_piece_pulses_untouched():
    sq = square(100, 100, 40)
    res = apply_cut_options([sq], CutOptions(ramp_mm=1.0, tab_count=2, tab_width_mm=1.0,
                                             tab_cut_power=50.0), [0])
    plain = apply_cut_options([sq], CutOptions(tab_count=2, tab_width_mm=1.0,
                                               tab_cut_power=50.0), [0])
    assert res.ramps == 1
    for q, k, f in zip(res.polylines, res.kinds, res.power_scale):
        if k in (KIND_TAB_PULSE, KIND_TAB_OFF):
            assert f == 1.0
    ramped = [k for k, f in zip(res.kinds, res.power_scale) if f < 1.0]
    assert ramped[0] == KIND_CUT and set(ramped[1:]) <= {KIND_RAMP}
    assert res.polylines[0][0] == sq[0]
    assert [p for p, k in zip(res.polylines, res.kinds) if k in (KIND_TAB_PULSE, KIND_TAB_OFF)] == \
        [p for p, k in zip(plain.polylines, plain.kinds) if k in (KIND_TAB_PULSE, KIND_TAB_OFF)]
    # das letzte Schnittstück (nach einem Steg) fällt ab
    last_tab = max(i for i, k in enumerate(res.kinds) if k == KIND_TAB)
    assert res.power_scale[last_tab] == 1.0 and res.power_scale[-1] < 0.5


def test_perforated_layer_without_ramp():
    res = apply_cut_options([[(0.0, 0.0), (20.0, 0.0)]],
                            CutOptions(ramp_mm=2.0, perf_cut_mm=2.0, perf_skip_mm=1.0))
    assert res.power_scale == [] and KIND_RAMP not in res.kinds


# --- Planer / G-Code ---------------------------------------------------------------------

def test_planner_carries_power_scale_and_report():
    rep = PlanReport()
    (lay,) = optimize_layers(job_layers(_doc(ramp_mm=2.0)), report=rep)
    assert len(lay.poly_power_scale) == len(lay.polylines) == len(lay.poly_kinds)
    assert rep.ramps == 2
    (plain,) = optimize_layers(job_layers(_doc()))
    assert plain.poly_power_scale == ()


def test_gcode_byte_identical_without_ramp():
    plain = optimized_document_gcode(_doc(), scan_offsets=None)
    same = optimized_document_gcode(_doc(ramp_start_power=30.0, ramp_outer_only=True),
                                    scan_offsets=None)
    assert plain == same


@pytest.mark.parametrize("order", [CutOrder(), CutOrder(enabled=False), CutOrder(corners=True),
                                   CutOrder(direction="top_bottom")])
def test_gcode_ramped_pi_safe_same_burn_no_extra_travel(order):
    plain_doc, doc = _doc(), _doc(ramp_mm=2.0, ramp_start_power=20.0)
    plain_doc.set_cut_order(order)
    doc.set_cut_order(order)
    plain = optimized_document_gcode(plain_doc, scan_offsets=None)
    g = optimized_document_gcode(doc, scan_offsets=None)
    pi_check(g)
    assert no_arcs(g) and g.count("M3 I") == 1
    assert g.count("G0 ") == plain.count("G0 ")
    assert parse_gcode(g).cut_length_mm == pytest.approx(parse_gcode(plain).cut_length_mm)
    s_full = round(0.8 * 255)
    vals = s_values(g)
    assert max(vals) == s_full and set(s_values(plain)) == {s_full}
    assert vals[:4] == [round(s_full * f) for f in (0.3, 0.5, 0.7, 0.9)]
    assert vals[-4:] == [round(s_full * f) for f in (0.9, 0.7, 0.5, 0.3)]
    assert len(vals) <= len(s_values(plain)) + 2 * 2 * 8   # 2 Linien × 2 Rampen × ≤ 8 Stufen
    assert len(parse_gcode(g).runs) == len(parse_gcode(plain).runs)


def test_gcode_ramp_every_pass_and_full_power_fill():
    doc = _doc(ramp_mm=1.0)
    lid = doc.active_layer_id
    doc.update_layer(lid, passes=2, fill_mode="hatch", line_interval_mm=2.0)
    g = optimized_document_gcode(doc, scan_offsets=None)
    pi_check(g)
    p1, p2 = g.split("; PASS 2 OF 2")
    p1 = p1.split("; PASS 1 OF 2")[1]
    assert s_values(p1) == s_values(p2)
    s_full = round(0.8 * 255)
    assert sum(1 for v in s_values(p1) if v < s_full) == 2 * 2 * 2   # nur Rampen-Stufen
    plain_doc = _doc()
    plain_doc.update_layer(plain_doc.active_layer_id, passes=2, fill_mode="hatch",
                           line_interval_mm=2.0)
    plain = optimized_document_gcode(plain_doc, scan_offsets=None)
    assert parse_gcode(g).cut_length_mm == pytest.approx(parse_gcode(plain).cut_length_mm)


def test_gcode_ramp_with_kerf_leads_overcut_and_tabs():
    cut = dict(kerf_mm=0.1, lead_in_mm=2.0, lead_out_mm=2.0, overcut_mm=1.0, tab_count=2,
               tab_width_mm=1.0)
    plain = optimized_document_gcode(_doc(**cut), scan_offsets=None)
    g = optimized_document_gcode(_doc(ramp_mm=1.5, **cut), scan_offsets=None)
    pi_check(g)
    assert no_arcs(g)
    assert g.count("G0 ") == plain.count("G0 ")
    assert parse_gcode(g).cut_length_mm == pytest.approx(parse_gcode(plain).cut_length_mm)


def test_outer_only_hole_full_power():
    doc = Document()
    lid = doc.active_layer_id
    doc.update_layer(lid, power=100.0, ramp_mm=1.0, ramp_outer_only=True)
    doc.add_shape(Shape("rect", Geometry(60, 60, 80, 50), lid))
    doc.add_shape(Shape("rect", Geometry(90, 75, 10, 10), lid))
    (lay,) = optimize_layers(job_layers(doc))
    first = [i for i, k in enumerate(lay.poly_kinds) if k != KIND_RAMP]
    assert len(first) == 2
    hole, outer = first   # innen zuerst
    assert lay.poly_power_scale[hole] == 1.0 and lay.poly_power_scale[outer] < 1.0
    g = optimized_document_gcode(doc, scan_offsets=None)
    pi_check(g)


def test_ramp_with_zero_power_steps_gets_no_extra_g0():
    doc = _doc(ramp_mm=2.0)
    doc.update_layer(doc.active_layer_id, power=1.0)   # S 3 → erste Stufe S0
    g = optimized_document_gcode(doc, scan_offsets=None)
    pi_check(g)
    assert 0 in s_values(g)
    plain = _doc()
    plain.update_layer(plain.active_layer_id, power=1.0)
    assert g.count("G0 ") == optimized_document_gcode(plain, scan_offsets=None).count("G0 ")


def test_estimate_and_path_preview():
    g = optimized_document_gcode(_doc(ramp_mm=3.0), scan_offsets=None)
    plain = optimized_document_gcode(_doc(), scan_offsets=None)
    est, est0 = estimate_gcode(g), estimate_gcode(plain)
    assert est.cut_length_mm == pytest.approx(est0.cut_length_mm)
    assert est.cut_time_s == pytest.approx(est0.cut_time_s, rel=0.05)
    tp = parse_gcode(g)
    assert len({m.power for m in tp.moves if m.kind == "CUT" or m.power > 0}) > 2


def test_overlap_removal_still_works_with_ramp():
    doc = Document()
    lid = doc.active_layer_id
    doc.update_layer(lid, overlap_tol_mm=0.05, ramp_mm=1.0)
    doc.add_shape(Shape("rect", Geometry(40, 40, 30, 20), lid))
    doc.add_shape(Shape("rect", Geometry(70, 40, 30, 20), lid))
    g = optimized_document_gcode(doc, scan_offsets=None)
    pi_check(g)
    assert parse_gcode(g).cut_length_mm == pytest.approx(180.0, abs=0.01)


# --- Dialog / Bedienung ------------------------------------------------------------------

def test_dialog_fields_enable_hint_values(qapp):
    from PySide6.QtWidgets import QDialogButtonBox
    from lumacut_job.cut_qt import CutOptionsDialog
    dlg = CutOptionsDialog(Layer(name="Schneiden"))
    assert dlg.values() == CUT_LAYER_DEFAULTS
    assert dlg.ramp.text() == "aus"
    assert not dlg.ramp_start.isEnabled() and not dlg.ramp_outer.isEnabled()
    assert dlg.ramp_hint.isHidden()
    dlg.ramp.setValue(2.0)
    assert dlg.ramp_start.isEnabled() and dlg.ramp_outer.isEnabled()
    assert "4 Stufen von 0 % bis 100 %" in dlg.ramp_hint.text()
    dlg.ramp_start.setValue(25)
    assert "von 25 %" in dlg.ramp_hint.text()
    dlg.ramp_outer.setChecked(True)
    v = dlg.values()
    assert (v["ramp_mm"], v["ramp_start_power"], v["ramp_outer_only"]) == (2.0, 25.0, True)
    dlg.perf_cut.setValue(2.0)
    assert "Perforation" in dlg.ramp_hint.text()
    dlg.findChild(QDialogButtonBox).button(QDialogButtonBox.RestoreDefaults).click()
    assert dlg.values() == CUT_LAYER_DEFAULTS
    dlg2 = CutOptionsDialog(Layer(name="x", ramp_mm=1.5, ramp_start_power=10, ramp_outer_only=True))
    assert (dlg2.ramp.value(), dlg2.ramp_start.value(), dlg2.ramp_outer.isChecked()) == \
        (1.5, 10.0, True)


def test_summary_and_hint():
    from lumacut_job.cut_qt import ramp_hint, summary
    assert summary(Layer(name="x", ramp_mm=2.0)) == "Rampe 2 mm"
    assert summary(Layer(name="x", ramp_mm=2.0, ramp_start_power=20, ramp_outer_only=True)) == \
        "Rampe 2 mm ab 20 % nur außen"
    assert summary(Layer(name="x", ramp_start_power=20, ramp_outer_only=True)) == ""
    assert summary(Layer(name="x", overcut_mm=1.0, ramp_mm=1.0)) == "Überschnitt 1 mm, Rampe 1 mm"
    assert ramp_hint(0.0, 20) == ""
    assert ramp_hint(0.5, 0).startswith("1 Stufe von")
    assert "20 Stufen" in ramp_hint(20.0, 0)


def test_apply_one_undo_step(qapp):
    from lumacut_canvas.editor import CanvasEditor
    from lumacut_job.cut_qt import apply_cut_options as apply_dialog
    ed = CanvasEditor()
    lid = ed.document.active_layer_id
    n = ed.undo_stack.count()
    assert apply_dialog(ed, lid, dict(CUT_LAYER_DEFAULTS, ramp_mm=2.0, ramp_start_power=10.0,
                                      ramp_outer_only=True))
    assert ed.undo_stack.count() == n + 1
    lay = ed.document.layer(lid)
    assert (lay.ramp_mm, lay.ramp_start_power, lay.ramp_outer_only) == (2.0, 10.0, True)
    assert not apply_dialog(ed, lid, dict(CUT_LAYER_DEFAULTS, ramp_mm=2.0, ramp_start_power=10.0,
                                          ramp_outer_only=True))
    ed.undo_stack.undo()
    assert ed.document.layer(lid).ramp_mm == 0.0


def test_document_save_load(tmp_path):
    from lumacut_canvas.document_io import load_document, save_document
    doc = _doc(ramp_mm=1.5, ramp_start_power=15.0)
    path = save_document(doc, tmp_path / "rampe.lcs")
    back = load_document(path)
    lay = back.layer(back.active_layer_id)
    assert (lay.ramp_mm, lay.ramp_start_power) == (1.5, 15.0)
    assert optimized_document_gcode(back, scan_offsets=None) == \
        optimized_document_gcode(doc, scan_offsets=None)


def test_main_window_cut_options_and_send(qapp):
    from main import LumaCutStudio
    win = LumaCutStudio()
    try:
        ed = win.canvas
        doc = ed.document
        lid = doc.active_layer.id
        ed.undo_stack.push(AddShapesCommand(doc, [Shape("rect", Geometry(40, 40, 30, 20), lid)],
                                            "Rechteck"))
        tools = win.job_tools
        assert tools.cut_options(dict(CUT_LAYER_DEFAULTS, ramp_mm=1.0))
        assert "Rampe 1 mm" in win.statusBar().currentMessage()
        g, _note = tools.job_gcode(ask_inputs=False)
        pi_check(g)
        assert len(set(s_values(g))) > 1
    finally:
        win.canvas.undo_stack.setClean()
        win.close()
        win.deleteLater()
        qapp.processEvents()
