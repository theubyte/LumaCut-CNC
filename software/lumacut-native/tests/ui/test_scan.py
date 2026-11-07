"""Head camera in the real window against the simulator: workplace scan of a part with go, the picture on the Pi,
the scan as background in Motiv and Starten, a scan from another device taken over, the live window.
The simulator's camera sees 90 mm across the picture, centred on the head: the test stores that as calibration."""
import json
import os
import struct
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SHOTS = Path(os.environ["LUMACUT_EXE"]).parent / "shots" if os.environ.get("LUMACUT_EXE") else ROOT / "build" / "shots"
P = "scan-panel"


def api(app, path, data=None, method=None, raw=False, ctype="application/json"):
    body = data if isinstance(data, (bytes, type(None))) else json.dumps(data).encode()
    req = urllib.request.Request(app.invoke("shell", "piUrl") + path, data=body, method=method, headers={"Content-Type": ctype})
    with urllib.request.urlopen(req, timeout=10) as r:
        return (r.read(), dict(r.headers)) if raw else json.load(r)


def store_sim_calibration(app):
    cur = api(app, "/api/camera/calibration")
    hx, hy = 45.0, 45.0 * 480 / 640
    android = {"photoWidth": 640, "photoHeight": 480, "scanZ": 40.0,
               "photo": [{"x": 0, "y": 0}, {"x": 640, "y": 0}, {"x": 640, "y": 480}, {"x": 0, "y": 480}],
               "relMm": [{"x": -hx, "y": -hy}, {"x": hx, "y": -hy}, {"x": hx, "y": hy}, {"x": -hx, "y": hy}]}
    api(app, "/api/camera/calibration", {"revision": cur.get("revision", 0), "calibrated": True, "image_width": 640, "image_height": 480,
                                         "scan_z": 40.0, "notes": "Simulator, vier Ecken", "updated_by": "Test", "android": android}, method="PUT")


def pi_status(app):
    return json.load(urllib.request.urlopen(app.invoke("shell", "piUrl") + "/api/status", timeout=5))


def state(app):
    return app.invoke(P, "state", 0)


def png_size(data):
    assert data[:8] == b"\x89PNG\r\n\x1a\n", data[:8]
    return struct.unpack(">II", data[16:24])


def red_png(w, h):
    import zlib
    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d))
    raw = b"".join(b"\0" + b"\xff\x20\x20" * w for _ in range(h))
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


def run(app):
    app.call("resize", w=1024, h=700)
    # The simulator starts without reference: reference run with go, as the owner would.
    app.click("nav-maschine"); time.sleep(0.3)
    app.click("m-tab-steuerung"); time.sleep(0.2)
    app.click("m-home"); time.sleep(0.2)
    app.click("go-confirm")
    app.wait(lambda: app.get("m-homed", "text") == "Ja", timeout=20)
    app.click("nav-motiv")
    app.wait(lambda: app.find("view-Motiv"))
    app.invoke("view-Motiv", "reset", 0)

    # Without calibration: a clear sentence and the way to Kalibrieren, no scan.
    app.click("bg-button")
    time.sleep(0.3)
    app.wait(lambda: "kalibriert" in state(app)["note"] or "Kalibrierung" in state(app)["note"], timeout=8)
    assert not state(app)["calibrated"]
    assert app.get("scan-uncalibrated", "visible") is True
    assert app.get("scan-start", "active") is False
    app.shot(SHOTS / "scan-ohne-kalibrierung.png")

    store_sim_calibration(app)
    app.invoke(P, "reloadCalibration", 0)
    app.wait(lambda: state(app)["calibrated"], timeout=8)

    # Calibrated at Z 40, but Z stands elsewhere and no surface is measured: the Pi would not move Z,
    # and flat over the bed the head could hit objects. Locked with the sentence, nothing moves.
    z_now = pi_status(app)["position"][2]
    assert pi_status(app)["workpiece_surface_z"] is None and abs(z_now - 40) > 1, pi_status(app)
    app.wait(lambda: state(app)["lock"].startswith("Zuerst abtasten"), timeout=8)
    assert app.get("scan-start", "active") is False
    assert "Z 40,0" in state(app)["lock"], state(app)["lock"]
    app.invoke(P, "scanArea", [120, 120, 240, 200])
    time.sleep(0.3)
    try:
        go_open = app.get("go-confirm", "visible")
    except RuntimeError:
        go_open = False
    assert not go_open and not state(app)["running"]
    assert pi_status(app)["position"][2] == z_now

    # Probe the plate first (Maschine, with go), then the scan may go.
    app.key(0x01000000)
    app.click("nav-maschine"); time.sleep(0.3)
    app.click("m-moveto"); time.sleep(0.2)
    app.click("go-confirm"); time.sleep(0.8)
    app.click("m-probe"); time.sleep(0.2)
    app.click("go-confirm")
    app.wait(lambda: pi_status(app)["workpiece_surface_z"] is not None, timeout=20)
    app.click("nav-motiv")
    app.wait(lambda: app.find("view-Motiv"))
    app.click("bg-button"); time.sleep(0.3)
    app.wait(lambda: state(app)["lock"] == "", timeout=8)

    # The scan button asks for a go; no means nothing moves.
    app.click("scan-region-all")
    app.click("scan-start")
    app.wait(lambda: app.get("go-confirm", "visible"), timeout=5)
    assert "ohne Laser" in app.get("go-detail", "text")
    app.click("go-cancel")
    time.sleep(0.3)
    assert not state(app)["running"]

    # A part of the bed: 120..240 × 120..200 mm, four pictures, after the go.
    app.invoke(P, "scanArea", [120, 120, 240, 200])
    app.wait(lambda: app.get("go-confirm", "visible"), timeout=5)
    assert "4 Bilder" in app.get("go-detail", "text"), app.get("go-detail", "text")
    assert "Scanhöhe Z 40,0" in app.get("go-detail", "text"), app.get("go-detail", "text")
    app.click("go-confirm")
    app.wait(lambda: state(app)["running"], timeout=5)
    app.wait(lambda: not state(app)["running"], timeout=90)
    s = state(app)
    assert "gespeichert" in s["result"], s
    assert s["bgLoaded"] and s["bgOn"], s
    # The pictures were taken at the calibration's height; Z held there.
    assert abs(pi_status(app)["position"][2] - 40) <= 0.1, pi_status(app)["position"]

    # On the Pi, for Android too: a PNG of the whole work area at 5 px/mm.
    data, headers = api(app, "/api/workspace/scan", raw=True)
    w, h = png_size(data)
    assert w > 1000 and h > 1000, (w, h)
    assert int(headers.get("X-Revision", 0)) == s["rev"], (headers.get("X-Revision"), s)

    # In the motif: the darker plate of the simulated bed shows inside the scanned part, the sheet outside.
    app.key(0x01000000)   # close the popover
    app.invoke("view-Motiv", "setTool", "rect")   # hides the invitation on the empty plate
    time.sleep(0.4)
    inside = app.invoke("view-Motiv", "win", [180, 160])
    on = app.call("pixel", x=inside[0], y=inside[1])
    app.invoke(P, "showBackground", False)
    time.sleep(0.3)
    off = app.call("pixel", x=inside[0], y=inside[1])
    assert abs(on["r"] - off["r"]) + abs(on["g"] - off["g"]) + abs(on["b"] - off["b"]) > 25, (on, off)
    app.invoke(P, "showBackground", True)
    time.sleep(0.3)
    app.shot(SHOTS / "scan-motiv.png")
    app.invoke("view-Motiv", "setTool", "select")

    # Starten shows the same background under the job.
    app.invoke("view-Motiv", "sample", 0)
    time.sleep(0.5)
    app.click("nav-start")
    app.wait(lambda: app.find("start-scan-show"), timeout=8)
    assert app.get("start-scan", "visible") is True
    assert app.get("start-scan", "hasImage") is True
    time.sleep(0.5)
    app.shot(SHOTS / "scan-starten.png")
    app.click("nav-motiv")
    app.wait(lambda: app.find("view-Motiv"))
    time.sleep(0.3)

    # Live window and the rectified picture at the head position.
    app.click("bg-button")
    time.sleep(0.2)
    app.click("live-window")
    app.click("live-overlay")
    app.key(0x01000000)
    app.wait(lambda: state(app)["frames"] >= 3, timeout=20)
    assert app.get("live-image", "hasImage") is True
    # The rectified picture lies around the head: the camera sees 90 × 67.5 mm centred on it.
    app.wait(lambda: state(app)["overlayArea"] != "", timeout=10)
    import re
    x0, x1, y0, y1 = map(int, re.findall(r"-?\d+", state(app)["overlayArea"]))
    pos = app.invoke("shell", "machine", "position")
    travel_x = json.load(urllib.request.urlopen(app.invoke("shell", "piUrl") + "/api/status", timeout=5))["config"]["travels"]["x"]
    assert abs((x1 - x0) - 90) <= 1 and abs((y1 - y0) - 68) <= 1, state(app)["overlayArea"]
    assert abs((x0 + x1) / 2 - (travel_x - pos[0])) <= 1 and abs((y0 + y1) / 2 - pos[1]) <= 1, (state(app)["overlayArea"], pos)
    app.invoke("view-Motiv", "setTool", "rect")
    time.sleep(0.8)
    app.shot(SHOTS / "scan-live.png")
    app.invoke("view-Motiv", "setTool", "select")
    app.click("live-close")
    time.sleep(0.3)
    assert not state(app)["liveOn"] and not state(app)["overlay"], state(app)

    # Another device scans: the new revision is taken over by itself.
    rev = json.load(urllib.request.urlopen(app.invoke("shell", "piUrl") + "/api/status", timeout=5))["sync"]["scan"]
    req = urllib.request.Request(app.invoke("shell", "piUrl") + f"/api/workspace/scan?base_revision={rev}&by=Tablet", data=red_png(390, 370),
                                 method="PUT", headers={"Content-Type": "image/png"})
    urllib.request.urlopen(req, timeout=5).read()
    app.wait(lambda: state(app)["rev"] == rev + 1, timeout=10)
    assert "vom Pi" in state(app)["stamp"], state(app)

