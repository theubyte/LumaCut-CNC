import re

import numpy as np
import pytest

from _pi_guard import pi_check
from lumacut_job.estimate import estimate_gcode
from lumacut_job.raster import (RasterSettings, depth_slices, power_map, raster_gcode, resample,
                                scanlines, sliced_depth_gcode)


def gradient(w=40, h=10):
    return np.tile(np.linspace(0, 255, w).astype(np.uint8), (h, 1))


@pytest.mark.parametrize("mode", ["threshold", "floyd", "atkinson", "ordered", "grayscale"])
def test_modes_produce_pi_safe_gcode(mode):
    s = RasterSettings(mode=mode, line_interval_mm=0.5, power=80)
    g = raster_gcode(gradient(), (50, 50), 20, 5, s)
    pi_check(g)
    vals = [int(v) for v in re.findall(r" S(\d+)", g)]
    assert max(vals) <= 204 and min(vals) == 0
    if mode == "grayscale":
        assert len(set(vals)) > 5
    else:
        assert set(vals) <= {0, 204}


def test_dither_keeps_average_darkness():
    s = RasterSettings(mode="floyd", power=100)
    img = np.full((20, 20), 191, dtype=np.uint8)  # 25 % dark
    on = power_map(img, s) > 0
    assert 0.2 < on.mean() < 0.3


def test_bidirectional_overscan_and_offset():
    s = RasterSettings(mode="threshold", line_interval_mm=1, overscan_mm=2, scan_offset_mm=0.5)
    pm = np.array([[0, 255, 255, 0], [0, 255, 255, 0]])
    lines = scanlines(pm, (100, 100), s)
    assert lines[:4] == ["G0 X99.000 Y100.500", "G1 X101.000 Y100.500 F3000 S0",
                         "G1 X103.000 Y100.500 F3000 S255", "G1 X105.000 Y100.500 F3000 S0"]
    # Reverse line: starts right, shifted by +0.5 mm.
    assert lines[4] == "G0 X105.500 Y101.500" and lines[6] == "G1 X101.500 Y101.500 F3000 S255"
    s.bidirectional = False
    assert scanlines(pm, (100, 100), s)[4].startswith("G0 X99.000")


def test_raster_rejects_outside_work_area_and_empty():
    with pytest.raises(ValueError):
        raster_gcode(gradient(), (31, 50), 20, 5, RasterSettings(overscan_mm=5))
    with pytest.raises(ValueError):
        raster_gcode(np.full((5, 5), 255, np.uint8), (50, 50), 5, 5, RasterSettings())


def test_resample_size():
    assert resample(gradient(), 20, 5, 0.25).shape == (20, 80)


def test_depth_slices_more_passes_where_dark():
    h = np.array([[0, 128, 255]], dtype=np.uint8)
    masks = depth_slices(h, 4)
    passes = sum(m.astype(int) for m in masks)[0]
    assert list(passes) == [4, 2, 0]


def test_sliced_depth_gcode_with_z_step_is_pi_safe():
    hm = np.tile(np.linspace(0, 255, 20).astype(np.uint8), (8, 1))
    s = RasterSettings(line_interval_mm=0.5, power=70, speed_mm_min=4000)
    g = sliced_depth_gcode(hm, (60, 60), 10, 4, s, levels=4, z_step_mm=0.2)
    pi_check(g)
    assert g.count("; SLICE") == 4
    assert g.count("G0 Z-0.200 F600") == 3 and "G0 Z0.600 F600" in g
    e = estimate_gcode(g)
    assert e.cut_time_s > 0 and e.bounds[0] >= 60
    with pytest.raises(ValueError):
        sliced_depth_gcode(hm, (60, 60), 10, 4, s, levels=20, z_step_mm=0.5)
    # Odd slices go bottom-up, still inside the image rows.
    ys = [float(y) for y in re.findall(r"Y(\d+\.\d+)", g)]
    assert min(ys) >= 60 and max(ys) <= 64
