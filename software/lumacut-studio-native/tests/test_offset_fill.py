"""Offset-Füllung je Ebene (LightBurn „Offset Fill“): Geometrie, G-Code, Planer, Panel."""

from __future__ import annotations

import math

import pytest

from _pi_guard import pi_check
from lumacut_canvas import hatch
from lumacut_canvas.hatch import (fill_segments, offset_fill_rings, rings_to_segments,
                                  segments_length)
from lumacut_job.planner import point_in_polygon

SQUARE = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]
HOLE = [(3.0, 3.0), (7.0, 3.0), (7.0, 7.0), (3.0, 7.0)]


def _dist_to_ring(p, ring):
    from shapely.geometry import LinearRing, Point
    return LinearRing(ring).distance(Point(p))


def _perimeter(ring):
    return sum(math.dist(ring[i - 1], ring[i]) for i in range(len(ring)))


# --- Geometrie ------------------------------------------------------------------

def test_mode_is_registered_with_german_label():
    assert "offset" in hatch.FILL_MODES and hatch.FILL_LABELS["offset"] == "Offset-Füllung"
    assert "offset" not in hatch.LINE_FILL_MODES


def test_square_gives_concentric_rings_half_interval_inside():
    rings = offset_fill_rings([SQUARE], 1.0)
    assert len(rings) == 5                       # 0.5, 1.5, … 4.5 mm innen
    for k, ring in enumerate(rings):
        d = k + 0.5
        xs = [p[0] for p in ring]
        ys = [p[1] for p in ring]
        assert min(xs) == pytest.approx(d) and max(xs) == pytest.approx(10 - d)
        assert min(ys) == pytest.approx(d) and max(ys) == pytest.approx(10 - d)
        assert _perimeter(ring) == pytest.approx(4 * (10 - 2 * d))
        assert ring[0] != ring[-1]               # Startpunkt nicht wiederholt
    # Gesamtlänge ≈ Fläche / Abstand (wie bei der Schraffur)
    assert sum(_perimeter(r) for r in rings) == pytest.approx(100.0)


def test_rings_stay_inside_and_keep_spacing():
    rings = offset_fill_rings([SQUARE], 0.4)
    for ring in rings:
        assert all(point_in_polygon(p, SQUARE) for p in ring)
    # jeder Ring hat überall den gleichen Abstand zur Kante
    for k, ring in enumerate(rings):
        for p in ring[::3]:
            assert _dist_to_ring(p, SQUARE) == pytest.approx((k + 0.5) * 0.4, abs=1e-6)


def test_holes_stay_free_and_get_their_own_rings():
    rings = offset_fill_rings([SQUARE, HOLE], 1.0)
    for ring in rings:
        for p in ring:
            assert point_in_polygon(p, SQUARE)
            assert not point_in_polygon(p, HOLE)
            assert _dist_to_ring(p, HOLE) >= 0.5 - 1e-6
    # ein Ring umschließt das Loch im Abstand 0,5 mm (gerundete Ecken)
    around = [r for r in rings if min(p[0] for p in r) == pytest.approx(2.5)]
    assert around and all(_dist_to_ring(p, HOLE) == pytest.approx(0.5, abs=0.03)
                          for p in around[0])


def test_circle_rings_are_round_and_outside_in():
    from shapely.geometry import Point
    circle = list(Point(20, 20).buffer(5, quad_segs=64).exterior.coords)[:-1]
    rings = offset_fill_rings([circle], 1.0)
    assert len(rings) == 5
    radii = [sum(math.dist(p, (20, 20)) for p in r) / len(r) for r in rings]
    assert radii == pytest.approx([4.5, 3.5, 2.5, 1.5, 0.5], abs=0.02)


def test_separate_islands_and_nearest_start():
    a = [(0.0, 0.0), (4.0, 0.0), (4.0, 4.0), (0.0, 4.0)]
    b = [(10.0, 0.0), (14.0, 0.0), (14.0, 4.0), (10.0, 4.0)]
    rings = offset_fill_rings([a, b], 1.0)
    assert len(rings) == 4                       # je Insel 2 Ringe (0,5 und 1,5 mm)
    # Tiefe für Tiefe von außen nach innen
    assert [round(min(p[1] for p in r), 3) for r in rings] == [0.5, 0.5, 1.5, 1.5]
    # jeder weitere Ring beginnt am Punkt, der dem vorigen Start am nächsten liegt
    for prev, ring in zip(rings[1:], rings[2:]):
        assert math.dist(ring[0], prev[0]) == pytest.approx(
            min(math.dist(p, prev[0]) for p in ring))


def test_thin_parts_and_degenerate_input():
    assert offset_fill_rings([[(0, 0), (10, 0), (10, 0.8), (0, 0.8)]], 1.0) == []   # < 1 Intervall
    assert len(offset_fill_rings([[(0, 0), (10, 0), (10, 1.2), (0, 1.2)]], 1.0)) == 1
    assert offset_fill_rings([], 1.0) == []
    assert offset_fill_rings([[(0, 0), (1, 1)]], 1.0) == []
    assert offset_fill_rings([[(0, 0), (5, 0), (5, 5), (0, 5), (0, 0)]], 1.0)  # geschlossen angegeben
    with pytest.raises(ValueError):
        offset_fill_rings([SQUARE], 0)
    with pytest.raises(ValueError):
        offset_fill_rings([[(0, 0), (1e5, 0), (1e5, 1e5), (0, 1e5)]], 0.05)


def test_segments_form_closed_chains():
    rings = offset_fill_rings([SQUARE], 1.0)
    segs = rings_to_segments(rings)
    assert len(segs) == sum(len(r) for r in rings)
    i = 0
    for ring in rings:
        chain = segs[i:i + len(ring)]
        i += len(ring)
        assert all(chain[j][1] == chain[j + 1][0] for j in range(len(chain) - 1))
        assert chain[-1][1] == chain[0][0]       # Ring geschlossen
    assert fill_segments([SQUARE], "offset", 1.0) == segs
    # Winkel und Bidirektional haben bei Offset keine Wirkung
    assert fill_segments([SQUARE], "offset", 1.0, 37.0, False) == segs
    assert segments_length(segs) == pytest.approx(100.0)


# --- Dokument, G-Code, Planer -------------------------------------------------------

def _doc(kind="rect", **layer):
    from lumacut_canvas.model import Document, Geometry, Shape
    doc = Document()
    lid = doc.active_layer_id
    doc.update_layer(lid, **layer)
    if kind == "text":
        s = Shape("text", Geometry(20, 20, 40, 15), lid, text="OBA")
    else:
        s = Shape(kind, Geometry(20, 20, 30, 20), lid)
    doc.add_shape(s)
    return doc, s


def _moves(g):
    return [l for l in g.splitlines() if l.startswith(("G0 ", "G1 "))]


def test_shape_fill_for_rect_ellipse_text(qapp):
    from PySide6.QtCore import QPointF
    from lumacut_canvas.export import shape_fill_segments
    from lumacut_canvas.shape_paths import shape_path
    for kind in ("rect", "ellipse", "text"):
        doc, s = _doc(kind, fill_mode="offset", line_interval_mm=0.3)
        segs = shape_fill_segments(s, doc.active_layer)
        assert segs, kind
        path = shape_path(s)
        path.setFillRule(__import__("PySide6.QtCore", fromlist=["Qt"]).Qt.OddEvenFill)
        inside = sum(path.contains(QPointF(*a)) for a, _ in segs)
        assert inside / len(segs) > 0.97, kind
    doc, s = _doc("rect", fill_mode="offset", line_interval_mm=1.0)
    assert segments_length(shape_fill_segments(s, doc.active_layer)) == pytest.approx(600.0)


def test_gcode_offset_rings_without_g0_inside_a_ring(qapp):
    from lumacut_canvas.gcode import document_to_gcode
    doc, _ = _doc("rect", fill_mode="offset", line_interval_mm=1.0, power=40, speed=2400,
                  hatch_outline=False)
    g = document_to_gcode(doc)
    moves = _moves(g)
    g0 = [m for m in moves if m.startswith("G0")]
    g1 = [m for m in moves if m.startswith("G1")]
    assert len(g0) == 10                          # 30 × 20 mm / 1 mm: 10 Ringe, je ein G0
    assert len(g1) == 10 * 4                      # Rechteck-Ringe: 4 Seiten
    assert all(m.endswith("F2400 S102") for m in g1)
    assert all(" S" not in m for m in g0)
    from lumacut_job.estimate import estimate_gcode
    assert estimate_gcode(g).cut_length_mm == pytest.approx(600.0, rel=1e-3)


def test_gcode_with_outline_and_passes(qapp):
    from lumacut_canvas.gcode import document_to_gcode
    doc, _ = _doc("rect", fill_mode="offset", line_interval_mm=2.0, passes=2)
    g = document_to_gcode(doc)
    p1 = g.split("; PASS 2 OF 2")[0].split("; PASS 1 OF 2")[1]
    assert len([m for m in _moves(p1) if m.startswith("G1")]) == 5 * 4 + 4   # Ringe + Kontur
    assert g.count("G1 ") == 2 * (5 * 4 + 4)


def test_hatch_gcode_is_unchanged_by_chain_rule(qapp):
    """Schraffur: jede Strecke weiterhin mit eigenem G0 (keine Strecke beginnt am vorigen Ende)."""
    from lumacut_canvas.gcode import document_to_gcode
    doc, _ = _doc("rect", fill_mode="crosshatch", line_interval_mm=1.0, hatch_outline=False)
    moves = _moves(document_to_gcode(doc))
    assert [m[:2] for m in moves] == ["G0", "G1"] * 50


def test_planner_and_pi_guard_accept_offset_fill(qapp):
    from lumacut_canvas.gcode import document_to_gcode
    from lumacut_job.planner import optimized_document_gcode
    doc, _ = _doc("text", fill_mode="offset", line_interval_mm=0.25)
    opt = optimized_document_gcode(doc)
    plain = document_to_gcode(doc)
    assert opt.count("G1 ") == plain.count("G1 ")
    pi_check(opt)                                # Guard lehnt keine Zeile ab
    assert opt.count("M3 I") == 1


def test_reversed_block_stays_a_chain_per_ring():
    from lumacut_canvas.gcode import order_fill_blocks
    rings = offset_fill_rings([SQUARE], 2.0)
    segs = rings_to_segments(rings)
    (rev,) = order_fill_blocks([segs], pos=(5.0, 5.0))   # Mitte: innerster Ring zuerst
    assert rev[0][0] == segs[-1][1]
    breaks = sum(rev[j][1] != rev[j + 1][0] for j in range(len(rev) - 1))
    assert breaks == len(rings) - 1              # nur zwischen den Ringen ein G0


def test_layer_file_roundtrip(qapp):
    from lumacut_canvas.model import Document, Layer
    l = Layer.from_dict({"name": "x", "fill_mode": "offset", "line_interval_mm": 0.3})
    assert l.fill_mode == "offset" and Layer.from_dict(l.to_dict()) == l
    doc, _ = _doc("rect", fill_mode="offset")
    again = Document.from_dict(doc.to_dict())
    assert again.layers[0].fill_mode == "offset"


# --- Ebenen-Panel, Vorschau -----------------------------------------------------------

def test_panel_offset_mode_disables_angle_and_bidir(qapp):
    from PySide6.QtGui import QUndoStack
    from lumacut_canvas.layers_panel import LayersPanel, layer_summary
    doc, _ = _doc("rect")
    stack = QUndoStack()
    p = LayersPanel(doc, stack)
    idx = p.fill_mode.findData("offset")
    assert idx >= 0 and p.fill_mode.itemText(idx) == "Offset-Füllung"
    p.fill_mode.setCurrentIndex(idx)
    p.fill_mode.activated.emit(idx)
    layer = doc.active_layer
    assert layer.fill_mode == "offset" and layer.hatch_angle == 0.0 and stack.count() == 1
    assert p.fill_interval.isEnabled() and p.fill_outline.isEnabled()
    assert not p.fill_angle.isEnabled() and not p.fill_bidir.isEnabled()
    assert "Offset-Füllung" in layer_summary(layer)
    p.fill_mode.setCurrentIndex(p.fill_mode.findData("hatch"))
    p.fill_mode.activated.emit(p.fill_mode.currentIndex())
    assert p.fill_angle.isEnabled() and p.fill_bidir.isEnabled()
    stack.undo()
    stack.undo()
    assert doc.active_layer.fill_mode == "none" and not p.fill_interval.isEnabled()


def test_canvas_preview_shows_offset_rings(qapp):
    from lumacut_canvas.editor import CanvasEditor
    doc, _ = _doc("rect")
    ed = CanvasEditor(doc)
    doc.update_layer(doc.active_layer_id, fill_mode="offset", line_interval_mm=1.0)
    ed.fill_preview.rebuild()
    assert ed.fill_preview.line_count() == 40
    ed.grab()
