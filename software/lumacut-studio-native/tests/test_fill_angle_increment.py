"""Winkel-Schritt je Durchgang der Schraffur (LightBurn Fill „Angle Increment“)."""

from __future__ import annotations

import math

import pytest

from _pi_guard import pi_check


def _doc(shapes=((10, 10, 20, 20),), **layer):
    from lumacut_canvas.model import Document, Geometry, Shape
    doc = Document()
    lid = doc.active_layer_id
    layer.setdefault("fill_mode", "hatch")
    layer.setdefault("line_interval_mm", 2.0)
    layer.setdefault("hatch_outline", False)
    layer.setdefault("passes", 2)
    doc.update_layer(lid, **layer)
    for x, y, w, h in shapes:
        doc.add_shape(Shape("rect", Geometry(x, y, w, h), lid))
    return doc


def _gcode(doc):
    from lumacut_canvas.gcode import document_to_gcode
    return document_to_gcode(doc)


def _passes(g):
    """Je ``; PASS`` die gelaserten Strecken ``((x0, y0), (x1, y1))`` und Kommentare."""
    out = []
    pos = None
    for line in g.splitlines():
        if line.startswith("; PASS"):
            out.append({"burns": [], "comments": []})
            continue
        if line.startswith(";") and out:
            out[-1]["comments"].append(line)
            continue
        if not line.startswith(("G0 ", "G1 ")):
            continue
        w = dict((t[0], float(t[1:])) for t in line.split()[1:] if t[0] in "XYS")
        nxt = (w["X"], w["Y"])
        if line.startswith("G1 ") and w.get("S", 0) > 0 and out and pos is not None:
            out[-1]["burns"].append((pos, nxt))
        pos = nxt
    return out


def _direction(seg) -> float:
    """Richtung einer Strecke in Grad [0, 180) (Maschinen-mm)."""
    (x0, y0), (x1, y1) = seg
    return round(math.degrees(math.atan2(y1 - y0, x1 - x0)) % 180.0, 1) % 180.0


def _burn_len(segs) -> float:
    return sum(math.dist(a, b) for a, b in segs)


# --- Modell -----------------------------------------------------------------------

def test_layer_default_normalization_and_file_roundtrip(qapp):
    from lumacut_canvas.hatch import ANGLE_INCREMENT_RANGE
    from lumacut_canvas.model import FILL_LAYER_FIELDS, Document, Layer
    assert ANGLE_INCREMENT_RANGE == (-90.0, 90.0)
    assert "fill_angle_increment" in FILL_LAYER_FIELDS
    l = Layer("x")
    assert l.fill_angle_increment == 0.0 and "fill_angle_increment" not in l.to_dict()
    l = Layer.from_dict({"name": "x", "fill_mode": "hatch", "passes": 4,
                         "fill_angle_increment": 45})
    assert l.fill_angle_increment == 45.0 and l.to_dict()["fill_angle_increment"] == 45.0
    assert Layer.from_dict(l.to_dict()) == l
    for raw, expected in ((200, 90.0), (-500, -90.0), (12.34567, 12.346), (-0.0, 0.0),
                          (float("nan"), 0.0), (float("inf"), 0.0)):
        got = Layer.from_dict({"fill_angle_increment": raw}).fill_angle_increment
        assert got == expected, raw
        assert math.copysign(1.0, got) == 1.0 or got != 0.0
    assert Layer("x", fill_angle_increment="kaputt").normalized().fill_angle_increment == 0.0
    doc = _doc(fill_angle_increment=30.0)
    back = Document.from_dict(doc.to_dict())
    assert back.layers[0].fill_angle_increment == 30.0


def test_old_files_keep_their_project_bytes(qapp):
    import json
    from lumacut_canvas.model import Document
    d = Document.from_dict(_doc().to_dict()).to_dict()
    assert all("fill_angle_increment" not in l for l in d["layers"])
    again = Document.from_dict(json.loads(json.dumps(d))).to_dict()
    assert json.dumps(again, sort_keys=True) == json.dumps(d, sort_keys=True)
    zero = _doc(fill_angle_increment=0.0).to_dict()["layers"][0]
    plain = _doc().to_dict()["layers"][0]
    zero.pop("id"), plain.pop("id")
    assert zero == plain


def test_pass_angles(qapp):
    from lumacut_canvas.hatch import pass_angles
    assert pass_angles(0, 45, 4) == [0.0, 45.0, 90.0, 135.0]
    assert pass_angles(30, -45, 3) == [30.0, 165.0, 120.0]
    assert pass_angles(10, 90, 3) == [10.0, 100.0, 10.0]
    assert pass_angles(20, 0, 3) == [20.0, 20.0, 20.0]
    assert pass_angles(170, 22.5, 2) == [170.0, 12.5]
    assert pass_angles(45, 30, 1) == [45.0]
    assert pass_angles(45, 30, 0) == [45.0]
    assert [math.copysign(1.0, a) for a in pass_angles(0, -90, 3)] == [1.0, 1.0, 1.0]


def test_layer_fill_pass_angles_only_when_it_changes_something(qapp):
    from lumacut_canvas.export import layer_fill_pass_angles
    from lumacut_canvas.model import Layer
    on = dict(fill_mode="hatch", passes=3, fill_angle_increment=45.0)
    assert layer_fill_pass_angles(Layer("x", **on)) == (0.0, 45.0, 90.0)
    assert layer_fill_pass_angles(Layer("x", **{**on, "fill_mode": "crosshatch",
                                          "hatch_angle": 45.0})) == (45.0, 90.0, 135.0)
    for change in ({"fill_mode": "offset"}, {"fill_mode": "none"}, {"passes": 1},
                   {"fill_angle_increment": 0.0}):
        assert layer_fill_pass_angles(Layer("x", **{**on, **change})) == (), change


# --- Auftrag (JobLayer) ---------------------------------------------------------------

def test_job_layer_gets_one_fill_per_pass(qapp):
    from lumacut_canvas.export import job_layers
    (jl,) = job_layers(_doc(passes=3, fill_angle_increment=90.0))
    assert len(jl.pass_fills) == 3 and jl.pass_fill_angles == (0.0, 90.0, 0.0)
    assert jl.pass_fills[0] is jl.fills and jl.pass_fills[2] is jl.fills
    assert {_direction(s) for block in jl.pass_fills[0] for s in block} == {0.0}
    assert {_direction(s) for block in jl.pass_fills[1] for s in block} == {90.0}
    # Quadrat: gleich viel Schraffur in beiden Richtungen
    assert _burn_len(jl.pass_fills[1][0]) == pytest.approx(_burn_len(jl.fills[0]), rel=1e-6)


def test_job_layer_unchanged_without_increment(qapp):
    from lumacut_canvas.export import job_layers
    plain = job_layers(_doc(passes=3))
    for extra in ({"fill_angle_increment": 0.0}, {"fill_angle_increment": 45.0, "passes": 1},
                  {"fill_angle_increment": 45.0, "fill_mode": "offset"}):
        doc = _doc(**{"passes": 3, **extra})
        (jl,) = job_layers(doc)
        assert jl.pass_fills == [] and jl.pass_fill_angles == (), extra
    from dataclasses import replace
    (jl,) = job_layers(_doc(passes=3, fill_angle_increment=0.0))
    assert repr(replace(jl, layer_id="x")) == repr(replace(plain[0], layer_id="x"))


# --- G-Code ---------------------------------------------------------------------------

def test_gcode_rotates_hatch_each_pass_and_passes_pi_guard(qapp):
    doc = _doc(passes=4, fill_angle_increment=45.0)
    g = _gcode(doc)
    pi_check(g)   # wirft bei einer abgelehnten Zeile
    passes = _passes(g)
    assert len(passes) == 4
    expected = [0.0, 45.0, 90.0, 135.0]
    for i, (p, angle) in enumerate(zip(passes, expected)):
        assert p["comments"] == [f"; FILL ANGLE {angle:g}"], i
        dirs = {_direction(s) for s in p["burns"]}
        assert dirs == {angle}, (i, dirs)
    assert not any(line.startswith(("G2 ", "G3 ")) for line in g.splitlines())
    # jede Strecke ein eigenes G1 mit Leistung, Leistung/Tempo der Ebene
    s = f" S{round(doc.layers[0].power / 100 * 255)}"
    assert all(line.endswith(s) for line in g.splitlines()
               if line.startswith("G1 ") and " S0" not in line)


def test_crosshatch_turns_both_directions(qapp):
    g = _gcode(_doc(fill_mode="crosshatch", hatch_angle=0.0, passes=2,
                    fill_angle_increment=45.0))
    first, second = _passes(g)
    assert {_direction(s) for s in first["burns"]} == {0.0, 90.0}
    assert {_direction(s) for s in second["burns"]} == {45.0, 135.0}
    assert first["comments"] == ["; FILL ANGLE 0"] and second["comments"] == ["; FILL ANGLE 45"]


def test_gcode_byte_identical_without_increment(qapp):
    base = _gcode(_doc(passes=3))
    assert "FILL ANGLE" not in base
    assert _gcode(_doc(passes=3, fill_angle_increment=0.0)) == base
    one = _gcode(_doc(passes=1))
    assert _gcode(_doc(passes=1, fill_angle_increment=45.0)) == one
    off = _gcode(_doc(fill_mode="offset", passes=3))
    assert _gcode(_doc(fill_mode="offset", passes=3, fill_angle_increment=45.0)) == off
    # ±90° ergeben dieselben Winkel (0°, 90°, 0°) – und einen anderen Auftrag als ohne
    plus = _gcode(_doc(passes=3, fill_angle_increment=90.0))
    assert plus != base and plus == _gcode(_doc(passes=3, fill_angle_increment=-90.0))
    from lumacut_job.planner import optimized_document_gcode
    assert (optimized_document_gcode(_doc(passes=3, fill_angle_increment=0.0), None)
            == optimized_document_gcode(_doc(passes=3), None))


def test_contours_stay_the_same_in_every_pass(qapp):
    g = _gcode(_doc(passes=2, fill_angle_increment=90.0, hatch_outline=True))
    lines = g.splitlines()
    i1, i2 = (i for i, l in enumerate(lines) if l.startswith("; PASS"))
    def contour(chunk):
        # Kontur = die letzten 4 G1 (Rechteck) des Durchgangs
        return [l for l in chunk if l.startswith("G1 ")][-4:]
    assert contour(lines[i1:i2]) == contour(lines[i2:])


def test_overscan_and_scan_offset_apply_to_every_pass(qapp):
    from dataclasses import replace
    from lumacut_canvas.export import job_layers
    from lumacut_canvas.gcode import layers_to_gcode
    doc = _doc(passes=2, fill_angle_increment=90.0, fill_overscan_mm=2.0)
    (jl,) = job_layers(doc)
    g = layers_to_gcode([jl])
    pi_check(g)
    lines = g.splitlines()
    i2 = next(i for i, l in enumerate(lines) if l == "; PASS 2 OF 2")
    second = lines[i2:]
    s0 = [l for l in second if l.startswith("G1 ") and l.endswith(" S0")]
    assert s0, "Überlauf auch im 2. Durchgang"
    shifted = layers_to_gcode([replace(jl, fill_scan_offset_mm=0.4)])
    burns_plain = _passes(g)[1]["burns"]
    burns_shift = _passes(shifted)[1]["burns"]
    assert len(burns_plain) == len(burns_shift)
    for (a, b), (c, d) in zip(burns_plain, burns_shift):
        # senkrechte Linien wandern um 0,2 mm entgegen ihrer Richtung (entlang Y)
        assert a[0] == pytest.approx(c[0]) and b[0] == pytest.approx(d[0])
        sign = 1 if b[1] > a[1] else -1
        assert c[1] - a[1] == pytest.approx(-0.2 * sign, abs=1e-3)


def test_fill_only_on_later_pass_still_counts(qapp):
    from lumacut_canvas.gcode import _has_moves
    from lumacut_canvas.export import JobLayer
    seg = [((50.0, 50.0), (60.0, 50.0))]
    jl = JobLayer("l", "x", 50, 1000, 2, [], fills=[], pass_fills=[[], [seg]],
                  pass_fill_angles=(0.0, 90.0))
    assert _has_moves(jl)
    from lumacut_canvas.gcode import layers_to_gcode
    g = layers_to_gcode([jl])
    p1, p2 = _passes(g)
    assert p1["burns"] == [] and p1["comments"] == []
    assert len(p2["burns"]) == 1 and p2["comments"] == ["; FILL ANGLE 90"]


# --- Planer, Vorschau, Schätzung --------------------------------------------------

def _segset(blocks):
    return {frozenset((tuple(round(c, 6) for c in a), tuple(round(c, 6) for c in b)))
            for block in blocks for a, b in block}


def test_planner_orders_every_pass_and_keeps_its_lines(qapp):
    from lumacut_canvas.export import job_layers
    from lumacut_job.planner import optimize_layers
    shapes = ((10, 10, 20, 20), (300, 10, 20, 20), (12, 200, 20, 20), (302, 200, 20, 20))
    doc = _doc(shapes, passes=3, fill_angle_increment=60.0)
    (raw,) = job_layers(doc)
    (opt,) = optimize_layers([raw])
    assert len(opt.pass_fills) == 3 and opt.pass_fills[0] == opt.fills
    for p in range(3):
        assert _segset(opt.pass_fills[p]) == _segset(raw.pass_fills[p]), p
        assert len(opt.pass_fills[p]) == 4
    # Durchgang 2 beginnt beim Block, an dem Durchgang 1 endete (kürzeste Leerfahrt)
    end1 = opt.fills[-1][-1][1]
    start2 = opt.pass_fills[1][0][0][0]
    others = [b[0][0] for b in raw.pass_fills[1]]
    assert math.dist(end1, start2) <= min(math.dist(end1, o) for o in others) + 40


def test_optimized_gcode_estimate_and_path_preview(qapp):
    from lumacut_canvas.toolpath import parse_gcode
    from lumacut_job.estimate import estimate_gcode
    from lumacut_job.planner import optimized_document_gcode
    doc = _doc(((10, 10, 30, 30), (100, 50, 30, 30)), passes=2, fill_angle_increment=90.0,
               hatch_outline=True)
    g = optimized_document_gcode(doc, None)
    pi_check(g)
    assert g.count("; FILL ANGLE 0") == 1 and g.count("; FILL ANGLE 90") == 1
    p1, p2 = _passes(g)
    assert {_direction(s) for s in p1["burns"]} >= {0.0}
    assert 90.0 in {_direction(s) for s in p2["burns"]}
    est = estimate_gcode(g)
    plain = estimate_gcode(optimized_document_gcode(
        _doc(((10, 10, 30, 30), (100, 50, 30, 30)), passes=2, hatch_outline=True), None))
    # Quadrate: unter 90° gleich viel Schraffur – die Schätzung zählt beide Durchgänge
    assert est.cut_length_mm == pytest.approx(plain.cut_length_mm, rel=0.02)
    assert est.cut_time_s > 0
    tp = parse_gcode(g)
    assert tp.moves, "Pfadvorschau liest den G-Code"


def test_cut_order_by_group_keeps_the_increment(qapp):
    from lumacut_canvas.export import job_layers
    from lumacut_canvas.gcode import layers_to_gcode
    from lumacut_canvas.model import CutOrder, Document, Geometry, Layer, Shape
    doc = Document(with_default_layer=False)
    eng = doc.add_layer(Layer("Gravur", power=30, speed=3000, fill_mode="hatch", passes=2,
                              hatch_outline=False, line_interval_mm=2.0,
                              fill_angle_increment=90.0))
    for i in range(2):
        doc.add_shape(Shape("rect", Geometry(40 + 80 * i, 60, 30, 20), eng.id,
                            groups=(f"g{i}",)))
    doc.set_cut_order(CutOrder(order_by="group"))
    layers = job_layers(doc)
    assert [l.unit for l in layers] == ["1 OF 2", "2 OF 2"]
    for jl in layers:
        assert len(jl.pass_fills) == 2 and len(jl.fills) == 1
    g = layers_to_gcode(layers)
    assert g.count("; FILL ANGLE 90") == 2
    pi_check(g)


def test_canvas_fill_preview_shows_the_first_pass(qapp):
    from lumacut_canvas.export import layer_fill_blocks
    doc = _doc(passes=2, hatch_angle=30.0, fill_angle_increment=60.0)
    layer = doc.layers[0]
    blocks = layer_fill_blocks(doc, layer)
    assert blocks == layer_fill_blocks(doc, layer, 30.0)
    assert blocks != layer_fill_blocks(doc, layer, 90.0)
    (ids, _segs), = blocks
    (ids2, segs2), = layer_fill_blocks(doc, layer, 90.0)
    assert ids2 == ids
    assert {round(math.degrees(math.atan2(b[1] - a[1], b[0] - a[0])) % 180, 1)
            for a, b in segs2} == {90.0}


# --- Panel ----------------------------------------------------------------------------

def test_panel_spin_enable_state_undo_summary(qapp):
    from PySide6.QtGui import QUndoStack
    from lumacut_canvas.layers_panel import LayersPanel, layer_summary
    doc = _doc(fill_mode="none")
    stack = QUndoStack()
    p = LayersPanel(doc, stack)
    assert not p.fill_angle_step.isEnabled()
    assert p.fill_angle_step.minimum() == -90 and p.fill_angle_step.maximum() == 90
    assert "Angle Increment" in p.fill_angle_step.toolTip()
    for mode, enabled in (("hatch", True), ("offset", False), ("crosshatch", True)):
        p.fill_mode.setCurrentIndex(p.fill_mode.findData(mode))
        p.fill_mode.activated.emit(p.fill_mode.currentIndex())
        assert p.fill_angle_step.isEnabled() is enabled, mode
    n = stack.count()
    p.fill_angle_step.setValue(15)
    p.fill_angle_step.setValue(45)            # aufeinanderfolgende Änderungen = ein Schritt
    assert doc.active_layer.fill_angle_increment == 45.0 and stack.count() == n + 1
    assert stack.text(n) == "Winkel-Schritt"
    assert "Winkel-Schritt +45°" in layer_summary(doc.active_layer)
    p.fill_angle_step.setValue(-22)
    assert "Winkel-Schritt -22°" in layer_summary(doc.active_layer)
    stack.undo()
    assert doc.active_layer.fill_angle_increment == 0.0 and p.fill_angle_step.value() == 0.0
    assert "Winkel-Schritt" not in layer_summary(doc.active_layer)
    stack.redo()
    assert p.fill_angle_step.value() == -22.0
    # Offset-Füllung: Wert bleibt gespeichert, aber keine Anzeige in der Kurzform
    doc.update_layer(doc.active_layer_id, fill_mode="offset")
    assert "Winkel-Schritt" not in layer_summary(doc.active_layer)


def test_panel_form_row_and_touch_mode(qapp):
    from PySide6.QtGui import QUndoStack
    from PySide6.QtWidgets import QFormLayout
    from lumacut_canvas.layers_panel import LayersPanel
    doc = _doc()
    p = LayersPanel(doc, QUndoStack())
    form = p.fill_box.layout()
    assert isinstance(form, QFormLayout)
    labels = [form.itemAt(i, QFormLayout.LabelRole).widget().text()
              for i in range(form.rowCount())
              if form.itemAt(i, QFormLayout.LabelRole) is not None]
    assert labels.index("Winkel-Schritt") == labels.index("Winkel") + 1
    p.set_touch_mode(True)
    assert p.fill_angle_step.isEnabled()
    p.fill_angle_step.setValue(30)
    assert doc.active_layer.fill_angle_increment == 30.0
    p.set_touch_mode(False)


def test_editor_save_load_keeps_increment(qapp, tmp_path):
    from lumacut_canvas.document_io import load_document, save_document
    doc = _doc(passes=3, fill_angle_increment=-30.0)
    path = tmp_path / "w.lcs"
    save_document(doc, path)
    back = load_document(path)
    assert back.layers[0].fill_angle_increment == -30.0
    assert _gcode(back) == _gcode(doc)
