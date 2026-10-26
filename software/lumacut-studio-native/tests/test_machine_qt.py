"""Status poller, machine panel and main window against the fake Pi (offscreen Qt)."""
import os
import tempfile
import time
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import _paths  # noqa: F401
from fake_pi import FakePi

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


@unittest.skipIf(QApplication is None, "PySide6 not installed")
class QtMachineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        os.environ.pop("LUMACUT_KEY", None)
        self.tmp = tempfile.TemporaryDirectory()
        self.store = QSettings(os.path.join(self.tmp.name, "s.ini"), QSettings.IniFormat)
        self.pi = FakePi(required_key="k-123").__enter__()

    def tearDown(self):
        self.pi.__exit__(None, None, None)
        self.tmp.cleanup()

    def test_poller_reports_connected_and_status(self):
        from machine.client import LumaCutClient
        from machine.worker import ConnState, StatusPoller
        poller = StatusPoller(LumaCutClient(self.pi.url, "k-123"), 250)
        states, statuses = [], []
        poller.state_changed.connect(lambda s, m: states.append(s))
        poller.status_received.connect(statuses.append)
        poller.start()
        try:
            self.assertTrue(wait_until(lambda: len(statuses) >= 2))
            self.assertEqual(states[:2], [ConnState.CONNECTING, ConnState.CONNECTED])
            self.assertEqual(statuses[0].position, (120.5, 80.25, 20.0))
        finally:
            poller.stop()
        self.assertEqual(states[-1], ConnState.DISCONNECTED)

    def test_poller_auth_failed(self):
        from machine.client import LumaCutClient
        from machine.worker import ConnState, StatusPoller
        poller = StatusPoller(LumaCutClient(self.pi.url, "bad"), 250)
        states = []
        poller.state_changed.connect(lambda s, m: states.append(s))
        poller.start()
        try:
            self.assertTrue(wait_until(lambda: ConnState.AUTH_FAILED in states))
        finally:
            poller.stop()

    def _panel(self, key="k-123"):
        from machine import settings
        from machine.panel import MachinePanel
        settings.save(settings.ConnectionSettings(base_url=self.pi.url, api_key=key),
                      self.store)
        panel = MachinePanel(store=self.store, confirm=lambda *_: True)
        self.addCleanup(panel.shutdown)
        return panel

    def test_panel_connects_shows_status_and_runs_commands(self):
        from machine.worker import ConnState
        panel = self._panel()
        self.assertEqual(panel.connection_state, ConnState.DISCONNECTED)
        self.assertFalse(panel.home_button.isEnabled())
        self.assertTrue(panel.estop_button.isEnabled())
        panel.connect_to_pi()
        self.assertTrue(wait_until(lambda: "120.50" in panel.pos_label.text()))
        self.assertEqual(panel.connection_state, ConnState.CONNECTED)
        self.assertEqual(panel.homed_label.text(), "Ja")
        self.assertEqual(panel.laser_label.text(), "Aus")
        self.assertTrue(wait_until(panel.home_button.isEnabled))
        panel.home()
        self.assertTrue(wait_until(lambda: "ok home" in panel.error_label.text()))
        panel.step_combo.setCurrentIndex(2)
        self.assertTrue(wait_until(panel.jog_buttons[0].isEnabled))
        panel.jog("Y", 1)
        self.assertTrue(wait_until(lambda: "ok jog" in panel.error_label.text()))
        self.assertEqual(self.pi.last("/api/action")["form"],
                         {"op": "jog", "axis": "Y", "distance": "10.0"})

        # Job: send a file, then start it, progress is displayed.
        path = os.path.join(self.tmp.name, "probe-test.gcode")
        with open(path, "w") as fh:
            fh.write("G0 X40 Y40\nM5 I\n")
        panel.set_job_file(path)
        self.assertTrue(wait_until(panel.send_button.isEnabled))
        panel.send_job()
        self.assertTrue(wait_until(panel.start_button.isEnabled))
        panel.start_job()
        self.assertTrue(wait_until(lambda: "ok start" in panel.error_label.text()))
        self.assertEqual(self.pi.last("/api/action")["form"],
                         {"op": "start", "name": "probe-test.gcode"})
        self.pi.status["job"] = {"file": "probe-test.gcode", "state": "running",
                                 "line": 1, "total": 2, "error": ""}
        self.assertTrue(wait_until(lambda: panel.job_progress.value() == 500))
        self.assertTrue(wait_until(panel.abort_button.isEnabled))
        self.assertFalse(panel.home_button.isEnabled())

    def test_estop_is_sent_even_when_disconnected_or_busy(self):
        panel = self._panel()
        panel.emergency_stop()
        self.assertTrue(wait_until(lambda: "ok estop" in panel.error_label.text()))
        self.assertEqual(self.pi.last("/api/action")["form"], {"op": "estop"})

    def test_panel_auth_failed_state_and_settings_persisted(self):
        from machine import settings
        from machine.worker import ConnState
        panel = self._panel(key="wrong")
        panel.connect_to_pi()
        self.assertTrue(wait_until(lambda: panel.connection_state == ConnState.AUTH_FAILED))
        self.assertIn("abgelehnt", panel.conn_badge.text())
        loaded = settings.load(self.store)
        self.assertEqual(loaded.base_url, self.pi.url)
        self.assertEqual(loaded.api_key, "wrong")
        self.assertNotIn("wrong", repr(loaded))

    def test_main_window_smoke(self):
        import main
        win = main.LumaCutStudio()
        win.show()
        self.app.processEvents()
        # NOT-AUS ist immer sichtbar (Werkzeugleiste); das Machine-Panel selbst
        # liegt seit der Vereinfachung 2026-10-26 hinter „Mehr“.
        self.assertTrue(win.estop_toolbar_button.isVisible())
        win.main_view.set_more(True)
        self.app.processEvents()
        self.assertTrue(win.machine_panel.estop_button.isVisible())
        win.close()  # closeEvent shuts the machine panel down
        self.assertTrue(win.machine_panel._shut_down)


if __name__ == "__main__":
    unittest.main()
