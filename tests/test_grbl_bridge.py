import threading
import time
import unittest

from pi400.marlin.grbl_bridge import GrblMarlinBridge
from pi400.marlin.transport import MarlinTransport


class FakeGrbl:
    """Grbl 1.1 answering $$, ?, $H and buffered lines; homes X and Y to +."""

    def __init__(self, homing_dir_mask=0):
        self.lock = threading.Lock()
        self.rx = b"Grbl 1.1h ['$' for help]\r\n"
        self.written = []
        self.settings = {23: homing_dir_mask, 30: 1000, 32: 1}
        self.pos = [0.0, 0.0]
        self.wco = [0.0, 0.0]
        self.relative = False

    def write(self, data):
        with self.lock:
            for byte in (b"?", b"!", b"\x18"):
                if data == byte:
                    self.written.append(data.decode("latin1"))
                    if data == b"?":
                        self.rx += ("<Idle|MPos:%.3f,%.3f,0.000|FS:0,0|WCO:%.3f,%.3f,0.000>\r\n"
                                    % (self.pos[0], self.pos[1], self.wco[0], self.wco[1])).encode()
                    return len(data)
            for line in data.decode().splitlines():
                line = line.strip()
                if not line:
                    continue
                self.written.append(line)
                if line == "$$":
                    for k, v in self.settings.items():
                        self.rx += b"$%d=%d\r\n" % (k, v)
                elif line == "$H":
                    self.pos = [0.0, 0.0]
                elif line.startswith("G10 L20"):
                    self.wco = list(self.pos)
                elif line.startswith(("G0", "G1")):
                    for axis, i in (("X", 0), ("Y", 1)):
                        if axis in line:
                            v = float(line.split(axis)[1].split()[0])
                            self.pos[i] = self.wco[i] + v
                self.rx += b"ok\r\n"
        return len(data)

    def read(self, n):
        with self.lock:
            out, self.rx = self.rx[:n], self.rx[n:]
        if not out:
            time.sleep(0.01)
        return out

    def close(self):
        pass


class GrblBridgeTest(unittest.TestCase):
    def make(self, mask=0, hint=None):
        grbl = FakeGrbl(mask)
        bridge = GrblMarlinBridge("/dev/fake", serial_port=grbl, surface_hint=hint)
        self.addCleanup(bridge.close)
        return grbl, bridge

    def ask(self, bridge, line, timeout=5.0):
        bridge.write((line + "\n").encode())
        lines, end = [], time.monotonic() + timeout
        while time.monotonic() < end:
            got = bridge.readline().decode().strip()
            if got:
                lines.append(got)
                if got.startswith("ok"):
                    return lines
        raise AssertionError("no ok for " + line + ": " + repr(lines))

    def test_identity_passes_the_gateway_check(self):
        _, bridge = self.make()
        reply = self.ask(bridge, "M115")
        self.assertIn("FIRMWARE_NAME:Marlin", reply[0])
        self.assertIn("LumaCut CNC", reply[0])
        self.assertIn("Cap:Z_PROBE:1", reply)

    def test_moves_mirror_axes_homing_to_plus_and_scale_power(self):
        grbl, bridge = self.make(mask=0)
        self.ask(bridge, "G28 X Y R0")
        self.ask(bridge, "M3 I")
        self.ask(bridge, "G1 X100 Y50 F3000 S127.5")
        self.assertIn("$H", grbl.written)
        self.assertIn("M4 S0", grbl.written)
        self.assertIn("G1 X-100.000 Y-50.000 F3000 S500", grbl.written)
        pos = self.ask(bridge, "M114")[0]
        self.assertTrue(pos.startswith("X:100.00 Y:50.00 Z:0.00"), pos)

    def test_axes_homing_to_minus_stay_and_arcs_keep_direction(self):
        grbl, bridge = self.make(mask=3)
        self.ask(bridge, "G2 X10 Y10 I5 J0 F600 S10")
        self.assertIn("G2 X10.000 Y10.000 I5.000 J0.000 F600 S39.2", grbl.written)

    def test_one_mirrored_axis_swaps_arc_direction(self):
        grbl, bridge = self.make(mask=2)
        self.ask(bridge, "G2 X10 Y10 I5 J0 F600")
        self.assertIn("G3 X-10.000 Y10.000 I-5.000 J0.000 F600", grbl.written)

    def test_z_is_remembered_but_never_sent(self):
        grbl, bridge = self.make(hint=lambda: 2.7)
        self.ask(bridge, "G28 Z")
        self.ask(bridge, "G0 Z20 F600")
        self.assertFalse(any("Z" in w for w in grbl.written if w.startswith("G")))
        self.assertIn("Z:20.00", self.ask(bridge, "M114")[0])
        probe = self.ask(bridge, "G30 E0")
        self.assertTrue(any(line.startswith("Bed X:") and "Z: 2.70" in line for line in probe))

    def test_refuses_grbl_without_laser_mode(self):
        grbl = FakeGrbl(0)
        grbl.settings[32] = 0
        with self.assertRaises(ConnectionError):
            GrblMarlinBridge("/dev/fake", serial_port=grbl)

    def test_dwell_milliseconds_become_seconds(self):
        grbl, bridge = self.make()
        self.ask(bridge, "G4 P800")
        self.assertIn("G4 P0.800", grbl.written)

    def test_emergency_stop_holds_and_resets(self):
        grbl, bridge = self.make()
        bridge.write(b"M112\n")
        self.assertEqual(grbl.written[-2:], ["!", "\x18"])

    def test_gateway_connects_through_the_bridge(self):
        grbl = FakeGrbl(0)
        machine = MarlinTransport("/dev/fake", serial_factory=lambda port, baud, timeout=0.1:
                                  GrblMarlinBridge(port, serial_port=grbl))
        machine.ensure_ready()
        self.addCleanup(lambda: machine._close_locked())
        self.assertTrue(machine.status()["connected"])
        machine.homing_verified = True
        machine.safe_home(operator_clear=True)
        self.assertTrue(machine.homed)
        self.assertIn("$H", grbl.written)


if __name__ == "__main__":
    unittest.main()
