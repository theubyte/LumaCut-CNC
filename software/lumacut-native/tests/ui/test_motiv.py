"""The design editor in the real window, with mouse and keyboard. Bench and pictures: test_motiv_shots.py."""
import json
import os
import tempfile
import struct
import time
import urllib.parse
import urllib.request
import zlib

CTRL, SHIFT, ALT = 0x04000000, 0x02000000, 0x08000000
K_DEL, K_ESC, K_RET, K_BACK = 0x01000007, 0x01000000, 0x01000004, 0x01000003
SIM_ARGS = ["--motion", "1050,150"]   # like the real Pi: top speed 150 mm/s = 9000 mm/min
K_LEFT, K_UP, K_RIGHT, K_DOWN = 0x01000012, 0x01000013, 0x01000014, 0x01000015
K_PGUP, K_PGDN, K_SPACE = 0x01000016, 0x01000017, 0x20


def red_png(w, h):
    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d))
    raw = b"".join(b"\0" + b"\xff\x20\x20" * w for _ in range(h))
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


def key_of(ch):
    return ord(ch.upper())


class Ed:
    """Editor seen from outside: millimetres to window pixels, the same way the owner's hand does it."""
    def __init__(self, app):
        self.app = app
        self.view = "view-Motiv"

    def px(self, x, y):
        return self.app.invoke(self.view, "win", [x, y])

    def inv(self, name, arg=0):
        return self.app.invoke(self.view, name, arg)

    def sel(self):
        return self.app.invoke(self.view, "selection", 0)

    def el(self, i):
        return self.app.invoke(self.view, "element", i)

    def count(self):
        return self.app.invoke(self.view, "count", 0)

    def settle(self, seconds=0.12):
        time.sleep(seconds)

    def tool(self, ch):
        self.app.key(key_of(ch), 0, ch.lower())
        self.settle(0.05)

    def move(self, p, down=False, mods=0):
        self.app.call("mouse", x=p[0], y=p[1], type="move", down=down, mods=mods)

    def press(self, p, mods=0):
        self.move(p, mods=mods)
        self.app.call("mouse", x=p[0], y=p[1], type="press", mods=mods)

    def release(self, p, mods=0):
        self.app.call("mouse", x=p[0], y=p[1], type="release", mods=mods)

    def click(self, x, y, mods=0):
        p = self.px(x, y)
        self.press(p, mods)
        self.release(p, mods)
        self.settle(0.05)

    def drag_px(self, a, b, mods=0, steps=8):
        self.press(a, mods)
        for i in range(1, steps + 1):
            self.move([a[0] + (b[0] - a[0]) * i / steps, a[1] + (b[1] - a[1]) * i / steps], down=True, mods=mods)
        self.release(b, mods)
        self.settle(0.05)

    def drag(self, x0, y0, x1, y1, mods=0, steps=8):
        self.drag_px(self.px(x0, y0), self.px(x1, y1), mods, steps)

    def wait_idle(self):
        self.app.wait(lambda: not self.app.get("stage", "loading"), timeout=20)


def shown(app, name):
    """The driver only finds what is visible."""
    return any(i["name"] == name for i in app.tree())


def close(a, b, tol=0.6):
    return abs(a - b) <= tol


def run(app):
    app.click("nav-motiv")
    app.wait(lambda: app.find("stage")["w"] > 100)
    app.call("resize", w=1440, h=900)
    time.sleep(0.4)
    ed = Ed(app)
    ed.inv("reset")
    time.sleep(0.2)

    # Empty: a clear invitation, and it leaves when drawing starts.
    assert app.find("empty-state")
    assert ed.count() == 0
    app.click("empty-rect")
    assert app.invoke(ed.view, "setTool", "rect") == "rect"
    ed.settle()

    # Draw a rectangle: one undo step, selected, the tool goes back to select.
    ed.tool("r")
    ed.drag(50, 80, 110, 120)
    assert ed.count() == 1
    e = ed.el(0)
    assert e["kind"] == "Rechteck", e
    assert close(e["minX"], 50) and close(e["minY"], 80) and close(e["maxX"], 110) and close(e["maxY"], 120), e
    assert ed.sel()["count"] == 1
    assert ed.inv("element", 0)["id"] == ed.sel()["id"]
    assert app.get("tool-select", "on") is True
    assert app.get("undo", "enabled") is True
    assert ed.inv("dirty") is True
    assert "•" in app.get("projectTitle", "text")

    # Move it: the stage shows it on the way, the document gets it on release.
    before = ed.el(0)
    p0, p1 = ed.px(65, 80), ed.px(85, 110)   # on the edge, away from the handles
    ed.press(p0)
    for i in range(1, 9):
        ed.move([p0[0] + (p1[0] - p0[0]) * i / 8, p0[1] + (p1[1] - p0[1]) * i / 8], down=True)
    assert ed.el(0)["x"] == before["x"], "Beim Ziehen bleibt das Dokument unberührt"
    assert close(ed.sel()["x"], 70) and close(ed.sel()["y"], 110), ed.sel()
    assert shown(app, "stage-pill")
    ed.release(p1)
    ed.settle()
    e = ed.el(0)
    assert close(e["minX"], 70) and close(e["minY"], 110), e
    assert not shown(app, "stage-pill")
    ed.app.key(0x5A, CTRL)   # Strg+Z
    ed.settle()
    assert close(ed.el(0)["minX"], 50)
    ed.app.key(0x59, CTRL)   # Strg+Y
    ed.settle()
    assert close(ed.el(0)["minX"], 70)

    # Arrow keys: 0,1 / 1 / 10 mm.
    x0 = ed.el(0)["x"]
    app.key(K_RIGHT); ed.settle(0.03)
    assert abs(ed.el(0)["x"] - x0 - 0.1) < 1e-6
    app.key(K_RIGHT, SHIFT); ed.settle(0.03)
    assert abs(ed.el(0)["x"] - x0 - 1.1) < 1e-6
    app.key(K_RIGHT, CTRL); ed.settle(0.03)
    assert abs(ed.el(0)["x"] - x0 - 11.1) < 1e-6
    for _ in range(3):
        app.key(0x5A, CTRL)
    ed.settle()
    assert abs(ed.el(0)["x"] - x0) < 1e-6

    # Scale by a corner handle; aspect locked keeps the ratio.
    assert app.get("lock-aspect", "pressedLook") is True
    a = ed.inv("handle", "se")
    b = ed.px(130, 180)
    ed.drag_px(a, b)
    e = ed.el(0)
    assert e["sx"] > 1.05 and abs(e["sx"] - e["sy"]) < 1e-6, e
    app.key(0x5A, CTRL); ed.settle()
    assert ed.el(0)["sx"] == 1
    # Free aspect through the side handle.
    a = ed.inv("handle", "e")
    ed.drag_px(a, [a[0] + 60, a[1]])
    e = ed.el(0)
    assert e["sx"] > 1.2 and e["sy"] == 1, e
    app.key(0x5A, CTRL); ed.settle()

    # Rotate by the handle above the frame, Shift gives steps of 15 degrees.
    a = ed.inv("handle", "rot")
    bb = ed.el(0)
    cx, cy = (bb["minX"] + bb["maxX"]) / 2, (bb["minY"] + bb["maxY"]) / 2
    ed.drag_px(a, ed.px(cx + 60, cy), mods=SHIFT)
    assert close(ed.el(0)["rot"], 90, 0.01), ed.el(0)
    app.key(0x5A, CTRL); ed.settle()
    assert ed.el(0)["rot"] == 0

    # Properties take numbers.
    app.click("prop-x-input"); app.key(0x41, CTRL); app.text("100"); app.key(K_RET); ed.settle()
    assert close(ed.el(0)["minX"], 100, 0.01), ed.el(0)
    app.key(0x5A, CTRL); ed.settle()

    # Alt+drag copies: one undo step takes copy and move back.
    box = ed.el(0)
    gx = box["minX"] + (box["maxX"] - box["minX"]) / 4
    ed.drag(gx, box["minY"], gx + 80, box["minY"] + 80, mods=ALT)
    assert ed.count() == 2
    assert close(ed.el(0)["minX"], box["minX"]) and close(ed.el(1)["minX"], box["minX"] + 80, 1.2)
    assert ed.sel()["id"] == ed.el(1)["id"]
    app.key(0x5A, CTRL); ed.settle()
    assert ed.count() == 1

    # Strg+D, C, V, X, A, Entf.
    app.key(0x41, CTRL); ed.settle()
    app.key(0x44, CTRL); ed.settle()
    assert ed.count() == 2
    assert close(ed.el(1)["x"], ed.el(0)["x"] + 5, 0.01)
    app.key(0x43, CTRL); app.key(0x56, CTRL); ed.settle()
    assert ed.count() == 3
    app.key(0x41, CTRL); ed.settle()
    assert ed.sel()["count"] == 3
    app.key(0x58, CTRL); ed.settle()
    assert ed.count() == 0
    app.key(0x56, CTRL); ed.settle()
    assert ed.count() == 3
    app.key(K_DEL); ed.settle()
    assert ed.count() == 0
    for _ in range(5):
        app.key(0x5A, CTRL)
    ed.settle()
    assert ed.count() == 1, ed.count()

    # Text: T and click, type right away, stays text.
    ed.tool("t")
    assert shown(app, "tool-hint")
    ed.click(60, 180)
    ed.settle(0.25)
    assert ed.count() == 2
    assert ed.sel().get("isText") is True
    assert app.get("text-input", "activeFocus") is True, "Nach T und Klick sofort tippbar"
    app.text("Hallo")
    ed.settle(0.15)
    t = ed.el(1)
    assert t["text"] == "Hallo", t
    assert t["paths"] >= 5 and t["points"] > 50, t
    w_hallo = t["maxX"] - t["minX"]
    # A letter key while typing must not switch the tool.
    assert app.get("tool-select", "on") is True
    app.click("font-size-input"); app.key(0x41, CTRL); app.text("20"); app.key(K_RET); ed.settle(0.15)
    t = ed.el(1)
    assert t["text"] == "Hallo" and close(t["maxX"] - t["minX"], 2 * w_hallo, w_hallo * 0.1), t
    # Typing was one undo step, the size another.
    app.key(0x5A, CTRL); ed.settle()
    assert ed.el(1)["text"] == "Hallo" and close(ed.el(1)["maxX"] - ed.el(1)["minX"], w_hallo, 0.5)
    app.key(0x5A, CTRL); ed.settle()
    assert ed.el(1)["text"] == "Text"
    app.key(0x59, CTRL); ed.settle()
    assert ed.el(1)["text"] == "Hallo"
    # Double click brings the keyboard back.
    b = ed.el(1)
    p = ed.px(b["minX"] + 0.4, (b["minY"] + b["maxY"]) / 2)   # on the stem of the H
    ed.press(p); ed.release(p); app.call("mouse", x=p[0], y=p[1], type="dbl")
    ed.settle(0.3)
    assert app.get("text-input", "activeFocus") is True, (ed.sel(), b, p, ed.px(b["minX"], b["minY"]))
    app.key(K_ESC); ed.settle()
    app.click("mv-canvas")
    ed.settle()
    app.key(K_ESC); ed.settle()

    # Two shapes unite through the toolbar.
    ed.inv("reset"); time.sleep(0.15)
    ed.tool("r"); ed.drag(50, 80, 110, 140)
    ed.tool("e"); ed.drag(90, 100, 150, 160)
    assert ed.count() == 2 and ed.el(1)["kind"] == "Ellipse"
    app.key(0x41, CTRL); ed.settle()
    assert ed.sel()["vectors"] == 2
    app.click("bool-union")
    app.wait(lambda: ed.count() == 1, timeout=5)
    u = ed.el(0)
    assert u["kind"] == "Verschweißen" and close(u["minX"], 50) and close(u["maxX"], 150), u
    assert ed.sel()["count"] == 1
    app.key(0x5A, CTRL); ed.settle()
    assert ed.count() == 2, "Rückgängig holt beide zurück"
    assert ed.el(0)["kind"] == "Rechteck"
    ed.inv("reset"); time.sleep(0.1)
    ed.tool("r"); ed.drag(50, 80, 90, 120)
    ed.tool("r"); ed.drag(70, 100, 110, 140)
    app.key(0x41, CTRL); ed.settle()
    app.click("bool-subtract")
    app.wait(lambda: ed.count() == 1, timeout=5)
    app.key(0x5A, CTRL); ed.settle()

    # Group: a click takes the whole group, ungroup splits again.
    app.key(0x41, CTRL); ed.settle()
    app.click("group"); ed.settle()
    app.key(K_ESC); ed.settle()
    ed.click(50, 100)
    assert ed.sel()["count"] == 2, ed.sel()
    assert shown(app, "ungroup")
    app.click("ungroup"); ed.settle()
    app.key(K_ESC); ed.settle()
    ed.click(50, 100)
    assert ed.sel()["count"] == 1

    # Rubber band left to right takes what lies inside, right to left what it touches.
    app.key(K_ESC); ed.settle()
    ed.drag(40, 70, 95, 125)
    assert ed.sel()["count"] == 1, ed.sel()
    app.key(K_ESC); ed.settle()
    ed.drag(125, 150, 85, 110)
    assert ed.sel()["count"] == 2, ed.sel()
    app.key(K_ESC); ed.settle()

    # Layer: selection changes what the laser does, the row shows it, values go direct.
    ed.click(50, 100)
    layers0 = ed.inv("layerIds")
    assert len(layers0) == 1, layers0
    gid = layers0[0]
    assert ed.inv("layerRow", gid)["focused"] is True
    app.click("process-Schneiden"); ed.settle()
    rows = ed.inv("layerIds")
    assert len(rows) == 2, rows
    sid = ed.el(0)["layer"]
    assert ed.inv("layerRow", sid)["name"] == "Schneiden"
    assert ed.inv("layerRow", sid)["focused"] is True
    assert ed.inv("layerRow", ed.el(1)["layer"])["focused"] is False
    assert app.get("process", "value") == "Schneiden"
    app.key(0x5A, CTRL); ed.settle()
    assert ed.el(0)["layer"] == gid
    # Power below 8 % warns right at the row.
    app.click("layer-power-Gravieren-input"); app.key(0x41, CTRL); app.text("5"); app.key(K_RET); ed.settle()
    assert shown(app, "layer-lowpower-Gravieren")
    assert ed.inv("layerRow", gid)["power"] == 5
    app.key(0x5A, CTRL); ed.settle()
    assert ed.inv("layerRow", gid)["power"] == 25
    # Speed: the Pi gives its top speed in mm/s (150 here), the field is mm/min: 9000 is allowed, more is capped.
    speed0 = ed.inv("layerRow", gid)["speed"]
    app.click("layer-speed-Gravieren-input"); app.key(0x41, CTRL); app.text("6000"); app.key(K_RET); ed.settle()
    assert ed.inv("layerRow", gid)["speed"] == 6000, ed.inv("layerRow", gid)
    app.click("layer-speed-Gravieren-input"); app.key(0x41, CTRL); app.text("20000"); app.key(K_RET); ed.settle()
    assert ed.inv("layerRow", gid)["speed"] == 9000, ed.inv("layerRow", gid)
    while ed.inv("layerRow", gid)["speed"] != speed0:
        app.key(0x5A, CTRL); ed.settle()
    app.click("layer-power-Gravieren-input"); ed.settle(0.1)   # the speed tip sits over the fold-out button
    # Folds out: passes, line interval, overscan, focus drop.
    app.click("layer-more-Gravieren"); ed.settle(0.1)
    app.click("layer-passes-Gravieren-input"); app.key(0x41, CTRL); app.text("3"); app.key(K_RET); ed.settle()
    app.click("layer-zstep-Gravieren-input"); app.key(0x41, CTRL); app.text("5"); app.key(K_RET); ed.settle()
    r = ed.inv("layerRow", gid)
    assert r["passes"] == 3 and r["zStep"] <= 1.5 + 1e-9, r
    app.click("layer-more-Gravieren"); ed.settle(0.1)

    # Plates: add, the sheet is empty, go back, move a shape over.
    n_plate0 = ed.count()
    app.click("plate-add"); ed.settle(0.2)
    assert app.get("plate-1", "on") is True
    assert app.find("empty-state")
    assert ed.sel()["count"] == 0
    app.click("plate-0"); ed.settle(0.2)
    assert app.get("plate-0", "on") is True
    assert app.get("stage", "elementCount") == n_plate0
    app.key(K_PGDN); ed.settle(0.15)
    assert app.get("plate-1", "on") is True
    app.key(K_PGUP); ed.settle(0.15)

    # Nodes: A, a square has four corners, drag one, double click makes it round, Entf takes one away.
    ed.inv("reset"); time.sleep(0.1)
    ed.tool("r"); ed.drag(60, 90, 120, 150)
    ed.tool("a")
    assert shown(app, "tool-hint")
    nodes = ed.el(0)["nodes"]
    assert len(nodes) == 4, nodes
    start = ed.inv("node", [0, 2])
    ed.drag_px(start, [start[0] + 40, start[1] + 25])
    moved = ed.el(0)["nodes"][2]
    assert moved["x"] > nodes[2]["x"] + 5 and moved["y"] > nodes[2]["y"] + 3, moved
    app.key(0x5A, CTRL); ed.settle()
    assert close(ed.el(0)["nodes"][2]["x"], nodes[2]["x"], 0.01)
    p = ed.inv("node", [0, 1])
    ed.press(p); ed.release(p); app.call("mouse", x=p[0], y=p[1], type="dbl")
    ed.settle()
    assert ed.el(0)["nodes"][1]["smooth"] is True, ed.el(0)["nodes"]
    p = ed.inv("node", [0, 0])
    ed.press(p); ed.release(p); ed.settle(0.05)
    app.key(K_DEL); ed.settle()
    assert len(ed.el(0)["nodes"]) == 3, ed.el(0)["nodes"]
    app.key(K_ESC); app.key(K_ESC); ed.settle()

    # Pen with Bezier handles, closing on the first point.
    ed.inv("reset"); time.sleep(0.1)
    ed.tool("p")
    ed.click(60, 100)
    ed.drag(120, 100, 130, 120)      # a drag sets a round node
    ed.click(100, 170)
    assert ed.count() == 0 and app.get("stage", "hasDraft") is True
    ed.click(60, 100)                # first point: closes
    ed.settle()
    k = ed.el(0)
    assert ed.count() == 1 and k["kind"] == "Kurve", k
    assert any(n["smooth"] for n in k["nodes"]), k
    assert k["points"] > 12, k
    # Polyline with Enter, backspace takes back the last point.
    ed.tool("l")
    ed.click(150, 100); ed.click(180, 110); ed.click(190, 150)
    app.key(K_BACK); ed.settle()
    app.key(K_RET); ed.settle()
    l = ed.el(1)
    assert l["kind"] == "Linie" and len(l["nodes"]) == 2, l
    # Measuring changes nothing.
    n = ed.count()
    ed.tool("m"); ed.drag(30, 30, 130, 30)
    assert shown(app, "stage-pill") and "100" in app.get("stage-pill", "text")
    app.key(K_ESC); app.key(K_ESC); ed.settle()
    assert ed.count() == n

    # Zoom to the mouse: the point under it stays.
    z0 = app.get("stage", "effectiveZoom")
    p = ed.px(100, 100)
    app.call("wheel", x=p[0], y=p[1], dy=240)
    ed.settle(0.05)
    z1 = app.get("stage", "effectiveZoom")
    q = ed.px(100, 100)
    assert z1 > z0 * 1.1 and abs(q[0] - p[0]) < 0.5 and abs(q[1] - p[1]) < 0.5, (z0, z1, p, q)
    # Space and the middle button pan.
    app.call("keydown", key=K_SPACE, text=" ")
    ed.drag_px(p, [p[0] + 40, p[1] + 25])
    app.call("keyup", key=K_SPACE)
    ed.settle(0.05)
    q = ed.px(100, 100)
    assert abs(q[0] - p[0] - 40) < 0.5 and abs(q[1] - p[1] - 25) < 0.5, (p, q)
    m = ed.px(100, 100)
    app.call("mouse", x=m[0], y=m[1], type="mpress")
    app.call("mouse", x=m[0] - 30, y=m[1], type="mmove")
    app.call("mouse", x=m[0] - 30, y=m[1], type="mrelease")
    ed.settle(0.05)
    assert abs(ed.px(100, 100)[0] - (m[0] - 30)) < 0.5
    assert ed.count() == n, "Verschieben ändert nichts am Motiv"
    # F fits the sheet again.
    app.key(0x46, 0, "f"); ed.settle(0.1)
    a, b = ed.px(0, 0), ed.px(app.get("stage", "bedWidth"), app.get("stage", "bedHeight"))
    box = app.find("stage")
    assert a[0] >= box["x"] and a[1] >= box["y"] and b[0] <= box["x"] + box["w"] and b[1] <= box["y"] + box["h"]
    assert app.get("zoom-label", "text").endswith("%")

    # Snapping: a shape caught by another shape's edge, a guide on the way.
    ed.inv("reset"); time.sleep(0.1)
    assert app.get("snap-objects", "pressedLook") is True
    ed.tool("r"); ed.drag(50, 80, 90, 120)
    ed.tool("r"); ed.drag(120, 200, 140, 220)
    # Move the second one close to the first one's left edge; it lands exactly on it.
    a = ed.px(120, 210)
    b = ed.px(50.7, 210)
    ed.drag_px(a, b)
    assert abs(ed.el(1)["minX"] - 50) < 1e-6, ed.el(1)
    # Strg while dragging switches snapping off.
    a = ed.px(50, 210)
    b = ed.px(50.7, 210)
    z = app.get("stage", "effectiveZoom")
    ed.drag_px(a, [a[0] + 1.5 * z, a[1]], mods=CTRL)
    assert abs(ed.el(1)["minX"] - 50) > 0.5, ed.el(1)

    # Warnings at the object, in the panel, with the way out.
    ed.inv("reset"); time.sleep(0.1)
    ed.tool("r"); ed.drag(100, 100, 140, 140)
    W = app.get("stage", "bedWidth")
    app.click("prop-x-input"); app.key(0x41, CTRL); app.text(str(W - 10)); app.key(K_RET); ed.settle()
    assert app.get("warn-1", "text") == "Ragt über die Arbeitsfläche"
    assert app.get("props-warning-note", "tone") == "bad"
    app.click("keep-inside"); ed.settle()
    assert close(ed.el(0)["maxX"], W, 0.01), ed.el(0)
    app.click("prop-y-input"); app.key(0x41, CTRL); app.text("0"); app.key(K_RET); ed.settle()
    assert "Park" in app.get("warn-2", "text")
    assert app.get("props-warning-note", "tone") == "warn"
    app.click("keep-inside"); ed.settle()
    assert ed.sel().get("warnText") is None, ed.sel()
    # The locked strip across the width comes from the Pi.
    assert app.get("stage", "parkHeight") > 0

    # Align, distribute, mirror, split through the toolbar.
    ed.inv("reset"); time.sleep(0.1)
    ed.tool("r"); ed.drag(50, 80, 70, 100)
    ed.tool("r"); ed.drag(90, 110, 130, 130)
    ed.tool("r"); ed.drag(200, 150, 220, 190)
    app.key(0x41, CTRL); ed.settle()
    app.click("align-left"); ed.settle()
    assert all(close(ed.el(i)["minX"], 50, 0.01) for i in range(3)), [ed.el(i) for i in range(3)]
    app.key(0x5A, CTRL); ed.settle()
    app.click("dist-h"); ed.settle()
    gap1 = ed.el(1)["minX"] - ed.el(0)["maxX"]
    gap2 = ed.el(2)["minX"] - ed.el(1)["maxX"]
    assert close(gap1, gap2, 0.01) and close(ed.el(0)["minX"], 50, 0.01) and close(ed.el(2)["maxX"], 220, 0.01)
    app.key(0x5A, CTRL); ed.settle()
    before = ed.el(2)
    app.click("mirror-h"); ed.settle()
    assert close(ed.el(2)["minX"], 50, 0.01), ed.el(2)
    app.key(0x5A, CTRL); ed.settle()
    assert close(ed.el(2)["minX"], before["minX"], 0.01)
    # Union of two far shapes keeps both parts in one element; split takes them apart again.
    app.click("bool-union")
    app.wait(lambda: ed.count() == 1, timeout=5)
    assert ed.el(0)["paths"] == 2 or ed.el(0)["paths"] == 3, ed.el(0)
    parts = ed.el(0)["paths"]
    app.click("split"); ed.settle()
    assert ed.count() == parts
    app.key(0x5A, CTRL); ed.settle()
    assert ed.count() == 1
    # Contour: dialog, one step, on the cut layer.
    app.key(0x41, CTRL); ed.settle()
    app.click("contour"); ed.settle(0.15)
    assert shown(app, "contour-dialog")
    app.click("contour-ok")
    app.wait(lambda: ed.count() == 2, timeout=8)
    k = ed.el(1)
    assert k["kind"] == "Kontur" and ed.inv("layerRow", k["layer"])["name"] == "Schneiden", k
    assert not shown(app, "contour-dialog")
    app.key(0x5A, CTRL); ed.settle()

    # Font: the list comes from the system, the text stays text.
    ed.inv("reset"); time.sleep(0.1)
    ed.tool("t"); ed.click(60, 180); ed.settle(0.2)
    app.text("Abc"); ed.settle(0.1)
    w0 = ed.el(0)["maxX"] - ed.el(0)["minX"]
    app.click("font-select"); ed.settle(0.2)
    assert shown(app, "font-dialog")
    app.click("font-search-input" if shown(app, "font-search-input") else "font-search"); app.text("mono"); ed.settle(0.1)
    app.click("font-0"); ed.settle(0.2)
    assert not shown(app, "font-dialog")
    e = ed.el(0)
    assert e["text"] == "Abc" and ed.sel()["fontFamily"] != "sans-serif" and abs(e["maxX"] - e["minX"] - w0) > 0.01, (e, ed.sel())
    app.click("font-bold"); ed.settle(0.1)
    assert ed.sel()["bold"] is True

    # Locked strip across the width from the Pi (simulator): shown, warned about, the way out goes below it.
    ed.inv("reset"); time.sleep(0.1)
    url = app.invoke("shell", "piUrl")
    if url:
        form = urllib.parse.urlencode({"op": "work_band", "y": "50"}).encode()
        urllib.request.urlopen(urllib.request.Request(url + "/api/action", data=form), timeout=5).read()
        W = app.get("stage", "bedWidth")
        app.wait(lambda: app.get("stage", "parkWidth") >= W, timeout=6)
        assert app.get("stage", "parkHeight") == 50
        ed.tool("r"); ed.drag(100, 100, 140, 140)
        app.click("prop-y-input"); app.key(0x41, CTRL); app.text("20"); app.key(K_RET); ed.settle()
        assert "Streifen" in app.get("warn-2", "text"), app.get("warn-2", "text")
        app.click("keep-inside"); ed.settle()
        assert close(ed.el(0)["minY"], 50, 0.01), ed.el(0)
        form = urllib.parse.urlencode({"op": "work_band", "y": ""}).encode()
        urllib.request.urlopen(urllib.request.Request(url + "/api/action", data=form), timeout=5).read()
        app.wait(lambda: app.get("stage", "parkWidth") < W, timeout=6)

        # Camera background: no scan yet says so; a scan shows on the sheet and never reaches the project.
        ed.inv("reset"); time.sleep(0.1)
        ed.inv("sample"); ed.wait_idle()
        app.click("bg-button"); ed.settle(0.1)
        assert shown(app, "bg-pop")
        app.click("bg-load")
        app.wait(lambda: "Scan" in str(app.invoke("shell", "lastToast")), timeout=8)
        assert not shown(app, "bg-show")
        rev = json.load(urllib.request.urlopen(url + "/api/status", timeout=5))["sync"]["scan"]
        png = red_png(64, 64)
        req = urllib.request.Request(f"{url}/api/workspace/scan?base_revision={rev}", data=png, method="PUT", headers={"Content-Type": "image/png"})
        urllib.request.urlopen(req, timeout=5).read()
        before = ed.inv("toJson")
        app.click("bg-load")
        app.wait(lambda: shown(app, "bg-show"), timeout=8)
        ed.settle(0.4)
        p = ed.px(340, 340)   # empty part of the sheet
        px = app.call("pixel", x=p[0], y=p[1])
        assert px["r"] > px["g"] + 40, px
        assert ed.inv("toJson") == before, "Hintergrund gehört nicht ins Projekt"
        app.click("bg-show"); ed.settle(0.3)
        px = app.call("pixel", x=p[0], y=p[1])
        assert abs(px["r"] - px["g"]) < 40, px
        app.key(K_ESC); ed.settle(0.1)

    # Picture: mode, sliders, one undo step for a slider drag.
    ed.inv("reset"); time.sleep(0.1)
    ed.inv("sample")
    app.wait(lambda: ed.count() > 5)
    ed.wait_idle()
    img = next(i for i in range(ed.count()) if ed.el(i).get("imageMode"))
    b = ed.el(img)
    ed.click((b["minX"] + b["maxX"]) / 2, (b["minY"] + b["maxY"]) / 2)
    assert ed.sel().get("isImage") is True, ed.sel()
    assert ed.sel()["imageMode"] == "dither"
    app.wait(lambda: app.get("image-preview", "backend") in ("gpu", "cpu"), timeout=8)
    pv = app.find("image-preview")
    probes = [app.call("pixel", x=pv["x"] + pv["w"] * f, y=pv["y"] + pv["h"] * 0.5) for f in (0.5, 0.65)]
    assert probes[0]["r"] != probes[1]["r"], ("Vorschau zeigt nichts", probes)
    app.click("image-mode"); ed.settle(0.1)
    app.click("image-mode-list-4"); ed.settle(0.3)
    assert ed.sel()["imageMode"] == "threshold"
    assert ed.el(img)["imageMode"] == "threshold"
    assert app.get("image-preview", "mode") == 1
    s0 = ed.sel()["brightness"]
    side = app.find("mv-side")
    for _ in range(12):   # the panel scrolls with the wheel
        t = app.find("vectorize")
        if t["y"] + t["h"] < side["y"] + side["h"]:
            break
        app.call("wheel", x=side["x"] + 150, y=side["y"] + 300, dy=-120)
        ed.settle(0.03)
    t = app.find("image-brightness")
    assert t["y"] + t["h"] < side["y"] + side["h"], t
    y = t["y"] + t["h"] / 2
    x0, x1 = t["x"] + 30, t["x"] + 80
    ed.drag_px([x0, y], [x1, y], steps=4)
    ed.settle(0.3)
    br = ed.sel()["brightness"]
    assert br != s0, br
    assert app.get("image-preview", "brightness") == br
    app.key(0x5A, CTRL); ed.settle(0.3)
    assert ed.sel()["brightness"] == s0, "Ein Schieben ist ein Schritt"
    app.click("vectorize"); ed.settle(0.2)
    n = ed.count()
    app.click("vectorize-ok")
    app.wait(lambda: ed.count() == n + 1, timeout=10)
    assert app.invoke("shell", "lastToast").endswith("Pfade erzeugt")

    # Files: saved with a path, opened again, title and dirty mark follow.
    path = os.path.join(tempfile.gettempdir(), f"lc-motiv-{os.getpid()}.lumacut").replace("\\", "/")
    assert app.invoke("sync-api", "saveTo", path) is True
    app.wait(lambda: ed.inv("dirty") is False, timeout=5)   # written on a worker
    assert "•" not in app.get("projectTitle", "text")
    n = ed.count()
    with open(path, encoding="utf-8") as f:
        assert len(json.load(f)["elements"]) == n
    ed.inv("reset"); time.sleep(0.1)
    assert ed.count() == 0
    assert app.invoke("sync-api", "openNow", path) is True
    app.wait(lambda: ed.count() == n)
    os.remove(path)
    ed.wait_idle()
    # Leaving the view and coming back keeps project and view.
    app.click("nav-material"); time.sleep(0.3)
    app.click("nav-motiv"); app.wait(lambda: app.find("stage")["w"] > 100)
    ed.wait_idle()
    assert app.get("stage", "elementCount") >= n - 1

    # Rename goes to the shell's title.
    app.click("file-menu"); ed.settle(0.05)
    app.click("file-menu-list-7"); ed.settle(0.15)
    assert shown(app, "rename-dialog")
    app.key(0x41, CTRL); app.text("Schild"); app.key(K_RET); ed.settle(0.15)
    assert app.get("projectTitle", "text").startswith("Schild")
    app.key(0x5A, CTRL); ed.settle()
    assert not app.get("projectTitle", "text").startswith("Schild")

    # Import through a path: one undo step, selected. While the importer is still a stand-in it says so.
    ed.inv("reset"); time.sleep(0.1)
    svg = os.path.join(tempfile.gettempdir(), f"lc-motiv-{os.getpid()}.svg").replace("\\", "/")
    with open(svg, "w", encoding="utf-8") as f:
        f.write('<svg xmlns="http://www.w3.org/2000/svg" width="40mm" height="30mm" viewBox="0 0 40 30"><rect x="1" y="1" width="38" height="28"/></svg>')
    ed.inv("importFile", svg)
    app.wait(lambda: ed.count() > 0 or "gebaut" in str(app.invoke("shell", "lastToast")), timeout=8)
    if ed.count():
        assert ed.sel()["count"] == ed.count()
        app.key(0x5A, CTRL); ed.settle()
        assert ed.count() == 0
    os.remove(svg)

    # Right mouse button: the menu of what is under it.
    ed.inv("reset"); time.sleep(0.1)
    ed.tool("r"); ed.drag(100, 100, 140, 140)
    app.key(K_ESC); ed.settle()
    p = ed.px(100, 120)
    ed.move(p)
    app.call("mouse", x=p[0], y=p[1], type="rpress")
    app.call("mouse", x=p[0], y=p[1], type="rrelease")
    ed.settle(0.1)
    assert ed.sel()["count"] == 1
    assert shown(app, "mv-context")
    app.key(K_ESC); ed.settle(0.1)
    assert not shown(app, "mv-context")

    # Export writes real files through a path.
    for fmt in ("svg", "dxf", "png"):
        out = os.path.join(tempfile.gettempdir(), f"lc-motiv-{os.getpid()}.{fmt}").replace("\\", "/")
        app.invoke(ed.view, "exportTo", [out, fmt])
        app.wait(lambda: os.path.exists(out) and os.path.getsize(out) > 0 or "ging nicht" in str(app.invoke("shell", "lastToast")), timeout=10)
        assert os.path.exists(out), app.invoke("shell", "lastToast")
        os.remove(out)
    ed.inv("reset")
