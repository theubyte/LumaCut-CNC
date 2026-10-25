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


class FirmwareDirectionContractTests(unittest.TestCase):
    def test_laser_power_pin_is_fan1_pc6_and_pwm_is_pa1(self):
        import importlib.util
        spec=importlib.util.spec_from_file_location(
            "lumacut_build",ROOT/"firmware"/"marlin"/"build.py")
        module=importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        pins=module.PIN_PATCH
        self.assertIn("#define SPINDLE_LASER_ENA_PIN PC7",pins)
        self.assertIn("#define SPINDLE_LASER_PWM_PIN PA1",pins)
        self.assertIn("#define FAN0_PIN PC6",pins)
        self.assertIn("#define FAN1_PIN -1",pins)
        self.assertNotIn("#define SPINDLE_LASER_ENA_PIN PC6",pins)

    def test_firmware_native_probe_has_fixed_bed_origin(self):
        build=(ROOT/"firmware"/"marlin"/"build.py").read_text()
        self.assertIn('cfg = uncomment(cfg, "FIX_MOUNTED_PROBE")',build)
        self.assertIn('cfg = uncomment(cfg, "Z_SAFE_HOMING")',build)
        self.assertIn('replace_active(cfg, "Z_SAFE_HOMING_X_POINT", "0")',build)
        self.assertIn('replace_active(cfg, "Z_SAFE_HOMING_Y_POINT", "0")',build)
        self.assertIn('replace_active(cfg, "Z_PROBE_LOW_POINT", "0")',build)

    def test_default_z_steps_match_calibrated_value(self):
        build=(ROOT/"firmware"/"marlin"/"build.py").read_text()
        self.assertIn(
            'replace_active(cfg, "DEFAULT_AXIS_STEPS_PER_UNIT", "{ 80, 80, 380 }")',
            build)

    def test_lumacut_x_y_reversed_only(self):
        build=(ROOT/"firmware/marlin/build.py").read_text(encoding="utf-8")
        self.assertIn('cfg = replace_active(cfg, "INVERT_X_DIR", "false")',build)
        self.assertIn('cfg = replace_active(cfg, "INVERT_Y_DIR", "false")',build)
        self.assertIn('cfg = replace_active(cfg, "INVERT_Z_DIR", "false")',build)
        self.assertIn('cfg = replace_active(cfg, "X_MIN_ENDSTOP_INVERTING", "true")',build)
        self.assertIn('cfg = replace_active(cfg, "Y_MIN_ENDSTOP_INVERTING", "true")',build)
        self.assertIn('cfg = replace_active(cfg, "Z_MIN_ENDSTOP_INVERTING", "true")',build)


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
            "ok\n","ok\n","ok\n","ok\n","ok\n","ok\n","ok\n","ok\n","ok\n",
            "X:0 Y:0 Z:20\n", "ok\n"
        ])
        response = bridge.safe_home()
        self.assertEqual(response[-1],"ok")
        self.assertTrue(bridge.homed)
        self.assertTrue(bridge.z_homed)
        self.assertEqual(bridge.serial.writes[0], b"M5 I\n")
        self.assertEqual(bridge.serial.writes[1], b"G28 X Y\n")
        self.assertEqual(bridge.serial.writes[3], b"G28 Z\n")
        self.assertEqual(bridge.serial.writes[6], b"G0 Z20.00 F360\n")

    def test_lightburn_g28_has_one_ack_and_real_marlin_usb_sequence(self):
        responses=["ok\n"] * 9 + ["X:0 Y:0 Z:20\n","ok\n"]
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

    def test_park_requires_home_and_moves_z_up_before_xy(self):
        serial=FakeSerial([
            "ok\n", "ok\n", "X:60 Y:90 Z:8\n", "ok\n",
            "ok\n", "ok\n", "ok\n", "ok\n", "X:15 Y:15 Z:20\n", "ok\n",
        ])
        ctrl=MarlinTransport("/dev/null")
        ctrl.serial=serial
        ctrl.identity="FIRMWARE_NAME:Marlin MACHINE_TYPE:LumaCut CNC"
        with self.assertRaisesRegex(RuntimeError,"gültiger XYZ"):
            ctrl.park_safezone(owner="lightburn")
        ctrl.homed=True
        reply=ctrl.park_safezone(owner="lightburn")
        self.assertEqual(reply[-1],"ok")
        writes=serial.writes
        self.assertEqual(writes[0],b"M5 I\n")
        self.assertIn(b"G0 Z20.000 F360\n",writes)
        self.assertIn(b"G0 X0.000 Y0.000 F6000\n",writes)
        self.assertLess(writes.index(b"G0 Z20.000 F360\n"),
                        writes.index(b"G0 X0.000 Y0.000 F6000\n"))

    def test_safepark_never_descends_from_current_z(self):
        serial=FakeSerial([
            "ok\n","ok\n","X:42 Y:50 Z:35\n","ok\n",
            "ok\n","ok\n","ok\n","ok\n","X:15 Y:15 Z:35\n","ok\n",
        ])
        ctrl=MarlinTransport("/dev/null")
        ctrl.serial=serial
        ctrl.identity="FIRMWARE_NAME:Marlin MACHINE_TYPE:LumaCut CNC"
        ctrl.homed=True
        ctrl.park_safezone(owner="lightburn")
        self.assertIn(b"G0 Z35.000 F360\n",serial.writes)
        self.assertNotIn(b"G0 Z20.000 F360\n",serial.writes)

    def test_lightburn_marlin_flavor_preamble_with_real_acks(self):
        # LightBurn 2.0.03 prepends a compound G00/G17/G40/G21
        # and G54 even when the user's custom start is only G21/G90.
        serial=FakeSerial(["ok\n"]*9)
        controller=MarlinTransport("/dev/null")
        controller.serial=serial
        controller.identity="FIRMWARE_NAME:Marlin MACHINE_TYPE:LumaCut CNC"
        controller.homing_verified=True
        controller.homed=True
        controller.surface_z=0.0
        class TCP:
            def __init__(self):
                self.messages=bytearray()
                self.payloads=[
                    b"G21\nG90\nG00 G17 G40 G21\nG54\nG90\nM3 I\nM5 I\n", b""]
            def settimeout(self, v): pass
            def recv(self, n): return self.payloads.pop(0)
            def sendall(self, raw): self.messages.extend(raw)
            def close(self): pass
        client=TCP()
        controller.serve_client(client)
        self.assertEqual(client.messages.count(b"ok\r\n"),7)
        self.assertEqual(
            serial.writes,
            [b"G21\n",b"G90\n",b"G21\n",b"M400\n",
             b"G90\n",b"M106 P0 S255\n",b"M3 I\n",b"M5 I\n"])
        self.assertNotIn(b"M112\n",serial.writes)
        self.assertFalse(controller.emergency_latched)

    def test_native_g30_measures_material_without_rezero(self):
        # Machine bed Z0 remains untouched; the only Z-probe command
        # reaching Marlin is G30. X/Y probe offset returns to laser spot.
        serial=FakeSerial([
            "ok\n", "ok\n", "X:80 Y:80 Z:20\n", "ok\n",
            "ok\n", "ok\n",
            "Bed X: 57.000 Y: 65.000 Z: 3.000\n", "ok\n",
            "ok\n", "ok\n", "ok\n", "ok\n",
            "X:80 Y:80 Z:20\n", "ok\n"
        ])
        bridge=MarlinTransport("/dev/null")
        bridge.serial=serial
        bridge.identity="FIRMWARE_NAME:Marlin MACHINE_TYPE:LumaCut CNC"
        bridge.homed=True
        bridge.homing_verified=True
        bridge.probe_xy_offset_mm=(23,15)
        reply=bridge.probe_workpiece(owner="lightburn")
        self.assertEqual(bridge.surface_z,3.0)
        self.assertEqual(bridge.status()["laser_focus_z"],8.5)
        self.assertEqual(bridge.status()["probe_minimum_z"],5.0)
        self.assertIn(b"G30\n",serial.writes)
        self.assertIn(b"G0 X57.000 Y65.000 F6000\n",serial.writes)
        self.assertIn(b"G0 X80.000 Y80.000 F6000\n",serial.writes)
        self.assertNotIn(b"G28 Z\n",serial.writes)
        self.assertTrue(any("workpiece Z:3.000" in x for x in reply))

    def test_g30_requires_calibrated_xy_offset(self):
        serial=FakeSerial([])
        bridge=MarlinTransport("/dev/null")
        bridge.serial=serial
        bridge.identity="FIRMWARE_NAME:Marlin MACHINE_TYPE:LumaCut CNC"
        bridge.homed=True
        bridge.homing_verified=True
        with self.assertRaisesRegex(ValueError,"X/Y-Tasterversatz"):
            bridge.probe_workpiece(owner="lightburn")
        self.assertEqual(serial.writes,[])

    def test_z_motion_floor_blocks_below_2mm_from_material_contact(self):
        serial=FakeSerial([
            "ok\n", "X:0 Y:0 Z:20\n", "ok\n",
            "ok\n", "X:0 Y:0 Z:20\n", "ok\n",
            "ok\n",
        ])
        bridge=MarlinTransport("/dev/null")
        bridge.serial=serial
        bridge.identity="FIRMWARE_NAME:Marlin MACHINE_TYPE:LumaCut CNC"
        bridge.homed=True
        bridge.homing_verified=True
        bridge.surface_z=0.0
        with self.assertRaisesRegex(ValueError,"Z-Sperre"):
            bridge.command("G0 Z1.9")
        self.assertNotIn(b"G0 Z1.9\n",serial.writes)
        # A rejected out-of-bounds move is fail-closed: USB disconnects.
        self.assertFalse(bridge.status()["connected"])
        self.assertTrue(serial.closed)

    def test_no_laser_before_probing_workpiece(self):
        serial=FakeSerial([])
        bridge=MarlinTransport("/dev/null")
        bridge.serial=serial
        bridge.identity="FIRMWARE_NAME:Marlin MACHINE_TYPE:LumaCut CNC"
        bridge.homed=True
        bridge.homing_verified=True
        with self.assertRaisesRegex(RuntimeError,"Werkstückkontakt fehlt"):
            bridge.command("M3 I")
        self.assertFalse(serial.writes)

    def test_reserved_xy_30mm_zone_blocks_laser_cut(self):
        serial=FakeSerial([
            "ok\n", "X:29 Y:35 Z:20\n", "ok\n",
        ])
        bridge=MarlinTransport("/dev/null")
        bridge.serial=serial
        bridge.identity="FIRMWARE_NAME:Marlin MACHINE_TYPE:LumaCut CNC"
        bridge.homed=True
        bridge.homing_verified=True
        bridge.surface_z=3.0
        bridge.laser_enabled=True
        bridge.guard.inline=True
        bridge.focused_this_job=True
        with self.assertRaisesRegex(ValueError,"30mm-Homing-Sperrzone"):
            bridge.command("G1 X45 Y40 S40")
        self.assertNotIn(b"G1 X45 Y40 S40\n",serial.writes)

    def test_reserved_xy_30mm_zone_allows_interior_cut(self):
        serial=FakeSerial([
            "ok\n", "X:35 Y:40 Z:20\n", "ok\n", "ok\n",
        ])
        bridge=MarlinTransport("/dev/null")
        bridge.serial=serial
        bridge.identity="FIRMWARE_NAME:Marlin MACHINE_TYPE:LumaCut CNC"
        bridge.homed=True
        bridge.homing_verified=True
        bridge.surface_z=3.0
        bridge.laser_enabled=True
        bridge.guard.inline=True
        bridge.focused_this_job=True
        self.assertEqual(bridge.command("G1 X65 Y60 S40")[-1],"ok")
        self.assertIn(b"G1 X65 Y60 S40\n",serial.writes)

    def test_reserved_xy_30mm_zone_permits_laser_off_rapid(self):
        serial=FakeSerial(["ok\n"])
        bridge=MarlinTransport("/dev/null")
        bridge.serial=serial
        bridge.identity="FIRMWARE_NAME:Marlin MACHINE_TYPE:LumaCut CNC"
        bridge.homed=True
        bridge.homing_verified=True
        bridge.surface_z=3.0
        bridge.laser_enabled=False
        self.assertEqual(bridge.command("G0 X10 Y10 F6000")[-1],"ok")

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
        with self.assertRaisesRegex(RuntimeError,"Werkstückkontakt fehlt"):
            controller.command("M3 I")
        self.assertEqual(fake.writes, [])

    def test_marlin_web_api_import_and_health(self):
        import subprocess
        import tempfile
        source = r"""
from marlin import web
with web.app.test_client() as client:
  assert client.get("/").status_code == 200
  good = client.get("/api/status")
  assert good.status_code == 200, good.data
  assert client.get("/api/jobs").status_code == 200
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


    def test_idle_service_shutdown_does_not_automatically_send_m112(self):
        source=(ROOT/"pi400"/"marlin"/"web.py").read_text()
        footer=source.split("def main():",1)[1]
        self.assertIn('machine.command("M5 I", owner="shutdown"',footer)
        self.assertIn('machine.command("M400", owner="shutdown"',footer)
        self.assertIn('if unsafe:',footer)
        self.assertIn('machine.emergency_stop()',footer)

    def test_web_api_handles_http_errors_without_double_read(self):
        ui=(ROOT/"pi400"/"marlin"/"index.html").read_text(encoding="utf-8")
        self.assertIn("const raw=await r.text();",ui)
        self.assertNotIn("await r.json();m=",ui)
        self.assertNotIn("m=await r.text()",ui)
        self.assertNotIn('id="saveKey"',ui)
        self.assertNotIn('id="key"',ui)
        self.assertNotIn("X-LumaCut-Key",ui)
        self.assertIn("Keine Anmeldung erforderlich",ui)

    def test_z_switch_tip_offset_wired_end_to_end(self):
        web=(ROOT/"pi400"/"marlin"/"web.py").read_text()
        ui=(ROOT/"pi400"/"marlin"/"index.html").read_text()
        self.assertIn('"z_switch_tip_offset_mm": 1.5',web)
        self.assertIn('request.form.get("z_switch_tip_offset_mm"',web)
        self.assertIn('config["z_switch_tip_offset_mm"] = offset',web)
        self.assertIn('persist()',web)
        self.assertIn('estimated_tip_gap_mm=tip_gap',web)
        self.assertIn('estimated_focus_adjust_mm=',web)
        self.assertIn('id="zOffset"',ui)
        self.assertIn('id="saveZSettings"',ui)
        self.assertIn('"/api/settings"',ui)
        self.assertIn('estimated_tip_gap_mm',ui)
        # Offset must not secretly change homing motion without confirming
        # whether the probe point is physically above or below laser tip.
        self.assertIn("machine.safe_home(owner=\"web\", clearance_mm=",web)

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
