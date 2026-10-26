"""Vereinfachte Scan-Oberfläche (Anforderungen 2026-10-26 §1/§2): ein Knopf, Rest unter „Mehr …“."""
from __future__ import annotations

import pytest


@pytest.fixture()
def editor(qapp):
    from lumacut_canvas.editor import CanvasEditor
    ed = CanvasEditor()
    yield ed
    ed.undo_stack.setClean()


@pytest.fixture()
def panel(qapp, editor):
    from scanprobe.panel import ScanPanel
    p = ScanPanel(editor, ask=False)
    yield p
    p.shutdown()


def test_scan_panel_has_no_own_camera_scan_button(panel):
    # Der Knopf „Kamera-Scan“ sitzt in der Canvas-Hauptansicht (main_view).
    assert not hasattr(panel, "scan_button")
    assert panel.advanced.isHidden() and not panel.more_button.isChecked()
    assert not hasattr(panel, "focus_check")
    # Expertenfunktionen liegen im ausgeklappten Bereich
    for w in (panel.probe_button, panel.full_button, panel.export_button, panel.mode_combo):
        assert panel.advanced.isAncestorOf(w)
    panel.show_advanced(True)
    assert not panel.advanced.isHidden() and panel.more_button.text() == "Weniger"
    panel.more_button.click()
    assert panel.advanced.isHidden() and panel.more_button.text() == "Mehr …"


def test_camera_scan_uses_pi_when_connected(panel, monkeypatch):
    from scanprobe.panel import MODE_PI, MODE_SIM
    started = []
    monkeypatch.setattr(panel, "start_scan", lambda: started.append(panel.mode) or True)
    assert panel.camera_scan() and started[-1] == MODE_SIM          # nicht verbunden
    panel.client_provider = lambda: object()
    assert panel.camera_scan() and started[-1] == MODE_PI           # verbunden -> Maschine
    panel.set_mode(MODE_SIM)
    panel._mode_activated()                                          # Nutzer wählt bewusst
    assert panel.camera_scan() and started[-1] == MODE_SIM


def test_camera_scan_simulation_runs(panel):
    assert panel.camera_scan() and panel.wait(60000) and panel.last_error == ""
    assert panel.mosaic is not None


class _Run:
    def __init__(self):
        self.calls = []

    def pause(self):
        self.calls.append("pause")

    def resume(self):
        self.calls.append("resume")

    def cancel(self):
        self.calls.append("cancel")


def test_external_run_takes_pause_and_cancel(panel):
    run = _Run()
    panel.attach_external_run(run)
    assert panel.busy and panel.cancel_button.isEnabled() and not panel.full_button.isEnabled()
    panel.pause()
    panel.resume()
    panel.cancel()
    assert run.calls == ["pause", "resume", "cancel"]
    panel.show_job_event({"type": "job_state", "state": "probing", "step": 2, "steps": 5,
                          "label": "Probing", "message": "3/9", "progress": 0.5})
    assert panel.progress.value() == 30 and "2/5" in panel.progress.format()
    panel.show_job_event({"type": "job_state", "state": "fehler", "label": "Fehler",
                          "message": "Sonde löst nicht aus"})
    assert panel.last_error == "Sonde löst nicht aus"
    panel.detach_external_run()
    assert not panel.busy and panel.full_button.isEnabled()


def test_empty_bed_reference_remember_use_forget(panel, tmp_path, monkeypatch):
    """Leerbett-Referenz: merken, beim nächsten Scan als Differenzbild nutzen, vergessen."""
    from scanprobe.workflow import ScanProbeWorkflow
    panel.empty_bed_path = tmp_path / "leerbett.png"
    assert not panel.empty_bed_button.isEnabled()          # noch kein Scan
    assert not panel.remember_empty_bed() and "leere Bett scannen" in panel.last_error
    assert panel.camera_scan() and panel.wait(60000) and panel.last_error == ""
    assert panel.empty_bed_button.isEnabled()
    assert panel.remember_empty_bed() and panel.empty_bed_path.exists()
    assert "gemerkt" in panel.empty_bed_label.text() and panel.objects == []
    seen = []
    real = ScanProbeWorkflow.detect
    monkeypatch.setattr(ScanProbeWorkflow, "detect",
                        lambda self, m, bg=None, **kw: seen.append(bg) or real(self, m, bg, **kw))
    panel._empty_bed, panel._empty_bed_loaded = None, False   # frisch von der Platte laden
    assert panel.camera_scan() and panel.wait(60000) and panel.last_error == ""
    assert seen and seen[-1] is not None and seen[-1].image.shape == panel.mosaic.image.shape
    # passt nicht (andere Scanhöhe) -> ohne Referenz, mit Hinweis
    panel._empty_bed.scan_z += 5
    bed, note = panel._empty_bed_for(panel.mosaic)
    assert bed is None and "passt nicht" in note
    panel.forget_empty_bed()
    assert not panel.empty_bed_path.exists() and panel.empty_bed() is None
