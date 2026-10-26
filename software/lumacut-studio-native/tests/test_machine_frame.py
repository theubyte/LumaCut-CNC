"""op=frame: client, panel button and locking against the fake Pi.

Framing must run the laser-off outline on the Pi without uploading a new
job, so the job sent before stays loaded and can be started right after.
"""
import os
import sys
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import _paths  # noqa: F401
from fake_pi import FakePi
from machine.client import ApiError, LumaCutClient, MachineStatus

try:
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication
except ImportError:  # pragma: no cover
    QApplication = None

ROOT = Path(__file__).resolve().parents[3]


def frame_program(mode="box"):
    from lumacut_job.estimate import frame_gcode
    from lumacut_job.planner import optimize_layers
    from lumacut_canvas.export import job_layers
    from lumacut_canvas import Document, Geometry, Shape
    doc = Document()
    doc.add_shape(Shape("rect", Geometry(60, 60, 80, 40), doc.active_layer_id))
    doc.add_shape(Shape("ellipse", Geometry(170, 90, 30, 30), doc.active_layer_id))
    return frame_gcode(optimize_layers(job_layers(doc)), mode=mode)


def wait_until(predicate, timeout=5.0):
    app = QApplication.instance()
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


class FrameClientTests(unittest.TestCase):
    def setUp(self):
        self.pi = FakePi().__enter__()
        self.addCleanup(self.pi.__exit__, None, None, None)
        self.client = LumaCutClient(self.pi.url)

    def test_frame_posts_gcode_and_mode_without_upload(self):
        g = frame_program("hull")
        self.assertEqual(self.client.frame(g, "hull"), "Rahmenfahrt gestartet")
        form = self.pi.last("/api/action")["form"]
        self.assertEqual((form["op"], form["mode"], form["gcode"]), ("frame", "hull", g))
        self.assertEqual(self.pi.uploads, [])
        status = self.client.status()
        self.assertTrue(status.framing and status.busy)
        self.assertEqual((status.frame.state, status.frame.mode), ("running", "hull"))
        self.assertEqual(status.job.state, "idle")

    def test_invalid_frame_never_reaches_the_pi(self):
        for gcode, mode in (("", "box"), ("G0 X1 Y1", "spiral"), ("G0 X1\n" * 20000, "box")):
            with self.assertRaises(ValueError):
                self.client.frame(gcode, mode)
        self.assertEqual(self.pi.requests, [])

    def test_frame_on_old_pi_service_explains_gap(self):
        self.pi.actions.discard("frame")
        with self.assertRaises(ApiError) as ctx:
            self.client.frame(frame_program(), "box")
        self.assertIn("op=frame fehlt", str(ctx.exception))

    def test_pi_refusal_is_passed_through(self):
        self.pi.fail["frame"] = (400, {"error": "Vor dem Rahmen referenzieren"})
        with self.assertRaisesRegex(ApiError, "referenzieren"):
            self.client.frame(frame_program(), "box")

    def test_status_without_frame_field_is_idle(self):
        status = MachineStatus.from_json({"connected": True, "owner": None})
        self.assertFalse(status.framing)
        self.assertEqual(status.frame.state, "idle")


class FrameMatchesPiGuardTests(unittest.TestCase):
    """The Studio frame generator output passes the Pi's op=frame check."""

    def test_generator_output_accepted_by_pi_frame_program(self):
        try:
            import flask  # noqa: F401
        except ImportError:  # pragma: no cover
            self.skipTest("flask not installed")
        programs = {m: frame_program(m) for m in ("box", "hull")}
        script = (
            "import json, sys\n"
            "from marlin import web\n"
            "web.machine.homing_verified = True\n"
            "for mode, text in json.loads(sys.stdin.read()).items():\n"
            "    cmds = web.frame_program(text)\n"
            "    assert not any(c.startswith('M3') for c in cmds), cmds\n"
            "    print(mode, len(cmds))\n")
        import json
        with tempfile.TemporaryDirectory() as tmp:
            env = dict(os.environ, LUMACUT_DATA=tmp, PYTHONPATH=str(ROOT / "pi400"))
            run = subprocess.run([sys.executable, "-c", script], input=json.dumps(programs),
                                 env=env, text=True, capture_output=True, timeout=30)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertIn("box", run.stdout)
        self.assertIn("hull", run.stdout)


@unittest.skipIf(QApplication is None, "PySide6 not installed")
class FramePanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        os.environ.pop("LUMACUT_KEY", None)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = QSettings(os.path.join(self.tmp.name, "s.ini"), QSettings.IniFormat)
        self.pi = FakePi().__enter__()
        self.addCleanup(self.pi.__exit__, None, None, None)
        self.answer = True

    def panel(self):
        from machine import settings
        from machine.panel import MachinePanel
        settings.save(settings.ConnectionSettings(base_url=self.pi.url), self.store)
        panel = MachinePanel(store=self.store, confirm=lambda *_: self.answer)
        self.addCleanup(panel.shutdown)
        self.modes = []
        def provider(mode):
            self.modes.append(mode)
            return frame_program(mode)
        panel.set_frame_provider(provider)
        panel.connect_to_pi()
        self.assertTrue(wait_until(panel.home_button.isEnabled))
        return panel

    def test_send_frame_start_without_reupload(self):
        panel = self.panel()
        available = []
        panel.frame_available_changed.connect(available.append)
        panel.send_gcode("canvas.gcode", "G0 X40 Y40\nM5 I\n")
        self.assertTrue(wait_until(panel.start_button.isEnabled))
        self.assertEqual(self.pi.uploads, ["canvas.gcode"])
        self.assertTrue(panel.frame_button.isEnabled())
        panel.frame_mode_combo.setCurrentIndex(panel.frame_mode_combo.findData("hull"))
        self.assertTrue(panel.frame())
        self.assertTrue(wait_until(lambda: "Rahmenfahrt gestartet" in panel.error_label.text()))
        self.assertEqual(self.modes, ["hull"])
        self.assertEqual(self.pi.last("/api/action")["form"]["mode"], "hull")
        # While framing: status text, everything locked except abort + E-Stop.
        self.assertTrue(wait_until(lambda: "Rahmenfahrt läuft" in panel.job_label.text()))
        self.assertIn("Gummiband", panel.job_label.text())
        self.assertIn("canvas.gcode bleibt geladen", panel.job_label.text())
        for b in (panel.frame_button, panel.start_button, panel.autorun_button,
                  panel.home_button, panel.park_button, *panel.jog_buttons):
            self.assertFalse(b.isEnabled(), b.text())
        self.assertTrue(panel.abort_button.isEnabled())
        self.assertTrue(panel.estop_button.isEnabled())
        self.assertFalse(panel.frame_available)
        self.assertFalse(panel.frame_gcode(frame_program(), "box"))   # refused locally
        self.assertIn("Rahmenfahrt", panel.error_label.text())
        self.pi.finish_frame("complete")
        self.assertTrue(wait_until(lambda: "Rahmenfahrt fertig" in panel.error_label.text()))
        # The uploaded job is still the start target: no second upload.
        self.assertTrue(wait_until(panel.start_button.isEnabled))
        panel.start_job()
        self.assertTrue(wait_until(lambda: "ok start" in panel.error_label.text()))
        self.assertEqual(self.pi.last("/api/action")["form"],
                         {"op": "start", "name": "canvas.gcode"})
        self.assertEqual(self.pi.uploads, ["canvas.gcode"])
        self.assertIn(False, available)
        self.assertTrue(panel.frame_available)

    def test_abort_reaches_a_running_frame(self):
        panel = self.panel()
        self.assertTrue(panel.frame_gcode(frame_program(), "box"))
        self.assertTrue(wait_until(panel.abort_button.isEnabled))
        panel.abort_job()
        self.assertTrue(wait_until(lambda: "ok abort" in panel.error_label.text()))
        self.pi.finish_frame("aborted")
        self.assertTrue(wait_until(lambda: "Rahmenfahrt abgebrochen" in panel.error_label.text()))

    def test_abort_stays_available_when_status_stalls_while_framing(self):
        from machine import panel as panel_module
        old = panel_module.STALE_AFTER_S
        panel_module.STALE_AFTER_S = 0.5
        self.addCleanup(setattr, panel_module, "STALE_AFTER_S", old)
        panel = self.panel()
        self.assertTrue(panel.frame_gcode(frame_program(), "box"))
        self.assertTrue(wait_until(lambda: "Rahmenfahrt läuft" in panel.job_label.text()))
        self.pi.delay["status"] = 1.5          # Pi holds machine.lock per edge
        self.assertTrue(wait_until(lambda: panel.stale, 3))
        self.assertFalse(panel.home_button.isEnabled())
        self.assertFalse(panel.start_button.isEnabled())
        self.assertTrue(panel.abort_button.isEnabled())
        self.assertTrue(panel.estop_button.isEnabled())
        panel.abort_job()
        self.assertTrue(wait_until(lambda: "ok abort" in panel.error_label.text()))
        self.pi.delay.clear()

    def test_frame_locked_when_not_homed_estop_or_declined(self):
        panel = self.panel()
        self.answer = False
        self.assertFalse(panel.frame())
        self.assertEqual(self.modes, ["box"])
        self.answer = True
        self.pi.status["homed"] = False
        self.assertTrue(wait_until(lambda: not panel.frame_button.isEnabled()))
        self.assertTrue(panel.home_button.isEnabled())
        self.assertFalse(panel.frame_gcode(frame_program(), "box"))
        self.assertIn("referenzieren", panel.error_label.text())
        self.pi.status.update(homed=True, emergency_latched=True)
        self.assertTrue(wait_until(lambda: panel.reset_button.isEnabled()))
        self.assertFalse(panel.frame_button.isEnabled())
        self.assertTrue(panel.estop_button.isEnabled())
        self.assertEqual([r for r in self.pi.requests if r.get("form", {}).get("op") == "frame"], [])

    def test_old_pi_without_frame_gets_clear_message(self):
        panel = self.panel()
        self.pi.actions.discard("frame")
        self.assertTrue(panel.frame_gcode(frame_program(), "box"))
        self.assertTrue(wait_until(lambda: "op=frame fehlt" in panel.error_label.text()))

    def test_no_provider_keeps_button_disabled(self):
        panel = self.panel()
        panel.set_frame_provider(None)
        self.assertFalse(panel.frame_button.isEnabled())


if __name__ == "__main__":
    unittest.main()
