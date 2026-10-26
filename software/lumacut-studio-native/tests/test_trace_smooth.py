"""Trace „Glätten“ (review round 8): corner-aware Bézier fitting of traced outlines
and centre lines, flattened finely (≤ 0.02 mm) – circles round, corners sharp."""
from __future__ import annotations

import math
import sys
import time
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _pi_guard import pi_check  # noqa: E402

from lumacut_import import trace as trace_mod  # noqa: E402
from lumacut_import.curvefit import find_corners, fit_beziers, flatten, smooth_polyline  # noqa: E402
from lumacut_import.trace import (FLAT_MM, MODE_CENTERLINE, TraceSettings,  # noqa: E402
                                  trace_gray, traced_shapes)

MM = (0.1, 0.1)
SMOOTH = TraceSettings(smoothing_px=0, tolerance_mm=0.05, min_area_mm2=0)
PLAIN = TraceSettings(smoothing_px=0, tolerance_mm=0.05, min_area_mm2=0, smooth_curves=False)


def _blank(h=200, w=200):
    return np.full((h, w), 255, np.uint8)


def _circle_dev(ring, cx, cy):
    p = np.asarray(ring, float)
    r = np.hypot(p[:, 0] - cx, p[:, 1] - cy)
    return float(np.abs(r - r.mean()).max()), float(np.sqrt(((r - r.mean()) ** 2).mean()))


def _max_curvature(pts, closed):
    """Largest discrete curvature (turn angle / mean adjacent chord) – kinks spike."""
    p = np.asarray(pts, float)
    if closed:
        p = np.vstack([p[-1:], p, p[:1]])
    seg = np.diff(p, axis=0)
    ln = np.hypot(seg[:, 0], seg[:, 1])
    ang = np.arctan2(seg[:, 1], seg[:, 0])
    turn = np.abs((np.diff(ang) + np.pi) % (2 * np.pi) - np.pi)
    return float((turn / (0.5 * (ln[:-1] + ln[1:]))).max())


def _dist_line(p, a, b):
    p, a, b = (np.asarray(v, float) for v in (p, a, b))
    d, q = b - a, p - a
    return abs(d[0] * q[1] - d[1] * q[0]) / float(np.hypot(*d))


def test_default_is_on_and_normalized_keeps_it():
    assert TraceSettings().smooth_curves is True
    assert TraceSettings(smooth_curves=0).normalized().smooth_curves is False
    assert FLAT_MM <= 0.02


@pytest.mark.parametrize("r", [8, 25, 60])
def test_circle_is_rounder_with_smoothing(r):
    import cv2
    g = _blank()
    cv2.circle(g, (100, 100), r, 0, -1)
    plain = trace_gray(g, PLAIN, MM)
    smooth = trace_gray(g, SMOOTH, MM)
    assert len(plain.parts) == len(smooth.parts) == 1
    pmax, prms = _circle_dev(plain.parts[0].outer, 100.5, 100.5)
    smax, srms = _circle_dev(smooth.parts[0].outer, 100.5, 100.5)
    assert smax < 0.75 * pmax and srms < 0.6 * prms
    assert smax < 0.5                                 # px (= 0.05 mm)
    # ohne Knicke: Krümmung überall nahe 1/r (Pixeltreppe: Spitzen weit darüber)
    if r >= 25:
        assert _max_curvature(smooth.parts[0].outer, True) < 2.0 / r
        assert _max_curvature(plain.parts[0].outer, True) > 4.0 / r
    # Abflachung ≤ 0,02 mm: Sehnen kurz genug für den Radius
    p = np.asarray(smooth.parts[0].outer)
    chord = np.hypot(*np.diff(np.vstack([p, p[:1]]), axis=0).T).max()
    assert chord ** 2 / (8 * r) <= FLAT_MM / MM[0] + 1e-6


def test_axis_square_keeps_exact_corners():
    g = _blank(100, 100)
    g[20:80, 20:80] = 0
    res = trace_gray(g, SMOOTH)
    ring = res.parts[0].outer
    for corner in ((20, 20), (80, 20), (80, 80), (20, 80)):
        assert min(math.dist(corner, p) for p in ring) < 1e-6
    xs, ys = zip(*ring)
    assert (min(xs), min(ys), max(xs), max(ys)) == pytest.approx((20, 20, 80, 80))


@pytest.mark.parametrize("deg", [17.0, 30.0, 45.0])
def test_rotated_square_corners_stay_sharp(deg):
    import cv2
    from shapely.geometry import Polygon
    a = math.radians(deg)
    c, h = (100.0, 100.0), 50.0
    true = [(c[0] + h * (math.cos(a) * sx - math.sin(a) * sy),
             c[1] + h * (math.sin(a) * sx + math.cos(a) * sy))
            for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
    g = _blank()
    cv2.fillPoly(g, [np.round(np.array(true) * 16).astype(np.int32)], 0, shift=4)
    true_px = [(x + 0.5, y + 0.5) for x, y in true]    # pixel centre = i + 0.5
    plain = trace_gray(g, PLAIN, MM).parts[0].outer
    smooth = trace_gray(g, SMOOTH, MM).parts[0].outer
    ref = Polygon(true_px)
    assert Polygon(smooth).hausdorff_distance(ref) < Polygon(plain).hausdorff_distance(ref)
    assert Polygon(smooth).hausdorff_distance(ref) < 1.0   # 45°: Spitzenpixel ragt ~0,9 px vor
    p = np.asarray(smooth, float)
    assert len(find_corners(p, True)) == 4
    for corner in true_px:                            # Ecke bleibt spitz (keine Rundung)
        assert min(math.dist(corner, q) for q in smooth) < 1.0
    # Kanten bleiben gerade: Punkte nahe der Kantenmitte liegen auf der Geraden
    for i in range(4):
        a0, b0 = true_px[i], true_px[(i + 1) % 4]
        mid = [q for q in smooth if 0.2 * h < math.dist(q, a0) < 1.8 * h
               and 0.2 * h < math.dist(q, b0) < 1.8 * h and _dist_line(q, a0, b0) < 3]
        assert mid and max(_dist_line(q, a0, b0) for q in mid) < 0.5


def test_holes_are_smoothed_and_polygon_stays_valid():
    import cv2
    from shapely.geometry import Polygon
    g = _blank()
    cv2.circle(g, (100, 100), 70, 0, -1)
    cv2.circle(g, (100, 100), 30, 255, -1)
    cv2.circle(g, (150, 100), 8, 255, -1)
    part = trace_gray(g, SMOOTH, MM).parts[0]
    assert len(part.holes) == 2
    assert Polygon(part.outer, part.holes).is_valid
    hole = max(part.holes, key=len)
    assert _circle_dev(hole, 100.5, 100.5)[0] < 0.5


def test_tiny_dots_unchanged_and_curvefit_helpers():
    g = _blank(20, 20)
    g[5, 5] = 0
    res = trace_gray(g, SMOOTH)
    assert len(res.parts) == 1 and len(res.parts[0].outer) >= 3
    # open polyline: ends stay put, pinned point stays
    pts = [(0.0, 0.0), (10.0, 0.4), (20.0, 0.0), (30.0, 0.5), (40.0, 0.0)]
    out = smooth_polyline(pts, False, pinned=(2,))
    assert out[0] == pytest.approx(pts[0]) and out[-1] == pytest.approx(pts[-1])
    assert min(math.dist(pts[2], q) for q in out) < 1e-6
    # quarter circle → wenige Béziers, abgeflacht innerhalb der Toleranz
    t = np.linspace(0, math.pi / 2, 60)
    arc = np.stack([50 * np.cos(t), 50 * np.sin(t)], axis=1)
    bez = fit_beziers(arc, np.array([0.0, 1.0]), np.array([1.0, 0.0]), 0.05)
    assert 1 <= len(bez) <= 3
    flat = np.asarray(flatten(bez, 0.02))
    assert np.abs(np.hypot(flat[:, 0], flat[:, 1]) - 50).max() < 0.1


def test_tolerance_controls_fit_not_flattening():
    import cv2
    g = _blank()
    cv2.ellipse(g, (100, 100), (80, 40), 15, 0, 360, 0, -1)
    fine = trace_gray(g, SMOOTH, MM).parts[0].outer
    coarse = trace_gray(g, TraceSettings(smoothing_px=0, tolerance_mm=0.3, min_area_mm2=0),
                        MM).parts[0].outer
    from shapely.geometry import Polygon
    # gröbere Toleranz bleibt glatt (fein abgeflacht) und innerhalb der Toleranz
    assert _max_curvature(coarse, True) < 2.0 * _max_curvature(fine, True)
    assert Polygon(coarse).hausdorff_distance(Polygon(fine)) < 3.0 + 0.5


# --------------------------------------------------------------- Mittellinie

def _cl(sc, tol=0.05):
    return TraceSettings(smoothing_px=0, tolerance_mm=tol, min_area_mm2=0,
                         mode=MODE_CENTERLINE, smooth_curves=sc)


def test_centerline_ring_is_smooth():
    import cv2
    g = _blank()
    cv2.circle(g, (100, 100), 60, 0, 7)
    plain = trace_gray(g, _cl(False), MM).lines
    smooth = trace_gray(g, _cl(True), MM).lines
    assert len(plain) == len(smooth) == 1
    assert smooth[0][0] == pytest.approx(smooth[0][-1])          # geschlossene Schleife
    assert _circle_dev(smooth[0], 100.5, 100.5)[0] < _circle_dev(plain[0], 100.5, 100.5)[0]
    assert _max_curvature(smooth[0][:-1], True) < 4.0 / 60 < 10.0 / 60 < _max_curvature(plain[0][:-1], True)


def test_centerline_thick_t_junction_has_no_kink():
    import cv2
    g = _blank()
    cv2.line(g, (20, 60), (180, 60), 0, 9)
    cv2.line(g, (100, 60), (100, 180), 0, 9)
    plain = trace_gray(g, _cl(False), MM).lines
    lines = trace_gray(g, _cl(True), MM).lines
    assert len(lines) == 2
    top = max(lines, key=lambda ln: abs(ln[0][0] - ln[-1][0]))
    stem = min(lines, key=lambda ln: abs(ln[0][0] - ln[-1][0]))
    # durchgehender Balken ganz gerade (ohne Glätten: Knick an der Abzweigung)
    assert max(abs(y - 60.5) for _x, y in top) < 0.05
    assert max(len(ln) for ln in plain) > len(top)
    # Abzweig endet genau auf dem Balken
    end = min(stem[0], stem[-1], key=lambda p: p[1])
    assert end == pytest.approx((100.5, 60.5), abs=0.05)
    assert max(abs(x - 100.5) for x, _y in stem) < 0.05


def test_centerline_crossing_strokes_stay_straight():
    import cv2
    A, B = ((20, 30), (200, 190)), ((20, 190), (200, 40))
    segs = [tuple((x + 0.5, y + 0.5) for x, y in s) for s in (A, B)]
    for w in (7, 11):
        g = _blank(220, 220)
        for a, b in (A, B):
            cv2.line(g, a, b, 0, w)
        worst = {}
        for sc in (False, True):
            lines = trace_gray(g, _cl(sc), MM).lines
            worst[sc] = max(min(_dist_line(p, *s) for s in segs) for ln in lines for p in ln)
        assert worst[True] <= worst[False] + 1e-9 and worst[True] < 1.0


def test_large_line_art_with_smoothing_is_fast():
    import cv2
    rng = np.random.default_rng(7)
    g = np.full((1500, 1500), 255, np.uint8)
    for _ in range(150):
        p = rng.integers(0, 1500, 4)
        cv2.line(g, (int(p[0]), int(p[1])), (int(p[2]), int(p[3])), 0, 3)
    t0 = time.perf_counter()
    res = trace_gray(g, _cl(True), MM)
    assert time.perf_counter() - t0 < 15.0 and res.lines


# --------------------------------------------------------- Laufzeit / Hinweis

def test_very_detailed_image_skips_smoothing_with_note(monkeypatch):
    import cv2
    g = _blank()
    cv2.circle(g, (100, 100), 60, 0, -1)
    assert trace_gray(g, SMOOTH, MM).note == ""
    monkeypatch.setattr(trace_mod, "SMOOTH_MAX_RAW_POINTS", 10)
    skipped = trace_gray(g, SMOOTH, MM)
    assert "Glätten übersprungen" in skipped.note
    assert skipped.parts[0].outer == trace_gray(g, PLAIN, MM).parts[0].outer
    assert trace_gray(g, PLAIN, MM).note == ""


def test_smoothing_runtime_on_logo_sized_image():
    import cv2
    g = _blank(2000, 2000)
    for i in range(6):
        for j in range(6):
            cv2.circle(g, (170 + 330 * i, 170 + 330 * j), 140, 0, -1)
            cv2.rectangle(g, (120 + 330 * i, 120 + 330 * j), (220 + 330 * i, 220 + 330 * j),
                          255, -1)
    t0 = time.perf_counter()
    res = trace_gray(g, SMOOTH, MM)
    assert time.perf_counter() - t0 < 10.0
    assert len(res.parts) == 36 and not res.note


# ------------------------------------------------------------------ G-Code / UI

def test_smoothed_trace_gcode_passes_pi_guard(qapp):
    import cv2
    from lumacut_canvas.model import Document, Geometry, ImageSettings, RasterImage, Shape
    from lumacut_job.planner import optimized_document_gcode
    g = _blank(100, 200)
    cv2.circle(g, (50, 50), 35, 0, -1)
    cv2.rectangle(g, (110, 20), (180, 80), 0, -1)
    cv2.circle(g, (145, 50), 15, 255, -1)
    ok, png = cv2.imencode(".png", g)
    img = RasterImage(png.tobytes(), 200, 100, ImageSettings())
    sh = Shape("image", Geometry(10.0, 20.0, 50.0, 25.0), "L1", image=img)   # 0.25 mm/px
    doc = Document()
    for s in traced_shapes(sh, trace_gray(g, SMOOTH, (0.25, 0.25)), doc.active_layer_id):
        doc.add_shape(s)
    gline = _blank(100, 200)
    cv2.circle(gline, (100, 50), 35, 0, 5)
    for s in traced_shapes(sh, trace_gray(gline, _cl(True), (0.25, 0.25)), doc.active_layer_id):
        doc.add_shape(s)
    gcode = optimized_document_gcode(doc)
    assert gcode.count("G1 ") >= 100
    pi_check(gcode)


def test_dialog_has_smooth_checkbox(qapp):
    import cv2
    from PySide6.QtWidgets import QCheckBox
    from lumacut_canvas.model import Geometry, ImageSettings, RasterImage, Shape
    from lumacut_import.trace_qt import TraceDialog
    g = _blank(120, 120)
    cv2.circle(g, (60, 60), 45, 0, -1)
    ok, png = cv2.imencode(".png", g)
    sh = Shape("image", Geometry(0.0, 0.0, 30.0, 30.0), "L1",
               image=RasterImage(png.tobytes(), 120, 120, ImageSettings()))
    dlg = TraceDialog(sh)
    box = dlg.findChild(QCheckBox, "trace_smooth")
    assert box is dlg.smooth_curves and box.isChecked() and dlg.settings().smooth_curves
    assert box.text().startswith("Glätten") and "Ecken" in box.toolTip()
    n_smooth = int(dlg.info.text().split(", ")[1].split()[0])
    box.setChecked(False)
    assert dlg._timer.isActive()                      # Vorschau wird neu berechnet
    dlg.update_preview()
    assert dlg.settings().smooth_curves is False
    n_plain = int(dlg.info.text().split(", ")[1].split()[0])
    assert n_plain != n_smooth
    dlg.deleteLater()
    off = TraceDialog(sh, TraceSettings(smooth_curves=False))
    assert not off.smooth_curves.isChecked()
    off.deleteLater()
