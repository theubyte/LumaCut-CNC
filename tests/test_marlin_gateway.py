"""Marlin USB/LightBurn/Wi-Fi contract tests without real motors or laser."""
import os
import sys
import tempfile
import subprocess
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pi400"))
from marlin.transport import MarlinLaserGuard, MarlinTransport

ROOT=Path(__file__).resolve().parents[1]


class FakeSerial:
    def __init__(self, replies=None):
        self.replies=list(replies or [])
        self.writes=[]
        self.closed=False
    def write(self, raw):
        self.writes.append(raw)
        return len(raw)
    def readline(self):
        if not self.replies:
            time.sleep(0.002)
            return b""
        return self.replies.pop(0).encode("ascii")
    def reset_input_buffer(self):
        pass
    def close(self):
        self.closed=True


class GuardTests(unittest.TestCase):
    def test_inline_marlin_m3_i_and_cut(self):
        g=MarlinLaserGuard()
        for cmd in ("M5 I","M3 I","G0 X30 Y20","G1 X50 S180 F1500",
                    "G1 Y55","G0 X20","G1 X35 S40","M5 I"):
            self.assertEqual(g.check(cmd, True),cmd)
        self.assertFalse(g.inline)

    def test_rejects_grbl_alias_and_wrong_power_mode(self):
        for cmd in ("$H", "$$", "?", "M4 I", "M3 S255", "M3",
                    "M42 P7 S255", "G1 X1 S500", "G1 X1 S20"):
            with self.subTest(cmd=cmd):
                with self.assertRaises(ValueError):
                    MarlinLaserGuard().check(cmd, True)

    def test_requires_explicit_cut_power_after_rapid(self):
        g=MarlinLaserGuard()
        g.check("M3 I",True)
        g.check("G0 X10",True)
        with self.assertRaisesRegex(ValueError,"nach G0"):
            g.check("G1 X20 F600",True)

    def test_homing_and_motion_require_verification(self):
        g=MarlinLaserGuard()
        for command in ("G28", "G28 Z", "G0 X5", "G1 X5"):
            with self.assertRaisesRegex(ValueError,"verifizier|bestätig|nur über Pi"):
                g.check(command,False)
        with self.assertRaisesRegex(ValueError,"nur über Pi"):
            g.check("G28 Z",True)
        with self.assertRaisesRegex(ValueError,"nur über Pi"):
            g.check("G28 X Y",True)


class USBProtocolTests(unittest.TestCase):
    def test_actual_marlin_m115_and_no_grbl_identity_spoof(self):
        serial=FakeSerial([
            "FIRMWARE_NAME:Marlin 2.1.2.9 MACHINE_TYPE:LumaCut CNC Marlin\n",
            "ok P15 B3\n", "ok\n"
        ])
        bridge=MarlinTransport("/dev/null",serial_factory=lambda *a,**k:serial)
        bridge.ensure_ready()
        self.assertEqual(serial.writes,[b"M115\n",b"M5 I\n"])
        self.assertTrue(bridge.status()["connected"])
        self.assertIn("LumaCut CNC",bridge.status()["identity"])

    def test_rejects_firmware_without_lumacut_identity(self):
        serial=FakeSerial(["FIRMWARE_NAME:Marlin 2.1.2.9 MACHINE_TYPE:Printer\n","ok\n"])
        bridge=MarlinTransport("/dev/null",serial_factory=lambda *a,**k:serial)
        with self.assertRaisesRegex(RuntimeError,"Fremde"):
            bridge.ensure_ready()
        self.assertTrue(serial.closed)

    def test_real_marlin_command_ack_required(self):
        serial=FakeSerial(["echo:busy: processing\n",
                          "X:1.00 Y:2.00 Z:3.00 E:0.00 Count X:80 Y:160 Z:1200\n",
                          "ok P15 B3\n"])
        bridge=MarlinTransport("/dev/null")
        bridge.serial=serial
        bridge.identity="FIRMWARE_NAME:Marlin MACHINE_TYPE:LumaCut CNC"
        result=bridge.command("M114")
        self.assertEqual(result[-1],"ok P15 B3")
        self.assertEqual(bridge.status()["position"],[1,2,3])
        self.assertEqual(bridge.status()["command_count"],1)

    def test_no_xyz_homed_after_only_z(self):
        serial=FakeSerial(["ok\n", "ok\n"])
        bridge=MarlinTransport("/dev/null")
        bridge.serial=serial
        bridge.identity="FIRMWARE_NAME:Marlin MACHINE_TYPE:LumaCut CNC"
        bridge.homing_verified=True
        with self.assertRaisesRegex(ValueError,"nur über Pi"):
            bridge.command("G28 Z")
        self.assertFalse(bridge.homed)
        bridge.homing_verified=True
        bridge.serial=FakeSerial([
            "ok\n","ok\n","ok\n","ok\n","ok\n","ok\n","ok\n","ok\n",
            "X:0 Y:0 Z:20\n", "ok\n"
        ])
        response = bridge.safe_home()
        self.assertEqual(response[-1],"ok")
        self.assertTrue(bridge.homed)
        self.assertTrue(bridge.z_homed)
        self.assertEqual(bridge.serial.writes[0], b"M5 I\n")
        self.assertEqual(bridge.serial.writes[1], b"G28 Z\n")
        self.assertEqual(bridge.serial.writes[4], b"G0 Z20.00 F360\n")
        self.assertEqual(bridge.serial.writes[6], b"G28 X Y\n")

    def test_lightburn_g28_has_one_ack_and_real_marlin_usb_sequence(self):
        responses=["ok\n"] * 8 + ["X:0 Y:0 Z:20\n","ok\n"]
        serial=FakeSerial(responses)
        controller=MarlinTransport("/dev/null")
        controller.serial=serial
        controller.identity="FIRMWARE_NAME:Marlin MACHINE_TYPE:LumaCut CNC"
        controller.homing_verified=True
        class FakeTCP:
            def __init__(self):
                self.payloads=[b"G28\r\n",b""]
                self.messages=bytearray()
                self.closed=False
            def settimeout(self,t): self.timeout=t
            def recv(self,n): return self.payloads.pop(0)
            def sendall(self,p): self.messages.extend(p)
            def close(self): self.closed=True
        sock=FakeTCP()
        controller.serve_client(sock)
        self.assertEqual(sock.messages.count(b"ok\r\n"),1,sock.messages)
        self.assertIn(b"X:0 Y:0 Z:20",sock.messages)
        self.assertTrue(controller.homed)
        self.assertEqual(controller.owner,None)
        self.assertTrue(sock.closed)

    def test_emergency_stop_bypasses_motion_lock_and_latches(self):
        controller=MarlinTransport("/dev/null")
        serial=FakeSerial([])
        controller.serial=serial
        controller.identity="FIRMWARE_NAME:Marlin MACHINE_TYPE:LumaCut CNC"
        controller.homed=True
        controller.emergency_stop()
        self.assertIn(b"M112\n",serial.writes)
        self.assertTrue(controller.status()["emergency_latched"])
        self.assertFalse(controller.status()["homed"])
        with self.assertRaisesRegex(RuntimeError,"Notstopp"):
            controller.command("M114")

    def test_estop_with_missing_usb_is_not_falsely_acknowledged(self):
        controller=MarlinTransport("/dev/null")
        with self.assertRaisesRegex(ConnectionError,"NICHT übertragen"):
            controller.emergency_stop()
        self.assertTrue(controller.status()["emergency_latched"])

    def test_job_cannot_embed_emergency_commands(self):
        guard=MarlinLaserGuard()
        for cmd in ("M112","M410"):
            with self.subTest(cmd=cmd):
                with self.assertRaisesRegex(ValueError,"Notstopp"):
                    guard.check(cmd, True)

    def test_timeout_disconnects_and_fails_closed(self):
        serial=FakeSerial([])
        bridge=MarlinTransport("/dev/null")
        bridge.serial=serial
        bridge.identity="FIRMWARE_NAME:Marlin MACHINE_TYPE:LumaCut CNC"
        with self.assertRaises(TimeoutError):
            bridge.command("M114",timeout=.03)
        self.assertFalse(bridge.status()["connected"])
        self.assertTrue(serial.closed)


class GatewayFilesTests(unittest.TestCase):
    def test_no_unsafe_marlin_commands_or_unhomed_power(self):
        guard = MarlinLaserGuard()
        for cmd in ("M42 P7 S255", "M999", "M106 S255", "G92 X100",
                    "M3 S255", "G0 X40 S255", "M3 I S150"):
            with self.subTest(cmd=cmd):
                with self.assertRaises(ValueError):
                    guard.check(cmd, True)
        fake=FakeSerial([])
        controller=MarlinTransport("/dev/null")
        controller.serial=fake
        controller.identity="FIRMWARE_NAME:Marlin MACHINE_TYPE:LumaCut CNC"
        controller.homing_verified=True
        with self.assertRaisesRegex(RuntimeError,"vollständig referenzieren"):
            controller.command("M3 I")
        self.assertEqual(fake.writes, [])

    def test_marlin_web_api_import_and_health(self):
        import subprocess
        import tempfile
        source = r"""
from marlin import web
with web.app.test_client() as client:
  assert client.get("/").status_code == 200
  assert client.get("/api/status").status_code == 401
  good = client.get("/api/status", headers={"X-LumaCut-Key":"test-secret-123456"})
  assert good.status_code == 200, good.data
  payload = good.get_json()
  assert payload["firmware"] == "marlin"
  assert payload["homing_verified"] is False
"""
        with tempfile.TemporaryDirectory() as tmp:
            env=os.environ.copy()
            env["LUMACUT_KEY"]="test-secret-123456"
            env["LUMACUT_DATA"]=tmp
            env["PYTHONPATH"]=str(ROOT/"pi400")
            result=subprocess.run([sys.executable,"-c",source],env=env,
                                  cwd=ROOT,text=True,capture_output=True,timeout=15)
            self.assertEqual(result.returncode,0,result.stderr)


    def test_web_api_handles_http_errors_without_double_read(self):
        ui=(ROOT/"pi400"/"marlin"/"index.html").read_text(encoding="utf-8")
        self.assertIn("const raw=await r.text();",ui)
        self.assertNotIn("await r.json();m=",ui)
        self.assertNotIn("m=await r.text()",ui)
        self.assertIn("Maschinenzugangscode fehlt oder ist ungültig",ui)
        self.assertIn("Zugangscode erforderlich",ui)

    def test_machine_web_and_service_modules_compile(self):
        import subprocess
        paths=[str(ROOT/"pi400"/"marlin"/p)
               for p in ("web.py","transport.py")]
        cmd=[sys.executable,"-m","py_compile",*paths]
        result=subprocess.run(cmd,capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)

    def test_ui_contains_real_marlin_protocol_and_accessory_actions(self):
        ui=(ROOT/"pi400"/"marlin"/"index.html").read_text()
        self.assertIn("MARLIN CONTROL OS",ui)
        for cmd in ("M3 I","M114","M115","M119","M112","LUMACUT_KEY"):
            if cmd=="LUMACUT_KEY":continue
            self.assertIn(cmd,ui)

if __name__=="__main__":
    unittest.main()
