"""The GPU items in the real window: behaviour, not speed (speed is bench_gpu.py)."""
import time

USES_SIM = False


def _do(app, fn, arg=0):
    return app.invoke("gpuBench", fn, arg)


def _pixel(app, fn, x, y):
    p = _do(app, fn, {"x": x, "y": y})
    return app.call("pixel", x=p["x"], y=p["y"])


def run(app):
    app.call("gpuBench")
    time.sleep(0.2)
    s = app.stats()
    assert s["gpuName"], "kein GPU-Name in stats"
    assert s["frameMs"].get("n", 0) >= 0 and "gpuMs" in s and "cpuMs" in s

    # Job preview: loading in the background, the upload is complete afterwards.
    _do(app, "show", "segments")
    _do(app, "fitAll")
    _do(app, "loadSegments", 300_000)
    app.wait(lambda: app.get("benchSegments", "segmentCount") == 300_000, timeout=30)
    app.wait(lambda: not app.get("benchSegments", "loading"), timeout=30)
    assert app.get("benchSegments", "uploadedCount") == 300_000

    # Zoom at the cursor: what is under the cursor stays there. Through real wheel events.
    box = app.find("benchSegments")
    cx, cy = box["x"] + box["w"] * 0.31, box["y"] + box["h"] * 0.62
    before = _do(app, "segToMm", {"x": cx, "y": cy})
    for _ in range(3):
        app.call("wheel", x=cx, y=cy, dy=360)
    after = _do(app, "segToMm", {"x": cx, "y": cy})
    assert abs(before["x"] - after["x"]) < 0.01 and abs(before["y"] - after["y"]) < 0.01, (before, after)
    # Pan with a drag: a mm point follows the mouse.
    p0 = _do(app, "segToItem", {"x": 100, "y": 100})
    app.drag(cx, cy, cx + 60, cy + 25)
    p1 = _do(app, "segToItem", {"x": 100, "y": 100})
    assert abs(p1["x"] - p0["x"] - 60) < 1 and abs(p1["y"] - p0["y"] - 25) < 1, (p0, p1)
    _do(app, "fitAll")

    # Playback: only a count; nothing is uploaded again. Travel off and on keeps it too.
    for n in (0, 1000, 150_000, 299_999, -1):
        _do(app, "playTo", n)
        assert app.get("benchSegments", "visibleCount") == n
    _do(app, "travel", False)
    _do(app, "travel", True)
    assert app.get("benchSegments", "uploadedCount") == 300_000

    # Device gone and back: the data arrives again by itself.
    app.call("gpuReset")
    time.sleep(1.0)
    app.wait(lambda: app.get("benchSegments", "uploadedCount") == 300_000, timeout=30)

    # Stage: even-odd over the whole layer. One square tinted, the overlap a hole, an open path not filled.
    _do(app, "show", "stage")
    _do(app, "stageEvenOdd")
    app.wait(lambda: app.get("benchStage", "elementCount") == 3 and not app.get("benchStage", "loading"), timeout=10)
    time.sleep(0.3)
    single = _pixel(app, "stageToItem", 120, 120)
    overlap = _pixel(app, "stageToItem", 175, 175)
    other = _pixel(app, "stageToItem", 230, 230)
    outside = _pixel(app, "stageToItem", 290, 120)
    openp = _pixel(app, "stageToItem", 335, 310)   # inside the open triangle
    assert single["b"] > single["r"] + 20, f"Fläche nicht gefüllt: {single}"
    assert other["b"] > other["r"] + 20, f"zweite Fläche nicht gefüllt: {other}"
    assert abs(overlap["b"] - overlap["r"]) < 25, f"Überlappung ist kein Loch: {overlap}"
    assert abs(outside["b"] - outside["r"]) < 25, f"außen gefüllt: {outside}"
    assert abs(openp["b"] - openp["r"]) < 25, f"offener Pfad gefüllt: {openp}"
    # Hiding one square: the overlap now belongs to the other one and is filled. Only the data texture changed.
    _do(app, "stageHide", 2)
    time.sleep(0.2)
    now = _pixel(app, "stageToItem", 175, 175)
    assert now["b"] > now["r"] + 20, f"nach Ausblenden nicht gefüllt: {now}"
    app.shot("build-gpu/shots/test-stage.png")

    # Compute preview exists and draws, on the GPU or on the CPU.
    _do(app, "show", "compute")
    _do(app, "computeLoad", 1)
    app.wait(lambda: app.get("benchCompute", "backend") in ("gpu", "cpu"), timeout=20)
    time.sleep(0.5)
    _do(app, "computeSet", {"mode": 2, "contrast": 20, "brightness": 0})
    time.sleep(0.5)
    app.shot("build-gpu/shots/test-compute.png")
    print("Compute-Weg:", app.get("benchCompute", "backend"), "| GPU:", s["gpuName"])
