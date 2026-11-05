"""Pi service operation: power cut, damaged files, full disk, stop by systemd,
foreign web pages. No real machine: fake serial port and temporary folders."""
import configparser
import hashlib
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pi400"))

from marlin import app_update, firmware_release, projects, service_auth, storage, workspace  # noqa: E402


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Temp(unittest.TestCase):
    def setUp(self):
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        self.dir = Path(holder.name)


class StorageTests(Temp):
    def test_failed_write_keeps_the_old_file_and_no_temporary(self):
        path = self.dir / "a.json"
        storage.atomic_write(path, "alt")
        with mock.patch.object(storage.os, "fsync", side_effect=OSError(28, "voll")):
            with self.assertRaises(OSError):
                storage.atomic_write(path, "neu")
        self.assertEqual(path.read_text("utf-8"), "alt")
        self.assertEqual([p.name for p in self.dir.iterdir()], ["a.json"])

    def test_threads_saving_at_once_leave_one_complete_file(self):
        path = self.dir / "a.json"
        errors = []

        def save(n):
            try:
                for _ in range(20):
                    storage.atomic_write(path, json.dumps({"n": n, "pad": "x" * 2000}))
            except OSError as exc:
                # Windows may refuse a rename over a file open elsewhere; Linux never does.
                if os.name != "nt":
                    errors.append(exc)
        threads = [threading.Thread(target=save, args=(n,)) for n in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])
        self.assertEqual(len(json.loads(path.read_text("utf-8"))["pad"]), 2000)
        self.assertEqual([p.name for p in self.dir.iterdir()], ["a.json"])

    def test_damaged_file_is_kept_aside(self):
        for text in ("", "{", "[]", "5"):
            path = self.dir / "c.json"
            path.write_text(text, "utf-8")
            self.assertIsNone(storage.read_json_object(path), text)
            self.assertFalse(path.exists())
            self.assertEqual((self.dir / "c.json.corrupt").read_text("utf-8"), text)
        self.assertIsNone(storage.read_json_object(self.dir / "fehlt.json"))
        self.assertFalse((self.dir / "fehlt.json.corrupt").exists())

    def test_leftovers_of_a_power_cut_are_removed(self):
        for name in (".config.json.abc.tmp", "a.gcode.partial"):
            (self.dir / name).write_text("x", "utf-8")
        (self.dir / "bleibt.gcode").write_text("x", "utf-8")
        self.assertEqual(storage.remove_stale_temp(self.dir), 2)
        self.assertEqual([p.name for p in self.dir.iterdir()], ["bleibt.gcode"])


class ServiceAuthTests(Temp):
    def setUp(self):
        super().setUp()
        self.path = self.dir / "service_password.json"
        self.auth = service_auth.ServiceAuth(self.path)

    def test_pings_do_not_repeat_the_slow_hash(self):
        self.auth.set("geheim")
        with mock.patch.object(service_auth.hashlib, "pbkdf2_hmac", wraps=hashlib.pbkdf2_hmac) as slow:
            for _ in range(40):                # one minute of pings every 1.5 s
                self.auth.check("geheim")
        self.assertEqual(slow.call_count, 1)

    def test_shortcut_ends_after_the_time_and_with_a_new_password(self):
        self.auth.set("geheim")
        self.auth.check("geheim")
        with mock.patch.object(service_auth.hashlib, "pbkdf2_hmac", wraps=hashlib.pbkdf2_hmac) as slow:
            now = time.monotonic()
            with mock.patch.object(service_auth.time, "monotonic", return_value=now + service_auth.VERIFIED_S + 1):
                self.auth.check("geheim")
            self.assertEqual(slow.call_count, 1)
        self.auth.set("anders", "geheim")
        with mock.patch.object(service_auth.time, "sleep"):
            with self.assertRaises(PermissionError):
                self.auth.check("geheim")
        self.auth.check("anders")

    def test_wrong_password_never_uses_the_shortcut(self):
        self.auth.set("geheim")
        self.auth.check("geheim")
        with mock.patch.object(service_auth.time, "sleep") as wait:
            with self.assertRaises(PermissionError):
                self.auth.check("falsch")
        wait.assert_called_once_with(1.0)

    def test_password_is_not_kept_in_memory(self):
        self.auth.set("geheim")
        self.auth.check("geheim")
        self.assertNotIn("geheim", repr(vars(self.auth)))
        self.assertNotIn(b"geheim", self.auth._verified[0])

    def test_parallel_guesses_wait_for_each_other(self):
        self.auth.set("geheim")
        results = []

        def guess():
            try:
                self.auth.check("falsch")
            except PermissionError:
                results.append(True)
        threads = [threading.Thread(target=guess) for _ in range(3)]
        start = time.monotonic()
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(len(results), 3)
        self.assertGreaterEqual(time.monotonic() - start, 2.9)

    def test_damaged_file_locks_instead_of_allowing_a_new_password(self):
        for text in ("", "{", "[]", "5", '{"salt":"zz","iterations":1,"hash":"a"}', '{"salt":"00"}',
                     '{"salt":"00","iterations":"x","hash":"a"}', '{"salt":"00","iterations":1,"hash":"é"}'):
            self.path.write_text(text, "utf-8")
            self.assertTrue(self.auth.is_set(), text)
            with self.assertRaisesRegex(PermissionError, "beschädigt"):
                self.auth.check("egal")
            with self.assertRaisesRegex(PermissionError, "beschädigt"):
                self.auth.set("neuesPasswort")

    @unittest.skipIf(os.name == "nt", "Dateirechte gibt es nur auf dem Pi")
    def test_hash_file_is_private(self):
        self.auth.set("geheim")
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)


class StoreTests(Temp):
    DOC = {"title": "Karte", "layers": [], "elements": [{"id": "e"}]}

    def _project(self, name="Karte"):
        store = projects.ProjectStore(self.dir)
        return store, store.save(name, json.dumps(self.DOC).encode("utf-8"))

    def test_damaged_project_list_loses_no_project(self):
        _, meta = self._project()
        for text in ("", "{", "[]", '{"projects":[{"id":"x"}]}', '{"projects":5}'):
            (self.dir / "index.json").write_text(text, "utf-8")
            listed = projects.ProjectStore(self.dir).list()
            self.assertEqual([(p["id"], p["name"], p["elements"]) for p in listed], [(meta["id"], "Karte", 1)], text)

    def test_power_cut_between_project_and_list(self):
        store, meta = self._project()
        (self.dir / "abcdef0123456789abcdef0123456789.json").write_text(json.dumps(self.DOC), "utf-8")
        names = sorted(p["name"] for p in projects.ProjectStore(self.dir).list())
        self.assertEqual(names, ["Karte", "Karte abcdef01"])     # names stay unique

    def test_failed_save_leaves_the_list_as_it_was(self):
        store, meta = self._project()
        with mock.patch.object(store, "_write", side_effect=OSError(28, "voll")):
            with self.assertRaises(OSError):
                store.save("Karte", json.dumps(dict(self.DOC, elements=[])).encode("utf-8"))
        self.assertEqual(store.list()[0]["elements"], 1)

    def test_damaged_work_state_means_no_material(self):
        bad = {"revision": "x", "material": {"name": "m"}, "areas": 5, "probe_points": [[1]], "settings": []}
        (self.dir / "state.json").write_text(json.dumps(bad), "utf-8")
        store = workspace.WorkspaceStore(self.dir)
        self.assertIsNone(store.material_thickness())      # the machine refuses jobs until one is chosen
        self.assertEqual(store.probe_points(), [])
        self.assertEqual(store.revisions()["workspace"], 0)
        self.assertEqual(store.put_state({"areas": []}, None, by=5)["updated_by"], "5")

    def test_damaged_release_files(self):
        for text in ("", "[]", "5", '{"boards":[1]}', '{"boards":{"skr":"x"}}'):
            fw = firmware_release.FirmwareReleases(self.dir)
            fw.meta_file.write_text(text, "utf-8")
            self.assertFalse(fw.offer("FIRMWARE_NAME:Marlin LumaCut CNC SKR")["update_available"], text)
            self.assertIsNone(fw.image("skr"), text)
            apps = app_update.AppUpdates(self.dir)
            apps.apk.write_bytes(b"x")
            apps.meta_file.write_text(text, "utf-8")
            if not text.startswith("{"):
                self.assertFalse(apps.status()["available"], text)


# ---------------------------------------------------------------- web service

class WebTests(Temp):
    def run_script(self, source, *args, data=None, timeout=40):
        data = data or self.dir
        env = dict(os.environ, LUMACUT_DATA=str(data), PYTHONPATH=str(ROOT / "pi400"), PYTHONUTF8="1",
                   LUMACUT_CAMERA_CALIBRATION=str(Path(data) / "camera_calibration.json"),
                   LUMACUT_HTTP=str(free_port()), LUMACUT_TCP=str(free_port()))
        run = subprocess.run([sys.executable, *args] if args else [sys.executable, "-c", source],
                             env=env, cwd=ROOT, capture_output=True, text=True, timeout=timeout)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        return run

    def write(self, name, text):
        path = self.dir / "marlin" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, "utf-8")
        return path

    def test_damaged_config_never_stops_the_service(self):
        self.write("config.json", json.dumps({
            "validated": "ja", "travels": "x", "motion": {"accel": "a", "speed": "b"}, "z_clearance_mm": "x",
            "focus_gap_mm": None, "light_brightness": None, "camera": 5, "user_origin": [1], "machine_name": 5,
            "probe_offset_x_mm": "x", "park_z_mm": True, "z_speed_mm_s": float("inf")}))
        self.run_script(r"""
from marlin import web
assert web.config["validated"] is False and web.machine.homing_verified is False
assert web.config["travels"]["z"] == 80.0 and web.config["z_clearance_mm"] == 20.0
assert web.config["machine_name"] == "LumaCut" and web.config["user_origin"] is None
assert web.app.test_client().get("/api/status").status_code == 200
""")

    def test_unreadable_config_is_kept_and_mechanics_stay_locked(self):
        path = self.write("config.json", '{"validated": tr')
        self.run_script(r"""
from marlin import web
assert web.machine.homing_verified is False
assert web.app.test_client().get("/api/status").status_code == 200
""")
        self.assertEqual((path.parent / "config.json.corrupt").read_text("utf-8"), '{"validated": tr')

    def test_good_values_next_to_a_damaged_one_stay(self):
        self.write("config.json", json.dumps({"validated": True, "travels": {"x": 370, "y": 360, "z": 80},
                                              "focus_gap_mm": "x", "user_origin": [60.0, 70.0],
                                              "motion": {"accel": None, "speed": None}}))
        self.run_script(r"""
from marlin import web
assert web.machine.homing_verified is True and web.machine.travel_xy == (370.0, 360.0)
assert web.config["user_origin"] == [60.0, 70.0] and web.config["focus_gap_mm"] == 7.0
""")

    def test_panel_setting_survives_a_restart(self):
        self.run_script(r"""
from marlin import web
c = web.app.test_client()
assert c.post("/api/action", data={"op": "panel_auto", "on": "0"}).status_code == 200
""")
        self.run_script(r"""
from marlin import web
assert web.config["panel_auto_update"] is False
""")

    def test_damaged_material_test_file_keeps_status_alive(self):
        for text in ("[]", "5", '{"a":1}', '{"kind":"cut","material":"m","state":"x","passes":5}'):
            self.write("matcal.json", text)
            self.run_script(r"""
from marlin import web
c = web.app.test_client()
assert c.get("/api/status").status_code == 200 and web.MATCAL["run"] is None
""")

    def test_foreign_web_page_cannot_operate_the_machine(self):
        self.run_script(r"""
from marlin import web
c = web.app.test_client()
stopped = []
web.machine.emergency_stop = lambda: stopped.append(1)
evil = {"Origin": "http://evil.example"}
for origin in ("http://evil.example", "null", "http://localhost.evil.example"):
    r = c.post("/api/action", data={"op": "home"}, headers={"Origin": origin})
    assert r.status_code == 403 and "Fremde" in r.get_json()["error"], (origin, r.data)
assert c.post("/api/settings", data={"machine_name": "x"}, headers=evil).status_code == 403
assert c.post("/api/commission", data={"enable": "1"}, headers=evil).status_code == 403
assert c.put("/api/workspace", json={}, headers=evil).status_code == 403
assert web.config["machine_name"] == "LumaCut"
# the web UI itself and clients without Origin (apps, panel)
assert c.post("/api/settings", data={"machine_name": "a"}, headers={"Origin": "http://LOCALHOST"}).status_code == 200
assert c.post("/api/settings", data={"machine_name": "b"}).status_code == 200
# stopping always works; reading is not affected
assert c.post("/api/action", data={"op": "estop"}, headers=evil).status_code == 200 and stopped == [1]
r = c.get("/api/status", headers=evil)
assert r.status_code == 200 and r.headers["X-Frame-Options"] == "SAMEORIGIN"
assert "Access-Control-Allow-Origin" not in r.headers
""")

    def test_errors_are_json_and_full_disk_is_named(self):
        self.run_script(r"""
import io, errno
from marlin import web
from marlin import storage
c = web.app.test_client()
for r, code in ((c.get("/api/gibtsnicht"), 404), (c.get("/api/action"), 405),
                (c.post("/api/upload", data=b"x" * (33 * 1024 * 1024), content_type="application/octet-stream"), 413)):
    assert r.status_code == code and r.get_json()["error"], r.data
assert c.get("/gibtsnicht").status_code == 404
class SerialException(OSError):
    pass
def gone():
    raise SerialException("could not open port")
web.machine.ensure_ready = gone
assert c.post("/api/action", data={"op": "connect"}).status_code == 503
web.machine.homing_verified = True
up = lambda name, body=b"G21\n": c.post("/api/upload", data={"file": (io.BytesIO(body), name)},
                                        content_type="multipart/form-data")
assert up("x" * 300 + ".gcode").status_code == 400
assert up("a.gcode").status_code == 200 and (web.JOBS / "a.gcode").read_bytes() == b"G21\n"
assert [p.name for p in web.JOBS.iterdir()] == ["a.gcode"]
assert c.put("/api/camera/settings", data='{"light":1e999}', content_type="application/json").status_code == 400
assert c.put("/api/workspace", json={"updated_by": 5}).status_code == 200
assert c.get("/api/status").get_json()["disk_free_mb"] > 0
assert c.get("/api/jobs/config.json/geometry").status_code == 400
# nearly full: large requests refused, small settings still saved
web.free_bytes = lambda path: storage.RESERVE_BYTES // 2
assert up("gross.gcode", b"G21\n" * 400000).status_code == 507
assert not (web.JOBS / "gross.gcode").exists()
assert c.post("/api/settings", data={"machine_name": "klein"}).status_code == 200
# really full: a clear message, the old file stays
def full(*a, **k):
    raise OSError(errno.ENOSPC, "No space left on device")
web.atomic_write = full
r = c.post("/api/settings", data={"machine_name": "x"})
assert r.status_code == 507 and "voll" in r.get_json()["error"], r.data
""")

    def test_refusals_log_one_line_and_bugs_their_trace(self):
        run = self.run_script(r"""
import logging
from marlin import web
c = web.app.test_client()
logging.basicConfig(level=logging.INFO)
assert c.post("/api/action", data={"op": "gibtsnicht"}).status_code == 400
""")
        self.assertIn("abgelehnt: Unbekannte Aktion", run.stderr)
        self.assertNotIn("Traceback", run.stderr)

    def test_backup_holds_the_real_calibration_and_can_be_restored(self):
        run = self.run_script(r"""
import json
from marlin import web, bedmap, heightmap
c = web.app.test_client()
cal = c.get("/api/camera/calibration").get_json()
assert c.get("/api/backup").get_json()["camera_calibration"] is None    # placeholder only
r = c.put("/api/camera/calibration", json={"revision": cal["revision"], "notes": "gemessen", "px_per_mm": 12.5})
assert r.status_code == 200, r.data
c.post("/api/settings", data={"machine_name": "Werkstatt", "travel_x_mm": "370"})
web.config["validated"] = True; web.persist()
web.WORKSPACE.put_state({"material": {"name": "Holz", "thickness_mm": 4}}, None)
web.MATCAL["run"] = {"kind": "cut", "material": "Holz", "state": "complete", "passes": []}
grid = bedmap.plan(heightmap.Box(30, 30, 300, 300), lambda x, y: True)
grid.z = [-1.0] * len(grid.z)
web._set_bed(bedmap.BedMap.from_measured(grid))
b = c.get("/api/backup").get_json()
assert b["camera_calibration"]["notes"] == "gemessen" and b["bed_map"] and b["material_calibration"]
assert "service_password" not in json.dumps(b)
(web.DATA.parent / "sicherung.json").write_text(json.dumps(b), "utf-8")
""")
        self.assertEqual(run.returncode, 0)
        fresh = self.dir / "neu"
        fresh.mkdir()
        run = self.run_script("", "-m", "marlin.restore_backup", str(self.dir / "sicherung.json"), data=fresh)
        self.assertIn("Mechanik-Freigabe", run.stdout)
        self.run_script(r"""
from marlin import web
c = web.app.test_client()
assert web.config["machine_name"] == "Werkstatt" and web.config["travels"]["x"] == 370.0
assert web.config["validated"] is False and web.machine.homing_verified is False   # never restored
assert web.WORKSPACE.material_thickness() == 4.0
cal = c.get("/api/camera/calibration").get_json()
assert cal["notes"] == "gemessen" and cal["px_per_mm"] == 12.5
assert web.BED is not None and web.MATCAL["run"]["material"] == "Holz"
assert web.MATERIALS.list()["materials"]
""", data=fresh)

    def test_restore_refuses_while_the_service_runs(self):
        source = self.dir / "s.json"
        source.write_text("{}", "utf-8")
        with socket.socket() as server:
            server.bind(("127.0.0.1", 0))
            server.listen(1)
            env = dict(os.environ, LUMACUT_DATA=str(self.dir), PYTHONPATH=str(ROOT / "pi400"), PYTHONUTF8="1",
                       LUMACUT_HTTP=str(server.getsockname()[1]))
            run = subprocess.run([sys.executable, "-m", "marlin.restore_backup", str(source)], env=env,
                                 cwd=ROOT, capture_output=True, text=True, timeout=30)
        self.assertEqual(run.returncode, 2)
        self.assertIn("läuft noch", run.stderr)

    STOP = r"""
import signal, threading, time, sys
from marlin import web
class Fake:
    def __init__(self): self.writes, self.q = [], []
    def write(self, raw):
        self.writes.append(raw.decode()); self.q.append(b"ok\n"); return len(raw)
    def readline(self):
        if self.q: return self.q.pop(0)
        time.sleep(0.001); return b""
    def reset_input_buffer(self): pass
    def close(self): pass
fake = Fake()
m = web.machine
m.serial, m.identity, m.state = fake, "LumaCut CNC", "Idle"
web.monitor_loop = lambda: None
web.panel.start = lambda *a, **k: None
web.SHUTDOWN_LOCK_WAIT_S = 0.2
%s
threading.Timer(1.0, signal.raise_signal, (signal.SIGTERM,)).start()
web.main()
sent = "".join(fake.writes)
assert web.running is False
print("SENT:" + sent.replace("\n", "|"))
"""

    def _stop(self, setup=""):
        run = self.run_script(self.STOP % setup)
        return re.search(r"SENT:(.*)", run.stdout).group(1)

    def test_stop_by_systemd_switches_the_laser_off_when_idle(self):
        sent = self._stop()
        self.assertIn("M5 I", sent)
        self.assertNotIn("M112", sent)

    def test_stop_by_systemd_with_service_beam_on_is_a_hard_stop(self):
        self.assertIn("M112", self._stop("m.service_power = 128"))

    def test_stop_by_systemd_with_a_job_is_a_hard_stop(self):
        self.assertIn("M112", self._stop('m.owner = "job"'))

    def test_stop_does_not_wait_behind_a_running_move(self):
        setup = ("hold = threading.Event()\n"
                 "threading.Thread(target=lambda: (m.lock.acquire(), hold.wait()), daemon=True).start()\n"
                 "time.sleep(0.1)")
        self.assertIn("M112", self._stop(setup))

    def test_background_loop_comes_back_after_a_crash(self):
        self.run_script(r"""
from marlin import web
web.SUPERVISE_RESTART_S = 0.01
web.running = True
runs = []
def loop():
    runs.append(1)
    if len(runs) < 3:
        raise KeyError("Fehler")
web._supervised(loop)
assert len(runs) == 3
# stopped service: no new attempt
runs.clear(); web.running = False
def broken():
    runs.append(1); raise KeyError("Fehler")
web._supervised(broken)
assert len(runs) == 1
""")

    def test_polling_stays_out_of_the_log(self):
        self.run_script(r"""
import logging
from marlin import web
f = web._QuietPolling()
line = lambda text: logging.LogRecord("werkzeug", logging.INFO, "", 0, text, (), None)
for quiet in ('1.2.3.4 - - [x] "GET /api/status HTTP/1.1" 200 -',
              '1.2.3.4 - - [x] "GET /api/jobs HTTP/1.1" 200 -',
              '1.2.3.4 - - [x] "GET /api/camera/snapshot?w=1 HTTP/1.1" 200 -',
              '1.2.3.4 - - [x] "GET /api/status HTTP/1.1" 304 -'):
    assert not f.filter(line(quiet)), quiet
for kept in ('1.2.3.4 - - [x] "GET /api/status HTTP/1.1" 500 -',
             '1.2.3.4 - - [x] "POST /api/action HTTP/1.1" 200 -',
             '1.2.3.4 - - [x] "GET /api/jobs/a.gcode/delete HTTP/1.1" 404 -',
             '1.2.3.4 - - [x] "GET /api/backup HTTP/1.1" 200 -'):
    assert f.filter(line(kept)), kept
""")


class ScriptTests(unittest.TestCase):
    def _unit(self):
        parser = configparser.ConfigParser(strict=False, interpolation=None)
        parser.optionxform = str
        parser.read(ROOT / "pi400" / "marlin" / "lumacut-marlin.service", encoding="utf-8")
        return parser

    def test_unit_keeps_devices_restart_and_stop_time(self):
        unit = self._unit()
        service = unit["Service"]
        self.assertEqual(service["Restart"], "always")
        self.assertEqual(service["User"], "lumacut")
        self.assertEqual(unit["Unit"]["StartLimitIntervalSec"], "0")
        self.assertGreaterEqual(int(service["TimeoutStopSec"]), 15)     # M5 I handshake on stop
        for group in ("dialout", "video"):
            self.assertIn(group, service["SupplementaryGroups"])
        for closed in ("PrivateDevices", "ProtectClock", "DevicePolicy", "DeviceAllow", "ProtectKernelTunables"):
            self.assertNotIn(closed, service)      # they close /dev or /sys: SKR, panel, camera gone
        self.assertIn("/var/lib/lumacut", service["ReadWritePaths"])
        self.assertIn("/etc/lumacut", service["ReadWritePaths"])

    def _safe_state(self, status):
        source = (ROOT / "pi400" / "update.sh").read_text(encoding="utf-8")
        code = re.search(r"<<'PY'\r?\n(.*?)\r?\nPY", source, re.S).group(1)
        env = dict(os.environ, STATUS_JSON=json.dumps(status), PYTHONUTF8="1")
        return subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True).returncode

    def test_update_waits_for_a_service_beam_or_a_move(self):
        idle = {"owner": "Frei", "state": "Idle", "service_laser_percent": 0, "busy": False}
        self.assertEqual(self._safe_state(idle), 0)
        self.assertEqual(self._safe_state(dict(idle, service_laser_percent=20)), 2)
        self.assertEqual(self._safe_state(dict(idle, busy=True)), 2)
        self.assertEqual(self._safe_state(dict(idle, owner="job")), 2)

    def test_scripts_install_the_unit_and_camera_tools(self):
        update = (ROOT / "pi400" / "update.sh").read_text(encoding="utf-8")
        self.assertIn("install_unit\n", update.replace("\r\n", "\n"))
        self.assertIn('systemctl daemon-reload', update)
        recover = (ROOT / "pi400" / "recover.sh").read_text(encoding="utf-8")
        self.assertIn('cp "$ROOT/pi400/marlin/$SERVICE"', recover)
        install = (ROOT / "pi400" / "install.sh").read_text(encoding="utf-8")
        self.assertIn("ffmpeg v4l-utils", install)
        for script in ("update.sh", "recover.sh", "install.sh"):
            run = subprocess.run(["bash", "-n", str(ROOT / "pi400" / script)], capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stderr)


if __name__ == "__main__":
    unittest.main()
