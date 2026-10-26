"""Buffer-aware job streaming (#18) against a simulated Marlin.

The simulation models the SKR's real limits: a 256-byte serial RX buffer
and BUFSIZE 8 command slots. Marlin answers "ok" when a line moves from
the RX buffer into a command slot; the planner frees one slot per tick.
An overflowing RX buffer or an ok without a sent line fails the test.
No motor or laser is involved.
"""
import sys
import time
import unittest
from collections import deque
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pi400"))
from marlin import transport
from marlin.transport import MarlinCommandError, MarlinTransport, normalize

RX_BUFFER = 256
BUFSIZE = 8


class SimMarlin:
    def __init__(self, errors=(), execute_every=2, advanced_ok=False):
        self.rx = b""
        self.slots = deque()
        self.out = deque()
        self.received = []          # every complete line Marlin parsed
        self.errors = set(errors)   # line texts answered with Error:
        self.execute_every = execute_every
        self.advanced_ok = advanced_ok
        self.ticks = 0
        self.max_rx = 0
        self.max_unacked = 0
        self.writes = []

    def write(self, raw):
        self.writes.append(raw)
        self.rx += raw
        self.max_rx = max(self.max_rx, len(self.rx))
        assert len(self.rx) <= RX_BUFFER, "Marlin RX-Puffer übergelaufen"
        self._parse()
        return len(raw)

    def _parse(self):
        while b"\n" in self.rx and len(self.slots) < BUFSIZE:
            line, self.rx = self.rx.split(b"\n", 1)
            text = line.decode("ascii")
            self.received.append(text)
            self.slots.append(text)
            if text in self.errors:
                self.out.append("echo:Unknown command: \"%s\"" % text)
                self.out.append("Error:simulated reject")
            if text == "M114":
                self.out.append("X:50.00 Y:50.00 Z:10.00 E:0.00 Count X:0 Y:0 Z:0")
            self.out.append("ok P%d B%d" % (16, BUFSIZE - len(self.slots))
                            if self.advanced_ok else "ok")

    def readline(self):
        self.ticks += 1
        if self.slots and self.ticks % self.execute_every == 0:
            self.slots.popleft()  # planner finished one block
            self._parse()
        if self.out:
            return (self.out.popleft() + "\n").encode("ascii")
        if not self.slots and not self.rx:
            time.sleep(0.001)
        return b""

    def reset_input_buffer(self):
        pass

    def close(self):
        pass


class Probe(SimMarlin):
    """Counts lines the Pi has written but Marlin has not yet acked."""

    def __init__(self, bridge_ref, **kw):
        super().__init__(**kw)
        self.bridge_ref = bridge_ref
        self.max_inflight = 0
        self.max_inflight_bytes = 0

    def write(self, raw):
        result = super().write(raw)
        bridge = self.bridge_ref[0]
        # inflight is updated right after write(); +1 for this line.
        self.max_inflight = max(self.max_inflight, len(bridge.inflight) + 1)
        self.max_inflight_bytes = max(self.max_inflight_bytes,
                                      sum(bridge.inflight) + len(raw))
        return result


def ready_bridge(serial):
    bridge = MarlinTransport("/dev/null")
    bridge.serial = serial
    bridge.identity = "FIRMWARE_NAME:Marlin MACHINE_TYPE:LumaCut CNC"
    bridge.homing_verified = True
    bridge.homed = True
    bridge.surface_z = 3.0
    bridge.focused_this_job = True
    bridge.fan_power = True
    bridge.last_xy_commanded = (50.0, 50.0)
    return bridge


def raster(rows=40, width=80, step=0.1, x0=40.0, y0=40.0):
    lines = []
    for r in range(rows):
        y = y0 + r * step
        a, b = (x0, x0 + width) if r % 2 == 0 else (x0 + width, x0)
        lines.append("G0 X%.2f Y%.2f" % (a, y))
        for k in range(1, 9):
            lines.append("G1 X%.2f S%d F6000" % (a + (b - a) * k / 8, (r * 17 + k * 29) % 256))
    return lines


class StreamingTests(unittest.TestCase):
    def run_job(self, lines, sim=None, **kw):
        ref = [None]
        sim = sim or Probe(ref, **kw)
        sim.bridge_ref = ref
        bridge = ready_bridge(sim)
        ref[0] = bridge
        bridge.command("M5 I", owner="job")
        bridge.command("M3 I", owner="job")
        for line in lines:
            bridge.stream_command(line, owner="job")
        bridge.drain(owner="job")
        bridge.command("M5 I", owner="job")
        return bridge, sim

    def test_window_respects_marlin_buffers_and_keeps_order(self):
        lines = raster()
        bridge, sim = self.run_job(lines, execute_every=3)
        sent = [normalize(l) + (" F9000" if l.startswith("G0") else "") for l in lines]
        self.assertEqual(sim.received, ["M5 I", "M3 I"] + sent + ["M5 I"])
        self.assertLessEqual(sim.max_inflight, transport.STREAM_MAX_LINES)
        self.assertLessEqual(sim.max_inflight_bytes, transport.STREAM_MAX_BYTES)
        self.assertGreater(sim.max_inflight, 1, "nicht gestreamt")
        self.assertLessEqual(sim.max_rx, RX_BUFFER)
        self.assertEqual(len(bridge.inflight), 0)
        self.assertEqual(bridge.commands, len(sim.received))
        self.assertEqual(bridge.streamed, len(lines))
        self.assertFalse(bridge.laser_enabled)

    def test_advanced_ok_and_slow_planner_count_the_same(self):
        for every in (1, 5, 11):
            with self.subTest(execute_every=every):
                bridge, sim = self.run_job(raster(rows=6), execute_every=every,
                                           advanced_ok=True)
                self.assertEqual(len(bridge.inflight), 0)
                self.assertEqual(bridge.commands, len(sim.received))

    def test_window_one_is_strict_ping_pong(self):
        ref = [None]
        sim = Probe(ref)
        bridge = ready_bridge(sim)
        ref[0] = bridge
        bridge.stream_window = 1
        bridge.command("M3 I", owner="job")
        for line in raster(rows=3):
            bridge.stream_command(line, owner="job")
        self.assertEqual(sim.max_inflight, 1)
        self.assertEqual(bridge.streamed, 0)

    def test_guard_holds_on_streamed_lines(self):
        bad_lines = [
            ("G0 X60 Y60 S50", "G0 darf keine"),
            ("G1 X60 S300", "0..255"),
            ("G1 X60 Y60 S10 M3", "Nur|nur|Pro Zeile|freigegeben"),
            ("G1 X60 Y10 S10", "Sperrzone"),
            ("G1 X" + "1" * 95, "96"),
            ("G92 X0", "freigegeben"),
        ]
        for bad, message in bad_lines:
            with self.subTest(line=bad):
                ref = [None]
                sim = Probe(ref, execute_every=50)
                bridge = ready_bridge(sim)
                ref[0] = bridge
                bridge.command("M3 I", owner="job")
                for line in ["G0 X40 Y40", "G1 X50 S20", "G1 X55 S20"]:
                    bridge.stream_command(line, owner="job")
                self.assertGreater(len(bridge.inflight), 0)
                with self.assertRaisesRegex(ValueError, message):
                    bridge.stream_command(bad, owner="job")
                # The rejected line never reached Marlin.
                self.assertNotIn(normalize(bad), sim.received)
                self.assertFalse(any(normalize(bad).encode() in w for w in sim.writes))
                # The controlled stop drains first, then switches off.
                bridge.command("M5 I", owner="job")
                self.assertEqual(sim.received[-1], "M5 I")
                self.assertEqual(len(bridge.inflight), 0)

    def test_first_cut_after_rapid_needs_power_when_streamed(self):
        ref = [None]
        sim = Probe(ref)
        bridge = ready_bridge(sim)
        ref[0] = bridge
        bridge.command("M3 I", owner="job")
        bridge.stream_command("G1 X60 S20", owner="job")
        bridge.stream_command("G0 X70 Y60", owner="job")
        with self.assertRaisesRegex(ValueError, "nach G0"):
            bridge.stream_command("G1 X80", owner="job")

    def test_marlin_error_stops_sending_and_raises(self):
        lines = raster(rows=4)
        bad = normalize(lines[5])
        ref = [None]
        sim = Probe(ref, errors={bad}, execute_every=4)
        bridge = ready_bridge(sim)
        ref[0] = bridge
        bridge.command("M3 I", owner="job")
        sent_after_error = None
        with self.assertRaises(MarlinCommandError):
            for i, line in enumerate(lines):
                bridge.stream_command(line, owner="job")
                if bridge.stream_error and sent_after_error is None:
                    sent_after_error = len(sim.received)
            bridge.drain(owner="job")
        # At most the lines already in the window follow the bad one.
        index = sim.received.index(bad)
        self.assertLessEqual(len(sim.received) - 1 - index, transport.STREAM_MAX_LINES)
        self.assertEqual(len(bridge.inflight), 0)
        self.assertEqual(bridge.stream_error, "")
        # The link stays usable for the controlled stop.
        bridge.command("M5 I", owner="job")
        self.assertEqual(sim.received[-1], "M5 I")
        self.assertIsNotNone(bridge.serial)

    def test_non_plain_lines_drain_first(self):
        ref = [None]
        sim = Probe(ref, execute_every=7)
        bridge = ready_bridge(sim)
        ref[0] = bridge
        bridge.focused_this_job = False
        bridge.command("M3 I", owner="job")
        bridge.stream_command("G0 X40 Y40", owner="job")
        bridge.stream_command("G0 X45 Y40", owner="job")
        self.assertEqual(len(bridge.inflight), 2)
        # First powered G1 needs focus (M400 + Z): drained, then one by one.
        bridge.stream_command("G1 X60 S20", owner="job")
        self.assertEqual(len(bridge.inflight), 0)
        self.assertIn("G0 Z8.500 F600", sim.received)
        self.assertLess(sim.received.index("G0 X45 Y40 F9000"),
                        sim.received.index("M400"))
        self.assertTrue(bridge.focused_this_job)
        # Now plain cuts stream again.
        bridge.stream_command("G1 X70 S20", owner="job")
        bridge.stream_command("G1 X80 S20", owner="job")
        self.assertGreaterEqual(len(bridge.inflight), 1)
        # Relative mode is never streamed.
        bridge.stream_command("G91", owner="job")
        self.assertEqual(len(bridge.inflight), 0)
        bridge.stream_command("G1 X1 S20", owner="job")
        self.assertEqual(len(bridge.inflight), 0)
        bridge.stream_command("G90", owner="job")
        bridge.stream_command("M5 I", owner="job")
        self.assertFalse(bridge.laser_enabled)

    def test_focus_compensated_z_streams_and_z_lock_holds(self):
        ref = [None]
        sim = Probe(ref, execute_every=50)
        bridge = ready_bridge(sim)
        ref[0] = bridge
        bridge.command("M3 I", owner="job")
        bridge.stream_command("G1 X60 Z9 S20", owner="job")
        bridge.stream_command("G1 X62 Z9.1 S20", owner="job")
        self.assertEqual(len(bridge.inflight), 2)
        # Surface 3 mm + 2 mm probe clearance: Z4 is refused unsent.
        with self.assertRaisesRegex(ValueError, "Z-Sperre"):
            bridge.stream_command("G1 X64 Z4 S20", owner="job")
        self.assertNotIn("G1 X64 Z4 S20", sim.received)

    def test_unknown_start_point_is_queried_not_streamed(self):
        ref = [None]
        sim = Probe(ref)
        bridge = ready_bridge(sim)
        ref[0] = bridge
        bridge.last_xy_commanded = None
        bridge.command("M3 I", owner="job")
        bridge.stream_command("G1 X60 Y50 S20", owner="job")
        self.assertIn("M114", sim.received)
        self.assertEqual(len(bridge.inflight), 0)
        self.assertEqual(bridge.last_xy_commanded, (60.0, 50.0))

    def test_timeout_closes_link_and_clears_window(self):
        class Silent(SimMarlin):
            def readline(self):
                time.sleep(0.001)
                return b""
        sim = Silent()
        bridge = ready_bridge(sim)
        bridge.stream_command("G0 X40 Y40", owner="job", timeout=0.05)
        with self.assertRaises(TimeoutError):
            bridge.drain(owner="job", timeout=0.05)
        self.assertIsNone(bridge.serial)
        self.assertEqual(len(bridge.inflight), 0)

    def test_window_setting_is_clamped(self):
        self.assertEqual(transport._stream_window_setting("1"), 1)
        self.assertEqual(transport._stream_window_setting("99"), 8)
        self.assertEqual(transport._stream_window_setting("abc"), 4)
        self.assertEqual(transport._stream_window_setting(None), 4)
        self.assertEqual(transport.STREAM_MAX_LINES, 4)

    def test_emergency_latch_blocks_further_streaming(self):
        ref = [None]
        sim = Probe(ref, execute_every=50)
        bridge = ready_bridge(sim)
        ref[0] = bridge
        bridge.stream_command("G0 X40 Y40", owner="job")
        bridge.emergency_stop()
        self.assertEqual(sim.writes[-1], b"M112\n")
        with self.assertRaisesRegex(RuntimeError, "M112"):
            bridge.stream_command("G0 X41 Y40", owner="job")


if __name__ == "__main__":
    unittest.main()
