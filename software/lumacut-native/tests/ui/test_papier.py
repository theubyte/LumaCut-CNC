"""Papier und Karton in the real window: gallery with thumbnails, groups, search, a template with mouse and keyboard,
the preview, "Ins Projekt" with the paper layers in order, a part too big for the sheet, and the workshop list without
paper templates. Nothing here moves or lasers: the view only edits the project."""
import os
import time
from pathlib import Path

CTRL = 0x04000000
K_RET = 0x01000004
K_ESC = 0x01000000
ROOT = Path(__file__).resolve().parents[2]
SHOTS = Path(os.environ["LUMACUT_EXE"]).parent / "shots" if os.environ.get("LUMACUT_EXE") else ROOT / "build" / "shots"
V = "view-Papier"


def inv(app, name, arg=0):
    return app.invoke(V, name, arg)


def settle(app):
    time.sleep(0.15)
    return inv(app, "settle")


def exists(app, name):
    try:
        app.find(name)
        return True
    except RuntimeError:
        return False


def type_into(app, name, text):
    app.click(name)
    time.sleep(0.05)
    app.key(0x41, CTRL)
    app.text(text)
    app.key(K_RET)
    time.sleep(0.1)


def pick(app, tid, title):
    app.click(f"pp-tpl-{tid}")
    app.wait(lambda: app.get("pp-heading", "text") == title, timeout=5)
    return settle(app)


def run(app):
    app.call("resize", w=1024, h=700)   # CI screen is small: everything must stay reachable
    app.click("nav-papier")
    app.wait(lambda: exists(app, V))
    inv(app, "reset")

    # The gallery: every template has a picture from its default values.
    ids = inv(app, "allIds")
    assert len(ids) >= 40, ids
    for tid in ids:
        t = inv(app, "thumb", tid)
        assert t["ok"] and t["ink"] > 300 and t["url"] == "image://papier/" + tid, (tid, t)

    # Groups and search narrow the gallery.
    app.click("pp-group-Umschlag")
    app.wait(lambda: "faltschachtel" not in inv(app, "shownIds"), timeout=5)
    shown = inv(app, "shownIds")
    assert "umschlag" in shown and "pochette" in shown, shown
    app.click("pp-group-alle")
    app.click("pp-search")
    app.text("pop-up")
    app.wait(lambda: len(inv(app, "shownIds")) == 2, timeout=5)
    assert sorted(inv(app, "shownIds")) == ["popupmotiv", "popupstufen"], inv(app, "shownIds")
    app.key(K_ESC)
    app.wait(lambda: len(inv(app, "shownIds")) == len(ids), timeout=5)

    # Faltschachtel with the mouse, width typed, a heart window: preview and size follow.
    r = pick(app, "faltschachtel", "Faltschachtel")
    assert r["ok"], r
    type_into(app, "ws-w-input", "60")
    assert inv(app, "params")["w"] == 60
    inv(app, "setParam", ["window", "herz"])
    inv(app, "setParam", ["text", "Für dich"])
    r = settle(app)
    assert r["ok"] and r["plates"] == 1, r
    app.wait(lambda: inv(app, "stageState")["elements"] >= 4, timeout=5)
    app.shot(SHOTS / "papier-faltschachtel.png")

    before = inv(app, "count")
    assert app.get("pp-apply", "active") is True
    app.click("pp-apply")
    app.wait(lambda: inv(app, "count") > before, timeout=5)
    layers = inv(app, "layerNames")
    for name in ("Papierbogen (nur Anzeige)", "Papier gravieren", "Papier falzen", "Papier schneiden"):
        assert name in layers, layers
    assert layers.index("Papier falzen") < layers.index("Papier schneiden"), layers
    assert layers.index("Papier gravieren") < layers.index("Papier schneiden"), layers
    assert inv(app, "layerByName", "Papierbogen (nur Anzeige)")["output"] is False
    assert "ins Projekt gelegt" in app.invoke("shell", "lastToast"), app.invoke("shell", "lastToast")

    # Envelope DIN lang does not fit A4: a sentence, no apply; on the whole bed it fits.
    r = pick(app, "umschlag", "Briefumschlag")
    assert r["ok"], r
    inv(app, "setParam", ["format", "dl"])
    r = settle(app)
    assert not r["ok"] and "größer als der Bogen" in r["error"], r
    assert app.get("pp-error", "visible") is True
    assert app.get("pp-apply", "active") is False
    inv(app, "setParam", ["sheet", "bett"])
    assert settle(app)["ok"]

    # A pop-up card and a generative snowflake also compute in the window.
    assert pick(app, "popupmotiv", "Pop-up-Karte Motiv")["ok"]
    app.shot(SHOTS / "papier-popup.png")
    assert pick(app, "schneeflocke", "Schneeflocken")["ok"]

    # The workshop list keeps its own tools; the paper view remembers its last template.
    app.click("nav-werkstatt")
    app.wait(lambda: exists(app, "view-Werkstatt"))
    assert exists(app, "ws-tool-box") and not exists(app, "ws-tool-faltschachtel")
    app.wait(lambda: app.get("ws-heading", "text") != "", timeout=5)
    app.click("nav-papier")
    app.wait(lambda: exists(app, V))
    app.wait(lambda: app.get("pp-heading", "text") == "Schneeflocken", timeout=5)
    app.shot(SHOTS / "papier-galerie.png")

