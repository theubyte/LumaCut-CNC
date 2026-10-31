import threading
import time
import unittest

from pi400.marlin.grbl_bridge import GrblMarlinBridge, merge_short_moves
from pi400.marlin.transport import MarlinTransport


class FakeGrbl:
    """Grbl 1.1 answering $$, ?, $H and buffered lines; homes X and Y to +."""

    def __init__(self, homing_dir_mask=0, state="Idle"):
        self.lock = threading.Lock()
        self.state = state
        self.rx = b"Grbl 1.1h ['$' for help]\r\n"
        self.written = []
        self.settings = {23: homing_dir_mask, 30: 1000, 32: 1}
        self.pos = [0.0, 0.0]
        self.wco = [0.0, 0.0]
        self.relative = False
        self.drop_oks = 0
        self.deaf = False

    def write(self, data):
        with self.lock:
            for byte in (b"?", b"!", b"\x18", b"~"):
                if data == byte:
                    self.written.append(data.decode("latin1"))
                    if data == b"~" and self.state == "Door":
                        self.state = "Idle"
                    if data == b"?":
                        self.rx += ("<" + self.state + "|MPos:%.3f,%.3f,0.000|FS:0,0|WCO:%.3f,%.3f,0.000>\r\n"
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
                if self.drop_oks:
                    self.drop_oks -= 1       # lost on the USB link
                    continue
                self.rx += b"ok\r\n"
        return len(data)

    def read(self, n):
        with self.lock:
            if self.deaf:                    # CH340 after "urb stopped": nothing arrives
                self.rx = b""
                out = b""
            else:
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

    def test_resumes_from_door_state_after_boot(self):
        grbl = FakeGrbl(3, state="Door")
        bridge = GrblMarlinBridge("/dev/fake", serial_port=grbl)
        self.addCleanup(bridge.close)
        self.assertIn("~", grbl.written)
        self.assertEqual(bridge.state, "Idle")

    def test_feed_is_capped_at_the_board_maximum(self):
        grbl, bridge = self.make(mask=3)
        grbl.settings.update({110: 6000, 111: 6000})
        bridge.settings.update({110: 6000.0, 111: 6000.0})
        self.ask(bridge, "G1 X10 Y10 F10199 S35")
        self.assertIn("G1 X10.000 Y10.000 F6000 S137.3", grbl.written)

    def test_lost_ok_is_acknowledged_once_grbl_is_idle(self):
        grbl, bridge = self.make(mask=3)
        grbl.drop_oks = 1
        reply = self.ask(bridge, "G1 X10 Y10 F600 S10", timeout=10.0)
        self.assertEqual(reply[-1], "ok")

    def test_deaf_link_is_reopened(self):
        grbl = FakeGrbl(3)
        opened = []

        def opener():
            grbl.deaf = False
            opened.append(1)
            return grbl
        bridge = GrblMarlinBridge("/dev/fake", serial_port=grbl, opener=opener)
        self.addCleanup(bridge.close)
        grbl.deaf = True
        reply = self.ask(bridge, "G1 X10 Y10 F600 S10", timeout=15.0)
        self.assertEqual(reply[-1], "ok")
        self.assertEqual(bridge.reopens, 1)

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
        # the board's own limits (no $110/$120 in the fake: Grbl defaults)
        self.assertEqual(machine.controller_motion(), (1000.0, 100.0))
        # deeper streaming window than the SKR's 4 lines (smooth arcs)
        self.assertEqual(machine.stream_window, 16)


class MergeShortMovesTest(unittest.TestCase):
    def circle(self, r=7.5, n=275, cx=160.0, cy=174.0):
        import math
        pts = [(cx + r * math.cos(2 * math.pi * i / n), cy + r * math.sin(2 * math.pi * i / n))
               for i in range(n + 1)]
        lines = ["G90", "G0 X%.3f Y%.3f" % pts[0]]
        lines += ["G1 X%.3f Y%.3f F4402 S187" % p for p in pts[1:]]
        return pts, lines

    def test_fine_circle_is_merged_within_tolerance(self):
        pts, lines = self.circle()
        out = merge_short_moves(lines)
        moves = [l for l in out if l.startswith("G1")]
        self.assertLess(len(moves), 80)
        self.assertGreater(len(moves), 40)
        self.assertEqual(out[-1], lines[-1])      # ends exactly where the circle ends
        # every original point stays within 0.01 mm of the merged path
        from pi400.marlin.grbl_bridge import _off_chord
        path = [pts[0]] + [tuple(float(w[1:]) for w in l.split()[1:3]) for l in moves]
        for p in pts:
            self.assertLess(min(_off_chord(p, a, b) for a, b in zip(path, path[1:])), 0.0105)

    def test_power_change_z_and_relative_mode_are_kept(self):
        lines = ["G90", "G0 X0 Y0", "G1 X0.1 Y0 F1000 S100", "G1 X0.2 Y0 F1000 S50",
                 "G1 X0.3 Y0 Z2 F1000 S50", "G91", "G1 X0.1 Y0 F1000 S50", "G1 X0.1 Y0 F1000 S50"]
        self.assertEqual(merge_short_moves(lines), lines)

    def test_straight_run_is_joined_up_to_max_length(self):
        lines = ["G0 X0 Y0"] + ["G1 X%.1f Y0 F1000 S100" % (0.5 * i) for i in range(1, 11)]
        out = merge_short_moves(lines)
        self.assertEqual(out, ["G0 X0 Y0", "G1 X3.0 Y0 F1000 S100", "G1 X5.0 Y0 F1000 S100"])


if __name__ == "__main__":
    unittest.main()
