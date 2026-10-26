"""Bild nachzeichnen (Bitmap → Vektor): Engine, Canvas-Umrechnung, Dialog, Undo."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _pi_guard import pi_check  # noqa: E402

from lumacut_import.trace import (TraceSettings, to_canvas, trace_gray,  # noqa: E402
                                  traced_shapes)

RAW = TraceSettings(smoothing_px=0, tolerance_mm=0, min_area_mm2=0)


def _blank(h=100, w=100):
    return np.full((h, w), 255, np.uint8)


def _bbox(ring):
    xs = [p[0] for p in ring]
    ys = [p[1] for p in ring]
    return min(xs), min(ys), max(xs), max(ys)


def test_square_with_hole_on_pixel_edges():
    g = _blank()
    g[20:80, 20:80] = 0
    g[40:60, 40:60] = 255
    res = trace_gray(g, RAW)
    assert len(res.parts) == 1
    part = res.parts[0]
    assert _bbox(part.outer) == pytest.approx((20, 20, 80, 80))
    assert len(part.holes) == 1
    # Loch auf den Pixelkanten (Ecken nur minimal angefast)
    assert _bbox(part.holes[0]) == pytest.approx((40, 40, 60, 60))


def test_island_in_hole_is_own_part_and_thin_lines_survive():
    g = _blank()
    g[20:80, 20:80] = 0
    g[40:60, 40:60] = 255
    g[47:53, 47:53] = 0          # Insel im Loch
    g[5, 10:90] = 0              # 1 Pixel breite Linie
    g[90, 90] = 0                # Einzelpixel
    res = trace_gray(g, RAW)
    boxes = sorted(_bbox(p.outer) for p in res.parts)
    assert boxes == pytest.approx(sorted([(20, 20, 80, 80), (47, 47, 53, 53),
                                          (10, 5, 90, 6), (90, 90, 91, 91)]))


def test_invert_threshold_and_border():
    g = _blank(40, 60)
    g[:, :30] = 200              # hellgrau links bis an den Bildrand
    assert trace_gray(g, RAW).parts == []                       # 200 > 128
    left = trace_gray(g, TraceSettings(threshold=230, smoothing_px=0, min_area_mm2=0))
    assert [_bbox(p.outer) for p in left.parts] == [pytest.approx((0, 0, 30, 40))]
    inv = trace_gray(g, TraceSettings(threshold=230, invert=True, smoothing_px=0, min_area_mm2=0))
    assert [_bbox(p.outer) for p in inv.parts] == [pytest.approx((30, 0, 60, 40))]


def test_despeckle_and_tolerance():
    import cv2
    g = _blank(200, 200)
    cv2.circle(g, (100, 100), 60, 0, -1)
    g[10, 10] = 0
    g[11, 180] = 0
    fine = trace_gray(g, TraceSettings(smoothing_px=0, tolerance_mm=0, min_area_mm2=0), (0.1, 0.1))
    assert len(fine.parts) == 3
    clean = trace_gray(g, TraceSettings(smoothing_px=0, tolerance_mm=0, min_area_mm2=0.5), (0.1, 0.1))
    assert len(clean.parts) == 1 and clean.removed == 2
    coarse = trace_gray(g, TraceSettings(smoothing_px=0, tolerance_mm=0.1, min_area_mm2=0.5), (0.1, 0.1))
    assert coarse.point_count < clean.point_count / 3
    # Vereinfachte Kontur weicht höchstens um die Toleranz ab (1 px = 0,1 mm)
    from shapely.geometry import Polygon
    a = Polygon(clean.parts[0].outer)
    b = Polygon(coarse.parts[0].outer)
    assert a.hausdorff_distance(b) <= 1.0 + 1e-6


def test_noise_is_refused_with_clear_message():
    rng = np.random.default_rng(3)
    g = ((rng.random((800, 800)) > 0.5) * 255).astype(np.uint8)
    with pytest.raises(ValueError, match="detailreich|Konturen"):
        trace_gray(g, RAW)


def test_settings_clamped_and_taken_from_image():
    st = TraceSettings(threshold=999, smoothing_px=-1, tolerance_mm=9, min_area_mm2=-3).normalized()
    assert (st.threshold, st.smoothing_px, st.tolerance_mm, st.min_area_mm2) == (255, 0.0, 2.0, 0.0)


def _image_shape(gray, x=10.0, y=20.0, w=50.0, h=20.0, rot=0.0):
    import cv2
    from lumacut_canvas.model import Geometry, ImageSettings, RasterImage, Shape
    ok, png = cv2.imencode(".png", gray)
    assert ok
    img = RasterImage(png.tobytes(), gray.shape[1], gray.shape[0],
                      ImageSettings(threshold=100, negative=False))
    return Shape("image", Geometry(x, y, w, h, rot), "L1", image=img)


def test_canvas_mapping_rotation_rings_and_group():
    from lumacut_import.trace import TraceSettings as TS
    g = _blank(40, 100)
    g[10:30, 10:40] = 0
    g[15:25, 20:30] = 255
    g[10:30, 60:90] = 0
    sh = _image_shape(g)                         # 0,5 mm je Pixel
    assert TS.for_image(sh).threshold == 100
    res = trace_gray(g, RAW)
    shapes = traced_shapes(sh, res, "L2")
    assert len(shapes) == 2 and all(s.kind == "polygon" and s.layer_id == "L2" for s in shapes)
    assert shapes[0].groups and shapes[0].groups == shapes[1].groups
    holed = next(s for s in shapes if s.rings)
    b = holed.bounds()
    assert (b.x, b.y, b.w, b.h) == pytest.approx((15, 25, 15, 10))
    other = next(s for s in shapes if not s.rings).bounds()
    assert (other.x, other.y, other.w, other.h) == pytest.approx((40, 25, 15, 10))
    # 90° gedreht: Punkte um die Bildmitte (35, 30) gedreht
    rot = _image_shape(g, rot=90.0)
    (px, py), = to_canvas(rot, [(0.0, 0.0)])
    assert (px, py) == pytest.approx((45.0, 5.0))


def test_traced_gcode_passes_pi_guard(qapp):
    from lumacut_canvas.model import Document
    from lumacut_job.planner import optimized_document_gcode
    g = _blank(40, 100)
    g[10:30, 10:40] = 0
    g[15:25, 20:30] = 255
    doc = Document()
    sh = _image_shape(g)
    for s in traced_shapes(sh, trace_gray(g, RAW), doc.active_layer_id):
        doc.add_shape(s)
    gcode = optimized_document_gcode(doc)
    assert gcode.count("G1 ") >= 8
    pi_check(gcode)


# ---------------------------------------------------------------- Hauptfenster


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


def _png(tmp_path, blank=False):
    from PySide6.QtGui import QColor, QImage
    img = QImage(100, 50, QImage.Format_RGB32)
    img.fill(QColor(255, 255, 255))
    for x in range(20, 60) if not blank else ():
        for y in range(10, 40):
            img.setPixelColor(x, y, QColor(0, 0, 0))
    img.setDotsPerMeterX(round(254 / 0.0254))   # 0,1 mm je Pixel
    img.setDotsPerMeterY(round(254 / 0.0254))
    p = tmp_path / ("leer.png" if blank else "logo.png")
    img.save(str(p))
    return p


def test_trace_action_menu_shortcut_and_enabled(win, tmp_path):
    tools = win.import_tools
    assert tools.trace_action.shortcut().toString() == "Alt+T"
    assert "Bild nachzeichnen …" in [a.text() for a in tools.menu.actions()]
    assert not tools.trace_action.isEnabled()
    tools.import_path(_png(tmp_path))
    assert tools.trace_action.isEnabled()


def test_trace_is_one_undo_step_and_optionally_deletes_image(win, tmp_path):
    from lumacut_import.trace import TraceSettings as TS
    ed = win.canvas
    tools = win.import_tools
    (img_id,) = tools.import_path(_png(tmp_path))
    n_before = len(ed.document.shapes)
    ids = tools.trace_image(img_id, TS(smoothing_px=0, tolerance_mm=0.01), delete_image=False)
    assert len(ids) == 1 and ed.selection == ids
    b = ed.document.shape(ids[0]).bounds()
    ib = ed.document.shape(img_id).bounds()
    assert (b.x - ib.x, b.y - ib.y, b.w, b.h) == pytest.approx((2.0, 1.0, 4.0, 3.0), abs=1e-3)
    assert ed.undo_stack.undoText() == "Bild nachzeichnen"
    ed.undo_stack.undo()
    assert len(ed.document.shapes) == n_before
    ids = tools.trace_image(img_id, TS(), delete_image=True)
    assert ids and not ed.document.has_shape(img_id)
    ed.undo_stack.undo()                         # ein Schritt: Bild wieder da, Konturen weg
    assert ed.document.has_shape(img_id) and not ed.document.has_shape(ids[0])


def test_trace_errors(win, tmp_path):
    from lumacut_import.trace import TraceSettings as TS
    tools = win.import_tools
    assert tools.trace_image(None, TS()) == []           # nichts ausgewählt
    (blank_id,) = tools.import_path(_png(tmp_path, blank=True))
    assert tools.trace_image(blank_id, TS()) == []           # weißes Bild
    assert "Keine Konturen" in tools.last_error
    (img_id,) = tools.import_path(_png(tmp_path))
    doc = win.canvas.document
    doc.update_layer(doc.active_layer_id, locked=True)
    assert tools.trace_image(img_id, TS()) == []
    assert "gesperrt" in tools.last_error


def test_trace_dialog_preview(win, tmp_path):
    from lumacut_import.trace_qt import TraceDialog
    tools = win.import_tools
    (img_id,) = tools.import_path(_png(tmp_path))
    dlg = TraceDialog(win.canvas.document.shape(img_id))
    assert "1 Kontur" in dlg.info.text() and dlg.ok_button.isEnabled()
    dlg.invert.setChecked(True)
    dlg.update_preview()
    assert dlg.settings().invert and "Kontur" in dlg.info.text()
    dlg.threshold.setValue(1)
    dlg.invert.setChecked(False)
    dlg.update_preview()                         # 0 < 1: nur das schwarze Rechteck
    assert "1 Kontur" in dlg.info.text()
    dlg.min_area.setValue(100)                   # Rechteck 4×3 mm = 12 mm² < 100
    dlg.update_preview()
    assert not dlg.ok_button.isEnabled() and "Keine Konturen" in dlg.info.text()
    dlg.deleteLater()


# --- Laufzeit (Review Runde 6): kein Hängen bei unruhigen Bildern ----------

def _dot_grid(n=1000, step=8):
    """Schwarze Fläche mit vielen 2×2-Pixel-Löchern (ein Teil, ~15 000 Löcher)."""
    g = np.zeros((n, n), np.uint8)
    yy, xx = np.mgrid[0:n, 0:n]
    g[((yy % step) < 2) & ((xx % step) < 2) & (yy > 4) & (xx > 4)
      & (yy < n - 5) & (xx < n - 5)] = 255
    return g


def test_many_holes_is_fast_and_exact():
    import time
    from shapely.geometry import Polygon
    g = _dot_grid()
    t0 = time.perf_counter()
    res = trace_gray(g, TraceSettings(smoothing_px=0, min_area_mm2=0), (0.1, 0.1))
    dt = time.perf_counter() - t0
    assert dt < 8.0                              # alter Pfad: ~15 s (quadratisch)
    assert len(res.parts) == 1
    part = res.parts[0]
    assert len(part.holes) == 124 * 124
    assert _bbox(part.outer) == pytest.approx((0, 0, 1000, 1000))
    # Löcher liegen auf den Pixelkanten und das Polygon ist gültig
    assert _bbox(part.holes[0])[2] - _bbox(part.holes[0])[0] == pytest.approx(2, abs=0.3)
    assert Polygon(part.outer, part.holes).is_valid


def test_smooth_noise_finishes_or_refuses_quickly():
    import time
    import cv2
    rng = np.random.default_rng(1)
    for n, sigma in ((1000, 4), (1000, 8), (2000, 8)):
        g = (rng.random((n, n)) * 255).astype(np.uint8)
        g = cv2.normalize(cv2.GaussianBlur(g, (0, 0), sigma), None, 0, 255, cv2.NORM_MINMAX)
        for st in (TraceSettings(), TraceSettings(smoothing_px=0, min_area_mm2=0)):
            t0 = time.perf_counter()
            try:
                res = trace_gray(g, st, (0.085, 0.085))
                assert res.parts
            except ValueError as exc:
                assert "Konturen" in str(exc) or "detailreich" in str(exc)
            assert time.perf_counter() - t0 < 15.0, (n, sigma, st)


def test_time_limit_and_size_cap(monkeypatch):
    import lumacut_import.trace as tr
    g = _blank()
    g[10:30, 10:30] = 0
    g[50:70, 50:70] = 0
    with pytest.raises(ValueError, match="dauert zu lange"):
        trace_gray(g, RAW, time_limit_s=0.0)
    assert len(trace_gray(g, RAW, time_limit_s=None).parts) == 2
    monkeypatch.setattr(tr, "MAX_PIXELS", 5000)
    with pytest.raises(ValueError, match="zu groß"):
        trace_gray(g, RAW)


def test_preview_on_large_noisy_image_stays_responsive(win):
    import time
    import cv2
    from lumacut_import.trace_qt import TraceDialog
    rng = np.random.default_rng(2)
    g = (rng.random((3000, 3000)) * 255).astype(np.uint8)
    g = cv2.normalize(cv2.GaussianBlur(g, (0, 0), 3), None, 0, 255, cv2.NORM_MINMAX)
    sh = _image_shape(g, w=250.0, h=250.0)
    t0 = time.perf_counter()
    dlg = TraceDialog(sh)
    dlg.smoothing.setValue(0)
    dlg.min_area.setValue(0)
    dlg.update_preview()
    assert time.perf_counter() - t0 < 10.0
    assert dlg.info.text()
    dlg.deleteLater()


# --- Auto-Schwellwert (Otsu) ----------------------------------------------

def _bimodal(dark=60, light=100):
    rng = np.random.default_rng(3)
    g = np.full((100, 100), light, np.int16)
    g[30:70, 20:60] = dark
    g = g + rng.integers(-5, 6, g.shape)
    return np.clip(g, 0, 255).astype(np.uint8)


def test_otsu_threshold_and_auto_setting():
    from lumacut_import.trace import effective_threshold, otsu_threshold
    g = _bimodal()
    t = otsu_threshold(g)
    assert 65 < t <= 95                          # zwischen den beiden Gipfeln
    assert TraceSettings().auto_threshold is False
    auto = TraceSettings(threshold=30, smoothing_px=0, tolerance_mm=0, min_area_mm2=0,
                         auto_threshold=True)
    assert auto.normalized().auto_threshold
    assert effective_threshold(g, auto) == t
    assert effective_threshold(g, RAW) == RAW.threshold
    # fester Schwellwert 30 findet nichts, Auto findet genau das dunkle Rechteck
    assert trace_gray(g, TraceSettings(threshold=30, smoothing_px=0, tolerance_mm=0,
                                       min_area_mm2=0)).parts == []
    res = trace_gray(g, auto)
    assert res.threshold == t
    assert len(res.parts) == 1 and _bbox(res.parts[0].outer) == pytest.approx((20, 30, 60, 70))
    # Invertieren mit Auto: der helle Rest (Rahmen mit Loch)
    inv = trace_gray(g, TraceSettings(**{**auto.__dict__, "invert": True}))
    assert len(inv.parts) == 1 and len(inv.parts[0].holes) == 1
    # einfarbiges Bild: kein Absturz
    flat = trace_gray(np.full((20, 20), 128, np.uint8), auto)
    assert flat.parts == [] or len(flat.parts) == 1


def test_trace_dialog_auto_threshold(win):
    from lumacut_import.trace_qt import TraceDialog
    dlg = TraceDialog(_image_shape(_bimodal(), w=50.0, h=50.0))
    dlg.threshold.setValue(30)
    dlg.update_preview()
    assert "Keine Konturen" in dlg.info.text() and dlg.threshold.isEnabled()
    dlg.auto_threshold.setChecked(True)
    dlg.update_preview()
    assert not dlg.threshold.isEnabled()
    assert "automatisch" in dlg.info.text() and "1 Kontur" in dlg.info.text()
    assert 65 < dlg.threshold.value() <= 95
    st = dlg.settings()
    assert st.auto_threshold
    dlg.auto_threshold.setChecked(False)
    assert dlg.threshold.isEnabled() and not dlg.settings().auto_threshold
    dlg.deleteLater()
