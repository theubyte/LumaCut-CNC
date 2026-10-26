"""Vektor-Füllung (Schraffur/Kreuzschraffur) je Ebene: Geometrie, Datei, G-Code, Panel."""

from __future__ import annotations

import math
import re

import pytest

from lumacut_canvas import hatch
from lumacut_canvas.hatch import fill_segments, hatch_lines, segments_length

SQUARE = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]
HOLE = [(3.0, 3.0), (7.0, 3.0), (7.0, 7.0), (3.0, 7.0)]


def _inside(pt, poly):
    from lumacut_job.planner import point_in_polygon
    return point_in_polygon(pt, poly)


def _mid(seg):
    (ax, ay), (bx, by) = seg
    return ((ax + bx) / 2, (ay + by) / 2)


# --- Geometrie ------------------------------------------------------------------

def test_square_line_count_and_length():
    segs = hatch_lines([SQUARE], 1.0, 0.0)
    assert len(segs) == 10
    assert all(abs(a[1] - b[1]) < 1e-9 for a, b in segs)        # waagerecht
    assert [round(a[1], 6) for a, _ in segs] == [k + 0.5 for k in range(10)]
    assert segments_length(segs) == pytest.approx(100.0)          # Fläche / Abstand


@pytest.mark.parametrize("angle", [0, 30, 45, 90, 135, 170])
def test_lines_stay_inside_and_cover_area(angle):
    segs = hatch_lines([SQUARE], 0.5, angle)
    assert segs
    for a, b in segs:
        for x, y in (a, b):
            assert -1e-6 <= x <= 10 + 1e-6 and -1e-6 <= y <= 10 + 1e-6
        assert _inside(_mid((a, b)), SQUARE)
        d = (b[0] - a[0], b[1] - a[1])
        # Richtung = Winkel gegen den Uhrzeigersinn auf dem Bildschirm (y nach unten)
        ang = math.degrees(math.atan2(-d[1], d[0])) % 180
        assert min(abs(ang - angle % 180), 180 - abs(ang - angle % 180)) < 1e-6
    assert segments_length(segs) == pytest.approx(100.0 / 0.5, rel=0.03)


def test_even_odd_keeps_holes_free():
    segs = hatch_lines([SQUARE, HOLE], 1.0, 0.0)
    assert len(segs) == 14     # 6 volle Zeilen + 4 Zeilen mit je 2 Stücken
    for seg in segs:
        m = _mid(seg)
        assert _inside(m, SQUARE) and not _inside(m, HOLE)
    assert segments_length(segs) == pytest.approx(100.0 - 16.0)


def test_bidirectional_alternates_and_unidirectional_does_not():
    bi = hatch_lines([SQUARE], 1.0, 0.0, bidirectional=True)
    assert [a[0] < b[0] for a, b in bi[:4]] == [True, False, True, False]
    uni = hatch_lines([SQUARE], 1.0, 0.0, bidirectional=False)
    assert all(a[0] < b[0] for a, b in uni)


def test_crosshatch_adds_perpendicular_set():
    single = fill_segments([SQUARE], "hatch", 1.0, 0.0)
    cross = fill_segments([SQUARE], "crosshatch", 1.0, 0.0)
    assert len(cross) == 2 * len(single)
    vertical = [s for s in cross if abs(s[0][0] - s[1][0]) < 1e-6]
    assert len(vertical) == 10
    assert fill_segments([SQUARE], "none", 1.0) == []
    with pytest.raises(ValueError):
        fill_segments([SQUARE], "zickzack", 1.0)


def test_degenerate_input_and_limits():
    assert hatch_lines([], 1.0) == []
    assert hatch_lines([[(0, 0), (5, 5)]], 1.0) == []           # offen/zu wenige Punkte
    with pytest.raises(ValueError):
        hatch_lines([SQUARE], 0.0)
    with pytest.raises(ValueError):
        hatch_lines([[(0, 0), (1e5, 0), (1e5, 1e5), (0, 1e5)]], 0.05)   # zu viele Linien


def test_normalize_angle():
    assert hatch.normalize_angle_180(180) == 0.0
    assert hatch.normalize_angle_180(-45) == 135.0
    assert hatch.normalize_angle_180(225) == 45.0


# --- Formen aus dem Dokument -----------------------------------------------------

def _doc(kind="rect", **layer):
    from lumacut_canvas.model import Document, Geometry, Shape
    doc = Document()
    lid = doc.active_layer_id
    doc.update_layer(lid, **layer)
    if kind == "text":
        s = Shape("text", Geometry(20, 20, 40, 15), lid, text="OBA")
    elif kind == "polygon":
        s = Shape("polygon", Geometry(20, 20, 30, 30), lid,
                  points=[(0.0, 0.0), (1.0, 0.0), (0.5, 1.0)])
    else:
        s = Shape(kind, Geometry(20, 20, 30, 20), lid)
    doc.add_shape(s)
    return doc, s


@pytest.mark.parametrize("kind", ["rect", "ellipse", "polygon", "text"])
def test_closed_shapes_are_filled_inside_their_outline(qapp, kind):
    from lumacut_canvas.export import shape_fill_segments
    from lumacut_canvas.shape_paths import shape_path
    doc, s = _doc(kind, fill_mode="hatch", line_interval_mm=0.5)
    segs = shape_fill_segments(s, doc.active_layer)
    assert segs
    path = shape_path(s)
    from PySide6.QtCore import QPointF
    for seg in segs:
        assert path.contains(QPointF(*_mid(seg))) or kind == "text"
    b = path.boundingRect()
    for a, c in segs:
        for x, y in (a, c):
            assert b.left() - 1e-3 <= x <= b.right() + 1e-3
            assert b.top() - 1e-3 <= y <= b.bottom() + 1e-3


def test_text_holes_stay_free(qapp):
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QPainterPath
    from lumacut_canvas.export import shape_fill_segments
    from lumacut_canvas.shape_paths import shape_path
    doc, s = _doc("text", fill_mode="hatch", line_interval_mm=0.3)
    path = shape_path(s)
    path.setFillRule(__import__("PySide6.QtCore", fromlist=["Qt"]).Qt.OddEvenFill)
    segs = shape_fill_segments(s, doc.active_layer)
    assert segs
    inside = sum(path.contains(QPointF(*_mid(seg))) for seg in segs)
    assert inside / len(segs) > 0.97     # Mitten liegen im Glyphen, nicht im Loch


def test_rotated_rect_hatch_follows_rotation(qapp):
    from lumacut_canvas.export import shape_fill_segments
    from lumacut_canvas.shape_paths import shape_path
    from PySide6.QtCore import QPointF
    doc, s = _doc("rect", fill_mode="hatch", line_interval_mm=0.5)
    s.geom.rot = 30.0
    segs = shape_fill_segments(s, doc.active_layer)
    path = shape_path(s)
    assert segs and all(path.contains(QPointF(*_mid(seg))) for seg in segs)
    assert segments_length(segs) == pytest.approx(30 * 20 / 0.5, rel=0.03)


def test_open_shapes_are_not_filled(qapp):
    from lumacut_canvas.export import shape_fill_segments
    doc, s = _doc("line", fill_mode="hatch")
    assert shape_fill_segments(s, doc.active_layer) == []


# --- Datei ------------------------------------------------------------------------

def test_fill_fields_roundtrip_and_old_files_load():
    from lumacut_canvas.model import Document, Layer
    plain = Layer("A").to_dict()
    assert not any(k in plain for k in ("fill_mode", "line_interval_mm", "hatch_angle"))
    old = Layer.from_dict({"name": "Alt", "power": 30})
    assert old.fill_mode == "none" and old.line_interval_mm == hatch.DEFAULT_INTERVAL_MM
    l = Layer.from_dict({**plain, "fill_mode": "crosshatch", "line_interval_mm": 0.01,
                         "hatch_angle": -30, "hatch_outline": False})
    assert (l.fill_mode, l.line_interval_mm, l.hatch_angle, l.hatch_outline) == \
        ("crosshatch", 0.05, 150.0, False)
    assert Layer.from_dict(l.to_dict()) == l
    assert Layer.from_dict({"name": "x", "fill_mode": "unsinn"}).fill_mode == "none"
    doc, _ = _doc("rect", fill_mode="hatch", hatch_angle=45)
    d = doc.to_dict()
    data = d["layers"][0]
    assert data["fill_mode"] == "hatch" and data["hatch_angle"] == 45.0
    assert d["version"] == Document.VERSION_WITHOUT_IMAGES   # keine Versionsänderung nötig
    again = Document.from_dict(d)
    assert again.layers[0].fill_mode == "hatch" and again.layers[0].hatch_angle == 45.0


# --- G-Code -----------------------------------------------------------------------

def _moves(gcode):
    return [l for l in gcode.splitlines() if l.startswith(("G0 ", "G1 "))]


def test_gcode_without_fill_unchanged(qapp):
    from lumacut_canvas.export import job_layers
    from lumacut_canvas.gcode import document_to_gcode
    doc, _ = _doc("rect")
    assert job_layers(doc)[0].fills == []
    g = document_to_gcode(doc)
    assert len(_moves(g)) == 1 + 4    # G0 + vier Seiten


def test_gcode_hatch_uses_layer_power_speed_passes(qapp):
    from lumacut_canvas.gcode import document_to_gcode
    doc, _ = _doc("rect", fill_mode="hatch", line_interval_mm=1.0, power=40, speed=2400, passes=2)
    g = document_to_gcode(doc)
    g1 = [l for l in g.splitlines() if l.startswith("G1 ")]
    assert all(l.endswith("F2400 S102") for l in g1)
    # 20 mm hoch / 1 mm = 20 Linien + 4 Kontur-Seiten, zweimal
    assert len(g1) == 2 * (20 + 4)
    # je Durchgang erst Füllung, dann Kontur
    p1 = g.split("; PASS 2 OF 2")[0]
    first = _moves(p1.split("; PASS 1 OF 2")[1])
    assert all(m.startswith(("G0", "G1")) for m in first)
    xs = [float(re.search(r"Y([-\d.]+)", m).group(1)) for m in first[:40:2]]
    assert len(set(round(x, 3) for x in xs)) == 20   # 20 verschiedene Zeilen zuerst


def test_gcode_fill_only_and_crosshatch(qapp):
    from lumacut_canvas.gcode import document_to_gcode
    doc, _ = _doc("rect", fill_mode="crosshatch", line_interval_mm=1.0, hatch_outline=False)
    g1 = [l for l in document_to_gcode(doc).splitlines() if l.startswith("G1 ")]
    assert len(g1) == 20 + 30     # waagerecht 20, senkrecht 30, keine Kontur


def test_gcode_pass_hook_runs_for_fill_only_layers(qapp):
    from lumacut_canvas.export import job_layers
    from lumacut_canvas.gcode import depth_comment_hook, layers_to_gcode
    doc, _ = _doc("rect", fill_mode="hatch", hatch_outline=False, line_interval_mm=1.0,
                  material="Pappel", thickness_mm=3.0, depth_per_pass_mm=1.0, passes=3)
    layers = job_layers(doc)
    assert layers[0].polylines == [] and layers[0].fills
    g = layers_to_gcode(layers, depth_comment_hook)
    assert g.count("; DEPTH") == layers[0].passes == len(layers[0].pass_depths_mm)


def test_planner_keeps_fill_blocks(qapp):
    from lumacut_job.planner import optimized_document_gcode
    from lumacut_canvas.gcode import document_to_gcode
    doc, _ = _doc("rect", fill_mode="hatch", line_interval_mm=1.0)
    opt = optimized_document_gcode(doc)
    assert len([l for l in opt.splitlines() if l.startswith("G1 ")]) == \
        len([l for l in document_to_gcode(doc).splitlines() if l.startswith("G1 ")])


def test_fill_blocks_reverse_when_end_is_closer():
    from lumacut_canvas.gcode import order_fill_blocks
    b1 = [((0, 0), (1, 0)), ((1, 1), (0, 1))]
    b2 = [((10, 0), (11, 0)), ((11, 5), (20, 5))]
    assert order_fill_blocks([b1, b2], pos=(0, 0)) == [b1, b2]
    assert order_fill_blocks([b2], pos=(21, 5)) == [[((20, 5), (11, 5)), ((11, 0), (10, 0))]]
    assert order_fill_blocks([b2, []], pos=None) == [b2]


# --- Ebenen-Panel, Undo, Vorschau ---------------------------------------------------

def _panel(doc):
    from PySide6.QtGui import QUndoStack
    from lumacut_canvas.layers_panel import LayersPanel
    stack = QUndoStack()
    return LayersPanel(doc, stack), stack


def test_panel_fill_mode_is_one_undo_step(qapp):
    doc, _ = _doc("rect")
    p, stack = _panel(doc)
    assert not p.fill_interval.isEnabled()
    p.fill_mode.setCurrentIndex(p.fill_mode.findData("crosshatch"))
    p.fill_mode.activated.emit(p.fill_mode.currentIndex())
    layer = doc.active_layer
    assert layer.fill_mode == "crosshatch" and layer.hatch_angle == 45.0
    assert stack.count() == 1 and p.fill_interval.isEnabled()
    stack.undo()
    assert doc.active_layer.fill_mode == "none" and doc.active_layer.hatch_angle == 0.0
    stack.redo()
    assert doc.active_layer.fill_mode == "crosshatch"


def test_panel_interval_angle_and_flags(qapp):
    doc, _ = _doc("rect", fill_mode="hatch")
    p, stack = _panel(doc)
    p.fill_interval.setValue(0.5)
    p.fill_interval.setValue(0.6)          # aufeinanderfolgende Änderungen = ein Schritt
    assert doc.active_layer.line_interval_mm == 0.6 and stack.count() == 1
    assert "Linienabstand" in stack.text(0)
    p.fill_angle.setValue(30)
    assert doc.active_layer.hatch_angle == 30.0
    p.fill_outline.click()
    assert doc.active_layer.hatch_outline is False
    stack.undo()
    assert doc.active_layer.hatch_outline is True
    from lumacut_canvas.layers_panel import layer_summary
    assert "Schraffur" in layer_summary(doc.active_layer)


def test_canvas_preview_follows_document(qapp):
    from lumacut_canvas.editor import CanvasEditor
    from lumacut_canvas.fill_preview import OVERLAY_KEY
    doc, _ = _doc("rect")
    ed = CanvasEditor(doc)
    fp = ed.fill_preview
    assert ed.overlay(OVERLAY_KEY) is None and fp.line_count() == 0
    doc.update_layer(doc.active_layer_id, fill_mode="hatch", line_interval_mm=1.0)
    fp.rebuild()                         # sonst nach DEBOUNCE_MS
    assert fp.line_count() == 20 and ed.overlay(OVERLAY_KEY) is fp
    doc.update_layer(doc.active_layer_id, visible=False)
    fp.rebuild()
    assert fp.line_count() == 0 and ed.overlay(OVERLAY_KEY) is None
    ed.grab()                            # Zeichnen ohne Fehler


def test_svg_png_show_fill(qapp, tmp_path):
    from lumacut_canvas.export import export_png, export_svg
    doc, _ = _doc("rect", fill_mode="hatch", line_interval_mm=1.0)
    export_svg(doc, tmp_path / "a.svg")
    export_svg(doc, tmp_path / "b.svg", show_fill=True)
    assert (tmp_path / "b.svg").stat().st_size > (tmp_path / "a.svg").stat().st_size
    plain = export_png(doc, tmp_path / "a.png", px_per_mm=4)
    filled = export_png(doc, tmp_path / "b.png", px_per_mm=4, show_fill=True)
    # Mitte des Rechtecks (35, 30 mm) ist nur mit Schraffur gefärbt – irgendwo in der Zeile
    def row_ink(img):
        y = int(30.5 * 4)
        return sum(img.pixelColor(x, y) != img.pixelColor(0, 0) for x in range(84, 196))
    assert row_ink(filled) > row_ink(plain)
