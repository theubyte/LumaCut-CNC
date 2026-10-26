"""Stability regressions of the machine connection (audit 2026-10-26).

- A failed or superseded upload never leaves the previous job startable.
- Closing the Studio while the Pi runs a job/frame asks first.
- LightBurn or another client holding the Pi locks the motion buttons;
  the USB heartbeat owner "monitor" does not.
- The Pi status snapshot fields (busy/stale_ms) and the upload timeout.
"""
import os
import tempfile
import time
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import _paths  # noqa: F401  (puts src/ on sys.path)
from fake_pi import FakePi

from machine import client as client_mod
from machine.client import LumaCutClient, MachineStatus, upload_timeout

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
    app.processEvents()
    return predicate()


class StatusSnapshotParsingTests(unittest.TestCase):
    BASE = {"firmware": "marlin", "connected": True, "owner": "Frei"}

    def test_snapshot_fields(self):
        s = MachineStatus.from_json(dict(self.BASE, busy=True, stale_ms=1500))
        self.assertTrue(s.pi_busy)
        self.assertEqual(s.stale_ms, 1500)
        fresh = MachineStatus.from_json(dict(self.BASE, busy=False, stale_ms=0))
        self.assertFalse(fresh.pi_busy)
        self.assertEqual(fresh.stale_ms, 0)

    def test_older_pi_without_snapshot_fields_is_fresh(self):
        s = MachineStatus.from_json(dict(self.BASE))
        self.assertFalse(s.pi_busy)
        self.assertEqual(s.stale_ms, 0)

    def test_unknown_snapshot_age(self):
        for value in (None, "x", True, [1]):
            s = MachineStatus.from_json(dict(self.BASE, busy=True, stale_ms=value))
            self.assertIsNone(s.stale_ms, value)

    def test_heartbeat_owner_is_not_busy(self):
        self.assertFalse(MachineStatus.from_json(dict(self.BASE, owner="monitor")).busy)
        self.assertEqual(
            MachineStatus.from_json(dict(self.BASE, owner="monitor")).foreign_owner, "")
        lb = MachineStatus.from_json(dict(self.BASE, owner="lightburn"))
        self.assertTrue(lb.busy)
        self.assertEqual(lb.foreign_owner, "lightburn")
        for own in ("job", "frame", "Frei"):
            self.assertEqual(
                MachineStatus.from_json(dict(self.BASE, owner=own)).foreign_owner, "")


class UploadTimeoutTests(unittest.TestCase):
    def test_scales_with_size(self):
        base = client_mod.UPLOAD_TIMEOUT_S
        self.assertEqual(upload_timeout(0), base)
        self.assertEqual(upload_timeout(1), base + client_mod.UPLOAD_TIMEOUT_PER_MB_S)
        big = upload_timeout(client_mod.MAX_JOB_BYTES)
        self.assertEqual(big, base + 32 * client_mod.UPLOAD_TIMEOUT_PER_MB_S)

    def test_upload_job_uses_scaled_timeout(self):
        c = LumaCutClient("http://127.0.0.1:9")
        payload = b"G0 X40 Y40\n" * (300 * 1024)     # ~3.3 MB
        with mock.patch.object(c, "_request", return_value={"message": "ok"}) as req:
            c.upload_job("big.gcode", payload)
        self.assertGreater(req.call_args.kwargs["timeout"], client_mod.UPLOAD_TIMEOUT_S)
        self.assertGreaterEqual(req.call_args.kwargs["timeout"], upload_timeout(len(payload)))


@unittest.skipIf(QApplication is None, "PySide6 not installed")
class PanelStabilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        os.environ.pop("LUMACUT_KEY", None)
        self.tmp = tempfile.TemporaryDirectory()
        self.store = QSettings(os.path.join(self.tmp.name, "s.ini"), QSettings.IniFormat)
        self.pi = FakePi().__enter__()
        self.answer = True
        self.asked = []

    def tearDown(self):
        self.pi.__exit__(None, None, None)
        self.tmp.cleanup()

    def confirm(self, title, text):
        self.asked.append((title, text))
        return self.answer

    def panel(self):
        from machine import settings
        from machine.panel import MachinePanel
        settings.save(settings.ConnectionSettings(base_url=self.pi.url), self.store)
        panel = MachinePanel(store=self.store, confirm=self.confirm)
        self.addCleanup(panel.shutdown)
        panel.connect_to_pi()
        self.assertTrue(wait_until(panel.home_button.isEnabled))
        return panel

    def idle(self, panel):
        return wait_until(lambda: not panel._runner.busy)

    def actions(self, op):
        return [r for r in self.pi.requests if r.get("form", {}).get("op") == op]

    # -- stale upload -------------------------------------------------
    def test_failed_upload_does_not_leave_previous_job_startable(self):
        panel = self.panel()
        panel.send_gcode("a.gcode", "G0 X40 Y40\n")
        self.assertTrue(wait_until(lambda: panel._uploaded == "a.gcode"))
        self.assertTrue(self.idle(panel))
        self.assertTrue(wait_until(panel.start_button.isEnabled))
        self.pi.fail["upload"] = (400, {"error": "G-Code Zeile 1: kaputt"})
        panel.send_gcode("b.gcode", "G0 X40 Y40\n")
        self.assertTrue(self.idle(panel))
        self.assertEqual(panel._uploaded, "")
        self.assertFalse(panel.start_button.isEnabled())
        self.assertFalse(panel.autorun_button.isEnabled())
        panel.start_job()
        self.assertTrue(self.idle(panel))
        self.assertEqual(self.actions("start"), [])

    def test_failed_reupload_of_same_name_is_not_startable(self):
        # The Pi keeps the old a.gcode when the new one is rejected.
        panel = self.panel()
        panel.send_gcode("a.gcode", "G0 X40 Y40\n")
        self.assertTrue(wait_until(lambda: panel._uploaded == "a.gcode"))
        self.assertTrue(self.idle(panel))
        self.pi.fail["upload"] = (400, {"error": "Motiv außerhalb"})
        panel.send_gcode("a.gcode", "G0 X1 Y1\n")
        self.assertTrue(self.idle(panel))
        self.assertEqual(panel._uploaded, "")
        self.assertFalse(panel.start_button.isEnabled())

    def test_start_disabled_while_upload_in_flight(self):
        panel = self.panel()
        panel.send_gcode("a.gcode", "G0 X40 Y40\n")
        self.assertTrue(wait_until(lambda: panel._uploaded == "a.gcode"))
        self.assertTrue(self.idle(panel))
        self.pi.delay["upload"] = 1.0
        panel.send_gcode("b.gcode", "G0 X40 Y40\n")
        self.assertEqual(panel._uploaded, "")       # at once, not after the upload
        self.assertFalse(panel.start_button.isEnabled())
        self.assertTrue(wait_until(lambda: panel._uploaded == "b.gcode"))

    def test_upload_superseded_by_file_choice_is_not_startable(self):
        panel = self.panel()
        self.pi.delay["upload"] = 0.8
        panel.send_gcode("a.gcode", "G0 X40 Y40\n")
        self.assertTrue(wait_until(lambda: self.pi.waiting.get("upload", 0) > 0, 5))
        path = os.path.join(self.tmp.name, "other.gcode")
        with open(path, "w") as fh:
            fh.write("G0 X40 Y40\n")
        panel.set_job_file(path)
        self.assertTrue(self.idle(panel))
        self.assertEqual(panel._uploaded, "")
        self.assertFalse(panel.start_button.isEnabled())

    def test_busy_runner_keeps_previous_upload(self):
        # A send that is not dispatched (runner busy) must not drop the
        # job that is already on the Pi.
        panel = self.panel()
        panel.send_gcode("a.gcode", "G0 X40 Y40\n")
        self.assertTrue(wait_until(lambda: panel._uploaded == "a.gcode"))
        self.assertTrue(self.idle(panel))
        self.pi.delay["home"] = 1.0
        panel.home()
        self.assertTrue(wait_until(lambda: panel._runner.busy))
        panel.send_gcode("b.gcode", "G0 X40 Y40\n")
        self.assertEqual(panel._uploaded, "a.gcode")
        self.assertTrue(self.idle(panel))
        self.assertEqual(self.pi.uploads, ["a.gcode"])

    def test_send_and_start_starts_the_new_file(self):
        panel = self.panel()
        panel.send_gcode("a.gcode", "G0 X40 Y40\n")
        self.assertTrue(wait_until(lambda: panel._uploaded == "a.gcode"))
        self.assertTrue(self.idle(panel))
        panel.send_gcode("b.gcode", "G0 X40 Y40\n", start=True)
        self.assertTrue(wait_until(lambda: len(self.actions("start")) == 1))
        self.assertEqual(self.actions("start")[0]["form"]["name"], "b.gcode")

    # -- close while busy ----------------------------------------------
    def test_close_idle_does_not_ask(self):
        panel = self.panel()
        self.assertTrue(panel.confirm_close())
        self.assertEqual(self.asked, [])

    def test_close_during_frame_or_job_asks(self):
        panel = self.panel()
        with self.pi.lock:
            self.pi.status["frame"] = {"state": "running", "mode": "box",
                                       "line": 1, "total": 4, "error": ""}
            self.pi.status["owner"] = "frame"
        self.assertTrue(wait_until(lambda: panel.active_operation() == "Rahmenfahrt"))
        self.answer = False
        self.assertFalse(panel.confirm_close())
        self.assertIn("NICHT", self.asked[-1][1])
        self.answer = True
        self.assertTrue(panel.confirm_close())
        with self.pi.lock:
            self.pi.status["frame"]["state"] = "complete"
            self.pi.status["owner"] = "job"
            self.pi.status["job"] = {"file": "a.gcode", "state": "running",
                                     "line": 3, "total": 9, "error": ""}
        self.assertTrue(wait_until(lambda: "a.gcode" in panel.active_operation()))
        self.answer = False
        self.assertFalse(panel.confirm_close())

    def test_close_during_long_command_asks_but_not_for_estop(self):
        panel = self.panel()
        self.pi.delay["home"] = 1.0
        panel.home()
        self.assertTrue(wait_until(lambda: panel._runner.busy))
        self.assertEqual(panel.active_operation(), "Home")
        self.answer = False
        self.assertFalse(panel.confirm_close())
        self.assertTrue(self.idle(panel))
        self.asked.clear()
        self.assertTrue(panel.confirm_close())
        self.assertEqual(self.asked, [])

    # -- foreign owner ------------------------------------------------
    def test_lightburn_owner_locks_motion_but_not_estop(self):
        panel = self.panel()
        panel.send_gcode("a.gcode", "G0 X40 Y40\n")
        self.assertTrue(wait_until(lambda: panel._uploaded == "a.gcode"))
        self.assertTrue(wait_until(panel.start_button.isEnabled))
        with self.pi.lock:
            self.pi.status["owner"] = "lightburn"
        self.assertTrue(wait_until(lambda: not panel.home_button.isEnabled()))
        for b in (panel.park_button, panel.focus_button, panel.start_button,
                  panel.autorun_button, *panel.jog_buttons):
            self.assertFalse(b.isEnabled(), b.text())
        self.assertTrue(panel.estop_button.isEnabled())
        self.assertIn("lightburn", panel.owner_label.text())
        with self.pi.lock:
            self.pi.status["owner"] = "monitor"     # USB heartbeat: transient
        self.assertTrue(wait_until(panel.home_button.isEnabled))
        self.assertEqual(panel.owner_label.text(), "Frei")

    def test_pi_snapshot_keeps_status_fresh_during_long_move(self):
        panel = self.panel()
        with self.pi.lock:
            self.pi.status.update(owner="web", state="Busy", busy=True, stale_ms=4200)
        self.assertTrue(wait_until(lambda: "Pi fährt" in panel.owner_label.text()))
        self.assertFalse(panel.stale)
        self.assertFalse(panel.home_button.isEnabled())
        self.assertTrue(panel.estop_button.isEnabled())

    # -- external users (scan/probe) ---------------------------------
    def test_external_operation_locks_panel_and_counts_as_active(self):
        panel = self.panel()
        self.assertIs(panel.client, panel._client)
        panel.set_external_operation("Scan")
        self.assertFalse(panel.home_button.isEnabled())
        self.assertFalse(panel.send_button.isEnabled())
        self.assertTrue(panel.estop_button.isEnabled())
        self.assertTrue(panel._poller._command_running)
        self.assertEqual(panel.active_operation(), "Scan")
        self.answer = False
        self.assertFalse(panel.confirm_close())
        panel.set_external_operation("")
        self.assertFalse(panel._poller._command_running)
        self.assertTrue(wait_until(panel.home_button.isEnabled))
        self.assertEqual(panel.active_operation(), "")


if __name__ == "__main__":
    unittest.main()
