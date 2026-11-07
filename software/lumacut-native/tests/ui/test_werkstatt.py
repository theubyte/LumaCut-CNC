"""Workshop in the real window: generators with mouse and keyboard, preview, "Ins Projekt", parts and layers in the project.
Nothing here moves or lasers: the workshop only edits the project."""
import os
import time
from pathlib import Path

CTRL = 0x04000000
K_RET = 0x01000004
ROOT = Path(__file__).resolve().parents[2]
SHOTS = Path(os.environ["LUMACUT_EXE"]).parent / "shots" if os.environ.get("LUMACUT_EXE") else ROOT / "build" / "shots"
V = "view-Werkstatt"


def inv(app, name, arg=0):
    return app.invoke(V, name, arg)


def settle(app):
    time.sleep(0.15)
    return inv(app, "settle")


def type_into(app, name, text):
    app.click(name)
    time.sleep(0.05)
    app.key(0x41, CTRL)
    app.text(text)
    app.key(K_RET)
    time.sleep(0.1)


def apply(app):
    before = inv(app, "count")
    assert app.get("ws-apply", "active") is True, inv(app, "result")
    app.click("ws-apply")
    app.wait(lambda: inv(app, "count") > before, timeout=5)
    return inv(app, "count") - before


def tool(app, tid):
    app.click(f"ws-tool-{tid}")
    app.wait(lambda: app.get("ws-heading", "text") != "", timeout=5)
    return settle(app)


def run(app):
    app.click("nav-werkstatt")
    app.wait(lambda: app.find(V))
    inv(app, "reset")

    # Material test grid: 5 × 5 fields, each on its own layer, labelled.
    r = tool(app, "materialtest")
    assert r["ok"] and r["parts"] == 35, r
    app.wait(lambda: inv(app, "stageState")["elements"] == 35, timeout=5)
    app.shot(SHOTS / "werkstatt-materialtest.png")
    assert apply(app) == 35
    layers = inv(app, "layerNames")
    assert "20 % · 300 mm/min" in layers and "100 % · 3000 mm/min" in layers and "Beschriftung" in layers, layers
    assert app.invoke("shell", "lastToast").startswith("35 Teile ins Projekt gelegt"), app.invoke("shell", "lastToast")

    # Below 8 % the laser does not fire reliably: the field stops at 8, the generator refuses with a sentence.
    type_into(app, "ws-powerFrom-input", "5")
    assert inv(app, "params")["powerFrom"] == 8
    inv(app, "setParam", ["powerFrom", 5])
    r = settle(app)
    assert not r["ok"] and "8 %" in r["error"], r
    assert app.get("ws-error", "visible") is True
    assert app.get("ws-apply", "active") is False
    type_into(app, "ws-powerFrom-input", "20")
    assert settle(app)["ok"]

    # Box: width typed, joined lid clicked; the busy plate makes it start on a fresh one.
    tool(app, "box")
    type_into(app, "ws-w-input", "120")
    app.click("ws-lid-joined")
    r = settle(app)
    assert inv(app, "params")["w"] == 120 and inv(app, "params")["lid"] == "joined"
    assert r["ok"] and r["parts"] == 6, r
    app.shot(SHOTS / "werkstatt-box.png")
    assert apply(app) == 6
    p = inv(app, "plates")
    assert p == {"count": 2, "active": 1}, p
    names = inv(app, "elementNames")
    assert all(n in names for n in ("Boden", "Vorne", "Hinten", "Links", "Rechts", "Deckel")), names

    # Gear: 30 teeth, onto the active plate.
    tool(app, "zahnrad")
    type_into(app, "ws-teeth-input", "30")
    r = settle(app)
    assert r["ok"] and any("30 Zähne" in n and "Teilkreis 60 mm" in n for n in r["notes"]), r
    assert apply(app) == 1

    # QR code: the known address gives version 3 (29 × 29).
    tool(app, "qr")
    type_into(app, "ws-text", "https://lumacut.example/abc?x=1")
    app.click("ws-plate")
    r = settle(app)
    assert r["ok"] and any("Version 3, 29 × 29" in n for n in r["notes"]), r
    app.shot(SHOTS / "werkstatt-qr.png")
    assert apply(app) == 2
    # One undo step per "Ins Projekt".
    n = inv(app, "count")
    u = inv(app, "undo")
    assert u == n - 2, (n, u)
    assert apply(app) == 2

    # Ruler with a name, scale bar, stamp, frame around the motif.
    tool(app, "lineal")
    type_into(app, "ws-title", "Werkstatt")
    assert apply(app) == 4
    tool(app, "massstab")
    assert apply(app) == 4
    tool(app, "stempel")
    app.click("ws-motif-star")
    assert settle(app)["ok"]
    app.shot(SHOTS / "werkstatt-stempel.png")
    assert apply(app) == 2
    tool(app, "rahmen")
    app.click("ws-source-motiv")
    app.click("ws-style-0")
    r = settle(app)
    assert r["ok"], r
    assert apply(app) == 1

    # Serial numbers over several plates; the preview switches plates.
    tool(app, "serien")
    type_into(app, "ws-count-input", "200")
    r = settle(app)
    assert r["ok"] and r["plates"] >= 2 and r["parts"] > 0, r
    app.click("ws-preview-plate-1")
    time.sleep(0.2)
    assert inv(app, "result")["plate"] == 1
    app.shot(SHOTS / "werkstatt-serien.png")
    plates_before = inv(app, "plates")["count"]
    added = apply(app)
    assert added == 400, added
    assert inv(app, "plates")["count"] >= plates_before + r["plates"], inv(app, "plates")

    names = inv(app, "elementNames")
    for n in ("Zahnrad", "QR-Code", "QR Umriss", "Lineal Umriss", "Lineal Text", "Maßstab Felder", "Stempel", "Rahmen", "SN-0001", "SN-0200 Umriss"):
        assert n in names, n
    assert set(inv(app, "layerNames")) >= {"Gravieren", "Linie", "Schneiden"}

    # Photo engraving: only a way to the image tools in Motiv.
    tool(app, "foto")
    assert app.get("ws-foto-open", "visible") is True
    try:
        hidden = app.get("ws-apply", "visible") is False
    except RuntimeError as e:          # the driver does not find hidden items
        hidden = "not found" in str(e)
    assert hidden

    # Perfboard holder 50 × 70 at the shared position, cut with the MDF values from the Pi's list.
    tool(app, "halterung")
    for k, want in ((1, "30x70"), (3, "50x70")):
        app.click("ws-size")
        time.sleep(0.2)
        app.click(f"ws-size-menu-{k}")
        time.sleep(0.1)
        assert inv(app, "params")["size"] == want
    time.sleep(0.1)
    assert inv(app, "params")["size"] == "50x70"
    r = settle(app)
    assert r["ok"] and r["parts"] == 3, r
    assert any("Tasche 50,3 × 70,3 mm" in n and "X 185, Y 197,5" in n for n in r["notes"]), r["notes"]
    own_cut = inv(app, "layerByName", "Schneiden")
    app.shot(SHOTS / "werkstatt-halterung.png")
    assert apply(app) == 3
    names = inv(app, "elementNames")
    assert all(n in names for n in ("Halterung Umriss", "Halterung Beschriftung", "Halterung Wendeachse")), names
    # The project's own cut layer stays as it was; the frame has its own layer with the MDF values.
    after = inv(app, "layerByName", "Schneiden")
    assert after == own_cut, (own_cut, after)
    holder = inv(app, "layerByName", "Halterung schneiden")
    assert holder is not None and inv(app, "layerByName", "Gravieren") is not None
    if any("aus der Materialliste" in n for n in r["notes"]):
        assert holder.get("materialName") == "MDF" and holder["powerPct"] == 95, holder
    # A second holder reuses the layer.
    n_layers = len(inv(app, "layerNames"))
    assert apply(app) == 3
    assert len(inv(app, "layerNames")) == n_layers
    assert inv(app, "layerNames").count("Halterung schneiden") == 1
    # The position is shared: typed here, stored for the perfboard editor, seen by the mask test.
    type_into(app, "ws-y-input", "180")
    assert inv(app, "setting", "perfboard/y") == 180
    # Own size.
    app.click("ws-custom")
    time.sleep(0.2)
    type_into(app, "ws-w-input", "60")
    r = settle(app)
    assert r["ok"] and any("Platine 60 × 70 mm" in n for n in r["notes"]), r
    app.click("ws-custom")
    # Into the park corner: refused with a sentence.
    inv(app, "setParam", ["x", 340])
    inv(app, "setParam", ["y", 60])
    r = settle(app)
    assert not r["ok"] and "Park-Ecke" in r["error"], r
    inv(app, "setParam", ["x", 185])
    inv(app, "setParam", ["y", 197.5])
    assert settle(app)["ok"]

    # Solder mask test preset: 4 × 3 small line fields on the Markieren process, centred on the same position.
    r = tool(app, "loetstopp")
    assert inv(app, "params")["y"] == 197.5
    assert r["ok"] and r["parts"] == 13 and any("Vorschlag" in w for w in r["warnings"]), r
    app.shot(SHOTS / "werkstatt-loetstopp.png")
    assert apply(app) == 13
    assert inv(app, "layerByName", "Markieren 8 % · 3000 mm/min")["powerPct"] == 8

    # Dark, small window.
    app.invoke("shell", "setTheme", "dark")
    app.invoke("shell", "resizeTo", [1000, 640])
    tool(app, "box")
    time.sleep(0.3)
    app.shot(SHOTS / "werkstatt-box-dunkel-klein.png")
    tool(app, "halterung")
    time.sleep(0.3)
    app.shot(SHOTS / "werkstatt-halterung-dunkel-klein.png")
    app.invoke("shell", "setTheme", "system")
