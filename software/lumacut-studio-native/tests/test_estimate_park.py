"""Zeitschätzung mit Anfahrt aus der Park-Ecke und Parken nach dem Auftrag – Review-Runde 52."""

from __future__ import annotations

import pathlib
import re

import pytest

from lumacut_job.estimate import (DEFAULT_PARK, PARK_FEED, PARK_Z_MM, TRAVEL_Z_MM, Z_ACCEL,
                                  ParkRoutine, estimate_gcode)
from lumacut_job.motion import MotionProfile, set_active_motion

ROOT = pathlib.Path(__file__).resolve().parents[3]

# 150 mm along X from the park corner, a cut, back to the same point: X0/Y0 is 150 mm away
JOB = "G21\nG90\nM5 I\nM3 I\nG0 X150 Y0\nG1 X250 Y0 F3000 S100\nG0 X150 Y0\nM5 I\nM400\n"


def _move(L, v, a):
    """Rest-to-rest trapezoid / triangle (reference formula)."""
    d = v * v / a
    if d >= L:
        return 2 * (L / a) ** 0.5
    return 2 * v / a + (L - d) / v


LIFT = _move(TRAVEL_Z_MM - PARK_Z_MM, 9.0, Z_ACCEL)       # 19 mm at 9 mm/s, 100 mm/s²
XY150 = _move(150.0, 150.0, 500.0)                       # F9000 = 150 mm/s, 500 mm/s²


# --- mirrors of the Pi ---------------------------------------------------------------

def test_mirrors_match_the_pi_and_the_firmware():
    tr = (ROOT / "pi400" / "marlin" / "transport.py").read_text(encoding="utf-8")
    web = (ROOT / "pi400" / "marlin" / "web.py").read_text(encoding="utf-8")
    fw = (ROOT / "firmware" / "marlin" / "build.py").read_text(encoding="utf-8")
    assert float(re.search(r"^PARK_Z_MM = ([\d.]+)", tr, re.M).group(1)) == PARK_Z_MM
    assert float(re.search(r'"park_z_mm": ([\d.]+)', web).group(1)) == PARK_Z_MM
    assert float(re.search(r'"z_clearance_mm": ([\d.]+)', web).group(1)) == TRAVEL_Z_MM
    assert f'"G0 X0.000 Y0.000 F{PARK_FEED:g}"' in tr          # park_safezone
    assert '"DEFAULT_MAX_ACCELERATION", "{ 500, 500, %g }"' % Z_ACCEL in fw
    # every job: drain, then park (the worker parks once at the end)
    assert 'machine.drain(owner="job")\n    _set_phase("parking")\n    machine.park_safezone(owner="job")' in web


# --- model ---------------------------------------------------------------------------

def test_approach_and_return_are_added_to_the_total():
    e = estimate_gcode(JOB)
    plain = estimate_gcode(JOB, park=False)
    assert e.park_included and not plain.park_included
    assert e.approach_length_mm == pytest.approx(150) and e.park_length_mm == pytest.approx(150)
    assert e.approach_time_s == pytest.approx(LIFT + XY150, rel=1e-9)
    assert e.park_time_s == pytest.approx(XY150 + LIFT, rel=1e-9)     # no Z in the job: no lift back
    assert e.routine_time_s == pytest.approx(2 * (LIFT + XY150))
    assert LIFT == pytest.approx(2.2011, abs=1e-3) and XY150 == pytest.approx(1.3)
    # the G-code part is unchanged
    for f in ("cut_time_s", "travel_time_s", "cut_length_mm", "travel_length_mm", "dwell_time_s"):
        assert getattr(e, f) == getattr(plain, f)
    assert e.total_time_s == pytest.approx(plain.total_time_s + e.routine_time_s)
    assert plain.total_time_s == pytest.approx(plain.program_time_s)
    assert plain.approach_time_s == plain.park_time_s == 0.0


def test_summary_and_scope_note():
    e = estimate_gcode(JOB)
    assert e.summary().endswith(" · Anfahrt/Parken 7 s")
    assert e.scope_note() == "mit Anfahrt aus der Park-Ecke und Parken, ohne Referenzfahrt/Abtasten"
    plain = estimate_gcode(JOB, park=False)
    assert "Anfahrt" not in plain.summary()
    assert plain.scope_note() == "ohne Referenzfahrt/Fokus/Parken"


def test_layers_stay_the_gcode_time():
    g = JOB.replace("M3 I\n", "M3 I\n; LAYER Schnitt\n")
    e = estimate_gcode(g)
    assert e.layers == [("Schnitt", pytest.approx(e.program_time_s))]
    assert e.layer_summary() == ""


def test_diagonal_return_and_per_axis_limit():
    g = "M3 I\nG0 X100 Y100\nG1 X300 Y300 F3000 S100\nM5 I\n"
    e = estimate_gcode(g)
    # 45° at F9000: the path speed 150 mm/s keeps both axes at 106 mm/s (< 150)
    assert e.approach_time_s == pytest.approx(LIFT + _move(2 ** 0.5 * 100, 150, 500), rel=1e-9)
    assert e.park_length_mm == pytest.approx(2 ** 0.5 * 300)
    assert e.park_time_s == pytest.approx(_move(2 ** 0.5 * 300, 150, 500) + LIFT, rel=1e-9)


def test_first_move_feed_and_z():
    slow = estimate_gcode("M3 I\nG0 X150 Y0 F3000\nG1 X200 Y0 F3000 S10\nM5 I\n")
    assert slow.approach_time_s == pytest.approx(LIFT + _move(150, 50, 500), rel=1e-9)
    # a first move with Z: the Pi does not lift first (the move sets the height itself)
    withz = estimate_gcode("M3 I\nG0 X150 Y0 Z20\nG1 X200 Y0 F3000 S10\nM5 I\n")
    assert withz.approach_time_s == pytest.approx(XY150, rel=1e-9)


def test_lift_back_after_a_lowered_head():
    rel = estimate_gcode("M3 I\nG0 X150 Y0\nG91\nG0 Z-5 F600\nG90\nG1 X200 Y0 F3000 S10\n"
                         "G0 X150 Y0\nM5 I\n")
    assert rel.park_time_s == pytest.approx(_move(5, 9, Z_ACCEL) + XY150 + LIFT, rel=1e-9)
    absz = estimate_gcode("M3 I\nG0 X150 Y0\nG0 Z3\nG1 X200 Y0 F3000 S10\nG0 X150 Y0\nM5 I\n")
    assert absz.park_time_s == pytest.approx(_move(17, 9, Z_ACCEL) + XY150 + LIFT, rel=1e-9)
    # head above the travel height at the end: no extra lift, the Pi lowers
    # from there (park_safezone keeps the higher Z for the park move; round 53)
    high = estimate_gcode("M3 I\nG0 X150 Y0\nG0 Z30\nG1 X200 Y0 F3000 S10\nG0 X150 Y0\nM5 I\n")
    assert high.park_time_s == pytest.approx(XY150 + _move(29, 9, Z_ACCEL), rel=1e-9)


def test_motion_calibration_and_z_speed_apply():
    base = estimate_gcode(JOB)
    set_active_motion(MotionProfile(2100.0, 200.0, 6.0, "pi"))
    cal = estimate_gcode(JOB)
    assert cal.approach_time_s == pytest.approx(
        _move(19, 6.0, Z_ACCEL) + _move(150, 150, 2100), rel=1e-9)     # F9000 still caps XY
    assert cal.park_time_s == pytest.approx(_move(150, 150, 2100) + _move(19, 6.0, Z_ACCEL), rel=1e-9)
    assert cal.approach_time_s - _move(19, 6.0, Z_ACCEL) < base.approach_time_s - LIFT   # faster XY


def test_custom_routine_and_switches():
    low = estimate_gcode(JOB, park=ParkRoutine(park_z=0.0))            # parks at travel height
    assert low.approach_time_s == pytest.approx(XY150, rel=1e-9)
    assert low.park_time_s == pytest.approx(XY150, rel=1e-9)
    assert ParkRoutine(park_z=0.0).lift_mm == 0.0 and DEFAULT_PARK.lift_mm == pytest.approx(19)
    tall = estimate_gcode(JOB, park=ParkRoutine(travel_z=30.0))
    assert tall.approach_time_s == pytest.approx(_move(29, 9, Z_ACCEL) + XY150, rel=1e-9)
    assert estimate_gcode(JOB, park=None).routine_time_s == 0.0


def test_no_move_no_routine():
    for g in ("", "G21\nG90\nM5 I\n", "G4 P500\n"):
        e = estimate_gcode(g)
        assert not e.park_included and e.routine_time_s == 0.0
        assert e.scope_note() == "ohne Referenzfahrt/Fokus/Parken"
        assert "Anfahrt" not in e.summary()


def test_canvas_job_gets_the_routine():
    from lumacut_canvas.export import JobLayer
    from lumacut_canvas.gcode import layers_to_gcode
    g = layers_to_gcode([JobLayer("a", "A", 50, 1000, 1,
                                  [[(150, 160), (250, 160), (250, 190), (150, 160)]])])
    e = estimate_gcode(g)
    assert e.approach_length_mm == pytest.approx((150 ** 2 + 160 ** 2) ** 0.5)
    assert e.park_length_mm == pytest.approx(e.approach_length_mm)   # closed outline ends at its start
    assert 7.0 < e.routine_time_s < 9.0


def test_history_summary_names_the_routine():
    from lumacut_job.history_qt import _summary
    assert "Anfahrt/Parken" in _summary(JOB)


# --- app ------------------------------------------------------------------------------

def test_main_window_preview_and_estimate_include_parking(qapp, tmp_path, monkeypatch):
    from PySide6.QtCore import QSettings
    monkeypatch.setenv("LUMACUT_MOTION_SETTINGS", str(tmp_path / "motion.ini"))
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(tmp_path))
    QSettings.setDefaultFormat(QSettings.IniFormat)
    main = pytest.importorskip("main")
    from lumacut_canvas.model import Geometry, Layer, Shape
    from lumacut_job.motion import remove_motion_listener
    win = main.LumaCutStudio()
    try:
        ed = win.canvas
        lid = ed.document.add_layer(Layer(name="Schnitt", power=20.0, speed=3000.0, passes=1)).id
        ed.document.add_shape(Shape("rect", Geometry(20, 20, 100, 80), lid))
        pv = ed.path_preview
        ed.set_path_preview(True)
        est = pv.estimate
        assert est.park_included and est.routine_time_s > 3.0
        assert est.total_time_s == pytest.approx(est.program_time_s + est.routine_time_s)
        tip = ed.path_preview_bar.readout.toolTip()
        assert "Zeit mit Anfahrt aus der Park-Ecke und Parken, ohne Referenzfahrt/Abtasten" in tip
        win.job_tools.show_estimate()
        msg = win.statusBar().currentMessage()
        assert "Anfahrt/Parken" in msg
        assert "(mit Anfahrt aus der Park-Ecke und Parken, ohne Referenzfahrt/Abtasten)" in msg
    finally:
        ed.undo_stack.setClean()
        win.close()
        remove_motion_listener(win.job_tools.motion_refresh)
