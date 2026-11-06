"""Pictures of the editor for the eye, and what it costs at 100,000 paths. Writes to build-motiv/shots unless LUMACUT_SHOTS is set.
Numbers go to stdout: load, hover, drag one, drag all, zoom, undo. Without LUMACUT_BENCH the frame rate is capped by vsync."""
import os
import statistics
import time
from pathlib import Path

from test_motiv import CTRL, Ed

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(os.environ.get("LUMACUT_SHOTS") or ROOT / "build-motiv" / "shots")
SIZES = [(1000, 640), (1440, 900), (2560, 1440)]


def shots(app, ed):
    for theme in ("light", "dark"):
        app.invoke("shell", "setTheme", theme)
        for w, h in SIZES:
            app.call("resize", w=w, h=h)
            time.sleep(0.5)
            ed.inv("reset")
            time.sleep(0.25)
            app.key(0x46, 0, "f")
            time.sleep(0.2)
            app.shot(OUT / f"motiv-leer-{theme}-{w}.png")
            ed.inv("sample")
            ed.wait_idle()
            time.sleep(0.7)
            app.shot(OUT / f"motiv-reich-{theme}-{w}.png")
            # With a selection: frame, handles, panels.
            ed.click(30, 100)
            time.sleep(0.25)
            app.shot(OUT / f"motiv-auswahl-{theme}-{w}.png")
            app.key(0x01000000)
            ed.settle()


def scene_shots(app, ed):
    for theme in ("light", "dark"):
        app.invoke("shell", "setTheme", theme)
        app.call("resize", w=1440, h=900)
        time.sleep(0.4)
        ed.inv("reset")
        time.sleep(0.2)
        ed.inv("sample")
        ed.wait_idle()
        time.sleep(0.5)
        # Picture selected: preview, sliders
        n = ed.count()
        img = next(i for i in range(n) if ed.el(i).get("imageMode"))
        b = ed.el(img)
        ed.click((b["minX"] + b["maxX"]) / 2, (b["minY"] + b["maxY"]) / 2)
        time.sleep(0.5)
        app.shot(OUT / f"motiv-bild-{theme}.png")
        app.key(0x01000000)
        # Node tool on a heart
        hearts = next(i for i in range(n) if ed.el(i)["kind"] == "Rechteck")
        b = ed.el(hearts)
        ed.click(b["minX"], (b["minY"] + b["maxY"]) / 2)
        ed.tool("a")
        time.sleep(0.2)
        app.shot(OUT / f"motiv-knoten-{theme}.png")
        app.key(0x01000000); app.key(0x01000000)
        ed.settle()
        # Warnings at the object
        ed.tool("r"); ed.drag(310, 10, 350, 40)
        ed.tool("r"); ed.drag(340, 200, 368, 240)
        app.click("prop-x-input"); app.key(0x41, CTRL); app.text("350"); app.key(0x01000004); ed.settle(0.2)
        app.key(0x01000000); ed.settle(0.2)
        app.shot(OUT / f"motiv-warnung-{theme}.png")
        ed.tool("p"); ed.click(150, 280); ed.drag(200, 270, 215, 290); ed.click(240, 320); ed.settle()
        app.shot(OUT / f"motiv-stift-{theme}.png")
        app.key(0x01000000); app.key(0x01000000); ed.settle()
    app.invoke("shell", "setTheme", "light")


def timed(fn):
    t = time.perf_counter()
    fn()
    return (time.perf_counter() - t) * 1000


def report(name, values):
    values = sorted(values)
    print(f"{name}: Median {statistics.median(values):.2f} ms, 95 % {values[int(len(values) * .95)]:.2f} ms, max {values[-1]:.2f} ms", flush=True)


def frames(name, s):
    f, c, g = s.get("frameMs", {}), s.get("cpuMs", {}), s.get("gpuMs", {})
    print(f"{name}: {f.get('n', 0)} Bilder, Abstand Median {f.get('p50', 0):.1f} ms, 95 % {f.get('p95', 0):.1f} ms, max {f.get('max', 0):.1f} ms; Render-Thread {c.get('p50', 0):.2f} ms, GPU {g.get('p50', 0):.2f} ms", flush=True)


def bench(app, ed, n=100000):
    app.invoke("shell", "setTheme", "light")
    app.call("resize", w=1440, h=900)
    time.sleep(0.3)
    print(f"--- {n} Pfade", flush=True)
    t = time.perf_counter()
    ed.inv("stress", n)
    gen = (time.perf_counter() - t) * 1000
    app.wait(lambda: app.get("stage", "elementCount") == n and not app.get("stage", "loading") and app.get("stage", "pendingUpload") == 0, timeout=60, every=0.02)
    print(f"Erzeugen und Laden: {gen:.0f} ms im Fenster-Thread, bis alles auf der GPU {(time.perf_counter() - t) * 1000:.0f} ms", flush=True)
    print("Speicher", round(app.stats().get("memMb", 0)), "MB", "Segmente", app.get("stage", "instanceCount"), flush=True)
    time.sleep(0.5)
    app.shot(OUT / "motiv-100000.png")

    def path_drag(a, b, steps, mods=0):
        vals = []
        ed.press(a, mods)
        for i in range(1, steps + 1):
            p = [a[0] + (b[0] - a[0]) * i / steps, a[1] + (b[1] - a[1]) * i / steps]
            vals.append(timed(lambda: ed.move(p, down=True, mods=mods)))
        return vals

    # Hover: hit test on every mouse move
    vals = []
    for i in range(300):
        p = ed.px(50 + i * 0.5, 100 + i * 0.3)
        vals.append(timed(lambda: ed.move(p)))
    report("Mausbewegung mit Treffertest", vals)

    # Pan and zoom cost one frame, no geometry.
    app.stats()
    time.sleep(0.05)
    vals = []
    p = ed.px(180, 180)
    for i in range(60):
        vals.append(timed(lambda: app.call("wheel", x=p[0], y=p[1], dy=60 if i < 30 else -60)))
    report("Zoomschritt", vals)
    app.key(0x46, 0, "f"); ed.settle(0.3)

    # One element: drag, commit, undo.
    e = ed.el(n // 2)
    ed.click(e["minX"] + (e["maxX"] - e["minX"]) / 2, e["minY"] + (e["maxY"] - e["minY"]) / 2)
    assert ed.sel()["count"] == 1, ed.sel()
    a = ed.px((e["minX"] + e["maxX"]) / 2, (e["minY"] + e["maxY"]) / 2)
    app.call("stats", reset=True)
    vals = path_drag(a, [a[0] + 200, a[1] + 120], 120)
    s = app.call("stats", reset=True)
    report("Ein Element ziehen, je Mausbewegung", vals)
    frames("  Bilder", s)
    print(f"  Stufe im Fenster-Thread {app.get('stage', 'dragMs'):.3f} ms", flush=True)
    t = timed(lambda: ed.release([a[0] + 200, a[1] + 120]))
    print(f"Ablegen (ein Rückgängig-Schritt): {t:.1f} ms", flush=True)
    print(f"Rückgängig: {timed(lambda: app.key(0x5A, CTRL)):.1f} ms, Wiederholen: {timed(lambda: app.key(0x59, CTRL)):.1f} ms", flush=True)

    # Everything: select, drag, commit, undo.
    t = timed(lambda: app.key(0x41, CTRL))
    assert ed.sel()["count"] == n
    print(f"Alles auswählen: {t:.1f} ms", flush=True)
    a = ed.px(160, 120)
    # Grab a shape, not a handle.
    hit = None
    for i in range(n // 3, n):
        hit = ed.el(i)
        break
    a = ed.px((hit["minX"] + hit["maxX"]) / 2, (hit["minY"] + hit["maxY"]) / 2)
    app.call("stats", reset=True)
    vals = path_drag(a, [a[0] + 100, a[1] + 60], 60)
    s = app.call("stats", reset=True)
    report(f"Alle {n} ziehen, je Mausbewegung", vals)
    frames("  Bilder", s)
    print(f"  Stufe im Fenster-Thread {app.get('stage', 'dragMs'):.2f} ms für {app.get('stage', 'scanCount')} Elemente", flush=True)
    t = timed(lambda: ed.release([a[0] + 100, a[1] + 60]))
    print(f"Ablegen aller: {t:.1f} ms", flush=True)
    print(f"Rückgängig aller: {timed(lambda: app.key(0x5A, CTRL)):.1f} ms, Wiederholen: {timed(lambda: app.key(0x59, CTRL)):.1f} ms", flush=True)
    print(f"Entf: {timed(lambda: app.key(0x01000007)):.1f} ms, Rückgängig: {timed(lambda: app.key(0x5A, CTRL)):.1f} ms", flush=True)
    app.wait(lambda: not app.get("stage", "loading") and app.get("stage", "pendingUpload") == 0, timeout=30, every=0.02)
    print("Speicher danach", round(app.stats().get("memMb", 0)), "MB", flush=True)
    app.invoke("view-Motiv", "reset", 0)


def run(app):
    OUT.mkdir(parents=True, exist_ok=True)
    app.click("nav-motiv")
    app.wait(lambda: app.find("stage")["w"] > 100)
    ed = Ed(app)
    if not os.environ.get("LUMACUT_BENCH_ONLY"):
        shots(app, ed)
        scene_shots(app, ed)
    if not os.environ.get("LUMACUT_SHOTS_ONLY"):
        bench(app, ed)
