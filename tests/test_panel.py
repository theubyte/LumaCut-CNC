import json
import tempfile
import threading
import unittest
from pathlib import Path

from pi400.marlin import panel


class FakeApi:
    """The Pi's HTTP API as far as the panel bridge uses it."""

    def __init__(self, status=None):
        self.calls = []
        self.status = status or {"connected": True, "origin": {"placement": None}}
        self.answer = (200, {"message": "ok"})

    def json(self, method, path, form=None, timeout=15):
        self.calls.append((method, path, dict(form or {})))
        if path == "/api/status":
            return 200, self.status
        if path == "/api/jobs":
            return 200, {"files": [{"name": "a.gcode", "bytes": 2048, "modified": 1}]}
        if path.endswith("/geometry"):
            return 200, {"bounds": {"xmin": 40, "ymin": 50, "xmax": 120, "ymax": 90}}
        return self.answer

    def call(self, method, path, form=None, timeout=15):
        self.calls.append((method, path, dict(form or {})))
        if "/content" in path:
            return 200, b"G0 X40 Y50\nM3 I\nG1 X50 S128 F1500\nG1 X60\nG1 X70 S255 F900\nM5\n", "text/plain"
        return 404, b"{}", "application/json"


class FakePort:
    def __init__(self):
        self.out = b""

    def write(self, data):
        self.out += data

    def messages(self):
        return [json.loads(line) for line in self.out.decode().splitlines() if line.startswith("{")]


def bridge(api=None):
    b = panel.PanelBridge(api or FakeApi())
    b.port = FakePort()
    return b


def wait_for_answer(b, count=1):
    for _ in range(200):
        if len([m for m in b.port.messages() if m["t"] == "res"]) >= count:
            return
        threading.Event().wait(0.01)
    raise AssertionError("no answer from the bridge")


class PanelActionTest(unittest.TestCase):
    def test_jog_goes_through_the_pi_api(self):
        b = bridge()
        b.handle_line(json.dumps({"t": "act", "id": 7, "op": "jog", "axis": "X", "distance": 10}).encode())
        wait_for_answer(b)
        self.assertIn(("POST", "/api/action", {"op": "jog", "axis": "X", "distance": "10"}), b.api.calls)
        self.assertEqual(b.port.messages()[-1], {"t": "res", "id": 7, "op": "jog", "ok": True, "msg": "ok"})

    def test_unknown_operation_is_refused_without_calling_the_pi(self):
        b = bridge()
        b.handle_line(b'{"t":"act","id":1,"op":"service_fire"}')
        self.assertEqual(b.api.calls, [])
        self.assertFalse(b.port.messages()[-1]["ok"])

    def test_extra_fields_are_dropped(self):
        b = bridge()
        b.handle_line(b'{"t":"act","id":2,"op":"home","clear":"1","gcode":"M3 S255"}')
        wait_for_answer(b)
        self.assertIn(("POST", "/api/action", {"op": "home", "clear": "1"}), b.api.calls)

    def test_pi_error_text_reaches_the_panel(self):
        api = FakeApi()
        api.answer = (400, {"error": "Marlin muss zuerst referenziert werden"})
        b = bridge(api)
        b.handle_line(b'{"t":"act","id":3,"op":"jog","axis":"Y","distance":"1"}')
        wait_for_answer(b)
        res = b.port.messages()[-1]
        self.assertFalse(res["ok"])
        self.assertEqual(res["msg"], "Marlin muss zuerst referenziert werden")

    def test_second_action_while_one_runs_is_refused(self):
        b = bridge()
        b.busy.acquire()
        b.handle_line(b'{"t":"act","id":4,"op":"park"}')
        self.assertEqual(b.port.messages()[-1]["msg"], "Vorherige Aktion läuft noch")

    def test_stop_is_never_blocked_by_a_running_action(self):
        b = bridge()
        b.busy.acquire()
        b.handle_line(b'{"t":"act","id":5,"op":"estop"}')
        wait_for_answer(b)
        self.assertIn(("POST", "/api/action", {"op": "estop"}), b.api.calls)

    def test_autorun_uses_the_placement_of_that_file(self):
        api = FakeApi({"origin": {"placement": {"file": "a.gcode"}}})
        b = bridge(api)
        b.handle_line(b'{"t":"act","id":6,"op":"autorun","name":"a.gcode"}')
        wait_for_answer(b)
        self.assertIn(("POST", "/api/action", {"op": "autorun", "name": "a.gcode", "placement": "1"}), api.calls)

    def test_frame_job_sends_a_laser_off_rectangle(self):
        b = bridge()
        b.handle_line(b'{"t":"act","id":8,"op":"frame_job","name":"a.gcode"}')
        wait_for_answer(b)
        form = [c[2] for c in b.api.calls if c[2].get("op") == "frame"][0]
        self.assertEqual(form["mode"], "box")
        self.assertNotIn("S", form["gcode"].replace("G0", ""))
        self.assertIn("G0 X120.0 Y90.0", form["gcode"])

    def test_job_list_is_sent(self):
        b = bridge()
        b.handle_line(b'{"t":"jobs"}')
        self.assertEqual(b.port.messages()[-1], {"t": "jobs", "files": [{"name": "a.gcode", "kb": 2}]})

    def test_noise_on_the_line_is_ignored(self):
        b = bridge()
        for raw in (b"M115", b"ESP-ROM:esp32s3-20210327", b"\xff\xfe", b"[1,2]"):
            b.handle_line(raw)
        self.assertEqual(b.port.out, b"")

    def test_ping_switches_the_camera(self):
        b = bridge()
        b.handle_line(b'{"t":"ping","cam":1}')
        self.assertGreater(b.camera_wanted, 0)
        b.handle_line(b'{"t":"ping","cam":0}')
        self.assertEqual(b.camera_wanted, 0)

    def test_image_is_sent_as_header_and_bytes(self):
        b = bridge()
        b.send({"t": "img", "w": 2, "h": 1, "len": 3}, b"\xff\xd8\x00")
        self.assertTrue(b.port.out.endswith(b'"len":3}\n\xff\xd8\x00'))


class CompactStatusTest(unittest.TestCase):
    STATUS = {
        "connected": True, "owner": "job", "homed": True, "emergency_latched": False,
        "laser_armed": True, "laser_cooling_fan_on": True, "exhaust": True, "lights": False,
        "position": [10.0, 20.0, 7.0], "activity": "job", "home_needs_confirm": False,
        "config": {"validated": True}, "job": {"file": "a.gcode", "state": "running", "phase": "running",
                                               "line": 50, "total": 100, "error": "", "probe": None},
        "queue": {"state": "idle"}, "frame": {"state": "idle"},
    }

    def test_fields_and_remaining_time(self):
        track = {}
        panel.compact(self.STATUS, 100.0, "14:32", track, None)
        msg = panel.compact(self.STATUS, 160.0, "14:33", track, None)
        self.assertEqual(msg["elapsed"], 60)
        self.assertEqual(msg["remain"], 60)
        self.assertTrue(msg["armed"])
        self.assertEqual(msg["job"]["file"], "a.gcode")
        self.assertEqual(msg["time"], "14:33")

    def test_idle_has_no_times(self):
        msg = panel.compact({"job": {"state": "complete"}}, 5.0, "10:00", {}, None)
        self.assertIsNone(msg["elapsed"])
        self.assertIsNone(msg["remain"])
        self.assertEqual(msg["owner"], "Frei")

    def test_power_and_feed_from_the_job_file(self):
        trace = panel.JobTrace("G0 X1\nG1 X2 S128 F1500\nG1 X3\nG1 X4 S255 F900\nM5\n")
        self.assertEqual(trace.at(3, 5), (128.0, 1500.0))
        self.assertEqual(trace.at(4, 5), (255.0, 900.0))
        self.assertEqual(trace.at(5, 5), (0.0, 900.0))
        msg = panel.compact(self.STATUS, 1.0, "", {}, trace)
        self.assertEqual(msg["power"], 50)     # line 50 of 100 -> file line 2/3 -> S128 = 50 %


class PortTest(unittest.TestCase):
    def make_tty(self, root, name, vid):
        dev = root / "sys" / "devices" / "usb1" / name
        (dev / "1-1:1.0" / "tty" / name).mkdir(parents=True)
        (dev / "idVendor").write_text(vid + "\n")
        tty = root / "sys" / "class" / "tty"
        tty.mkdir(parents=True, exist_ok=True)
        (tty / name).mkdir()
        (tty / name / "device").symlink_to(dev / "1-1:1.0")
        (root / "dev").mkdir(exist_ok=True)
        (root / "dev" / name).write_text("")

    def test_panel_is_found_by_its_vendor_and_the_skr_is_not(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            try:
                self.make_tty(root, "ttyACM0", "303a")
                self.make_tty(root, "ttyACM1", "1eaf")
            except OSError:
                self.skipTest("no symlinks on this system")
            self.assertEqual(panel.find_panel(root / "dev", root / "sys"), str(root / "dev" / "ttyACM0"))
            self.assertTrue(panel.is_panel(str(root / "dev" / "ttyACM0"), root / "sys"))
            self.assertFalse(panel.is_panel(str(root / "dev" / "ttyACM1"), root / "sys"))

    def test_by_id_name_marks_the_panel(self):
        self.assertTrue(panel.is_panel("/dev/serial/by-id/usb-Espressif_USB_JTAG_serial_debug_unit_AA:BB-if00"))
        self.assertFalse(panel.is_panel("/dev/serial/by-id/usb-LeafLabs_Maple-if00"))


if __name__ == "__main__":
    unittest.main()
