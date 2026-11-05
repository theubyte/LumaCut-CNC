import json
import re
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
        self.workspace = {"revision": 7, "material": {"name": "MDF", "thickness_mm": 3.0}}
        self.put_answer = (200, {"revision": 8})

    def json(self, method, path, form=None, timeout=15):
        self.calls.append((method, path, dict(form or {})))
        if path == "/api/status":
            return 200, self.status
        if path == "/api/jobs":
            return 200, {"files": [{"name": "a.gcode", "bytes": 2048, "modified": 1}]}
        if path.endswith("/geometry"):
            return 200, {"bounds": {"xmin": 40, "ymin": 50, "xmax": 120, "ymax": 90}}
        if path == "/api/materials":
            return 200, {"revision": 1, "materials": [
                {"name": "MDF", "thickness_mm": 3.0, "process": "Schneiden", "builtin": True},
                {"name": "Leder", "thickness_mm": 2.0, "process": "Gravieren", "builtin": False},
                {"name": "Leder", "thickness_mm": 2.0, "process": "Schneiden", "builtin": True}]}
        if path == "/api/workspace":
            return 200, self.workspace
        return self.answer

    def send_json(self, method, path, body, timeout=15):
        self.calls.append((method, path, dict(body)))
        return self.put_answer

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


def wait_for_kind(b, kind):
    for _ in range(200):
        found = [m for m in b.port.messages() if m["t"] == kind]
        if found:
            return found[-1]
        threading.Event().wait(0.01)
    raise AssertionError("no %s message from the bridge" % kind)


def wait_for_answer(b, count=1):
    for _ in range(200):
        if len([m for m in b.port.messages() if m["t"] == "res"]) >= count:
            return
        threading.Event().wait(0.01)
    raise AssertionError("no answer from the bridge")


class RunEsptoolTest(unittest.TestCase):
    def test_home_points_at_the_data_folder(self):
        # 05.11.: ProtectHome made esptool fail on ~/.config/esptool/esptool.cfg.
        from unittest import mock
        done = mock.Mock(returncode=0, stdout="ok", stderr="")
        with mock.patch.object(panel.subprocess, "run", return_value=done) as run:
            self.assertTrue(panel.run_esptool(["esptool"])[0])
        self.assertEqual(run.call_args.kwargs["env"]["HOME"], str(panel.PYLIB.parent))


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
        self.assertEqual(wait_for_kind(b, "jobs"), {"t": "jobs", "files": [{"name": "a.gcode", "kb": 2}]})

    def test_a_job_name_the_panel_cannot_hold_is_left_out(self):
        api = FakeApi()
        real = api.json
        api.json = lambda m, p, f=None, timeout=15: ((200, {"files": [
            {"name": "x" * 96 + ".gcode", "bytes": 1}, {"name": "ü" * 40 + ".gcode", "bytes": 1}]})
            if p == "/api/jobs" else real(m, p, f, timeout))
        b = bridge(api)
        b.send_jobs()
        self.assertEqual([f["name"] for f in b.port.messages()[-1]["files"]], ["ü" * 40 + ".gcode"])

    def test_long_lists_still_fit_into_one_line(self):
        items = [{"name": "ä" * 90, "kb": 1} for _ in range(60)]
        msg = panel.fit_line("files", items, {"t": "jobs"})
        self.assertLessEqual(len(json.dumps(msg, ensure_ascii=False, separators=(",", ":")).encode()), panel.LINE_LIMIT)
        self.assertGreater(len(msg["files"]), 10)

    def test_a_query_does_not_block_the_line(self):
        api = FakeApi()
        release = threading.Event()
        real = api.json
        api.json = lambda m, p, f=None, timeout=15: (release.wait(5), real(m, p, f, timeout))[1]
        b = bridge(api)
        b.handle_line(b'{"t":"jobs"}')       # waits for the slow Pi in the background
        api.json = real
        b.handle_line(b'{"t":"act","id":9,"op":"estop"}')
        wait_for_answer(b)
        self.assertIn(("POST", "/api/action", {"op": "estop"}), api.calls)
        release.set()

    def test_a_failing_pi_does_not_end_the_session(self):
        api = FakeApi()
        def down(*args, **kwargs):
            raise OSError("connection refused")
        api.json = down
        b = bridge(api)
        b.answer_query("jobs")               # no exception out of it
        self.assertEqual(b.port.out, b"")

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


class PanelLimitsTest(unittest.TestCase):
    """What the panel must never be able to do. Do not loosen this."""

    FORBIDDEN = ("service_laser", "service_supply", "service_password", "service_unlock", "supply_test",
                 "ttl_test", "z_test", "motion_test", "motion_limits", "line_laser", "matcal", "bedmap",
                 "start", "frame", "moveto", "connect", "firmware_update_install", "panel_auto", "gcode")

    def test_allowed_actions_are_exactly_these(self):
        self.assertEqual(panel.ACTIONS, {
            "estop": (), "estop_reset": (), "abort": (), "home": ("clear",), "jog": ("axis", "distance"),
            "probe": (), "park": (), "light": ("on", "brightness"), "exhaust": ("on",),
            "queue_pause": (), "queue_run": (), "autorun": ("name", "clear"), "frame_job": ("name",),
            "material": ("name", "thickness"), "screen_off": ("minutes",), "panel_update": ()})

    def test_service_menu_and_raw_gcode_are_refused_without_calling_the_pi(self):
        for op in self.FORBIDDEN:
            b = bridge()
            b.handle_line(json.dumps({"t": "act", "id": 1, "op": op, "gcode": "M3 S255", "power": "100"}).encode())
            self.assertEqual(b.api.calls, [], op)
            self.assertFalse(b.port.messages()[-1]["ok"], op)

    def test_no_allowed_action_carries_gcode_or_laser_power(self):
        for op, fields in panel.ACTIONS.items():
            for field in ("gcode", "power", "percent", "S"):
                self.assertNotIn(field, fields, op)

    def test_panel_sources_only_use_allowed_actions_and_known_queries(self):
        src = (Path(panel.__file__).resolve().parents[2] / "firmware" / "panel" / "src")
        text = (src / "ui.c").read_text(encoding="utf-8")
        ops = set(re.findall(r'link_act\("(\w+)"', text)) | set(re.findall(r'act_(?:simple|toggle), "(\w+)"', text))
        self.assertTrue({"estop", "autorun", "light"} <= ops)
        self.assertEqual(ops - set(panel.ACTIONS), set())
        for op, rest in re.findall(r'link_act\("(\w+)", ([^;]*?)NULL\)', text):
            keys = re.findall(r'"(\w+)", (?:"[^"]*"|\w+(?:\[\w+\])?), ', rest + " ")
            self.assertLessEqual(set(keys), set(panel.ACTIONS[op]), op)
        queries = set(re.findall(r'link_request\("(\w+)"\)', text))
        self.assertEqual(queries, set(panel.PanelBridge.QUERIES))
        for name in ("service_", "\"gcode\"", "M3 "):
            self.assertNotIn(name, text)

    def test_every_drive_and_laser_action_of_the_panel_goes_through_the_go(self):
        text = (Path(panel.__file__).resolve().parents[2] / "firmware" / "panel" / "src" / "ui.c").read_text(encoding="utf-8")
        for op, action in (("home", "do_home"), ("park", "do_park"), ("probe", "do_probe"),
                           ("frame_job", "do_frame"), ("autorun", "do_start"), ("queue_run", "do_resume")):
            self.assertRegex(text, r'ask_go\([^;]*%s\)' % action, op)
            found = re.search(r'static void %s\(void\)(?: \{ (.*?) \}\n|\n\{\n(.*?)\n\}\n)' % action, text, re.S)
            body = found.group(1) or found.group(2)
            self.assertIn('link_act("%s"' % op, body)
            # nowhere else in the file: no way around the question
            self.assertFalse('link_act("%s"' % op in text.replace(body, ""), op)
        self.assertIn("Hände raus · Deckel zu · Schutzbrille auf", text)


class PanelMaterialTest(unittest.TestCase):
    def act(self, b, **fields):
        b.handle_line(json.dumps({"t": "act", "id": 1, "op": "material", **fields}).encode())
        wait_for_answer(b)
        return b.port.messages()[-1]

    def test_list_has_one_line_per_material_and_thickness(self):
        b = bridge()
        b.handle_line(b'{"t":"mats"}')
        items = wait_for_kind(b, "mats")["items"]
        self.assertEqual(items, [{"name": "Leder", "mm": 2.0, "proc": "Gravieren, Schneiden", "start": False},
                                 {"name": "MDF", "mm": 3.0, "proc": "Schneiden", "start": True}])

    def test_choice_goes_to_the_shared_work_state_with_its_revision(self):
        b = bridge()
        res = self.act(b, name="MDF", thickness="3")
        self.assertTrue(res["ok"], res)
        self.assertIn(("PUT", "/api/workspace", {"material": {"name": "MDF", "thickness_mm": 3.0},
                                                 "base_revision": 7, "updated_by": "panel"}), b.api.calls)

    def test_only_materials_of_the_list(self):
        for fields in ({"name": "Holz", "thickness": "3"}, {"name": "MDF", "thickness": "59"},
                       {"name": "MDF", "thickness": "dick"}):
            b = bridge()
            self.assertFalse(self.act(b, **fields)["ok"], fields)
            self.assertFalse([c for c in b.api.calls if c[0] == "PUT"])

    def test_not_while_the_machine_works(self):
        for status in ({"activity": "job", "job": {"state": "running"}},
                       {"activity": "idle", "job": {"state": "idle"}, "queue": {"state": "running"}},
                       {"activity": "idle", "job": {"state": "idle"}, "laser_armed": True}):
            b = bridge(FakeApi(status))
            self.assertFalse(self.act(b, name="MDF", thickness="3")["ok"], status)
            self.assertFalse([c for c in b.api.calls if c[0] == "PUT"])

    def test_another_device_changed_it_meanwhile(self):
        api = FakeApi()
        api.put_answer = (409, {"error": "x", "revision": 9})
        res = self.act(bridge(api), name="MDF", thickness="3")
        self.assertFalse(res["ok"])
        self.assertIn("nochmal", res["msg"])

    def test_status_carries_the_chosen_material_and_reads_it_only_on_change(self):
        b = bridge()
        s = {"sync": {"workspace": 7}}
        self.assertEqual(b.panel_fields(s)["mat"], "MDF")
        self.assertEqual(b.panel_fields(s)["mat_mm"], 3.0)
        self.assertEqual(len([c for c in b.api.calls if c[1] == "/api/workspace"]), 1)
        b.api.workspace = {"revision": 8, "material": None}
        self.assertEqual(b.panel_fields({"sync": {"workspace": 8}})["mat"], "")

    def test_status_survives_a_failing_workspace(self):
        b = bridge()
        def down(*args, **kwargs):
            raise OSError("down")
        b.api.json = down
        self.assertEqual(b.panel_fields({"sync": {"workspace": 1}})["mat"], "")


class PanelPrefsTest(unittest.TestCase):
    def test_screen_off_is_kept_on_the_pi(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "panel.json"
            b = panel.PanelBridge(FakeApi(), prefs_path=path)
            b.port = FakePort()
            self.assertEqual(b.prefs["screen_off"], panel.SCREEN_OFF_DEFAULT)
            b.handle_line(b'{"t":"act","id":1,"op":"screen_off","minutes":"5"}')
            wait_for_answer(b)
            self.assertTrue(b.port.messages()[-1]["ok"])
            self.assertEqual(panel.PanelBridge(FakeApi(), prefs_path=path).prefs["screen_off"], 5)
            self.assertEqual(b.panel_fields({})["soff"], 5)

    def test_other_values_are_refused(self):
        b = bridge()
        for minutes in ("7", "-1", "bald", ""):
            ok, _ = b.set_screen_off(minutes)
            self.assertFalse(ok, minutes)
        self.assertEqual(b.prefs["screen_off"], panel.SCREEN_OFF_DEFAULT)

    def test_broken_file_gives_the_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "panel.json"
            for text in ("kaputt", "[1]", '{"screen_off": 999}'):
                path.write_text(text)
                self.assertEqual(panel.load_prefs(path)["screen_off"], panel.SCREEN_OFF_DEFAULT)

    def test_light_level_goes_to_the_pi(self):
        b = bridge()
        b.handle_line(b'{"t":"act","id":1,"op":"light","on":"1","brightness":"60","effects":"0"}')
        wait_for_answer(b)
        self.assertIn(("POST", "/api/action", {"op": "light", "on": "1", "brightness": "60"}), b.api.calls)


class PanelEventsTest(unittest.TestCase):
    IDLE = {"connected": True, "activity": "idle", "job": {"state": "idle"}}

    def texts(self, log):
        return [(e["level"], e["text"]) for e in log.items]

    def test_a_job_from_start_to_end(self):
        log = panel.EventLog()
        log.observe(self.IDLE, "10:00")
        self.assertEqual(log.seq, 0)
        run = {"connected": True, "activity": "job", "laser_armed": True, "job": {"state": "homing", "file": "a.gcode"}}
        log.observe(run, "10:01")
        log.observe({**run, "job": {"state": "running", "file": "a.gcode"}}, "10:02")   # no second entry
        log.observe({**self.IDLE, "job": {"state": "complete", "file": "a.gcode"}}, "10:30")
        self.assertEqual(self.texts(log), [("ok", "Fertig: a.gcode"), ("info", "Gestartet: a.gcode")])
        self.assertEqual(log.items[0]["time"], "10:30")
        self.assertEqual(log.problem, 0)

    def test_problems_are_counted_for_the_dot_on_the_panel(self):
        log = panel.EventLog()
        log.observe(self.IDLE, "10:00")
        log.observe({**self.IDLE, "job": {"state": "error", "file": "a.gcode", "error": "Kein Material"}}, "10:01")
        self.assertEqual(self.texts(log), [("err", "a.gcode: Kein Material")])
        self.assertEqual(log.problem, log.seq)

    def test_emergency_stop_connection_and_reference(self):
        log = panel.EventLog()
        log.observe(self.IDLE, "10:00")
        log.observe({**self.IDLE, "emergency_latched": True, "fault": "M112"}, "10:01")
        log.observe(self.IDLE, "10:02")
        log.observe({**self.IDLE, "connected": False}, "10:03")
        log.observe({**self.IDLE, "reference": {"lost": "Schalter offen"}}, "10:04")
        got = self.texts(log)
        self.assertIn(("err", "Notstopp aktiv: M112"), got)
        self.assertIn(("ok", "Notstopp quittiert"), got)
        self.assertIn(("err", "Steuerung getrennt (USB prüfen)"), got)
        self.assertIn(("info", "Steuerung verbunden"), got)
        self.assertIn(("warn", "Referenz verloren: Schalter offen"), got)

    def test_laser_armed_without_a_job_is_an_error(self):
        log = panel.EventLog()
        log.observe(self.IDLE, "10:00")
        log.observe({**self.IDLE, "laser_armed": True}, "10:01")
        log.observe({**self.IDLE, "laser_armed": True}, "10:02")
        self.assertEqual(self.texts(log), [("err", "Laser scharf ohne Auftrag")])

    def test_the_list_is_short_and_refused_actions_land_in_it(self):
        log = panel.EventLog(size=3)
        for i in range(5):
            log.add("info", "x%d" % i, "10:00")
        self.assertEqual([e["text"] for e in log.items], ["x4", "x3", "x2"])
        api = FakeApi()
        api.answer = (400, {"error": "Marlin muss zuerst referenziert werden"})
        b = bridge(api)
        b.handle_line(b'{"t":"act","id":1,"op":"park"}')
        wait_for_answer(b)
        for _ in range(100):
            if b.events.items:
                break
            threading.Event().wait(0.01)
        self.assertEqual(b.events.items[0]["text"], "Marlin muss zuerst referenziert werden")
        b.handle_line(b'{"t":"events"}')
        self.assertEqual(wait_for_kind(b, "events")["items"][0]["level"], "warn")


class PanelSystemTest(unittest.TestCase):
    def test_system_page(self):
        api = FakeApi({"connected": True, "serial_errors": 2,
                       "firmware_release": {"running_build": "b1", "release_build": "b2", "update_available": True}})
        b = bridge(api)
        b.firmware = lambda: {"version": "9.9"}
        b.path = "/dev/ttyACM0"
        b.version = "1.3"
        b.handle_line(b'{"t":"sys"}')
        msg = wait_for_kind(b, "sys")
        self.assertEqual((msg["skr"], msg["skr_new"], msg["serial_err"], msg["panel_new"]), ("b1", "b2", 2, "9.9"))
        self.assertTrue(msg["skr_conn"])

    def test_wlan_helpers_cope_with_a_pi_without_wlan(self):
        def missing(*args, **kwargs):
            raise FileNotFoundError("iwgetid")
        self.assertEqual(panel.wifi_name(run=missing), "")
        self.assertEqual(panel.software_version(run=missing), "")
        self.assertIsNone(panel.wifi_signal(Path("/gibt/es/nicht")))

    def test_signal_from_proc(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "wireless"
            path.write_text("Inter-| sta-|   Quality\n face | status | link level noise\n"
                            " wlan0: 0000   49.  -61.  -256        0      0      0      0      0        0\n")
            self.assertEqual(panel.wifi_signal(path), 70)


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

    def test_light_frame_power_and_waiting_queue(self):
        msg = panel.compact({"light_brightness": 60, "light_dimmable": True, "config": {"frame_power_pct": 0.5},
                             "queue": {"state": "paused", "items": [{"state": "done"}, {"state": "queued"}]}},
                            1.0, "", {}, None)
        self.assertEqual((msg["bright"], msg["dim"], msg["fpow"], msg["qn"]), (60, True, 0.5, 1))

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


class ClosingPort(FakePort):
    """Closing it frees the port, as serve_forever does after the session ends."""

    def __init__(self, b):
        super().__init__()
        self.b = b
        self.closed = False

    def close(self):
        self.closed = True
        self.b.port_free.set()


class PanelUpdateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        folder = Path(self.tmp.name)
        image = folder / "lumacut-panel.bin"
        image.write_bytes(b"panel image")
        import hashlib
        (folder / "manifest.json").write_text(json.dumps({
            "version": "1.1", "file": image.name, "address": "0x10000",
            "sha256": hashlib.sha256(image.read_bytes()).hexdigest()}))
        self.folder = folder
        self.flashed = []

    def tearDown(self):
        self.tmp.cleanup()

    def make(self, status=None, flash_ok=True, auto=True):
        def flasher(command):
            self.flashed.append(command)
            return flash_ok, "Hash of data verified." if flash_ok else "No serial data received."
        b = panel.PanelBridge(FakeApi(status or {"activity": "idle", "job": {"state": "idle"}}),
                              firmware=lambda: panel.bundled_firmware(self.folder), auto=lambda: auto,
                              flasher=flasher, has_esptool=lambda: True)
        b.port = ClosingPort(b)
        b.path = "/dev/serial/by-id/usb-Espressif_USB_JTAG_serial_debug_unit_AA-if00"
        return b

    def wait(self, b):
        for _ in range(300):
            if b.update["state"] != "flashing":
                return
            threading.Event().wait(0.01)
        raise AssertionError("update did not finish")

    def test_ping_reports_the_version(self):
        b = self.make()
        b.handle_line(b'{"t":"ping","cam":0,"v":"1.0"}')
        self.assertEqual(b.version, "1.0")
        info = b.info()
        self.assertEqual((info["version"], info["available"], info["update_available"]), ("1.0", "1.1", True))

    def test_older_panel_is_flashed_with_esptool_on_its_port(self):
        b = self.make()
        b.version = "1.0"
        ok, text = b.request_update()
        self.assertTrue(ok, text)
        self.wait(b)
        self.assertEqual(b.update["state"], "done")
        self.assertTrue(b.port.closed)
        command = self.flashed[0]
        self.assertEqual(command[command.index("--port") + 1], b.path)
        self.assertEqual(command[-2:], ["0x10000", str(self.folder / "lumacut-panel.bin")])
        self.assertIn("Bildschirm ist kurz aus", b.port.messages()[-1]["msg"])
        self.assertFalse(b.hold)

    def test_current_panel_is_left_alone_unless_asked(self):
        b = self.make()
        b.version = "1.1"
        self.assertFalse(b.request_update()[0])
        self.assertTrue(b.request_update(manual=True)[0])
        self.wait(b)

    def test_never_during_a_job_or_with_the_laser_armed(self):
        for status in ({"activity": "running", "job": {"state": "running"}},
                       {"activity": "idle", "job": {"state": "idle"}, "queue": {"state": "running"}},
                       {"activity": "idle", "job": {"state": "idle"}, "laser_armed": True}):
            b = self.make(status)
            b.version = "1.0"
            ok, text = b.request_update(manual=True)
            self.assertFalse(ok)
            self.assertIn("später", text)
        self.assertEqual(self.flashed, [])

    def test_failed_version_is_not_retried_by_itself(self):
        b = self.make(flash_ok=False)
        b.version = "1.0"
        b.connected_at = 0.0
        b.auto_update(b.api.status)
        self.wait(b)
        self.assertEqual(b.update["state"], "error")
        b.auto_update(b.api.status)
        self.assertEqual(len(self.flashed), 1)
        self.assertTrue(b.request_update(manual=True)[0])
        self.wait(b)

    def test_automatic_update_can_be_switched_off(self):
        b = self.make(auto=False)
        b.version = "1.0"
        b.auto_update(b.api.status)
        self.assertEqual(b.update["state"], "idle")

    def test_wrong_checksum_is_not_flashed(self):
        b = self.make()
        b.version = "1.0"
        (self.folder / "lumacut-panel.bin").write_bytes(b"other")
        b.request_update()
        self.wait(b)
        self.assertEqual(b.update["state"], "error")
        self.assertEqual(self.flashed, [])

    def test_versions_compare_as_numbers(self):
        self.assertLess(panel.version_key("1.9"), panel.version_key("1.10"))
        self.assertLess(panel.version_key("kaputt"), panel.version_key("1.0"))

    def test_bundled_firmware_of_the_repo_is_readable(self):
        fw = panel.bundled_firmware()
        self.assertIsNotNone(fw)
        self.assertTrue(fw["path"].is_file())


if __name__ == "__main__":
    unittest.main()
