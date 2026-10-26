"""Scan-&-Probe-Oberfläche (offscreen, Simulationsmodus, ohne Hardware)."""
from __future__ import annotations

import json
from types import SimpleNamespace

import numpy as np
import pytest

from scanprobe import adapters
from scanprobe.geometry import Rect
from scan_coords import screen_rect


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


def _scan(panel):
    assert panel.start_scan(), panel.last_error
    assert panel.wait(60000)
    assert panel.last_error == ""


def test_jog_steps_cover_distance():
    assert adapters.jog_steps(23.4) == [10, 10, 1, 1, 1, 0.1, 0.1, 0.1, 0.1]
    assert sum(adapters.jog_steps(-12.3)) == pytest.approx(-12.3)
    assert adapters.jog_steps(0.02) == []


def test_mosaic_matches_work_area(qapp):
    from scanprobe.panel import from_machine, mosaic_to_work_image
    from scanprobe.stitch import Mosaic
    img = np.zeros((370 * 2, 390 * 2, 3), np.uint8)
    img[2 * 100:2 * 120, 2 * 200:2 * 220] = 255          # Maschine X200–220 / Y100–120
    out = mosaic_to_work_image(Mosaic(img, 0.5, (0.0, 0.0), np.ones(img.shape[:2], bool)), mm_per_px=1.0)
    assert out.shape[:2] == (340, 360)
    sx, sy = from_machine(210, 110)                         # Bildschirmlage (Nullpunkt oben rechts, §2.3)
    assert out[int(sy), int(sx)].min() > 200
    assert out[10, 10].max() == 0


def test_scan_lists_objects_and_sets_canvas_overlays(panel, editor):
    from scanprobe.panel import from_machine
    _scan(panel)
    assert panel.objects_list.count() == 2 and len(panel.objects) == 2
    assert "Rechteck" in panel.objects_list.item(0).text() or "Rechteck" in panel.objects_list.item(1).text()
    # Hintergrund: Scanbild auf 360 × 340 mm, Rechteck (Maschine 70–190 / 80–170) hell
    bd = editor.view.backdrop
    assert bd is not None and bd.width() / bd.height() == pytest.approx(360 / 340, rel=0.01)
    s = bd.width() / 360
    ix, iy = from_machine(130, 125)
    ox, oy = from_machine(35, 350)
    inside = bd.pixelColor(int(ix * s), int(iy * s))
    outside = bd.pixelColor(int(ox * s), int(oy * s))
    assert inside.lightness() > outside.lightness() + 60
    # Hilfsformen in der Szene, aber nicht im Dokument
    items = panel.overlay.object_items
    assert items and all(it.scene() is editor.scene for it in items)
    assert editor.document.shapes == []
    rect = [o for o in panel.objects if o.kind == "rectangle"][0]
    path_item = [it for it in items if it.data(0) == rect.id][0]
    br = path_item.sceneBoundingRect()
    left = min(from_machine(70, 0)[0], from_machine(190, 0)[0])   # Maschine 70–190 / 80–170
    assert br.left() == pytest.approx(left, abs=3) and br.bottom() == pytest.approx(170 - 30, abs=3)
    panel.show_objects.setChecked(False)
    assert not any(it.isVisible() for it in items)
    panel.show_mosaic.setChecked(False)
    assert editor.view.backdrop is None
    panel.show_mosaic.setChecked(True)
    assert editor.view.backdrop is not None
    assert panel.probe_button.isEnabled()


def test_auto_probe_builds_heatmap(panel, editor, tmp_path):
    _scan(panel)
    panel.design_only.setChecked(False)
    assert panel.start_probe(), panel.last_error
    assert panel.wait(60000) and panel.last_error == ""
    assert panel.maps is not None and len(panel.maps.maps) == 2
    assert panel.maps.surface_z(100, 100) == pytest.approx(3.0 + 0.008 * 30 + 0.004 * 20, abs=0.08)
    heat = panel.overlay.heat_item
    assert heat is not None and heat.scene() is editor.scene and heat.isVisible()
    assert heat.sceneBoundingRect().width() == pytest.approx(360, abs=1)
    assert "Höhenkarte: Z" in panel.heat_label.text()
    panel.show_heatmap.setChecked(False)
    assert not heat.isVisible()
    # Speichern / Laden
    p = tmp_path / "mesh.json"
    assert panel.save_button.isEnabled()
    panel.save_maps(p)
    assert json.loads(p.read_text())["format"] == "lumacut-heightmaps/1"
    panel.clear()
    assert panel.maps is None and panel.overlay.heat_item is None and editor.view.backdrop is None
    panel.load_maps(p)
    assert len(panel.maps.maps) == 2


def test_auto_probe_only_under_design(panel, editor):
    from lumacut_canvas.model import Geometry, Shape
    _scan(panel)
    # Design auf der Scheibe (Maschine 270..300 / 240..270)
    editor.document.add_shape(Shape("rect", Geometry(*screen_rect(270, 240, 30, 30)),
                                    editor.document.active_layer_id))
    assert panel.design_bounds()[0].xmin == pytest.approx(270)
    panel.design_only.setChecked(True)
    assert panel.start_probe()
    assert panel.wait(60000) and panel.last_error == ""
    circle = [o for o in panel.objects if o.kind == "circle"][0]
    assert [m.area_id for m in panel.maps.maps] == [circle.id]


def test_probe_design_without_scan(panel, editor):
    from lumacut_canvas.model import Geometry, Shape
    assert not panel.probe_button.isEnabled()
    editor.document.add_shape(Shape("rect", Geometry(50, 60, 40, 30), editor.document.active_layer_id))
    panel._update_enabled()
    assert panel.probe_button.isEnabled()
    assert panel.start_probe() and panel.wait(60000)
    assert panel.maps is not None and panel.maps.maps[0].area_id == "design1"
    assert any("kein Werkstück" in n for n in panel.last_notes)


def test_full_run_from_ui(panel):
    panel.design_only.setChecked(False)
    assert panel.start_full()
    assert panel.wait(60000) and panel.last_error == ""
    assert len(panel.objects) == 2 and panel.mosaic is not None
    assert panel.maps is not None and len(panel.maps.maps) == 2
    assert "Fertig" in panel.phase_label.text()
    # Zweiter Lauf: gleiches Material -> Höhenmesh wird nach Kontrollmessung wiederverwendet
    assert panel.start_full() and panel.wait(60000)
    assert "wiederverwendet" in panel.phase_label.text()


def _wait_until(cond, timeout_ms=30000):
    """Ereignisse verarbeiten, bis ``cond()`` gilt – Zustand statt fester Wartezeit."""
    from PySide6.QtCore import QCoreApplication, QElapsedTimer
    from PySide6.QtTest import QTest
    t = QElapsedTimer()
    t.start()
    while not cond():
        if t.elapsed() > timeout_ms:
            return False
        QTest.qWait(5)
    QCoreApplication.processEvents()
    return True


class _MoveGate:
    """Lässt XY-Fahrten des Simulators nur nach ``release()`` durch (eine Kachel je Freigabe)."""

    def __init__(self):
        import threading
        self.permits = threading.Semaphore(0)
        self.waiting = threading.Event()        # Worker steht in einer Fahrt und wartet
        self.open = False

    def wrap(self, hw):
        move = hw.machine.move_to

        def gated(x, y, z=None, feed=None):
            if x is not None and not self.open:
                self.waiting.set()
                assert self.permits.acquire(timeout=60), "Gate nie freigegeben"
                self.waiting.clear()
            return move(x, y, z, feed)
        hw.machine.move_to = gated
        return hw

    def release(self, n=1):
        self.waiting.clear()
        for _ in range(n):
            self.permits.release()

    def open_all(self):
        self.open = True
        self.permits.release(100)


def test_pause_resume_cancel(qapp, editor, monkeypatch):
    """Deterministisch: ein Gate hält den Simulator an bekannter Stelle fest, die Pause
    gilt erst, wenn der Worker sie quittiert (``RunControl.parked``).

    Früher: feste Wartezeiten + „Fortschritt 150 ms stabil“ – unter Last meldete der
    laufende Schritt (Fahrt + Bild) seinen Fortschritt erst danach (CI: assert 2 == 1).
    """
    from PySide6.QtCore import QCoreApplication
    from PySide6.QtTest import QTest
    from scanprobe.panel import ScanPanel
    gate = _MoveGate()
    real = adapters.simulated_setup
    monkeypatch.setattr(adapters, "simulated_setup", lambda *a, **kw: gate.wrap(real(*a, **kw)))
    panel = ScanPanel(editor, ask=False)
    try:
        assert panel.start_scan()
        assert panel.busy and not panel.full_button.isEnabled() and panel.cancel_button.isEnabled()
        ctl = panel.workflow.control
        gate.release()                                     # Kachel 1
        assert _wait_until(lambda: panel.progress.value() == 1 and gate.waiting.is_set())
        # Pause mitten in der Fahrt zu Kachel 2: nur angefordert, Schritt läuft zu Ende
        panel.pause()
        assert panel.pause_button.text() == "Fortsetzen" and ctl.paused and not ctl.parked
        gate.release()                                     # Kachel 2 endet, dann Checkpoint
        assert _wait_until(lambda: ctl.parked), "Pause nicht quittiert"
        QCoreApplication.processEvents()                   # schon eingereihte Signale abholen
        assert panel.progress.value() == 2                 # laufender Schritt zählt genau einmal
        gate.release()                                     # Freigabe da – Pause muss trotzdem halten
        QTest.qWait(300)
        assert ctl.parked and panel.busy and panel.progress.value() == 2
        panel.resume()
        assert not ctl.paused
        assert _wait_until(lambda: panel.progress.value() == 3 and gate.waiting.is_set())
        # Abbruch im Stillstand (nach quittierter Pause) -> sicher „Abgebrochen.“
        panel.pause()
        gate.release()
        assert _wait_until(lambda: ctl.parked), "zweite Pause nicht quittiert"
        QCoreApplication.processEvents()
        assert panel.progress.value() == 4
        panel.cancel()
        assert panel.wait(30000)
        QCoreApplication.processEvents()
        assert panel.phase_label.text() == "Abgebrochen."
        assert panel.full_button.isEnabled() and not panel.cancel_button.isEnabled()
        assert panel.pause_button.text() == "Pause"
        assert panel.mosaic is None
        # nach Abbruch geht ein neuer Lauf
        gate.open_all()
        panel._mode_changed()
        _scan(panel)
        assert len(panel.objects) == 2
    finally:
        gate.open_all()
        panel.shutdown()


def test_run_control_parks_only_between_steps():
    import threading
    from scanprobe.control import Cancelled, RunControl
    ctl = RunControl()
    step_running, step_go = threading.Event(), threading.Event()
    log = []

    def worker():
        try:
            for i in range(3):
                ctl.checkpoint()
                step_running.set()
                step_go.wait(10)
                log.append(i)
        except Cancelled:
            log.append("cancelled")

    t = threading.Thread(target=worker)
    t.start()
    assert step_running.wait(10)
    ctl.pause()
    assert not ctl.parked                       # Schritt läuft noch -> nur angefordert
    step_go.set()                               # Schritt 0 endet, Worker parkt
    assert ctl.wait_parked(10) and log == [0]
    ctl.cancel()                                # weckt den geparkten Worker
    t.join(10)
    assert not t.is_alive() and log == [0, "cancelled"] and not ctl.parked


def test_pi_mode_requires_connection_and_calibration(panel, tmp_path):
    from scanprobe.panel import MODE_PI
    panel.set_mode(MODE_PI)
    assert panel.camera_edit.isEnabled()
    assert not panel.start_scan()
    assert "Nicht mit dem Pi verbunden" in panel.last_error
    panel.client_provider = lambda: object()
    assert not panel.start_scan()
    assert "camera.json" in panel.last_error
    cal = adapters.default_calibration()
    p = tmp_path / "camera.json"
    cal.save(p)
    panel.load_calibration(p)
    assert "px/mm" in panel.cal_label.text()
    assert not panel.busy


class _FakeClient:
    def __init__(self, homed=True, surface=None):
        self.st = SimpleNamespace(skr_connected=True, emergency_latched=False, homed=homed,
                                  job=SimpleNamespace(active=False), position=(100.0, 100.0, 20.0),
                                  workpiece_surface_z=surface)
        self.jogs, self.probes = [], []

    def status(self):
        return self.st

    def jog(self, axis, distance):
        self.jogs.append((axis, distance))
        i = "XYZ".index(axis)
        p = list(self.st.position)
        p[i] += distance
        self.st.position = tuple(p)
        return "ok"

    def probe(self, x, y):
        self.probes.append((x, y))
        self.st.workpiece_surface_z = 3.25
        return "Werkstückoberfläche Z=3.250 mm, Fokus Z=8.750 mm"


def test_pi_adapters_with_fake_client():
    c = _FakeClient()
    m = adapters.PiMachine(c)
    m.move_to(112.3, 90.0, 40.0)
    assert c.st.position == pytest.approx((112.3, 90.0, 40.0))
    assert c.jogs[0][0] == "Z"                       # erst hoch, dann XY
    pr = adapters.PiProbe(c)
    assert pr.probe_z(150, 120, safe_z=20, feed=216, max_depth=-1) == pytest.approx(3.25)
    # Z-Sperre: nie unter Oberfläche + 2 mm
    c.jogs.clear()
    m.move_to(None, None, 1.0)
    assert c.st.position[2] == pytest.approx(5.3, abs=0.06)
    with pytest.raises(ValueError):
        m.move_to(500, 10)
    with pytest.raises(adapters.HardwareNotReady):
        adapters.PiMachine(_FakeClient(homed=False)).move_to(50, 50)


def test_main_window_has_scan_panel(qapp, tmp_path):
    from PySide6.QtCore import QSettings
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(tmp_path))
    QSettings.setDefaultFormat(QSettings.IniFormat)
    main = pytest.importorskip("main")
    win = main.LumaCutStudio()
    win.show()
    qapp.processEvents()
    panel = win.scan_panel
    assert panel.canvas is win.canvas
    assert panel.client_provider() is None              # nicht verbunden
    panel.ask = False
    assert panel.start_scan() and panel.wait(60000)
    assert len(panel.objects) == 2 and win.canvas.view.backdrop is not None
    assert "Werkstück" in win.statusBar().currentMessage()
    win.canvas.undo_stack.setClean()
    win.close()


def test_doc_example_calibration_loads():
    """Das camera.json-Beispiel in der Doku muss gültig bleiben."""
    import json
    import re
    from pathlib import Path
    from scanprobe import CameraCalibration
    doc = Path(__file__).resolve().parents[1] / "docs" / "KAMERA_KALIBRIERUNG.md"
    block = re.search(r"```json\n(.*?)```", doc.read_text(encoding="utf-8"), re.S).group(1)
    cal = CameraCalibration.from_dict(json.loads(block))
    assert cal.has_distortion and cal.exposure == -6
    assert CameraCalibration.from_dict(cal.to_dict()) == cal
