"""One-click job on the Studio side (Anforderungen 2026-10-26 §1, ZUSAMMENARBEIT §4).

Studio only sends the job and op=autorun; the Pi runs home (if needed) →
probe → focus → job → park and reports job.state (+ job.probe, optional
job.phase). Manual home/probe/jog and op=start live in the hidden
"Erweitert" group. An older Pi without op=autorun gets a clear message.
"""
import os
import tempfile
import time
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import _paths  # noqa: F401
from fake_pi import FakePi
from machine.client import OLD_PI_AUTORUN, ApiError, JobState, LumaCutClient

try:
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication
except ImportError:  # pragma: no cover
    QApplication = None


def wait_until(predicate, timeout=15.0):
    app = QApplication.instance()
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


class JobStateParseTests(unittest.TestCase):
    def test_probe_progress_and_phase(self):
        j = JobState.from_json({"state": "probing", "probe": {"done": 3, "total": 12}})
        self.assertEqual((j.phase, j.probe_done, j.probe_total), ("probing", 3, 12))
        self.assertTrue(j.active)
        j = JobState.from_json({"state": "running", "phase": "focusing"})
        self.assertEqual(j.phase, "focusing")
        self.assertTrue(j.active)
        for state in ("focusing", "parking"):
            self.assertTrue(JobState.from_json({"state": state}).active)
        for state in ("idle", "complete", "aborted", "error"):
            self.assertFalse(JobState.from_json({"state": state, "phase": "parking"}).active)
        j = JobState.from_json({"state": "probing", "probe": "kaputt"})
        self.assertEqual((j.probe_done, j.probe_total), (0, 0))

    def test_real_pi_status_without_phase(self):
        """web.py sends no job.phase: after the last line it drains and parks
        while still "running" with line == total -> shown as parking."""
        run = {"file": "a.gcode", "state": "running", "line": 5, "total": 10,
               "error": "", "probe": {"done": 13, "total": 13}}
        self.assertEqual(JobState.from_json(run).phase, "running")
        self.assertEqual(JobState.from_json(dict(run, line=10)).phase, "parking")
        self.assertEqual(JobState.from_json(dict(run, line=0, total=0)).phase, "running")
        self.assertEqual(JobState.from_json(dict(run, state="complete", line=10)).phase,
                         "complete")
        # an explicit phase (future Pi) wins
        self.assertEqual(JobState.from_json(dict(run, line=10, phase="running")).phase,
                         "running")

    def test_features_parsed(self):
        from machine.client import FEATURE_AUTORUN_MESH, MachineStatus
        base = {"connected": True, "firmware": "marlin"}
        s = MachineStatus.from_json(dict(base, features=["autorun_mesh", "materials"]))
        self.assertTrue(s.has_feature(FEATURE_AUTORUN_MESH))
        self.assertTrue(MachineStatus.from_json(
            dict(base, features={"autorun_mesh": True})).has_feature("autorun_mesh"))
        for old in (base, dict(base, features="autorun_mesh"),
                    dict(base, features={"autorun_mesh": False})):
            self.assertFalse(MachineStatus.from_json(old).has_feature("autorun_mesh"))

    def test_old_pi_without_autorun_gets_clear_message(self):
        with FakePi() as pi:
            pi.make_pre_autorun_pi()
            with self.assertRaises(ApiError) as ctx:
                LumaCutClient(pi.url).autorun_job("a.gcode")
            self.assertEqual(str(ctx.exception), OLD_PI_AUTORUN)

    def test_other_autorun_errors_pass_through(self):
        with FakePi() as pi:
            pi.fail["autorun"] = (400, {"error": "Nicht referenziert"})
            with self.assertRaises(ApiError) as ctx:
                LumaCutClient(pi.url).autorun_job("a.gcode")
            self.assertIn("Nicht referenziert", str(ctx.exception))


@unittest.skipIf(QApplication is None, "PySide6 not installed")
class OneClickPanelTests(unittest.TestCase):
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

    def panel(self):
        from machine import settings
        from machine.panel import MachinePanel
        settings.save(settings.ConnectionSettings(base_url=self.pi.url), self.store)
        panel = MachinePanel(store=self.store, confirm=lambda *_: True)
        self.addCleanup(panel.shutdown)
        panel.connect_to_pi()
        self.assertTrue(wait_until(panel.home_button.isEnabled))
        return panel

    def ops(self, op):
        return [r["form"] for r in self.pi.requests if r.get("form", {}).get("op") == op]

    def idle(self, panel):
        return wait_until(lambda: not panel._runner.busy)

    def test_single_start_button_and_hidden_service_group(self):
        panel = self.panel()
        # The main view's "Start" is the one primary start; the panel button
        # is the file path and says so (no second "Auftrag starten").
        self.assertEqual(panel.autorun_button.text(), "Datei-Auftrag starten")
        self.assertNotEqual(panel.autorun_button.objectName(), "primary")
        self.assertIn("Hauptansicht", panel.autorun_button.toolTip())
        self.assertTrue(panel.motion_group.isHidden())
        # manual controls (and op=start) are inside the service group
        for b in (panel.home_button, panel.focus_button, panel.start_button,
                  *panel.jog_buttons):
            self.assertTrue(panel.motion_group.isAncestorOf(b), b.text())
        self.assertFalse(panel.motion_group.isAncestorOf(panel.autorun_button))
        panel.advanced_toggle.setChecked(True)
        self.assertFalse(panel.motion_group.isHidden())
        panel.set_advanced_visible(False)
        self.assertTrue(panel.motion_group.isHidden())
        self.assertFalse(panel.advanced_toggle.isChecked())
        # hidden buttons keep their enabled logic
        self.assertTrue(panel.home_button.isEnabled())

    def test_one_click_sends_chosen_file_then_autorun(self):
        panel = self.panel()
        path = os.path.join(self.tmp.name, "motiv.gcode")
        with open(path, "w") as fh:
            fh.write("G0 X40 Y40\n")
        panel.set_job_file(path)
        self.assertTrue(wait_until(panel.autorun_button.isEnabled))
        panel.autorun_job()
        self.assertTrue(self.idle(panel))
        self.assertEqual(self.pi.uploads, ["motiv.gcode"])
        runs = self.ops("autorun")
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0]["name"], "motiv.gcode")
        self.assertNotIn("x", runs[0])           # the Pi picks the probe points
        self.assertEqual(self.ops("start"), [])
        self.assertEqual(self.ops("home"), [])  # no manual homing from Studio
        self.assertEqual(panel._uploaded, "motiv.gcode")

    def test_one_click_from_canvas_export(self):
        panel = self.panel()
        panel.send_gcode("canvas.gcode", "G0 X40 Y40\n", autorun=True)
        self.assertTrue(self.idle(panel))
        self.assertTrue(wait_until(lambda: len(self.ops("autorun")) == 1))
        self.assertEqual(self.ops("autorun")[0]["name"], "canvas.gcode")
        self.assertEqual(self.ops("start"), [])

    def test_one_click_with_placement_places_first(self):
        panel = self.panel()
        panel.send_gcode("a.gcode", "G0 X40 Y40\n")
        self.assertTrue(wait_until(lambda: panel._uploaded == "a.gcode"))
        self.assertTrue(self.idle(panel))
        panel.set_job_origin("current", "tr")
        panel.autorun_job()
        self.assertTrue(self.idle(panel))
        self.assertEqual(self.ops("place")[-1]["anchor"], "tr")
        self.assertEqual(self.ops("autorun")[-1].get("placement"), "1")

    def test_phase_display_follows_pi(self):
        panel = self.panel()
        self.pi.set_job_phase("homing")
        self.assertTrue(wait_until(lambda: "Referenzfahrt" in panel.job_label.text()))
        self.assertFalse(panel.autorun_button.isEnabled())
        self.assertTrue(panel.abort_button.isEnabled())
        self.pi.set_job_phase("probing", probe=(3, 12))
        self.assertTrue(wait_until(lambda: "Abtasten 3 / 12" in panel.job_label.text()))
        self.assertIn("3 / 12 Punkte", panel.job_progress.format())
        self.pi.set_job_phase("running", phase="focusing")
        self.assertTrue(wait_until(lambda: "Fokus einstellen" in panel.job_label.text()))
        self.pi.set_job_phase("running", phase="parking")
        self.assertTrue(wait_until(lambda: "Parken" in panel.job_label.text()))
        self.assertTrue(panel.estop_button.isEnabled())
        self.pi.set_job_phase("complete")
        self.assertTrue(wait_until(lambda: "Fertig" in panel.job_label.text()))

    def test_phase_display_with_real_pi_fields(self):
        panel = self.panel()
        self.pi.set_job_phase("running", line=4, total=10)
        self.assertTrue(wait_until(lambda: "Läuft" in panel.job_label.text()))
        self.pi.set_job_phase("running", line=10, total=10)
        self.assertTrue(wait_until(lambda: "Parken" in panel.job_label.text()))
        self.assertTrue(panel.abort_button.isEnabled())
        self.pi.set_job_phase("error")
        with self.pi.lock:
            self.pi.status["job"]["error"] = "Abtasten fehlgeschlagen"
        self.assertTrue(wait_until(lambda: "Abtasten fehlgeschlagen" in panel.job_label.text()))

    def test_autorun_mesh_hint_for_older_pi(self):
        asked = []
        from machine import settings
        from machine.panel import OLD_PI_MESH, MachinePanel
        settings.save(settings.ConnectionSettings(base_url=self.pi.url), self.store)
        panel = MachinePanel(store=self.store,
                             confirm=lambda title, text: asked.append(text) or False)
        self.addCleanup(panel.shutdown)
        panel.connect_to_pi()
        self.assertTrue(wait_until(panel.home_button.isEnabled))
        panel.send_gcode("a.gcode", "G0 X40 Y40\n")
        self.assertTrue(wait_until(lambda: panel._uploaded == "a.gcode"))
        self.assertTrue(self.idle(panel))
        self.assertTrue(wait_until(lambda: OLD_PI_MESH in panel.autorun_button.toolTip()))
        panel.autorun_job()
        self.assertIn(OLD_PI_MESH, asked[-1])
        self.pi.set_features("autorun_mesh", "materials")
        self.assertTrue(wait_until(lambda: OLD_PI_MESH not in panel.autorun_button.toolTip()))
        panel.autorun_job()
        self.assertNotIn(OLD_PI_MESH, asked[-1])
        self.assertEqual(self.ops("autorun"), [])   # declined twice

    def test_autorun_task_for_main_start_places_job(self):
        panel = self.panel()
        panel.send_gcode("a.gcode", "G0 X40 Y40\n")
        self.assertTrue(wait_until(lambda: panel._uploaded == "a.gcode"))
        self.assertTrue(self.idle(panel))
        panel.set_job_origin("current", "br")
        call = panel.autorun_task("a.gcode")
        call()   # worker-thread call; synchronous here
        self.assertEqual(self.ops("place")[-1]["anchor"], "br")
        self.assertEqual(self.ops("autorun")[-1].get("placement"), "1")
        panel.set_job_origin("absolute", "tr")
        panel.autorun_task("a.gcode")()
        self.assertNotIn("placement", self.ops("autorun")[-1])

    def test_canvas_one_click_follows_origin(self):
        panel = self.panel()
        panel.set_job_origin("current", "tr")
        panel.send_gcode("c.gcode", "G0 X40 Y40\n", autorun=True)
        self.assertTrue(wait_until(lambda: len(self.ops("autorun")) == 1))
        self.assertEqual(self.ops("place")[-1]["anchor"], "tr")
        self.assertEqual(self.ops("autorun")[-1].get("placement"), "1")

    def test_abort_and_estop_in_every_phase(self):
        panel = self.panel()
        for state, phase in (("homing", None), ("probing", None), ("running", "focusing"),
                             ("running", None), ("running", "parking")):
            self.pi.set_job_phase(state, phase=phase)
            self.assertTrue(wait_until(panel.abort_button.isEnabled), (state, phase))
            self.assertTrue(panel.estop_button.isEnabled())
        before = len(self.ops("abort"))
        panel.abort_job()
        self.assertTrue(wait_until(lambda: len(self.ops("abort")) == before + 1))

    def test_old_pi_shows_update_message(self):
        self.pi.make_pre_autorun_pi()
        panel = self.panel()
        panel.send_gcode("a.gcode", "G0 X40 Y40\n")
        self.assertTrue(wait_until(lambda: panel._uploaded == "a.gcode"))
        self.assertTrue(self.idle(panel))
        panel.autorun_job()
        self.assertTrue(self.idle(panel))
        self.assertTrue(wait_until(lambda: "Pi-Dienst" in panel.error_label.text()))
        self.assertIn("Erweitert", panel.error_label.text())


if __name__ == "__main__":
    unittest.main()
