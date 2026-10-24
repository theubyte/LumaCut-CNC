"""Pi 400 GRBL transport and browser server regression tests.

Tests do not send real motion. In particular GRBL host status '?'
requests are forwarded exactly once; Pi dashboard polls never reach
the LightBurn console.
"""
import importlib
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
import time
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"pi400"))
from lumacut.core import Controller


class FakeSocket:
    def __init__(self):
        self.lines=bytearray()
        self.closed=False

    def sendall(self,data):
        self.lines.extend(data)

    def close(self):
        self.closed=True


class Pi400TransportTests(unittest.TestCase):
    def test_unsolicited_status_never_spams_lightburn(self):
        c=Controller("/dev/null")
        sock=FakeSocket()
        c.host=sock
        c.owner="host"
        for i in range(100):
            with c.cond:
                forwarded=c._read_response("<Idle|MPos:0,0,0|FS:0,0>")
            self.assertFalse(forwarded)
        self.assertEqual(c.suppressed_reports,100)
        self.assertEqual(c.position,[0.,0.,0.])
        self.assertEqual(c.state,"Idle")
        self.assertEqual(c.host_pending,0)

    def test_explicit_host_status_and_grbl_replies(self):
        c=Controller("/dev/null")
        c.host=FakeSocket()
        c.owner="host"
        c.host_pending=1
        with c.cond:
            self.assertTrue(c._read_response("<Run|MPos:-2,-3,-4>"))
            self.assertFalse(c._read_response("<Run|MPos:-3,-4,-5>"))
            self.assertTrue(c._read_response("ok"))
            self.assertTrue(c._read_response("error:20"))
            self.assertTrue(c._read_response("[VER:1.1f]"))
            self.assertTrue(c._read_response("$30=1000"))
        self.assertEqual(c.settings[30],1000)
        self.assertEqual(c.last_error,"error:20")
        self.assertEqual(c.suppressed_reports,1)

    def test_lightburn_homing_and_settings_are_tracked_from_real_ack(self):
        c=Controller("/dev/null")
        c.host=FakeSocket()
        c.owner="host"
        c.host_commands.append("$H")
        with c.cond:
            c._read_response("ok")
        self.assertTrue(c.homed)
        c.host_commands.append("$130=450.5")
        with c.cond:
            c._read_response("ok")
        self.assertEqual(c.settings[130],450.5)
        self.assertFalse(c.homed)
        c.host_commands.append("$H")
        with c.cond:
            c._read_response("error:9")
        self.assertFalse(c.homed)

    def test_lightburn_cannot_bypass_service_parameter_or_gpio_access(self):
        c = Controller("/dev/null")
        sock = FakeSocket()
        class FakeSerial:
            def __init__(self): self.written = bytearray()
            def write(self, data):
                self.written.extend(data)
                return len(data)
        c.serial = FakeSerial()
        c.host = sock
        c.owner = "host"
        c._forward_host_bytes_locked(b"$LCIO=1\n$110=6000\n$I\nM64 P0\nG1 X10 F1000\n?")
        self.assertEqual(bytes(c.serial.written), b"$I\nG1 X10 F1000\n?")
        self.assertEqual(bytes(sock.lines), b"error:9\r\n"*3)
        self.assertEqual(c.host_pending, 1)
        self.assertEqual(list(c.host_commands), ["$I", "G1 X10 F1000"])
        self.assertTrue(c.host_command_allowed("$H"))
        self.assertTrue(c.host_command_allowed("$G"))
        self.assertTrue(c.host_command_allowed("M3 S100"))
        self.assertFalse(c.host_command_allowed("$27=4"))
        self.assertFalse(c.host_command_allowed("G1 X10 M65 P0"))

    def test_lightburn_chunked_and_oversized_commands_fail_closed(self):
        c = Controller("/dev/null")
        sock = FakeSocket()
        class FakeSerial:
            def __init__(self): self.written = bytearray()
            def write(self, data):
                self.written.extend(data)
                return len(data)
        c.serial = FakeSerial()
        c.host = sock
        c.owner = "host"
        c._forward_host_bytes_locked(b"$110")
        c._forward_host_bytes_locked(b"=100\r\nG0 X2\r\n")
        self.assertEqual(bytes(c.serial.written), b"G0 X2\n")
        self.assertEqual(bytes(sock.lines), b"error:9\r\n")
        c._forward_host_bytes_locked(b"G0 X" + b"0"*400 + b"\n")
        self.assertEqual(bytes(sock.lines), b"error:9\r\n"*2)
        self.assertEqual(bytes(c.serial.written), b"G0 X2\n")

    def test_exclusive_host_ownership(self):
        c=Controller("/dev/null")
        c.serial=object()
        c.owner="host"
        with self.assertRaisesRegex(RuntimeError,"belegt"):
            c.command("$I",timeout=0.01)
        c.owner=None
        c.bootstrap_ready=True
        with self.assertRaises(TimeoutError):
            # A fake write-only SKR never ACKs.
            class Device:
                def write(self,data): return len(data)
            c.serial=Device()
            c.command("$I",timeout=0.02)

    def test_usb_bootstrap_requires_two_real_acks(self):
        c=Controller("/dev/null")
        with c.cond:
            c.bootstrap_pending=2
            self.assertFalse(c.bootstrap_ready)
            c._read_response("[FIRMWARE:grblHAL]")
            c._read_response("[BOARD:LumaCut SKR Mini MZ v1.0 EXPERIMENTAL]")
            for setting in ("$30=1000","$32=1","$130=450","$131=450","$132=80"):
                c._read_response(setting)
            self.assertFalse(c.bootstrap_ready)
            c._read_response("ok")
            self.assertFalse(c.bootstrap_ready)
            c._read_response("ok")
            self.assertTrue(c.bootstrap_ready)
            self.assertEqual(c.settings[130], 450)

    def test_usb_bootstrap_rejects_other_grbl_boards(self):
        c=Controller("/dev/null")
        with c.cond:
            c.bootstrap_pending=2
            c._read_response("[FIRMWARE:grblHAL]")
            c._read_response("[BOARD:Other Router]")
            for setting in ("$30=1000","$32=1","$130=450","$131=450","$132=80"):
                c._read_response(setting)
            c._read_response("ok")
            c._read_response("ok")
            self.assertFalse(c.bootstrap_ready)
            self.assertIn("passt nicht", c.last_error)

    def test_usb_bootstrap_fails_closed_on_firmware_error(self):
        c=Controller("/dev/null")
        with c.cond:
            c.bootstrap_pending=2
            c._read_response("error:20")
            self.assertFalse(c.bootstrap_ready)
            self.assertEqual(c.bootstrap_pending, 0)
            self.assertIn("Initialisierung", c.last_error)

    def test_accessory_feedback(self):
        c=Controller("/dev/null")
        with c.cond:
            c._read_response("<Idle|MPos:0,0,0|A:FM>")
        self.assertEqual(c.status()["accessories"],{"lights":True,"exhaust":True})
        with c.cond:
            c._read_response("<Idle|MPos:0,0,0>")
        self.assertFalse(c.status()["accessories"]["lights"])


class Pi400WebTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory()
        os.environ["LUMACUT_KEY"]="unit-test-long-private-key"
        os.environ["LUMACUT_DATA"]=cls.temp.name
        os.environ["LUMACUT_SKR"]="/dev/does-not-exist"
        cls.module=importlib.import_module("lumacut.app")
        cls.client=cls.module.app.test_client()

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_frontend_and_authenticated_api(self):
        self.assertEqual(self.client.get("/").status_code,200)
        self.assertEqual(self.client.get("/api/status").status_code,401)
        headers={"X-LumaCut-Key":"unit-test-long-private-key"}
        self.assertEqual(self.client.get("/api/status",headers=headers).status_code,200)
        self.assertEqual(self.client.get("/api/ui/config",headers=headers).status_code,200)
        self.assertEqual(self.client.get("/api/update/status",headers=headers).status_code,200)

    def test_maintenance_disables_mutations(self):
        headers={"X-LumaCut-Key":"unit-test-long-private-key"}
        lock=Path(self.temp.name)/"maintenance.lock"
        lock.touch()
        try:
            response=self.client.post("/api/ui/action",headers=headers,data={"op":"home"})
            self.assertEqual(response.status_code,423)
        finally:
            lock.unlink()

    def test_lightburn_profile_is_real_grbl_usb_import(self):
        headers={"X-LumaCut-Key":"unit-test-long-private-key"}
        response=self.client.get("/api/lightburn/profile",headers=headers)
        self.assertEqual(response.status_code,200)
        obj=json.loads(response.data)
        self.assertEqual(obj["DeviceList"][0]["Name"],"GRBL")

    def test_camera_missing_is_informative(self):
        headers={"X-LumaCut-Key":"unit-test-long-private-key"}
        os.environ["LUMACUT_CAMERA_DEVICE"]="/dev/nonexistent-camera"
        response=self.client.get("/api/camera/snapshot",headers=headers)
        self.assertEqual(response.status_code,503)


if __name__=="__main__":
    unittest.main()
