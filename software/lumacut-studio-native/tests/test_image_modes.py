"""Review round 27: Jarvis / Stucki / Sierra / halftone / newsprint image modes,
dot width correction and the live preview in the image settings dialog."""
from __future__ import annotations

import json
import re

import numpy as np
import pytest

from _pi_guard import pi_check
from lumacut_job import raster
from lumacut_job.raster import (MODES, RasterSettings, _dot_width, _error_diffuse,
                                _error_diffuse_rows, power_map, raster_gcode, scanlines)

NEW_DOT_MODES = ("jarvis", "stucki", "sierra", "halftone", "newsprint")


def gradient(w=60, h=12):
    return np.tile(np.linspace(0, 255, w).astype(np.uint8), (h, 1))


def runs_of(line_list):
    """(x, S) of every G1 in a list of G-code lines."""
    out = []
    for line in line_list:
        m = re.match(r"G1 X([\d.]+) Y[\d.]+ F\d+ S(\d+)", line)
        if m:
            out.append((float(m.group(1)), int(m.group(2))))
    return out


# ------------------------------------------------------------- engine
def test_new_modes_are_listed_everywhere():
    from lumacut_canvas.model import IMAGE_MODES
    from lumacut_import.qt import MODE_LABELS
    for m in NEW_DOT_MODES:
        assert m in MODES and m in IMAGE_MODES and m in MODE_LABELS
    # old modes keep their place (old files, combo index 0 = threshold)
    assert IMAGE_MODES[:6] == ("threshold", "floyd", "atkinson", "ordered", "grayscale", "depth3d")
    assert list(MODE_LABELS)[0] == "threshold"


@pytest.mark.parametrize("mode", NEW_DOT_MODES)
def test_new_modes_produce_pi_safe_on_off_gcode(mode):
    s = RasterSettings(mode=mode, line_interval_mm=0.25, power=80, halftone_cpi=20)
    g = raster_gcode(gradient(), (50, 50), 15, 3, s)
    pi_check(g)
    vals = {int(v) for v in re.findall(r" S(\d+)", g)}
    assert vals <= {0, 204} and 204 in vals


@pytest.mark.parametrize("mode", NEW_DOT_MODES)
@pytest.mark.parametrize("level", [0.1, 0.25, 0.5, 0.75, 0.9])
def test_new_modes_keep_the_tone(mode, level):
    s = RasterSettings(mode=mode, power=100, line_interval_mm=0.1, halftone_cpi=30)
    img = np.full((120, 120), round(255 * (1 - level)), dtype=np.uint8)
    share = (power_map(img, s) > 0).mean()
    assert share == pytest.approx(level, abs=0.04)


@pytest.mark.parametrize("mode", NEW_DOT_MODES)
def test_white_stays_unburned_and_black_fully_burned(mode):
    s = RasterSettings(mode=mode, power=50)
    assert not power_map(np.full((30, 30), 255, np.uint8), s).any()
    assert (power_map(np.full((30, 30), 0, np.uint8), s) == round(0.5 * 255)).all()
    # negative swaps it
    s.negative = True
    assert not power_map(np.full((30, 30), 0, np.uint8), s).any()


@pytest.mark.parametrize("kernel", ["_FLOYD", "_ATKINSON", "_JARVIS", "_STUCKI", "_SIERRA"])
def test_row_diffusion_matches_the_pixel_loop(kernel):
    k = getattr(raster, kernel)
    d = np.random.default_rng(7).random((40, 55))
    assert (_error_diffuse_rows(d, k) == _error_diffuse(d, k)).all()


def test_kernels_sum_to_one_and_have_the_textbook_weights():
    for k in (raster._JARVIS, raster._STUCKI, raster._SIERRA, raster._FLOYD, raster._ATKINSON[:0]):
        if k:
            assert sum(f for _dx, _dy, f in k) == pytest.approx(1.0)
    assert (1, 0, 7 / 48) in raster._JARVIS and (-2, 2, 1 / 48) in raster._JARVIS
    assert (1, 0, 8 / 42) in raster._STUCKI and (0, 2, 4 / 42) in raster._STUCKI
    assert (1, 0, 5 / 32) in raster._SIERRA and len(raster._SIERRA) == 10


def test_old_modes_unchanged():
    """Floyd / Atkinson still use the original float32 loop (bit-identical output)."""
    g = (np.random.default_rng(3).random((25, 33)) * 255).astype(np.uint8)
    for mode, kernel in (("floyd", raster._FLOYD), ("atkinson", raster._ATKINSON)):
        s = RasterSettings(mode=mode, power=100)
        dark = (255.0 - g.astype(np.float32)) / 255.0
        assert ((power_map(g, s) > 0) == _error_diffuse(dark, kernel)).all()


def test_jarvis_spreads_differently_from_floyd():
    g = gradient(80, 30)
    a = power_map(g, RasterSettings(mode="floyd"))
    b = power_map(g, RasterSettings(mode="jarvis"))
    c = power_map(g, RasterSettings(mode="stucki"))
    assert (a != b).any() and (b != c).any()


def test_halftone_dots_are_round_clusters_per_cell():
    s = RasterSettings(mode="halftone", line_interval_mm=0.1, halftone_cpi=25.4, halftone_angle=0)
    # 1 mm cells = 10 px; 20 % dark -> one round dot of ~20 px per cell
    on = power_map(np.full((40, 40), 204, np.uint8), s) > 0
    for cy in range(4):
        for cx in range(4):
            cell = on[cy * 10:(cy + 1) * 10, cx * 10:(cx + 1) * 10]
            assert 16 <= cell.sum() <= 24
            assert cell[4:6, 4:6].all()          # centre burned
            assert not cell[0, 0] and not cell[9, 9]   # corners free


def test_halftone_cell_size_and_angle_change_the_pattern():
    img = np.full((60, 60), 160, np.uint8)
    base = power_map(img, RasterSettings(mode="halftone", halftone_cpi=30, halftone_angle=45))
    assert (base != power_map(img, RasterSettings(mode="halftone", halftone_cpi=15,
                                                  halftone_angle=45))).any()
    assert (base != power_map(img, RasterSettings(mode="halftone", halftone_cpi=30,
                                                  halftone_angle=0))).any()
    # mirrored image + mirrored angle = mirrored pattern (machine X flip)
    s0 = RasterSettings(mode="halftone", halftone_cpi=25.4, halftone_angle=0, line_interval_mm=0.1)
    m0 = power_map(np.full((40, 40), 128, np.uint8), s0)
    assert (m0[:, ::-1] == m0).all()     # 0° screen is symmetric on whole cells


def test_halftone_cell_px_helper():
    s = RasterSettings(mode="halftone", halftone_cpi=25.4, line_interval_mm=0.2)
    assert raster.halftone_cell_px(s) == pytest.approx(5.0)


def test_newsprint_tile_is_an_exact_45_degree_screen():
    tile = raster._newsprint_tile()
    assert tile.shape == (12, 12)
    # 144 pixels = two cells of 72 ranks each
    ranks = np.sort(np.rint(tile.ravel() * 72 - 0.5).astype(int))
    assert list(ranks) == sorted(list(range(72)) * 2)
    on = raster._newsprint(np.full((48, 48), 0.2))
    assert on.mean() == pytest.approx(14 / 72, abs=1e-9)


def test_settings_validation():
    with pytest.raises(ValueError):
        RasterSettings(mode="halftone", halftone_cpi=2).validate()
    with pytest.raises(ValueError):
        RasterSettings(halftone_angle=120).validate()
    with pytest.raises(ValueError):
        RasterSettings(line_interval_mm=0.1, dot_width_mm=0.2).validate()
    RasterSettings(line_interval_mm=0.1, dot_width_mm=0.1).validate()
    with pytest.raises(ValueError):
        raster.dot_mask(np.zeros((2, 2)), RasterSettings(mode="grayscale"))


def test_new_diffusion_is_fast_enough():
    import time
    g = (np.random.default_rng(1).random((400, 500)) * 255).astype(np.uint8)
    t = time.perf_counter()
    power_map(g, RasterSettings(mode="jarvis"))
    assert time.perf_counter() - t < 5.0


# ------------------------------------------------------------- dot width correction
def test_dot_width_zero_is_unchanged():
    pm = power_map(gradient(), RasterSettings(mode="stucki"))
    a = scanlines(pm, (50, 50), RasterSettings(line_interval_mm=0.1))
    b = scanlines(pm, (50, 50), RasterSettings(line_interval_mm=0.1, dot_width_mm=0.0))
    assert a == b


def test_dot_width_shortens_burning_runs_at_both_ends():
    s = RasterSettings(line_interval_mm=1, overscan_mm=0, dot_width_mm=0.4, bidirectional=False)
    pm = np.array([[255, 255, 0, 0, 255, 0, 255, 255, 255]])
    lines = scanlines(pm, (100, 100), s)
    assert lines[0] == "G0 X100.200 Y100.500"        # row start moves in by 0.2
    assert runs_of(lines) == [(101.8, 255), (104.2, 0), (104.8, 255), (106.2, 0), (108.8, 255)]
    # burned lengths: 1.6, 0.6, 2.6 (each 0.4 shorter)


def test_dot_width_keeps_tiny_dots_and_grayscale_edges():
    # single 1-px dot with full-interval correction keeps MIN_DOT_PX
    out = _dot_width([(0, 1, 200)], 1.0)
    assert out[0][1] - out[0][0] == pytest.approx(raster.MIN_DOT_PX)
    assert out[0][0] == pytest.approx(0.45)
    # neighbouring runs of different power keep their shared edge
    out = _dot_width([(0, 2, 100), (2, 4, 200), (4, 5, 0), (5, 6, 50)], 0.5)
    assert out == [(0.25, 2.0, 100), (2.0, 3.75, 200), (3.75, 5.25, 0), (5.25, 5.75, 50)]


def test_dot_width_reverse_lines_and_scan_offset():
    s = RasterSettings(line_interval_mm=1, overscan_mm=1, dot_width_mm=0.5, scan_offset_mm=0.3)
    pm = np.array([[255, 255, 0], [255, 255, 0]])
    lines = scanlines(pm, (100, 100), s)
    fwd = runs_of(lines[:4])
    rev = runs_of(lines[4:])
    assert fwd == [(100.25, 0), (101.75, 255), (102.75, 0)]
    # reverse: starts right (1.75 + 0.3 shift), burns to 0.25 + 0.3
    assert lines[4] == "G0 X103.050 Y101.500"
    assert rev == [(102.05, 0), (100.55, 255), (99.55, 0)]
    pi_check("\n".join(["G21", "G90", "M5 I", "M3 I"] + lines + ["M5 I"]))


def test_dot_width_reduces_burned_length_in_gcode():
    from lumacut_job.estimate import estimate_gcode
    s0 = RasterSettings(mode="halftone", line_interval_mm=0.2, overscan_mm=0)
    s1 = RasterSettings(mode="halftone", line_interval_mm=0.2, overscan_mm=0, dot_width_mm=0.1)
    g0 = raster_gcode(gradient(), (60, 60), 12, 2.4, s0)
    g1 = raster_gcode(gradient(), (60, 60), 12, 2.4, s1)
    pi_check(g1)
    assert estimate_gcode(g1).cut_length_mm < estimate_gcode(g0).cut_length_mm


# ------------------------------------------------------------- model / images
def test_image_settings_new_fields_roundtrip_and_clamp():
    from lumacut_canvas.model import ImageSettings
    st = ImageSettings.from_dict({"mode": "halftone", "halftone_cpi": 999, "halftone_angle": -200,
                                  "dot_width_mm": 5, "line_interval_mm": 0.08})
    assert st.mode == "halftone" and st.halftone_cpi == 150 and st.halftone_angle == -90
    assert st.dot_width_mm == pytest.approx(0.08)
    assert ImageSettings.from_dict(json.loads(json.dumps(st.to_dict()))) == st
    # old file without the new keys -> defaults (output unchanged)
    old = ImageSettings.from_dict({"mode": "floyd"})
    assert (old.halftone_cpi, old.halftone_angle, old.dot_width_mm) == (30.0, 45.0, 0.0)


def _doc_with_image(qapp, **settings):
    from lumacut_canvas.model import Document, Geometry, ImageSettings, Layer, RasterImage, Shape
    from lumacut_import.image import grayscale_png
    from PySide6.QtGui import QColor, QImage
    d = Document()
    d.add_layer(Layer("Ebene 1"))
    img = QImage(60, 30, QImage.Format_RGB32)
    for x in range(60):
        for y in range(30):
            v = int(255 * x / 59)
            img.setPixelColor(x, y, QColor(v, v, v))
    png, pw, ph = grayscale_png(img)
    sh = Shape("image", Geometry(80, 80, 12, 6), d.active_layer_id,
               image=RasterImage(png, pw, ph, ImageSettings(**settings)))
    d.add_shape(sh)
    return d, sh


@pytest.mark.parametrize("mode", NEW_DOT_MODES)
def test_image_objects_in_new_modes_send_pi_safe(qapp, mode):
    from lumacut_job.images import image_job, raster_settings
    _d, sh = _doc_with_image(qapp, mode=mode, line_interval_mm=0.2, dot_width_mm=0.05,
                             halftone_cpi=20, halftone_angle=30)
    rs = raster_settings(sh)
    assert (rs.mode, rs.halftone_cpi, rs.halftone_angle, rs.dot_width_mm) == (mode, 20, 30, 0.05)
    job = image_job(sh)
    assert job.lines[0].endswith(mode.upper())
    pi_check("\n".join(["G21", "G90", "M5 I", "M3 I"] + job.lines + ["M5 I", "M400"]))


def test_image_job_mirrors_the_halftone_angle_with_the_machine_flip(qapp, monkeypatch):
    from lumacut_job import images
    _d, sh = _doc_with_image(qapp, mode="halftone", line_interval_mm=0.2, halftone_angle=30)
    seen = []
    real = images.power_map

    def spy(gray, s):
        seen.append(s.halftone_angle)
        return real(gray, s)

    monkeypatch.setattr(images, "power_map", spy)
    images.image_job(sh)
    assert seen == [-30.0 if images.IMAGE_FLIP_X else 30.0]


def test_old_image_document_gcode_is_unchanged(qapp):
    """A document saved before round 27 (no new keys) gives the same image G-code."""
    from lumacut_canvas.model import Document
    from lumacut_job.images import image_job
    d, sh = _doc_with_image(qapp, mode="floyd", line_interval_mm=0.2)
    data = json.loads(json.dumps(d.to_dict()))
    for s in data["objects"]:
        for k in ("halftone_cpi", "halftone_angle", "dot_width_mm"):
            s["image"]["settings"].pop(k)
    d2 = Document.from_dict(data)
    assert image_job(d2.shapes[0]).lines == image_job(sh).lines


def test_depth3d_uses_dot_width_too(qapp):
    from lumacut_job.images import image_job
    _d, a = _doc_with_image(qapp, mode="depth3d", line_interval_mm=0.2, depth_levels=3)
    _d, b = _doc_with_image(qapp, mode="depth3d", line_interval_mm=0.2, depth_levels=3,
                            dot_width_mm=0.1)
    assert image_job(a).lines != image_job(b).lines


# ------------------------------------------------------------- preview
def test_preview_array_matches_the_engine():
    from lumacut_canvas.model import ImageSettings
    from lumacut_import.image_preview import preview_array
    g = gradient(60, 30)
    st = ImageSettings(mode="jarvis", line_interval_mm=0.2, power=50)
    pv = preview_array(g, 12, 6, st)
    pm = power_map(raster.resample(g, 12, 6, 0.2), RasterSettings(mode="jarvis", power=50))
    assert pv.pixels.shape == pm.shape and not pv.cropped
    assert ((pv.pixels == 0) == (pm > 0)).all() and set(np.unique(pv.pixels)) <= {0, 255}
    assert pv.burn_share == pytest.approx((pm > 0).mean())


def test_preview_grayscale_depth_and_crop():
    from lumacut_canvas.model import ImageSettings
    from lumacut_import.image_preview import preview_array
    g = gradient(60, 30)
    pv = preview_array(g, 12, 6, ImageSettings(mode="grayscale", line_interval_mm=0.2))
    assert len(np.unique(pv.pixels)) > 10
    pv = preview_array(g, 12, 6, ImageSettings(mode="depth3d", line_interval_mm=0.2,
                                               depth_levels=4))
    assert set(np.unique(pv.pixels)) <= {0, 64, 128, 191, 255}
    pv = preview_array(g, 120, 60, ImageSettings(mode="halftone", line_interval_mm=0.1),
                       max_pixels=10_000)
    assert pv.cropped and pv.pixels.size <= 10_000 and pv.pixels.shape == (100, 100)


def test_dialog_new_fields_and_roundtrip(qapp):
    from lumacut_canvas.model import ImageSettings
    from lumacut_import.qt import ImageSettingsDialog
    st = ImageSettings(mode="halftone", halftone_cpi=40, halftone_angle=15, dot_width_mm=0.05,
                       line_interval_mm=0.1)
    dlg = ImageSettingsDialog(st, 10.0, 100)
    assert dlg.settings() == st.normalized()
    assert dlg.cpi.isEnabled() and dlg.angle.isEnabled() and not dlg.threshold.isEnabled()
    assert "Zelle 0.64 mm = 6.3 Punkte" in dlg.hint.text()
    dlg.cpi.setValue(120)
    assert "zu klein" in dlg.hint.text()
    dlg.mode.setCurrentIndex(list(dlg.mode.itemData(i) for i in range(dlg.mode.count()))
                             .index("jarvis"))
    assert not dlg.cpi.isEnabled() and dlg.settings().mode == "jarvis"
    # dot width is limited to the line interval
    dlg.interval.setValue(0.04)
    assert dlg.dot_width.maximum() == pytest.approx(0.04) and dlg.dot_width.value() <= 0.04
    assert dlg.preview.isHidden()           # no image data -> no preview
    dlg.update_preview()
    assert dlg.preview_runs == 0


def test_dialog_preview_updates_debounced(qapp):
    from PySide6.QtCore import QCoreApplication, QElapsedTimer
    from lumacut_canvas.model import ImageSettings
    from lumacut_import.qt import ImageSettingsDialog
    from PySide6.QtGui import QColor, QImage
    from lumacut_import.image import grayscale_png
    img = QImage(60, 30, QImage.Format_RGB32)
    for x in range(60):
        for y in range(30):
            v = int(255 * x / 59)
            img.setPixelColor(x, y, QColor(v, v, v))
    png, pw, _ph = grayscale_png(img)
    dlg = ImageSettingsDialog(ImageSettings(mode="floyd", line_interval_mm=0.2), 12.0, pw,
                              png=png, height_mm=6.0)
    assert not dlg.preview.isHidden()
    assert dlg.preview_runs == 1 and dlg.preview.pixmap() is not None
    assert "60 × 30 Laserpunkte" in dlg.preview_label.text()
    first = dlg.last_preview.pixels.copy()
    dlg.mode.setCurrentIndex(list(dlg.mode.itemData(i) for i in range(dlg.mode.count()))
                             .index("halftone"))
    dlg.cpi.setValue(20)
    assert dlg.preview_runs == 1          # debounced, not yet recomputed
    t = QElapsedTimer()
    t.start()
    while dlg.preview_runs == 1 and t.elapsed() < 3000:
        QCoreApplication.processEvents()
    assert dlg.preview_runs == 2          # several changes -> one recompute
    assert (dlg.last_preview.pixels != first).any()
    dlg.negative.setChecked(True)
    dlg.update_preview()
    assert dlg.preview_runs == 3


def test_edit_image_settings_passes_the_image_to_the_dialog(qapp, tmp_path, monkeypatch):
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QDialog
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(tmp_path))
    QSettings.setDefaultFormat(QSettings.IniFormat)
    main = pytest.importorskip("main")
    from lumacut_import import qt as import_qt
    from PySide6.QtGui import QColor, QImage
    w = main.LumaCutStudio()
    w.import_tools.interactive = False
    try:
        img = QImage(50, 20, QImage.Format_RGB32)
        img.fill(QColor(90, 90, 90))
        p = tmp_path / "foto.png"
        img.save(str(p))
        ids = w.import_tools.import_path(p)
        seen = {}

        class FakeDialog(import_qt.ImageSettingsDialog):
            def exec(self):  # noqa: A003
                seen["gray"] = self._gray is not None
                seen["runs"] = self.preview_runs
                self.mode.setCurrentIndex(
                    [self.mode.itemData(i) for i in range(self.mode.count())].index("stucki"))
                self.dot_width.setValue(0.03)
                return QDialog.Accepted

        monkeypatch.setattr(import_qt, "ImageSettingsDialog", FakeDialog)
        assert w.import_tools.edit_image_settings(ids[0])
        assert seen == {"gray": True, "runs": 1}
        st = w.canvas.document.shape(ids[0]).image.settings
        assert st.mode == "stucki" and st.dot_width_mm == pytest.approx(0.03)
    finally:
        w.canvas.undo_stack.setClean()
        w.close()
