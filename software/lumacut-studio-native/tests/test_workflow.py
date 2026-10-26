"""Geführter Ablauf: Zustandsmaschine (Qt-frei), Panel mit Fake-Adapter, Hauptfenster gegen FakePi."""
from __future__ import annotations

import time
from dataclasses import replace

import pytest

from lumacut_workflow import (BLOCKED, DONE, READY, RUNNING, SKIPPED, STEP_KEYS, WorkflowFacts,
                              WorkflowMarks, current_step, evaluate, summary)

READY_PI = WorkflowFacts(connected=True, homed=True, design_empty=False, marked_areas=1)


def by_key(states):
    return {s.key: s for s in states}


def test_step_order():
    assert STEP_KEYS == ("home", "scan", "mark", "probe", "focus", "frame", "job", "park")


def test_disconnected_blocks_machine_steps_with_reason():
    st = by_key(evaluate(WorkflowFacts()))
    assert st["home"].status == BLOCKED and "Nicht mit dem Pi verbunden" in st["home"].reason
    assert st["scan"].status == BLOCKED
    assert st["mark"].status == BLOCKED and "scannen" in st["mark"].reason
    assert st["probe"].status == BLOCKED and "Bereiche" in st["probe"].reason
    assert st["frame"].reason == "Kein Design auf der Arbeitsfläche"
    assert st["job"].status == BLOCKED
    assert current_step(evaluate(WorkflowFacts())).key == "home"


def test_simulation_allows_scan_without_pi():
    st = by_key(evaluate(WorkflowFacts(simulation=True)))
    assert st["scan"].status == READY
    st = by_key(evaluate(WorkflowFacts(simulation=True, has_mosaic=True)))
    assert st["scan"].status == DONE and st["mark"].status == READY
    st = by_key(evaluate(WorkflowFacts(simulation=True, has_mosaic=True, marked_areas=2)))
    assert st["mark"].status == DONE and st["probe"].status == READY


def test_home_then_emergency():
    f = WorkflowFacts(connected=True)
    assert by_key(evaluate(f))["home"].status == READY
    assert by_key(evaluate(replace(f, homed=True)))["home"].status == DONE
    st = by_key(evaluate(replace(f, homed=True, emergency=True)))
    assert st["home"].status == BLOCKED and "Notstopp" in st["home"].reason
    assert st["focus"].status == BLOCKED


def test_job_waits_for_focus_and_frame_unless_skipped():
    marks = WorkflowMarks()
    st = by_key(evaluate(READY_PI, marks))
    assert st["job"].status == BLOCKED and "Fokus und Rahmen" in st["job"].reason
    marks.skip("frame")
    st = by_key(evaluate(READY_PI, marks))
    assert st["frame"].status == SKIPPED and "Fokus" in st["job"].reason
    st = by_key(evaluate(replace(READY_PI, surface_z=12.3), marks))
    assert st["focus"].status == DONE and st["job"].status == READY


def test_running_states_and_busy_machine():
    f = replace(READY_PI, surface_z=1.0, machine_busy=True, machine_activity="frame",
                frame_state="running")
    st = by_key(evaluate(f))
    assert st["frame"].status == RUNNING
    assert st["park"].status == BLOCKED and st["park"].reason == "Maschine beschäftigt"
    f = replace(READY_PI, surface_z=1.0, machine_busy=True, machine_activity="job", job_state="running")
    assert by_key(evaluate(f))["job"].status == RUNNING
    f = WorkflowFacts(simulation=True, scan_busy=True, scan_kind="probe", marked_areas=1)
    st = by_key(evaluate(f))
    assert st["probe"].status == RUNNING and st["scan"].status == BLOCKED


def test_marks_skip_done_reset():
    marks = WorkflowMarks()
    with pytest.raises(ValueError, match="nicht übersprungen"):
        marks.skip("home")
    with pytest.raises(ValueError):
        marks.skip("job")
    for k in ("scan", "mark", "probe"):
        marks.skip(k)
    marks.mark_done("frame")
    f = replace(READY_PI, surface_z=2.0)
    states = evaluate(f, marks)
    st = by_key(states)
    assert [st[k].status for k in ("scan", "mark", "probe")] == [SKIPPED] * 3
    assert st["frame"].status == DONE and st["job"].status == READY
    assert current_step(states).key == "job"
    assert "Nächster Schritt: Auftrag (bereit)" in summary(states)
    marks.invalidate(["frame"])
    assert by_key(evaluate(f, marks))["frame"].status == READY
    marks.unskip("scan")
    assert by_key(evaluate(f, marks))["scan"].status == READY
    marks.reset()
    assert not marks.skipped and not marks.done
    marks.mark_done("job"); marks.mark_done("park")
    for k in ("scan", "mark", "probe", "frame"):
        marks.skip(k)
    assert summary(evaluate(f, marks)).startswith("Ablauf abgeschlossen")


# --------------------------------------------------------------- Panel (Fake)
class FakeAdapter:
    def __init__(self):
        self.facts_value = WorkflowFacts(connected=True)
        self.marks = WorkflowMarks()
        self.ran = []

    def facts(self):
        return self.facts_value

    def run(self, key):
        self.ran.append(key)
        return True


def test_panel_follows_current_step_and_skips(qapp):
    from lumacut_workflow.qt import WorkflowPanel
    a = FakeAdapter()
    p = WorkflowPanel(a)
    assert p.selected_key() == "home" and p.run_button.isEnabled()
    assert not p.skip_button.isEnabled()              # Home nicht überspringbar
    assert p.run_selected() and a.ran == ["home"]
    a.facts_value = replace(a.facts_value, homed=True)
    p.refresh()
    assert p.selected_key() == "scan"
    assert "✔" in p.list.item(0).text() and "erledigt" in p.list.item(0).text()
    p.toggle_skip()
    assert p.state("scan").status == SKIPPED and p.selected_key() == "mark"
    assert p.state("mark").status == READY and p.run_button.text() == "Markieren"
    assert "anhaken" in p.reason_label.text()
    p.select("probe")
    assert p.state("probe").status == BLOCKED and not p.run_button.isEnabled()
    assert "Keine markierten Bereiche" in p.reason_label.text()
    assert not p.run_selected() and a.ran == ["home"]
    p.select("scan")
    assert p.skip_button.text() == "Nicht überspringen"
    p.toggle_skip()
    assert p.state("scan").status == READY
    p.reset()
    assert p.selected_key() == "scan"


# ---------------------------------------------------- Hauptfenster + FakePi
def _op(pi):
    with pi.lock:
        acts = [r for r in pi.requests if r["path"] == "/api/action"]
    return acts[-1].get("form", {}).get("op") if acts else None


def _wait(pred, timeout=10.0):
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance()
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        app.processEvents()
        if pred():
            return True
        time.sleep(0.01)
    return pred()


@pytest.fixture()
def win(qapp, tmp_path, monkeypatch):
    from PySide6.QtCore import QSettings
    monkeypatch.delenv("LUMACUT_KEY", raising=False)
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(tmp_path))
    QSettings.setDefaultFormat(QSettings.IniFormat)
    main = pytest.importorskip("main")
    w = main.LumaCutStudio()
    w.import_tools.interactive = False
    w.machine_panel._confirm = lambda *_: True
    w.workflow_adapter.confirm = lambda *_: True
    w.scan_panel.ask = False
    yield w
    w.scan_panel.shutdown()
    w.machine_panel.shutdown()
    w.canvas.undo_stack.setClean()
    w.close()


def test_main_window_has_workflow_group(win):
    from PySide6.QtWidgets import QGroupBox
    group = win.workflow_panel.parentWidget()
    assert isinstance(group, QGroupBox) and group.title() == "Ablauf"
    col = group.parentWidget().layout()
    assert col.indexOf(group) == 0
    assert win.workflow_panel.selected_key() == "home"
    assert win.workflow_panel.state("home").reason == "Nicht mit dem Pi verbunden"


def test_full_guided_run_against_fake_pi(win):
    import sys, pathlib
    sys.path.insert(0, str(pathlib.Path(__file__).parent))
    from fake_pi import FakePi
    from lumacut_canvas import Geometry, Shape
    with FakePi() as pi:
        p, mp = win.workflow_panel, win.machine_panel
        pi.status["homed"] = False
        mp.url_edit.setText(pi.url)
        mp.connect_to_pi()
        assert _wait(lambda: p.state("home").status == READY)
        assert p.run_selected()
        assert _wait(lambda: _op(pi) == "home")
        pi.status["homed"] = True
        assert _wait(lambda: p.state("home").status == DONE)
        assert p.selected_key() == "scan"
        # Scan + Probe in Simulation (ohne Kamera/Taster)
        assert p.state("scan").status == READY
        assert p.run_selected(), win.scan_panel.last_error
        assert win.scan_panel.wait(60000)
        assert _wait(lambda: p.state("scan").status == DONE)
        assert _wait(lambda: p.state("mark").status == DONE)   # erkannte Werkstücke angehakt
        assert p.selected_key() == "probe" and p.run_selected()
        assert win.scan_panel.wait(60000)
        assert _wait(lambda: p.state("probe").status == DONE), win.scan_panel.last_error
        # Fokus: G30 über die Pi-API, erledigt sobald die Oberfläche bekannt ist
        assert p.selected_key() == "focus" and p.run_selected()
        assert _wait(lambda: _op(pi) == "probe")
        pi.status["workpiece_surface_z"] = 4.5
        assert _wait(lambda: p.state("focus").status == DONE)
        # Rahmen braucht ein Design
        assert p.state("frame").status in (READY, BLOCKED)
        doc = win.canvas.document
        from scan_coords import screen_rect   # Maschine 90..170 / 90..130, auf dem Werkstück (§2.3)
        doc.add_shape(Shape("rect", Geometry(*screen_rect(90, 90, 80, 40)), doc.active_layer_id))
        win.canvas.documentChanged.emit()
        assert _wait(lambda: p.state("frame").status == READY)
        assert p.selected_key() == "frame" and p.run_selected()
        assert _wait(lambda: p.state("frame").status == RUNNING)
        assert p.state("job").status == BLOCKED
        pi.finish_frame("complete")
        assert _wait(lambda: p.state("frame").status == DONE)
        # Auftrag: senden + starten in einem Schritt
        assert _wait(lambda: p.state("job").status == READY)
        assert p.selected_key() == "job" and p.run_selected()
        assert _wait(lambda: _op(pi) == "start")
        assert pi.uploads == ["canvas.gcode"]
        pi.status["job"] = {"file": "canvas.gcode", "state": "running", "line": 1, "total": 9,
                            "error": ""}
        pi.status["owner"] = "job"
        assert _wait(lambda: p.state("job").status == RUNNING)
        pi.status["job"] = dict(pi.status["job"], state="complete", line=9)
        pi.status["owner"] = "Frei"
        assert _wait(lambda: p.state("job").status == DONE)
        # Parken
        assert _wait(lambda: p.selected_key() == "park" and p.state("park").status == READY)
        assert p.run_selected()
        assert _wait(lambda: p.state("park").status == DONE)
        assert _op(pi) == "park"
        assert p.summary_label.text().startswith("Ablauf abgeschlossen")
        # Design ändern → Rahmen/Auftrag wieder offen
        doc.add_shape(Shape("rect", Geometry(10, 10, 5, 5), doc.active_layer_id))
        win.canvas.documentChanged.emit()
        assert _wait(lambda: p.state("frame").status == READY and p.state("job").status != DONE)
        mp.disconnect_from_pi()
