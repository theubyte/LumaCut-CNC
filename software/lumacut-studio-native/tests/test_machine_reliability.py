"""Reliability of E-Stop and status polling against the fake Pi."""
import os
import socket
import tempfile
import time
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import _paths  # noqa: F401  (puts src/ on sys.path)
from fake_pi import FakePi

from machine.client import (ApiError, ConnectionFailed, LumaCutClient,
                            MachineStatus, ProtocolError, StatusTimeout)

try:
    from PySide6.QtCore import QSettings
    from PySide6.QtWidgets import QApplication
except ImportError:  # pragma: no cover
    QApplication = None


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def refused(*_args, **_kwargs):
    """Deterministic network failure, identical on every platform (a real
    closed port is refused at once on Linux but only after ~2 s of SYN
    retries on Windows)."""
    raise ConnectionFailed("Pi nicht erreichbar (test): Verbindung abgelehnt")


class EmergencyStopClientTests(unittest.TestCase):
    def setUp(self):
        self.pi = FakePi().__enter__()
        self.client = LumaCutClient(self.pi.url)

    def tearDown(self):
        self.pi.__exit__(None, None, None)

    def estop_requests(self):
        return [r for r in self.pi.requests
                if r.get("form", {}).get("op") == "estop" or
                (r["path"] == "/api/action" and b"op=estop" in r["body"])]

    def test_retries_after_dropped_connections(self):
        self.pi.drop["estop"] = 2
        message = self.client.emergency_stop()
        self.assertIn("ok estop", message)
        self.assertIn("Versuch 3", message)
        self.assertEqual(len(self.estop_requests()), 3)

    def test_pi_answer_is_final_and_not_retried(self):
        self.pi.fail["estop"] = (503, {"error": "Software-Notstopp NICHT übertragen: "
                                               "USB getrennt, physischen Not-Aus benutzen"})
        with self.assertRaises(ApiError) as ctx:
            self.client.emergency_stop()
        self.assertIn("USB getrennt", str(ctx.exception))
        self.assertEqual(len(self.estop_requests()), 1)

    def test_short_timeout_per_attempt(self):
        self.pi.delay["estop"] = 10.0
        started = time.monotonic()
        with self.assertRaises(ConnectionFailed) as ctx:
            self.client.emergency_stop(retries=1, timeout=0.5)
        # 2 × 0.5 s + pause; far below the 10 s the Pi would need
        self.assertLess(time.monotonic() - started, 6.0)
        self.assertIn("physischen Not-Aus", str(ctx.exception))
        self.assertIn("2 Versuchen", str(ctx.exception))

    def test_unreachable_pi_gives_clear_failure(self):
        client = LumaCutClient("http://127.0.0.1:%d" % free_port())
        with self.assertRaises(ConnectionFailed) as ctx:
            client.emergency_stop()
        # 3 attempts on Linux; Windows may only fit 2 into the deadline
        self.assertRegex(str(ctx.exception),
                         r"NOT-AUS nicht bestätigt nach [23] Versuchen – physischen Not-Aus")

    def test_retries_stop_at_the_deadline(self):
        calls = []

        def slow_refusal(op, timeout=None, **_):
            calls.append(timeout)
            time.sleep(0.4)
            refused()
        with mock.patch.object(self.client, "action", side_effect=slow_refusal):
            with self.assertRaises(ConnectionFailed) as ctx:
                self.client.emergency_stop(retries=5, timeout=3.0, deadline=1.0)
        # 0.4 + 0.2 + 0.4 = 1.0 s → no third attempt may start
        self.assertEqual(len(calls), 2, calls)
        self.assertEqual(calls[0], 3.0)
        self.assertLessEqual(calls[1], 3.0)
        self.assertGreaterEqual(calls[1], 0.5)
        self.assertIn("nach 2 Versuchen", str(ctx.exception))

    def test_all_attempts_refused_deterministically(self):
        with mock.patch.object(self.client, "action", side_effect=refused) as action:
            with self.assertRaises(ConnectionFailed) as ctx:
                self.client.emergency_stop()
        self.assertEqual(action.call_count, 3)
        self.assertIn("nach 3 Versuchen – physischen Not-Aus benutzen!", str(ctx.exception))
        self.assertIn("Verbindung abgelehnt", str(ctx.exception))

    def test_system_proxy_is_ignored(self):
        env = {"http_proxy": "http://127.0.0.1:%d" % free_port(),
               "HTTP_PROXY": "http://127.0.0.1:%d" % free_port(),
               "no_proxy": "", "NO_PROXY": ""}
        with mock.patch.dict(os.environ, env):
            client = LumaCutClient(self.pi.url)
            self.assertIn("ok estop", client.emergency_stop())

    def test_park_on_new_and_old_pi(self):
        self.assertEqual(self.client.park(), "ok park")
        self.pi.actions.discard("park")      # Pi service before op=park
        with self.assertRaises(ApiError) as ctx:
            self.client.park()
        self.assertIn("op=park fehlt", str(ctx.exception))


class StatusParsingTests(unittest.TestCase):
    def setUp(self):
        self.pi = FakePi().__enter__()
        self.client = LumaCutClient(self.pi.url)

    def tearDown(self):
        self.pi.__exit__(None, None, None)

    def test_timeout_is_reported_as_status_timeout(self):
        self.pi.delay["status"] = 1.0
        with self.assertRaises(StatusTimeout):
            self.client.status(timeout=0.2)

    def test_malformed_json_and_wrong_shape(self):
        for raw in (b"{not json", b"", b"[1, 2, 3]", b'"marlin"', b"\xff\xfe"):
            self.pi.raw_status = raw
            with self.assertRaises(ProtocolError, msg=raw):
                self.client.status()

    def test_status_without_any_known_field_is_rejected(self):
        self.pi.raw_status = b'{"hello": "world"}'
        with self.assertRaises(ProtocolError):
            self.client.status()

    def test_partial_status_uses_safe_defaults(self):
        self.pi.raw_status = b'{"connected": true, "homed": true}'
        status = self.client.status()
        self.assertTrue(status.homed)
        self.assertIsNone(status.position)
        self.assertIsNone(status.laser_armed)        # unknown, not "off"
        self.assertEqual(status.owner, "Frei")
        self.assertEqual(status.job.state, "idle")

    def test_mistyped_fields(self):
        status = MachineStatus.from_json({
            "firmware": "marlin", "homed": "false", "connected": 1,
            "position": ["a", 2, 3], "owner": 7, "laser_armed": "true",
            "job": ["x"], "workpiece_surface_z": float("nan"),
            "emergency_latched": None})
        self.assertFalse(status.homed)
        self.assertTrue(status.skr_connected)
        self.assertIsNone(status.position)
        self.assertEqual(status.owner, "Frei")
        self.assertTrue(status.laser_armed)
        self.assertEqual(status.job.state, "idle")
        self.assertIsNone(status.workpiece_surface_z)
        self.assertFalse(status.emergency_latched)
        with self.assertRaises(ProtocolError):
            MachineStatus.from_json({"firmware": "grbl", "homed": True})


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


@unittest.skipIf(QApplication is None, "PySide6 not installed")
class PollerReliabilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.pi = FakePi().__enter__()
        self.states = []
        self.statuses = []

    def tearDown(self):
        self.pi.__exit__(None, None, None)

    def poller(self, interval=250, timeout=0.3, url=None):
        from machine.worker import StatusPoller
        p = StatusPoller(LumaCutClient(url or self.pi.url), interval,
                         status_timeout_s=timeout)
        p.state_changed.connect(lambda s, m: self.states.append(s))
        p.status_received.connect(self.statuses.append)
        self.addCleanup(p.stop)
        p.start()
        return p

    def test_timeouts_during_a_command_keep_connected(self):
        from machine.worker import ConnState
        p = self.poller()
        self.assertTrue(wait_until(lambda: self.statuses))
        p.set_command_running(True)
        self.pi.delay["status"] = 0.6           # Pi holds machine.lock (Home)
        before = len(self.pi.requests)
        self.assertTrue(wait_until(lambda: len(self.pi.requests) >= before + 3))
        self.assertNotIn(ConnState.ERROR, self.states)
        self.assertEqual(p.state, ConnState.CONNECTED)
        self.pi.delay.clear()
        count = len(self.statuses)
        self.assertTrue(wait_until(lambda: len(self.statuses) > count))

    def test_timeouts_without_command_become_error_after_grace(self):
        from machine.worker import ConnState
        p = self.poller()
        p.TIMEOUT_GRACE_S = 0.5
        self.assertTrue(wait_until(lambda: self.statuses))
        self.pi.delay["status"] = 0.6
        self.assertTrue(wait_until(lambda: ConnState.ERROR in self.states))
        self.pi.delay.clear()
        self.assertTrue(wait_until(lambda: self.states[-1] == ConnState.CONNECTED))

    def test_malformed_answer_is_error_and_recovers(self):
        from machine.worker import ConnState
        self.pi.raw_status = b"<html>kein JSON</html>"
        self.poller()
        self.assertTrue(wait_until(lambda: ConnState.ERROR in self.states))
        self.assertEqual(self.statuses, [])
        self.pi.raw_status = None
        self.assertTrue(wait_until(lambda: self.states[-1] == ConnState.CONNECTED))
        self.assertTrue(wait_until(lambda: self.statuses))

    def test_single_failure_is_tolerated_then_error(self):
        from machine.worker import ConnState
        self.poller()
        self.assertTrue(wait_until(lambda: self.statuses))
        self.pi.fail["status"] = (500, {"error": "Interner Fehler"})
        self.assertTrue(wait_until(lambda: ConnState.ERROR in self.states))
        status_requests = [r for r in self.pi.requests if r["path"] == "/api/status"]
        self.assertGreaterEqual(len(status_requests), 3)   # ok + 2 failures

    def test_backoff_on_errors(self):
        self.pi.fail["status"] = (500, {"error": "kaputt"})
        self.poller(interval=250)
        time.sleep(1.6)
        polls = [r for r in self.pi.requests if r["path"] == "/api/status"]
        # healthy: ~7 polls in 1.6 s; with backoff 500/750/1000 ms: ≤ 4
        self.assertLessEqual(len(polls), 4)

    def test_stop_is_fast_and_silent_while_request_hangs(self):
        from machine.worker import ConnState
        p = self.poller(timeout=3.0)
        self.assertTrue(wait_until(lambda: self.statuses))
        self.pi.delay["status"] = 2.5
        self.assertTrue(wait_until(lambda: self.pi.status_waiting, 5))   # poll hangs
        started = time.monotonic()
        p.stop(wait_ms=200)
        self.assertLess(time.monotonic() - started, 1.5)  # not the 2.5 s hang
        self.assertEqual(self.states[-1], ConnState.DISCONNECTED)
        count = len(self.statuses)
        self.assertTrue(wait_until(lambda: not self.pi.status_waiting, 10))
        wait_until(lambda: False, timeout=0.3)    # hanging request completed
        wait_until(lambda: False, timeout=0.2)
        self.assertEqual(len(self.statuses), count)
        self.assertEqual(self.states[-1], ConnState.DISCONNECTED)


@unittest.skipIf(QApplication is None, "PySide6 not installed")
class PanelReliabilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        os.environ.pop("LUMACUT_KEY", None)
        self.tmp = tempfile.TemporaryDirectory()
        self.store = QSettings(os.path.join(self.tmp.name, "s.ini"), QSettings.IniFormat)
        self.pi = FakePi().__enter__()
        self.answer = True

    def tearDown(self):
        self.pi.__exit__(None, None, None)
        self.tmp.cleanup()

    def panel(self, url=None, connect=True):
        from machine import settings
        from machine.panel import MachinePanel
        settings.save(settings.ConnectionSettings(base_url=url or self.pi.url), self.store)
        panel = MachinePanel(store=self.store, confirm=lambda *_: self.answer)
        self.addCleanup(panel.shutdown)
        if connect:
            panel.connect_to_pi()
            self.assertTrue(wait_until(panel.home_button.isEnabled))
        return panel

    def test_estop_while_long_command_runs(self):
        panel = self.panel()
        self.pi.delay["home"] = 8.0
        panel.home()
        self.assertTrue(wait_until(lambda: panel._runner.busy))
        self.assertFalse(panel.home_button.isEnabled())
        self.assertTrue(panel.estop_button.isEnabled())
        started = time.monotonic()
        panel.emergency_stop()
        self.assertTrue(wait_until(lambda: "NOT-AUS bestätigt" in panel.estop_label.text(), 6))
        self.assertLess(time.monotonic() - started, 6.0)   # long before Home ends
        self.assertTrue(panel._runner.busy)          # Home still running
        self.assertIn("ok estop", panel.estop_label.text())

    def test_estop_failure_feedback_when_disconnected(self):
        # Deterministic: every attempt fails at once, on every platform.
        panel = self.panel(url="http://127.0.0.1:%d" % free_port(), connect=False)
        with mock.patch.object(LumaCutClient, "action", side_effect=refused) as action:
            panel.emergency_stop()
            self.assertTrue(wait_until(lambda: "NICHT bestätigt" in panel.estop_label.text()))
        self.assertEqual(action.call_count, 3)
        self.assertEqual(action.call_args.args[0], "estop")
        text = panel.estop_label.text()
        self.assertIn("nach 3 Versuchen", text)
        self.assertIn("physischen Not-Aus", text)
        self.assertTrue(panel.estop_button.isEnabled())
        self.assertIn("fehlgeschlagen", panel.error_label.text())

    def test_estop_feedback_against_closed_port(self):
        # Real socket, no timing assertion: Linux refuses at once, Windows
        # after SYN retries; the deadline bounds it to ~4 s everywhere.
        panel = self.panel(url="http://127.0.0.1:%d" % free_port(), connect=False)
        panel.emergency_stop()
        self.assertIn("warte auf Bestätigung", panel.estop_label.text())
        self.assertTrue(wait_until(lambda: "NICHT bestätigt" in panel.estop_label.text(), 30))
        self.assertIn("physischen Not-Aus", panel.estop_label.text())
        self.assertTrue(panel.estop_button.isEnabled())

    def test_stale_status_locks_controls_but_not_estop(self):
        from machine import panel as panel_module
        old = panel_module.STALE_AFTER_S
        panel_module.STALE_AFTER_S = 0.5
        self.addCleanup(setattr, panel_module, "STALE_AFTER_S", old)
        panel = self.panel()
        self.pi.delay["status"] = 1.5
        self.assertTrue(wait_until(lambda: panel.stale, 10))
        self.assertIn("Status", panel.conn_badge.text())
        self.assertFalse(panel.home_button.isEnabled())
        self.assertTrue(panel.estop_button.isEnabled())
        self.pi.delay.clear()
        self.assertTrue(wait_until(lambda: not panel.stale, 10))
        self.assertEqual(panel.conn_badge.text(), "Verbunden")
        self.assertTrue(wait_until(panel.home_button.isEnabled))

    def test_estop_reset_flow(self):
        self.pi.status["emergency_latched"] = True
        self.pi.status["homed"] = False
        self.pi.status["fault"] = "M112 ausgelöst: SKR stromlos schalten und prüfen"
        from machine import settings
        from machine.panel import MachinePanel
        settings.save(settings.ConnectionSettings(base_url=self.pi.url), self.store)
        panel = MachinePanel(store=self.store, confirm=lambda *_: self.answer)
        self.addCleanup(panel.shutdown)
        panel.connect_to_pi()
        self.assertTrue(wait_until(panel.reset_button.isEnabled))
        self.assertIn("NOTSTOPP", panel.skr_label.text())
        self.assertFalse(panel.home_button.isEnabled())
        self.answer = False
        panel.reset_emergency()
        self.assertFalse(any(b"op=estop_reset" in r["body"] for r in self.pi.requests))
        self.answer = True
        panel.reset_emergency()
        self.assertTrue(wait_until(lambda: "ok estop_reset" in panel.error_label.text()))
        self.pi.status["emergency_latched"] = False
        self.pi.status["fault"] = ""
        self.assertTrue(wait_until(panel.home_button.isEnabled))
        self.assertFalse(panel.reset_button.isEnabled())

    def test_shutdown_does_not_hang_on_long_command(self):
        panel = self.panel()
        self.pi.delay["home"] = 5.0
        panel.home()
        started = time.monotonic()
        panel.shutdown()
        self.assertLess(time.monotonic() - started, 2.0)


if __name__ == "__main__":
    unittest.main()
