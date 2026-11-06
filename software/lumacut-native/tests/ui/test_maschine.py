"""Machine view in the real window against the simulator: go dialog, jog, probe, light, exhaust, NOT-AUS, locks, work band, camera."""
import json
import time
import urllib.request

K_RET, K_ESC, K_PAUSE, K_TAB = 0x01000004, 0x01000000, 0x01000008, 0x01000001
K_LEFT, K_UP, K_RIGHT, K_DOWN, K_PGUP, K_PGDN = 0x01000012, 0x01000013, 0x01000014, 0x01000015, 0x01000016, 0x01000017
ALT, CTRL = 0x08000000, 0x04000000


def pi_status(app):
    return json.load(urllib.request.urlopen(app.invoke("shell", "piUrl") + "/api/status", timeout=5))


def pos(app):
    return app.get("status-pos", "text")


def is_open(app, name):
    return any(i["name"] == name for i in app.tree())


def run(app):
    app.click("nav-maschine")
    time.sleep(0.4)
    app.click("m-tab-steuerung")
    app.wait(lambda: app.get("m-headline", "text") == "Nicht referenziert")
    start = pos(app)

    # Locked before the reference: buttons say why, a click does nothing, jog neither.
    assert app.get("m-park", "lock").startswith("Nicht referenziert")
    app.click("m-park")
    assert not is_open(app, "go-confirm")
    app.click("jog-right")
    time.sleep(0.3)
    assert pos(app) == start

    # Referenz: the Pi does not know the height, so the question names it.
    assert pi_status(app)["home_needs_confirm"] is True
    app.click("m-home")
    time.sleep(0.2)
    assert app.get("go-confirm", "text") == "Ja, referenzieren"
    assert "Kopfhöhe" in app.get("go-detail", "text")
    # Enter never starts: focus is on Abbrechen.
    app.key(K_RET)
    time.sleep(0.2)
    assert not is_open(app, "go-confirm")
    assert app.get("m-headline", "text") == "Nicht referenziert"
    # Esc closes.
    app.click("m-home"); time.sleep(0.2); app.key(K_ESC); time.sleep(0.2)
    assert not is_open(app, "go-confirm")
    # Tab to the start button: Enter and Space still do nothing there. Tab stays inside the dialog.
    app.click("m-home"); time.sleep(0.2)
    app.key(K_TAB); time.sleep(0.1)
    app.key(K_RET); app.key(0x20, 0, " "); time.sleep(0.3)
    assert is_open(app, "go-confirm"), "Enter oder Leertaste haben den Go ausgelöst"
    assert not pi_status(app)["homed"]
    app.click("go-cancel"); time.sleep(0.2)
    # Alt+S starts, on purpose.
    app.click("m-home"); time.sleep(0.2); app.key(0x53, ALT)
    app.wait(lambda: app.get("m-headline", "text") == "Bereit", timeout=15)
    assert app.get("m-homed", "text") == "Ja"
    assert pos(app).startswith("X 390,0  Y 0,0")

    # Jog: work directions, from the door. Keys and buttons, no go dialog.
    app.key(K_DOWN); time.sleep(0.4)
    assert " Y 1,0" in pos(app), pos(app)
    app.click("jog-step-10"); time.sleep(0.1)
    app.click("jog-down"); time.sleep(0.4)
    assert " Y 11,0" in pos(app), pos(app)
    app.click("jog-step-0.1"); time.sleep(0.1)
    app.click("jog-left"); time.sleep(0.4)
    assert pos(app).startswith("X 389,9"), pos(app)
    app.click("jog-step-1"); time.sleep(0.1)
    assert not is_open(app, "go-confirm")
    # Z stays locked until a surface is measured.
    assert app.get("jog-zup", "lock").startswith("Z erst")

    # Zu Position: go dialog names the target; machine X = bed width - work X.
    app.click("m-moveto"); time.sleep(0.2)
    assert "X 100,0, Y 100,0" in app.get("go-detail", "text")
    app.click("go-confirm"); time.sleep(0.8)
    assert pos(app).startswith("X 100,0  Y 100,0"), pos(app)
    assert pi_status(app)["position"][0] == 290

    # Abtasten with go. Afterwards Z may move.
    app.click("m-probe"); time.sleep(0.2)
    assert "neu scannen" in app.get("go-detail", "text")
    app.click("go-confirm")
    app.wait(lambda: app.get("m-surface", "text") != "–", timeout=15)
    app.wait(lambda: app.get("jog-zup", "lock") == "")
    z0 = pi_status(app)["position"][2]
    app.key(K_PGUP); time.sleep(0.5)
    assert abs(pi_status(app)["position"][2] - z0 - 1) < 0.01

    # Light and exhaust: no dialog.
    # The Pi plays light effects after moves and restores the old state afterwards: wait them out, then
    # compare with what it reports now. A click during an effect is undone by the Pi itself.
    time.sleep(3)
    light0 = pi_status(app)["lights"]
    app.wait(lambda: app.get("m-light", "on") == light0)
    app.click("m-light")
    app.wait(lambda: pi_status(app)["lights"] is (not light0))
    assert not is_open(app, "go-confirm")
    exhaust0 = pi_status(app)["exhaust"]
    app.click("m-exhaust")
    app.wait(lambda: pi_status(app)["exhaust"] is (not exhaust0))
    app.click("m-exhaust"); app.click("m-light")
    app.wait(lambda: pi_status(app)["exhaust"] is exhaust0 and pi_status(app)["lights"] is light0)

    # The locked strip: from the Pi, visible, and back.
    w0 = app.get("bed-blocked", "width")
    app.click("m-band")
    app.wait(lambda: app.get("m-band", "on") is True)
    assert pi_status(app)["config"]["blocked_band_y_mm"] == 35
    assert pi_status(app)["park_corner_mm"]["x"] == 390
    time.sleep(0.2)
    assert app.get("bed-blocked", "width") > 2 * w0
    app.click("m-band")
    app.wait(lambda: app.get("m-band", "on") is False)
    assert pi_status(app)["park_corner_mm"]["x"] == 78

    # NOT-AUS over an open dialog, no question; the dialog goes away.
    app.click("m-park"); time.sleep(0.2)
    assert is_open(app, "go-confirm")
    app.click("estop"); time.sleep(0.6)
    assert not is_open(app, "go-confirm")
    assert pi_status(app)["emergency_latched"] is True
    assert app.get("m-headline", "text") == "Not-Aus aktiv"
    assert app.get("conn-chip", "text") == "Not-Aus aktiv"
    app.click("estop-reset")
    app.wait(lambda: not pi_status(app)["emergency_latched"], timeout=15)
    # Pause key: from anywhere, also while typing.
    app.click("moveto-x-input"); app.key(K_PAUSE); time.sleep(0.6)
    assert pi_status(app)["emergency_latched"] is True
    app.click("m-estop-reset")
    app.wait(lambda: not pi_status(app)["emergency_latched"], timeout=15)

    # Whatever is not on the list is refused without a request; fired-laser service ops do not exist here.
    for op in ("service_laser", "ttl_test", "supply_test", "firmware_update_install", "was_neues"):
        assert app.invoke("shell", "tryAction", op) is False
        assert "nicht freigegeben" in app.invoke("shell", "lastToast")
    assert not is_open(app, "go-confirm")

    # Strg+1..6
    app.key(0x31, CTRL); time.sleep(0.2)
    assert "Material" in app.get("mainView", "source")
    app.key(0x36, CTRL); time.sleep(0.3)
    assert "Maschine" in app.get("mainView", "source")

    # Camera: texture updates, stops when the tab is hidden.
    app.click("m-tab-kamera")
    app.wait(lambda: app.get("view-Maschine", "camFrames") >= 2, timeout=15)
    app.click("m-tab-steuerung"); time.sleep(0.6)
    f0 = app.get("view-Maschine", "camFrames")
    time.sleep(1.0)
    assert app.get("view-Maschine", "camFrames") == f0, "Vorschau läuft im verdeckten Reiter weiter"

    # Kalibrieren: entered values go through a dialog.
    app.click("m-tab-kalibrieren"); time.sleep(0.3)
    app.click("kal-taster"); time.sleep(0.2)
    assert app.get("kal-title", "text") == "Taster-Versatz"
    app.click("probe-edit"); time.sleep(0.2)
    assert app.get("set-probe_offset_x_mm", "value") == -27.4, "Der Dialog muss die Werte vom Pi zeigen"
    app.click("settings-save")
    time.sleep(0.5)
    assert pi_status(app)["probe_xy_offset_mm"] == [-27.4, 13.0]
    assert not is_open(app, "settings-save")
    app.click("m-tab-steuerung")
