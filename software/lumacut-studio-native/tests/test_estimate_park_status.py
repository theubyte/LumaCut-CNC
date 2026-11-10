"""Zeitschätzung: Fahr-/Parkhöhe aus dem Pi-Status, Anfahrt ab Kopfposition und
Platzierung am Ursprung – Review-Runde 53."""

from __future__ import annotations

import pathlib
import re

import pytest
from PySide6.QtCore import QObject, QSettings, Signal

from lumacut_job import park_routine as pr
from lumacut_job.estimate import estimate_gcode
from lumacut_job.park_routine import (DEFAULT_PARK, DEFAULT_START, PI, SAVED, JobStart, ParkRoutine,
                                      ParkSync, active_park, active_start, add_park_listener,
                                      load_saved, remove_park_listener, routine_from_status,
                                      set_active_park, set_active_start, start_from_status)

ROOT = pathlib.Path(__file__).resolve().parents[3]

# 150 mm along X from the park corner, a cut, back to the same point (as in test_estimate_park)
JOB = "G21\nG90\nM5 I\nM3 I\nG0 X150 Y0\nG1 X250 Y0 F3000 S100\nG0 X150 Y0\nM5 I\nM400\n"


def _move(L, v, a):
    d = v * v / a
    if d >= L:
        return 2 * (L / a) ** 0.5
    return 2 * v / a + (L - d) / v


def _xy(L):
    return _move(L, 150.0, 500.0)      # F9000 capped at the firmware 150 mm/s, 500 mm/s²


def _z(L):
    return _move(L, 9.0, 100.0)


def _status(**top):
    cfg = top.pop("config", {"z_clearance_mm": 20.0, "park_z_mm": 1.0})
    return {"firmware": "marlin", "connected": True, "config": cfg, **top}


class _Store:
    def __init__(self):
        self.data, self.synced = {}, 0

    def value(self, key, default=None):
        return self.data.get(key, default)

    def setValue(self, key, value):
        self.data[key] = value

    def sync(self):
        self.synced += 1


# --- what the Pi reports ---------------------------------------------------------------

def test_the_pi_reports_these_fields():
    web = (ROOT / "pi400" / "marlin" / "web.py").read_text(encoding="utf-8")
    tr = (ROOT / "pi400" / "marlin" / "transport.py").read_text(encoding="utf-8")
    assert "travel_z_mm=round(machine.travel_z, 2)" in web              # /api/status
    assert "config=_status_config()" in web and "cfg = dict(config)" in web
    assert '"probe_minimum_z": (None if self.surface_z is None else' in tr
    assert '"position": self.position' in tr
    assert re.search(r"self\.material_mm \+ TRAVEL_GAP_MM", tr)        # material + 20 mm
    assert float(re.search(r"^TRAVEL_GAP_MM = ([\d.]+)", tr, re.M).group(1)) == 20.0
    assert float(re.search(r"^Z_MAX_MM = ([\d.]+)", tr, re.M).group(1)) == pr.Z_MAX_MM
    assert 'number("park_z_mm", 0, 20,' in web and pr.PARK_Z_RANGE == (0.0, 20.0)
    assert 'number("z_clearance_mm", 0.5, 50,' in web and pr.CLEARANCE_RANGE == (0.5, 50.0)
    # park_safezone: never below the current Z, the travel height or the probe minimum
    assert "z_target = max(self.position[2], self.travel_z," in tr
    # the head lifts only when it sits low in the park corner
    assert "if not self.parked_low or not _XY_MOTION.match(cmd):" in tr


def test_routine_from_status():
    r = routine_from_status(_status(travel_z_mm=26.0, config={"z_clearance_mm": 20.0, "park_z_mm": 2.0}))
    assert r == ParkRoutine(park_z=2.0, travel_z=26.0, source=PI)
    # older answer without travel_z_mm: the configured clearance
    assert routine_from_status(_status(config={"z_clearance_mm": 12.5})).travel_z == 12.5
    assert routine_from_status(_status(config={"z_clearance_mm": 12.5})).park_z == 1.0
    # park height 0 = stays at the travel height
    assert routine_from_status(_status(config={"park_z_mm": 0})).lift_mm == 0.0
    # probe minimum after probing a surface
    assert routine_from_status(_status(probe_minimum_z=33.0)).min_park_lift_z == 33.0
    # garbage falls back to the defaults, a reduced answer keeps what is known
    bad = routine_from_status(_status(travel_z_mm="x", probe_minimum_z=True,
                                      config={"z_clearance_mm": 99, "park_z_mm": -3}))
    assert bad.same_heights(DEFAULT_PARK)
    assert routine_from_status({"firmware": "marlin", "connected": True}) is None
    assert routine_from_status(None) is None
    assert routine_from_status({"travel_z_mm": 30}).travel_z == 30.0


# --- estimate with the Pi's heights ------------------------------------------------------

def test_travel_height_with_material_lengthens_the_lifts():
    base = estimate_gcode(JOB)
    thick = estimate_gcode(JOB, park=ParkRoutine(travel_z=26.0))        # 6 mm material + 20 mm
    assert thick.approach_time_s == pytest.approx(_z(25) + _xy(150), rel=1e-9)
    assert thick.park_time_s == pytest.approx(_xy(150) + _z(25), rel=1e-9)
    assert thick.program_time_s == base.program_time_s
    # the active routine (set from the status) is the default of every estimate
    set_active_park(routine_from_status(_status(travel_z_mm=26.0)))
    assert estimate_gcode(JOB).routine_time_s == pytest.approx(thick.routine_time_s)
    assert estimate_gcode(JOB).routine_note() == "Fahrhöhe 26 mm, Parkhöhe 1 mm (Pi)"
    assert estimate_gcode(JOB, park=DEFAULT_PARK).routine_note() == ""


def test_probe_minimum_raises_the_park_move():
    e = estimate_gcode(JOB, park=ParkRoutine(min_park_lift_z=30.0))
    assert e.park_time_s == pytest.approx(_z(10) + _xy(150) + _z(29), rel=1e-9)
    assert e.approach_time_s == pytest.approx(_z(19) + _xy(150), rel=1e-9)   # start unaffected
    assert "Parkfahrt über Z30" in ParkRoutine(min_park_lift_z=30.0).label()


# --- start and placement -------------------------------------------------------------------

def test_head_jogged_away_starts_there_without_a_lift():
    e = estimate_gcode(JOB, start=JobStart(head=(100.0, 0.0, 20.0)))
    assert e.approach_length_mm == pytest.approx(50)
    assert e.approach_time_s == pytest.approx(_xy(50), rel=1e-9)
    assert e.park_time_s == pytest.approx(_xy(150) + _z(19), rel=1e-9)
    assert e.scope_note() == "mit Anfahrt von der Kopfposition und Parken, ohne Referenzfahrt/Abtasten"
    # head low but away from the corner: the Pi does not lift, the park lift starts at its Z
    low = estimate_gcode(JOB, start=JobStart(head=(100.0, 0.0, 5.0)))
    assert low.approach_time_s == pytest.approx(_xy(50), rel=1e-9)
    assert low.park_time_s == pytest.approx(_z(15) + _xy(150) + _z(19), rel=1e-9)


def test_head_parked_low_in_the_corner_is_the_default():
    parked = estimate_gcode(JOB, start=JobStart(head=(0.0, 0.0, 1.0)))
    assert parked.routine_time_s == pytest.approx(estimate_gcode(JOB).routine_time_s)
    assert parked.scope_note().startswith("mit Anfahrt aus der Park-Ecke")
    # at X0/Y0 but up at the travel height (e.g. after homing without lowering): no lift
    up = estimate_gcode(JOB, start=JobStart(head=(0.0, 0.0, 20.0)))
    assert up.approach_time_s == pytest.approx(_xy(150), rel=1e-9)


def test_user_origin_moves_the_approach_and_the_park_move():
    # powered extent X150..250 / Y0: anchor "tr" = small X, small Y = (150, 0)
    st = JobStart(origin="user", anchor="tr", target=(200.0, 50.0))
    assert st.offset(JOB) == (50.0, 50.0)
    e = estimate_gcode(JOB, start=st)
    plain = estimate_gcode(JOB)
    d = (200 ** 2 + 50 ** 2) ** 0.5
    assert e.approach_length_mm == pytest.approx(d) and e.park_length_mm == pytest.approx(d)
    assert e.placement_offset == (50.0, 50.0)
    for f in ("cut_time_s", "travel_time_s", "cut_length_mm", "travel_length_mm", "program_time_s"):
        assert getattr(e, f) == getattr(plain, f)                  # G-code part unchanged
    assert e.bounds == plain.bounds                                # as drawn (preview)
    assert "am Ursprung „Benutzer-Ursprung“ versetzt um X+50.0 / Y+50.0 mm" in e.routine_note()
    # centre anchor
    assert JobStart(origin="user", anchor="center", target=(200.0, 50.0)).offset(JOB) == (0.0, 50.0)
    # unknown target or a job without laser moves: planned unshifted
    assert JobStart(origin="user", target=None).offset(JOB) == (0.0, 0.0)
    assert JobStart(origin="user", target=(200.0, 50.0)).offset("G0 X10 Y10\n") == (0.0, 0.0)


def test_current_position_starts_at_the_anchor():
    st = JobStart(head=(300.0, 100.0, 20.0), origin="current", anchor="tr", target=(300.0, 100.0))
    e = estimate_gcode(JOB, start=st)
    assert e.approach_length_mm == pytest.approx(0.0) and e.approach_time_s == 0.0
    assert e.park_length_mm == pytest.approx((300 ** 2 + 100 ** 2) ** 0.5)
    assert "„Kopfposition“" in e.routine_note()


def test_start_from_status():
    from machine.client import MachineStatus
    raw = _status(position=[120.0, 80.0, 18.0],
                  origin={"modes": ["absolute", "current", "user"], "user": [40, 60]})
    st = MachineStatus.from_json(raw)
    assert start_from_status(st) == JobStart(head=(120.0, 80.0, 18.0))
    assert start_from_status(st, "current", "bl").target == (120.0, 80.0)
    assert start_from_status(st, "user", "center") == JobStart((120.0, 80.0, 18.0), "user",
                                                                "center", (40.0, 60.0))
    assert start_from_status(raw, "user").target == (40.0, 60.0)     # raw dict works too
    assert start_from_status({"position": None}, "current").target is None
    assert start_from_status(st, "bogus").origin == "absolute"


# --- active values, storage, sync ---------------------------------------------------------

def test_listeners_and_storage():
    seen = []
    cb = lambda: seen.append(1)  # noqa: E731
    add_park_listener(cb)
    try:
        assert not set_active_park(ParkRoutine(source=PI))            # same heights
        assert set_active_park(ParkRoutine(travel_z=30.0))
        assert set_active_start(JobStart(head=(5.0, 5.0, 5.0)))
        assert not set_active_start(JobStart(head=(5.0, 5.0, 5.0)))
        assert len(seen) == 2
    finally:
        remove_park_listener(cb)
    store = _Store()
    pr.save(store, ParkRoutine(park_z=2.0, travel_z=25.0, min_park_lift_z=40.0))
    assert load_saved(store) == ParkRoutine(park_z=2.0, travel_z=25.0, source=SAVED)
    pr.save(store, DEFAULT_PARK)
    assert load_saved(store) is None                                  # defaults: nothing to apply
    store.data.update({"estimate/park_z": "abc", "estimate/travel_z": 25})
    assert load_saved(store) is None


class _Combo(QObject):
    currentIndexChanged = Signal(int)


class _Panel(QObject):
    status_changed = Signal(object)

    def __init__(self):
        super().__init__()
        self._status = None
        self.origin = ("absolute", "tr")
        self.origin_combo = _Combo()
        self.anchor_combo = _Combo()

    def job_origin(self):
        return self.origin


def test_sync_follows_status_and_origin(qapp):
    from machine.client import MachineStatus
    store = _Store()
    panel = _Panel()
    sync = ParkSync(panel, store=store)
    assert active_park() == DEFAULT_PARK and active_start() == DEFAULT_START
    st = MachineStatus.from_json(_status(
        travel_z_mm=25.0, position=[150.0, 60.0, 25.0], coord_convention="origin_top_right",
        origin={"modes": ["absolute", "current", "user"], "user": [200.0, 50.0]}))
    panel._status = st
    panel.status_changed.emit(st)
    assert active_park().travel_z == 25.0 and active_park().source == PI
    assert load_saved(store).travel_z == 25.0
    writes = store.synced
    panel.status_changed.emit(st)
    assert store.synced == writes                                     # every poll: no extra write
    assert active_start() == JobStart(head=(150.0, 60.0, 25.0))
    panel.origin = ("user", "tr")
    panel.origin_combo.currentIndexChanged.emit(1)
    assert active_start().origin == "user" and active_start().target == (200.0, 50.0)
    assert estimate_gcode(JOB).placement_offset == (50.0, 50.0)
    # while a job runs the head moves: the start is kept
    running = MachineStatus.from_json(_status(travel_z_mm=25.0, position=[10.0, 10.0, 3.0],
                                              activity="job"))
    panel.status_changed.emit(running)
    assert active_start().head == (150.0, 60.0, 25.0)
    # disconnected: park corner, absolute
    panel._status = None
    sync.update_start()
    assert active_start() == DEFAULT_START
    # next start offline: the stored heights apply
    set_active_park(None)
    ParkSync(None, store=store)
    assert active_park() == ParkRoutine(travel_z=25.0, source=SAVED)
    assert "zuletzt gesehen" in estimate_gcode(JOB).routine_note()


# --- app wiring ------------------------------------------------------------------------------

def test_main_window_follows_the_pi_heights(qapp, tmp_path, monkeypatch):
    monkeypatch.setenv("LUMACUT_MOTION_SETTINGS", str(tmp_path / "motion.ini"))
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(tmp_path))
    QSettings.setDefaultFormat(QSettings.IniFormat)
    main = pytest.importorskip("main")
    from machine.client import MachineStatus
    from lumacut_canvas.model import Geometry, Layer, Shape
    win = main.LumaCutStudio()
    try:
        ed = win.canvas
        lid = ed.document.add_layer(Layer(name="Schnitt", power=20.0, speed=3000.0, passes=1)).id
        ed.document.add_shape(Shape("rect", Geometry(20, 20, 100, 80), lid))
        pv = ed.path_preview
        ed.set_path_preview(True)
        before = pv.estimate.routine_time_s
        gcode = pv.gcode
        win.machine_panel.status_changed.emit(MachineStatus.from_json(
            _status(travel_z_mm=40.0, config={"z_clearance_mm": 20.0, "park_z_mm": 1.0})))
        assert active_park().travel_z == 40.0
        assert pv.gcode == gcode and not pv.pending()
        assert pv.estimate.routine_time_s == pytest.approx(before - 2 * _z(19) + 2 * _z(39))
        win.job_tools.show_estimate()
        assert "Fahrhöhe 40 mm, Parkhöhe 1 mm (Pi)" in win.statusBar().currentMessage()
        assert load_saved(QSettings(str(tmp_path / "motion.ini"), QSettings.IniFormat)).travel_z == 40.0
    finally:
        ed.undo_stack.setClean()
        win.close()
        remove_park_listener(win.job_tools.park_refresh)
        from lumacut_job.motion import remove_motion_listener
        remove_motion_listener(win.job_tools.motion_refresh)
