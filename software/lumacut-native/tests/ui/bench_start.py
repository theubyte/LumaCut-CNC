"""How long from "Motiv geändert" to the finished preview, and how smoothly a long job plays. Run by hand, prints a table.
    python tests/ui/bench_start.py <sim port> <automation port> [segments ...]
LUMACUT_EXE names the program. The dither image's size is chosen so that the writer produces about that many segments.
"""
import json
import math
import os
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from driver import App, ROOT  # noqa: E402
from start_helpers import image_element, layer, project, shot  # noqa: E402


def noise(n):
    # A fixed cheap pattern: dither of mid grey breaks every row into many pieces, without slow Python randomness.
    return bytes((i * 2654435761 >> 13) & 255 for i in range(n))


def bench(app, target, results):
    px = int(math.sqrt(target * 1.78))     # about 0.56 segments per pixel with this pattern
    mm = 300 * px / 3000
    path = project(f"Bench{target}", [image_element(px, px, min(mm, 300), min(mm, 300), x=40, y=45, gray=noise(px * px))], [layer(mode="FILL", power=30, speed=6000)], name=f"bench{target}")
    t0 = time.time()
    before = app.invoke("start-api", "revision")
    app.invoke("start-api", "openProject", path)
    app.wait(lambda: app.invoke("start-api", "revision") != before, timeout=120)
    t_load = time.time() - t0
    app.wait(lambda: app.invoke("start-api", "timings").get("count", 0) > 0 and not app.invoke("start-api", "building"), timeout=300)
    app.wait(lambda: not app.get("start-preview", "loading"), timeout=120)
    time.sleep(0.5)
    timings = app.invoke("start-api", "timings")
    print(f"{target}: load file {t_load * 1000:.0f} ms, " + json.dumps(timings), flush=True)
    assert timings["count"] > 0
    # A real change after the load: the title does not change the toolpath, a layer value does. Rebuilds with the same content.
    app.invoke("start-api", "setTitle", f"Bench {target} neu")
    # The window keeps answering meanwhile: each answer comes from its main thread.
    worst = 0.0
    time.sleep(0.05)
    while True:
        t0 = time.time()
        busy = app.invoke("start-api", "building") or app.get("start-preview", "loading")
        worst = max(worst, time.time() - t0)
        if not busy:
            break
        time.sleep(0.01)
    change = app.invoke("start-api", "timings")
    print(f"{target}: change {json.dumps(change)} worst main thread answer {worst * 1000:.0f} ms", flush=True)
    time.sleep(0.5)
    app.stats()
    app.call("stats", reset=True)
    app.click("start-to-begin")
    app.click("start-play")
    time.sleep(6)
    s = app.call("stats")
    app.click("start-play")
    mode = app.get("start-preview", "renderMode")
    print(f"{target}: play fps={s.get('fps'):.1f} frameMs={s.get('frameMs')} cpuMs={s.get('cpuMs')} gpuMs={s.get('gpuMs')} mode={mode} mem={s.get('memMb')}", flush=True)
    shot(app, f"bench-{target}")
    results.append({"target": target, "count": timings["count"], "bytes": timings["bytes"], "open": timings, "change": change, "mainThreadMs": worst * 1000, "fps": s.get("fps"), "frameMs": s.get("frameMs"), "gpuMs": s.get("gpuMs"), "mode": mode})


def main():
    sim_port, port = int(sys.argv[1]), int(sys.argv[2])
    targets = [int(a) for a in sys.argv[3:]] or [1_000_000, 5_000_000]
    py = os.environ.get("SIM_PYTHON", sys.executable)
    sim = subprocess.Popen([py, str(ROOT / "tools" / "sim_pi.py"), "--port", str(sim_port)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env={**os.environ, "PYTHONUTF8": "1"})
    time.sleep(5)
    app = App(port=port, pi_url=f"http://127.0.0.1:{sim_port}", env={"LUMACUT_BENCH": "1"} if os.environ.get("BENCH_NOVSYNC") else None)
    try:
        app.wait(lambda: app.stats()["firstFrameMs"] > 0, timeout=30)
        app.click("nav-start")
        time.sleep(0.5)
        results = []
        for t in targets:
            bench(app, t, results)
        print(json.dumps(results, indent=1))
    finally:
        app.close()
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(sim.pid)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


if __name__ == "__main__":
    main()
