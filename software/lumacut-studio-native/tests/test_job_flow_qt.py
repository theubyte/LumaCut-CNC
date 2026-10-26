"""Qt-Anbindung des Ein-Klick-Auftrags mit Fakes (kein Pi, keine Hardware)."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from scanprobe import adapters
from scanprobe.workflow import ScanProbeWorkflow
from test_job_flow import GCODE, FakePort


class FakeMachinePanel:
    def __init__(self, client=object(), origin="absolute"):
        self.client = client
        self.origin = origin
        self.ops: list[str] = []

    def job_origin(self):
        return self.origin, "tl"

    def set_external_operation(self, label):
        self.ops.append(label)


@pytest.fixture()
def setup(qapp):
    from lumacut_canvas.editor import CanvasEditor
    from scanprobe.job_flow_qt import install_one_click
    from scanprobe.panel import ScanPanel
    ed = CanvasEditor()
    panel = ScanPanel(ed, ask=False)
    hw = adapters.simulated_setup()
    port = FakePort(hw.machine)
    win = SimpleNamespace(canvas=ed, scan_panel=panel, machine_panel=FakeMachinePanel(),
                          job_tools=SimpleNamespace(job_gcode=lambda: (GCODE, "")))
    ctrl = install_one_click(
        win, ask=False, port_factory=lambda client: port,
        workflow_factory=lambda: ScanProbeWorkflow(hw.machine, None, hw.probe, hw.calibration,
                                                   settle_s=0.0),
        job_kwargs=dict(poll_s=0.0))
    yield ctrl, win, port
    ctrl.shutdown()
    panel.shutdown()
    ed.undo_stack.setClean()


def test_one_click_runs_and_keeps_mesh(setup):
    ctrl, win, port = setup
    assert win.scan_panel.advanced.isAncestorOf(win.scan_panel.one_click_button)
    assert ctrl.start() and ctrl.busy and win.scan_panel.busy
    assert ctrl.wait() and ctrl.last_result.ok, ctrl.last_result.error
    assert win.machine_panel.ops == ["Ein-Klick-Auftrag", ""]
    assert not win.scan_panel.busy and win.scan_panel.has_maps
    assert port.calls[0] == "home" and "upload" in port.calls and "start" in port.calls
    assert "Fokuskorrektur" in port.uploaded["canvas.gcode"]
    assert "fertig" in ctrl.last_message
    # zweiter Auftrag: Mesh wird geprüft und wiederverwendet
    assert ctrl.start() and ctrl.wait() and ctrl.last_result.ok
    assert ctrl.last_result.reused_mesh


def test_one_click_refuses_without_connection_or_relative_origin(setup):
    ctrl, win, _ = setup
    win.machine_panel.client = None
    assert not ctrl.start() and "verbunden" in ctrl.last_message
    win.machine_panel.client = object()
    win.machine_panel.origin = "head"
    assert not ctrl.start() and "Absolut" in ctrl.last_message
    assert not ctrl.busy and win.machine_panel.ops == []


def test_one_click_cancel_from_panel(setup):
    import threading
    ctrl, win, port = setup
    in_home, release = threading.Event(), threading.Event()
    real_home = port.home

    def slow_home():
        in_home.set()
        release.wait(10)
        return real_home()
    port.home = slow_home
    assert ctrl.start() and in_home.wait(10)
    win.scan_panel.cancel()              # Panel-Knopf steuert den Ein-Klick-Auftrag
    release.set()
    assert ctrl.wait() and ctrl.last_result.state == "abgebrochen"
    assert "start" not in port.calls and "upload" not in port.calls
    assert win.machine_panel.ops[-1] == "" and not win.scan_panel.busy
