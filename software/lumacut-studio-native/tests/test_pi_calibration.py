"""Kamera-Kalibrierung auf dem Pi: Client (HTTP), Abbildung und Scan-Panel mit Fake-Pi."""
from __future__ import annotations

import copy
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

import _paths  # noqa: F401  (src/ auf sys.path)
from machine.client import ApiError, LumaCutClient
from scanprobe import adapters, pi_calibration
from scanprobe.calibration import CameraCalibration

PLACEHOLDER = dict(adapters.default_calibration().to_dict(), schema_version=1, revision=0,
                   updated_at="", updated_by="", notes="", calibrated=False, placeholder=True,
                   status="platzhalter",
                   storage={"path": "/etc/lumacut/camera_calibration.json", "writable": True,
                            "error": ""})


def measured_cal() -> CameraCalibration:
    return CameraCalibration(1280, 720, px_per_mm=7.5, scan_z=35.0, offset_mm=(28.5, -21.0),
                             flip_y=-1)


class FakeCalibrationPi:
    """Speichert wie pi400/marlin/camera_calibration.py (Revision, 409)."""

    def __init__(self):
        self.record = copy.deepcopy(PLACEHOLDER)
        self.puts: list[dict] = []
        self.supported = True
        self.unreachable = False

    def _check(self):
        from machine.client import ConnectionFailed
        if self.unreachable:
            raise ConnectionFailed("Pi nicht erreichbar (http://lumacut.local:8080): timed out")
        if not self.supported:
            raise ApiError("Pi lehnt ab (HTTP 404): nicht gefunden", 404, {"error": "nicht gefunden"})

    def camera_calibration(self):
        self._check()
        return copy.deepcopy(self.record)

    def put_camera_calibration(self, record, revision):
        self._check()
        self.puts.append(dict(record, revision=revision))
        if revision != self.record["revision"]:
            raise ApiError("Pi lehnt ab (HTTP 409): geändert", 409,
                           {"error": "Kalibrierung wurde inzwischen geändert (Revision %d)"
                                     % self.record["revision"], "current": self.camera_calibration()})
        self.record = dict(copy.deepcopy(record), schema_version=1,
                           revision=revision + 1, updated_at="2026-10-26T09:00:00Z",
                           placeholder=False, storage=PLACEHOLDER["storage"],
                           status="kalibriert" if record["calibrated"] else "unkalibriert")
        return copy.deepcopy(self.record)


# ---------------------------------------------------------------- Client/HTTP
class _Server:
    def __init__(self, routes=True):
        self.record = copy.deepcopy(PLACEHOLDER)
        self.requests = []
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _reply(self, code, data):
                raw = json.dumps(data).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_GET(self):
                fake.requests.append(("GET", self.path, dict(self.headers), b""))
                if routes and self.path == "/api/camera/calibration":
                    return self._reply(200, fake.record)
                self._reply(404, {"error": "nicht gefunden"})

            def do_PUT(self):
                body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
                fake.requests.append(("PUT", self.path, dict(self.headers), body))
                if not routes:
                    return self._reply(405, {"error": "Methode nicht erlaubt"})
                data = json.loads(body)
                if data["revision"] != fake.record["revision"]:
                    return self._reply(409, {"error": "Kalibrierung wurde inzwischen geändert",
                                             "current": fake.record})
                fake.record = dict(data, revision=data["revision"] + 1, placeholder=False)
                self._reply(200, fake.record)

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = "http://127.0.0.1:%d" % self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture()
def server():
    s = _Server()
    yield s
    s.close()


def test_client_get_put_sends_json_and_revision(server):
    client = LumaCutClient(server.url, "k")
    assert client.camera_calibration()["placeholder"] is True
    rec = measured_cal().to_dict()
    saved = client.put_camera_calibration(rec, 0)
    assert saved["revision"] == 1
    method, path, headers, body = server.requests[-1]
    assert (method, path) == ("PUT", "/api/camera/calibration")
    assert headers["Content-Type"] == "application/json"
    assert json.loads(body)["revision"] == 0 and json.loads(body)["px_per_mm"] == 7.5
    with pytest.raises(ApiError) as ctx:
        client.put_camera_calibration(rec, 0)
    assert ctx.value.status == 409 and ctx.value.payload["current"]["revision"] == 1


def test_fetch_and_store_map_conflict_and_old_pi(server):
    client = LumaCutClient(server.url, "")
    pc = pi_calibration.fetch(client)
    assert pc.placeholder and pc.revision == 0 and "Platzhalter" in pc.status_text()
    saved = pi_calibration.store(client, measured_cal(), 0, updated_by="Test")
    assert saved.revision == 1 and saved.calibrated and saved.calibration.px_per_mm == 7.5
    with pytest.raises(pi_calibration.Conflict) as ctx:
        pi_calibration.store(client, measured_cal(), 0)
    assert "inzwischen geändert" in str(ctx.value) and ctx.value.current.revision == 1
    old = _Server(routes=False)
    try:
        with pytest.raises(pi_calibration.NotSupported, match="Pi-Software zu alt"):
            pi_calibration.fetch(LumaCutClient(old.url, ""))
        with pytest.raises(pi_calibration.NotSupported):
            pi_calibration.store(LumaCutClient(old.url, ""), measured_cal(), 0)
    finally:
        old.close()


def test_unreachable_pi_is_german():
    client = LumaCutClient("http://127.0.0.1:9", "")
    with pytest.raises(pi_calibration.Unreachable, match="Pi nicht erreichbar"):
        pi_calibration.fetch(client)


def test_from_dict_ignores_pi_metadata_and_keeps_homography():
    data = dict(PLACEHOLDER, homography=[[1, 0, 0], [0, 1, 0], [0, 0, 1]], message="ok")
    cal = CameraCalibration.from_dict(data)
    assert cal.homography[0][0] == 1 and cal.px_per_mm == 4.0
    assert pi_calibration.is_placeholder_values(adapters.default_calibration())
    assert not pi_calibration.is_placeholder_values(measured_cal())
    with pytest.raises(TypeError):
        CameraCalibration.from_dict(dict(PLACEHOLDER, tippfehler=1))


# ---------------------------------------------------------------- Panel
@pytest.fixture()
def panel(qapp):
    from scanprobe.panel import MODE_PI, ScanPanel
    pi = FakeCalibrationPi()
    p = ScanPanel(None, client_provider=lambda: pi, ask=False)
    p.fake_pi = pi
    p.set_mode(MODE_PI)
    yield p
    p.shutdown()


def test_panel_fetches_from_pi_and_never_uses_placeholder(panel):
    assert panel.pi_calibration is not None and panel.pi_calibration.placeholder
    assert panel.calibration is None
    assert "Platzhalter" in panel.cal_label.text()
    assert not panel.start_scan()
    assert "keine Kalibrierung gespeichert" in panel.last_error
    assert "camera.json importieren" in panel.last_error


def test_panel_import_then_save_to_pi_and_reload(panel, tmp_path):
    p = tmp_path / "camera.json"
    measured_cal().save(p)
    panel.load_calibration(p)
    assert "nicht auf dem Pi gespeichert" in panel.cal_label.text()
    assert panel.pi_save_button.isEnabled()
    assert panel.save_calibration_to_pi(notes="Fadenkreuz-Test")
    put = panel.fake_pi.puts[-1]
    assert put["revision"] == 0 and put["calibrated"] is True and put["notes"] == "Fadenkreuz-Test"
    assert put["updated_by"].startswith("LumaCut Studio")
    assert "Revision 1" in panel.cal_label.text() and "kalibriert" in panel.cal_label.text()
    # Anderer Client: Panel neu → holt Revision 1 vom Pi, nicht aus camera.json
    from scanprobe.panel import MODE_PI, ScanPanel
    other = ScanPanel(None, client_provider=lambda: panel.fake_pi, ask=False)
    try:
        other.set_mode(MODE_PI)
        assert other.calibration.px_per_mm == 7.5 and other.pi_calibration.revision == 1
    finally:
        other.shutdown()
    # Export bleibt möglich
    out = tmp_path / "export.json"
    panel.export_calibration(out)
    assert CameraCalibration.load(out).px_per_mm == 7.5


def test_panel_conflict_keeps_local_values(panel, tmp_path):
    p = tmp_path / "camera.json"
    measured_cal().save(p)
    panel.load_calibration(p)
    panel.fake_pi.record["revision"] = 5          # inzwischen von anderem Client gespeichert
    assert not panel.save_calibration_to_pi()
    assert "inzwischen geändert" in panel.last_error
    assert panel.calibration.px_per_mm == 7.5 and panel.calibration_dirty
    assert panel.pi_calibration.revision == 5
    assert panel.save_calibration_to_pi()           # zweiter Versuch mit neuer Revision
    assert panel.fake_pi.record["revision"] == 6


def test_panel_old_or_unreachable_pi_falls_back_to_camera_json(qapp, tmp_path):
    from scanprobe.panel import MODE_PI, ScanPanel
    pi = FakeCalibrationPi()
    pi.supported = False
    panel = ScanPanel(None, client_provider=lambda: pi, ask=False)
    try:
        panel.set_mode(MODE_PI)
        assert "Pi-Software zu alt" in panel.cal_label.text()
        assert not panel.start_scan() and "Pi-Software zu alt" in panel.last_error
        p = tmp_path / "camera.json"
        measured_cal().save(p)
        panel.load_calibration(p)
        assert panel.calibration.px_per_mm == 7.5   # lokal weiter nutzbar
        assert not panel.save_calibration_to_pi()
        assert "Pi-Software zu alt" in panel.last_error
        pi.supported, pi.unreachable = True, True
        assert panel.refresh_pi_calibration(report=True) is None
        assert "Pi nicht erreichbar" in panel.last_error
    finally:
        panel.shutdown()


def test_simulation_mode_does_not_touch_pi(qapp):
    from scanprobe.panel import ScanPanel
    calls = []
    panel = ScanPanel(None, client_provider=lambda: calls.append(1), ask=False)
    try:
        assert calls == [] and not panel.pi_cal_button.isEnabled()
        assert not panel.pi_save_button.isEnabled()
    finally:
        panel.shutdown()
