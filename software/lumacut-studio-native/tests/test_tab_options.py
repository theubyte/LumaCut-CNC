"""Haltestege wie LightBurn: „Innere Formen ohne Stege“ (Skip Inner Shapes),
„Höchstens Stege je Kontur“ (Limit Max Tabs) und „Steg-Leistung“ (Tab Cut Power,
gepulste Schnitte quer über den Steg) – Engine, Planer, G-Code, Vorschau, Dialog."""

from __future__ import annotations

import json
import math
import re

import pytest
from _pi_guard import pi_check

from lumacut_canvas.commands import AddShapesCommand
from lumacut_canvas.export import JobLayer, job_layers
from lumacut_canvas.gcode import layers_to_gcode
from lumacut_canvas.model import (CUT_LAYER_DEFAULTS, CUT_LAYER_FIELDS, Document, Geometry, Layer,
                                  Shape)
from lumacut_canvas.toolpath import CUT, parse_gcode
from lumacut_job.cutpath import (KIND_CUT, KIND_LEAD_IN, KIND_LEAD_OUT, KIND_PERF, KIND_TAB,
                                 KIND_TAB_OFF, KIND_TAB_PULSE, MIN_TAB_PULSE_MM,
                                 TAB_PULSE_PERIOD_MM, CutOptions, apply_cut_options, split_tabs,
                                 split_tabs_with_gaps, tab_intervals, tab_pulses)
from lumacut_job.estimate import estimate_gcode
from lumacut_job.planner import optimize_layers, optimized_document_gcode


def square(x, y, s, ccw=True):
    sq = [(x, y), (x + s, y), (x + s, y + s), (x, y + s), (x, y)]
    return sq if ccw else list(reversed(sq))


def length(p):
    return sum(math.dist(a, b) for a, b in zip(p, p[1:]))


def close(a, b, tol=1e-6):
    return math.dist(a, b) < tol


def burned_mm(gcode: str) -> float:
    return parse_gcode(gcode).cut_length_mm


# --- Höchstens Stege je Kontur (Limit Max Tabs) ------------------------------------

def test_tab_max_limits_spacing_mode():
    sq = square(0, 0, 100)                       # Umfang 400 mm
    assert len(tab_intervals(sq, 0, 1.0, 20.0)) == 20
    assert len(tab_intervals(sq, 0, 1.0, 20.0, max_count=3)) == 3
    assert len(split_tabs(sq, 0, 1.0, 20.0, max_count=3)) == 4
    # gleichmäßig verteilt (Abstand ≈ Umfang / 3), nicht in Ecken
    mids = [(a + b) / 2 for a, b in tab_intervals(sq, 0, 1.0, 20.0, max_count=3)]
    gaps = [b - a for a, b in zip(mids, mids[1:])]
    assert all(abs(g - 400 / 3) < 400 / 12 + 1e-6 for g in gaps)
    assert all(min(abs(m - c) for c in (0, 100, 200, 300, 400)) >= 1.0 for m in mids)
    # Grenze größer als die Abstands-Anzahl ändert nichts; 0 = unbegrenzt
    assert tab_intervals(sq, 0, 1.0, 20.0, max_count=50) == tab_intervals(sq, 0, 1.0, 20.0)
    assert tab_intervals(sq, 0, 1.0, 20.0, max_count=0) == tab_intervals(sq, 0, 1.0, 20.0)


def test_tab_max_ignored_with_fixed_count_and_split_tabs_unchanged():
    sq = square(10, 10, 50)
    assert len(tab_intervals(sq, 6, 1.0, 0.0, max_count=2)) == 6
    # split_tabs (alte Signatur) unverändert: gleiche Stücke wie die Schnittstücke mit Lücken
    pieces = split_tabs(sq, 4, 2.0)
    with_gaps = split_tabs_with_gaps(sq, 4, 2.0)
    assert pieces == [p for p, gap in with_gaps if not gap]
    assert [gap for _p, gap in with_gaps] == [False, True, False, True, False, True, False,
                                              True, False]
    # Stücke und Stege schließen lückenlos aneinander und ergeben den ganzen Umfang
    for (a, _), (b, _) in zip(with_gaps, with_gaps[1:]):
        assert close(a[-1], b[0])
    assert sum(length(p) for p, _ in with_gaps) == pytest.approx(200.0)
    assert sum(length(p) for p, gap in with_gaps if gap) == pytest.approx(8.0)
    # zu kurze Kontur / keine Breite → keine Stege
    assert tab_intervals(square(0, 0, 2), 4, 1.0) == []
    assert split_tabs_with_gaps(sq, 4, 0.0) == [(sq, False)]


def test_tab_max_in_planner_options():
    opts = CutOptions(tab_spacing_mm=10.0, tab_width_mm=1.0, tab_max=2)
    res = apply_cut_options([square(20, 20, 80)], opts)
    assert res.kinds.count(KIND_TAB) == 2
    res = apply_cut_options([square(20, 20, 80)], CutOptions(tab_spacing_mm=10.0, tab_width_mm=1.0))
    assert res.kinds.count(KIND_TAB) == 32


# --- Innere Formen ohne Stege (Skip Inner Shapes) ---------------------------------

def _nested():
    frame = square(0, 0, 200)          # Rahmen (Tiefe 0)
    part = square(20, 20, 100)         # Teil im Rahmen (Tiefe 1)
    hole = square(40, 40, 40)          # Loch im Teil (Tiefe 2)
    island = square(50, 50, 20)        # Insel im Loch (Tiefe 3)
    single = square(250, 20, 60)       # freies Teil (Tiefe 0)
    return [island, hole, part, frame, single]


def test_skip_inner_only_outermost_contours_get_tabs():
    polys = _nested()
    on = apply_cut_options(polys, CutOptions(tab_count=4, tab_width_mm=1.0))
    assert on.kinds.count(KIND_TAB) == 5 * 4
    skip = apply_cut_options(polys, CutOptions(tab_count=4, tab_width_mm=1.0, tab_skip_inner=True))
    # nur Rahmen und freies Teil (Tiefe 0) behalten ihre 4 Stege – wie LightBurn
    assert skip.kinds.count(KIND_TAB) == 2 * 4
    assert skip.kinds.count(KIND_CUT) == 5
    # ungestegte Konturen bleiben ganz (ein geschlossener Lauf, gleicher Umfang)
    whole = [p for p, k in zip(skip.polylines, skip.kinds) if k == KIND_CUT and close(p[0], p[-1])]
    assert sorted(round(length(p)) for p in whole) == [80, 160, 400]


def test_skip_inner_uses_layer_depth_and_keeps_leads_and_kerf():
    polys = [square(140, 100, 20), square(120, 80, 80)]
    opts = CutOptions(tab_count=3, tab_width_mm=1.0, tab_skip_inner=True, lead_in_mm=2.0,
                      lead_out_mm=1.0)
    res = apply_cut_options(polys, opts)
    assert res.kinds.count(KIND_LEAD_IN) == 2 and res.kinds.count(KIND_LEAD_OUT) == 2
    assert res.kinds.count(KIND_TAB) == 3
    # das Loch kommt zuerst und ist ohne Stege
    assert res.kinds[:3] == [KIND_LEAD_IN, KIND_CUT, KIND_LEAD_OUT]


def test_skip_inner_off_without_tabs_and_open_paths_untouched():
    line = [(0, 0), (50, 0)]
    res = apply_cut_options([line, square(10, 10, 30)],
                            CutOptions(tab_count=0, tab_skip_inner=True, tab_cut_power=50))
    assert res.kinds == [KIND_CUT, KIND_CUT] and res.polylines[0] == line


# --- Steg-Leistung (Tab Cut Power) --------------------------------------------------

def test_tab_pulses_pattern_and_coverage():
    gap = [(0.0, 0.0), (2.0, 0.0)]
    parts = tab_pulses(gap, 25)
    kinds = [k for _p, k in parts]
    assert kinds[0] == KIND_TAB_OFF and kinds[-1] == KIND_TAB_OFF   # Steg-Enden bleiben aus
    assert kinds.count(KIND_TAB_PULSE) == round(2.0 / TAB_PULSE_PERIOD_MM)
    assert all(a != b for a, b in zip(kinds, kinds[1:]))           # an / aus abwechselnd
    for (a, _), (b, _) in zip(parts, parts[1:]):
        assert close(a[-1], b[0])                                    # lückenlos
    assert close(parts[0][0][0], gap[0]) and close(parts[-1][0][-1], gap[-1])
    on = sum(length(p) for p, k in parts if k == KIND_TAB_PULSE)
    assert on == pytest.approx(0.5)                                  # 25 % von 2 mm
    assert sum(length(p) for p, _ in parts) == pytest.approx(2.0)
    # Pulse gleichmäßig: gleiche Länge
    lens = {round(length(p), 9) for p, k in parts if k == KIND_TAB_PULSE}
    assert len(lens) == 1


@pytest.mark.parametrize("power", [5, 25, 50, 75, 95])
def test_tab_pulses_on_share_follows_power(power):
    gap = [(0.0, 0.0), (3.0, 0.0)]
    on = sum(length(p) for p, k in tab_pulses(gap, power) if k == KIND_TAB_PULSE)
    assert on == pytest.approx(3.0 * power / 100)


def test_tab_pulses_off_tiny_and_corner():
    gap = [(0.0, 0.0), (1.0, 0.0)]
    assert tab_pulses(gap, 0) == [] and tab_pulses(gap, -5) == []
    # Puls kürzer als MIN_TAB_PULSE_MM → ganzer Steg aus (G1 S0)
    tiny = tab_pulses([(0.0, 0.0), (0.1, 0.0)], 5)
    assert tiny == [([(0.0, 0.0), (0.1, 0.0)], KIND_TAB_OFF)]
    assert 0.1 * 0.05 < MIN_TAB_PULSE_MM
    # Steg über eine Ecke: Stücke folgen der Kontur (Eckpunkt bleibt erhalten)
    corner = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0)]
    parts = tab_pulses(corner, 50)
    pts = [q for p, _ in parts for q in p]
    assert any(close(q, (1.0, 0.0)) for q in pts)
    assert sum(length(p) for p, _ in parts) == pytest.approx(2.0)


def test_apply_with_tab_power_keeps_contour_continuous():
    sq = square(20, 20, 60)
    res = apply_cut_options([sq], CutOptions(tab_count=4, tab_width_mm=2.0, tab_cut_power=30))
    assert res.kinds[0] == KIND_CUT and res.kinds.count(KIND_TAB) == 4
    assert KIND_TAB_PULSE in res.kinds and KIND_TAB_OFF in res.kinds
    # ganze Kontur ohne Unterbrechung: jedes Stück beginnt am Ende des vorigen
    for a, b in zip(res.polylines, res.polylines[1:]):
        assert close(a[-1], b[0])
    assert sum(length(p) for p in res.polylines) == pytest.approx(240.0)
    on = sum(length(p) for p, k in zip(res.polylines, res.kinds) if k == KIND_TAB_PULSE)
    assert on == pytest.approx(4 * 2.0 * 0.3)
    # 0 % = Lücke wie bisher (gleiches Ergebnis wie ohne das Feld)
    plain = apply_cut_options([sq], CutOptions(tab_count=4, tab_width_mm=2.0))
    zero = apply_cut_options([sq], CutOptions(tab_count=4, tab_width_mm=2.0, tab_cut_power=0))
    assert plain.polylines == zero.polylines and plain.kinds == zero.kinds
    assert KIND_TAB_PULSE not in plain.kinds


def test_tab_power_with_perforation_and_overcut():
    sq = square(20, 20, 60)
    res = apply_cut_options([sq], CutOptions(tab_count=2, tab_width_mm=2.0, tab_cut_power=50,
                                             perf_cut_mm=3.0, perf_skip_mm=1.0))
    assert KIND_PERF in res.kinds
    # Pulse werden nicht perforiert: genau 2 × (round(2 / 0,4) = 5) Pulse à 0,2 mm
    pulses = [p for p, k in zip(res.polylines, res.kinds) if k == KIND_TAB_PULSE]
    assert len(pulses) == 10 and all(length(p) == pytest.approx(0.2) for p in pulses)
    # Überschnitt endet wie bisher 0,5 mm vor dem ersten Steg
    over = apply_cut_options([sq], CutOptions(tab_count=2, tab_width_mm=2.0, tab_cut_power=50,
                                              overcut_mm=200.0))
    first = over.polylines[0]                    # endet am Anfang des ersten Stegs
    assert over.kinds[1] == KIND_TAB_OFF and close(over.polylines[1][0], first[-1])
    last = over.polylines[-1]
    assert math.dist(last[-1], first[-1]) == pytest.approx(0.5, abs=1e-6)


def _layer(polys, **opts):
    return JobLayer("l", "Schneiden", 80, 600, 2, polys, **opts)


def test_gcode_pulsed_tabs_one_g0_per_contour_and_pi_safe():
    lay = _layer([square(40, 40, 30), square(100, 40, 30)], tab_count=3, tab_width_mm=2.0,
                 tab_cut_power=40)
    (planned,) = optimize_layers([lay])
    g = layers_to_gcode([planned])
    pi_check(g)
    body = [l for l in g.splitlines() if l.startswith(("G0", "G1"))]
    # je Durchgang und Kontur genau eine Positionierfahrt: Pulse schließen ohne G0 an
    assert sum(1 for l in body if l.startswith("G0")) == 2 * 2
    assert any(l.startswith("G1") and l.endswith(" S0") for l in body)
    assert all(" F600" in l for l in body if l.startswith("G1"))
    assert g.count("M3 I") == 1
    # Brennlänge = Umfang − Stege + Puls-Anteil (2 Konturen × 3 Stege × 2 mm × 40 %), 2 Durchgänge
    expect = 2 * (2 * 120 - 2 * 3 * 2.0 * 0.6)
    assert burned_mm(g) == pytest.approx(expect, abs=0.05)
    gaps = layers_to_gcode(optimize_layers([_layer([square(40, 40, 30), square(100, 40, 30)],
                                                   tab_count=3, tab_width_mm=2.0)]))
    assert burned_mm(gaps) == pytest.approx(2 * (240 - 12), abs=0.05)
    assert not any(l.endswith(" S0") for l in gaps.splitlines() if l.startswith("G1"))


def test_gcode_without_new_options_unchanged():
    polys = [square(40, 40, 30), square(45, 45, 10)]
    base = layers_to_gcode(optimize_layers([_layer(polys, tab_count=3, tab_width_mm=2.0)]))
    same = layers_to_gcode(optimize_layers([_layer(polys, tab_count=3, tab_width_mm=2.0,
                                                   tab_cut_power=0.0, tab_max=5,
                                                   tab_skip_inner=False)]))
    assert base == same
    skip = layers_to_gcode(optimize_layers([_layer(polys, tab_count=3, tab_width_mm=2.0,
                                                   tab_skip_inner=True)]))
    assert skip != base and burned_mm(skip) > burned_mm(base)


def test_toolpath_and_estimate_with_pulsed_tabs():
    lay = _layer([square(40, 40, 30)], tab_count=2, tab_width_mm=2.0, tab_cut_power=50)
    g = layers_to_gcode(optimize_layers([lay]))
    tp = parse_gcode(g)
    # die Steg-Lücken sind Leerfahrten mit Schnitttempo (G1 S0), keine Eilgänge
    offs = [m for m in tp.moves if m.kind != CUT and m.feed == 600]
    assert offs and all(m.length < 2.0 for m in offs)
    est = estimate_gcode(g)
    assert est.cut_length_mm == pytest.approx(burned_mm(g), abs=0.05)
    assert est.total_time_s > 0


# --- Dokument, Planer, Serialisierung -------------------------------------------------

def _doc(**cut):
    doc = Document()
    lid = doc.active_layer_id
    doc.update_layer(lid, **cut)
    doc.add_shape(Shape("rect", Geometry(60, 60, 80, 50), lid))
    doc.add_shape(Shape("ellipse", Geometry(80, 70, 20, 20), lid))   # Loch
    return doc


def test_document_skip_inner_and_power_through_planner(qapp):
    doc = _doc(tab_count=3, tab_width_mm=1.5, tab_skip_inner=True)
    (lay,) = optimize_layers(job_layers(doc))
    assert lay.poly_kinds.count("tab") == 3                  # nur das Rechteck
    g = optimized_document_gcode(doc)
    pi_check(g)
    doc2 = _doc(tab_count=3, tab_width_mm=1.5, tab_cut_power=50, lead_in_mm=2.0)
    g2 = optimized_document_gcode(doc2)
    pi_check(g2)
    assert " S0" in g2
    (lay2,) = optimize_layers(job_layers(doc2))
    assert {"tab_pulse", "tab_off", "lead_in"} <= set(lay2.poly_kinds)
    assert len(lay2.poly_kinds) == len(lay2.polylines)


def test_layer_fields_roundtrip_defaults_and_clamp():
    l = Layer(name="A", tab_count=3, tab_skip_inner=True, tab_max=4, tab_cut_power=35)
    d = l.to_dict()
    assert {"tab_skip_inner", "tab_max", "tab_cut_power"} <= set(d)
    back = Layer.from_dict(json.loads(json.dumps(d)))
    assert (back.tab_skip_inner, back.tab_max, back.tab_cut_power) == (True, 4, 35.0)
    assert all(getattr(back, k) == getattr(l, k) for k in CUT_LAYER_FIELDS)
    # Standard wird nicht geschrieben; alte Dateien laden die Standardwerte
    plain = Layer(name="x").to_dict()
    assert not any(k in plain for k in ("tab_skip_inner", "tab_max", "tab_cut_power"))
    old = Layer.from_dict({"name": "alt", "tab_count": 2})
    assert (old.tab_skip_inner, old.tab_max, old.tab_cut_power) == (False, 0, 0.0)
    c = Layer(name="c", tab_max=-3, tab_cut_power=150).normalized()
    assert (c.tab_max, c.tab_cut_power) == (0, 95.0)
    c = Layer(name="c", tab_max=999, tab_cut_power=-1).normalized()
    assert (c.tab_max, c.tab_cut_power) == (100, 0.0)
    doc = Document()
    doc.update_layer(doc.active_layer_id, tab_cut_power=200, tab_max=500)
    assert (doc.active_layer.tab_cut_power, doc.active_layer.tab_max) == (95.0, 100)
    again = Document.from_dict(doc.to_dict())
    assert again.active_layer.tab_cut_power == 95.0


def test_cut_options_of_reads_new_fields():
    o = CutOptions.of(Layer(name="x", tab_skip_inner=True, tab_max=3, tab_cut_power=20))
    assert (o.tab_skip_inner, o.tab_max, o.tab_cut_power) == (True, 3, 20.0)
    # die neuen Felder allein schalten keine Schnittoptionen ein
    assert not o.active and not o.shapes_contours


# --- Dialog und Kurztext ------------------------------------------------------------

def test_dialog_fields_enabled_hint_and_defaults(qapp):
    from PySide6.QtWidgets import QDialogButtonBox
    from lumacut_job.cut_qt import CutOptionsDialog
    dlg = CutOptionsDialog(Layer(name="Schneiden"))
    assert dlg.values() == CUT_LAYER_DEFAULTS
    assert dlg.tab_max.text() == "unbegrenzt" and dlg.tab_power.text() == "aus (Lücke)"
    # ohne Stege ausgegraut
    assert not dlg.tab_max.isEnabled() and not dlg.tab_power.isEnabled()
    assert not dlg.tab_skip_inner.isEnabled()
    dlg.tab_count.setValue(4)
    assert dlg.tab_power.isEnabled() and dlg.tab_skip_inner.isEnabled()
    assert not dlg.tab_max.isEnabled()                 # nur im Abstands-Modus
    dlg.tab_spacing.setValue(40.0)
    assert dlg.tab_max.isEnabled()
    dlg.tab_max.setValue(6)
    dlg.tab_skip_inner.setChecked(True)
    assert dlg.tabs_hint.text() == ""
    dlg.tab_width.setValue(2.0)
    dlg.tab_power.setValue(25)
    assert dlg.tabs_hint.text().startswith("Je Steg 5 Pulse à 0,10 mm")
    v = dlg.values()
    assert (v["tab_max"], v["tab_skip_inner"], v["tab_cut_power"]) == (6, True, 25.0)
    dlg.findChild(QDialogButtonBox).button(QDialogButtonBox.RestoreDefaults).click()
    assert dlg.values() == CUT_LAYER_DEFAULTS
    assert dlg.tabs_hint.text() == "" and not dlg.tab_power.isEnabled()


def test_dialog_loads_layer_values(qapp):
    from lumacut_job.cut_qt import CutOptionsDialog
    dlg = CutOptionsDialog(Layer(name="S", tab_spacing_mm=30, tab_max=5, tab_cut_power=40,
                                 tab_skip_inner=True))
    assert (dlg.tab_max.value(), dlg.tab_power.value(), dlg.tab_skip_inner.isChecked()) == \
        (5, 40.0, True)
    assert dlg.tab_max.isEnabled()


def test_tab_power_hint_texts():
    from lumacut_job.cut_qt import tab_power_hint
    assert tab_power_hint(1.0, 0) == "" and tab_power_hint(0.0, 50) == ""
    assert tab_power_hint(1.0, 50) == ("Je Steg 2 Pulse à 0,25 mm mit der Leistung der Ebene, "
                                       "dazwischen Laser aus.")
    assert tab_power_hint(0.3, 50).startswith("Je Steg 1 Puls à 0,15 mm")
    assert "bleibt ganz stehen" in tab_power_hint(0.1, 5)


def test_summary_texts():
    from lumacut_job.cut_qt import summary
    assert summary(Layer(name="x", tab_spacing_mm=40, tab_max=6, tab_cut_power=25,
                         tab_skip_inner=True)) == (
        "Stege je 40 mm, höchstens 6 Stege, Steg-Leistung 25 %, innere Formen ohne Stege")
    assert summary(Layer(name="x", tab_count=3, tab_max=6)) == "3 Stege"   # Grenze nur bei Abstand
    # ohne Stege sagen die neuen Felder nichts
    assert summary(Layer(name="x", tab_cut_power=25, tab_skip_inner=True)) == ""


@pytest.fixture
def editor(qapp):
    from lumacut_canvas.editor import CanvasEditor
    ed = CanvasEditor()
    yield ed
    ed.undo_stack.setClean()
    ed.close()
    ed.deleteLater()
    qapp.processEvents()


def test_apply_is_one_undo_step(editor):
    from lumacut_job.cut_qt import apply_cut_options as apply_ui
    doc = editor.document
    lid = doc.active_layer.id
    n = editor.undo_stack.count()
    vals = dict(CUT_LAYER_DEFAULTS, tab_count=2, tab_cut_power=30.0, tab_skip_inner=True)
    assert apply_ui(editor, lid, vals)
    assert editor.undo_stack.count() == n + 1
    assert (doc.layer(lid).tab_cut_power, doc.layer(lid).tab_skip_inner) == (30.0, True)
    assert not apply_ui(editor, lid, vals)
    editor.undo_stack.undo()
    assert (doc.layer(lid).tab_cut_power, doc.layer(lid).tab_skip_inner) == (0.0, False)


def test_main_window_cut_options_with_tab_power(qapp):
    from main import LumaCutStudio
    win = LumaCutStudio()
    try:
        tools = win.job_tools
        ed = win.canvas
        doc = ed.document
        lid = doc.active_layer.id
        ed.undo_stack.push(AddShapesCommand(
            doc, [Shape("rect", Geometry(50, 50, 40, 30), lid),
                  Shape("ellipse", Geometry(60, 60, 10, 10), lid)], "Formen"))
        assert tools.cut_options(dict(CUT_LAYER_DEFAULTS, tab_count=4))
        gaps = optimized_document_gcode(doc)
        assert tools.cut_options(dict(CUT_LAYER_DEFAULTS, tab_count=4, tab_cut_power=50,
                                      tab_skip_inner=True))
        pulsed = optimized_document_gcode(doc)
        pi_check(pulsed)
        assert " S0" in pulsed and burned_mm(pulsed) > burned_mm(gaps)
        msg = win.statusBar().currentMessage()
        assert "Steg-Leistung 50 %" in msg and "innere Formen ohne Stege" in msg
    finally:
        win.canvas.undo_stack.setClean()
        win.close()
        win.deleteLater()
        qapp.processEvents()
