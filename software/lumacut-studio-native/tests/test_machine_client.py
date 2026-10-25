"""LumaCutClient against a fake Pi HTTP server (no Qt, no hardware)."""
import email
import socket
import unittest

import _paths  # noqa: F401  (puts src/ on sys.path)
from fake_pi import FakePi

from machine.client import (AUTH_HEADER, ApiError, AuthFailed, ConnectionFailed,
                            LumaCutClient, ProtocolError, normalize_base_url)


class NormalizeUrlTests(unittest.TestCase):
    def test_defaults_and_port(self):
        self.assertEqual(normalize_base_url(""), "http://lumacut.local:8080")
        self.assertEqual(normalize_base_url("lumacut.local"), "http://lumacut.local:8080")
        self.assertEqual(normalize_base_url("192.168.2.89:8081/"), "http://192.168.2.89:8081")
        self.assertEqual(normalize_base_url("http://pi:9000"), "http://pi:9000")

    def test_rejects_garbage(self):
        with self.assertRaises(ValueError):
            normalize_base_url("ftp://pi")


class ClientTests(unittest.TestCase):
    def setUp(self):
        self.pi = FakePi(required_key="s3cret-key").__enter__()
        self.client = LumaCutClient(self.pi.url, "s3cret-key")

    def tearDown(self):
        self.pi.__exit__(None, None, None)

    def test_status_is_parsed_and_key_header_sent(self):
        status = self.client.status()
        self.assertTrue(status.skr_connected)
        self.assertTrue(status.homed)
        self.assertEqual(status.position, (120.5, 80.25, 20.0))
        self.assertFalse(status.laser_armed)
        self.assertEqual(status.job.state, "idle")
        self.assertIsNone(status.job.progress)
        self.assertEqual(self.pi.last()["headers"].get(AUTH_HEADER), "s3cret-key")

    def test_job_progress(self):
        self.pi.status["job"] = {"file": "a.gcode", "state": "running",
                                 "line": 25, "total": 100, "error": ""}
        job = self.client.status().job
        self.assertTrue(job.active)
        self.assertAlmostEqual(job.progress, 0.25)

    def test_wrong_key_is_auth_failed(self):
        with self.assertRaises(AuthFailed) as ctx:
            LumaCutClient(self.pi.url, "wrong").status()
        self.assertNotIn("wrong", str(ctx.exception))
        with self.assertRaises(AuthFailed):
            LumaCutClient(self.pi.url, "").status()
        self.assertNotIn(AUTH_HEADER, self.pi.last()["headers"])

    def test_key_never_in_repr(self):
        self.assertNotIn("s3cret", repr(self.client))

    def test_actions_send_form_payloads(self):
        self.assertEqual(self.client.home(), "ok home")
        self.assertEqual(self.pi.last("/api/action")["form"], {"op": "home"})
        self.client.jog("x", -10)
        self.assertEqual(self.pi.last("/api/action")["form"],
                         {"op": "jog", "axis": "X", "distance": "-10.0"})
        self.client.jog("Z", 0.1)
        self.assertEqual(self.pi.last("/api/action")["form"]["distance"], "0.1")
        self.client.focus()
        self.assertEqual(self.pi.last("/api/action")["form"], {"op": "probe"})
        self.client.probe(100, 120.5)
        self.assertEqual(self.pi.last("/api/action")["form"],
                         {"op": "probe", "x": "100.000", "y": "120.500"})
        self.client.park()
        self.assertEqual(self.pi.last("/api/action")["form"], {"op": "park"})
        self.client.emergency_stop()
        self.assertEqual(self.pi.last("/api/action")["form"], {"op": "estop"})
        self.client.reset_emergency()
        self.assertEqual(self.pi.last("/api/action")["form"], {"op": "estop_reset"})
        self.client.start_job("a.gcode")
        self.assertEqual(self.pi.last("/api/action")["form"], {"op": "start", "name": "a.gcode"})
        self.client.autorun_job("a.gcode")
        self.assertEqual(self.pi.last("/api/action")["form"], {"op": "autorun", "name": "a.gcode"})
        self.client.abort_job()
        self.assertEqual(self.pi.last("/api/action")["form"], {"op": "abort"})
        self.client.connect_machine()
        self.assertEqual(self.pi.last("/api/action")["form"], {"op": "connect"})

    def test_invalid_jog_never_reaches_the_pi(self):
        before = len(self.pi.requests)
        for axis, distance in (("A", 1), ("X", 5), ("Y", 0)):
            with self.assertRaises(ValueError):
                self.client.jog(axis, distance)
        with self.assertRaises(ValueError):
            self.client.start_job("../etc/passwd.gcode")
        with self.assertRaises(ValueError):
            self.client.start_job("job.txt")
        self.assertEqual(len(self.pi.requests), before)

    def test_pi_rejection_carries_german_reason(self):
        self.pi.fail["home"] = (400, {"error": "Steuerung belegt durch lightburn"})
        with self.assertRaises(ApiError) as ctx:
            self.client.home()
        self.assertIn("lightburn", str(ctx.exception))
        self.assertEqual(ctx.exception.status, 400)
        self.pi.fail["home"] = (503, {"error": "Marlin SKR noch nicht per USB identifiziert"})
        with self.assertRaises(ApiError):
            self.client.home()

    def test_park_on_old_pi_service_explains_gap(self):
        self.pi.actions.discard("park")
        with self.assertRaises(ApiError) as ctx:
            self.client.park()
        self.assertIn("op=park", str(ctx.exception))

    def test_upload_is_multipart_with_filename(self):
        msg = self.client.upload_job("studio-1.gcode", "G0 X40 Y40\nM5 I\n")
        self.assertIn("gespeichert", msg)
        req = self.pi.last("/api/upload")
        ctype = req["headers"]["Content-Type"]
        self.assertTrue(ctype.startswith("multipart/form-data; boundary="))
        parsed = email.message_from_bytes(
            b"Content-Type: " + ctype.encode() + b"\r\n\r\n" + req["body"])
        part = parsed.get_payload()[0]
        self.assertEqual(part.get_param("name", header="content-disposition"), "file")
        self.assertEqual(part.get_filename(), "studio-1.gcode")
        self.assertEqual(part.get_payload(decode=True), b"G0 X40 Y40\nM5 I\n")
        self.assertEqual(req["headers"].get(AUTH_HEADER), "s3cret-key")

    def test_upload_rejection(self):
        self.pi.fail["upload"] = (400, {"error": "G-Code Zeile 3: M4 unzulässig"})
        with self.assertRaises(ApiError) as ctx:
            self.client.upload_job("a.gcode", "M4\n")
        self.assertIn("Zeile 3", str(ctx.exception))

    def test_jobs_and_geometry(self):
        self.assertEqual(self.client.jobs()[0]["name"], "a.gcode")
        self.assertEqual(self.client.job_geometry("a.gcode")["center"], [50, 50])

    def test_not_a_lumacut_server(self):
        self.pi.status["firmware"] = "grbl"
        with self.assertRaises(ProtocolError):
            self.client.status()

    def test_redirects_are_not_followed(self):
        self.pi.redirect = True
        with self.assertRaises(ProtocolError):
            self.client.status()


class UnreachableTests(unittest.TestCase):
    def test_connection_refused(self):
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        sock.close()
        with self.assertRaises(ConnectionFailed):
            LumaCutClient("http://127.0.0.1:%d" % port, "k").status()


if __name__ == "__main__":
    unittest.main()
