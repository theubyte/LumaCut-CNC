"""Probe reach of op=autorun, checked against Claude's real Pi code.

Reproduces "Kein Abtastpunkt erreichbar" (pi400/marlin/heightmap.py
_mark_reachable) with the real plan_probe and MarlinTransport.probe_reachable
(no serial port is opened). Read-only: nothing on the Pi side is changed.

Machine mm: X0/Y0 = endstop corner, top right seen from the door; cutting
area X30-390 / Y30-370; head during G30 X10-380 / Y10-360
(transport.PROBE_HEAD_MIN/MAX, Marlin PROBING_MARGIN, Pi b966c89); probe offset
(tip minus laser) X-23 / Y+15 -> probe-able laser points X30-357 / Y30-370.
Grid points outside are probed up to 40 mm next to them (substitute), so
since b966c89 every case below is accepted.

Run ``python tests/test_machine_probe_reach.py`` for the table.
"""
import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import _paths  # noqa: F401

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "pi400"))
from marlin import heightmap  # noqa: E402
from marlin.transport import PROBE_HEAD_MAX, PROBE_HEAD_MIN, MarlinTransport  # noqa: E402

from machine import client as mc  # noqa: E402

OFFSET = (-23.0, 15.0)
BOUNDS = heightmap.Box(30.0, 30.0, 390.0, 370.0)    # web.py auto_plan bounds

# name, (xmin, ymin, xmax, ymax) of the lasered rectangle, expected
CASES = [
    ("Nullpunkt-Ecke (30,30), 20x10", (30, 30, 50, 40), True),
    ("Nullpunkt-Ecke (30,30), 50x50", (30, 30, 80, 80), True),
    ("Streifen oben, 40x12 bei Y30", (100, 30, 140, 42), True),
    ("Oben, 20x17 bei Y30 (Unterkante Y47)", (100, 30, 120, 47), True),
    ("Oben, 20x20 bei Y30 (Unterkante Y50)", (100, 30, 120, 50), True),
    ("Klein 10x10 bei Y38-48, Mitte Y43", (200, 38, 210, 48), True),
    ("Klein 10x10 bei Y42-52, Mitte Y47", (200, 42, 210, 52), True),
    ("Linker Rand, 30x30 bei X360", (360, 200, 390, 230), True),
    ("Links, 14 breit X352-366 (Mitte X359)", (352, 200, 366, 210), True),
    ("Links, 30x30 bei X350", (350, 200, 380, 230), True),
    ("Gegenecke Schalter-fern (390,370), 30x30", (360, 340, 390, 370), True),
    ("Gegenecke, 60x60 bis (390,370)", (330, 310, 390, 370), True),
    ("Ecke unten rechts (30,370), 20x20", (30, 350, 50, 370), True),
    ("Mitte 100x80", (150, 150, 250, 230), True),
    ("Ganze Fläche 360x340", (30, 30, 390, 370), True),
]


def machine():
    t = MarlinTransport("/dev/null")       # constructor only, no port opened
    t.probe_xy_offset_mm = OFFSET
    return t


def rect_gcode(xmin, ymin, xmax, ymax):
    return ["G90", "G0 X%g Y%g" % (xmin, ymin), "M3 S0",
            "G1 X%g Y%g S500 F1200" % (xmax, ymin), "G1 X%g Y%g" % (xmax, ymax),
            "G1 X%g Y%g" % (xmin, ymax), "G1 X%g Y%g" % (xmin, ymin), "M5"]


def plan(box, t=None):
    t = t or machine()
    try:
        grids = heightmap.plan_probe(rect_gcode(*box), BOUNDS, t.probe_reachable)
    except ValueError as exc:
        return None, str(exc)
    pts = [g.point(i) for g in grids for i in range(len(g.z))]
    ok = [p for g in grids for i, p in enumerate(map(g.point, range(len(g.z))))
          if g.reachable[i]]
    return (pts, ok), ""


class ProbeReachTests(unittest.TestCase):
    def test_limits_from_pi_code(self):
        t = machine()
        self.assertEqual(PROBE_HEAD_MAX, mc.PROBE_HEAD_MAX)
        self.assertEqual(PROBE_HEAD_MIN, mc.PROBE_HEAD_MIN)
        self.assertTrue(t.probe_reachable(30.0, 25.0))
        self.assertFalse(t.probe_reachable(30.0, 24.99))
        self.assertTrue(t.probe_reachable(357.0, 370.0))
        self.assertFalse(t.probe_reachable(357.01, 200.0))
        # head = laser point - offset: (100, 50) -> head (123, 35)
        self.assertTrue(t._probe_head_ok(123.0, 35.0))
        self.assertEqual(mc.probe_reach(OFFSET), (30.0, 357.0, 30.0, 370.0))

    def test_cases(self):
        for name, box, expected in CASES:
            with self.subTest(name):
                result, error = plan(box)
                self.assertEqual(result is not None, expected, (name, error))
                if not expected:
                    self.assertIn("Kein Abtastpunkt erreichbar", error)

    def test_edge_point_probed_next_to_it(self):
        """Formerly refused (only the grid point counted); since b966c89 the Pi
        probes the nearest reachable spot within 40 mm instead."""
        box = (352, 200, 366, 210)                  # grid point X359 > 357
        self.assertFalse(machine().probe_reachable(359.0, 205.0))
        grids = heightmap.plan_probe(rect_gcode(*box), BOUNDS, machine().probe_reachable)
        self.assertEqual([g.probe_point(0) for g in grids], [(357.0, 205.0)])

    def test_studio_explains_refusal(self):
        msg = ("Kein Abtastpunkt erreichbar: der Taster kommt an keine Stelle des "
               "Motivs – Motiv weiter in die Mitte schieben, dann neu starten.")
        text = mc.explain_probe_error(msg, OFFSET)
        self.assertTrue(text.startswith(msg))
        self.assertIn("X30–357 / Y30–370", text)
        self.assertNotIn("obersten", text)
        self.assertIn("linken 33 mm", text)
        self.assertIn("X-23 / Y+15", text)
        self.assertEqual(mc.explain_probe_error("Abgebrochen", OFFSET), "Abgebrochen")
        other = mc.explain_probe_error(msg, (10.0, -5.0))
        self.assertIn("X30–390 / Y30–355", other)
        self.assertNotIn("rechten", other)
        self.assertIn("untersten 15 mm", other)


class StudioShowsReachTests(unittest.TestCase):
    """The client adds the reach to the Pi's 400 for autorun and queue_run."""

    def setUp(self):
        from fake_pi import FakePi
        self.pi = FakePi().__enter__()
        self.addCleanup(self.pi.__exit__, None, None, None)
        with self.pi.lock:
            self.pi.status["probe_xy_offset_mm"] = [-23.0, 15.0]
        refusal = {"error": "Kein Abtastpunkt erreichbar: der Taster kommt an keine "
                            "Stelle des Motivs – Motiv weiter in die Mitte schieben, "
                            "dann neu starten."}
        self.pi.fail["autorun"] = (400, refusal)
        self.pi.fail["queue_run"] = (400, {"error": "Warteschlange #1 (a.gcode): "
                                                    + refusal["error"]})

    def test_autorun_and_queue(self):
        client = mc.LumaCutClient(self.pi.url)
        self.assertEqual(client.status().probe_offset, (-23.0, 15.0))
        for call in (lambda: client.autorun_job("a.gcode"), client.queue_run):
            with self.assertRaises(mc.ApiError) as ctx:
                call()
            self.assertIn("Kein Abtastpunkt erreichbar", str(ctx.exception))
            self.assertIn("X30–357 / Y30–370", str(ctx.exception))


class ProbeWarningShownTests(unittest.TestCase):
    """job.warnings (Pi 7, clamped probe point) is shown, start stays free."""

    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app = QApplication.instance() or QApplication([])

    def test_parse(self):
        job = mc.JobState.from_json({"state": "running", "warnings": [
            {"code": "probe_clamped", "text": "Taster bei X40 Y45 statt Y35 (10 mm)"},
            "zweite", 3, {"text": ""}]})
        self.assertEqual(job.warnings, ("Taster bei X40 Y45 statt Y35 (10 mm)", "zweite"))
        self.assertEqual(mc.JobState.from_json({"state": "idle"}).warnings, ())

    def test_panel_shows_warning_and_start_stays_enabled(self):
        import tempfile
        from PySide6.QtCore import QSettings
        from fake_pi import FakePi
        from machine import settings
        from machine.panel import MachinePanel
        from test_machine_qt import wait_until
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        store = QSettings(os.path.join(tmp.name, "s.ini"), QSettings.IniFormat)
        pi = FakePi().__enter__()
        self.addCleanup(pi.__exit__, None, None, None)
        settings.save(settings.ConnectionSettings(base_url=pi.url), store)
        panel = MachinePanel(store=store, confirm=lambda *_: True)
        self.addCleanup(panel.shutdown)
        panel.connect_to_pi()
        self.assertTrue(wait_until(panel.home_button.isEnabled))
        panel.send_gcode("a.gcode", "G0 X40 Y40\nM5 I\n")
        self.assertTrue(wait_until(panel.start_button.isEnabled))
        warning = "Taster bei X40 Y45 statt X40 Y35 getastet (10 mm daneben)"
        with pi.lock:
            pi.status["job"].update(state="complete", file="a.gcode",
                                    warnings=[{"code": "probe_clamped", "text": warning}])
        self.assertTrue(wait_until(lambda: warning in panel.job_label.text()))
        self.assertTrue(panel.start_button.isEnabled())


if __name__ == "__main__" and "--table" not in sys.argv and len(sys.argv) > 1:
    unittest.main()
elif __name__ == "__main__":
    t = machine()
    print("Probe-able laser points: X%.0f-%.0f / Y%.0f-%.0f" % mc.probe_reach(OFFSET))
    for name, box, _ in CASES:
        result, error = plan(box, t)
        if result is None:
            print("%-44s %-22s ABGELEHNT" % (name, box))
        else:
            pts, ok = result
            print("%-44s %-22s %d/%d Punkte erreichbar: %s" % (
                name, box, len(ok), len(pts),
                " ".join("(%.0f,%.0f)" % p for p in ok[:4])))
