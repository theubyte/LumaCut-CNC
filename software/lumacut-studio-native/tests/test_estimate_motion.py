"""Zeitschätzung mit den Bewegungsgrenzen des Pi (config.motion) – Review-Runde 49."""

from __future__ import annotations

import math

import pytest
from PySide6.QtCore import QSettings

from lumacut_job import motion as mo
from lumacut_job.estimate import ACCEL_XY, MAX_XY, MAX_Z, estimate_gcode
from lumacut_job.motion import (DEFAULT, PI, PI_FIRMWARE, SAVED, MotionProfile, MotionSync,
                                active_motion, add_motion_listener, load_saved,
                                motion_from_status, remove_motion_listener, set_active_motion)

LINE = "G21\nG90\nM3 I\nG0 X30 Y30\nG1 X330 Y30 F12000 S100\nM5 I\n"     # 300 mm, F12000 = 200 mm/s
SHORT = "M3 I\nG0 X30 Y30\nG1 X31 Y30 F6000 S100\n"
DIAG = "M3 I\nG0 X30 Y30\nG1 X330 Y330 F12000 S100\n"                     # 45°, wants 200 mm/s


def _status(motion=None, z=None, **cfg):
    config = dict(cfg)
    if motion is not ...:
        config["motion"] = motion
    if z is not None:
        config["z_speed_mm_s"] = z
    return {"firmware": "marlin", "connected": True, "config": config}


class _Store:
    def __init__(self):
        self.data, self.synced = {}, 0

    def value(self, key, default=None):
        return self.data.get(key, default)

    def setValue(self, key, value):
        self.data[key] = value

    def sync(self):
        self.synced += 1


# --- defaults and model ------------------------------------------------------

def test_defaults_are_the_firmware_values():
    assert active_motion() == DEFAULT and DEFAULT.is_default
    assert (ACCEL_XY, MAX_XY, MAX_Z) == (500.0, 150.0, 9.0)
    e = estimate_gcode(SHORT)
    assert e.cut_time_s == pytest.approx(2 * math.sqrt(1 / 500), rel=1e-3)
    assert e.motion == DEFAULT
    assert e.motion_note() == "Bewegung: Firmware-Standard 500 mm/s², 150 mm/s"


def test_active_profile_drives_accel_and_speed():
    slow = estimate_gcode(LINE)
    # trapezoid from rest to rest: L / v + v / a
    assert slow.cut_time_s == pytest.approx(300 / 150 + 150 / 500)       # capped at 150 mm/s
    set_active_motion(MotionProfile(2100.0, 200.0, 9.0, PI))
    fast = estimate_gcode(LINE)
    assert fast.cut_time_s == pytest.approx(300 / 200 + 200 / 2100)
    assert estimate_gcode(SHORT).cut_time_s == pytest.approx(2 * math.sqrt(1 / 2100), rel=1e-3)
    assert fast.motion.source == PI and "Pi-Kalibrierung 2100 mm/s², 200 mm/s" in fast.motion_note()
    # lengths never change, only times
    assert fast.cut_length_mm == slow.cut_length_mm


def test_explicit_arguments_still_win():
    set_active_motion(MotionProfile(2100.0, 200.0, 9.0, PI))
    e = estimate_gcode(SHORT, accel=500)
    assert e.cut_time_s == pytest.approx(2 * math.sqrt(1 / 500), rel=1e-3)
    assert e.motion.source == mo.EXPLICIT and e.motion.speed == 200.0
    assert e.motion_note().startswith("Bewegung: Vorgabe 500 mm/s²")
    other = estimate_gcode(SHORT, motion=MotionProfile(1000.0, 100.0))
    assert other.cut_time_s == pytest.approx(2 * math.sqrt(1 / 1000), rel=1e-3)


def test_per_axis_feed_limit_on_diagonals():
    """Marlin limits each axis (M203 X Y): a 45° move may run speed·√2 along the path."""
    straight = estimate_gcode(LINE)
    diag = estimate_gcode(DIAG)
    L = 300 * math.sqrt(2)
    assert diag.cut_length_mm == pytest.approx(L)
    # 200 mm/s requested: path speed ≤ 150·√2 = 212 → the F wins (200 mm/s)
    assert diag.cut_time_s == pytest.approx(L / 200 + 200 / 500)
    assert straight.cut_time_s == pytest.approx(300 / 150 + 150 / 500)
    # a 30° move: X component cos30 ≈ 0.866 → path limit 150 / 0.866 ≈ 173 mm/s
    dx, dy = 300 * math.cos(math.radians(30)), 300 * math.sin(math.radians(30))
    g = f"M3 I\nG0 X30 Y30\nG1 X{30 + dx:.4f} Y{30 + dy:.4f} F12000 S100\n"
    e = estimate_gcode(g)
    v = 150 / math.cos(math.radians(30))
    assert e.cut_time_s == pytest.approx(300 / v + v / 500, rel=1e-3)


def test_axis_aligned_and_default_rapids_unchanged():
    """Default rapids (F9000 = 150 mm/s) and X/Y moves keep their old times."""
    g = "M3 I\nG0 X30 Y30\nG1 X40 Y30 F600 S50\nG0 X190 Y180\nG1 X200 Y180 F600 S50\nM5 I\n"
    e = estimate_gcode(g)
    L = math.hypot(150, 150)
    assert e.travel_length_mm == pytest.approx(L)
    assert L / 150 < e.travel_time_s < L / 150 + 0.4


def test_z_speed_from_profile():
    g = "G0 X30 Y30\nG91\nG0 Z-6 F600\nG90\n"
    assert estimate_gcode(g).travel_time_s == pytest.approx(6 / 9, rel=0.2)
    set_active_motion(MotionProfile(500.0, 150.0, 3.0, PI))
    assert estimate_gcode(g).travel_time_s > 6 / 3


# --- status parsing ------------------------------------------------------------

def test_motion_from_status():
    p = motion_from_status(_status({"accel": 2100, "speed": 200}, z=9))
    assert p == MotionProfile(2100.0, 200.0, 9.0, PI)
    assert p.label() == "Pi-Kalibrierung 2100 mm/s², 200 mm/s"
    # null motion (not calibrated): firmware values, but known to come from the Pi
    p = motion_from_status(_status(None))
    assert p.same_limits(DEFAULT) and p.source == PI_FIRMWARE
    assert p.label().startswith("Pi ohne Kalibrierung (Firmware) 500")
    # Atomstack board, already capped by the Pi
    assert motion_from_status(_status({"accel": 1000, "speed": 100})).speed == 100.0
    # Z: capped at the firmware's 9 mm/s, slower is kept and shown
    assert motion_from_status(_status({"accel": 900, "speed": 120}, z=20)).z_speed == 9.0
    slow_z = motion_from_status(_status({"accel": 900, "speed": 120}, z=4))
    assert slow_z.z_speed == 4.0 and slow_z.label().endswith("Z 4 mm/s")


@pytest.mark.parametrize("motion", [
    {"accel": 50, "speed": 200}, {"accel": 2000, "speed": 900}, {"accel": "x", "speed": 100},
    {"accel": 2000}, {"accel": True, "speed": 100}, {"accel": float("nan"), "speed": 100}, "kaputt"])
def test_invalid_motion_means_firmware(motion):
    p = motion_from_status(_status(motion))
    assert p.same_limits(DEFAULT) and p.source == PI_FIRMWARE


def test_status_without_config_keeps_the_current_limits():
    assert motion_from_status({"firmware": "marlin", "connected": True}) is None
    assert motion_from_status({"config": "x"}) is None
    assert motion_from_status(None) is None
    from machine.client import MachineStatus
    st = MachineStatus.from_json(_status({"accel": 3000, "speed": 250}))
    assert motion_from_status(st.raw) == MotionProfile(3000.0, 250.0, 9.0, PI)


# --- active profile, listeners, persistence -----------------------------------------

def test_listeners_fire_only_on_a_real_change():
    seen = []
    add_motion_listener(seen.append)
    try:
        assert set_active_motion(MotionProfile(2100.0, 200.0, 9.0, PI))
        assert not set_active_motion(MotionProfile(2100.0, 200.0, 9.0, SAVED))
        assert active_motion().source == SAVED            # source updated silently
        assert set_active_motion(None)
        assert [p.accel for p in seen] == [2100.0, 500.0]
    finally:
        remove_motion_listener(seen.append)
    set_active_motion(MotionProfile(1000.0, 100.0))
    assert len(seen) == 2


def test_sync_applies_and_stores_the_pi_calibration():
    store = _Store()
    sync = MotionSync(None, store=store)
    assert active_motion() == DEFAULT                    # nothing saved yet
    p = sync.on_status(_status({"accel": 2100, "speed": 200}))
    assert active_motion() == p and p.source == PI
    assert load_saved(store) == MotionProfile(2100.0, 200.0, 9.0, SAVED)
    writes = store.synced
    sync.on_status(_status({"accel": 2100, "speed": 200}))   # every poll: no extra write
    assert store.synced == writes
    assert sync.on_status({"firmware": "marlin", "connected": True}) is None
    assert active_motion().accel == 2100.0                # reduced answer keeps it
    # next start, offline: the stored calibration is used
    set_active_motion(None)
    MotionSync(None, store=store)
    assert active_motion() == MotionProfile(2100.0, 200.0, 9.0, SAVED)
    assert "zuletzt gesehen" in estimate_gcode(LINE).motion_note()
    # calibration reset on the Pi: firmware values, nothing stale comes back
    sync.on_status(_status(None))
    assert active_motion().same_limits(DEFAULT)
    assert load_saved(store) is None
    set_active_motion(MotionProfile(1000.0, 100.0))
    MotionSync(None, store=store)
    assert active_motion().accel == 1000.0               # no saved calibration applied


def test_load_saved_rejects_garbage():
    store = _Store()
    store.data.update({"estimate/motion_accel": "abc", "estimate/motion_speed": 200})
    assert load_saved(store) is None
    store.data.update({"estimate/motion_accel": "2100", "estimate/motion_speed": "200",
                       "estimate/motion_z_speed": "99"})
    assert load_saved(store) == MotionProfile(2100.0, 200.0, 9.0, SAVED)    # z out of range


def test_default_store_honours_the_test_ini(tmp_path, monkeypatch):
    path = tmp_path / "m.ini"
    monkeypatch.setenv("LUMACUT_MOTION_SETTINGS", str(path))
    store = mo.default_store()
    mo.save(store, MotionProfile(1500.0, 180.0, 9.0, PI))
    again = QSettings(str(path), QSettings.IniFormat)
    assert load_saved(again) == MotionProfile(1500.0, 180.0, 9.0, SAVED)


# --- app wiring ---------------------------------------------------------------------

def test_main_window_follows_the_pi_and_re_estimates_the_preview(qapp, tmp_path, monkeypatch):
    monkeypatch.setenv("LUMACUT_MOTION_SETTINGS", str(tmp_path / "motion.ini"))
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(tmp_path))
    QSettings.setDefaultFormat(QSettings.IniFormat)
    main = pytest.importorskip("main")
    from machine.client import MachineStatus
    from lumacut_canvas.model import Geometry, Layer, Shape
    win = main.LumaCutStudio()
    try:
        ed = win.canvas
        lid = ed.document.add_layer(Layer(name="Schnell", power=20.0, speed=12000.0, passes=1)).id
        ed.document.add_shape(Shape("rect", Geometry(20, 20, 200, 150), lid))
        pv = ed.path_preview
        ed.set_path_preview(True)
        before = pv.estimate.total_time_s
        gcode = pv.gcode
        assert "Firmware-Standard" in ed.path_preview_bar.readout.toolTip()
        win.machine_panel.status_changed.emit(
            MachineStatus.from_json(_status({"accel": 2100, "speed": 200})))
        assert active_motion().source == PI and active_motion().accel == 2100.0
        assert pv.gcode == gcode and not pv.pending()          # only the time is re-estimated
        assert pv.estimate.total_time_s < before
        assert "Pi-Kalibrierung 2100 mm/s², 200 mm/s" in ed.path_preview_bar.readout.toolTip()
        win.job_tools.show_estimate()
        msg = win.statusBar().currentMessage()
        assert "Bewegung: Pi-Kalibrierung 2100 mm/s², 200 mm/s" in msg
        assert load_saved(QSettings(str(tmp_path / "motion.ini"), QSettings.IniFormat)).accel == 2100.0
    finally:
        ed.undo_stack.setClean()
        win.close()
        remove_motion_listener(win.job_tools.motion_refresh)
