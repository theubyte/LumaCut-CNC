"""Laser G-code and GRBL TCP safety regression tests (no real hardware)."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pi400"))
from lumacut.laser_guard import LaserGuard, check_program
from lumacut.core import Controller
from lumacut.pins import DEFAULT_ROLES, manifest


class FakeSerial:
    def __init__(self):
        self.written = bytearray()

    def write(self, data):
        self.written.extend(data)
        return len(data)


class FakeSocket:
    def __init__(self):
        self.written = bytearray()

    def sendall(self, data):
        self.written.extend(data)


class LaserSafetyTests(unittest.TestCase):
    def test_rejects_powered_m3_traversal_before_any_motion(self):
        for source in (
            "G90\nM3 S500\nG0 X100\nG1 Y5",
            "M3 S0\nG0 X1\nS500\nG0 X100",
            "S1000\nM3\nG0 X100",
            "G0 X10 M3 S700",
        ):
            with self.subTest(source=source):
                with self.assertRaisesRegex(ValueError, "M3"):
                    check_program(source)

    def test_accepts_m4_dynamic_laser_travel(self):
        check_program("G21 G90\nM5\nM8\nM4 S0\nG0 X30 Y40\n"
                      "G1 X50 F500 S350\nG0 X5\nM4 S0\nM5\nM9\nM2")
        check_program("(header)\nG0X0Y0 ; positioning\nM4S0\nG1X4S100\nM5")

    def test_comments_cannot_activate_spindle(self):
        check_program("(M3 S1000)\n; M3 S1000\nM4 S500\nG1 X1")

    def test_laser_requires_real_grbl_laser_mode(self):
        c = Controller("/dev/null")
        c.serial = FakeSerial()
        c.host = FakeSocket()
        c.owner = "host"
        c.bootstrap_ready = True
        c.settings[32] = 0
        c._forward_host_bytes_locked(b"M4 S0\nG0 X5\n")
        self.assertEqual(bytes(c.serial.written), b"")
        self.assertEqual(bytes(c.host.written), b"error:9\r\n" * 2)
        c.settings[32] = 1
        c._forward_host_bytes_locked(b"M4 S0\nG0 X5\n")
        self.assertEqual(bytes(c.serial.written), b"M4 S0\nG0 X5\n")

    def test_host_homing_and_status_queries_remain_allowed(self):
        c = Controller("/dev/null")
        c.serial = FakeSerial()
        c.host = FakeSocket()
        c.owner = "host"
        c.bootstrap_ready = True
        c.settings[32] = 1
        c._forward_host_bytes_locked(b"$I\n$$\n$H\n?\n")
        self.assertEqual(bytes(c.serial.written), b"$I\n$$\n$H\n?")
        self.assertEqual(bytes(c.host.written), b"")

    def test_host_rejects_powered_m3_but_keeps_valid_motion(self):
        c = Controller("/dev/null")
        c.serial = FakeSerial()
        c.host = FakeSocket()
        c.owner = "host"
        c.bootstrap_ready = True
        c.settings[32] = 1
        c._forward_host_bytes_locked(b"M3 S0\nS250\nG0 X50\nM5\nM4 S0\nG1 X60 S250\n")
        self.assertEqual(bytes(c.host.written), b"error:9\r\n")
        self.assertEqual(bytes(c.serial.written),
                         b"M3 S0\nG0 X50\nM5\nM4 S0\nG1 X60 S250\n")

    def test_physical_pin_contract_and_reserved_laser(self):
        channels = manifest(DEFAULT_ROLES)
        self.assertEqual(channels["channels"]["M8"]["pin"], "PC9")
        self.assertEqual(channels["channels"]["M7"]["pin"], "PC8")
        pins = {p["pin"]: p for p in channels["pins"]}
        self.assertEqual(pins["PC7"]["availability"], "reserved")
        self.assertEqual(pins["PC6"]["availability"], "assignable")


if __name__ == "__main__":
    unittest.main()
