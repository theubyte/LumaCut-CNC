"""Ein-Klick-Auftrag: Zustandsmaschine mit Fakes (Anforderungen 2026-10-26 §1)."""
from __future__ import annotations

import json
import threading
import time
from types import SimpleNamespace

import pytest

from scanprobe import adapters
from scanprobe.control import RunControl
from scanprobe.job_flow import (FAST_PROBE, STEPS, ClientMachinePort, OneClickJob, job_burn_rects,
                                job_probe_areas, lowest_measured_point, mesh_reusable)
from scanprobe.workflow import ScanProbeWorkflow


def square(x0, y0, size, s=800):
    return "\n".join([
        "G21", "G90", "M4 S0", f"G0 X{x0} Y{y0}",
        f"G1 X{x0 + size} Y{y0} F1500 S{s}", f"G1 X{x0 + size} Y{y0 + size}",
        f"G1 X{x0} Y{y0 + size}", f"G1 X{x0} Y{y0}", "M5", ""])


class FakePort:
    """Pi-Verhalten wie pi400/marlin/web.py, stark vereinfacht."""

    def __init__(self, fake_machine, job_polls=3, fail=None):
        self.m = fake_machine
        self.homed = False
        self.latched = False
        self.surface = None
        self.job = SimpleNamespace(file="", state="idle", line=0, total=0, error="")
        self.calls: list[str] = []
        self.uploaded: dict[str, str] = {}
        self.job_polls = job_polls
        self.fail = fail or {}
        self._polls = 0

    def _maybe_fail(self, op):
        if op in self.fail:
            raise RuntimeError(self.fail[op])

    def status(self):
        if self.job.state in ("running",):
            self._polls += 1
            self.job.line = min(self.job.total, self._polls * max(1, self.job.total // self.job_polls))
            if self._polls > self.job_polls:
                self.job.state = "complete"
                self.calls.append("park(job)")
        job = SimpleNamespace(**vars(self.job))
        job.active = job.state in ("homing", "probing", "running")
        job.progress = job.line / job.total if job.total else None
        return SimpleNamespace(homed=self.homed, emergency_latched=self.latched,
                               workpiece_surface_z=self.surface, job=job)

    def home(self):
        self.calls.append("home")
        self._maybe_fail("home")
        self.homed = True
        return "ok"

    def probe_at(self, x, y):
        self.calls.append(f"probe_at({x:.1f},{y:.1f})")
        self._maybe_fail("probe_at")
        self.surface = self.m.probe_z(x, y, safe_z=20, feed=200, max_depth=-1)
        return "ok"

    def upload_job(self, name, gcode):
        self.calls.append("upload")
        self._maybe_fail("upload")
        self.uploaded[name] = gcode
        return "ok"

    def start_job(self, name):
        self.calls.append("start")
        self.job = SimpleNamespace(file=name, state="running", line=0,
                                   total=len(self.uploaded[name].splitlines()), error="")
        self._polls = 0
        return "ok"

    def abort_job(self):
        self.calls.append("abort")
        self.job.state = "aborted"
        return "ok"

    def park(self):
        self.calls.append("park")
        return "ok"


def make(job_polls=3, fail=None, **kw):
    hw = adapters.simulated_setup()
    port = FakePort(hw.machine, job_polls, fail)
    wf = ScanProbeWorkflow(hw.machine, None, hw.probe, hw.calibration, settle_s=0.0)
    events: list[dict] = []
    flow = OneClickJob(port, wf, on_event=events.append, poll_s=0.0, sleep=lambda s: None, **kw)
    return flow, port, events, hw


GCODE = square(90, 100, 40)  # liegt auf der Holzplatte des simulierten Betts


def test_burn_rects_and_areas_from_job():
    g = GCODE + square(250, 230, 30)
    rects = job_burn_rects(g)
    assert len(rects) == 2
    assert rects[0].xmin == pytest.approx(90) and rects[0].xmax == pytest.approx(130)
    areas, notes = job_probe_areas(g)
    assert len(areas) == 2 and not notes
    assert areas[0].bounds.xmin == pytest.approx(87)  # + 3 mm Rand
    # nahe beieinander -> ein Bereich
    assert len(job_burn_rects(square(90, 100, 20) + square(112, 100, 20))) == 1
    assert job_burn_rects("G0 X10 Y10\nG1 X20 Y20 S0\n") == []


def test_full_flow_order_and_events_are_json():
    flow, port, events, _ = make()
    res = flow.run(GCODE, "motiv.gcode")
    assert res.ok, res.error
    assert flow.history == list(STEPS) + ["fertig"]
    # Reihenfolge an der Maschine: Home, Fokus-G30, Upload, Start; Parken macht der Pi
    assert port.calls[0] == "home"
    assert [c for c in port.calls if not c.startswith("probe_at")][1:] == ["upload", "start", "park(job)"]
    assert any(c.startswith("probe_at") for c in port.calls)
    assert "park" not in port.calls
    sent = port.uploaded["motiv.gcode"]
    assert " Z" in sent and sent != GCODE        # fokuskorrigiert
    assert res.probe_points > 0 and not res.reused_mesh
    json.dumps(events)
    json.dumps(res.to_dict())
    assert events[-1]["state"] == "fertig"
    states = [e["state"] for e in events]
    assert states.index("probing") < states.index("fokus") < states.index("job")
    # Fokus am niedrigsten Messpunkt -> Pi-Sperre greift nicht
    x, y, z = lowest_measured_point(res.maps)
    assert res.focus_point == (x, y)
    assert res.export.report.z_min >= port.surface + 2.0 - 1e-6


def test_fast_probe_is_coarse_and_adaptive():
    assert FAST_PROBE.spacing_mm >= 20 and FAST_PROBE.adaptive


def test_mesh_reused_after_spot_checks():
    flow, port, events, hw = make()
    first = flow.run(GCODE, "a.gcode")
    assert first.ok
    probes_before = first.probe_points
    flow2 = OneClickJob(port, flow.workflow, on_event=events.append, poll_s=0.0, sleep=lambda s: None)
    res = flow2.run(GCODE, "a.gcode", saved_maps=first.maps)
    assert res.ok and res.reused_mesh
    assert res.probe_points <= 3 * len(first.maps.maps) < probes_before


def test_mesh_not_reused_when_old_or_not_covering():
    flow, port, _, _ = make()
    first = flow.run(GCODE, "a.gcode")
    ok, why = mesh_reusable(first.maps, square(250, 230, 30))
    assert not ok and "deckt" in why
    ok, why = mesh_reusable(first.maps, GCODE, now=time.time() + 9 * 3600)
    assert not ok and "älter" in why
    assert mesh_reusable(first.maps, GCODE)[0]


def test_invalid_job_stops_before_moving():
    flow, port, events, _ = make()
    res = flow.run("G21\nG90\nG2 X10 Y10 I5 J0 S500\n", "arc.gcode")
    assert res.state == "fehler" and res.error_code == "invalid_job"
    assert port.calls == []
    res = flow.run("G21\nG90\nG0 X100 Y100\n", "leer.gcode")
    assert res.error_code == "invalid_job" and "Brennstrecke" in res.error


def test_emergency_and_running_job_block_start():
    flow, port, _, _ = make()
    port.latched = True
    assert flow.run(GCODE).error_code == "emergency"
    port.latched = False
    port.job.state = "running"; port.job.file = "x.gcode"; port.job.total = 10 ** 6
    assert flow.run(GCODE).error_code == "not_ready"
    assert port.calls == []


def test_homing_failure_is_reported_in_german():
    flow, port, events, _ = make(fail={"home": "Endschalter X nicht erreicht"})
    res = flow.run(GCODE)
    assert res.error_code == "homing_failed" and "Referenzfahrt" in res.error
    assert events[-1]["error"]["code"] == "homing_failed"
    assert "upload" not in port.calls


def test_upload_rejected_parks_head():
    flow, port, _, _ = make(fail={"upload": "Motiv liegt außerhalb"})
    res = flow.run(GCODE)
    assert res.error_code == "upload_failed"
    assert port.calls[-1] == "park"          # vor dem Lasern: Ablauf parkt selbst


def test_no_contact_is_probe_error_and_parks():
    flow, port, _, _ = make()
    flow.workflow.probe.probe_z = lambda *a, **kw: None     # Taster löst nie aus
    res = flow.run(GCODE)
    assert res.state == "fehler" and res.error_code == "probe_failed"
    assert "Material" in res.error and port.calls[-1] == "park"


def test_job_error_on_pi():
    flow, port, _, _ = make()
    orig = port.status

    def status():
        st = orig()
        if port.job.state == "running" and port._polls >= 2:
            port.job.state, port.job.error = "error", "Z-Sperre"
        return st
    port.status = status
    res = flow.run(GCODE)
    assert res.error_code == "job_failed" and "Z-Sperre" in res.error
    assert "park" not in port.calls         # Pi parkt nach Fehler selbst


def test_cancel_during_probing_parks():
    flow, port, events, _ = make()
    orig = flow.workflow.probe.probe_z
    count = {"n": 0}

    def probe_z(*a, **kw):
        count["n"] += 1
        if count["n"] == 3:
            flow.cancel()
        return orig(*a, **kw)
    flow.workflow.probe.probe_z = probe_z
    res = flow.run(GCODE)
    assert res.state == "abgebrochen" and res.error_code == "cancelled"
    assert port.calls[-1] == "park" and "upload" not in port.calls


def test_cancel_during_job_aborts_on_pi():
    flow, port, _, _ = make(job_polls=50)
    orig = port.status

    def status():
        st = orig()
        if port.job.state == "running" and port._polls == 3:
            flow.cancel()
        return st
    port.status = status
    res = flow.run(GCODE)
    assert res.state == "abgebrochen"
    assert "abort" in port.calls and "park" not in port.calls


def test_pause_blocks_between_steps():
    flow, port, events, _ = make()
    flow.pause()
    t = threading.Thread(target=flow.run, args=(GCODE,))
    t.start()
    time.sleep(0.2)
    assert t.is_alive() and port.calls in ([], ["home"])
    assert any(e.get("paused") for e in events)
    flow.resume()
    t.join(30)
    assert flow.result.ok


def test_client_port_calls_existing_client_methods():
    calls = []

    class Client:
        def __getattr__(self, name):
            return lambda *a, **kw: calls.append((name, a)) or "ok"
    p = ClientMachinePort(Client())
    p.home(); p.probe_at(1, 2); p.upload_job("a.gcode", "G0"); p.start_job("a.gcode")
    p.abort_job(); p.park(); p.status()
    assert [c[0] for c in calls] == ["home", "focus", "upload_job", "start_job", "abort_job",
                                     "park", "status"]
    assert calls[1][1] == (1.0, 2.0)


def test_already_homed_skips_homing():
    flow, port, _, _ = make()
    port.homed = True
    res = flow.run(GCODE)
    assert res.ok and "home" not in port.calls
    assert flow.history[0] == "referenzieren"
    port.calls.clear()
    flow.always_home = True
    assert flow.run(GCODE).ok and port.calls[0] == "home"


class PiAutorunPort(FakePort):
    """Pi mit ``autorun_mesh`` (Vertrag ZUSAMMENARBEIT §4): homing → probing → running."""

    def __init__(self, *a, fail_in=None, **kw):
        super().__init__(*a, **kw)
        self.phase_polls = []
        self.fail_in = fail_in

    def autorun(self, name):
        self.calls.append("autorun")
        self.job = SimpleNamespace(file=name, state="homing", line=0,
                                   total=len(self.uploaded[name].splitlines()), error="")
        self.phase_polls = ["homing"] * 2 + ["probing"] * 4
        self._polls = 0
        return "ok"

    def status(self):
        probe = None
        if self.phase_polls:
            state = self.phase_polls.pop(0)
            if state == self.fail_in and self.job.state == state:   # nach dem 1. Messpunkt
                self.job.state, self.job.error = "error", "Taster ohne Kontakt"
                self.phase_polls = []
            else:
                self.job.state = state
                if state == "probing":
                    probe = {"done": 4 - len(self.phase_polls), "total": 4}
        elif self.job.state in ("homing", "probing"):
            self.job.state = "running"
        st = super().status()
        st.raw = {"features": ["autorun_mesh"], "job": {"probe": probe} if probe else {}}
        return st


def make_pi(**kw):
    hw = adapters.simulated_setup()
    port = PiAutorunPort(hw.machine, **kw)
    events: list[dict] = []
    flow = OneClickJob(port, None, on_event=events.append, poll_s=0.0, sleep=lambda s: None)
    return flow, port, events


def test_pi_autorun_mesh_is_used_when_pi_reports_it():
    flow, port, events = make_pi()
    res = flow.run(GCODE, "motiv.gcode")
    assert res.ok and res.pi_mesh, res.error
    assert port.uploaded["motiv.gcode"] == GCODE        # unkorrigiert, Pi korrigiert selbst
    assert "start" not in port.calls and "home" not in port.calls
    assert not any(c.startswith("probe_at") for c in port.calls)
    assert flow.history == list(STEPS) + ["fertig"]
    probe_ev = [e for e in events if e["state"] == "probing" and e["progress"]]
    assert probe_ev and probe_ev[-1]["progress"] == 1.0
    assert res.to_dict()["pi_mesh"] is True


def test_pi_autorun_probe_error_is_probe_failed():
    flow, port, _ = make_pi(fail_in="probing")
    res = flow.run(GCODE)
    assert res.error_code == "probe_failed" and "Taster" in res.error
    assert "park" not in port.calls     # Pi hat den Auftrag selbst beendet


def test_studio_mesh_forced_even_if_pi_could():
    hw = adapters.simulated_setup()
    port = PiAutorunPort(hw.machine)
    wf = ScanProbeWorkflow(hw.machine, None, hw.probe, hw.calibration, settle_s=0.0)
    flow = OneClickJob(port, wf, poll_s=0.0, sleep=lambda s: None, use_pi_mesh=False)
    res = flow.run(GCODE)
    assert res.ok and not res.pi_mesh and "autorun" not in port.calls


def test_detach_leaves_running_job_on_pi():
    flow, port, events, _ = make(job_polls=10_000)
    orig = port.status
    calls = {"n": 0}

    def status():
        st = orig()
        if st.job.active:
            calls["n"] += 1
            if calls["n"] == 3:
                flow.detach()
        return st
    port.status = status
    res = flow.run(GCODE, "motiv.gcode")
    assert res.state == "fehler" and res.error_code == "detached"
    assert "abort" not in port.calls and "park" not in port.calls
