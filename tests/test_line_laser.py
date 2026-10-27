"""pi400/marlin/line_laser.py: measuring line laser on a Pi GPIO (no hardware needed)."""
import types
import unittest

from pi400.marlin import line_laser


class LineLaserTests(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.fail = False

        def run(cmd, **k):
            self.calls.append(cmd)
            return types.SimpleNamespace(returncode=1 if self.fail else 0, stderr="kein Zugriff" if self.fail else "")
        self.laser = line_laser.LineLaser(run=run)

    def test_off_until_configured_and_starts_off(self):
        with self.assertRaisesRegex(RuntimeError, "nicht eingerichtet"):
            self.laser.set(True)
        self.laser.configure(17)
        self.assertEqual(self.calls, [["pinctrl", "set", "17", "op", "dl"]])
        self.assertEqual(self.laser.status(), {"gpio": 17, "on": False})

    def test_on_off_and_auto_off(self):
        self.laser.configure(17)
        line_laser.AUTO_OFF_S, saved = 0.05, line_laser.AUTO_OFF_S
        try:
            self.laser.set(True)
            self.assertEqual(self.calls[-1], ["pinctrl", "set", "17", "op", "dh"])
            self.assertTrue(self.laser.on)
            import time
            time.sleep(0.3)
            self.assertFalse(self.laser.on, "switched itself off")
            self.assertEqual(self.calls[-1][-1], "dl")
        finally:
            line_laser.AUTO_OFF_S = saved

    def test_moving_to_another_pin_switches_the_old_one_off(self):
        self.laser.configure(17)
        self.laser.set(True)
        self.laser.configure(27)
        self.assertIn(["pinctrl", "set", "17", "op", "dl"], self.calls)
        self.assertEqual(self.calls[-1], ["pinctrl", "set", "27", "op", "dl"])
        self.laser.configure(None)
        self.assertEqual(self.laser.status(), {"gpio": None, "on": False})
        for bad in (0, 1, 28, True):
            with self.assertRaises(ValueError):
                self.laser.configure(bad)

    def test_pin_error_is_reported(self):
        self.laser.configure(17)
        self.fail = True
        with self.assertRaisesRegex(RuntimeError, "kein Zugriff"):
            self.laser.set(True)


if __name__ == "__main__":
    unittest.main()
