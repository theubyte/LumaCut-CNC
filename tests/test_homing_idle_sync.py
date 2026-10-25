"""Protect Pi-400 against stale <Home> status after the $H acknowledgement.

Simulated serial/status tests only; no motors or laser output is commanded.
"""
import os
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pi400"))
from lumacut.core import Controller


class HomingIdleTransportTests(unittest.TestCase):
    def controller(self):
        c = Controller("/dev/null")
        c.serial = object()  # no real serial device
        c.bootstrap_ready = True
        c.homed = True
        return c

    def test_stale_idle_before_ack_does_not_count(self):
        c = self.controller()
        c.state = "Idle"
        c.last_status = time.monotonic() - 1
        with self.assertRaisesRegex(TimeoutError, "statt Idle"):
            c.wait_for_idle_after_homing(timeout=0.03)

    def test_transient_home_waits_for_fresh_idle_report(self):
        c = self.controller()
        c.state = "Home"
        completed = threading.Event()

        def report():
            time.sleep(0.03)
            with c.cond:
                c._read_response("<Idle|MPos:-1,-1,-20|FS:0,0>")
            completed.set()

        thread = threading.Thread(target=report)
        thread.start()
        try:
            c.wait_for_idle_after_homing(timeout=0.5)
            self.assertTrue(completed.is_set())
            self.assertEqual(c.state, "Idle")
        finally:
            thread.join(timeout=1)

    def test_homing_alarm_fails_without_motion(self):
        c = self.controller()
        c.state = "Alarm"
        with self.assertRaisesRegex(RuntimeError, "Alarm"):
            c.wait_for_idle_after_homing(timeout=0.1)
        self.assertFalse(c.homed)

    def test_disconnect_during_homing_is_not_success(self):
        c = self.controller()
        c.serial = None
        with self.assertRaises(ConnectionError):
            c.wait_for_idle_after_homing(timeout=0.1)


class HomingPiIntegrationTests(unittest.TestCase):
    def test_post_home_z_waits_for_idle_and_no_extra_move_if_already_at_target(self):
        import tempfile
        os.environ.setdefault("LUMACUT_KEY", "unit-test-long-private-key")
        with tempfile.TemporaryDirectory() as root:
            os.environ.setdefault("LUMACUT_DATA", root)
            from lumacut import app as module
            previous = dict(module.config["focus"])
            was_homed = module.controller.homed
            events = []
            state = {
                "owner": "Frei", "state": "Idle",
                "connected": True, "bootstrap_ready": True, "homed": False,
                "position": [-1, -1, -20],
                "settings": {112: 1200, 132: 100},
            }

            def fake_send(commands, timeout=15):
                events.append("send " + commands[0])
                if commands[0] == "$H":
                    state["state"] = "Home"  # status poll has not refreshed yet
                    state["homed"] = True
                    module.controller.homed = True
                return "ok"

            def fake_wait(timeout=15):
                events.append("wait Idle")
                self.assertEqual(state["state"], "Home")
                state["state"] = "Idle"

            module.config["focus"] = {"lift": 20.0, "gap": 7.0,
                                      "tip": 0.0, "auto": True}
            module.controller.homed = False
            try:
                with patch.object(module.controller, "status", side_effect=lambda: state), \\
                     patch.object(module.controller, "wait_for_idle_after_homing",
                                  side_effect=fake_wait), \\
                     patch.object(module, "run_commands", side_effect=fake_send):
                    result = module.do_action("home")
                self.assertIn("Z bereits auf Sicherheitsabstand", result)
                self.assertEqual(events, ["send $H", "wait Idle"])
            finally:
                module.config["focus"] = previous
                module.controller.homed = was_homed

    def test_ui_blocks_local_controls_during_home_and_lightburn_host(self):
        page = (ROOT / "pi400" / "static" / "index.html").read_text(encoding="utf-8")
        self.assertIn("const LOCAL_OPS=new Set(", page)
        self.assertIn('s.owner&&s.owner!=="Frei"', page)
        self.assertIn('s.state==="Home"', page)
        self.assertIn("button.disabled=!available||owned||!validState", page)
        self.assertIn("transientHomeError&&s.state===\"Idle\"", page)


if __name__ == "__main__":
    unittest.main()
