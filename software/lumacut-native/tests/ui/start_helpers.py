"""Shared for the Start tests: projects as files, the simulator's API, small waits. No logic of the app in here."""
import base64
import json
import math
import random
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path

K_RET, K_ESC, K_TAB, K_SPACE = 0x01000004, 0x01000000, 0x01000001, 0x20
SHOTS = Path(__file__).resolve().parents[2] / "build-start" / "shots"
TMP = Path(tempfile.mkdtemp(prefix="lumacut-start-"))


def layer(id="L0", name="Linie", mode="LINE", power=40.0, speed=1500.0, **kw):
    d = {"id": id, "name": name, "color": 4285314815, "mode": mode, "powerPct": power, "minPowerPct": 0.0, "speed": speed, "passes": 1,
         "intervalMm": 0.1, "overscanMm": 2.5, "zStepMm": 0.0, "output": True, "visible": True, "locked": False, "materialName": None,
         "thicknessMm": 0.0, "depthPerPassMm": 0.0, "toneCurve": [], "darkness": None}
    d.update(kw)
    return d


def element(paths, id="E1", layer_id="L0", kind="Stern", x=0.0, y=0.0, plate=0, **kw):
    d = {"id": id, "layerId": layer_id, "kind": kind, "transform": {"x": x, "y": y, "scaleX": 1, "scaleY": 1, "rotation": kw.pop("rotation", 0)},
         "paths": paths, "text": None, "fontSizeMm": 10, "bold": False, "fontFamily": "sans-serif", "raster": None, "imageWidthMm": 0, "imageHeightMm": 0,
         "imageMode": "GRAYSCALE", "adjust": {}, "groupId": None, "plate": plate}
    d.update(kw)
    return d


def star(cx=95.0, cy=95.0, r=45.0):
    pts = []
    for i in range(11):
        a = -math.pi / 2 + i * math.pi / 5
        k = r if i % 2 == 0 else r * 0.45
        pts.append({"x": cx + k * math.cos(a), "y": cy + k * math.sin(a)})
    return [pts]


def rect(x0, y0, w, h):
    return [[{"x": x0, "y": y0}, {"x": x0 + w, "y": y0}, {"x": x0 + w, "y": y0 + h}, {"x": x0, "y": y0 + h}, {"x": x0, "y": y0}]]


def image_element(w_px, h_px, w_mm, h_mm, x=40.0, y=50.0, rotation=0, seed=7, mode="DITHER", gray=None, **kw):
    if gray is None:
        rnd = random.Random(seed)
        gray = bytes(rnd.getrandbits(8) for _ in range(w_px * h_px))
    return element([], kind="Bild", x=x, y=y, rotation=rotation, raster={"width": w_px, "height": h_px, "grayBase64": base64.b64encode(gray).decode()},
                   imageWidthMm=w_mm, imageHeightMm=h_mm, imageMode=mode, **kw)


def project(title="Rennlauf", elements=None, layers=None, plates=1, name=None):
    doc = {"title": title, "layers": layers or [layer()], "elements": elements if elements is not None else [element(star())], "plateCount": plates, "activePlate": 0}
    path = TMP / ((name or title) + ".lumacut")
    path.write_text(json.dumps(doc), encoding="utf-8")
    return str(path).replace("\\", "/")


def open_project(app, path, wait_job=True):
    before = app.invoke("start-api", "revision")
    app.invoke("start-api", "openProject", path)
    app.wait(lambda: app.invoke("start-api", "revision") != before, timeout=60)
    if wait_job:
        app.wait(lambda: not app.invoke("start-api", "building"), timeout=120)


def checks(app):
    return {c["id"]: c["text"] for c in app.invoke("start-api", "checks")}


def base(app):
    return app.invoke("shell", "piUrl")


def pi_status(app):
    return json.load(urllib.request.urlopen(base(app) + "/api/status", timeout=5))


def pi_json(app, method, path, data=None, raw=None, ctype="application/json"):
    body = raw if raw is not None else (json.dumps(data).encode() if data is not None else None)
    req = urllib.request.Request(base(app) + path, data=body, method=method, headers={"Content-Type": ctype} if body is not None else {})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)


def pi_action(app, op, **fields):
    return pi_json(app, "POST", "/api/action", raw=urllib.parse.urlencode({"op": op, **fields}).encode(), ctype="application/x-www-form-urlencoded")


def set_material(app, name="Testpappel", thickness=8.0):
    w = pi_json(app, "GET", "/api/workspace")
    pi_json(app, "PUT", "/api/workspace", {"base_revision": w["revision"], "updated_by": "Test", "material": {"name": name, "thickness_mm": thickness}})
    app.wait(lambda: app.get("start-material", "text").startswith(name), timeout=8)


def add_tested_material(app, name="Testpappel", thickness=8.0):
    """An entry the operator saved: it counts as tried on this machine."""
    m = pi_json(app, "GET", "/api/materials")
    pi_json(app, "POST", "/api/materials", {"base_revision": m["revision"], "name": name, "thickness_mm": thickness, "process": "Schneiden", "mode": "line", "power_pct": 60, "speed_mm_min": 600, "passes": 1})


def is_open(app, name):
    return any(i["name"] == name for i in app.tree())


def wait_idle(app, timeout=60):
    def idle():
        s = pi_status(app)
        return s["job"]["state"] in ("idle", "complete", "aborted", "error") and s.get("owner") in ("Frei", None) and (s.get("frame") or {}).get("state") not in ("running", "starting")
    app.wait(idle, timeout=timeout, every=0.2)
    app.wait(lambda: app.get("start-go", "lock") == "" or True, timeout=2)


def shot(app, name):
    app.shot(SHOTS / f"start-{name}.png")
