"""Centre-line trace (review round 7): thinning, skeleton graph, canvas paths, dialog."""
from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _pi_guard import pi_check  # noqa: E402

from lumacut_import.centerline import skeleton_lines, thin  # noqa: E402
from lumacut_import.trace import (MODE_CENTERLINE, MODE_OUTLINE, TraceSettings,  # noqa: E402
                                  trace_gray, traced_shapes)

CL = TraceSettings(smoothing_px=0, tolerance_mm=0.05, min_area_mm2=0, mode=MODE_CENTERLINE)
MM = (0.1, 0.1)


def _blank(h=200, w=200):
    return np.full((h, w), 255, np.uint8)


def _dist_to_segment(p, a, b):
    p, a, b = (np.asarray(v, float) for v in (p, a, b))
    t = np.clip(np.dot(p - a, b - a) / np.dot(b - a, b - a), 0, 1)
    return float(np.linalg.norm(p - (a + t * (b - a))))


def _length(line):
    return sum(np.hypot(line[i + 1][0] - line[i][0], line[i + 1][1] - line[i][1])
               for i in range(len(line) - 1))


def test_mode_setting_is_normalized_and_default_is_outline():
    assert TraceSettings().mode == MODE_OUTLINE
    assert TraceSettings(mode="bogus").normalized().mode == MODE_OUTLINE
    assert TraceSettings(mode=MODE_CENTERLINE).normalized().mode == MODE_CENTERLINE


def test_thin_gives_one_pixel_connected_skeleton():
    import cv2
    g = _blank()
    cv2.putText(g, "Ab8", (5, 150), cv2.FONT_HERSHEY_SIMPLEX, 4, 0, 10)
    mask = g < 128
    sk = thin(mask)
    assert sk.any() and not (sk.astype(bool) & ~mask).any()      # inside the strokes
    # no 2×2 block of skeleton pixels left (one pixel wide)
    blocks = sk[:-1, :-1] & sk[1:, :-1] & sk[:-1, 1:] & sk[1:, 1:]
    assert not blocks.any()
    # topology kept: same number of 8-connected pieces as the strokes
    n_mask = cv2.connectedComponents(mask.astype(np.uint8), connectivity=8)[0]
    n_skel = cv2.connectedComponents(sk.astype(np.uint8), connectivity=8)[0]
    assert n_mask == n_skel


def test_thick_straight_stroke_becomes_one_centre_line():
    import cv2
    g = _blank(100, 200)
    cv2.line(g, (10, 50), (190, 50), 0, 7)
    res = trace_gray(g, CL, MM)
    assert res.parts == [] and len(res.lines) == 1
    line = res.lines[0]
    assert len(line) == 2                            # simplified to one segment
    assert all(abs(y - 50.5) < 0.6 for _x, y in line)
    assert _length(line) == pytest.approx(180, abs=8)


def test_crossing_strokes_stay_two_lines_and_spurs_are_pruned():
    import cv2
    g = _blank()
    cv2.line(g, (20, 100), (180, 100), 0, 6)
    cv2.line(g, (100, 20), (100, 180), 0, 6)
    res = trace_gray(g, CL, MM)
    assert len(res.lines) == 2
    for line in res.lines:
        a, b = line[0], line[-1]
        assert _length(line) > 150                  # not split at the crossing
        assert all(_dist_to_segment(p, a, b) < 1.0 for p in line)


def test_t_and_y_junctions_keep_every_branch():
    import cv2
    g = _blank()
    cv2.line(g, (20, 20), (180, 180), 0, 5)
    cv2.line(g, (20, 180), (100, 100), 0, 5)
    res = trace_gray(g, CL, MM)
    assert len(res.lines) == 2                       # through-line + one branch
    total = sum(_length(line) for line in res.lines)
    assert total == pytest.approx(2 * 160 * 2 ** 0.5 * 0.75, rel=0.08)
    ends = [p for line in res.lines for p in (line[0], line[-1])]
    for corner in ((20.5, 20.5), (180.5, 180.5), (20.5, 180.5)):
        assert min(np.hypot(p[0] - corner[0], p[1] - corner[1]) for p in ends) < 5


def test_ring_becomes_closed_line_on_the_circle():
    import cv2
    g = _blank()
    cv2.circle(g, (100, 100), 60, 0, 6)
    res = trace_gray(g, CL, MM)
    assert len(res.lines) == 1
    ring = res.lines[0]
    assert ring[0] == ring[-1] and len(ring) > 20
    radii = [np.hypot(x - 100.5, y - 100.5) for x, y in ring]
    assert min(radii) > 58.5 and max(radii) < 61.5


def test_specks_removed_and_tolerance_reduces_points():
    import cv2
    g = _blank()
    cv2.ellipse(g, (100, 100), (80, 40), 15, 0, 300, 0, 4)
    g[5, 5] = 0
    g[190:192, 190:192] = 0
    raw = trace_gray(g, TraceSettings(smoothing_px=0, tolerance_mm=0, min_area_mm2=0,
                                      mode=MODE_CENTERLINE, smooth_curves=False), MM)
    clean = trace_gray(g, TraceSettings(smoothing_px=0, tolerance_mm=0, min_area_mm2=0.1,
                                        mode=MODE_CENTERLINE, smooth_curves=False), MM)
    assert len(clean.lines) == 1 and clean.removed == 2
    assert len(raw.lines) == 1                       # single dots have no line
    coarse = trace_gray(g, TraceSettings(smoothing_px=0, tolerance_mm=0.2, min_area_mm2=0.1,
                                         mode=MODE_CENTERLINE, smooth_curves=False), MM)
    assert coarse.point_count < clean.point_count / 2


def test_skeleton_lines_on_plain_pixel_graph():
    sk = np.zeros((20, 30), np.uint8)
    sk[10, 2:28] = 1                                 # horizontal line
    sk[3:10, 15] = 1                                 # branch up from the middle
    lines = skeleton_lines(sk)
    assert len(lines) == 2 and not any(closed for _l, closed in lines)
    lengths = sorted(_length(line) for line, _c in lines)
    assert lengths == pytest.approx([7, 25], abs=1.0)


def test_canvas_paths_open_and_fill_safe(qapp):
    import cv2
    from lumacut_canvas.model import Document, Geometry, ImageSettings, RasterImage, Shape
    from lumacut_job.planner import optimized_document_gcode
    g = _blank(100, 200)
    cv2.line(g, (10, 30), (190, 30), 0, 5)
    cv2.circle(g, (100, 65), 25, 0, 4)
    ok, png = cv2.imencode(".png", g)
    img = RasterImage(png.tobytes(), 200, 100, ImageSettings())
    sh = Shape("image", Geometry(10.0, 20.0, 50.0, 25.0), "L1", image=img)   # 0.25 mm/px
    res = trace_gray(g, CL, (0.25, 0.25))
    shapes = traced_shapes(sh, res, "L1")
    assert len(shapes) == 2 and all(s.kind == "path" for s in shapes)
    assert shapes[0].groups and shapes[0].groups == shapes[1].groups
    line = min(shapes, key=lambda s: s.bounds().h)
    b = line.bounds()
    assert b.y == pytest.approx(20 + 30.5 * 0.25, abs=0.2) and b.w == pytest.approx(45, abs=2)
    doc = Document()
    for s in traced_shapes(sh, res, doc.active_layer_id):
        doc.add_shape(s)
    gcode = optimized_document_gcode(doc)
    assert gcode.count("G1 ") >= 10
    pi_check(gcode)


def test_large_line_art_is_fast_and_blobs_do_not_hang():
    import cv2
    rng = np.random.default_rng(7)
    g = np.full((1500, 1500), 255, np.uint8)
    for _ in range(150):
        p = rng.integers(0, 1500, 4)
        cv2.line(g, (int(p[0]), int(p[1])), (int(p[2]), int(p[3])), 0, int(rng.integers(2, 10)))
    t = time.monotonic()
    res = trace_gray(g, CL, MM)
    assert time.monotonic() - t < 15 and res.lines
    blob = np.full((1500, 1500), 255, np.uint8)
    blob[50:1450, 50:1450] = 0
    t = time.monotonic()
    try:
        trace_gray(blob, CL, MM, time_limit_s=1.0)
    except ValueError as exc:
        assert "Flächen" in str(exc)
    assert time.monotonic() - t < 6


# ---------------------------------------------------------------- dialog / window


@pytest.fixture()
def win(qapp, tmp_path):
    from PySide6.QtCore import QSettings
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(tmp_path))
    QSettings.setDefaultFormat(QSettings.IniFormat)
    main = pytest.importorskip("main")
    w = main.LumaCutStudio()
    w.import_tools.interactive = False
    yield w
    w.canvas.undo_stack.setClean()
    w.close()


def _sketch_png(tmp_path):
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QColor, QImage, QPainter, QPen
    img = QImage(200, 100, QImage.Format_RGB32)
    img.fill(QColor(255, 255, 255))
    p = QPainter(img)
    pen = QPen(QColor(0, 0, 0))
    pen.setWidth(5)
    pen.setCapStyle(Qt.FlatCap)
    p.setPen(pen)
    p.drawLine(20, 50, 180, 50)
    p.end()
    img.setDotsPerMeterX(round(254 / 0.0254))   # 0.1 mm per pixel
    img.setDotsPerMeterY(round(254 / 0.0254))
    path = tmp_path / "skizze.png"
    img.save(str(path))
    return path


def test_dialog_mode_switch_and_trace_into_document(win, tmp_path):
    from lumacut_import.trace_qt import TraceDialog
    tools = win.import_tools
    (img_id,) = tools.import_path(_sketch_png(tmp_path))
    dlg = TraceDialog(win.canvas.document.shape(img_id))
    assert dlg.settings().mode == MODE_OUTLINE and "1 Kontur" in dlg.info.text()
    dlg.mode.setCurrentIndex(dlg.mode.findData(MODE_CENTERLINE))
    dlg.update_preview()
    st = dlg.settings()
    assert st.mode == MODE_CENTERLINE and "1 Linie" in dlg.info.text() and dlg.ok_button.isEnabled()
    dlg.deleteLater()
    ids = tools.trace_image(img_id, st, delete_image=False)
    assert len(ids) == 1
    sh = win.canvas.document.shape(ids[0])
    b = sh.bounds()
    ib = win.canvas.document.shape(img_id).bounds()
    assert sh.kind == "path"
    assert (b.x - ib.x, b.y - ib.y, b.w) == pytest.approx((2.05, 5.05, 15.9), abs=0.35)
    assert win.canvas.undo_stack.undoText() == "Bild nachzeichnen"


def test_dialog_hint_for_filled_areas(win, tmp_path):
    from lumacut_import.trace_qt import TraceDialog
    from PySide6.QtGui import QColor, QImage
    img = QImage(60, 60, QImage.Format_RGB32)
    img.fill(QColor(255, 255, 255))
    for x in range(20, 40):
        for y in range(20, 40):
            img.setPixelColor(x, y, QColor(0, 0, 0))
    path = tmp_path / "flaeche.png"
    img.save(str(path))
    (img_id,) = win.import_tools.import_path(path)
    dlg = TraceDialog(win.canvas.document.shape(img_id),
                      TraceSettings(mode=MODE_CENTERLINE, smoothing_px=0))
    assert dlg.settings().mode == MODE_CENTERLINE
    # a filled square thins to a short X-shaped skeleton or nothing – never an error
    assert dlg.info.text()
    dlg.deleteLater()
