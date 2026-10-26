"""Job origin options (#16): client, panel and Studio output on the Pi.

A job runs absolute (as drawn) unless the operator picks "Aktuelle
Position" or "Benutzer-Ursprung". Then the Pi places the job (op=place),
checks travel, the 30 mm safe zone and the laser guard on the moved lines,
and start/frame use that same placement. An older Pi never receives origin
fields: it would ignore them and run the job absolute.
"""
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import _paths  # noqa: F401
from fake_pi import FakePi
from machine.client import ApiError, LumaCutClient, MachineStatus, OriginState

try:
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication
except ImportError:  # pragma: no cover
    QApplication = None

ROOT = Path(__file__).resolve().parents[3]


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


class OriginClientTests(unittest.TestCase):
    def setUp(self):
        self.pi = FakePi().__enter__()
        self.addCleanup(self.pi.__exit__, None, None, None)
        self.client = LumaCutClient(self.pi.url)

    def test_status_parses_origin_and_older_pi(self):
        status = self.client.status()
        self.assertTrue(status.origin.supported)
        self.assertIsNone(status.origin.user)
        self.pi.make_older_pi()
        old = self.client.status()
        self.assertFalse(old.origin.supported)
        self.assertEqual(MachineStatus.from_json({"homed": True, "origin": "x"}).origin,
                         OriginState())
        o = OriginState.from_json({"modes": ["absolute", "current", "user"],
                                   "user": [40, "kaputt"],
                                   "placement": {"file": "a.gcode", "origin": "user",
                                                 "anchor": "tl"}})
        self.assertIsNone(o.user)
        self.assertTrue(o.placed("a.gcode", "user", "tl"))
        self.assertFalse(o.placed("a.gcode", "user", "br"))

    def test_place_start_and_frame_fields(self):
        self.client.set_user_origin(55.5, 66.25)
        self.assertEqual(self.client.status().origin.user, (55.5, 66.25))
        self.client.place_job("a.gcode", "user", "center")
        self.client.start_job("a.gcode", placement=True)
        self.client.autorun_job("a.gcode", placement=True)
        self.client.frame("G0 X40 Y40 S0\n", "box", placement=True, name="a.gcode")
        self.client.start_job("a.gcode")
        forms = ops(self.pi)
        self.assertEqual(forms[0], {"op": "origin_set", "x": "55.500", "y": "66.250"})
        self.assertEqual(forms[1], {"op": "place", "name": "a.gcode", "origin": "user",
                                    "anchor": "center"})
        self.assertEqual(forms[2], {"op": "start", "name": "a.gcode", "placement": "1"})
        self.assertEqual(forms[3], {"op": "autorun", "name": "a.gcode", "placement": "1"})
        self.assertEqual(forms[4]["placement"], "1")
        self.assertEqual(forms[4]["name"], "a.gcode")
        self.assertEqual(forms[5], {"op": "start", "name": "a.gcode"})   # absolute: unchanged
        with self.assertRaises(ValueError):
            self.client.place_job("a.gcode", "irgendwo")
        with self.assertRaises(ValueError):
            self.client.place_job("a.gcode", "user", "mitte")
        with self.assertRaises(ValueError):
            self.client.set_user_origin(10, None)

    def test_older_pi_explains_update(self):
        self.pi.make_older_pi()
        for call in (lambda: self.client.place_job("a.gcode", "current"),
                     lambda: self.client.set_user_origin(),
                     self.client.clear_user_origin):
            with self.assertRaises(ApiError) as ctx:
                call()
            self.assertIn("Pi aktualisieren", str(ctx.exception))


@unittest.skipIf(QApplication is None, "PySide6 not installed")
class OriginPanelTests(unittest.TestCase):
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
        panel.set_frame_provider(lambda mode: "G0 X40 Y40 S0\nG0 X80 Y40 S0\n")
        panel.connect_to_pi()
        self.assertTrue(wait_until(panel.home_button.isEnabled))
        panel.send_gcode("canvas.gcode", "G0 X40 Y40\nM5 I\n")
        self.assertTrue(wait_until(panel.start_button.isEnabled))
        return panel

    def test_absolute_default_sends_no_origin_fields(self):
        panel = self.panel()
        self.assertEqual(panel.job_origin(), ("absolute", "tr"))
        self.assertFalse(panel.anchor_combo.isEnabled())
        panel.start_job()
        self.assertTrue(wait_until(lambda: "ok start" in panel.error_label.text()))
        self.assertEqual(ops(self.pi)[-1], {"op": "start", "name": "canvas.gcode"})
        self.assertFalse(any(f["op"] == "place" for f in ops(self.pi)))

    def test_user_origin_from_head_and_placed_start_and_frame(self):
        panel = self.panel()
        self.assertTrue(panel.origin_set_button.isEnabled())
        self.assertTrue(panel.set_user_origin())
        self.assertTrue(wait_until(lambda: "ok origin_set" in panel.error_label.text()))
        self.assertTrue(wait_until(lambda: "X120.5 Y80.2" in panel.origin_label.text()
                                   or "X120.5 Y80.3" in panel.origin_label.text()))
        panel.set_job_origin("user", "center")
        self.assertTrue(panel.anchor_combo.isEnabled())
        self.assertTrue(panel.frame())
        self.assertTrue(wait_until(lambda: "Rahmenfahrt gestartet" in panel.error_label.text()))
        frame_form = ops(self.pi)[-1]
        self.assertEqual((frame_form["op"], frame_form["placement"], frame_form["name"]),
                         ("frame", "1", "canvas.gcode"))
        self.assertEqual(ops(self.pi)[-2], {"op": "place", "name": "canvas.gcode",
                                            "origin": "user", "anchor": "center"})
        self.pi.finish_frame("complete")
        self.assertTrue(wait_until(lambda: "platziert: canvas.gcode" in panel.origin_label.text()))
        before = len([f for f in ops(self.pi) if f["op"] == "place"])
        panel.start_job()
        self.assertTrue(wait_until(lambda: "ok start" in panel.error_label.text()))
        # Same placement as the frame: no second op=place (head moved meanwhile).
        self.assertEqual(len([f for f in ops(self.pi) if f["op"] == "place"]), before)
        self.assertEqual(ops(self.pi)[-1], {"op": "start", "name": "canvas.gcode",
                                            "placement": "1"})

    def test_lost_placement_is_placed_again(self):
        panel = self.panel()
        panel.set_job_origin("current", "tl")
        self.pi.fail["start"] = (409, {"error": "Keine gültige Platzierung für canvas.gcode "
                                                "– neu platzieren (op=place)"})

        def clear_fail_after_first_place():
            places = [f for f in ops(self.pi) if f["op"] == "place"]
            if len(places) >= 1 and any(f["op"] == "start" for f in ops(self.pi)):
                self.pi.fail.pop("start", None)
            return len(places) >= 2
        panel.start_job()
        wait_until(clear_fail_after_first_place, 5)
        # Either it retried successfully or it reports the Pi's reason; never absolute.
        self.assertFalse(any(f == {"op": "start", "name": "canvas.gcode"} for f in ops(self.pi)))

    def test_older_pi_locks_origin_and_never_sends_fields(self):
        panel = self.panel()
        panel.set_job_origin("user", "br")
        self.pi.make_older_pi()
        self.assertTrue(wait_until(lambda: not panel.origin_combo.isEnabled()))
        self.assertIn("Pi aktualisieren", panel.origin_label.text())
        self.assertFalse(panel.origin_set_button.isEnabled())
        self.assertEqual(panel.job_origin(), ("absolute", "tr"))
        self.assertFalse(panel.set_user_origin(100, 100))
        self.assertIn("Pi aktualisieren", panel.error_label.text())
        panel.start_job()   # falls back to the absolute start the old Pi knows
        self.assertTrue(wait_until(lambda: "ok start" in panel.error_label.text()))
        self.assertEqual(ops(self.pi)[-1], {"op": "start", "name": "canvas.gcode"})

    def test_origin_button_needs_homed(self):
        panel = self.panel()
        self.pi.status["homed"] = False
        self.assertTrue(wait_until(lambda: not panel.origin_set_button.isEnabled()))


class StudioOutputPlacedOnPiTests(unittest.TestCase):
    """Real Studio G-code (vector + raster) placed by the real Pi code."""

    def test_canvas_job_placed_on_user_origin_passes_pi_checks(self):
        if QApplication is None:
            self.skipTest("PySide6 not installed")
        try:
            import flask  # noqa: F401
        except ImportError:  # pragma: no cover
            self.skipTest("flask not installed (pi400 web.py needs it)")
        QApplication.instance() or QApplication([])
        from PySide6.QtGui import QColor, QImage
        from lumacut_canvas import Document, Geometry, Shape
        from lumacut_canvas.model import ImageSettings, RasterImage
        from lumacut_import.image import grayscale_png
        from lumacut_job.planner import optimized_document_gcode
        doc = Document()
        doc.add_shape(Shape("rect", Geometry(20, 20, 60, 30), doc.active_layer_id))
        doc.add_shape(Shape("ellipse", Geometry(100, 40, 30, 30), doc.active_layer_id))
        img = QImage(30, 12, QImage.Format_RGB32)
        img.fill(QColor(60, 60, 60))
        png, pw, ph = grayscale_png(img)
        doc.add_shape(Shape("image", Geometry(40, 80, 30, 12), doc.active_layer_id,
                            image=RasterImage(png, pw, ph, ImageSettings())))
        gcode = optimized_document_gcode(doc)
        script = (
            "import sys\n"
            "from marlin import web, placement\n"
            "from marlin.transport import MarlinLaserGuard\n"
            "web.machine.homed = True\n"
            "web.machine.homing_verified = True\n"
            "web.config['user_origin'] = [200.0, 150.0]\n"
            "text = sys.stdin.read()\n"
            "for anchor in placement.ANCHORS:\n"
            "    result, lines = web.make_placement('c.gcode', text, 'user', anchor)\n"
            "    guard = MarlinLaserGuard()\n"
            "    for line in lines:\n"
            "        guard.check(line, True)\n"
            "    ax, ay = placement.anchor_point(placement.scan(lines)[1], anchor)\n"
            "    assert abs(ax - 200) < 1e-6 and abs(ay - 150) < 1e-6, (anchor, ax, ay)\n"
            "    print(anchor, result['dx'], result['dy'])\n"
            "web.config['user_origin'] = [380.0, 360.0]\n"
            "try:\n"
            "    web.make_placement('c.gcode', text, 'user', 'tl')\n"
            "except ValueError as exc:\n"
            "    print('refused', exc)\n")
        with tempfile.TemporaryDirectory() as tmp:
            env = dict(os.environ, LUMACUT_DATA=tmp, PYTHONPATH=str(ROOT / "pi400"))
            run = subprocess.run([sys.executable, "-c", script], input=gcode, env=env,
                                 text=True, capture_output=True, timeout=60)
        self.assertEqual(run.returncode, 0, run.stderr)
        for anchor in ("tl", "tr", "bl", "br", "center"):
            self.assertIn(anchor + " ", run.stdout)
        self.assertIn("refused", run.stdout)


if __name__ == "__main__":
    unittest.main()
