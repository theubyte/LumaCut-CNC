"""Multi-job queue on the Pi (#17): client, status parsing and panel list."""
import os
import tempfile
import time
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import _paths  # noqa: F401
from fake_pi import FakePi
from machine.client import ApiError, LumaCutClient, MachineStatus, QueueState

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


def ops(pi):
    return [r["form"] for r in pi.requests if "form" in r and r["form"]["op"] != "status"]


class QueueClientTests(unittest.TestCase):
    def setUp(self):
        self.pi = FakePi().__enter__()
        self.addCleanup(self.pi.__exit__, None, None, None)
        self.client = LumaCutClient(self.pi.url)

    def test_status_parsing_and_tolerance(self):
        q = self.client.status().queue
        self.assertTrue(q.supported)
        self.assertEqual((q.items, q.state, q.max), ([], "idle", 50))
        self.assertFalse(q.active)
        q = QueueState.from_json({"items": [{"id": 3, "file": "a.gcode", "state": "running",
                                             "dx": 1.5}, {"file": "ohne-id"}, "kaputt"],
                                  "state": "pausing", "current": 3, "max": 50})
        self.assertEqual([i.id for i in q.items], [3])
        self.assertEqual((q.items[0].dx, q.current), (1.5, 3))
        self.assertTrue(q.active)
        self.assertEqual(MachineStatus.from_json({"homed": True, "queue": 7}).queue,
                         QueueState())
        self.pi.make_pre_queue_pi()
        self.assertFalse(self.client.status().queue.supported)
        self.assertTrue(self.client.status().origin.supported)

    def test_ops_and_fields(self):
        self.client.queue_add("a.gcode")
        self.client.queue_add("b.gcode", "user", "center")
        self.client.queue_add("c.gcode", placement=True)
        self.client.queue_skip(2)
        self.client.queue_remove(1)
        self.client.queue_run()
        self.client.queue_pause()
        self.client.queue_clear()
        self.assertEqual(ops(self.pi), [
            {"op": "queue_add", "name": "a.gcode", "origin": "absolute", "anchor": "tl"},
            {"op": "queue_add", "name": "b.gcode", "origin": "user", "anchor": "center"},
            {"op": "queue_add", "name": "c.gcode", "placement": "1"},
            {"op": "queue_skip", "id": "2"},
            {"op": "queue_remove", "id": "1"},
            {"op": "queue_run"}, {"op": "queue_pause"}, {"op": "queue_clear"}])
        with self.assertRaises(ValueError):
            self.client.queue_add("a.gcode", "mond")
        with self.assertRaises(ValueError):
            self.client.queue_add("a.gcode", "user", "mitte")
        with self.assertRaises(ValueError):
            self.client.queue_add("../x.gcode")

    def test_older_pi_explains_update(self):
        self.pi.make_pre_queue_pi()
        for call in (lambda: self.client.queue_add("a.gcode"), self.client.queue_run,
                     lambda: self.client.queue_remove(1), self.client.queue_clear):
            with self.assertRaises(ApiError) as ctx:
                call()
            self.assertIn("Warteschlange", str(ctx.exception))
            self.assertIn("Pi aktualisieren", str(ctx.exception))


@unittest.skipIf(QApplication is None, "PySide6 not installed")
class QueuePanelTests(unittest.TestCase):
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

    def send(self, panel, name):
        panel.send_gcode(name, "G0 X40 Y40\nM5 I\n")
        self.assertTrue(wait_until(lambda: panel._uploaded == name
                                   and panel.queue_add_button.isEnabled()))

    def test_add_run_pause_skip_remove(self):
        panel = self.panel()
        self.assertFalse(panel.queue_add_button.isEnabled())   # nothing sent yet
        self.assertFalse(panel.queue_run_button.isEnabled())
        self.send(panel, "a.gcode")
        panel.set_job_origin("user", "br")
        self.assertTrue(panel.queue_job())
        self.assertTrue(wait_until(lambda: panel.queue_list.count() == 1))
        self.assertEqual(ops(self.pi)[-1], {"op": "queue_add", "name": "a.gcode",
                                            "origin": "user", "anchor": "br"})
        self.assertIn("Benutzer-Ursprung", panel.queue_list.item(0).text())
        self.send(panel, "b.gcode")
        panel.set_job_origin("absolute")
        self.assertTrue(panel.queue_job())
        self.assertTrue(wait_until(lambda: panel.queue_list.count() == 2))
        self.assertIn("2 wartend", panel.queue_label.text())
        # Skip/remove need a selection.
        self.assertFalse(panel.queue_skip_button.isEnabled())
        panel.queue_list.setCurrentRow(1)
        self.assertTrue(wait_until(panel.queue_skip_button.isEnabled))
        panel.queue_skip_button.click()
        self.assertTrue(wait_until(lambda: "übersprungen" in panel.queue_list.item(1).text()))
        self.assertTrue(wait_until(lambda: panel.queue_list.currentRow() == 1
                                   and not panel.queue_skip_button.isEnabled()))
        panel.queue_remove_button.click()
        self.assertTrue(wait_until(lambda: panel.queue_list.count() == 1))
        self.assertEqual(ops(self.pi)[-1], {"op": "queue_remove", "id": "2"})
        # Run: start/home/frame locked, abort and pause available.
        self.assertTrue(wait_until(panel.queue_run_button.isEnabled))
        self.assertTrue(panel.queue_run())
        self.assertTrue(wait_until(lambda: "läuft" in panel.queue_label.text()))
        self.assertTrue(wait_until(panel.abort_button.isEnabled))
        self.assertFalse(panel.start_button.isEnabled())
        self.assertFalse(panel.home_button.isEnabled())
        self.assertFalse(panel.queue_run_button.isEnabled())
        self.assertIn("Warteschlange", panel.active_operation())
        self.assertTrue(wait_until(panel.queue_pause_button.isEnabled))
        panel.queue_pause_button.click()
        self.assertTrue(wait_until(lambda: "hält nach" in panel.queue_label.text()))
        self.pi.finish_queue("stopped", "error", "G-Code Zeile 3: kaputt")
        self.assertTrue(wait_until(lambda: "kaputt" in panel.queue_label.text()))
        self.assertTrue(wait_until(panel.home_button.isEnabled))
        self.assertTrue(wait_until(panel.queue_clear_button.isEnabled))
        panel.queue_clear_button.click()
        self.assertTrue(wait_until(lambda: panel.queue_list.count() == 0))

    def test_older_pi_disables_queue_with_hint(self):
        panel = self.panel()
        self.send(panel, "a.gcode")
        self.pi.make_pre_queue_pi()
        self.assertTrue(wait_until(lambda: "Pi aktualisieren" in panel.queue_label.text()))
        self.assertFalse(panel.queue_add_button.isEnabled())
        self.assertFalse(panel.queue_run_button.isEnabled())
        self.assertFalse(panel.queue_job())
        self.assertIn("keine Warteschlange", panel.error_label.text())
        self.assertFalse(any(f["op"].startswith("queue") for f in ops(self.pi)))
        self.assertTrue(panel.start_button.isEnabled())    # single jobs still work


if __name__ == "__main__":
    unittest.main()
