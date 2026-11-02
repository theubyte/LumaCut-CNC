"""Überlauf der Schraffur (LightBurn „Overscanning“) und Reihenfolge der Füllblöcke."""

from __future__ import annotations

import math

import pytest

from _pi_guard import pi_check

def _doc(shapes=((10, 10, 20, 10),), **layer):
    from lumacut_canvas.model import Document, Geometry, Shape
    doc = Document()
    lid = doc.active_layer_id
    layer.setdefault("fill_mode", "hatch")
    layer.setdefault("line_interval_mm", 2.0)
    layer.setdefault("hatch_outline", False)
    doc.update_layer(lid, **layer)
    for x, y, w, h in shapes:
        doc.add_shape(Shape("rect", Geometry(x, y, w, h), lid))
    return doc


def _moves(g):
    """(G-Nummer, (x, y), S oder None) je Bewegung."""
    out = []
    for line in g.splitlines():
        if not line.startswith(("G0 ", "G1 ")):
            continue
        w = dict((t[0], float(t[1:])) for t in line.split()[1:])
        out.append((int(line[1]), (w["X"], w["Y"]), w.get("S")))
    return out


def _gcode(doc):
    from lumacut_canvas.gcode import document_to_gcode
    return document_to_gcode(doc)


# --- Modell -----------------------------------------------------------------------

def test_layer_default_normalization_and_file_roundtrip(qapp):
    from lumacut_canvas.hatch import OVERSCAN_RANGE
    from lumacut_canvas.model import Document, Layer
    assert OVERSCAN_RANGE == (0.0, 20.0)
    l = Layer("x")
    assert l.fill_overscan_mm == 0.0 and "fill_overscan_mm" not in l.to_dict()
    l = Layer.from_dict({"name": "x", "fill_mode": "hatch", "fill_overscan_mm": 2.5})
    assert l.fill_overscan_mm == 2.5 and l.to_dict()["fill_overscan_mm"] == 2.5
    assert Layer.from_dict(l.to_dict()) == l
    assert Layer.from_dict({"fill_overscan_mm": 99}).fill_overscan_mm == 20.0
    assert Layer.from_dict({"fill_overscan_mm": -3}).fill_overscan_mm == 0.0
    doc = _doc(fill_overscan_mm=3.0)
    assert Document.from_dict(doc.to_dict()).layers[0].fill_overscan_mm == 3.0


def test_job_layer_carries_overscan_only_for_line_fills(qapp):
    from lumacut_canvas.export import job_layers
    for mode, expected in (("hatch", 2.0), ("crosshatch", 2.0), ("offset", 0.0)):
        (jl,) = job_layers(_doc(fill_mode=mode, fill_overscan_mm=2.0))
        assert jl.fill_overscan_mm == expected


# --- G-Code -----------------------------------------------------------------------

def test_default_output_is_unchanged(qapp):
    """0 mm: kein S0, gleiche Zeilen wie ohne das Feld; Offset ignoriert den Überlauf."""
    from lumacut_canvas.export import job_layers
    from lumacut_canvas.gcode import layers_to_gcode
    from dataclasses import replace
    g = _gcode(_doc())
    assert " S0" not in g
    (jl,) = job_layers(_doc())
    assert layers_to_gcode([replace(jl, fill_overscan_mm=0.0)]) == g
    off = _doc(fill_mode="offset")
    off_os = _doc(fill_mode="offset", fill_overscan_mm=5.0)
    assert _gcode(off_os) == _gcode(off)
    mv = _moves(g)
    assert all(m[0] == 0 or m[2] > 0 for m in mv)


@pytest.mark.parametrize("mode,angle", [("hatch", 0.0), ("hatch", 30.0), ("crosshatch", 45.0)])
def test_overscan_extends_every_line_laser_off_on_both_ends(qapp, mode, angle):
    d = 2.0
    plain = _moves(_gcode(_doc(fill_mode=mode, hatch_angle=angle)))
    over = _moves(_gcode(_doc(fill_mode=mode, hatch_angle=angle, fill_overscan_mm=d)))
    burn_plain = [m for m in plain if m[0] == 1]
    burn = [(i, m) for i, m in enumerate(over) if m[0] == 1 and m[2] > 0]
    assert [m for _, m in burn] == burn_plain          # gleiche Laserstrecken
    for i, (_, end, s) in burn:
        start = over[i - 1][1]
        g_lead, lead_end, s_lead = over[i - 1]
        g_pre, pre, _ = over[i - 2]
        g_tail, tail, s_tail = over[i + 1]
        assert (g_lead, s_lead) == (1, 0.0) and g_pre == 0     # G0 → G1 S0 → G1 S → G1 S0
        assert (g_tail, s_tail) == (1, 0.0)
        assert math.dist(pre, start) == pytest.approx(d, abs=2e-3)
        assert math.dist(end, tail) == pytest.approx(d, abs=2e-3)
        # kollinear: Anlauf und Auslauf liegen auf der Verlängerung der Linie
        L = math.dist(start, end)
        assert math.dist(pre, end) == pytest.approx(L + d, abs=3e-3)
        assert math.dist(start, tail) == pytest.approx(L + d, abs=3e-3)


def test_overscan_is_laser_off_for_pi_guard_estimate_and_park_check(qapp):
    from lumacut_job.estimate import estimate_gcode
    from lumacut_job.park_corner import powered_bounds
    from lumacut_job.planner import optimized_document_gcode
    for mode in ("hatch", "crosshatch"):
        plain = optimized_document_gcode(_doc(fill_mode=mode, line_interval_mm=0.5))
        over = optimized_document_gcode(_doc(fill_mode=mode, line_interval_mm=0.5,
                                             fill_overscan_mm=3.0))
        pi_check(over)
        assert over.count("M3 I") == 1
        assert powered_bounds(over) == powered_bounds(plain)
        e0, e1 = estimate_gcode(plain), estimate_gcode(over)
        assert e1.cut_length_mm == pytest.approx(e0.cut_length_mm)
        assert e1.bounds == e0.bounds
        lines = (10 / 0.5) * (2 if mode == "crosshatch" else 1)
        assert e1.travel_length_mm > e0.travel_length_mm + lines * 2 * 3.0 * 0.9
        assert e1.total_time_s > e0.total_time_s


def test_overscan_is_clamped_to_the_work_area(qapp):
    from lumacut_canvas.gcode import overscan_segment
    from lumacut_canvas.workarea import (MACHINE_X_MAX, MACHINE_X_MIN, MACHINE_Y_MAX,
                                         MACHINE_Y_MIN)
    # Rechteck bündig an der linken und unteren Kante der Arbeitsfläche
    doc = _doc(shapes=((0, 320, 30, 20),), hatch_angle=30.0, fill_overscan_mm=10.0)
    g = _gcode(doc)
    pi_check(g)
    mv = _moves(g)
    assert any(m[2] == 0.0 for m in mv)
    for _, (x, y), _ in mv:
        assert MACHINE_X_MIN - 1e-3 <= x <= MACHINE_X_MAX + 1e-3
        assert MACHINE_Y_MIN - 1e-3 <= y <= MACHINE_Y_MAX + 1e-3
    # direkt: Richtung +X an der rechten Grenze -> kein Auslauf, Anlauf voll
    a, b = (MACHINE_X_MAX - 20, 100.0), (MACHINE_X_MAX - 1, 100.0)
    a2, b2 = overscan_segment(a, b, 5.0)
    assert a2 == pytest.approx((MACHINE_X_MAX - 25, 100.0))
    assert b2 == pytest.approx((MACHINE_X_MAX, 100.0))
    assert overscan_segment(b, b, 5.0) == (b, b)
    assert overscan_segment(a, b, 0.0) == (a, b)
    # schräg in die Ecke: gekürzt, nie außerhalb
    c = (MACHINE_X_MIN + 1, MACHINE_Y_MIN + 3)
    a2, _ = overscan_segment(c, (c[0] + 10, c[1] + 10), 8.0)
    assert a2[0] >= MACHINE_X_MIN - 1e-9 and a2[1] >= MACHINE_Y_MIN - 1e-9
    assert a2 == pytest.approx((MACHINE_X_MIN, MACHINE_Y_MIN + 2))


def test_path_preview_shows_overscan_as_travel(qapp):
    from lumacut_canvas.toolpath import parse_gcode
    from lumacut_job.planner import optimized_document_gcode
    t0 = parse_gcode(optimized_document_gcode(_doc()))
    t1 = parse_gcode(optimized_document_gcode(_doc(fill_overscan_mm=2.0)))
    assert t1.cut_length_mm == pytest.approx(t0.cut_length_mm)
    assert t1.rapid_length_mm > t0.rapid_length_mm


# --- Panel -----------------------------------------------------------------------

def test_panel_overscan_spin_enable_state_undo_and_summary(qapp):
    from PySide6.QtGui import QUndoStack
    from lumacut_canvas.layers_panel import LayersPanel, layer_summary
    doc = _doc(fill_mode="none")
    stack = QUndoStack()
    p = LayersPanel(doc, stack)
    assert not p.fill_overscan.isEnabled()
    for mode, enabled in (("hatch", True), ("offset", False), ("crosshatch", True)):
        p.fill_mode.setCurrentIndex(p.fill_mode.findData(mode))
        p.fill_mode.activated.emit(p.fill_mode.currentIndex())
        assert p.fill_overscan.isEnabled() is enabled, mode
    n = stack.count()
    p.fill_overscan.setValue(1.5)
    p.fill_overscan.setValue(2.5)          # aufeinanderfolgende Änderungen = ein Schritt
    assert doc.active_layer.fill_overscan_mm == 2.5 and stack.count() == n + 1
    assert stack.text(n) == "Überlauf"
    assert "Überlauf 2,5 mm" in layer_summary(doc.active_layer)
    stack.undo()
    assert doc.active_layer.fill_overscan_mm == 0.0 and p.fill_overscan.value() == 0.0
    assert "Überlauf" not in layer_summary(doc.active_layer)
    stack.redo()
    assert p.fill_overscan.value() == 2.5


# --- Reihenfolge der Füllblöcke ------------------------------------------------------

# Vier Objekte im Zickzack: Objekt-Reihenfolge links, rechts, links, rechts
ZIGZAG = ((10, 10, 10, 10), (300, 10, 10, 10), (12, 40, 10, 10), (302, 40, 10, 10))


def test_planner_orders_fill_blocks_nearest_first_and_reduces_travel(qapp):
    from lumacut_canvas.export import job_layers
    from lumacut_job.estimate import estimate_gcode
    from lumacut_job.planner import (fill_travel_length, optimize_layers,
                                     optimized_document_gcode, order_fill_blocks_nearest)
    doc = _doc(shapes=ZIGZAG)
    (jl,) = job_layers(doc)
    start = (30.0, 30.0)
    (opt,) = optimize_layers([jl], start)
    assert sum(map(len, opt.fills)) == sum(map(len, jl.fills))
    undirected = lambda blocks: sorted(sorted(tuple(sorted(seg)) for seg in b) for b in blocks)
    assert undirected(opt.fills) == undirected(jl.fills)   # nur umsortiert / umgedreht
    assert fill_travel_length(opt.fills, start) < 0.6 * fill_travel_length(jl.fills, start)
    plain = estimate_gcode(_gcode(doc))
    best = estimate_gcode(optimized_document_gcode(doc))
    assert best.cut_length_mm == pytest.approx(plain.cut_length_mm)
    assert best.travel_length_mm < 0.6 * plain.travel_length_mm
    # „Leerfahrten reduzieren“ aus: Objekt-Reihenfolge bleibt
    (keep,) = optimize_layers([jl], start, reduce_travel=False)
    assert keep.fills == jl.fills
    # ein Block: unverändert
    assert order_fill_blocks_nearest(jl.fills[:1], jl.fills[0][0][0]) == jl.fills[:1]
    assert order_fill_blocks_nearest([], start) == []


def test_offset_blocks_are_reordered_but_never_reversed(qapp):
    from lumacut_canvas.export import job_layers
    from lumacut_job.planner import optimize_layers
    doc = _doc(shapes=ZIGZAG, fill_mode="offset")
    (jl,) = job_layers(doc)
    assert jl.fill_fixed_order
    (opt,) = optimize_layers([jl], (30.0, 30.0))
    assert opt.fills != jl.fills
    assert all(any(b == o for o in jl.fills) for b in opt.fills)   # nur umsortiert


def test_contours_start_where_the_fill_ends(qapp):
    from lumacut_canvas.export import job_layers
    from lumacut_job.planner import optimize_layers
    doc = _doc(shapes=ZIGZAG, hatch_outline=True)
    (jl,) = job_layers(doc)
    (opt,) = optimize_layers([jl], (30.0, 30.0))
    end = opt.fills[-1][-1][1]
    first = opt.polylines[0]
    nearest = min(math.dist(end, p) for poly in jl.polylines for p in poly)
    assert min(math.dist(end, p) for p in first) == pytest.approx(nearest, abs=1e-6)


def test_fill_only_layer_is_kept_next_to_an_image(qapp):
    """Bild + Ebene nur mit Füllung (Kontur aus): die Schraffur geht mit raus."""
    from PySide6.QtGui import QColor, QImage
    from lumacut_canvas.model import Geometry, ImageSettings, RasterImage, Shape
    from lumacut_import.image import grayscale_png
    from lumacut_job.planner import optimized_document_gcode
    doc = _doc(fill_overscan_mm=1.0)
    img = QImage(20, 10, QImage.Format_RGB32)
    img.fill(QColor(0, 0, 0))
    png, pw, ph = grayscale_png(img)
    doc.add_shape(Shape("image", Geometry(100, 100, 20, 10), doc.active_layer_id,
                        image=RasterImage(png, pw, ph, ImageSettings())))
    g = optimized_document_gcode(doc)
    pi_check(g)
    assert "; LAYER" in g and " S0" in g
    hatch = [m for m in _moves(g) if m[0] == 1 and m[2] and abs(m[1][1] - (30 + 11)) < 1e-6]
    assert hatch
