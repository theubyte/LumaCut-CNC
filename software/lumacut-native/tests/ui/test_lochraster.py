"""Lochraster in the real window: template 50 x 70, DIP-8 placed with the mouse, resistor, LED, two connections (one
drawn with the mouse), a label, checks with a short and undo, view from below, parts list and assistant, file and
exports, "Ins Projekt" onto two plates, Starten shows both layers. Nothing moves, nothing lasers.

Alone, with its own simulator on 84xx and automation on 94xx:
    python tests/ui/test_lochraster.py [exe]
"""
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SHOTS = Path(os.environ.get("LUMACUT_SHOTS") or ROOT / "build-platine" / "shots")
CTRL = 0x04000000
K_ESC, K_R, K_Z = 0x01000000, 0x52, 0x5A


def api(app, method, arg=0):
    return app.invoke("lochraster-api", method, arg)


def info(app):
    return api(app, "info")


def shown(app, name):
    return any(it["name"] == name for it in app.tree())


def idle(app):
    app.wait(lambda: not info(app)["busy"], timeout=20)
    time.sleep(0.3)


def click_hole(app, c, r, mods=0):
    x, y = api(app, "holeWin", [c, r])
    app.call("mouse", x=x, y=y, type="move", mods=mods)
    app.call("mouse", x=x, y=y, type="press", mods=mods)
    app.call("mouse", x=x, y=y, type="release", mods=mods)
    time.sleep(0.15)


def tab(app, name):
    """Opens a tab of the right panel and waits until it is really shown."""
    app.click("pf-tabs-" + name)
    app.wait(lambda: app.get("pf-tabs", "value") == name, timeout=10)
    time.sleep(0.2)


def check_ids(app):
    return [c["id"] for c in api(app, "checks")]


def run(app):
    app.call("resize", w=1024, h=700)   # CI screen is small: everything must stay reachable
    app.click("nav-platine")
    app.wait(lambda: app.find("view-Platine")["w"] > 100)
    app.invoke("platine-api", "setMode", "lochraster")
    app.wait(lambda: shown(app, "pf-stage"))
    assert shown(app, "pcb-mode-gerber") and shown(app, "pcb-mode-lochraster")

    # Template 50 x 70: 18 x 24 holes. Switching templates through the bar works.
    i = api(app, "newDesign", 3)
    assert i["cols"] == 18 and i["rows"] == 24 and i["parts"] == 0, i
    app.click("pf-template-0")
    assert info(app)["cols"] == 6 and info(app)["rows"] == 28
    app.click("pf-template-3")
    assert info(app)["cols"] == 18 and abs(info(app)["width"] - 50) < 1e-9

    # DIP-8 with the mouse: pick it in the library, click the hole for pin 1 (I7).
    app.click("pf-lib-dip8")
    assert info(app)["tool"] == "part"
    click_hole(app, 8, 6)
    i = info(app)
    assert i["refs"] == ["U1"], i
    sel = api(app, "selection")
    assert sel["kind"] == "part" and sel["pins"].startswith("I7, I8, I9, I10, L10"), sel
    app.key(K_ESC)
    assert info(app)["tool"] == "select"

    # Resistor and LED, then turn the LED with R after selecting it with the mouse.
    assert api(app, "place", ["res-762", 2, 4]) == "R1"
    assert api(app, "place", ["led-5", 3, 13]) == "LED1"
    app.key(K_ESC)
    click_hole(app, 3, 13)
    assert api(app, "selection")["ref"] == "LED1"
    app.key(K_R, 0, "r")
    assert api(app, "selection")["rot"] == 90, api(app, "selection")
    app.key(K_Z, CTRL)
    assert api(app, "selectRef", "LED1")["rot"] == 0

    # Connection 1 with the mouse: R1 pin 2 (F5) to U1 pin 1 (I7) on the solder side.
    app.click("pf-tool-wire")
    click_hole(app, 5, 4)
    click_hole(app, 8, 6)
    app.key(K_ESC)
    app.key(K_ESC)
    i = info(app)
    assert i["wires"] == 1, i
    # Connection 2: LED cathode (E14) to U1 pin 4 (I10), wire bridge on the component side.
    assert api(app, "wire", [4, 13, 8, 9, False]) == 2
    # A label in the free margin at the bottom.
    assert api(app, "label", ["BLINK", 25, 67.5]) == 1
    idle(app)
    ids = check_ids(app)
    assert "materialtest" in ids, ids
    assert not any(c["tone"] == "bad" for c in api(app, "checks")), api(app, "checks")
    i = info(app)
    assert i["componentLines"] > 0 and i["solderLines"] > 0, i

    # A deliberate short: a second solder bridge across the first one. Undo removes it.
    api(app, "wire", [7, 2, 7, 8, True])
    assert "short" in check_ids(app), check_ids(app)
    api(app, "undo")
    assert "short" not in check_ids(app)
    # Text too small for the beam is reported.
    api(app, "selectRef", "U1")
    api(app, "label", ["klein", 25, 2.2])
    api(app, "setSel", ["height", 0.6])
    assert "text-small" in check_ids(app)
    api(app, "undo")
    api(app, "undo")
    assert "text-small" not in check_ids(app)

    tab(app, "check")
    idle(app)
    app.shot(SHOTS / "lochraster-1-oben-dunkel.png")

    # From below: solder side, mirrored.
    app.click("pf-view-true")
    assert info(app)["viewBelow"] is True
    idle(app)
    x0 = api(app, "holeWin", [0, 0])[0]
    x17 = api(app, "holeWin", [17, 0])[0]
    assert x0 > x17, (x0, x17)   # column A is on the right when seen from below
    app.shot(SHOTS / "lochraster-2-unten-dunkel.png")
    app.click("pf-view-false")

    # Parts list and assistant: resistor first, LED last.
    tab(app, "bom")
    rows = api(app, "bom")
    assert [r["refs"] for r in rows] == ["R1", "U1", "LED1"], rows
    # Without a GPU (CI) the tab builds slowly: wait for the button and for each step instead of asserting at once.
    app.wait(lambda: app.get("pf-assist-start", "visible"), timeout=10)
    app.click("pf-assist-start")
    app.wait(lambda: info(app)["assist"] == 0, timeout=10)
    app.wait(lambda: app.get("pf-assist-title", "text").endswith(": R1"), timeout=10)
    app.click("pf-assist-next")
    app.wait(lambda: info(app)["assist"] == 1, timeout=10)
    app.shot(SHOTS / "lochraster-3-bestueckung.png")

    # File round trip and exports.
    tmp = Path(tempfile.mkdtemp(prefix="lochraster-"))
    assert api(app, "save", str(tmp / "blinker.lumaraster"))
    saved = json.loads((tmp / "blinker.lumaraster").read_text(encoding="utf-8"))
    assert saved["format"] == "lumaraster" and saved["version"] == 1 and len(saved["parts"]) == 3
    api(app, "newDesign", 1)
    assert info(app)["parts"] == 0
    assert api(app, "open", str(tmp / "blinker.lumaraster"))
    assert info(app)["refs"] == ["U1", "R1", "LED1"] and info(app)["wires"] == 2
    for fmt in ("csv", "png", "svg"):
        assert api(app, "exportTo", [str(tmp / ("plan." + fmt)), fmt])
    csv = (tmp / "plan.csv").read_bytes().decode("utf-8-sig")
    assert csv.startswith("Referenz;Wert;Bauteil;Anzahl") and "U1;NE555;IC-Sockel DIP-8;1" in csv, csv
    assert (tmp / "plan.png").read_bytes()[:4] == b"\x89PNG"
    assert b"<svg" in (tmp / "plan.svg").read_bytes()

    # Into the project: component side and mirrored solder side on two plates, process Markieren only.
    bx, by = api(app, "bed")
    assert abs(bx - 185) < 1e-9 and abs(by - 197.5) < 1e-9
    tab(app, "board")
    app.click("pf-to-project")
    app.wait(lambda: shown(app, "view-Start"), timeout=10)
    app.wait(lambda: any(r.get("name") == "Lochraster Bestückungsseite" for r in app.invoke("start-api", "layers")), timeout=20)
    time.sleep(0.6)
    app.shot(SHOTS / "lochraster-4-starten-oben.png")
    app.click("start-plate-1")
    app.wait(lambda: any(r.get("name") == "Lochraster Lötseite" for r in app.invoke("start-api", "layers")), timeout=20)
    time.sleep(0.6)
    app.shot(SHOTS / "lochraster-5-starten-unten.png")

    app.click("nav-motiv")
    app.wait(lambda: app.find("stage")["w"] > 100)
    project = json.loads(app.invoke("view-Motiv", "toJson", 0))
    layers = {l["id"]: l for l in project["layers"]}
    ours = [e for e in project["elements"] if e["kind"] == "Lochraster"]
    assert {e.get("plate", 0) for e in ours} == {0, 1}, ours
    for e in ours:
        layer = layers[e["layerId"]]
        assert layer["name"].startswith("Lochraster") and layer["mode"] == "LINE", layer
        assert layer["process"] == "Markieren", layer
        assert layer["powerPct"] >= 8

    # Light theme.
    app.click("nav-optionen")
    app.wait(lambda: shown(app, "o-theme-seg-light"))
    app.click("o-theme-seg-light")
    app.click("nav-platine")
    app.wait(lambda: shown(app, "pf-stage"))
    tab(app, "board")
    time.sleep(0.6)
    app.shot(SHOTS / "lochraster-6-hell.png")
    app.click("pf-view-true")
    time.sleep(0.5)
    app.shot(SHOTS / "lochraster-7-unten-hell.png")
    app.click("pf-view-false")


def listening(port):
    import socket
    with socket.socket() as s:
        s.settimeout(0.3)
        return s.connect_ex(("127.0.0.1", port)) == 0


def free_port(start):
    """Simulator and automation port both free. An older app still on the automation port would otherwise answer
    in place of the new one and vanish mid-test (ConnectionResetError at the first call)."""
    for p in range(start, 8499):
        if not listening(p) and not listening(p + 1000):
            return p
    raise RuntimeError("Kein freier Port zwischen %d und 8499" % start)


def main():
    sys.path.insert(0, str(HERE))
    from driver import App
    exe = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("LUMACUT_EXE") or str(ROOT / "build-platine" / "LumaCutStudio.exe")
    port = free_port(int(os.environ.get("LOCHRASTER_SIM_PORT", "8421")))
    sim = subprocess.Popen([sys.executable, str(ROOT / "tools" / "sim_pi.py"), "--port", str(port)],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env={**os.environ, "PYTHONUTF8": "1"})
    app = None
    try:
        time.sleep(5)
        app = App(exe=exe, port=port + 1000, pi_url=f"http://127.0.0.1:{port}")
        app.wait(lambda: app.stats()["firstFrameMs"] > 0, timeout=30)
        run(app)
        print("OK    test_lochraster", flush=True)
    except Exception:
        if app:
            try:
                app.shot(SHOTS / "fehler-test_lochraster.png")
            except Exception:
                pass
        raise
    finally:
        if app:
            app.close()
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(sim.pid)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


if __name__ == "__main__":
    main()
