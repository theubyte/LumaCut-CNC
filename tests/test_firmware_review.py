"""Pi side of the review findings on the own firmware: no motors, no laser."""
import queue
import sys
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pi400"))
from marlin.transport import MarlinCommandError, MarlinTransport


class ScriptedSerial:
    """The test decides when the firmware answers, like a real slow M400."""

    def __init__(self):
        self.lines = queue.Queue()
        self.writes = []

    def write(self, raw):
        self.writes.append(raw.decode().strip())
        return len(raw)

    def readline(self):
        try:
            return (self.lines.get(timeout=0.005) + "\n").encode()
        except queue.Empty:
            return b""

    def answer(self, *lines):
        for line in lines:
            self.lines.put(line)

    def reset_input_buffer(self):
        pass

    def close(self):
        pass


class AutoSerial(ScriptedSerial):
    """Answers every line with ok; chosen commands with an error first."""

    def __init__(self, errors=None):
        super().__init__()
        self.errors = errors or {}

    def write(self, raw):
        super().write(raw)
        cmd = raw.decode().strip()
        for start, text in self.errors.items():
            if cmd.startswith(start):
                self.answer(text)
        self.answer("ok P127 B16")
        return len(raw)


def machine(serial):
    ctrl = MarlinTransport("/dev/null")
    ctrl.serial = serial
    ctrl.identity = "FIRMWARE_NAME:LumaCut CNC 0.1 MACHINE_TYPE:LumaCut CNC"
    ctrl.job_chime_enabled = False
    return ctrl


def wait_until(check, seconds=2.0):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if check():
            return True
        time.sleep(0.002)
    return False


class QuickStopTests(unittest.TestCase):
    def start_waiting_command(self, ctrl, cmd):
        result = {}

        def run():
            with ctrl.lock:
                try:
                    result["lines"] = ctrl._exchange_locked(cmd, timeout=5)
                except MarlinCommandError as exc:
                    result["error"] = exc

        thread = threading.Thread(target=run)
        thread.start()
        self.assertTrue(wait_until(lambda: cmd in ctrl.serial.writes))
        return thread, result

    def quick_stop_while_waiting(self, ctrl):
        stopper = threading.Thread(target=ctrl.quick_stop, kwargs={"owner": "web"})
        stopper.start()
        # On the wire although the lock is still held by the waiting command.
        self.assertTrue(wait_until(lambda: "M410" in ctrl.serial.writes),
                        "M410 waited for the command lock")
        self.assertEqual(ctrl.serial.writes.count("M410"), 1)
        return stopper

    def test_m410_overtakes_a_waiting_m400_and_the_oks_stay_right(self):
        serial = ScriptedSerial()
        ctrl = machine(serial)
        waiter, result = self.start_waiting_command(ctrl, "M400")
        stopper = self.quick_stop_while_waiting(ctrl)
        time.sleep(0.05)
        self.assertNotIn("lines", result)  # one ok is not yet the answer to M400
        serial.answer("ok P127 B16")       # the M410 line itself
        time.sleep(0.05)
        self.assertNotIn("lines", result)
        serial.answer("ok P127 B16")       # the aborted M400
        waiter.join(2)
        self.assertIn("lines", result)
        # Lock is free now: the second M410 goes out and gets its own ok.
        self.assertTrue(wait_until(lambda: serial.writes.count("M410") == 2))
        serial.answer("ok P127 B16")
        stopper.join(2)
        self.assertFalse(stopper.is_alive())

        # Nothing stale is left: the next command gets its own answer.
        reader = threading.Thread(target=lambda: result.update(m114=ctrl._exchange_locked("M114", timeout=2)))
        reader.start()
        self.assertTrue(wait_until(lambda: "M114" in serial.writes))
        time.sleep(0.03)
        self.assertNotIn("m114", result)
        serial.answer("X:1.000 Y:2.000 Z:3.000 Count X:80 Y:160 Z:3056", "ok P127 B16")
        reader.join(2)
        self.assertIn("X:1.000", result["m114"][0])
        self.assertEqual(ctrl.position, [1.0, 2.0, 3.0])

    def test_m114_answer_is_not_cut_off_by_the_m410_ok(self):
        # The firmware answers M410 on arrival, in front of the running M114.
        serial = ScriptedSerial()
        ctrl = machine(serial)
        waiter, result = self.start_waiting_command(ctrl, "M114")
        stopper = self.quick_stop_while_waiting(ctrl)
        serial.answer("ok P127 B16", "X:1.000 Y:2.000 Z:3.000 Count X:80 Y:160 Z:3056", "ok P127 B16")
        waiter.join(2)
        self.assertTrue(any("X:1.000" in line for line in result["lines"]))
        self.assertTrue(wait_until(lambda: serial.writes.count("M410") == 2))
        serial.answer("ok P127 B16")
        stopper.join(2)

    def test_homing_aborted_by_m410_still_reports_its_error(self):
        serial = ScriptedSerial()
        ctrl = machine(serial)
        waiter, result = self.start_waiting_command(ctrl, "G28 X")
        stopper = self.quick_stop_while_waiting(ctrl)
        serial.answer("ok P127 B16", "Error:Homing failed", "ok P127 B16")
        waiter.join(2)
        self.assertIn("error", result)
        self.assertTrue(wait_until(lambda: serial.writes.count("M410") == 2))
        serial.answer("ok P127 B16")
        stopper.join(2)
        self.assertEqual(ctrl._stray_oks, 0)

    def test_idle_needs_one_m410_only(self):
        ctrl = machine(AutoSerial())
        ctrl.laser_enabled = True
        ctrl.quick_stop(owner="web")
        self.assertEqual(ctrl.serial.writes, ["M410"])
        self.assertFalse(ctrl.laser_enabled)
        self.assertEqual(ctrl._stray_oks, 0)

    def test_owner_is_checked_before_anything_is_written(self):
        ctrl = machine(AutoSerial())
        ctrl.owner = "lightburn"
        with self.assertRaises(RuntimeError):
            ctrl.quick_stop(owner="web")
        self.assertEqual(ctrl.serial.writes, [])

    def test_missing_ok_does_not_hang_or_poison_later_commands(self):
        serial = ScriptedSerial()
        ctrl = machine(serial)
        ctrl._write_m410(serial)
        ctrl._absorb_stray_oks(time.monotonic() + 0.05)
        self.assertEqual(ctrl._stray_oks, 0)


class FirmwareSaidTests(unittest.TestCase):
    def exchange_with_unsolicited(self, line):
        serial = AutoSerial()
        ctrl = machine(serial)
        ctrl.homed = ctrl.z_homed = True
        ctrl.service_power = 120
        serial.answer(line)
        return ctrl

    def test_laser_off_message_clears_the_service_power(self):
        ctrl = self.exchange_with_unsolicited("echo:Laser off: USB silent")
        with ctrl.lock:
            ctrl._exchange_locked("M114", timeout=1)
        self.assertEqual(ctrl.service_power, 0)
        self.assertTrue(ctrl.homed)

    def check_reference_lost(self, line):
        ctrl = self.exchange_with_unsolicited(line)
        ctrl.laser_enabled = True
        with ctrl.lock, self.assertRaises(MarlinCommandError):
            ctrl._exchange_locked("M114", timeout=1)
        self.assertFalse(ctrl.homed or ctrl.z_homed)
        self.assertFalse(ctrl.laser_enabled)
        self.assertTrue(ctrl.reference_lost)

    def test_planner_underrun_loses_the_reference(self):
        self.check_reference_lost("Error:Planner underrun")

    def test_driver_reset_loses_the_reference(self):
        self.check_reference_lost("Error:Driver reset")


class ExpectedSwitchHitTests(unittest.TestCase):
    HIT = "endstops hit: X:0.012"

    def fault(self, inflight=False, laser=False):
        ctrl = machine(AutoSerial())
        ctrl.last_xy_commanded = (0.0, 0.0)
        ctrl.laser_enabled = laser
        if inflight:
            ctrl.inflight.append(10)
        return ctrl._is_fault_locked(self.HIT)

    def test_parking_at_zero_stays_harmless(self):
        self.assertFalse(self.fault())

    def test_with_lines_under_way_it_is_a_fault(self):
        # The firmware threw those lines away, they get a bare ok.
        self.assertTrue(self.fault(inflight=True))

    def test_with_laser_armed_it_is_a_fault(self):
        self.assertTrue(self.fault(laser=True))


class BlindLiftTests(unittest.TestCase):
    """Default clearance 20 mm: lifts of 19..22 mm fit the 25 mm budget."""

    def machine(self, last):
        ctrl = machine(AutoSerial())
        ctrl.z_unhomed_lift = 25.0
        ctrl.last_known_z = last
        return ctrl

    def lift_mm(self, commands):
        return float(commands[1].split()[1][1:]) if commands else 0.0

    def test_default_lifts_fit(self):
        for last, want in ((1.0, 19.0), (0.0, 20.0), (-2.0, 22.0), (60.0, 5.0)):
            with self.subTest(last=last):
                self.assertEqual(self.lift_mm(self.machine(last)._lift_before_home_locked(False)), want)

    def test_thick_material_is_capped_at_the_budget(self):
        ctrl = self.machine(1.0)
        ctrl.material_mm = 15.0  # travel height 35 mm wants 34 mm
        self.assertEqual(self.lift_mm(ctrl._lift_before_home_locked(False)), 25.0)

    def test_a_second_attempt_only_gets_what_is_left(self):
        ctrl = self.machine(1.0)
        self.assertEqual(self.lift_mm(ctrl._lift_before_home_locked(False)), 19.0)
        self.assertEqual(self.lift_mm(ctrl._lift_before_home_locked(False)), 6.0)
        self.assertEqual(ctrl._lift_before_home_locked(False), [])

    def test_refused_lift_does_not_stop_homing(self):
        serial = AutoSerial(errors={"G0 Z19": "Error:Out of bounds"})
        ctrl = machine(serial)
        ctrl.last_known_z = 1.0
        ctrl.homing_verified = True
        ctrl.safe_home(owner="web")
        self.assertIn("G28 X Y R0", serial.writes)
        self.assertIn("G28 Z", serial.writes)
        self.assertEqual(ctrl.blind_lift_used, 0.0)
        self.assertTrue(ctrl.z_homed)

    def test_z_test_fits_and_counts(self):
        ctrl = machine(AutoSerial())
        ctrl.z_unhomed_lift = 25.0
        ctrl.z_test(10.0, owner="web")
        self.assertEqual(ctrl.blind_lift_used, 10.0)
        ctrl.last_known_z = 1.0
        self.assertEqual(self.lift_mm(ctrl._lift_before_home_locked(False)), 15.0)

    def test_m115_gives_the_budget(self):
        serial = AutoSerial()
        ctrl = machine(serial)
        ctrl.serial = None
        ctrl.identity = ""
        replies = ["FIRMWARE_NAME:LumaCut CNC 0.1 (x) MACHINE_TYPE:LumaCut CNC", "Cap:Z_PROBE:1",
                   "Cap:SELF_UPDATE:1", "Cap:Z_UNHOMED_LIFT:25"]
        original = serial.write

        def write(raw):
            if raw.strip() == b"M115":
                serial.answer(*replies)
            return original(raw)

        serial.write = write
        ctrl.serial_factory = lambda *a, **k: serial
        ctrl.ensure_ready()
        self.assertEqual(ctrl.z_unhomed_lift, 25.0)


if __name__ == "__main__":
    unittest.main()
