"""Zero point top right (docs/ANFORDERUNGEN_VEREINFACHUNG_2026-10-26.md §2.1).

Machine X0/Y0 is the endstop corner, top right seen from the front; X grows
to the left, Y towards the door. The jog cross, anchor names and the Pi
placement anchors follow that view. An older Pi (no ``coord_convention``)
mapped "l" to small X, so Studio swaps left/right for it.
"""
import os
import tempfile
import time
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import _paths  # noqa: F401
from fake_pi import FakePi
from machine.client import COORD_CONVENTION, LumaCutClient, wire_anchor

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


class WireAnchorTests(unittest.TestCase):
    def test_new_pi_keeps_visible_names(self):
        for a in ("tl", "tr", "bl", "br", "center"):
            self.assertEqual(wire_anchor(a, COORD_CONVENTION), a)

    def test_older_pi_swaps_left_right(self):
        self.assertEqual([wire_anchor(a, None) for a in ("tl", "tr", "bl", "br", "center")],
                         ["tr", "tl", "br", "bl", "center"])
        for a in ("tl", "tr", "bl", "br", "center"):
            self.assertEqual(wire_anchor(wire_anchor(a, None), None), a)

    def test_status_reports_convention(self):
        with FakePi() as pi:
            client = LumaCutClient(pi.url)
            self.assertEqual(client.status().coord_convention, COORD_CONVENTION)
            pi.status.pop("coord_convention")
            self.assertIsNone(client.status().coord_convention)


@unittest.skipIf(QApplication is None, "PySide6 not installed")
class PanelOrientationTests(unittest.TestCase):
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

    def test_jog_cross_matches_front_view(self):
        panel = self.panel()
        grid = panel.jog_buttons[0].parentWidget().layout()
        where = {}
        for b in panel.jog_buttons:
            for i in range(grid.count()):
                item = grid.itemAt(i)
                if item.layout() is not None:
                    lay = item.layout()
                    idx = lay.indexOf(b)
                    if idx >= 0:
                        r, c, _, _ = lay.getItemPosition(idx)
                        where[(b.property("axis"), b.property("direction"))] = (r, c, b.text())
        self.assertEqual(where[("X", 1)][:2], (1, 0))    # X+ = left
        self.assertEqual(where[("X", -1)][:2], (1, 2))   # X- = right
        self.assertEqual(where[("Y", -1)][:2], (0, 1))   # Y- = up (switch side)
        self.assertEqual(where[("Y", 1)][:2], (2, 1))    # Y+ = down (door)
        self.assertIn("←", where[("X", 1)][2])
        self.assertIn("↓", where[("Y", 1)][2])
        self.assertIn("oben rechts", panel.pos_label.toolTip())

    def test_default_anchor_is_switch_corner_and_old_pi_gets_swapped_name(self):
        panel = self.panel()
        self.assertEqual(panel.anchor_combo.currentData(), "tr")
        panel.set_job_origin("current", "tl")
        self.assertEqual(panel.job_origin(), ("current", "tl"))
        self.pi.status.pop("coord_convention")
        self.assertTrue(wait_until(lambda: panel._status.coord_convention is None))
        self.assertEqual(panel.job_origin(), ("current", "tr"))
        self.assertEqual(panel._anchor_label("tr"), "Oben links")
