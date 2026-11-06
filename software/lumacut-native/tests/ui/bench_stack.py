"""Measures the stack in the real window without vsync: start time, frame rate at N segments, memory."""
import json
import sys
import time

from driver import App

exe = sys.argv[1] if len(sys.argv) > 1 else None
app = App(exe=exe, env={"LUMACUT_BENCH": "1"})
try:
    app.wait(lambda: app.stats()["firstFrameMs"] > 0)
    print("Erstes Bild nach", app.stats()["firstFrameMs"], "ms, Speicher", round(app.stats()["memMb"]), "MB")
    app.click("nav-start")
    time.sleep(0.5)
    app.shot("build/shots/probe-leer.png")
    for n in (100_000, 1_000_000, 5_000_000):
        t = time.time()
        app.invoke("start-stage", "benchmark", n)
        time.sleep(1.0)
        app.stats()
        time.sleep(3.0)
        s = app.stats()
        print(f"{n:>8} Segmente: {s['fps']:.0f} Bilder/s, Speicher {s['memMb']:.0f} MB, Grafik-API {s['api']}")
        app.shot(f"build/shots/probe-{n}.png")
    print(json.dumps(app.find("start-preview")))
finally:
    app.close()
