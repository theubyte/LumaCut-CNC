"""Platine in the real window: load files (through the test handle, not the native dialog), example board, isolation,
bottom side mirrored, layer toggles, "Ins Projekt" onto its own plate and on to Starten. Nothing moves, nothing lasers.

Alone, with its own simulator on 84xx and automation on 94xx:
    python tests/ui/test_platine.py [exe]
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PCB = ROOT / "tests" / "pcb"
SHOTS = Path(os.environ.get("LUMACUT_SHOTS") or ROOT / "build-platine" / "shots")


def api(app, method, arg=0):
    return app.invoke("platine-api", method, arg)


def info(app):
    return api(app, "info")


def settle(app, since=None, timeout=20):
    """Waits until the worker is done and, if given, the plan revision moved past `since`."""
    app.wait(lambda: not api(app, "busy") and (since is None or info(app)["revision"] > since), timeout=timeout)
    time.sleep(0.25)   # the GPU stage uploads after the plan arrives
    return info(app)


def layer(i, name):
    return next((l for l in i.get("layers", []) if l["name"] == name), None)


def shown(app, name):
    return any(it["name"] == name for it in app.tree())


def run(app):
    app.call("resize", w=1440, h=900)
    app.click("nav-platine")
    app.wait(lambda: app.find("view-Platine")["w"] > 100)
    app.invoke("platine-api", "setMode", "gerber")
    api(app, "clear")
    time.sleep(0.2)

    # Empty: one invitation with the two ways in.
    assert shown(app, "pcb-empty")
    assert shown(app, "pcb-example") and shown(app, "pcb-pick")

    # Own small files from tests/pcb: two pads, an outline, two holes.
    paths = [str(PCB / n) for n in ("zwei_pads.GTL", "zwei_pads.GKO", "zwei_pads.DRL")]
    api(app, "loadFiles", paths)
    i = settle(app, 0)
    assert i["files"] == 3 and i["kinds"] == ["copper-top", "outline", "drill"], i
    assert i["drills"] == 2, i
    assert abs(i["boardW"] - 20) < 0.01 and abs(i["boardH"] - 10) < 0.01, i
    assert abs(i["copperTop"] - 8) < 1e-6, i
    resist = layer(i, "Platine Ätzresist")
    # Raster negative at beam 0.15: board edge + 0.5 mm round minus two pads grown by half a beam.
    edge = 21 * 11 - (4 - 3.14159265) * 0.25
    pads = 2 * (2.15 * 2.15 - (4 - 3.14159265) * 0.075 ** 2)
    assert resist and resist["process"] == "Gravieren" and abs(resist["area"] - (edge - pads)) < 0.05, resist
    assert layer(i, "Platine Bohrmarken")["paths"] == 2, i

    # Example board: seven files, every layer recognised, 26 holes.
    rev = i["revision"]
    api(app, "loadExample")
    i = settle(app, rev)
    assert i["files"] == 7, i
    assert i["kinds"] == ["copper-top", "copper-bottom", "mask-top", "mask-bottom", "silk-top", "outline", "drill"], i
    assert i["drills"] == 26 and abs(i["boardW"] - 60) < 0.01 and abs(i["boardH"] - 40) < 0.01, i
    assert app.get("pcb-size", "text") == "60,0 × 40,0 mm"
    assert app.get("pcb-drills", "text") == "26"
    assert api(app, "shown") > 3
    assert all(c["tone"] != "bad" for c in api(app, "checks")), api(app, "checks")
    app.shot(SHOTS / "platine-1-raster.png")

    # Isolation with three lines per copper edge.
    rev = i["revision"]
    app.click("pcb-method-isolation")
    i = settle(app, rev)
    iso = layer(i, "Platine Ätzresist")
    assert iso and iso["process"] == "Markieren" and iso["paths"] > 0 and iso["area"] == 0, iso
    one = iso["paths"]
    rev = i["revision"]
    api(app, "set", ["passes", 1])
    i = settle(app, rev)
    assert layer(i, "Platine Ätzresist")["paths"] < one, (one, i)
    rev = i["revision"]
    api(app, "set", ["passes", 3])
    i = settle(app, rev)
    assert layer(i, "Platine Ätzresist")["paths"] == one
    rev = i["revision"]
    assert abs(api(app, "set", ["passSpacingMm", 0.2])["passSpacingMm"] - 0.2) < 1e-9
    i = settle(app, rev)
    app.shot(SHOTS / "platine-2-isolation.png")

    # The preview's layers can be hidden without new geometry.
    assert any(r["key"] == "copper" and r["shown"] for r in api(app, "viewLayers")), (api(app, "viewLayers"), info(app))
    app.click("pcb-layer-copper")
    assert any(r["key"] == "copper" and not r["shown"] for r in api(app, "viewLayers"))
    time.sleep(0.6)   # past the double-click interval, as a hand would be
    app.click("pcb-layer-copper")
    assert any(r["key"] == "copper" and r["shown"] for r in api(app, "viewLayers"))

    # Bottom side: mirrored by itself, the job keeps its size.
    rev = i["revision"]
    w, h = i["jobW"], i["jobH"]
    app.click("pcb-side-bottom")
    i = settle(app, rev)
    s = api(app, "set", ["mirror", True])
    assert s["side"] == "bottom" and s["mirror"] is True
    assert abs(i["jobW"] - w) < 1e-6 and abs(i["jobH"] - h) < 1e-6
    assert not any(c["id"] == "mirror" for c in api(app, "checks"))
    app.shot(SHOTS / "platine-3-unten.png")
    app.click("pcb-mirror")   # unmirrored bottom is flagged
    assert any(c["id"] == "mirror" for c in api(app, "checks"))
    time.sleep(0.6)
    app.click("pcb-mirror")
    rev = info(app)["revision"]
    app.click("pcb-side-top")
    i = settle(app, rev)
    assert api(app, "set", ["mirror", False])["mirror"] is False

    # Laser values: starting values, never below 8 %.
    app.click("pcb-tabs-laser")
    time.sleep(0.2)
    rows = api(app, "jobLayers")
    assert rows and rows[0]["key"] == "resist" and rows[0]["power"] >= 8, rows
    app.shot(SHOTS / "platine-4-lasern.png")
    app.click("pcb-tabs-steps")
    time.sleep(0.2)
    assert shown(app, "pcb-steps")
    app.shot(SHOTS / "platine-5-ablauf.png")
    app.click("pcb-tabs-settings")

    # Into the project: own plate, PCB layers with process names, on to Starten.
    app.click("pcb-to-project")
    app.wait(lambda: shown(app, "view-Start"), timeout=10)
    app.wait(lambda: any("Platine" in r.get("name", "") for r in app.invoke("start-api", "layers")), timeout=20)
    names = [r["name"] for r in app.invoke("start-api", "layers")]
    assert "Platine Ätzresist" in names and "Platine Bohrmarken" in names and "Platine Passmarken" in names, names
    time.sleep(0.6)
    app.shot(SHOTS / "platine-6-starten.png")

    # Back: the work is still there; a second "Ins Projekt" replaces on the same plate, no new plate.
    app.click("nav-platine")
    app.wait(lambda: shown(app, "pcb-to-project"))
    assert info(app)["files"] == 7
    app.click("pcb-to-project")
    app.wait(lambda: shown(app, "view-Start"), timeout=10)
    app.click("nav-motiv")
    app.wait(lambda: app.find("stage")["w"] > 100)
    project = json.loads(app.invoke("view-Motiv", "toJson", 0))
    platine = [e for e in project["elements"] if e["kind"] == "Platine"]
    plates = {e.get("plate", 0) for e in platine}
    assert len(plates) == 1, plates
    layers = {l["id"]: l for l in project["layers"]}
    used = {layers[e["layerId"]]["name"] for e in platine}
    assert "Platine Ätzresist" in used and "Platine Umriss" in used, used
    assert sum(1 for l in project["layers"] if l["name"] == "Platine Ätzresist") == 1
    out = {layers[e["layerId"]]["name"]: layers[e["layerId"]]["output"] for e in platine}
    assert out["Platine Ätzresist"] is True and out["Platine Umriss"] is False, out
    app.shot(SHOTS / "platine-7-motiv.png")

    # Light theme: the same view, colours only from the theme.
    app.click("nav-optionen")
    app.wait(lambda: shown(app, "o-theme-seg-light"))
    app.click("o-theme-seg-light")
    app.click("nav-platine")
    app.wait(lambda: shown(app, "pcb-preview"))
    time.sleep(0.6)
    app.shot(SHOTS / "platine-8-hell.png")


def main():
    sys.path.insert(0, str(HERE))
    from driver import App
    exe = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("LUMACUT_EXE") or str(ROOT / "build-platine" / "LumaCutStudio.exe")
    port = int(os.environ.get("PLATINE_SIM_PORT", "8411"))
    sim = subprocess.Popen([sys.executable, str(ROOT / "tools" / "sim_pi.py"), "--port", str(port)],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env={**os.environ, "PYTHONUTF8": "1"})
    app = None
    try:
        time.sleep(5)
        app = App(exe=exe, port=port + 1000, pi_url=f"http://127.0.0.1:{port}")
        app.wait(lambda: app.stats()["firstFrameMs"] > 0, timeout=30)
        run(app)
        print("OK    test_platine", flush=True)
    except Exception:
        if app:
            try:
                app.shot(SHOTS / "fehler-test_platine.png")
            except Exception:
                pass
        raise
    finally:
        if app:
            app.close()
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(sim.pid)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


if __name__ == "__main__":
    main()
