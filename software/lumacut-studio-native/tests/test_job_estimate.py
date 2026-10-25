import math

import pytest

from _pi_guard import pi_check
from lumacut_canvas.export import JobLayer
from lumacut_canvas.gcode import layers_to_gcode
from lumacut_job.estimate import (convex_hull, estimate_gcode, format_duration, frame_gcode,
                                  job_bounds)


def test_long_straight_cut_is_near_length_over_feed():
    g = "G21\nG90\nM3 I\nG0 X30 Y30\nG1 X330 Y30 F3000 S100\nM5 I\n"
    e = estimate_gcode(g)
    assert e.cut_length_mm == pytest.approx(300)
    # 300 mm at 50 mm/s = 6 s plus a little acceleration overhead.
    assert 6.0 < e.cut_time_s < 6.2
    assert e.travel_length_mm == 0 and e.bounds == (30, 30, 330, 30)


def test_short_segments_are_acceleration_limited():
    g = "M3 I\nG0 X30 Y30\nG1 X31 Y30 F6000 S100\n"
    e = estimate_gcode(g)
    # 1 mm with 500 mm/s²: triangle profile 2*sqrt(1/500) ≈ 0.089 s (> 1/100 s).
    assert e.cut_time_s == pytest.approx(2 * math.sqrt(1 / 500), rel=1e-3)


def test_corners_slow_down_and_rapids_count_as_travel():
    square = "M3 I\nG0 X30 Y30\n" + "\n".join(
        f"G1 X{x} Y{y} F6000 S50" for x, y in ((130, 30), (130, 130), (30, 130), (30, 30)))
    smooth = "M3 I\nG0 X30 Y30\nG1 X430 Y30 F6000 S50\n"
    sq, line = estimate_gcode(square), estimate_gcode(smooth)
    assert sq.cut_length_mm == pytest.approx(line.cut_length_mm)
    assert sq.cut_time_s > line.cut_time_s + 0.5
    g = "M3 I\nG0 X30 Y30\nG1 X40 Y30 F600 S50\nG0 X190 Y30\nG1 X200 Y30 F600 S50\nM5 I\nM400"
    e = estimate_gcode(g)
    assert e.travel_length_mm == pytest.approx(150)
    assert 1.0 < e.travel_time_s < 1.4  # 150 mm at 150 mm/s + accel
    assert e.total_time_s == pytest.approx(e.cut_time_s + e.travel_time_s)


def test_z_moves_and_dwell():
    e = estimate_gcode("G0 X30 Y30\nG91\nG0 Z-0.9 F600\nG90\nG4 P500\n")
    assert e.dwell_time_s == pytest.approx(0.5)
    assert e.travel_length_mm == pytest.approx(0.9)


def test_format_duration():
    assert format_duration(42) == "42 s"
    assert format_duration(125) == "2 min 05 s"
    assert format_duration(3725) == "1 h 02 min"


def _layers():
    return [JobLayer("a", "A", 50, 1000, 1, [[(50, 60), (150, 60), (150, 90), (50, 60)],
                                              [(100, 40), (120, 70)]])]


def test_frame_box_is_laser_off_and_pi_safe():
    g = frame_gcode(_layers())
    lines = g.splitlines()
    assert "M3 I" not in lines and all(" S0" in l for l in lines if l.startswith("G1"))
    assert lines[4] == "G0 X50.000 Y40.000" and lines[-2:] == ["M5 I", "M400"]
    corners = {l.split(" F")[0] for l in lines if l.startswith("G1")}
    assert corners == {"G1 X150.000 Y40.000", "G1 X150.000 Y90.000", "G1 X50.000 Y90.000",
                       "G1 X50.000 Y40.000"}
    pi_check(g)
    assert estimate_gcode(g).cut_length_mm == 0  # nothing is lasered


def test_frame_hull_and_margin_and_clamp():
    hull = convex_hull([(0, 0), (10, 0), (5, 2), (10, 10), (0, 10)])
    assert sorted(hull) == [(0, 0), (0, 10), (10, 0), (10, 10)]
    g = frame_gcode(_layers(), mode="hull", loops=2)
    assert g.count("G1") == 2 * len(convex_hull([p for l in _layers() for q in l.polylines for p in q]))
    edge = [JobLayer("e", "E", 50, 1000, 1, [[(30, 30), (40, 40)]])]
    g = frame_gcode(edge, margin_mm=5)
    assert "G0 X30.000 Y30.000" in g  # clamped to the work area
    with pytest.raises(ValueError):
        frame_gcode([])
    with pytest.raises(ValueError):
        frame_gcode(_layers(), mode="circle")
    assert job_bounds(_layers()) == (50, 40, 150, 90)


def test_estimate_of_canvas_gcode():
    g = layers_to_gcode(_layers())
    e = estimate_gcode(g)
    assert e.cut_length_mm > 200 and e.moves > 3 and "min" in e.summary() or "s" in e.summary()
