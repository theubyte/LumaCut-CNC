"""Höhenkarte und Relief-G-Code (Pi-/Marlin-Regeln)."""

import re

import numpy as np
import pytest
from _pi_guard import pi_check

from lumacut_materials import load_db, plan_relief
from lumacut_materials.heightmap import (HeightmapOptions, adjust, heightmap_from_gray,
                                         heightmap_from_image, resample, to_gray)
from lumacut_materials.relief import ReliefJob, job_from_plan, layer_fractions, relief_to_gcode

# Regeln aus pi400/marlin/transport.py
LINE = re.compile(r"^(;[\x20-\x7E]*|G21|G90|G91|M3 I|M5 I|M400|G0 X\d+\.\d{3} Y\d+\.\d{3}|"
                  r"G0 Z-?\d+\.\d{3} F600|G1 X\d+\.\d{3} Y\d+\.\d{3} F\d+(\.\d+)? S\d+)$")


def _dome(n=60):
    yy, xx = np.mgrid[0:n, 0:n]
    return np.clip(np.hypot(xx - n / 2, yy - n / 2) / (n / 2), 0, 1)  # Mitte schwarz = tief


def test_heightmap_resample_and_depth():
    g = np.tile(np.linspace(0, 1, 200), (100, 1))
    hm = heightmap_from_gray(g, HeightmapOptions(width_mm=20, line_interval_mm=0.1, depth_mm=2))
    assert (hm.rows, hm.cols) == (100, 200)
    assert hm.width_mm == pytest.approx(20) and hm.height_mm == pytest.approx(10)
    assert hm.depth[0, 0] == pytest.approx(2, abs=0.02) and hm.depth[0, -1] == pytest.approx(0, abs=0.02)
    hm2 = heightmap_from_gray(g, HeightmapOptions(width_mm=20, height_mm=5, line_interval_mm=0.25,
                                                  depth_mm=1))
    assert (hm2.rows, hm2.cols) == (20, 80)
    assert hm2.max_depth_mm <= 1.0


def test_resample_preserves_mean():
    rng = np.random.default_rng(1)
    g = rng.random((97, 131))
    assert resample(g, 30, 40).mean() == pytest.approx(g.mean(), abs=0.01)
    assert resample(g, 200, 300).shape == (200, 300)


def test_adjust_invert_gamma_contrast():
    g = np.array([[0.0, 0.5, 1.0]])
    o = HeightmapOptions(width_mm=1)
    assert np.allclose(adjust(g, o), g)
    o.invert = True
    assert np.allclose(adjust(g, o), [[1, 0.5, 0]])
    o.invert, o.gamma = False, 2.0
    assert adjust(g, o)[0, 1] > 0.5  # Mitteltöne heller = flacher
    o.gamma, o.contrast = 1.0, 2.0
    assert np.allclose(adjust(g, o), [[0, 0.5, 1]])
    o.contrast = 0.0
    assert np.allclose(adjust(g, o), 0.5)


def test_blur_smooths_steps():
    g = np.zeros((40, 40))
    g[:, 20:] = 1
    sharp = heightmap_from_gray(g, HeightmapOptions(width_mm=4, line_interval_mm=0.1, depth_mm=1))
    soft = heightmap_from_gray(g, HeightmapOptions(width_mm=4, line_interval_mm=0.1, depth_mm=1,
                                                   blur_mm=0.3))
    assert np.abs(np.diff(soft.depth, axis=1)).max() < np.abs(np.diff(sharp.depth, axis=1)).max()


def test_to_gray_alpha_is_white():
    bgra = np.zeros((2, 2, 4), dtype=np.uint8)
    bgra[0, 0, 3] = 255  # deckend schwarz
    g = to_gray(bgra)
    assert g[0, 0] == 0 and g[1, 1] == 1


def test_heightmap_from_image_file(tmp_path):
    cv2 = pytest.importorskip("cv2")
    img = (np.tile(np.linspace(0, 255, 50), (30, 1))).astype(np.uint8)
    p = tmp_path / "höhe.png"
    ok, buf = cv2.imencode(".png", img)
    buf.tofile(str(p))
    hm = heightmap_from_image(p, HeightmapOptions(width_mm=5, line_interval_mm=0.1, depth_mm=1))
    assert hm.cols == 50 and hm.rows == 30


def test_layer_fractions_sum_to_depth():
    d = np.array([[0.0, 0.3, 1.0, 2.0]])
    total = sum(layer_fractions(d, 4, k) for k in range(4))
    assert np.allclose(total * 0.5, d)  # Schichtdicke 0,5 mm


def test_relief_gcode_follows_pi_rules():
    db = load_db()
    hm = heightmap_from_gray(_dome(), HeightmapOptions(width_mm=12, line_interval_mm=0.2,
                                                      depth_mm=2.0, blur_mm=0.2))
    plan = plan_relief(db, "basswood_solid", 2.0)
    job = job_from_plan(plan, hm, 0.0, 0.0)
    code, stats = relief_to_gcode(job)
    lines = code.splitlines()
    bad = [l for l in lines if not LINE.match(l) or len(l) > 96]
    assert not bad, bad[:5]
    assert lines.count("M3 I") == 1 and not any(l.startswith("M4 ") for l in lines) and lines[-2:] == ["M5 I", "M400"]
    s = [int(v) for v in re.findall(r" S(\d+)", code)]
    assert max(s) <= 255 and min(s) >= 0 and len(set(s)) > 4  # variable Leistung
    # Erstes G1 nach jedem G0 hat S (immer); G0 nie mit S
    assert not any(l.startswith("G0") and " S" in l for l in lines)
    # Safezone: alle XY ≥ 30
    xs = [float(v) for v in re.findall(r"X(\d+\.\d+)", code)]
    ys = [float(v) for v in re.findall(r"Y(\d+\.\d+)", code)]
    assert min(xs) >= 30 and min(ys) >= 30
    # Z: vor dem ersten Schnitt keine Z-Fahrt, Summe der Absenkungen wird zurückgefahren
    first_g1 = next(i for i, l in enumerate(lines) if l.startswith("G1"))
    assert not any(" Z" in l for l in lines[:first_g1])
    z = [float(v) for v in re.findall(r"G0 Z(-?\d+\.\d+)", code)]
    assert sum(z) == pytest.approx(0, abs=1e-6)
    assert -sum(v for v in z if v < 0) <= 3.0
    assert stats.passes == plan.passes + 1 and "; FINISH" in code
    assert "(Y)" in code  # Achsen wechseln
    assert stats.est_seconds > 0 and stats.burn_mm > 0
    pi_check(code)  # echter MarlinLaserGuard des Pi


def test_relief_rejects_out_of_area_and_too_much_drop():
    hm = heightmap_from_gray(_dome(20), HeightmapOptions(width_mm=10, line_interval_mm=0.5))
    with pytest.raises(ValueError):
        relief_to_gcode(ReliefJob(hm, x_mm=355, y_mm=0, layers=2, speed_mm_min=1000))
    with pytest.raises(ValueError):
        relief_to_gcode(ReliefJob(hm, x_mm=0, y_mm=0, layers=5, speed_mm_min=1000, z_step_mm=1.0))
    with pytest.raises(ValueError):
        relief_to_gcode(ReliefJob(hm, x_mm=0, y_mm=0, layers=2, speed_mm_min=1000, flavor="m4"))


def test_relief_overscan_stays_in_work_area():
    hm = heightmap_from_gray(_dome(20), HeightmapOptions(width_mm=10, line_interval_mm=0.5))
    code, _ = relief_to_gcode(ReliefJob(hm, x_mm=350, y_mm=330, layers=2, speed_mm_min=1000,
                                        overscan_mm=5))
    xs = [float(v) for v in re.findall(r"X(\d+\.\d+)", code)]
    ys = [float(v) for v in re.findall(r"Y(\d+\.\d+)", code)]
    assert max(xs) <= 390 and max(ys) <= 370


def test_grbl_flavor_uses_m4_and_1000_scale():
    hm = heightmap_from_gray(_dome(20), HeightmapOptions(width_mm=10, line_interval_mm=0.5))
    code, _ = relief_to_gcode(ReliefJob(hm, x_mm=0, y_mm=0, layers=2, speed_mm_min=1000,
                                        flavor="grbl_m4", finish=False))
    assert "M4 S0" in code and "M3 I" not in code
    assert max(int(v) for v in re.findall(r" S(\d+)", code)) == 1000
