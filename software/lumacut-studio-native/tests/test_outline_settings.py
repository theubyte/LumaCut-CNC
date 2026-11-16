"""Eigene Kontur-Einstellung einer Füll-Ebene (LightBurn Unterebene „Line“ unter „Fill“):
Modell (Standard aus, nur gespeichert wenn gesetzt, kaputte Werte = „wie Ebene“), Export
(zwei Blöcke: Füllung, dann Konturen), G-Code (eigenes S / F / Durchgänge, Pi-Prüfung, ein
M3, Byte für Byte gleich ohne Werte), Schnittoptionen an der Kontur, Fokus-Schritt, Planer,
Schätzung / Pfadvorschau, Panel (Felder, Hinweis, Kurzform, Undo), Speichern / Laden."""

from __future__ import annotations

import json
import math

import pytest
from _pi_guard import pi_check

from lumacut_canvas.export import OUTLINE_SUFFIX, job_layers, split_outline
from lumacut_canvas.gcode import document_to_gcode, layers_to_gcode
from lumacut_canvas.model import (FILL_LAYER_DEFAULTS, FILL_LAYER_FIELDS, MAX_FOCUS_DROP_MM,
                                  OUTLINE_FIELDS, PASSES_RANGE, POWER_RANGE, SPEED_RANGE,
                                  CutOrder, Document, Geometry, Layer, Shape)
from lumacut_canvas.toolpath import parse_gcode
from lumacut_job.cutpath import KIND_LEAD_IN, KIND_RAMP
from lumacut_job.estimate import estimate_gcode
from lumacut_job.planner import PlanReport, optimize_layers, optimized_document_gcode

OWN = dict(outline_power=100.0, outline_speed=300.0, outline_passes=2)


def _doc(shapes=((60, 60, 40, 20),), line=False, **layer):
    """Namensschild: Füll-Ebene 20 % · 3000 mm/min · 1× mit Kontur."""
    doc = Document()
    lid = doc.active_layer_id
    layer.setdefault("power", 20.0)
    layer.setdefault("speed", 3000.0)
    layer.setdefault("fill_mode", "hatch")
    layer.setdefault("line_interval_mm", 2.0)
    doc.update_layer(lid, **layer)
    for x, y, w, h in shapes:
        doc.add_shape(Shape("rect", Geometry(x, y, w, h), lid))
    if line:
        doc.add_shape(Shape("line", Geometry(60, 150, 50, 0), lid))
    return doc


def _blocks(g: str) -> dict[str, list[str]]:
    """G-Code-Zeilen je ``; LAYER``-Block."""
    out: dict[str, list[str]] = {}
    cur = None
    for ln in g.splitlines():
        if ln.startswith("; LAYER "):
            cur = ln[len("; LAYER "):]
            out[cur] = []
        elif cur is not None:
            out[cur].append(ln)
    return out


def _sf(lines) -> set[tuple[str, int]]:
    """(F, S) aller G1 mit Leistung."""
    out = set()
    for ln in lines:
        if ln.startswith("G1 "):
            w = {t[0]: t[1:] for t in ln.split()[1:]}
            if int(w["S"]) > 0:
                out.add((w["F"], int(w["S"])))
    return out


def _burn(lines) -> float:
    pos, total = None, 0.0
    for ln in lines:
        if not ln.startswith(("G0 ", "G1 ")):
            continue
        w = {t[0]: float(t[1:]) for t in ln.split()[1:] if t[0] in "XYS"}
        nxt = (w["X"], w["Y"])
        if ln.startswith("G1 ") and w.get("S", 0) > 0 and pos is not None:
            total += math.dist(pos, nxt)
        pos = nxt
    return total


# --- Modell -------------------------------------------------------------------------------

def test_defaults_saved_only_when_set_and_round_trip():
    assert OUTLINE_FIELDS == ("outline_power", "outline_speed", "outline_passes")
    assert set(OUTLINE_FIELDS) <= set(FILL_LAYER_FIELDS)
    assert [FILL_LAYER_DEFAULTS[k] for k in OUTLINE_FIELDS] == [0.0, 0.0, 0]
    assert not any(k.startswith("outline") for k in Layer(name="x").to_dict())
    l = Layer(name="A", fill_mode="hatch", outline_power=90.0, outline_passes=3)
    d = l.to_dict()
    assert d["outline_power"] == 90.0 and d["outline_passes"] == 3 and "outline_speed" not in d
    back = Layer.from_dict(json.loads(json.dumps(d)))
    assert (back.outline_power, back.outline_speed, back.outline_passes) == (90.0, 0.0, 3)
    old = Layer.from_dict({"name": "alt", "fill_mode": "hatch"})
    assert (old.outline_power, old.outline_speed, old.outline_passes) == (0.0, 0.0, 0)


@pytest.mark.parametrize("raw, expect", [
    ({"outline_power": 250, "outline_speed": 99999, "outline_passes": 99},
     (POWER_RANGE[1], SPEED_RANGE[1], PASSES_RANGE[1])),
    ({"outline_power": 0.4, "outline_speed": 0.2, "outline_passes": 0.3}, (1.0, 1.0, 1)),
    ({"outline_power": -5, "outline_speed": -1, "outline_passes": -2}, (0.0, 0.0, 0)),
    ({"outline_power": "x", "outline_speed": "schnell", "outline_passes": "zwei"}, (0.0, 0.0, 0)),
    ({"outline_power": float("nan"), "outline_speed": float("inf"),
      "outline_passes": float("-inf")}, (0.0, 0.0, 0)),
    ({"outline_power": None, "outline_speed": [300], "outline_passes": {"n": 2}}, (0.0, 0.0, 0)),
    ({"outline_power": True, "outline_speed": False, "outline_passes": True}, (0.0, 0.0, 0)),
    ({"outline_power": "75", "outline_speed": "450.55", "outline_passes": 2.6}, (75.0, 450.6, 3)),
])
def test_broken_values_and_clamping(raw, expect):
    l = Layer.from_dict({"name": "b", "fill_mode": "hatch", **raw})
    assert (l.outline_power, l.outline_speed, l.outline_passes) == expect
    assert isinstance(l.outline_passes, int)


def test_update_layer_normalizes():
    doc = Document()
    lid = doc.active_layer_id
    doc.update_layer(lid, outline_power=500.0, outline_speed=-3.0, outline_passes=50)
    lay = doc.layer(lid)
    assert (lay.outline_power, lay.outline_speed, lay.outline_passes) == (100.0, 0.0, 30)


def test_outline_settings_only_with_fill_and_outline_and_a_difference():
    base = dict(power=20.0, speed=3000.0, passes=1)
    assert Layer(name="a", **base, **OWN).outline_settings() is None           # keine Füllung
    assert Layer(name="a", fill_mode="hatch", hatch_outline=False, **base,
                 **OWN).outline_settings() is None                             # Kontur aus
    assert Layer(name="a", fill_mode="hatch", **base).outline_settings() is None   # nicht gesetzt
    assert Layer(name="a", fill_mode="hatch", outline_power=20.0, outline_speed=3000.0,
                 outline_passes=1, **base).outline_settings() is None          # alles gleich
    assert Layer(name="a", fill_mode="offset", **base, **OWN).outline_settings() == (100.0, 300.0, 2)
    # nur ein Wert gesetzt: der Rest wie die Ebene
    assert Layer(name="a", fill_mode="crosshatch", outline_speed=500.0,
                 **base).outline_settings() == (20.0, 500.0, 1)
    assert Layer(name="a", fill_mode="hatch", outline_passes=3,
                 **base).outline_settings() == (20.0, 3000.0, 3)


def test_old_files_keep_their_project_bytes():
    d = Document.from_dict(_doc().to_dict()).to_dict()
    assert all(not any(k.startswith("outline") for k in l) for l in d["layers"])
    again = Document.from_dict(json.loads(json.dumps(d))).to_dict()
    assert json.dumps(again, sort_keys=True) == json.dumps(d, sort_keys=True)


# --- Export ---------------------------------------------------------------------------------

def test_job_layers_split_fill_then_outline():
    doc = _doc(line=True, **OWN)
    fill, outline = job_layers(doc)
    assert fill.layer_id == outline.layer_id == doc.active_layer_id
    assert fill.name == "Schneiden" and outline.name == "Schneiden" + OUTLINE_SUFFIX
    assert fill.fills and not fill.polylines and fill.sublayer == ""
    assert (fill.power_percent, fill.speed_mm_min, fill.passes) == (20.0, 3000.0, 1)
    assert outline.polylines and not outline.fills and outline.sublayer == "outline"
    assert (outline.power_percent, outline.speed_mm_min, outline.passes) == (100.0, 300.0, 2)
    (plain,) = job_layers(_doc(line=True))
    assert outline.polylines == plain.polylines        # Konturen und offene Pfade
    assert fill.fills == plain.fills


@pytest.mark.parametrize("layer", [{}, dict(outline_power=20.0, outline_speed=3000.0,
                                            outline_passes=1),
                                   dict(fill_mode="none", **OWN),
                                   dict(hatch_outline=False, **OWN)])
def test_no_split_without_own_settings(layer):
    layers = job_layers(_doc(**layer))
    assert len(layers) == 1 and layers[0].sublayer == ""


def test_only_open_paths_on_fill_layer_give_only_the_outline_block():
    doc = _doc(shapes=(), line=True, **OWN)
    (outline,) = job_layers(doc)
    assert outline.sublayer == "outline" and outline.power_percent == 100.0


def test_split_outline_none_and_no_polylines():
    lay = Layer(name="x", fill_mode="hatch", **OWN)
    assert split_outline(None, lay) == []
    doc = _doc(hatch_outline=False)
    (jl,) = job_layers(doc)
    assert split_outline(jl, lay) == [jl]      # keine Linien → nichts zu teilen


def test_manual_start_points_stay_on_the_outline_block():
    def with_start(**layer):
        doc = _doc(**layer)
        doc.shapes[0].start = (0.5, 0.0)
        return doc
    fill, outline = job_layers(with_start(**OWN))
    (plain,) = job_layers(with_start())
    assert plain.start_points
    assert fill.start_points == () and fill.tab_points == () and fill.kept_directions == ()
    assert outline.start_points == plain.start_points
    _f, outline = optimize_layers(job_layers(with_start(**OWN)))
    (plain,) = optimize_layers(job_layers(with_start()))
    assert outline.polylines == plain.polylines


def test_angle_increment_fills_stay_with_the_fill_block():
    doc = _doc(passes=2, fill_angle_increment=90.0, **OWN)
    fill, outline = job_layers(doc)
    assert len(fill.pass_fills) == 2 and fill.pass_fill_angles
    assert outline.pass_fills == [] and outline.pass_fill_angles == ()


def test_cut_order_by_group_splits_every_unit():
    doc = Document(with_default_layer=False)
    eng = doc.add_layer(Layer("Schild", power=20, speed=3000, fill_mode="hatch",
                              line_interval_mm=2.0, **OWN))
    for i in range(2):
        doc.add_shape(Shape("rect", Geometry(40 + 80 * i, 60, 30, 20), eng.id,
                            groups=(f"g{i}",)))
    doc.set_cut_order(CutOrder(order_by="group"))
    layers = job_layers(doc)
    assert [(l.unit, l.sublayer) for l in layers] == [("1 OF 2", ""), ("1 OF 2", "outline"),
                                                      ("2 OF 2", ""), ("2 OF 2", "outline")]
    g = layers_to_gcode(layers)
    pi_check(g)
    assert g.count("; GROUP ") == 2 and g.count("M3 I") == 1


# --- G-Code -----------------------------------------------------------------------------------

def test_gcode_byte_identical_without_own_settings():
    for fn in (document_to_gcode, lambda d: optimized_document_gcode(d, scan_offsets=None)):
        plain = fn(_doc(line=True))
        assert fn(_doc(line=True, outline_power=20.0, outline_speed=3000.0,
                       outline_passes=1)) == plain
        assert fn(_doc(line=True, hatch_outline=False, **OWN)) == \
            fn(_doc(line=True, hatch_outline=False))
        assert fn(_doc(line=True, fill_mode="none", **OWN)) == fn(_doc(line=True, fill_mode="none"))


@pytest.mark.parametrize("order", [CutOrder(), CutOrder(enabled=False), CutOrder(corners=True)])
def test_gcode_own_power_speed_passes_pi_safe(order):
    doc, plain_doc = _doc(line=True, **OWN), _doc(line=True)
    doc.set_cut_order(order)
    plain_doc.set_cut_order(order)
    g = optimized_document_gcode(doc, scan_offsets=None)
    plain = optimized_document_gcode(plain_doc, scan_offsets=None)
    pi_check(g)
    assert g.count("M3 I") == 1 and g.count("M5 I") == 2 and g.rstrip().endswith("M400")
    blocks = _blocks(g)
    assert list(blocks) == ["Schneiden", "Schneiden (Kontur)"]
    fill, outline = blocks["Schneiden"], blocks["Schneiden (Kontur)"]
    assert _sf(fill) == {("3000", round(0.2 * 255))}
    assert _sf(outline) == {("300", 255)}
    assert sum(1 for ln in fill if ln.startswith("; PASS")) == 1
    assert [ln for ln in outline if ln.startswith("; PASS")] == ["; PASS 1 OF 2", "; PASS 2 OF 2"]
    # gleiche Füllung, Konturen und offene Pfade doppelt
    lines_once = parse_gcode(document_to_gcode(_doc(line=True, fill_mode="none"))).cut_length_mm
    assert lines_once > 0
    assert _burn(outline) == pytest.approx(2 * lines_once, rel=1e-6)
    assert _burn(fill) + _burn(outline) == pytest.approx(
        _burn(_blocks(plain)["Schneiden"]) + lines_once, rel=1e-6)


def test_fill_before_outline_even_with_several_layer_passes():
    g = document_to_gcode(_doc(passes=3, outline_passes=1, outline_power=90.0))
    pi_check(g)
    blocks = _blocks(g)
    assert [ln for ln in blocks["Schneiden"] if ln.startswith("; PASS")] == \
        ["; PASS 1 OF 3", "; PASS 2 OF 3", "; PASS 3 OF 3"]
    assert [ln for ln in blocks["Schneiden (Kontur)"] if ln.startswith("; PASS")] == \
        ["; PASS 1 OF 1"]
    assert g.index("; LAYER Schneiden\n") < g.index("; LAYER Schneiden (Kontur)")


def test_only_one_value_set_keeps_the_rest_of_the_layer():
    g = document_to_gcode(_doc(outline_speed=600.0))
    assert _sf(_blocks(g)["Schneiden (Kontur)"]) == {("600", round(0.2 * 255))}


def test_cut_options_apply_to_the_outline_like_before():
    cut = dict(kerf_mm=0.1, lead_in_mm=2.0, lead_out_mm=1.0, overcut_mm=1.0, tab_count=2,
               tab_width_mm=1.0, ramp_mm=1.0)
    rep = PlanReport()
    fill, outline = optimize_layers(job_layers(_doc(**cut, **OWN)), report=rep)
    (plain,) = optimize_layers(job_layers(_doc(**cut)))
    assert outline.polylines == plain.polylines and outline.poly_kinds == plain.poly_kinds
    assert outline.poly_power_scale == plain.poly_power_scale
    assert KIND_LEAD_IN in outline.poly_kinds and KIND_RAMP in outline.poly_kinds
    assert not fill.polylines and fill.fills
    assert rep.ramps == 1
    g = optimized_document_gcode(_doc(**cut, **OWN), scan_offsets=None)
    pi_check(g)
    outline_s = {int(ln.rsplit("S", 1)[1]) for ln in _blocks(g)["Schneiden (Kontur)"]
                 if ln.startswith("G1 ")}
    assert 255 in outline_s and len(outline_s) > 2     # Rampe von der Kontur-Leistung aus


def test_perforation_and_overlap_on_outline():
    g = optimized_document_gcode(_doc(perf_cut_mm=2.0, perf_skip_mm=1.0, **OWN),
                                 scan_offsets=None)
    pi_check(g)
    outline = _blocks(g)["Schneiden (Kontur)"]
    assert any("S0" in ln for ln in outline if ln.startswith("G1 ")) or \
        sum(1 for ln in outline if ln.startswith("G0 ")) > 2


def test_focus_step_shrinks_to_stay_within_the_limit():
    (fill, outline) = job_layers(_doc(z_step=1.5, passes=1, outline_passes=4))
    assert fill.z_step_mm == 1.5
    assert outline.z_step_mm == pytest.approx(1.0)
    assert outline.z_step_mm * 3 <= MAX_FOCUS_DROP_MM + 1e-9
    (_f, outline) = job_layers(_doc(z_step=1.0, z_offset=-1.0, outline_passes=4))
    assert outline.z_step_mm == pytest.approx(0.666)
    (_f, outline) = job_layers(_doc(z_step=0.5, outline_passes=4))
    assert outline.z_step_mm == 0.5                      # passt, bleibt
    g = document_to_gcode(_doc(z_step=1.5, outline_passes=4, outline_power=100.0))
    pi_check(g)
    assert "G0 Z-1.000 F600" in g


def test_pass_depths_only_kept_when_the_pass_count_matches():
    doc = _doc(passes=2, outline_power=100.0, thickness_mm=3.0, depth_per_pass_mm=1.5)
    fill, outline = job_layers(doc)
    assert outline.passes == 2 and outline.pass_depths_mm == fill.pass_depths_mm
    doc = _doc(passes=2, outline_passes=3, thickness_mm=3.0, depth_per_pass_mm=1.5)
    fill, outline = job_layers(doc)
    assert outline.pass_depths_mm == ()


def test_scan_offset_and_overscan_only_on_the_fill_block():
    from lumacut_job.scan_offset import ScanOffsetTable
    table = ScanOffsetTable(((1000.0, 0.2), (3000.0, 0.4)))
    g = optimized_document_gcode(_doc(fill_overscan_mm=2.0, **OWN), scan_offsets=table)
    pi_check(g)
    outline = _blocks(g)["Schneiden (Kontur)"]
    plain = _blocks(optimized_document_gcode(_doc(**OWN), scan_offsets=None))["Schneiden (Kontur)"]
    assert outline == plain


def test_estimate_and_path_preview():
    g = optimized_document_gcode(_doc(**OWN), scan_offsets=None)
    plain = optimized_document_gcode(_doc(), scan_offsets=None)
    est, est0 = estimate_gcode(g), estimate_gcode(plain)
    contour = 2 * (40 + 20)
    assert est.cut_length_mm == pytest.approx(est0.cut_length_mm + contour, rel=1e-3)
    # Kontur 2× mit 300 statt 1× mit 3000 mm/min: mindestens 2 · 120 mm / 5 mm/s = 48 s
    assert est.cut_time_s >= est0.cut_time_s + 2 * contour / 5.0 - contour / 50.0 - 1
    tp = parse_gcode(g)
    assert tp.cut_length_mm == pytest.approx(est.cut_length_mm, rel=1e-3)
    powers = {m.power for m in tp.moves if m.power > 0}
    assert len(powers) == 2


def test_two_layers_and_images_stay_in_order():
    doc = _doc(**OWN)
    cut = doc.add_layer(Layer("Ausschnitt", power=100, speed=200))
    doc.add_shape(Shape("rect", Geometry(150, 60, 20, 20), cut.id))
    g = optimized_document_gcode(doc, scan_offsets=None)
    pi_check(g)
    names = [ln[8:] for ln in g.splitlines() if ln.startswith("; LAYER ")]
    assert names == ["Schneiden", "Schneiden (Kontur)", "Ausschnitt"]


# --- Panel ------------------------------------------------------------------------------------

def test_panel_fields_enable_hint_undo_summary(qapp):
    from PySide6.QtGui import QUndoStack
    from lumacut_canvas.layers_panel import LayersPanel, layer_summary, outline_hint
    doc = _doc(fill_mode="none")
    stack = QUndoStack()
    p = LayersPanel(doc, stack)
    spins = (p.outline_power, p.outline_speed, p.outline_passes)
    assert not any(w.isEnabled() for w in spins) and p.outline_hint.isHidden()
    assert all(w.specialValueText() == "wie Ebene" for w in spins)
    assert all("Line" in w.toolTip() for w in spins)
    p.fill_mode.setCurrentIndex(p.fill_mode.findData("hatch"))
    p.fill_mode.activated.emit(p.fill_mode.currentIndex())
    assert all(w.isEnabled() for w in spins)
    assert "Einstellung der Ebene" in p.outline_hint.text()
    n = stack.count()
    p.outline_power.setValue(80)
    p.outline_power.setValue(100)            # aufeinanderfolgende Änderungen = ein Schritt
    assert stack.count() == n + 1 and stack.text(n) == "Kontur-Leistung"
    assert doc.active_layer.outline_power == 100.0
    p.outline_speed.setValue(300)
    p.outline_passes.setValue(2)
    assert stack.count() == n + 3 and stack.text(n + 2) == "Kontur-Durchgänge"
    lay = doc.active_layer
    assert (lay.outline_power, lay.outline_speed, lay.outline_passes) == (100.0, 300.0, 2)
    assert isinstance(lay.outline_passes, int)
    summary = layer_summary(lay, "mm/min")
    assert "Kontur 100 % · 300 mm/min · 2×" in summary
    assert "eigener Einstellung" in p.outline_hint.text() and "2×" in p.outline_hint.text()
    assert outline_hint(lay, "mm/min").endswith("(wie LightBurns Unterebene „Line“).")
    # Kontur aus: Felder grau, Werte bleiben gespeichert, keine Kurzform
    p.fill_outline.setChecked(False)
    assert not any(w.isEnabled() for w in spins)
    assert "Nur die Füllung" in p.outline_hint.text()
    assert "Kontur" not in layer_summary(doc.active_layer, "mm/min")
    assert doc.active_layer.outline_passes == 2
    stack.undo()                               # Kontur wieder an
    assert all(w.isEnabled() for w in spins)
    for _ in range(3):
        stack.undo()
    lay = doc.active_layer
    assert (lay.outline_power, lay.outline_speed, lay.outline_passes) == (0.0, 0.0, 0)
    assert p.outline_power.text() == "wie Ebene"
    assert "Kontur" not in layer_summary(lay, "mm/min")


def test_panel_rows_after_kontur_mitlasern_and_touch(qapp):
    from PySide6.QtGui import QUndoStack
    from PySide6.QtWidgets import QFormLayout
    from lumacut_canvas.layers_panel import LayersPanel
    doc = _doc()
    p = LayersPanel(doc, QUndoStack())
    form = p.fill_box.layout()
    rows = {}
    for i in range(form.rowCount()):
        for role in (QFormLayout.FieldRole, QFormLayout.SpanningRole):
            item = form.itemAt(i, role)
            if item is not None and item.widget() is not None:
                rows[item.widget()] = i
    assert rows[p.fill_outline] < rows[p.outline_power] < rows[p.outline_speed] \
        < rows[p.outline_passes] < rows[p.outline_hint] < rows[p.fill_bidir]
    p.set_touch_mode(True)
    p.outline_speed.setValue(450)
    assert doc.active_layer.outline_speed == 450.0
    p.set_touch_mode(False)


def test_panel_speed_in_mm_per_s(qapp):
    from lumacut_canvas.layers_panel import layer_summary
    lay = _doc(outline_speed=600.0).active_layer
    assert "Kontur 20 % · 10 mm/s · 1×" in layer_summary(lay, "mm/s")


def test_layer_hint_follows_the_main_values(qapp):
    from lumacut_canvas.layers_panel import outline_hint
    doc = _doc(outline_power=50.0)
    assert "50 %" in outline_hint(doc.active_layer, "mm/min")
    doc.update_layer(doc.active_layer_id, power=50.0)   # jetzt gleich der Ebene
    assert "Einstellung der Ebene" in outline_hint(doc.active_layer, "mm/min")
    assert len(job_layers(doc)) == 1
    doc.update_layer(doc.active_layer_id, fill_mode="none")
    assert outline_hint(doc.active_layer) == ""


# --- Datei / Hauptfenster -------------------------------------------------------------------

def test_document_save_load(tmp_path):
    from lumacut_canvas.document_io import load_document, save_document
    doc = _doc(line=True, **OWN)
    path = save_document(doc, tmp_path / "schild.lcs")
    back = load_document(path)
    lay = back.layer(back.active_layer_id)
    assert (lay.outline_power, lay.outline_speed, lay.outline_passes) == (100.0, 300.0, 2)
    assert optimized_document_gcode(back, scan_offsets=None) == \
        optimized_document_gcode(doc, scan_offsets=None)


def test_broken_file_values_load_as_off(tmp_path):
    from lumacut_canvas.document_io import load_document, save_document
    doc = _doc()
    path = save_document(doc, tmp_path / "kaputt.lcs")
    data = json.loads(path.read_text(encoding="utf-8"))
    data["layers"][0].update(outline_power="viel", outline_speed=None, outline_passes=-4)
    path.write_text(json.dumps(data), encoding="utf-8")
    back = load_document(path)
    lay = back.layer(back.active_layer_id)
    assert (lay.outline_power, lay.outline_speed, lay.outline_passes) == (0.0, 0.0, 0)
    assert document_to_gcode(back) == document_to_gcode(doc)


def test_main_window_panel_and_send(qapp):
    from main import LumaCutStudio
    from lumacut_canvas.commands import AddShapesCommand
    win = LumaCutStudio()
    try:
        ed = win.canvas
        doc = ed.document
        lid = doc.active_layer.id
        ed.undo_stack.push(AddShapesCommand(doc, [Shape("rect", Geometry(40, 40, 30, 20), lid)],
                                            "Rechteck"))
        doc.update_layer(lid, power=20.0, speed=3000.0, fill_mode="hatch", line_interval_mm=2.0)
        panel = win.layers_panel
        panel.outline_power.setValue(100)
        panel.outline_passes.setValue(2)
        assert doc.layer(lid).outline_settings() == (100.0, 3000.0, 2)
        g, _note = win.job_tools.job_gcode(ask_inputs=False)
        pi_check(g)
        assert g.count("M3 I") == 1 and "(Kontur)" in g
        assert _sf(_blocks(g)[doc.layer(lid).name + OUTLINE_SUFFIX]) == {("3000", 255)}
    finally:
        win.canvas.undo_stack.setClean()
        win.close()
        win.deleteLater()
        qapp.processEvents()
