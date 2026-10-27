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


class ProbeContactHeightTests(unittest.TestCase):
    def test_marlin_2129_early_trigger_threshold_for_3mm_mdf(self):
        from importlib.util import spec_from_file_location, module_from_spec
        spec = spec_from_file_location("lumacut_marlin_build",
                                       ROOT / "firmware" / "marlin" / "build.py")
        module = module_from_spec(spec)
        spec.loader.exec_module(module)
        # The original Marlin 2.1.2.9 tolerance is 5mm; the actual switch
        # triggered at Z5.37 above the bare-bed origin and was rejected.
        self.assertGreater(5.37, 5.0)
        source = (ROOT / "firmware" / "marlin" / "build.py").read_text(encoding="utf-8")
        self.assertIn('replace_active(cfg, "Z_CLEARANCE_MULTI_PROBE", "16")', source)
        self.assertIn('replace_active(cfg, "Z_CLEARANCE_BETWEEN_PROBES", "16")', source)
        self.assertLess(5.37, 16.0)
        example = (
            "#define Z_CLEARANCE_BETWEEN_PROBES  5 // (mm)\n"
            "#define Z_CLEARANCE_MULTI_PROBE     5 // (mm)\n"
        )
        patched = module.replace_active(example, "Z_CLEARANCE_MULTI_PROBE", "16")
        patched = module.replace_active(patched, "Z_CLEARANCE_BETWEEN_PROBES", "16")
        self.assertIn("#define Z_CLEARANCE_MULTI_PROBE 16", patched)
        self.assertIn("#define Z_CLEARANCE_BETWEEN_PROBES 16", patched)


class ProbePinConfigurationTests(unittest.TestCase):
    def test_g30_shares_zmin_pin(self):
        source = (ROOT / "firmware" / "marlin" / "build.py").read_text(encoding="utf-8")
        self.assertIn('probe_directive = "Z_MIN_PROBE_USES_Z_MIN_ENDSTOP_PIN"', source)
        self.assertIn('uncomment(cfg, "FIX_MOUNTED_PROBE")', source)
        self.assertIn('replace_active(cfg, "Z_MIN_ENDSTOP_INVERTING", "true")', source)


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
        self.assertIn('replace_active(cfg, "Z_PROBE_LOW_POINT", "-2")',build)

    def test_firmware_z_travel_ends_at_80mm(self):
        build=(ROOT/"firmware"/"marlin"/"build.py").read_text()
        self.assertIn('replace_active(cfg, "Z_MAX_POS", "80")',build)

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


class ZSpeedProfileTests(unittest.TestCase):
    def test_firmware_sets_both_z_homing_and_g30_speeds_to_1_8x(self):
        from importlib.util import module_from_spec, spec_from_file_location
        spec = spec_from_file_location(
            "lumacut_z_speed_build", ROOT / "firmware" / "marlin" / "build.py")
        module = module_from_spec(spec)
        spec.loader.exec_module(module)
        example = (
            "#define HOMING_FEEDRATE_MM_M { (50*60), (50*60), (4*60) }\n"
            "#define Z_PROBE_FEEDRATE_FAST (4*60)\n"
            "#define Z_PROBE_FEEDRATE_SLOW (Z_PROBE_FEEDRATE_FAST / 2)\n"
            "#define DEFAULT_MAX_FEEDRATE { 500, 500, 5, 30 }\n"
        )
        source = (ROOT / "firmware" / "marlin" / "build.py").read_text()
        self.assertIn('replace_active(cfg, "HOMING_FEEDRATE_MM_M",', source)
        self.assertIn('replace_active(cfg, "Z_PROBE_FEEDRATE_FAST", "432")', source)
        self.assertIn('replace_active(cfg, "Z_PROBE_FEEDRATE_SLOW", "216")', source)
        self.assertIn('replace_active(cfg, "DEFAULT_MAX_FEEDRATE", "{ 150, 150, 9 }")', source)
        homing = module.replace_active(
            example, "HOMING_FEEDRATE_MM_M", "{ (50*60), (50*60), 432 }")
        fast = module.replace_active(homing, "Z_PROBE_FEEDRATE_FAST", "432")
        slow = module.replace_active(fast, "Z_PROBE_FEEDRATE_SLOW", "216")
        result = module.replace_active(
            slow, "DEFAULT_MAX_FEEDRATE", "{ 150, 150, 9 }")
        for line in (
            "#define HOMING_FEEDRATE_MM_M { (50*60), (50*60), 432 }",
            "#define Z_PROBE_FEEDRATE_FAST 432",
            "#define Z_PROBE_FEEDRATE_SLOW 216",
            "#define DEFAULT_MAX_FEEDRATE { 150, 150, 9 }",
        ):
            self.assertIn(line, result)
        self.assertEqual(432 / 240, 1.8)
        self.assertEqual(216 / 120, 1.8)
        self.assertLessEqual(432 / 60, 9)


class USBProtocolTests(unittest.TestCase):
    def test_actual_marlin_m115_and_no_grbl_identity_spoof(self):
        serial=FakeSerial([
            "FIRMWARE_NAME:Marlin 2.1.2.9 MACHINE_TYPE:LumaCut CNC Marlin\n",
            "ok P15 B3\n", "ok\n", "ok\n", "ok\n", "ok\n", "ok\n", "ok\n", "ok\n"
        ])
        bridge=MarlinTransport("/dev/null",serial_factory=lambda *a,**k:serial)
        bridge.ensure_ready()
        # M851 clears a stale EEPROM probe offset (Mega Zero -40/-10/+2);
        # the X/Y limits (firmware values until the motion calibration) too.
        self.assertEqual(serial.writes,[b"M115\n",b"M5 I\n",b"M203 Z9\n",
                                        b"M851 X0 Y0 Z0\n", b"M201 X500 Y500\n",
                                        b"M203 X150 Y150 Z9\n", b"M204 P500 T500\n", b"M84 S0\n"])
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
            "X:0 Y:0 Z:20\n", "ok\n", "x_min: TRIGGERED\n", "y_min: TRIGGERED\n", "z_min: open\n", "ok\n"
        ])
        bridge.homing_chime_enabled = False
        response = bridge.safe_home()
        self.assertEqual(response[-1],"ok")
        self.assertTrue(bridge.homed)
        self.assertTrue(bridge.z_homed)
        self.assertEqual(bridge.serial.writes[0], b"M5 I\n")
        self.assertEqual(bridge.serial.writes[1], b"G28 X Y\n")
        self.assertEqual(bridge.serial.writes[3], b"G28 Z\n")
        self.assertEqual(bridge.serial.writes[6], b"G0 Z20.00 F600\n")

    def test_lightburn_g28_has_one_ack_and_real_marlin_usb_sequence(self):
        responses=["ok\n"] * 9 + ["X:0 Y:0 Z:20\n","ok\n","x_min: TRIGGERED\n","y_min: TRIGGERED\n","ok\n"]
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
        controller.homing_chime_enabled = False
        controller.serve_client(sock)
        self.assertEqual(sock.messages.count(b"ok\r\n"),1,sock.messages)
        self.assertIn(b"X:0 Y:0 Z:20",sock.messages)
        self.assertTrue(controller.homed)
        self.assertEqual(controller.owner,None)
        self.assertTrue(sock.closed)

    def test_reference_check_by_the_xy_switches_at_the_origin(self):
        from marlin.transport import parse_endstops
        self.assertEqual(parse_endstops(["Reporting endstop status", "x_min: open", "y_min: TRIGGERED", "z_min: open", "ok"]),
                         {"x_min": False, "y_min": True, "z_min": False})
        def homed_bridge(after_home):
            serial = FakeSerial(["ok\n"] * 9 + ["X:0 Y:0 Z:20\n", "ok\n"] + after_home)
            b = MarlinTransport("/dev/null")
            b.serial = serial
            b.identity = "FIRMWARE_NAME:Marlin MACHINE_TYPE:LumaCut CNC"
            b.homing_verified = True
            b.homing_chime_enabled = False
            b.light_effects = False
            b.safe_home()
            return b, serial
        # switches pressed after homing: check active, still pressed = still homed
        b, serial = homed_bridge(["x_min: TRIGGERED\n", "y_min: TRIGGERED\n", "ok\n",
                                  "x_min: TRIGGERED\n", "y_min: TRIGGERED\n", "ok\n"])
        self.assertTrue(b.switch_check)
        self.assertTrue(b.check_reference())
        self.assertTrue(b.homed)
        self.assertEqual(b.status()["reference"], {"switch_check": True, "lost": ""})
        # head pushed away by hand: X switch open -> not homed any more, reason given
        serial.replies += ["x_min: open\n", "y_min: TRIGGERED\n", "ok\n"]
        self.assertFalse(b.check_reference())
        self.assertFalse(b.homed)
        self.assertIn("Endschalter X offen", b.status()["reference"]["lost"])
        self.assertIsNone(b.check_reference(), "nothing to check while not homed")
        # head somewhere else on the bed: switches are open by design, no check
        b, serial = homed_bridge(["x_min: TRIGGERED\n", "y_min: TRIGGERED\n", "ok\n"])
        b.last_xy_commanded = (120.0, 80.0)
        writes = len(serial.writes)
        self.assertIsNone(b.check_reference())
        self.assertEqual(len(serial.writes), writes)
        # switches that do not reach X0/Y0 on a machine: check stays off instead of false alarms
        b, serial = homed_bridge(["x_min: open\n", "y_min: open\n", "ok\n"])
        self.assertFalse(b.switch_check)
        self.assertIsNone(b.check_reference())
        self.assertTrue(b.homed)
        # somebody else drives the machine: no check
        b, _ = homed_bridge(["x_min: TRIGGERED\n", "y_min: TRIGGERED\n", "ok\n"])
        b.owner = "job"
        self.assertIsNone(b.check_reference())

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
        ctrl.job_chime_enabled = False
        reply=ctrl.park_safezone(owner="lightburn")
        self.assertEqual(reply[-1],"ok")
        writes=serial.writes
        self.assertEqual(writes[0],b"M5 I\n")
        self.assertIn(b"G0 Z20.000 F600\n",writes)
        self.assertIn(b"G0 X0.000 Y0.000 F9000\n",writes)
        self.assertLess(writes.index(b"G0 Z20.000 F600\n"),
                        writes.index(b"G0 X0.000 Y0.000 F9000\n"))

    def test_safepark_never_descends_from_current_z(self):
        serial=FakeSerial([
            "ok\n","ok\n","X:42 Y:50 Z:35\n","ok\n",
            "ok\n","ok\n","ok\n","ok\n","X:15 Y:15 Z:35\n","ok\n",
        ])
        ctrl=MarlinTransport("/dev/null")
        ctrl.serial=serial
        ctrl.identity="FIRMWARE_NAME:Marlin MACHINE_TYPE:LumaCut CNC"
        ctrl.homed=True
        ctrl.job_chime_enabled = False
        ctrl.park_safezone(owner="lightburn")
        self.assertIn(b"G0 Z35.000 F600\n",serial.writes)
        self.assertNotIn(b"G0 Z20.000 F600\n",serial.writes)

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
             b"G90\n",b"M106 P0 S255\n",b"G4 P800\n",b"M3 I\n",b"M5 I\n"])
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
        self.assertIn(b"G0 X57.000 Y65.000 F9000\n",serial.writes)
        self.assertIn(b"G0 X80.000 Y80.000 F9000\n",serial.writes)
        self.assertNotIn(b"G28 Z\n",serial.writes)
        self.assertTrue(any("workpiece Z:3.000" in x for x in reply))

    def test_repeat_g30_from_park_reuses_last_valid_material_point(self):
        responses = [
            "ok\n", "ok\n", "X:0 Y:0 Z:20\n", "ok\n",
            "ok\n", "ok\n", "ok\n", "ok\n", "ok\n",
            "Bed X: 97.000 Y: 105.000 Z: 3.000\n", "ok\n",
            "ok\n", "ok\n", "ok\n", "ok\n",
            "X:120 Y:120 Z:20\n", "ok\n"
        ]
        serial = FakeSerial(responses)
        bridge = MarlinTransport("/dev/null")
        bridge.serial = serial
        bridge.identity = "FIRMWARE_NAME:Marlin MACHINE_TYPE:LumaCut CNC"
        bridge.homed = True
        bridge.homing_verified = True
        bridge.probe_xy_offset_mm = (23, 15)
        bridge.last_probe_laser_xy = (120, 120)
        bridge.probe_workpiece()
        self.assertIn(b"G0 X120.000 Y120.000 F9000\n", serial.writes)
        self.assertIn(b"G0 X97.000 Y105.000 F9000\n", serial.writes)
        self.assertIn(b"G30\n", serial.writes)
        self.assertEqual(bridge.surface_z, 3.0)

    def _probe_bridge(self, responses):
        serial = FakeSerial(responses)
        bridge = MarlinTransport("/dev/null")
        bridge.serial = serial
        bridge.identity = "FIRMWARE_NAME:Marlin MACHINE_TYPE:LumaCut CNC"
        bridge.homed = True
        bridge.homing_verified = True
        bridge.probe_xy_offset_mm = (0.0, 0.0)
        return bridge, serial

    def test_g30_early_trigger_uses_confirmed_contact_height(self):
        # Stock Z_CLEARANCE_MULTI_PROBE 5: contact at 7.37 mm is valid but
        # Marlin reports Probing Failed and leaves the head at the contact.
        bridge, serial = self._probe_bridge([
            "ok\n", "ok\n", "X:120.00 Y:120.00 Z:20.00\n", "ok\n",
            "ok\n", "ok\n",
            "Error:Probing Failed\n",
            "X:120.00 Y:120.00 Z:7.37 E:0.00 Count X:9600 Y:9600 Z:2800\n",
            "ok\n",
            "ok\n",
            "X:120.00 Y:120.00 Z:7.37 E:0.00 Count X:9600 Y:9600 Z:2800\n", "ok\n",
            "Reporting endstop status\n", "x_min: open\n", "y_min: open\n",
            "z_min: TRIGGERED\n", "ok\n",
            "ok\n", "ok\n", "ok\n", "ok\n",
            "X:120.00 Y:120.00 Z:20.00\n", "ok\n",
        ])
        reply = bridge.probe_workpiece()
        self.assertAlmostEqual(bridge.surface_z, 7.37)
        self.assertIn(b"M119\n", serial.writes)
        self.assertIn(b"G0 Z20.000 F600\n", serial.writes)
        self.assertFalse(any(line.startswith("Error:") for line in reply))
        self.assertTrue(any("workpiece Z:7.370" in line for line in reply))
        self.assertEqual(bridge.last_xy_commanded, (120.0, 120.0))

    def test_g30_switch_pressed_at_start_is_rejected(self):
        bridge, serial = self._probe_bridge([
            "ok\n", "ok\n", "X:120.00 Y:120.00 Z:20.00\n", "ok\n",
            "ok\n", "ok\n",
            "Error:Probing Failed\n", "X:120.00 Y:120.00 Z:19.90\n", "ok\n",
            "ok\n", "X:120.00 Y:120.00 Z:19.90\n", "ok\n",
            "z_min: TRIGGERED\n", "ok\n",
        ])
        with self.assertRaisesRegex(RuntimeError, "schon beim G30-Start"):
            bridge.probe_workpiece()
        self.assertIsNone(bridge.surface_z)

    def test_g30_ignores_post_probe_position_report(self):
        # The X:/Y:/Z: report after "Bed" is the raised head, not contact.
        bridge, serial = self._probe_bridge([
            "ok\n", "ok\n", "X:120.00 Y:120.00 Z:20.00\n", "ok\n",
            "ok\n", "ok\n",
            "Bed X: 120.00 Y: 120.00 Z: 4.20\n",
            "X:120.00 Y:120.00 Z:20.20 E:0.00 Count X:9600 Y:9600 Z:7676\n", "ok\n",
            "ok\n", "ok\n", "ok\n", "ok\n", "ok\n",
        ])
        bridge.probe_workpiece()
        self.assertAlmostEqual(bridge.surface_z, 4.2)

    def test_continuous_cut_never_drains_planner_between_segments(self):
        # M400 before each vector node stopped the head and burnt dots.
        serial = FakeSerial(["ok\n"] * 4)
        bridge = MarlinTransport("/dev/null")
        bridge.serial = serial
        bridge.identity = "FIRMWARE_NAME:Marlin MACHINE_TYPE:LumaCut CNC"
        bridge.homed = True
        bridge.homing_verified = True
        bridge.surface_z = 3.0
        bridge.laser_enabled = True
        bridge.guard.inline = True
        bridge.focused_this_job = True
        bridge.last_xy_commanded = (40.0, 40.0)
        for cmd in ("G1 X50 Y40 S100 F1200", "G1 X50 Y50 S100",
                    "G1 X40 Y50 S100", "G1 X40 Y40 S100"):
            bridge.command(cmd, owner="lightburn")
        self.assertNotIn(b"M400\n", serial.writes)
        self.assertNotIn(b"M114\n", serial.writes)
        self.assertEqual(bridge.last_xy_commanded, (40.0, 40.0))

    def test_tracked_start_point_blocks_cut_out_of_home_band(self):
        serial = FakeSerial([])
        bridge = MarlinTransport("/dev/null")
        bridge.serial = serial
        bridge.identity = "FIRMWARE_NAME:Marlin MACHINE_TYPE:LumaCut CNC"
        bridge.homed = True
        bridge.homing_verified = True
        bridge.surface_z = 3.0
        bridge.laser_enabled = True
        bridge.guard.inline = True
        bridge.focused_this_job = True
        bridge.last_xy_commanded = (29.0, 35.0)
        with self.assertRaisesRegex(ValueError, "30mm-Homing-Sperrzone"):
            bridge.command("G1 X45 Y40 S40")
        bridge.last_xy_commanded = (40.0, 40.0)
        # Arc around X30: the circle reaches X20, inside the home band.
        with self.assertRaisesRegex(ValueError, "30mm-Homing-Sperrzone"):
            bridge.command("G2 X40 Y40 I-10 J0 S40")
        self.assertEqual(serial.writes, [])

    def test_lightburn_g1_without_s_after_rapid_reuses_last_power(self):
        # Seen on the machine 25.10.: LightBurn "G1 X175" after G0 without S
        # was rejected and latched M112. Marlin resets inline power on G0.
        serial = FakeSerial(["ok\n"] * 4)
        bridge = MarlinTransport("/dev/null")
        bridge.serial = serial
        bridge.identity = "FIRMWARE_NAME:Marlin MACHINE_TYPE:LumaCut CNC"
        bridge.homed = True
        bridge.homing_verified = True
        bridge.surface_z = 3.0
        bridge.laser_enabled = True
        bridge.guard.inline = True
        bridge.focused_this_job = True
        bridge.last_xy_commanded = (40.0, 40.0)
        bridge.command("G1 X60 Y40 S120 F1500", owner="lightburn")
        bridge.command("G0 X80 Y60", owner="lightburn")
        bridge.command("G1 X175", owner="lightburn")
        self.assertIn(b"G1 X175 S120\n", serial.writes)
        self.assertFalse(bridge.emergency_latched)
        # Outside LightBurn the strict rule stays: explicit S required.
        bridge.command("G0 X80 Y60", owner="web")
        with self.assertRaisesRegex(ValueError, "S-Leistung"):
            bridge.command("G1 X90", owner="web")

    def test_laser_supply_settles_only_on_first_power_up(self):
        serial = FakeSerial(["ok\n"] * 6)
        bridge = MarlinTransport("/dev/null")
        bridge.serial = serial
        bridge.identity = "FIRMWARE_NAME:Marlin MACHINE_TYPE:LumaCut CNC"
        bridge.homed = True
        bridge.homing_verified = True
        bridge.surface_z = 3.0
        bridge.command("M3 I")
        bridge.command("M5 I")
        bridge.command("M3 I")
        self.assertEqual(serial.writes, [b"M106 P0 S255\n", b"G4 P800\n",
                                         b"M3 I\n", b"M5 I\n", b"M3 I\n"])

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
        # The move never reached Marlin. Since 8af184c a rejected G-code
        # keeps the healthy USB link (no forced reconnect / re-home).
        self.assertTrue(bridge.status()["connected"])
        self.assertFalse(serial.closed)

    def test_absolute_z_moves_do_not_drain_the_planner(self):
        # Focus compensation puts a Z word on every short segment; an M400
        # per segment would stop the head and burn dots.
        serial=FakeSerial(["ok\n", "ok\n"])
        bridge=MarlinTransport("/dev/null")
        bridge.serial=serial
        bridge.identity="FIRMWARE_NAME:Marlin MACHINE_TYPE:LumaCut CNC"
        bridge.homed=True
        bridge.homing_verified=True
        bridge.surface_z=3.0
        bridge.command("G0 Z8.5 F600")
        bridge.command("G0 Z5.2")
        self.assertEqual(serial.writes,[b"G0 Z8.5 F600\n", b"G0 Z5.2\n"])
        with self.assertRaisesRegex(ValueError,"Z-Sperre"):
            bridge.command("G0 Z4.9")

    def test_z_never_above_80mm_rail_limit(self):
        # Above Z80 the head runs out of the Z linear rail.
        serial=FakeSerial(["ok\n", "ok\n", "ok\n", "X:0 Y:0 Z:75\n", "ok\n"])
        bridge=MarlinTransport("/dev/null")
        bridge.serial=serial
        bridge.identity="FIRMWARE_NAME:Marlin MACHINE_TYPE:LumaCut CNC"
        bridge.homed=True
        bridge.homing_verified=True
        bridge.surface_z=3.0
        bridge.command("G0 Z80 F600")
        with self.assertRaisesRegex(ValueError,"Höchstgrenze Z80"):
            bridge.command("G0 Z80.1")
        bridge.command("G91")
        with self.assertRaisesRegex(ValueError,"Höchstgrenze Z80"):
            bridge.command("G0 Z+10 F360")   # jog from Z75
        self.assertNotIn(b"G0 Z80.1\n",serial.writes)
        self.assertNotIn(b"G0 Z+10 F360\n",serial.writes)

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

    def test_xy_rapid_without_f_uses_fast_travel_not_previous_z_feed(self):
        serial = FakeSerial(["ok\n"])
        bridge = MarlinTransport("/dev/null")
        bridge.serial = serial
        bridge.identity = "FIRMWARE_NAME:Marlin MACHINE_TYPE:LumaCut CNC"
        bridge.homed = True
        bridge.homing_verified = True
        bridge.command("G0 X120 Y120")
        self.assertEqual(serial.writes, [b"G0 X120 Y120 F9000\n"])

    def test_g30_rejects_firmware_without_probe_capability_before_motion(self):
        serial = FakeSerial()
        bridge = MarlinTransport("/dev/null")
        bridge.serial = serial
        bridge.identity = "FIRMWARE_NAME:Marlin MACHINE_TYPE:LumaCut CNC"
        bridge.homed = True
        bridge.homing_verified = True
        bridge.cap_z_probe = False
        with self.assertRaisesRegex(RuntimeError, "Cap:Z_PROBE:0"):
            bridge.probe_workpiece(owner="lightburn")
        self.assertEqual(serial.writes, [])
        self.assertFalse(bridge.laser_enabled)

    def test_g30_tracks_commanded_xy_independent_of_stale_m114(self):
        serial = FakeSerial(["ok\\n"])
        bridge = MarlinTransport("/dev/null")
        bridge.serial = serial
        bridge.identity = "FIRMWARE_NAME:Marlin MACHINE_TYPE:LumaCut CNC"
        bridge.homed = True
        bridge.homing_verified = True
        bridge.command("G0 X120 Y120", owner="lightburn")
        self.assertEqual(bridge.last_xy_commanded, (120.0, 120.0))

    def test_lightburn_bare_g0_is_modal_without_homing(self):
        serial = FakeSerial(["ok\n"])
        bridge = MarlinTransport("/dev/null")
        bridge.serial = serial
        bridge.identity = "FIRMWARE_NAME:Marlin MACHINE_TYPE:LumaCut CNC"
        bridge.homing_verified = True
        bridge.homed = False
        result = bridge.command("G0", owner="lightburn")
        self.assertEqual(result[-1], "ok")
        self.assertEqual(serial.writes, [b"G0\n"])
        self.assertFalse(bridge.homed)
        self.assertFalse(bridge.laser_enabled)

    def test_lightburn_move_jog_with_s_does_not_require_m3(self):
        serial = FakeSerial(["ok\n"])
        bridge = MarlinTransport("/dev/null")
        bridge.serial = serial
        bridge.identity = "FIRMWARE_NAME:Marlin MACHINE_TYPE:LumaCut CNC"
        bridge.homed = True
        bridge.homing_verified = True
        bridge.command("G1 X120 Y120 F2400 S60", owner="lightburn")
        self.assertEqual(serial.writes, [b"G0 X120 Y120 F2400\n"])
        self.assertFalse(bridge.laser_enabled)

    def test_lightburn_jog_with_stale_inline_guard_stays_laser_off(self):
        serial = FakeSerial(["ok\n"])
        bridge = MarlinTransport("/dev/null")
        bridge.serial = serial
        bridge.identity = "FIRMWARE_NAME:Marlin MACHINE_TYPE:LumaCut CNC"
        bridge.homed = True
        bridge.homing_verified = True
        bridge.guard.inline = True  # stale protocol state after interrupted job
        bridge.laser_enabled = False
        bridge.command("G1 X120 Y120 F2400 S60", owner="lightburn")
        self.assertEqual(serial.writes, [b"G0 X120 Y120 F2400\n"])
        self.assertFalse(bridge.laser_enabled)

    def test_unarmed_powered_motion_outside_lightburn_not_reinterpreted(self):
        serial = FakeSerial()
        bridge = MarlinTransport("/dev/null")
        bridge.serial = serial
        bridge.identity = "FIRMWARE_NAME:Marlin MACHINE_TYPE:LumaCut CNC"
        bridge.homed = True
        bridge.homing_verified = True
        with self.assertRaisesRegex(ValueError, "Laserleistung"):
            bridge.command("G1 X120 Y120 S60", owner="web")

    def test_dimmable_light_and_effects(self):
        from marlin import transport as tr
        serial = FakeSerial(["ok\n"] * 60)
        bridge = MarlinTransport("/dev/null")
        bridge.serial = serial
        bridge.identity = "FIRMWARE_NAME:Marlin MACHINE_TYPE:LumaCut CNC"
        self.assertEqual(bridge.set_light(True, 60), (True, 60, True))
        self.assertIsInstance(bridge.status()["light_brightness"], int)   # the Android app reads an integer
        self.assertEqual(serial.writes, [b"M355 S1 P153\n"])
        bridge.set_light(False)
        self.assertEqual(serial.writes[-1], b"M355 S0 P0\n")
        # Exhaust off (M9) no longer switches the dimmable light.
        bridge.set_light(True)
        bridge.exhaust = True
        bridge.command("M9", owner="web")
        self.assertTrue(bridge.lights)
        self.assertFalse(bridge.exhaust)
        # An effect plays its steps, then returns to the operator's setting.
        serial.writes.clear()
        tr.LIGHT_EFFECTS["test"] = ((100, 0), (0, 0))
        self.assertTrue(bridge.light_effect("test", owner="web"))
        self.assertEqual(serial.writes, [b"M355 S1 P255\n", b"M355 S0 P0\n", b"M355 S1 P153\n"])
        bridge.light_effects = False
        self.assertFalse(bridge.light_effect("test", owner="web"))
        with self.assertRaisesRegex(ValueError, "Helligkeit"):
            bridge.set_light(True, 150)

    def test_old_firmware_light_falls_back_to_m7_m9(self):
        serial = FakeSerial(['echo:Unknown command: "M355 S1 P153"\n', "ok\n"] + ["ok\n"] * 10)
        bridge = MarlinTransport("/dev/null")
        bridge.serial = serial
        bridge.identity = "FIRMWARE_NAME:Marlin MACHINE_TYPE:LumaCut CNC"
        bridge.exhaust = True
        self.assertEqual(bridge.set_light(True, 60)[2], False)
        self.assertEqual(serial.writes, [b"M355 S1 P153\n", b"M7\n"])
        bridge.set_light(False)
        self.assertEqual(serial.writes[-2:], [b"M9\n", b"M8\n"])   # exhaust stays on
        self.assertFalse(bridge.light_effect("home", owner="web"))  # no effects without dimming

    def test_melodies_play_on_motor_coils_without_any_motion(self):
        from marlin.transport import MELODIES
        for event in ("home", "start", "done"):
            with self.subTest(event=event):
                serial = FakeSerial(["ok\n"] * 20)
                bridge = MarlinTransport("/dev/null")
                bridge.serial = serial
                bridge.identity = "FIRMWARE_NAME:Marlin MACHINE_TYPE:LumaCut CNC"
                bridge.homed = True
                bridge.position = [143.0, 105.0, 20.0]   # anywhere: nothing moves
                self.assertTrue(bridge._play_stepper_chime_locked(event))
                expected = [f"M300 S{hz} P{ms}\n".encode() for hz, ms in MELODIES[event]]
                self.assertEqual(serial.writes, expected)
                self.assertTrue(bridge.homed)
                self.assertTrue(bridge.motor_tones_supported)

    def test_no_melody_with_laser_on_or_for_alarms(self):
        serial = FakeSerial(["ok\n"] * 5)
        bridge = MarlinTransport("/dev/null")
        bridge.serial = serial
        bridge.identity = "FIRMWARE_NAME:Marlin MACHINE_TYPE:LumaCut CNC"
        bridge.laser_enabled = True
        self.assertFalse(bridge._play_stepper_chime_locked("done"))
        bridge.laser_enabled = False
        self.assertFalse(bridge._play_stepper_chime_locked("alarm"))
        self.assertEqual(serial.writes, [])

    def test_old_firmware_without_motor_tones_switches_melodies_off(self):
        serial = FakeSerial(['echo:Unknown command: "M300 S784 P130"\n', "ok\n"])
        bridge = MarlinTransport("/dev/null")
        bridge.serial = serial
        bridge.identity = "FIRMWARE_NAME:Marlin MACHINE_TYPE:LumaCut CNC"
        self.assertFalse(bridge._play_stepper_chime_locked("home"))
        self.assertIs(bridge.motor_tones_supported, False)
        self.assertFalse(bridge._play_stepper_chime_locked("done"))
        self.assertEqual(len(serial.writes), 1)

    def test_marlin_error_drains_ack_and_keeps_serial_alive(self):
        from marlin.transport import MarlinCommandError
        serial = FakeSerial(["Error:Probing Failed\n", "ok P15 B7\n",
                             "ok P15 B7\n"])
        bridge = MarlinTransport("/dev/null")
        bridge.serial = serial
        bridge.identity = "FIRMWARE_NAME:Marlin MACHINE_TYPE:LumaCut CNC"
        with self.assertRaisesRegex(MarlinCommandError, "Probing Failed"):
            bridge.command("M119")
        self.assertTrue(bridge.status()["connected"])
        self.assertFalse(serial.closed)
        self.assertEqual(bridge.command("M114")[-1], "ok P15 B7")

    def test_lightburn_probing_failed_preserves_tcp_and_usb(self):
        serial = FakeSerial([
            "ok\n", "ok\n", "X:120.00 Y:120.00 Z:20.00\n",
            "ok\n", "ok\n", "ok\n", "Error:Probing Failed\n",
            # Real 2.1.2.9 G30: report_current_position() follows the error.
            "X:120.00 Y:120.00 Z:-2.00 E:0.00 Count X:9600 Y:9600 Z:-760\n",
            "ok P15 B7\n",
            "ok P15 B7\n",
            "X:120.00 Y:120.00 Z:-2.00 E:0.00 Count X:9600 Y:9600 Z:-760\n",
            "ok P15 B7\n",
            "Reporting endstop status\n", "x_min: open\n", "y_min: open\n",
            "z_min: open\n", "ok P15 B7\n",
            "ok P15 B7\n",
        ])
        bridge = MarlinTransport("/dev/null")
        bridge.serial = serial
        bridge.identity = "FIRMWARE_NAME:Marlin MACHINE_TYPE:LumaCut CNC"
        bridge.homed = True
        bridge.homing_verified = True
        bridge.position = [120.0, 120.0, 20.0]
        bridge.probe_xy_offset_mm = (0.0, 0.0)
        class TCP:
            def __init__(self):
                self.payloads = [b"G30\nG0\n", b""]
                self.messages = bytearray()
            def settimeout(self, value): pass
            def recv(self, count): return self.payloads.pop(0)
            def sendall(self, raw): self.messages.extend(raw)
            def close(self): pass
        sock = TCP()
        bridge.serve_client(sock)
        self.assertIn(b"ohne Tasterkontakt", sock.messages)
        self.assertIsNone(bridge.surface_z)
        self.assertIn(b"ok P15 B7", sock.messages)
        self.assertTrue(bridge.status()["connected"])
        self.assertFalse(serial.closed)
        self.assertTrue(bridge.homed)
        self.assertFalse(bridge.laser_enabled)
        self.assertIn(b"G0\n", serial.writes)

    def test_lightburn_rejected_command_keeps_tcp_alive(self):
        serial = FakeSerial(["ok\n"])
        bridge = MarlinTransport("/dev/null")
        bridge.serial = serial
        bridge.identity = "FIRMWARE_NAME:Marlin MACHINE_TYPE:LumaCut CNC"
        bridge.homing_verified = True
        class TCP:
            def __init__(self):
                self.payloads = [b"M3 I\nG0\n", b""]
                self.messages = bytearray()
            def settimeout(self, value): pass
            def recv(self, count): return self.payloads.pop(0)
            def sendall(self, raw): self.messages.extend(raw)
            def close(self): pass
        sock = TCP()
        bridge.serve_client(sock)
        self.assertIn(b"Error:LumaCut", sock.messages)
        self.assertIn(b"ok\r\n", sock.messages)
        self.assertEqual(serial.writes, [b"G0\n"])
        self.assertFalse(serial.closed)

    def test_reserved_xy_30mm_zone_permits_laser_off_rapid(self):
        serial=FakeSerial(["ok\n"])
        bridge=MarlinTransport("/dev/null")
        bridge.serial=serial
        bridge.identity="FIRMWARE_NAME:Marlin MACHINE_TYPE:LumaCut CNC"
        bridge.homed=True
        bridge.homing_verified=True
        bridge.surface_z=3.0
        bridge.laser_enabled=False
        self.assertEqual(bridge.command("G0 X10 Y10 F9000")[-1],"ok")

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

    def _run_web_script(self, source):
        with tempfile.TemporaryDirectory() as tmp:
            env=os.environ.copy()
            env["LUMACUT_DATA"]=tmp
            env["PYTHONPATH"]=str(ROOT/"pi400")
            result=subprocess.run([sys.executable,"-c",source],env=env,
                                  cwd=ROOT,text=True,capture_output=True,timeout=30)
            self.assertEqual(result.returncode,0,result.stderr)

    def test_preflight_rejects_safezone_motif_and_accepts_workflow_lines(self):
        self._run_web_script(r"""
from marlin import web
web.machine.homing_verified = True
try:
    web.preflight("G0 X40 Y40\nM3 I\nG1 X20 Y40 S100\nM5 I\n")
except ValueError as exc:
    assert "Safezone" in str(exc), exc
else:
    raise AssertionError("motif in home band accepted")
web.preflight("G28\nG30\nG0 X40 Y40\nM3 I\nG1 X60 Y40 S100\nM5 I\nM2\n")
""")

    def test_job_content_delete_and_park_endpoints(self):
        self._run_web_script(r"""
from marlin import web
(web.JOBS / "Schild.gcode").write_text("G21\nM3 I\nG0 X40 Y40\nG1 X50 S10 F600\n", encoding="utf-8")
(web.DATA / "config.json").write_text("{}", encoding="utf-8")
with web.app.test_client() as c:
    r = c.get("/api/jobs")
    assert r.get_json()["files"][0]["name"] == "Schild.gcode" and "modified" in r.get_json()["files"][0]
    r = c.get("/api/jobs/Schild.gcode/content")
    assert r.status_code == 200 and "G1 X50 S10" in r.get_data(as_text=True), r.data
    assert c.get("/api/jobs/..%2Fconfig.json/content").status_code == 400
    assert c.get("/api/jobs/config.json/content").status_code == 400
    web.job.update(file="Schild.gcode", state="running")
    assert c.post("/api/jobs/Schild.gcode/delete").status_code == 400
    web.job.update(state="complete")
    assert c.post("/api/jobs/Schild.gcode/delete").status_code == 200
    assert not (web.JOBS / "Schild.gcode").exists()
    calls = []
    web.machine.park_safezone = lambda owner: calls.append(owner)
    web.local_owner = lambda: None
    r = c.post("/api/action", data={"op": "park"})
    assert r.status_code == 200 and calls == ["web"], (r.data, calls)
""")

    def test_move_to_is_laser_off_and_only_raises_z(self):
        from marlin.transport import MarlinTransport
        serial = FakeSerial(["ok\n", "ok\n", "X:10.00 Y:10.00 Z:5.00\n", "ok\n",
                             "ok\n", "ok\n", "ok\n", "X:200.00 Y:150.00 Z:20.00\n", "ok\n"])
        bridge = MarlinTransport("/dev/null")
        bridge.serial = serial
        bridge.identity = "FIRMWARE_NAME:Marlin MACHINE_TYPE:LumaCut CNC"
        bridge.homed = True
        bridge.homing_verified = True
        bridge.move_to(200.0, 150.0)
        self.assertEqual(serial.writes, [b"M5 I\n", b"M400\n", b"M114\n", b"G0 Z20.000 F600\n",
                                         b"G0 X200.000 Y150.000 F9000\n", b"M400\n", b"M114\n"])
        self.assertEqual(bridge.last_xy_commanded, (200.0, 150.0))
        with self.assertRaisesRegex(ValueError, "außerhalb"):
            bridge.move_to(400.0, 10.0)
        bridge.laser_enabled = True
        with self.assertRaisesRegex(RuntimeError, "Laser"):
            bridge.move_to(100.0, 100.0)

    def test_motion_test_uses_test_limits_and_restores_the_stored_ones(self):
        from marlin.transport import MarlinTransport
        replies = (["ok\n"] * 2 + ["X:10.00 Y:10.00 Z:5.00\n", "ok\n"] + ["ok\n"] * (3 + 3 + 12 + 1 + 3)
                   + ["X:200.00 Y:150.00 Z:20.00\n", "ok\n"])
        serial = FakeSerial(replies)
        bridge = MarlinTransport("/dev/null")
        bridge.serial = serial
        bridge.identity = "FIRMWARE_NAME:Marlin MACHINE_TYPE:LumaCut CNC"
        bridge.homed = True
        bridge.homing_verified = True
        bridge.motion_limits = (1500.0, 180.0)
        bridge.motion_test(3000.0, 250.0, 200.0, 150.0, 40.0, 1)
        writes = [w.decode().strip() for w in serial.writes]
        test = writes.index("M201 X3000 Y3000")
        self.assertEqual(writes[test:test + 3], ["M201 X3000 Y3000", "M203 X250 Y250 Z9", "M204 P3000 T3000"])
        moves = [w for w in writes[test + 3:] if w.startswith("G0 X")]
        self.assertEqual(len(moves), 12)
        self.assertTrue(all(w.endswith("F15000") for w in moves))
        self.assertEqual(moves[-1], "G0 X200.000 Y150.000 F15000")
        self.assertIn("G0 X240.000 Y190.000 F15000", moves)
        self.assertEqual(writes[-4:], ["M201 X1500 Y1500", "M203 X180 Y180 Z9", "M204 P1500 T1500", "M114"])
        self.assertNotIn("M500", writes)
        with self.assertRaisesRegex(ValueError, "außerhalb"):
            bridge.motion_test(3000.0, 250.0, 20.0, 150.0, 40.0, 1)
        with self.assertRaisesRegex(ValueError, "Beschleunigung"):
            bridge.motion_test(50000.0, 250.0, 200.0, 150.0, 40.0, 1)

    def test_motion_limits_sent_now_and_firmware_values_by_default(self):
        from marlin.transport import MarlinTransport
        serial = FakeSerial(["ok\n"] * 8)
        bridge = MarlinTransport("/dev/null")
        bridge.serial = serial
        bridge.identity = "FIRMWARE_NAME:Marlin MACHINE_TYPE:LumaCut CNC"
        bridge.set_motion_limits((2500.0, 200.0))
        bridge.set_motion_limits(None)
        self.assertEqual([w.decode().strip() for w in serial.writes],
                         ["M400", "M201 X2500 Y2500", "M203 X200 Y200 Z9", "M204 P2500 T2500",
                          "M400", "M201 X500 Y500", "M203 X150 Y150 Z9", "M204 P500 T500"])

    def test_camera_snapshot_and_moveto_endpoints(self):
        self._run_web_script(r"""
import subprocess, types, json
from marlin import web
web.CAMERA = __file__ if False else web.CONFIG.parent.as_posix()   # an existing path stands in for /dev/video0
calls = []
FORMATS = "[0]: 'MJPG' (Motion-JPEG, compressed)\n\t\tSize: Discrete 1920x1080\n\t\tSize: Discrete 640x480\n"
CTRLS = "  white_balance_temperature 0x0098091a (int)    : min=2500 max=7000 step=1 default=6000\n"
def fake_run(cmd, **k):
    calls.append(cmd)
    out = FORMATS if "--list-formats-ext" in cmd else CTRLS if "--list-ctrls" in cmd else ""
    return types.SimpleNamespace(returncode=0, stdout=out if k.get("text") else out.encode(), stderr=b"")
class FakeProc:
    def __init__(self, cmd, **k):
        calls.append(cmd); self.returncode = 0
        self.stderr = iter([b"Input #0, video4linux2,v4l2\n", b"  Stream #0:0: Video: mjpeg\n"])
    def communicate(self, timeout=None):
        return bytes([0xFF, 0xD8, 0xFF, 0xE0]) + b"jpegdata", b""
    def kill(self):
        pass
subprocess.run = fake_run
subprocess.Popen = FakeProc
moves = []
web.machine.move_to = lambda x, y, owner: moves.append((x, y, owner))
web.local_owner = lambda: None
with web.app.test_client() as c:
    r = c.get("/api/camera/snapshot?w=640&h=480")
    assert r.status_code == 200 and r.headers["Content-Type"] == "image/jpeg", r.data
    ff = [cmd for cmd in calls if cmd[0] == "ffmpeg"][0]
    assert "640x480" in ff and "v4l2" in ff and "mjpeg" in ff, ff
    assert c.get("/api/camera/snapshot?w=10&h=10").status_code == 400
    r = c.get("/api/camera/snapshot?w=800&h=600")
    assert r.status_code == 400 and "nicht" in r.get_json()["error"], r.data
    assert c.get("/api/status").get_json()["camera"]["available"] is True
    # fixed white balance: stored, reported with the camera's range, set before and after the stream starts
    r = c.put("/api/camera/settings", json={"white_balance": 4800, "light": 100})
    assert r.status_code == 200, r.data
    got = c.get("/api/camera/settings").get_json()
    assert got["white_balance"] == 4800 and got["exposure"] is None and got["ranges"]["white_balance"] == [2500, 7000], got
    assert c.get("/api/status").get_json()["config"]["camera"]["white_balance"] == 4800
    assert c.put("/api/camera/settings", json={"white_balance": "warm"}).status_code == 400
    calls.clear()
    assert c.get("/api/camera/snapshot?w=1920&h=1080").status_code == 200
    assert sum(1 for cmd in calls if "white_balance_temperature=4800" in cmd) == 2, calls
    calls.clear()
    assert c.get("/api/camera/snapshot?w=1920&h=1080&wb=auto").status_code == 200
    assert not any("white_balance_temperature=4800" in cmd for cmd in calls)
    assert any("white_balance_automatic=1" in cmd for cmd in calls)
    r = c.post("/api/action", data={"op": "moveto", "x": "120.5", "y": "80"})
    assert r.status_code == 200 and moves == [(120.5, 80.0, "web")], (r.data, moves)
web.CAMERA = "/dev/does-not-exist"
with web.app.test_client() as c:
    r = c.get("/api/camera/snapshot")
    assert r.status_code == 503 and "Keine Kamera" in r.get_json()["error"], r.data
""")

    def test_job_with_own_z_skips_single_surface_focus(self):
        self._run_web_script(r"""
from marlin import web
compensated = ["G90", "M3 I S0", "G0 X50 Y50", "G0 Z9.5 F600", "G1 X52 Y50 Z9.6 F1500 S200"]
plain = ["G90", "M3 I S0", "G0 X50 Y50", "G1 X52 Y50 F1500 S200", "G0 Z20"]
relative_only = ["G91", "G0 Z-1 F600", "G90", "G1 X52 Y50 F1500 S200"]
assert web._job_sets_focus(compensated)
assert not web._job_sets_focus(plain)
assert not web._job_sets_focus(relative_only)
""")

    def test_one_click_order_and_controlled_stop_without_m112(self):
        self._run_web_script(r"""
from marlin import web
calls = []
m = web.machine
def home(**k):
    calls.append("home")
    m.homed = True
def probe(groups, **k):
    calls.append("probe")
    return [[3.0] * len(g) for g in groups]
m.safe_home = home
m.probe_surface = probe
m.park_safezone = lambda **k: calls.append("park")
m.emergency_stop = lambda: calls.append("M112")
m.probe_xy_offset_mm = (0.0, 0.0)
m.position = [0.0, 0.0, 20.0]
m.homed = False
def command(cmd, **k):
    if cmd.startswith("G1 X99"):
        raise ValueError("rejected")
    calls.append(cmd)
m.command = command
m.stream_command = command  # job lines use the streaming path (#18)
m.drain = lambda **k: None
auto = web.auto_plan(["G28", "G0 X40 Y40", "M3 I", "G1 X44 Y40 S10", "M5 I", "M2"])
web.job_lock.acquire()
web._job_worker("a.gcode", auto["commands"], auto)
# Surface 3 + focus 7 - switch offset 1.5 = Z8.5; G28/M2 of the file dropped.
assert calls == ["home", "probe", "M5 I", "G90", "G0 X40.000 Y40.000",
                 "G0 Z8.500 F600", "M3 I", "G1 X42.000 Y40.000 S10",
                 "G1 X44.000 Y40.000 S10", "M5 I", "park"], calls
assert web.job["state"] == "complete"
calls.clear()
web.job_lock.acquire()
web._job_worker("a.gcode", auto["commands"], auto)
assert calls[:2] == ["probe", "M5 I"], "already homed: no homing again"
calls.clear()
web.job_lock.acquire()
web._job_worker("b.gcode", ["M3 I", "G1 X99 S10"])
assert "M112" not in calls, calls
assert calls[-2:] == ["M5 I", "park"], calls
assert web.job["state"] == "error"
""")

    def test_web_park_action_uses_safe_park_and_respects_owner(self):
        self._run_web_script(r"""
from marlin import web
calls = []
m = web.machine
m.park_safezone = lambda **k: calls.append(("park", k))
m.serial = object()
m.identity = "LumaCut"
m.state = "Idle"
with web.app.test_client() as client:
    ok = client.post("/api/action", data={"op": "park"})
    assert ok.status_code == 200, ok.data
    assert calls == [("park", {"owner": "web"})], calls
    m.owner = "lightburn"
    busy = client.post("/api/action", data={"op": "park"})
    assert busy.status_code == 400, busy.data
    assert "LightBurn" in busy.get_json()["error"]
    assert len(calls) == 1, calls
    m.owner = None
""")

    FRAME_GCODE = ("; LUMACUT FRAME (laser off)\nG21\nG90\nM5 I\nG0 X60.000 Y60.000\n"
                   "G1 X120.000 Y60.000 F3000 S0\nG1 X120.000 Y110.000 F3000 S0\n"
                   "G1 X60.000 Y110.000 F3000 S0\nG1 X60.000 Y60.000 F3000 S0\nM5 I\nM400\n")

    def test_status_never_blocks_behind_long_move(self):
        # Home, park, probe and frame edges hold machine.lock for the whole
        # move. /api/status must answer anyway (cached snapshot + live
        # owner/latch, busy/stale_ms) and stay full and fresh when idle.
        self._run_web_script(r"""
import threading, time
from marlin import web
m = web.machine
m.identity = "FIRMWARE_NAME:Marlin MACHINE_TYPE:LumaCut CNC"
m.serial = object()
m.position = [10.0, 20.0, 30.0]
with web.app.test_client() as c:
    s = c.get("/api/status").get_json()
    assert s["busy"] is False and s["stale_ms"] == 0, s
    assert s["identity"].startswith("FIRMWARE_NAME") and s["owner"] == "Frei", s
    held, release = threading.Event(), threading.Event()
    def long_move():
        with m.lock:
            m.owner = "web"
            m.state = "Busy"
            held.set()
            release.wait(10)
            m.owner = None
            m.state = "Idle"
    t = threading.Thread(target=long_move, daemon=True)
    t.start()
    assert held.wait(5)
    m.emergency_latched = True     # E-Stop writes without the lock
    m.position = [11.0, 20.0, 30.0]
    t0 = time.monotonic()
    r = c.get("/api/status")
    took = time.monotonic() - t0
    assert r.status_code == 200 and took < 2.0, (r.status_code, took)
    s = r.get_json()
    assert s["busy"] is True and s["stale_ms"] >= 0, s
    assert s["owner"] == "web" and s["state"] == "Busy", s
    assert s["emergency_latched"] is True and s["position"] == [11.0, 20.0, 30.0], s
    assert s["identity"].startswith("FIRMWARE_NAME"), "cached fields survive"
    assert s["connected"] is True and "job" in s and "frame" in s, s
    # No cached snapshot at all (first poll during a move): still answers.
    web._status_cache.update(snapshot=None, at=None)
    s = c.get("/api/status").get_json()
    assert s["busy"] is True and s["stale_ms"] is None and s["owner"] == "web", s
    release.set(); t.join(5)
    s = c.get("/api/status").get_json()
    assert s["busy"] is False and s["owner"] == "Frei" and s["stale_ms"] == 0, s
""")

    def test_frame_keeps_uploaded_job_and_never_fires_laser(self):
        # op=frame through the real transport: the uploaded job file, the
        # job list and the job state stay byte-for-byte identical, and Marlin
        # never sees M3 or a non-zero S.
        self._run_web_script(r"""
import re, time
from marlin import web
from marlin.transport import MarlinTransport
FRAME = %r

class Sim:
    def __init__(self):
        self.pos = [150.0, 150.0, 40.0]
        self.out = []
        self.writes = []
    def write(self, raw):
        cmd = raw.decode().strip()
        self.writes.append(cmd)
        reply = []
        if cmd == "M115":
            reply += ["FIRMWARE_NAME:Marlin 2.1.2.9 MACHINE_TYPE:LumaCut CNC Marlin", "Cap:Z_PROBE:1"]
        elif cmd == "M114":
            reply.append("X:%%.2f Y:%%.2f Z:%%.2f E:0.00 Count X:0 Y:0 Z:0" %% tuple(self.pos))
        elif cmd.startswith("G28"):
            self.pos = [0.0, 0.0, 0.0] if cmd == "G28 Z" else [0.0, 0.0, self.pos[2]]
        elif re.match(r"G[01] ", cmd):
            for i, axis in enumerate("XYZ"):
                m = re.search(axis + r"([-+]?[0-9.]+)", cmd)
                if m and " G91" not in " ".join(self.writes[-3:]):
                    self.pos[i] = float(m.group(1))
        elif cmd == "M119":
            reply += ["Reporting endstop status", "z_min: open"]
        self.out += [r + "\n" for r in reply] + ["ok\n"]
        return len(raw)
    def readline(self):
        return self.out.pop(0).encode() if self.out else b""
    def reset_input_buffer(self):
        pass
    def close(self):
        pass

sim = Sim()
web.machine = m = MarlinTransport("/dev/null", serial_factory=lambda *a, **k: sim)
m.homing_verified = True
m.ensure_ready()
job_text = "G21\nG90\nM5 I\nG0 X80 Y80\nM3 I\nG1 X100 Y80 F1500 S60\nM5 I\n"
with web.app.test_client() as c:
    r = c.post("/api/action", data={"op": "frame", "gcode": FRAME})
    assert r.status_code == 400 and "referenzieren" in r.get_json()["error"], r.data
    m.homed = True
    m.state = "Idle"
    import io
    r = c.post("/api/upload", data={"file": (io.BytesIO(job_text.encode()), "Schild.gcode")})
    assert r.status_code == 200, r.data
    web.job.update(file="Schild.gcode", state="complete", line=7, total=7, error="")
    before_job = dict(web.job)
    before_files = sorted(p.name for p in web.JOBS.iterdir())
    before_text = (web.JOBS / "Schild.gcode").read_bytes()
    sent_before = len(sim.writes)
    r = c.post("/api/action", data={"op": "frame", "mode": "hull", "gcode": FRAME})
    assert r.status_code == 200, r.data
    assert "Gummiband" in r.get_json()["message"], r.data
    for _ in range(200):
        if web.frame["state"] != "running":
            break
        time.sleep(0.02)
    assert web.frame["state"] == "complete", web.frame
    assert web.frame["mode"] == "hull" and web.frame["line"] == web.frame["total"], web.frame
    assert web.job == before_job, (web.job, before_job)
    assert sorted(p.name for p in web.JOBS.iterdir()) == before_files
    assert (web.JOBS / "Schild.gcode").read_bytes() == before_text
    framed = sim.writes[sent_before:]
    assert not any(w.startswith("M3") for w in framed), framed
    assert all(re.search(r"S0*[1-9]", w) is None for w in framed if w.startswith("G")), framed
    assert "G1 X120.000 Y110.000 F3000 S0" in framed and framed[-1] in ("M5 I", "M400", "M114"), framed
    assert framed.count("M400") >= 5, "waits per edge so abort stops at the next corner"
    assert m.laser_enabled is False and m.owner is None and not web.job_lock.locked()
    status = c.get("/api/status").get_json()
    assert status["frame"]["state"] == "complete" and status["activity"] == "idle", status
    assert status["job"] == before_job
""" % self.FRAME_GCODE)

    def test_frame_refusals_validation_and_abort(self):
        self._run_web_script(r"""
from marlin import web
FRAME = %r
m = web.machine
m.serial = object()
m.identity = "FIRMWARE_NAME:Marlin MACHINE_TYPE:LumaCut CNC"
m.state = "Idle"
m.homing_verified = True
sent = []
m.command = lambda cmd, **k: sent.append((cmd, k.get("owner")))
with web.app.test_client() as c:
    post = lambda **d: c.post("/api/action", data=dict(op="frame", **d))
    m.homed = False
    r = post(gcode=FRAME)
    assert r.status_code == 400 and "referenzieren" in r.get_json()["error"], r.data
    m.homed = True
    for bad, why in (("G0 X50 Y50\nM3 I\nG1 X60 Y50 S100\n", "M3"),
                     ("G1 X60 Y50 F3000 S10\n", "S"),
                     ("G0 X50 Y50 Z3\n", "Z"),
                     ("G91\nG0 X5\n", "G91"),
                     ("G2 X60 Y60 I5 J0\n", "G2"),
                     ("G0 X50 Y500\n", "travel"),
                     ("G0 X-1 Y50\n", "negative"),
                     ("M106 S255\nG0 X50 Y50\n", "fan"),
                     ("; only comment\nM5 I\n", "no move"),
                     ("", "empty")):
        r = post(gcode=bad)
        assert r.status_code == 400 and "error" in r.get_json(), (why, r.data)
    r = post(gcode=FRAME, mode="spiral")
    assert r.status_code == 400, r.data
    assert sent == [], sent
    # While a job runs: owner is "job" -> refused, nothing sent.
    web.job.update(file="Schild.gcode", state="running")
    web.job_lock.acquire()
    m.owner = "job"
    r = post(gcode=FRAME)
    assert r.status_code == 400 and "job" in r.get_json()["error"], r.data
    m.owner = None
    r = post(gcode=FRAME)
    assert r.status_code == 400 and "läuft bereits" in r.get_json()["error"], r.data
    assert sent == [] and web.job["state"] == "running", sent
    web.job_lock.release()
    web.job.update(state="complete")
    # While framing: a job start is refused with a clear message.
    m.owner = "frame"
    r = c.post("/api/action", data={"op": "start", "name": "Schild.gcode"})
    assert r.status_code == 400 and "Rahmenfahrt" in r.get_json()["error"], r.data
    m.owner = None
    # op=abort reaches a running frame.
    web.frame["state"] = "running"
    web.stop_job.clear()
    r = c.post("/api/action", data={"op": "abort"})
    assert r.status_code == 200 and web.stop_job.is_set(), r.data
    assert c.get("/api/status").get_json()["activity"] == "framing"
# Worker: abort after the first edge -> stops, laser off, lock released.
cmds = web.frame_program(FRAME)
sent.clear()
def stop_on_first_edge(cmd, **k):
    sent.append(cmd)
    if cmd.startswith("G1"):
        web.stop_job.set()
m.command = stop_on_first_edge
web.stop_job.clear()
web.job_lock.acquire()
m.owner = "frame"
web.frame.update(state="running")
web._frame_worker(cmds)
assert web.frame["state"] == "aborted", web.frame
assert [c for c in sent if c.startswith("G1")] == ["G1 X120.000 Y60.000 F3000 S0"], sent
assert sent[-1] == "M5 I" and m.owner is None and not web.job_lock.locked(), sent
assert web.job["state"] == "complete"
""" % self.FRAME_GCODE)

    def test_one_click_end_to_end_against_simulated_marlin(self):
        # Studio output -> Pi preflight -> home -> G30 -> focus -> cut -> park,
        # all through the real transport against a stateful Marlin model.
        self._run_web_script(r"""
import re, time
from marlin import web
from marlin.transport import MarlinTransport

class MarlinSim:
    def __init__(self):
        self.pos = [150.0, 150.0, 40.0]
        self.absolute = True
        self.out = []
        self.writes = []
    def report(self):
        x, y, z = self.pos
        return "X:%.2f Y:%.2f Z:%.2f E:0.00 Count X:0 Y:0 Z:0" % (x, y, z)
    def write(self, raw):
        cmd = raw.decode().strip()
        self.writes.append(cmd)
        words = dict((k, float(v)) for k, v in re.findall(r"([XYZ])([-+]?[0-9.]+)", cmd))
        reply = []
        if cmd == "M115":
            reply.append("FIRMWARE_NAME:Marlin 2.1.2.9 MACHINE_TYPE:LumaCut CNC Marlin")
            reply.append("Cap:Z_PROBE:1")
        elif cmd == "G28 X Y":
            self.pos[0] = self.pos[1] = 0.0
        elif cmd == "G28 Z":
            self.pos[2] = 0.0
        elif cmd in ("G90", "G91"):
            self.absolute = cmd == "G90"
        elif re.match(r"G[0123] ", cmd):
            for i, axis in enumerate("XYZ"):
                if axis in words:
                    self.pos[i] = words[axis] if self.absolute else self.pos[i] + words[axis]
        elif cmd == "M114":
            reply.append(self.report())
        elif cmd == "G30 E0":
            # The switch tip sits at head + offset on a tilted sheet.
            self.pos[2] = surface(self.pos[0] + 10.0, self.pos[1] + 5.0)
            reply.append("Bed X: %.2f Y: %.2f Z: %.3f" % tuple(self.pos))
            reply.append(self.report())
        elif cmd == "M119":
            reply += ["Reporting endstop status", "z_min: open"]
        self.out += [r + "\n" for r in reply] + ["ok\n"]
        return len(raw)
    def readline(self):
        return self.out.pop(0).encode() if self.out else b""
    def reset_input_buffer(self):
        pass
    def close(self):
        pass

def surface(x, y):
    return 3.0 + (x - 250.0) * 0.004 + (y - 280.0) * 0.002

sim = MarlinSim()
web.machine = m = MarlinTransport("/dev/null", serial_factory=lambda *a, **k: sim)
m.homing_verified = True
m.probe_xy_offset_mm = (10.0, 5.0)
m.ensure_ready()
gcode = ("G21\nG90\nM5 I\nM3 I\n; LAYER engrave\nG0 X279.094 Y276.357\n"
         "G1 X388.781 Y276.357 F2000 S77\nG1 X388.781 Y354.412 F2000 S77\n"
         "G1 X279.094 Y354.412 F2000 S77\nG1 X279.094 Y276.357 F2000 S77\nM5 I\nM400\n")
web.preflight(gcode)
auto = web.auto_plan(gcode.splitlines())
web.job_lock.acquire()
m.owner = "job"
web._job_worker("studio.gcode", auto["commands"], auto)
assert web.job["state"] == "complete", web.job
assert web.job["probe"] == {"done": 7, "total": 7}, web.job["probe"]   # 3 x 2 + lowest again
w = sim.writes
probes = [i for i, c in enumerate(w) if c == "G30 E0"]
assert len(probes) == 7 and "G30" not in w, "one measurement per point, no stow/deploy raise"
stow = w.index("M402")
order = [w.index("G28 X Y"), w.index("G28 Z"), probes[0], probes[-1], stow, w.index("M3 I")]
assert order == sorted(order), order
assert w.index("G0 Z20.00 F600") > w.index("G28 Z")
# Fast: between the points only a low hop (contact + 3 mm), never the 20 mm retract.
hops = [float(c.split("Z")[1].split()[0]) for c in w[probes[0]:stow] if c.startswith("G0 Z")]
assert hops and max(hops) < 7.0, hops
# The switch tip probes the planned laser points: head = point - offset.
first = auto["grids"][0].point(0)
approach = [c for c in w[:probes[0]] if c.startswith("G0 X")][-1]
assert approach == "G0 X%.3f Y%.3f F9000" % (first[0] - 10, first[1] - 5), (approach, first)
# The lowest point is probed last, so the Z floor fits every focus height.
contacts = [surface(*auto["grids"][0].point(i)) for i in range(6)]
assert abs(m.surface_z - min(contacts)) < 0.002, (m.surface_z, contacts)
# Focus follows the tilted surface: Z = surface + 7 - 1.5 at every piece.
z = None
cuts = 0
for c in w[w.index("M3 I"):]:
    words = dict(re.findall(r"([XYZS])([-+]?[0-9.]+)", c))
    if c.startswith("G0 Z") or (c.startswith("G1") and "Z" in words):
        z = float(words["Z"])
        assert z >= m.surface_z + 2.0
    if c.startswith("G1 X") and "S77" in c:
        cuts += 1
        expected = surface(float(words["X"]), float(words["Y"])) + 5.5
        assert abs(z - expected) < 0.05, (c, z, expected)
    if c == "M5 I":
        break
assert cuts > 100, "lines split into <= 2 mm pieces"
assert w.index("G4 P800") < w.index("M3 I")
park = w.index("G0 X0.000 Y0.000 F9000")
assert park > w.index("M3 I") and w[park - 2].startswith("G0 Z20.000")
from marlin.transport import MELODIES
tones = [c for c in w if c.startswith("M300 ")]
assert len(tones) == sum(len(MELODIES[e]) for e in ("home", "start", "done")), tones
start_tones = [i for i, c in enumerate(w) if c.startswith("M300 ") and stow < i < w.index("M3 I")]
assert len(start_tones) == len(MELODIES["start"]), "start melody after probing, before the first cut"
assert "M569 S0 X" not in w, "no driver mode switching from the Pi any more"
assert "M112" not in w
assert abs(m.position[0]) < 0.01 and abs(m.position[1]) < 0.01
""")

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

    def test_focus_settings_save_during_lightburn_session(self):
        source = r"""
from marlin import web
web.machine.homed = True
web.machine.owner = "lightburn"
with web.app.test_client() as client:
  r = client.post("/api/settings", data={
    "z_switch_tip_offset_mm": "1.5",
    "z_clearance_mm": "20",
    "focus_gap_mm": "7",
    "probe_offset_x_mm": "23",
    "probe_offset_y_mm": "15"
  })
  assert r.status_code == 200, r.data
  assert web.machine.probe_xy_offset_mm == (23, 15)
  assert web.machine.focus_gap_mm == 7.0
  assert web.CONFIG.is_file()
  assert client.get("/api/status").get_json()["config"]["probe_offset_x_mm"] == 23
  empty = client.post("/api/settings", data={
    "z_switch_tip_offset_mm": "1.5",
    "z_clearance_mm": "20",
    "focus_gap_mm": "7",
    "probe_offset_x_mm": "",
    "probe_offset_y_mm": ""
  })
  assert empty.status_code == 200, empty.data
  assert web.machine.probe_xy_offset_mm is None
"""
        with tempfile.TemporaryDirectory() as tmp:
            env = os.environ.copy()
            env["LUMACUT_DATA"] = tmp
            env["PYTHONPATH"] = str(ROOT / "pi400")
            run = subprocess.run([sys.executable, "-c", source], env=env,
                                 cwd=ROOT, capture_output=True, text=True,
                                 timeout=15)
            self.assertEqual(run.returncode, 0, run.stderr)

    def test_lightburn_busy_reconnect_does_not_spam_error_lines(self):
        controller = MarlinTransport("/dev/null")
        controller.owner = "lightburn"
        class Reconnect:
            def __init__(self): self.lines=[]; self.closed=False
            def settimeout(self, value): pass
            def sendall(self, value): self.lines.append(value)
            def close(self): self.closed=True
        socket = Reconnect()
        controller.serve_client(socket)
        self.assertTrue(socket.closed)
        self.assertEqual(socket.lines, [])

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
