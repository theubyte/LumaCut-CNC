"""Material view against the simulator: create, edit with base_revision, conflict, use, and the options around it."""
import json
import time
import urllib.request

K_RET, K_ESC, K_BACK, K_UP = 0x01000004, 0x01000000, 0x01000003, 0x01000013
CTRL = 0x04000000


def api(app, path, data=None, method=None):
    req = urllib.request.Request(app.invoke("shell", "piUrl") + path, data=json.dumps(data).encode() if data is not None else None,
                                 headers={"Content-Type": "application/json"}, method=method)
    return json.load(urllib.request.urlopen(req, timeout=5))


def entry(app, name, process):
    return next(m for m in api(app, "/api/materials")["materials"] if m["name"] == name and m["process"] == process)


def replace_text(app, name, text):
    app.click(name)
    time.sleep(0.05)
    app.key(0x41, CTRL)
    app.text(text)
    app.key(K_RET)


def run(app):
    app.click("nav-material")
    app.wait(lambda: app.get("mt-title", "text") != "")
    assert app.get("mt-use", "active") is True

    # Search filters the list only.
    app.click("mt-item-1"); time.sleep(0.1)
    title = app.get("mt-title", "text")
    app.click("mt-search"); app.text("schie"); time.sleep(0.2)
    assert app.get("mt-item-0", "title") == "Schiefer"
    assert app.get("mt-title", "text") == title
    for _ in range(5):
        app.key(K_BACK)
    time.sleep(0.2)

    # New material: rough start values, warned as untested.
    app.click("mt-new"); time.sleep(0.2)
    assert app.get("mt-save", "active") is False
    app.text("Birke")
    time.sleep(0.1)
    assert app.get("mt-save", "active") is True
    app.click("mt-proc-check-Markieren")
    app.click("mt-save")
    app.wait(lambda: app.get("mt-title", "text") == "Birke")
    procs = {m["process"] for m in api(app, "/api/materials")["materials"] if m["name"] == "Birke"}
    assert procs == {"Gravieren", "Markieren", "Schneiden"}, procs

    # Same name again: refused before it reaches the Pi.
    app.click("mt-new"); time.sleep(0.2)
    app.text("Birke"); time.sleep(0.1)
    assert app.get("mt-save", "active") is False
    app.key(K_ESC); time.sleep(0.2)

    # Edit: comma is read, value lands on the Pi, the field keeps working after the reload.
    replace_text(app, "mt-power-Schneiden-input", "50,5")
    app.wait(lambda: entry(app, "Birke", "Schneiden")["power_pct"] == 50.5)
    time.sleep(0.2)
    assert app.get("mt-power-Schneiden-input", "text") == "50,5"
    # Below the reliable minimum the field stops at 8 %.
    replace_text(app, "mt-power-Gravieren-input", "2")
    app.wait(lambda: entry(app, "Birke", "Gravieren")["power_pct"] == 8)

    # Arrow key steps by the field's step.
    app.click("mt-speed-Schneiden-input"); app.key(K_UP); time.sleep(0.5)
    assert entry(app, "Birke", "Schneiden")["speed_mm_min"] == 450
    app.key(K_RET); time.sleep(0.3)

    # Another device changed the list in between: 409, reload, ask again. Nothing is overwritten silently.
    rev = api(app, "/api/materials")["revision"]
    api(app, "/api/materials", {"name": "Fremd", "thickness_mm": 1, "process": "Schneiden", "mode": "line", "power_pct": 50, "speed_mm_min": 500, "base_revision": rev}, "POST")
    replace_text(app, "mt-zstep-Schneiden-input", "0,4")
    app.wait(lambda: "noch einmal speichern" in app.invoke("shell", "lastToast"))
    assert entry(app, "Birke", "Schneiden")["z_step_mm"] == 0
    time.sleep(0.5)

    # Use it: current on the Pi, for every device.
    app.click("mt-use")
    app.wait(lambda: app.get("mt-use", "text") == "Wird verwendet")
    assert api(app, "/api/workspace")["material"]["name"] == "Birke"
    app.click("nav-maschine"); time.sleep(0.4)
    app.click("m-tab-steuerung"); time.sleep(0.2)
    assert app.get("m-material", "text").startswith("Birke")

    # Rename follows the current material, the delete asks.
    app.click("nav-material"); time.sleep(0.5)
    app.click("mt-edit"); time.sleep(0.2)
    app.key(0x41, CTRL); app.text("Birke hell"); time.sleep(0.1)
    app.click("mt-save")
    app.wait(lambda: app.get("mt-title", "text") == "Birke hell")
    assert api(app, "/api/workspace")["material"]["name"] == "Birke hell"
    app.click("mt-del-Markieren"); time.sleep(0.2)
    app.click("confirm-cancel"); time.sleep(0.2)
    assert any(m["name"] == "Birke hell" and m["process"] == "Markieren" for m in api(app, "/api/materials")["materials"])
    app.click("mt-del-Markieren"); time.sleep(0.2)
    app.click("confirm-ok")
    app.wait(lambda: not any(m["name"] == "Birke hell" and m["process"] == "Markieren" for m in api(app, "/api/materials")["materials"]))

    # Options: address rules, reachable check, theme.
    app.click("nav-optionen"); time.sleep(0.3)
    app.click("o-address"); app.key(0x41, CTRL); app.text("example.com"); time.sleep(0.2)
    assert app.get("o-save", "active") is False
    assert app.get("o-test", "active") is False
    app.key(0x41, CTRL); app.text(app.invoke("shell", "piUrl").replace("http://", "")); time.sleep(0.2)
    app.click("o-test")
    app.wait(lambda: any(i["name"] == "o-check" for i in app.tree()))
    assert "Erreichbar" in app.get("o-check", "text")
    app.click("o-theme-seg-dark"); time.sleep(0.2)
    assert app.invoke("shell", "isDark") is True
    app.click("o-theme-seg-light"); time.sleep(0.2)
    assert app.invoke("shell", "isDark") is False
