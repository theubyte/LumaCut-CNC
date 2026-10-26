"""Scan über die Pi-Endpunkte ``GET /api/camera/snapshot`` und ``op=moveto``.

Der Fake-Pi bildet pi400/marlin/web.py + transport.move_to nach:
moveto ist blockierend (Antwort nach M400 mit ``position``), hebt Z auf
``z_clearance_mm`` an, wenn der Kopf tiefer steht, senkt Z nie; Z-Jogs
nur mit vermessener Oberfläche; Snapshot liefert ein JPEG und fährt nie.
Ein „alter Pi“ hat weder ``camera`` im Status noch moveto/Snapshot.
"""
from __future__ import annotations

import copy
import json
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

import _paths  # noqa: F401  (src/ auf sys.path)
from machine.client import ApiError, LumaCutClient
from scanprobe import adapters
from scanprobe.fakes import FakeCamera, SyntheticBed
from scanprobe.geometry import DEFAULT_LIMITS
from scanprobe.stitch import stitch_mosaic
from scanprobe.tile_scan import TileScanner, plan_tiles

STATUS = {
    "firmware": "marlin", "connected": True, "state": "Idle", "owner": "Frei",
    "homed": True, "z_homed": True, "homing_verified": True,
    "position": [0.0, 0.0, 40.0], "laser_armed": False, "emergency_latched": False,
    "workpiece_surface_z": 3.25, "busy": False, "stale_ms": 0,
    "job": {"state": "idle"}, "frame": {"state": "idle"},
    "config": {"z_clearance_mm": 20.0, "travels": {"x": 390, "y": 370, "z": 90}},
    "camera": {"device": "/dev/video0", "available": True},
}


class FakeScanPi:
    def __init__(self, old: bool = False, camera: bool = True):
        self.status = copy.deepcopy(STATUS)
        self.old = old
        if old:
            del self.status["camera"]
        elif not camera:
            self.status["camera"]["available"] = False
        self.requests: list[tuple[str, str, dict]] = []
        self.snapshot_fail: list[int] = []     # Statuscodes der nächsten Snapshot-Antworten
        self.snapshot_raw: bytes | None = None
        self.snapshot_size: tuple[int, int] | None = None   # liefert andere Größe
        self.moveto_error: str | None = None
        self.moveto_offset = 0.0               # Pi meldet andere Position
        self.busy_polls = 0                    # so oft busy=True melden
        self.bed = SyntheticBed.with_objects(seed=3, objects=[
            {"kind": "rect", "rect": (70, 80, 190, 170), "z": lambda x, y: 3.0}])
        self.cal = adapters.default_calibration()
        self.lock = threading.Lock()
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _json(self, code, data):
                raw = json.dumps(data).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_GET(self):
                url = urllib.parse.urlsplit(self.path)
                query = dict(urllib.parse.parse_qsl(url.query))
                with fake.lock:
                    fake.requests.append(("GET", url.path, query))
                if url.path == "/api/status":
                    with fake.lock:
                        st = copy.deepcopy(fake.status)
                        if fake.busy_polls > 0:
                            fake.busy_polls -= 1
                            st["busy"], st["state"] = True, "Busy"
                    return self._json(200, st)
                if url.path == "/api/camera/snapshot" and not fake.old:
                    code, data = fake.snapshot(query)
                    if code != 200:
                        return self._json(code, {"error": data})
                    self.send_response(200)
                    self.send_header("Content-Type", "image/jpeg")
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                    return None
                self._json(404, {"error": "nicht gefunden"})

            def do_POST(self):
                body = self.rfile.read(int(self.headers.get("Content-Length") or 0)).decode()
                form = dict(urllib.parse.parse_qsl(body))
                with fake.lock:
                    fake.requests.append(("POST", self.path, form))
                    code, data = fake.action(form)
                self._json(code, data)

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = "http://127.0.0.1:%d" % self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    # -- Pi-Seite ---------------------------------------------------------
    def snapshot(self, query):
        w, h = int(query.get("w", 1280)), int(query.get("h", 960))
        if not (160 <= w <= 4096 and 120 <= h <= 3072):
            return 400, "Bildgröße unzulässig"
        if not self.status.get("camera", {"available": True})["available"]:
            return 503, "Kamera /dev/video0 nicht gefunden"
        if self.snapshot_fail:
            return self.snapshot_fail.pop(0), "Kamera lieferte kein Bild"
        if self.snapshot_raw is not None:
            return 200, self.snapshot_raw
        x, y, _z = self.status["position"]
        head = SimpleNamespace(true_x=x, true_y=y)
        img = FakeCamera(head, self.bed, self.cal).capture()
        if self.snapshot_size:
            img = cv2.resize(img, self.snapshot_size)
        ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 95])
        assert ok
        return 200, buf.tobytes()

    def action(self, form):
        pos = self.status["position"]
        op = form.get("op")
        if op == "jog":
            axis, dist = form["axis"], float(form["distance"])
            if axis == "Z" and self.status["workpiece_surface_z"] is None:
                return 400, {"error": "Z-Fahrten nur mit vermessener Werkstückoberfläche erlaubt"}
            i = "XYZ".index(axis)
            pos[i] = round(pos[i] + dist, 3)
            return 200, {"message": "Jog %s %+g" % (axis, dist)}
        if op == "moveto" and not self.old:
            if self.moveto_error:
                return 400, {"error": self.moveto_error}
            x, y = float(form["x"]), float(form["y"])
            if not (0 <= x <= 390 and 0 <= y <= 370):
                return 400, {"error": "Ziel außerhalb des Fahrbereichs"}
            clearance = self.status["config"]["z_clearance_mm"]
            if pos[2] < clearance:
                pos[2] = clearance
            pos[0], pos[1] = x + self.moveto_offset, y
            return 200, {"message": "Fahrt beendet", "position": list(pos)}
        return 400, {"error": "Unbekannte Marlin-Aktion: %s" % op}

    def count(self, method, path, op=None):
        return sum(1 for m, p, f in self.requests
                   if m == method and p == path and (op is None or f.get("op") == op))

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture()
def pi():
    fake = FakeScanPi()
    yield fake
    fake.close()


@pytest.fixture()
def old_pi():
    fake = FakeScanPi(old=True)
    yield fake
    fake.close()


def _machine(fake, **kw):
    kw.setdefault("sleep", lambda s: None)
    return adapters.PiMachine(LumaCutClient(fake.url, ""), **kw)


# ---------------------------------------------------------------- Client
def test_client_snapshot_and_moveto_requests(pi):
    client = LumaCutClient(pi.url, "")
    data = client.camera_snapshot(640, 480)
    assert data[:2] == b"\xff\xd8"                        # JPEG
    assert pi.requests[-1] == ("GET", "/api/camera/snapshot", {"w": "640", "h": "480"})
    reply = client.move_to(100.0, 50.5)
    assert reply["position"][:2] == [100.0, 50.5]
    assert pi.requests[-1][2] == {"op": "moveto", "x": "100.000", "y": "50.500"}


# ---------------------------------------------------------------- Feature-Erkennung
def test_pi_features_new_without_camera_and_old():
    full = FakeScanPi()
    nocam = FakeScanPi(camera=False)
    old = FakeScanPi(old=True)
    try:
        f = adapters.pi_features(LumaCutClient(full.url, ""))
        assert f.moveto and f.snapshot and "/dev/video0" in f.summary
        f = adapters.pi_features(LumaCutClient(nocam.url, ""))
        assert f.moveto and not f.snapshot and "keine Kamera" in f.summary
        f = adapters.pi_features(LumaCutClient(old.url, ""))
        assert not f.moveto and not f.snapshot and "Jog-Schritten" in f.summary
        # keine Fahrt, kein Snapshot zur Erkennung
        for fake in (full, nocam, old):
            assert {p for _m, p, _f in fake.requests} == {"/api/status"}
    finally:
        for fake in (full, nocam, old):
            fake.close()


# ---------------------------------------------------------------- Snapshot-Kamera
def test_snapshot_camera_decodes_bgr_with_calibrated_size(pi):
    cam = adapters.PiSnapshotCamera(LumaCutClient(pi.url, ""), 640, 480, sleep=lambda s: None)
    img = cam.capture()
    assert img.shape == (480, 640, 3) and img.dtype == np.uint8
    assert cam.requests == 1
    # Kamera fährt nie
    assert pi.count("POST", "/api/action") == 0


def test_snapshot_retries_503_then_succeeds(pi):
    sleeps = []
    cam = adapters.PiSnapshotCamera(LumaCutClient(pi.url, ""), 640, 480, retries=2,
                                    sleep=sleeps.append)
    pi.snapshot_fail = [503, 503]
    assert cam.capture().shape == (480, 640, 3)
    assert cam.requests == 3 and len(sleeps) == 2


def test_snapshot_errors_are_german(pi, old_pi):
    cam = adapters.PiSnapshotCamera(LumaCutClient(pi.url, ""), 640, 480, retries=1,
                                    sleep=lambda s: None)
    pi.snapshot_fail = [503, 503]
    with pytest.raises(adapters.HardwareNotReady, match="kein Bild nach 2 Versuchen"):
        cam.capture()
    pi.snapshot_raw = b"kein jpeg"
    with pytest.raises(adapters.HardwareNotReady, match="kein gültiges JPEG"):
        cam.capture()
    pi.snapshot_raw = None
    pi.snapshot_size = (800, 600)
    with pytest.raises(adapters.HardwareNotReady, match="liefert 800×600.*640×480"):
        cam.capture()
    old = adapters.PiSnapshotCamera(LumaCutClient(old_pi.url, ""), 640, 480, sleep=lambda s: None)
    with pytest.raises(adapters.HardwareNotReady, match="ohne Kamera-Snapshot.*Lokal"):
        old.capture()
    assert old.requests == 1                              # 404 nicht wiederholen
    with pytest.raises(adapters.HardwareNotReady, match="Bildgröße 5000×480"):
        adapters.PiSnapshotCamera(LumaCutClient(pi.url, ""), 5000, 480)


def test_pi_setup_camera_kinds(pi):
    client = LumaCutClient(pi.url, "")
    cal = adapters.default_calibration()
    feats = adapters.pi_features(client)
    hw = adapters.pi_setup(client, cal, "", adapters.CAMERA_PI, feats)
    assert isinstance(hw.camera, adapters.PiSnapshotCamera) and hw.machine.use_moveto
    assert (hw.camera.width, hw.camera.height) == (640, 480) and "Pi-Kamera" in hw.description
    hw = adapters.pi_setup(client, cal, "", adapters.CAMERA_LOCAL, feats)
    assert hw.camera is None                              # lokal ohne Quelle
    nocam = adapters.PiFeatures(moveto=True, snapshot=False, note="Pi meldet keine Kamera")
    with pytest.raises(adapters.HardwareNotReady, match="keine Kamera"):
        adapters.pi_setup(client, cal, "", adapters.CAMERA_PI, nocam)


# ---------------------------------------------------------------- moveto
def test_moveto_one_request_per_xy_move(pi):
    m = _machine(pi)
    m.move_to(120.0, 85.5, None, 9000)
    assert pi.status["position"] == [120.0, 85.5, 40.0]
    assert m.motion_requests == 1 and pi.count("POST", "/api/action", "jog") == 0
    m.wait_idle()
    assert m.use_moveto is True


def test_moveto_raises_z_first_and_respects_surface(pi):
    pi.status["position"] = [10.0, 10.0, 4.0]
    m = _machine(pi)
    m.move_to(50.0, 60.0, 5.0)        # Ziel Z5 → nie unter Oberfläche 3.25 + 2 = 5.25
    ops = [f.get("op") for meth, _p, f in pi.requests if meth == "POST"]
    first_moveto = ops.index("moveto")
    assert "jog" in ops[:first_moveto]                    # Z vor XY hoch
    # moveto hebt auf Rückzugshöhe 20, danach abwärts in Jog-Schritten (abgerundet)
    z = pi.status["position"][2]
    assert 5.25 <= z <= 5.35 and pi.status["position"][:2] == [50.0, 60.0]


def test_moveto_without_z_keeps_pi_lift(pi):
    pi.status["position"] = [10.0, 10.0, 12.0]
    m = _machine(pi)
    m.move_to(30.0, 30.0)
    assert pi.status["position"] == [30.0, 30.0, 20.0]    # Pi hebt, Studio senkt nicht ungefragt


def test_moveto_rejected_and_position_mismatch(pi):
    m = _machine(pi)
    pi.moveto_error = "Maschine ist nicht referenziert"
    with pytest.raises(adapters.HardwareNotReady, match="Fahrt nach X50.0 Y50.0 abgelehnt.*referenziert"):
        m.move_to(50.0, 50.0)
    pi.moveto_error = None
    pi.moveto_offset = 1.0
    with pytest.raises(adapters.HardwareNotReady, match="Position X61.00"):
        m.move_to(60.0, 60.0)
    with pytest.raises(ValueError, match="außerhalb"):
        m.move_to(500.0, 10.0)


def test_unknown_moveto_falls_back_to_jog(pi):
    """Status sagt „neu“, Pi kennt moveto trotzdem nicht → Jog-Rückfall mit Hinweis."""
    pi.old = True
    m = _machine(pi, use_moveto=True)
    m.move_to(21.0, 11.0)
    assert pi.status["position"][:2] == [21.0, 11.0]
    assert m.use_moveto is False and adapters.OLD_PI_NOTE in m.notes
    jogs = pi.count("POST", "/api/action", "jog")
    m.move_to(32.0, 22.0)                                 # kein zweiter moveto-Versuch
    assert pi.count("POST", "/api/action", "moveto") == 1
    assert pi.count("POST", "/api/action", "jog") - jogs == 4   # 10 + 1 je Achse


def test_old_pi_detected_from_status_uses_jog(old_pi):
    m = _machine(old_pi)
    m.move_to(21.0, 11.0)
    assert m.use_moveto is False
    assert old_pi.count("POST", "/api/action", "moveto") == 0
    assert old_pi.status["position"][:2] == [21.0, 11.0]


# ---------------------------------------------------------------- wait_idle
def test_wait_idle_polls_status_until_idle(pi):
    sleeps = []
    m = _machine(pi, sleep=sleeps.append, poll_s=0.05)
    pi.busy_polls = 3
    m.wait_idle()
    assert len(sleeps) == 3 and pi.count("GET", "/api/status") == 4


def test_wait_idle_timeout_and_emergency(pi):
    m = _machine(pi, poll_s=0.0, idle_timeout_s=0.0)
    pi.busy_polls = 100
    with pytest.raises(adapters.HardwareNotReady, match="noch Bewegung"):
        m.wait_idle()
    pi.busy_polls = 0
    pi.status["emergency_latched"] = True
    with pytest.raises(adapters.HardwareNotReady, match="Notstopp"):
        m.wait_idle()


# ---------------------------------------------------------------- Z-Vorabprüfung
def test_check_scan_height_requires_g30_surface(pi):
    pi.status["workpiece_surface_z"] = None
    m = _machine(pi)
    with pytest.raises(adapters.HardwareNotReady, match="Fokus \\(G30\\)"):
        m.check_scan_height(35.0)
    assert pi.count("POST", "/api/action") == 0           # Prüfung fährt nie
    pi.status["position"][2] = 35.0                       # Kopf steht schon auf Scanhöhe
    assert m.check_scan_height(35.0) == []


def test_check_scan_height_surface_travel_and_clearance(pi):
    m = _machine(pi)
    pi.status["workpiece_surface_z"] = 34.0
    with pytest.raises(adapters.HardwareNotReady, match="weniger als 2 mm"):
        m.check_scan_height(35.0)
    pi.status["workpiece_surface_z"] = 3.0
    with pytest.raises(adapters.HardwareNotReady, match="Fahrbereichs Z0..90"):
        m.check_scan_height(95.0)
    assert m.check_scan_height(40.0) == [] and m.use_moveto is True
    notes = m.check_scan_height(15.0)                     # unter Rückzugshöhe 20
    assert m.use_moveto is False and "Rückzugshöhe" in notes[0]
    pi.status["position"] = [0.0, 0.0, 15.0]
    m.move_to(25.0, 0.0)
    assert pi.count("POST", "/api/action", "moveto") == 0 and pi.status["position"][2] == 15.0


def test_check_scan_height_on_old_pi_notes_jog(old_pi):
    notes = _machine(old_pi).check_scan_height(40.0)
    assert notes == [adapters.OLD_PI_NOTE]


# ---------------------------------------------------------------- Scan-Ablauf
def _scan(fake, camera_kind):
    client = LumaCutClient(fake.url, "")
    cal = fake.cal
    feats = adapters.pi_features(client)
    hw = adapters.pi_setup(client, cal, "", camera_kind, feats)
    hw.machine._sleep = lambda s: None
    if hw.camera is None:   # „lokal“: gleiche Bilder, aber ohne Pi-Anfrage
        cam = PiImageLocal(fake)
        hw.camera = cam
    hw.machine.check_scan_height(cal.scan_z)
    plan = plan_tiles(DEFAULT_LIMITS.work_rect, cal, 0.2, DEFAULT_LIMITS)
    fake.requests.clear()
    tiles = TileScanner(hw.machine, hw.camera, cal, settle_s=0, sleep=lambda s: None).run(plan)
    return plan, tiles, hw


class PiImageLocal:
    """Lokale Kamera-Attrappe: dasselbe JPEG-Bild wie der Pi, ohne HTTP."""

    def __init__(self, fake):
        self.fake = fake

    def capture(self):
        _code, data = self.fake.snapshot({"w": 640, "h": 480})
        return cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)


def test_request_count_jog_vs_moveto_default_plan():
    """Rechnerische Abschätzung (keine Messung): Pi-Anfragen pro Kachel."""
    new, old = FakeScanPi(), FakeScanPi(old=True)
    try:
        plan, tiles_new, _ = _scan(new, adapters.CAMERA_PI)
        _plan, tiles_old, _ = _scan(old, adapters.CAMERA_LOCAL)
        n = len(plan.tiles)
        assert len(tiles_new) == len(tiles_old) == n
        new_total = len(new.requests)
        old_motion = old.count("POST", "/api/action")
        old_total = len(old.requests)
        # moveto: je Kachel 1 Status + 1 moveto + 1 Status (wait_idle) + 1 Snapshot
        assert new.count("POST", "/api/action", "moveto") == n
        assert new.count("GET", "/api/camera/snapshot") == n
        assert new_total <= 4 * n + 2
        # Jog: Zerlegung in 10/1/0,1-mm-Schritte, eine Anfrage je Schritt
        assert old_motion > 3 * n and old_total > 2 * new_total - 4 * n
        print(f"\nStandardplan {n} Kacheln: moveto+Snapshot {new_total} Pi-Anfragen "
              f"({new_total / n:.1f}/Kachel), Jog {old_total} ({old_total / n:.1f}/Kachel, "
              f"davon {old_motion} Jog-Schritte, Kamera lokal)")
    finally:
        new.close()
        old.close()


def test_both_camera_sources_give_identical_mosaic():
    """Versatz/Drehung/Spiegelung/Entzerrung hängen nur an der Kalibrierung."""
    a, b = FakeScanPi(), FakeScanPi()
    try:
        plan, tiles_pi, _ = _scan(a, adapters.CAMERA_PI)
        _plan, tiles_local, _ = _scan(b, adapters.CAMERA_LOCAL)
        for t1, t2 in zip(tiles_pi, tiles_local):
            assert t1.tile.head == t2.tile.head
            assert np.array_equal(t1.image, t2.image)
        m1 = stitch_mosaic(tiles_pi, a.cal, plan.bounds, 1.0)
        m2 = stitch_mosaic(tiles_local, b.cal, plan.bounds, 1.0)
        assert np.array_equal(m1.image, m2.image)
        # Werkstück (hell) liegt im Mosaik dort, wo es auf dem Bett liegt
        assert m1.image[125, 130].mean() > m1.image[300, 330].mean()
    finally:
        a.close()
        b.close()


# ---------------------------------------------------------------- Panel
@pytest.fixture()
def panel(qapp):
    from lumacut_canvas.editor import CanvasEditor
    from scanprobe.panel import ScanPanel
    ed = CanvasEditor()
    p = ScanPanel(ed, ask=False)
    yield p
    p.shutdown()
    ed.undo_stack.setClean()


def _pi_panel(panel, fake, tmp_path):
    from scanprobe.panel import MODE_PI
    client = LumaCutClient(fake.url, "")
    panel.client_provider = lambda: client
    path = tmp_path / "camera.json"
    fake.cal.save(path)
    panel.set_mode(MODE_PI)
    panel.load_calibration(path)
    return client


def test_panel_defaults_to_pi_camera_and_scans_via_snapshot(panel, pi, tmp_path):
    _pi_panel(panel, pi, tmp_path)
    assert panel.camera_kind == adapters.CAMERA_PI
    assert not panel.camera_edit.isEnabled()            # Quelle nur für „Lokal“
    assert "Snapshot" in panel.camera_note.text()
    pi.requests.clear()
    assert panel.start_scan(), panel.last_error
    assert panel.wait(60000)
    assert panel.last_error == "" and panel.mosaic is not None
    tiles = pi.count("GET", "/api/camera/snapshot")
    assert tiles > 0 and pi.count("POST", "/api/action", "moveto") == tiles
    assert pi.count("POST", "/api/action", "jog") == 0


def test_panel_old_pi_uses_local_camera_with_note(panel, old_pi, tmp_path):
    _pi_panel(panel, old_pi, tmp_path)
    assert panel.camera_kind == adapters.CAMERA_LOCAL
    assert panel.camera_edit.isEnabled()
    assert "Jog-Schritten" in panel.camera_note.text()
    panel.set_camera_kind(adapters.CAMERA_PI)            # Nutzer will trotzdem Pi-Kamera
    assert not panel.start_scan()
    assert "Snapshot/moveto" in panel.last_error


def test_panel_user_choice_sticks_and_precheck_blocks_without_g30(panel, pi, tmp_path):
    panel.set_camera_kind(adapters.CAMERA_LOCAL)
    pi.status["workpiece_surface_z"] = None
    pi.status["position"] = [0.0, 0.0, 20.0]             # Scanhöhe 40 ≠ Z20
    _pi_panel(panel, pi, tmp_path)
    assert panel.camera_kind == adapters.CAMERA_LOCAL     # nicht überschrieben
    panel.set_camera_kind(adapters.CAMERA_PI)
    pi.requests.clear()
    assert not panel.start_scan()
    assert "Fokus (G30)" in panel.last_error
    assert pi.count("POST", "/api/action") == 0 and pi.count("GET", "/api/camera/snapshot") == 0
