"""Glatte Kreise und Ellipsen (Anforderungen 2026-10-26 §9.3).

Gemessen wird die größte Abweichung der Polylinie (Stützpunkte *und*
Sehnenmitten) von der echten Ellipse – im G-Code, in der Schraffur, bei
Boole/Versatz, im SVG-Export, bei der Knoten-Umwandlung und beim SVG-Import.
"""
from __future__ import annotations

import math
import re

import pytest

from _pi_guard import pi_check
from lumacut_canvas import pathops
from lumacut_canvas.model import Document, Geometry, Layer, Shape
from lumacut_canvas.shape_paths import (FLATTEN_TOL_MM, MIN_ELLIPSE_SEGMENTS, ellipse_segments,
                                        shape_path, shape_polygons)
from lumacut_canvas.workarea import from_machine

TOL = 0.02


def ellipse_distance(p, cx, cy, a, b, rot_deg=0.0) -> float:
    """Abstand eines Punkts zur Ellipse (Mitte, Halbachsen, Drehung im Uhrzeigersinn)."""
    r = math.radians(rot_deg)
    dx, dy = p[0] - cx, p[1] - cy
    u, v = dx * math.cos(r) + dy * math.sin(r), -dx * math.sin(r) + dy * math.cos(r)

    def d(t):
        return math.hypot(u - a * math.cos(t), v - b * math.sin(t))
    n = 720
    t = min((2 * math.pi * i / n for i in range(n)), key=d)
    h = 2 * math.pi / n
    for _ in range(60):  # goldener Schnitt um das beste Raster-t
        lo, hi = t - h, t + h
        m1, m2 = lo + (hi - lo) * 0.382, lo + (hi - lo) * 0.618
        if d(m1) < d(m2):
            hi = m2
        else:
            lo = m1
        t, h = (lo + hi) / 2, (hi - lo) / 2
    return d(t)


def max_deviation(poly, *ell) -> float:
    pts = list(poly)
    probe = pts + [((p[0] + q[0]) / 2, (p[1] + q[1]) / 2) for p, q in zip(pts, pts[1:])]
    return max(ellipse_distance(p, *ell) for p in probe)


def ell_of(g: Geometry):
    return (g.x + g.w / 2, g.y + g.h / 2, g.w / 2, g.h / 2, g.rot)


CASES = [Geometry(10, 10, 2, 2), Geometry(10, 10, 20, 20), Geometry(50, 40, 100, 100),
         Geometry(0, 0, 360, 340), Geometry(30, 60, 300, 40, 37.0), Geometry(100, 100, 7, 55, -120.0)]


def test_segment_count_rule():
    for r in (0.01, 0.5, 1, 10, 50, 180):
        n = ellipse_segments(r, r / 2)
        assert n >= MIN_ELLIPSE_SEGMENTS and n % 4 == 0
        assert r * (1 - math.cos(math.pi / n)) <= FLATTEN_TOL_MM + 1e-12
    assert ellipse_segments(1, 1) == 64
    assert ellipse_segments(180, 170) == 212  # Ø 360 mm: gut 200 Segmente, nicht Tausende


@pytest.mark.parametrize("g", CASES, ids=lambda g: f"{g.w}x{g.h}r{g.rot}")
def test_flattened_ellipse_within_tolerance(qapp, g):
    s = Shape("ellipse", g, "L")
    (poly,) = shape_polygons(s)
    assert poly[0] == poly[-1] and len(poly) - 1 >= 64
    assert max_deviation(poly, *ell_of(g)) <= TOL


def test_scaled_and_rotated_ellipse_after_editing(qapp):
    doc = Document()
    s = doc.add_shape(Shape("ellipse", Geometry(10, 10, 20, 10), doc.active_layer_id))
    doc.set_geometry(s.id, Geometry(5, 5, 250, 90, 63.0))  # wie Skalieren + Drehen im Editor
    g = doc.shape(s.id).geom if hasattr(doc, "shape") else doc.shapes[0].geom
    (poly,) = shape_polygons(doc.shapes[0])
    assert max_deviation(poly, *ell_of(g)) <= TOL


def _gcode_xy(gcode: str):
    pts = []
    for line in gcode.splitlines():
        m = re.match(r"G1 .*X(-?[\d.]+) Y(-?[\d.]+)", line)
        if m:
            pts.append(from_machine(float(m.group(1)), float(m.group(2))))
    return pts


def test_gcode_circle_smooth_no_arcs_and_compact(qapp):
    from lumacut_job.planner import optimized_document_gcode
    doc = Document()
    g = Geometry(80, 70, 150, 90, 25.0)
    doc.add_shape(Shape("ellipse", g, doc.active_layer_id))
    gcode = optimized_document_gcode(doc)
    pi_check(gcode)
    assert not re.search(r"^G[23]\b", gcode, re.M)  # Pi: Höhenausgleich/smart_cam lehnen Bögen ab
    pts = _gcode_xy(gcode)
    assert 64 <= len(pts) <= 300
    # Rundung auf 0,001 mm im G-Code eingerechnet
    assert max_deviation(pts, *ell_of(g)) <= TOL + 0.001
    # Größe im Rahmen: Ø 360 mm-Kreis < 300 Bewegungen, < 10 kB
    big = Document()
    big.add_shape(Shape("ellipse", Geometry(0, 0, 360, 340), big.active_layer_id))
    gc = optimized_document_gcode(big)
    assert len(_gcode_xy(gc)) < 300 and len(gc) < 10_000


def test_job_layers_use_smooth_polylines(qapp):
    from lumacut_canvas.export import job_layers
    doc = Document()
    g = Geometry(10, 10, 2, 2)
    doc.add_shape(Shape("ellipse", g, doc.active_layer_id))
    (layer,) = job_layers(doc)
    (poly,) = layer.polylines
    pts = [from_machine(*p) for p in poly]
    assert len(pts) - 1 >= 64 and max_deviation(pts, *ell_of(g)) <= TOL


def test_hatch_clipped_at_true_circle(qapp):
    from lumacut_canvas.export import shape_fill_segments
    layer = Layer(name="F")
    layer.fill_mode = "hatch"
    layer.line_interval_mm = 0.5
    g = Geometry(20, 20, 60, 60)
    segs = shape_fill_segments(Shape("ellipse", g, layer.id), layer)
    assert len(segs) > 50
    ends = [p for seg in segs for p in seg]
    assert max(ellipse_distance(p, *ell_of(g)) for p in ends) <= TOL


def test_offset_and_boolean_stay_round(qapp):
    doc = Document()
    L = doc.active_layer_id
    c = Shape("ellipse", Geometry(50, 50, 40, 40), L)
    (out,) = pathops.offset([c], 30.0)
    ring = out.abs_points()
    assert max_deviation(ring + ring[:1], 70, 70, 50, 50) <= TOL
    (inner,) = pathops.offset([c], -5.0)
    ring = inner.abs_points()
    assert max_deviation(ring + ring[:1], 70, 70, 15, 15) <= TOL
    # runde Ecken beim Versatz eines Rechtecks: Bogen um die Ecke, Radius 40
    r = Shape("rect", Geometry(100, 100, 50, 30), L)
    (big,) = pathops.offset([r], 40.0, "round")
    corner = [p for p in big.abs_points() if p[0] < 100 and p[1] < 100]
    assert len(corner) > 20
    assert max(abs(math.dist(p, (100, 100)) - 40) for p in corner) <= TOL
    # Vereinigung zweier Kreise: jeder Punkt liegt auf einem der beiden Kreise
    a = Shape("ellipse", Geometry(0, 0, 40, 40), L)
    b = Shape("ellipse", Geometry(25, 0, 40, 40), L)
    (u,) = pathops.boolean([a, b], "union")
    for p in u.abs_points():
        assert min(ellipse_distance(p, 20, 20, 20, 20), ellipse_distance(p, 45, 20, 20, 20)) <= TOL


def test_display_and_svg_use_true_curves(qapp, tmp_path):
    from PySide6.QtGui import QTransform
    from lumacut_canvas.export import export_svg
    g = Geometry(0, 0, 360, 340, 30.0)
    s = Shape("ellipse", g, "L")
    path = shape_path(s)
    k = 1000.0  # sehr fein abflachen → misst nur den Formfehler der Bézierbögen
    (poly,) = path.toSubpathPolygons(QTransform.fromScale(k, k))
    pts = [(p.x() / k, p.y() / k) for p in poly][::7]
    assert max(ellipse_distance(p, *ell_of(g)) for p in pts) <= 0.002
    doc = Document()
    doc.add_shape(Shape("ellipse", Geometry(10, 10, 300, 200), doc.active_layer_id))
    f = tmp_path / "e.svg"
    export_svg(doc, f)
    d = re.search(r'<path[^>]* d="([^"]+)"', f.read_text()).group(1)
    assert d.count("C") == 8 and "L" not in d  # echte Kurven, keine Polylinie


def test_node_conversion_keeps_circle_round(qapp):
    from lumacut_canvas import nodes
    for g in (Geometry(0, 0, 40, 40), Geometry(0, 0, 360, 360), Geometry(0, 0, 200, 100, 20.0)):
        e = Shape("ellipse", g, "L")
        pe = nodes.to_editable(e)
        assert 16 <= len(pe.points) <= 32
        (poly,) = shape_polygons(pe, tol=0.002)
        assert max(ellipse_distance(p, *ell_of(g)) for p in poly) <= TOL + 0.002


def test_svg_import_circle_within_tolerance(qapp, tmp_path):
    from lumacut_import import import_file
    f = tmp_path / "c.svg"
    f.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="200mm" height="200mm" '
                 'viewBox="0 0 200 200"><circle cx="100" cy="100" r="80"/></svg>')
    res = import_file(f, "L1")
    (s,) = res.shapes
    b = s.bounds()
    pts = s.abs_points()
    assert len(pts) >= 64
    ell = (b.x + b.w / 2, b.y + b.h / 2, b.w / 2, b.h / 2)
    assert max_deviation(pts + pts[:1], *ell) <= TOL + 1e-6
