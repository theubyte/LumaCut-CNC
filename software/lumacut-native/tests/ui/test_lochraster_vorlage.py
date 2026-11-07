"""Template "Laser-Interface V2" in the real window at 1024 x 700: open it through the menu, the board and the note are
right, checks without errors, view from both sides, "Ins Projekt" onto two plates, Starten shows both layers.
Nothing moves, nothing lasers (the template itself says not to laser yet).

Alone, with its own simulator on 84xx and automation on 94xx:
    python tests/ui/test_lochraster_vorlage.py [exe]
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SHOTS = Path(os.environ.get("LUMACUT_SHOTS") or ROOT / "build-platine" / "shots")
sys.path.insert(0, str(HERE))
from test_lochraster import api, info, shown, idle, tab, free_port  # noqa: E402


def run(app):
    app.call("resize", w=1024, h=700)   # CI screen is small: everything must stay reachable
    app.click("nav-platine")
    app.wait(lambda: app.find("view-Platine")["w"] > 100)
    app.invoke("platine-api", "setMode", "lochraster")
    app.wait(lambda: shown(app, "pf-stage"))

    # Open through the menu, like the owner: "+" then the template entry.
    app.click("pf-new")
    app.wait(lambda: shown(app, "pf-new-menu-6"))
    app.click("pf-new-menu-6")
    app.wait(lambda: info(app)["parts"] == 18, timeout=10)
    i = info(app)
    assert i["cols"] == 32 and i["rows"] == 26 and abs(i["width"] - 90) < 1e-9 and abs(i["height"] - 70) < 1e-9, i
    assert i["wires"] == 23 and i["labels"] >= 9, i
    assert sorted(i["refs"]) == sorted(["C1", "C2", "C3", "D1", "F1", "J1", "J2", "J3", "J4", "K1", "LED1",
                                        "R1", "R4", "R5", "R6", "R7", "U1", "U2"]), i
    sel = api(app, "selectRef", "U2")
    assert sel["pins"] == "UQ, TQ, SQ" and sel["value"] == "LM317T", sel
    assert api(app, "selectRef", "K1")["value"] == "NAIS JS1-24V"
    assert api(app, "selectRef", "R5")["value"] == "5k6"
    assert api(app, "selectRef", "J1")["pins"] == "D'E, D'C"
    api(app, "selectRef", "C3")
    app.key(0x01000000)   # Esc: nothing selected for the pictures
    idle(app)

    # Checks: hints only, the note about measuring the relay and not lasering yet is shown.
    tab(app, "check")
    checks = api(app, "checks")
    assert not any(c["tone"] == "bad" for c in checks), checks
    note = next(c for c in checks if c["id"] == "note")
    assert "Pins vor dem Verdrahten messen" in note["text"] and "Noch nicht lasern" in note["text"], note
    tab(app, "board")
    assert app.get("pf-note", "visible") is True
    app.shot(SHOTS / "lochraster-vorlage-1-oben.png")

    app.click("pf-view-true")
    app.wait(lambda: info(app)["viewBelow"] is True)
    idle(app)
    x0 = api(app, "holeWin", [0, 0])[0]
    x31 = api(app, "holeWin", [31, 0])[0]
    assert x0 > x31, (x0, x31)
    app.shot(SHOTS / "lochraster-vorlage-2-unten.png")
    app.click("pf-view-false")

    # Into the project: two plates, process Markieren only.
    app.click("pf-to-project")
    app.wait(lambda: shown(app, "view-Start"), timeout=10)
    app.wait(lambda: any(r.get("name") == "Lochraster Bestückungsseite" for r in app.invoke("start-api", "layers")), timeout=20)
    time.sleep(0.6)
    app.shot(SHOTS / "lochraster-vorlage-3-starten-oben.png")
    app.click("start-plate-1")
    app.wait(lambda: any(r.get("name") == "Lochraster Lötseite" for r in app.invoke("start-api", "layers")), timeout=20)
    time.sleep(0.6)
    app.shot(SHOTS / "lochraster-vorlage-4-starten-unten.png")
    app.click("nav-motiv")
    app.wait(lambda: app.find("stage")["w"] > 100)
    project = json.loads(app.invoke("view-Motiv", "toJson", 0))
    layers = {l["id"]: l for l in project["layers"]}
    ours = [e for e in project["elements"] if e["kind"] == "Lochraster"]
    assert {e.get("plate", 0) for e in ours} == {0, 1}, ours
    assert all(layers[e["layerId"]]["process"] == "Markieren" and layers[e["layerId"]]["mode"] == "LINE" for e in ours)


def main():
    from driver import App
    exe = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("LUMACUT_EXE") or str(ROOT / "build-platine" / "LumaCutStudio.exe")
    port = free_port(int(os.environ.get("LOCHRASTER_SIM_PORT", "8431")))
    sim = subprocess.Popen([sys.executable, str(ROOT / "tools" / "sim_pi.py"), "--port", str(port)],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env={**os.environ, "PYTHONUTF8": "1"})
    app = None
    try:
        time.sleep(5)
        app = App(exe=exe, port=port + 1000, pi_url=f"http://127.0.0.1:{port}")
        app.wait(lambda: app.stats()["firstFrameMs"] > 0, timeout=30)
        run(app)
        print("OK    test_lochraster_vorlage", flush=True)
    except Exception:
        if app:
            try:
                app.shot(SHOTS / "fehler-test_lochraster_vorlage.png")
            except Exception:
                pass
        raise
    finally:
        if app:
            app.close()
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(sim.pid)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


if __name__ == "__main__":
    main()
