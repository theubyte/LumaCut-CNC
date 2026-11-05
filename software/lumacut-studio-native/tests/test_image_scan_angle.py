"""Review round 34: scan angle / angle increment for image objects (LightBurn
"Scan Angle" / "Angle Increment") – model, engine, job, preview and dialog."""
from __future__ import annotations

import hashlib
import json
import math
import re

import numpy as np
import pytest

from _pi_guard import pi_check
from lumacut_job.raster import ScanFrame, _clip_runs, wrap_angle

_MOVE = re.compile(r"^(G[01]) X(-?[\d.]+) Y(-?[\d.]+)(?: F[\d.]+)?(?: S(\d+))?")


def _half_image(qapp, w=60, h=30):
    """Left half black, right half white (PNG bytes, width, height)."""
    from PySide6.QtGui import QColor, QImage
    from lumacut_import.image import grayscale_png
    img = QImage(w, h, QImage.Format_RGB32)
    for x in range(w):
        for y in range(h):
            v = 0 if x < w // 2 else 255
            img.setPixelColor(x, y, QColor(v, v, v))
    return grayscale_png(img)


def _shape(qapp, geom=(80.0, 80.0, 12.0, 6.0, 0.0), png=None, **settings):
    from lumacut_canvas.model import Geometry, ImageSettings, RasterImage, Shape
    png, pw, ph = png or _half_image(qapp)
    settings.setdefault("mode", "threshold")
    settings.setdefault("line_interval_mm", 0.2)
    sh = Shape("image", Geometry(*geom), "l",
               image=RasterImage(png, pw, ph, ImageSettings(**settings)))
    sh.id = "img"
    return sh


def _segments(lines):
    """Moves as ``(kind, (x0, y0), (x1, y1), S)`` in canvas mm."""
    from lumacut_canvas.workarea import machine_to_screen
    out, pos = [], None
    for ln in lines:
        m = _MOVE.match(ln)
        if not m:
            continue
        p = machine_to_screen(float(m.group(2)), float(m.group(3)))
        if pos is not None:
            out.append((m.group(1), pos, p, int(m.group(4) or 0)))
        pos = p
    return out


def _burns(lines):
    return [(a, b, s) for k, a, b, s in _segments(lines) if k == "G1" and s > 0]


def _local(sh, p):
    """Canvas point → unrotated image-local coordinates (0..w, 0..h)."""
    cx, cy = sh.geom.center()
    t = math.radians(-sh.geom.rot)
    dx, dy = p[0] - cx, p[1] - cy
    return (dx * math.cos(t) - dy * math.sin(t) + sh.geom.w / 2,
            dx * math.sin(t) + dy * math.cos(t) + sh.geom.h / 2)


def _program(lines):
    return "\n".join(["G21", "G90", "M5 I", "M3 I"] + lines + ["M5 I", "M400"])


# ------------------------------------------------------------- model
def test_settings_defaults_normalize_and_old_files():
    from lumacut_canvas.model import ImageSettings
    st = ImageSettings()
    assert st.scan_angle == 0.0 and st.angle_increment == 0.0
    d = st.to_dict()
    assert "scan_angle" not in d and "angle_increment" not in d      # old files unchanged
    n = ImageSettings(scan_angle=135, angle_increment=-200).normalized()
    assert -90 <= n.scan_angle <= 90 and -90 <= n.angle_increment <= 90
    st2 = ImageSettings(scan_angle=30, angle_increment=45).normalized()
    d2 = json.loads(json.dumps(st2.to_dict()))
    assert d2["scan_angle"] == 30 and d2["angle_increment"] == 45
    assert ImageSettings.from_dict(d2) == st2
    assert ImageSettings.from_dict(d) == st
    hash(st2)


def test_wrap_angle_and_pass_angles():
    from lumacut_canvas.model import ImageSettings
    from lumacut_job.images import pass_angles
    assert wrap_angle(0) == 0 and wrap_angle(90) == 90 and wrap_angle(-90) == -90
    assert wrap_angle(120) == pytest.approx(-60)
    assert wrap_angle(-135) == pytest.approx(45)
    assert wrap_angle(180) == pytest.approx(0)
    assert pass_angles(ImageSettings(passes=3)) == [0, 0, 0]
    assert pass_angles(ImageSettings(passes=2, scan_angle=30)) == [30, 30]
    assert pass_angles(ImageSettings(passes=3, angle_increment=90)) == [0, 90, 0]
    assert pass_angles(ImageSettings(passes=3, scan_angle=45, angle_increment=60)) == \
        pytest.approx([45, -75, -15])


def test_clip_runs_and_scan_frame():
    runs = [(0.0, 1.0, 0), (1.0, 3.0, 200), (3.0, 4.0, 0), (4.0, 6.0, 100)]
    assert _clip_runs(runs, 1.5, 5.0) == [(1.5, 3.0, 200), (3.0, 4.0, 0), (4.0, 5.0, 100)]
    assert _clip_runs(runs, 3.2, 3.8) == []                     # nothing burns inside
    f = ScanFrame(10.0, 20.0, 0.6, 0.8, -0.8, 0.6)
    assert f.point(5, 0) == pytest.approx((13.0, 24.0))
    assert f.shifted(5).point(0, 1) == pytest.approx(f.point(5, 1))


# ------------------------------------------------------------- old output
def test_zero_angle_is_byte_identical_to_round_33(qapp):
    """Hashes generated with the round-33 code (origin/main 80b7086)."""
    from PySide6.QtGui import QColor, QImage
    from lumacut_import.image import grayscale_png
    from lumacut_job import scan_offset as so
    from lumacut_job.images import image_job
    img = QImage(40, 24, QImage.Format_RGB32)
    for x in range(40):
        for y in range(24):
            v = (x * 6 + y * 5) % 256
            img.setPixelColor(x, y, QColor(v, v, v))
    png = grayscale_png(img)
    table = so.ScanOffsetTable(entries=[(3000.0, 0.4)]).normalized()
    cases = [
        ("floyd", {}, 0, None, "bd7ac051afc46aad", 867),
        ("halftone", {"halftone_cpi": 25, "halftone_angle": 30}, 0, None, "4e4213475ba43ba0", 467),
        ("grayscale", {"brightness": 10, "passes": 2}, 20, table, "4df5b69a691a4644", 2989),
        ("depth3d", {"depth_levels": 4, "z_step_mm": 0.1}, 0, None, "2983d7ea31ec2570", 635),
        ("sketch", {}, 35, table, "3c57f74d753a760e", 461),
    ]
    for mode, kw, rot, tab, digest, n in cases:
        sh = _shape(qapp, (2, 100, 10, 6, rot), png, mode=mode, **kw)
        sh.id = "ref"
        lines = image_job(sh, "L", tab).lines
        assert len(lines) == n, mode
        assert hashlib.sha256("\n".join(lines).encode()).hexdigest()[:16] == digest, mode
        assert not any("SCAN ANGLE" in ln for ln in lines)


# ------------------------------------------------------------- geometry
@pytest.mark.parametrize("rot", [0.0, 25.0])
@pytest.mark.parametrize("angle", [90.0, 30.0, -45.0, 60.0])
def test_burns_lie_in_the_dark_half_and_follow_the_angle(qapp, rot, angle):
    from lumacut_job.images import image_job
    sh = _shape(qapp, (80, 80, 12, 6, rot), scan_angle=angle)
    lines = image_job(sh).lines
    assert lines[1] == f"; SCAN ANGLE {angle:g}"
    burns = _burns(lines)
    assert burns
    t = math.radians(angle)
    total = 0.0
    for a, b, _s in burns:
        dx, dy = b[0] - a[0], b[1] - a[1]
        ln = math.hypot(dx, dy)
        total += ln
        # direction along (cos θ, −sin θ) in canvas (Y down), either way round
        assert abs(dx * math.sin(t) + dy * math.cos(t)) < 2e-3 + 1e-3 * ln
        for p in (a, b, ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)):
            u, v = _local(sh, p)
            assert -0.01 <= u <= 6.0 + 0.25 and -0.01 <= v <= 6.01
    # coverage: dark half (36 mm²) / line interval ≈ burn length
    assert total * 0.2 == pytest.approx(36.0, rel=0.08)
    pi_check(_program(lines))


def test_angle_90_is_vertical_and_angle_0_is_unchanged(qapp):
    from lumacut_job.images import image_job
    sh0 = _shape(qapp)
    sh90 = _shape(qapp, scan_angle=90)
    b0 = _burns(image_job(sh0).lines)
    b90 = _burns(image_job(sh90).lines)
    assert all(abs(a[1] - b[1]) < 1e-6 for a, b, _ in b0)           # rows along X
    assert all(abs(a[0] - b[0]) < 1e-3 for a, b, _ in b90)           # rows along Y
    xs = sorted({round(a[0], 3) for a, _b, _ in b90})
    assert len(xs) == pytest.approx(30, abs=1)                        # 6 mm / 0.2 mm columns


def test_bidirectional_and_unidirectional_rows(qapp):
    from lumacut_job.images import image_job
    for bidi in (True, False):
        sh = _shape(qapp, scan_angle=30, bidirectional=bidi)
        burns = _burns(image_job(sh).lines)
        dirs = {math.copysign(1, b[0] - a[0]) for a, b, _ in burns}
        assert len(dirs) == (2 if bidi else 1)


def test_overscan_runs_along_the_row(qapp):
    from lumacut_job.images import image_job
    sh = _shape(qapp, scan_angle=30, overscan_mm=3)
    segs = _segments(image_job(sh).lines)
    t = math.radians(30)
    lead = [(a, b) for k, a, b, s in segs if k == "G1" and s == 0]
    assert lead
    hits = 0
    for a, b in lead:
        dx, dy = b[0] - a[0], b[1] - a[1]
        assert abs(dx * math.sin(t) + dy * math.cos(t)) < 3e-3
        hits += abs(math.hypot(dx, dy) - 3.0) < 1e-2
    assert hits >= len(lead) // 2


def test_overscan_and_offset_are_clamped_at_the_work_area_edge(qapp):
    from lumacut_canvas.workarea import to_machine
    from lumacut_job import scan_offset as so
    from lumacut_job.images import angled_settings, image_job
    from lumacut_job.raster import _MAX_X, _MAX_Y, _MIN_X, _MIN_Y
    table = so.ScanOffsetTable(entries=[(3000.0, 1.0)]).normalized()
    mid = _shape(qapp, (150, 150, 12, 6, 0), scan_angle=30, overscan_mm=4)
    s, _f = angled_settings(mid, 30.0, table)
    assert s.overscan_mm == 4 and s.scan_offset_mm == pytest.approx(1.0)
    edge = _shape(qapp, (0.5, 0.5, 12, 6, 0), scan_angle=30, overscan_mm=4)
    s, _f = angled_settings(edge, 30.0, table)
    assert s.overscan_mm < 4
    lines = image_job(edge, "", table).lines
    for _k, a, b, _s in _segments(lines):
        for p in (a, b):
            x, y = to_machine(*p)
            assert _MIN_X - 1e-3 <= x <= _MAX_X + 1e-3 and _MIN_Y - 1e-3 <= y <= _MAX_Y + 1e-3
    pi_check(_program(lines))


def test_scan_offset_shifts_reverse_rows_along_the_row(qapp):
    from lumacut_job import scan_offset as so
    from lumacut_job.images import image_job
    table = so.ScanOffsetTable(entries=[(3000.0, 0.8)]).normalized()
    sh = _shape(qapp, scan_angle=45)
    plain = image_job(sh).lines
    shifted = image_job(sh, "", table).lines
    assert plain != shifted
    t = math.radians(45)
    u = (math.cos(t), -math.sin(t))
    bp, bs = _burns(plain), _burns(shifted)
    assert len(bp) == len(bs)
    fwd = rev = 0
    for (a0, b0, _), (a1, b1, _) in zip(bp, bs):
        d = ((a1[0] - a0[0]) * u[0] + (a1[1] - a0[1]) * u[1])
        going = (b0[0] - a0[0]) * u[0] + (b0[1] - a0[1]) * u[1]
        # every row moves by half the offset against its travel direction
        assert d * math.copysign(1, going) == pytest.approx(-0.4, abs=2e-3)
        fwd += going > 0
        rev += going < 0
    assert fwd and rev


def test_angle_increment_rotates_each_pass(qapp):
    from lumacut_job.images import image_job
    sh = _shape(qapp, passes=3, angle_increment=90)
    lines = image_job(sh).lines
    marks = [ln for ln in lines if ln.startswith("; ")]
    assert marks == ["; IMAGE img THRESHOLD", "; PASS 1 OF 3", "; SCAN ANGLE 0",
                     "; PASS 2 OF 3", "; SCAN ANGLE 90", "; PASS 3 OF 3", "; SCAN ANGLE 0"]
    i1, i2, i3 = (lines.index(f"; PASS {k} OF 3") for k in (1, 2, 3))
    assert lines[i1 + 2:i2] == lines[i3 + 2:]                         # same angle → same body
    b0, b90 = _burns(lines[i1:i2]), _burns(lines[i2:i3])
    assert all(abs(a[1] - b[1]) < 1e-6 for a, b, _ in b0)
    assert all(abs(a[0] - b[0]) < 1e-3 for a, b, _ in b90)
    pi_check(_program(lines))
    one = image_job(_shape(qapp, passes=1, angle_increment=90)).lines
    assert one == image_job(_shape(qapp)).lines                        # one pass: no effect


def test_depth3d_with_scan_angle(qapp):
    from lumacut_job.images import image_job
    sh = _shape(qapp, mode="depth3d", depth_levels=3, z_step_mm=0.1, scan_angle=45)
    lines = image_job(sh).lines
    burns = _burns(lines)
    assert burns
    for a, b, _s in burns:
        dx, dy = b[0] - a[0], b[1] - a[1]
        assert abs(dx + dy) < 2e-3 * max(1.0, math.hypot(dx, dy))     # u = (cos 45°, −sin 45°)
        u, v = _local(sh, a)
        assert -0.01 <= u <= 6.25 and -0.01 <= v <= 6.01
    assert any(ln.startswith("G0 Z") or " Z" in ln for ln in lines)
    pi_check(_program(lines))


def test_halftone_angle_stays_on_the_workpiece(qapp):
    """Halftone at α with scan angle θ is rendered at α+θ in the scan frame –
    rotating back gives α again (frame axes u=(cos θ, −sin θ), v=(sin θ, cos θ))."""
    from lumacut_job.images import angled_settings
    sh = _shape(qapp, mode="halftone", halftone_angle=20, scan_angle=30)
    s, _f = angled_settings(sh, 30.0)
    assert s.halftone_angle == pytest.approx(50)
    sh2 = _shape(qapp, mode="halftone", halftone_angle=80, scan_angle=40)
    s2, _ = angled_settings(sh2, 40.0)
    assert s2.halftone_angle == pytest.approx(-60)


# ------------------------------------------------------------- preview
@pytest.mark.parametrize("angle", [90.0, 30.0])
def test_preview_keeps_the_canvas_orientation(qapp, angle):
    from lumacut_import.image_preview import preview_shape
    sh0 = _shape(qapp, line_interval_mm=0.1)
    sha = _shape(qapp, line_interval_mm=0.1, scan_angle=angle)
    p0 = preview_shape(sh0, sh0.image.settings)
    pa = preview_shape(sha, sha.image.settings)
    dark = pa.pixels < 128
    _ys, xs = np.nonzero(dark)
    # dark part stays on the left like the image on the canvas
    assert xs.mean() < pa.pixels.shape[1] / 2
    assert dark.sum() == pytest.approx((p0.pixels < 128).sum(), rel=0.12)


def test_preview_burn_share_matches_without_angle(qapp):
    from lumacut_import.image_preview import preview_shape
    sh0 = _shape(qapp, mode="floyd", line_interval_mm=0.1)
    sha = _shape(qapp, mode="floyd", line_interval_mm=0.1, scan_angle=45)
    assert preview_shape(sha, sha.image.settings).burn_share == pytest.approx(
        preview_shape(sh0, sh0.image.settings).burn_share, abs=0.1)


# ------------------------------------------------------------- dialog / editor
def test_dialog_round_trip_and_increment_enabled(qapp):
    from lumacut_canvas.model import ImageSettings
    from lumacut_import.qt import ImageSettingsDialog
    png, pw, _ph = _half_image(qapp)
    dlg = ImageSettingsDialog(ImageSettings(mode="floyd", line_interval_mm=0.2, scan_angle=30,
                                            passes=2, angle_increment=90),
                              12.0, pw, png=png, height_mm=6.0)
    assert dlg.scan_angle.value() == 30 and dlg.angle_increment.value() == 90
    assert dlg.angle_increment.isEnabled()
    st = dlg.settings()
    assert (st.scan_angle, st.angle_increment) == (30, 90)
    dlg.update_preview()
    assert "Scan-Winkel 30°" in dlg.preview_label.text()
    dlg.passes.setValue(1)
    assert not dlg.angle_increment.isEnabled()
    dlg.scan_angle.setValue(-45)
    assert dlg.settings().scan_angle == -45
    dlg.update_preview()
    assert "Scan-Winkel -45°" in dlg.preview_label.text()
    dlg.scan_angle.setValue(0)
    dlg.update_preview()
    assert "Scan-Winkel" not in dlg.preview_label.text()
    plain = ImageSettingsDialog(ImageSettings(), 10.0, 100)
    assert plain.scan_angle.value() == 0 and not plain.angle_increment.isEnabled()
    assert "scan_angle" not in plain.settings().to_dict()


def test_edit_image_settings_stores_the_scan_angle_with_undo(qapp, tmp_path, monkeypatch):
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QDialog
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(tmp_path))
    QSettings.setDefaultFormat(QSettings.IniFormat)
    main = pytest.importorskip("main")
    from lumacut_canvas.document_io import load_document, save_document
    from lumacut_import import qt as import_qt
    from PySide6.QtGui import QColor, QImage
    w = main.LumaCutStudio()
    w.import_tools.interactive = False
    try:
        img = QImage(40, 20, QImage.Format_RGB32)
        for x in range(40):
            for y in range(20):
                v = 60 + 3 * x
                img.setPixelColor(x, y, QColor(v, v, v))
        p = tmp_path / "foto.png"
        img.save(str(p))
        ids = w.import_tools.import_path(p)

        class FakeDialog(import_qt.ImageSettingsDialog):
            def exec(self):  # noqa: A003
                self.scan_angle.setValue(45)
                return QDialog.Accepted

        monkeypatch.setattr(import_qt, "ImageSettingsDialog", FakeDialog)
        assert w.import_tools.edit_image_settings(ids[0])
        doc = w.canvas.document
        assert doc.shape(ids[0]).image.settings.scan_angle == 45
        path = save_document(doc, tmp_path / "a.lcs")
        assert load_document(path).shape(ids[0]).image.settings.scan_angle == 45
        w.canvas.undo_stack.undo()
        assert w.canvas.document.shape(ids[0]).image.settings.scan_angle == 0
    finally:
        w.canvas.undo_stack.setClean()
        w.close()


def test_full_document_job_with_scan_angle_passes_the_pi_guard(qapp):
    from lumacut_canvas.model import Document, Layer
    from lumacut_job.estimate import estimate_gcode
    from lumacut_job.planner import optimized_document_gcode
    d = Document()
    d.add_layer(Layer("Ebene 1"))
    sh = _shape(qapp, mode="floyd", passes=2, scan_angle=30, angle_increment=60, overscan_mm=2)
    sh.layer_id = d.active_layer_id
    d.add_shape(sh)
    g = optimized_document_gcode(d, scan_offsets=None)
    assert "; SCAN ANGLE 30" in g and "; SCAN ANGLE 90" in g
    pi_check(g)
    est = estimate_gcode(g)
    assert est.total_time_s > 0
