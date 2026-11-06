"""Measures the GPU items in the real window, without vsync, and writes build-gpu/bench.md.

    python tests/ui/bench_gpu.py [exe] [--port 9601] [--only hw|sw]

Runs twice: on the real adapter, then on the software adapter (WARP, as in CI). Frame times come from the render thread
and from QRhi timestamps (command "stats"). Screenshots land in build-gpu/shots.
"""
import json
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from driver import App, QT_BIN  # noqa: E402

ROOT = HERE.parents[1]
OUT = ROOT / "build-gpu"
SHOTS = OUT / "shots"


def fmt(v, digits=1):
    return "-" if v is None else f"{v:.{digits}f}"


class Bench:
    def __init__(self, app, tag):
        self.app = app
        self.tag = tag
        self.lines = []

    def do(self, fn, arg=0):
        return self.app.invoke("gpuBench", fn, arg)

    def shot(self, name):
        self.app.shot(SHOTS / f"{self.tag}-{name}.png")

    def sample(self, seconds=2.0):
        self.app.call("stats", reset=True)
        time.sleep(seconds)
        s = self.app.call("stats", reset=True)
        fm, cp, gp = s["frameMs"], s["cpuMs"], s["gpuMs"]
        return {
            "fps": 1000.0 / fm["avg"] if fm.get("n") else 0,
            "frame": fm.get("avg"), "p99": fm.get("p99"), "cpu": cp.get("avg"), "gpu": gp.get("avg"), "n": fm.get("n", 0),
            "mem": s.get("memMb"),
        }

    def row(self, label, m, extra=""):
        self.lines.append(f"| {label} | {m['fps']:.0f} | {fmt(m['frame'], 2)} | {fmt(m['p99'], 2)} | {fmt(m['cpu'], 2)} | {fmt(m['gpu'], 2)} | {fmt(m['mem'], 0)} | {extra} |")
        print(self.lines[-1], flush=True)

    def header(self, title):
        self.lines += ["", f"### {title}", "", "| Fall | Bilder/s | Bild ms | p99 ms | CPU ms | GPU ms | Speicher MB | Anmerkung |", "|---|---:|---:|---:|---:|---:|---:|---|"]
        print("\n".join(self.lines[-4:]), flush=True)

    # --- job preview -------------------------------------------------------------------------------------------
    def segments(self, counts):
        app = self.app
        self.header("Auftragsvorschau (SegmentsItem), Fenster " + str(app.find("benchSegments")["w"]) + " x " + str(app.find("benchSegments")["h"]))
        self.do("show", "segments")
        self.do("continuous", True)
        self.do("powerColor", True)
        for n in counts:
            self.do("fitAll")
            app.call("stats", reset=True)
            t = time.time()
            self.do("loadSegments", n)
            # The GUI must keep answering while the worker and the upload run.
            answer = 0.0
            app.wait(lambda: app.get("benchSegments", "segmentCount") == min(n, 20_000_000) or False, timeout=120)
            while app.get("benchSegments", "loading"):
                a = time.time()
                app.get("benchSegments", "uploadedCount")
                answer = max(answer, time.time() - a)
                time.sleep(0.01)
                if time.time() - t > 300:
                    raise TimeoutError("Laden hängt")
            load_ms = (time.time() - t) * 1000
            during = app.call("stats", reset=True)["frameMs"]
            raster = app.get("benchSegments", "rasterLook")
            time.sleep(0.3)
            mode = app.get("benchSegments", "renderMode")
            m = self.sample()
            self.row(f"{n:,} ganz".replace(",", "."), m, f"{mode}, Laden {load_ms:.0f} ms, längstes Bild beim Laden {during.get('max', 0):.1f} ms, GUI-Antwort max {answer * 1000:.1f} ms")
            self.shot(f"seg-{n}-fit")
            # The same picture with every real segment on every frame: the raw throughput, and the moire the map avoids.
            self.do("burnMap", False)
            time.sleep(0.3)
            m = self.sample(1.5)
            self.row("  roh, jedes Segment jedes Bild", m, f"gezeichnet {app.get('benchSegments', 'drawnCount'):,}".replace(",", "."))
            self.shot(f"seg-{n}-roh")
            self.do("burnMap", True)
            w, h = app.find("benchSegments")["w"], app.find("benchSegments")["h"]
            self.do("setZoomAt", {"x": w / 2, "y": h / 2, "f": 30.0})
            time.sleep(0.2)
            mode = app.get("benchSegments", "renderMode")
            m = self.sample(1.0)
            self.row("  Zoom 30x", m, f"{mode}, gezeichnet {app.get('benchSegments', 'drawnCount'):,}".replace(",", "."))
            self.shot(f"seg-{n}-zoom")
            self.do("fitAll")
            # Playback forward: only a count changes.
            self.do("pending", 0.15)
            self.do("playTo", n // 2)
            time.sleep(1.0)
            m = self.sample(1.0)
            self.row("  Abspielen halb, Rest blass", m, app.get("benchSegments", "renderMode"))
            self.shot(f"seg-{n}-play")
            self.do("pending", 0.0)
            self.do("playTo", -1)
            self.do("travel", False)
            time.sleep(0.2)
            self.do("travel", True)
        self.do("continuous", False)

    def decimation(self):
        app = self.app
        self.do("show", "segments")
        self.do("fitAll")
        t = time.time()
        self.do("loadSegments", 25_000_000)
        app.wait(lambda: app.get("benchSegments", "sourceCount") == 25_000_000, timeout=120)
        count = app.get("benchSegments", "segmentCount")
        self.lines += ["", f"Grenze: 25 Mio. Segmente werden auf {count:,} zusammengefasst ({time.time() - t:.1f} s), decimated={app.get('benchSegments', 'decimated')}.".replace(",", ".")]
        print(self.lines[-1], flush=True)
        assert count <= 20_000_000 and app.get("benchSegments", "decimated")

    def looks(self):
        """Screenshots for the eye: dense raster at several zooms, both themes, device change."""
        app = self.app
        self.do("show", "segments")
        self.do("fitAll")
        self.do("theme", False)
        self.do("loadSegments", 1_000_000)
        app.wait(lambda: not app.get("benchSegments", "loading"), timeout=60)
        time.sleep(0.5)
        self.shot("look-1m-light")
        self.do("loadSegments", 5_000_000)
        app.wait(lambda: app.get("benchSegments", "segmentCount") == 5_000_000 and not app.get("benchSegments", "loading"), timeout=60)
        time.sleep(0.5)
        self.shot("look-5m-light")
        self.do("loadSegments", 1_000_000)
        app.wait(lambda: app.get("benchSegments", "segmentCount") == 1_000_000 and not app.get("benchSegments", "loading"), timeout=60)
        self.do("continuous", True)
        for w, h in ((1000, 640), (1440, 900), (2560, 1440)):
            app.call("resize", w=w, h=h)
            time.sleep(0.6)
            got = app.find("benchSegments")
            assert abs(got["w"] - w) <= 2 and abs(got["h"] - h) <= 2, f"Fenster nicht {w} x {h}: {got}"
            self.shot(f"look-1m-{w}")
            m = self.sample(0.5)
            self.lines.append(f"Fenster {w} x {h}: {m['fps']:.0f} Bilder/s, {fmt(m['frame'], 2)} ms je Bild, ohne neues Hochladen.")
            print(self.lines[-1], flush=True)
        self.do("continuous", False)
        self.do("theme", True)
        time.sleep(1.0)
        self.shot("look-1m-dark")
        self.do("theme", False)
        time.sleep(0.5)

    def reset_device(self):
        app = self.app
        self.do("show", "segments")
        self.do("fitAll")
        self.do("loadSegments", 1_000_000)
        app.wait(lambda: not app.get("benchSegments", "loading"), timeout=60)
        before = app.stats()["gpuName"]
        app.call("gpuReset")
        time.sleep(1.5)
        app.wait(lambda: app.get("benchSegments", "uploadedCount") == 1_000_000, timeout=30)
        time.sleep(0.5)
        self.shot("seg-after-device-reset")
        self.lines += ["", f"Gerätewechsel (Szenengraph und Gerät neu, Adapter {before}): Daten kamen ohne Zutun wieder an."]
        print(self.lines[-1], flush=True)

    # --- stage -------------------------------------------------------------------------------------------------
    def stage(self, sizes):
        app = self.app
        self.header("Bühne (StageItem)")
        self.do("show", "stage")
        self.do("continuous", True)
        for paths, segs in sizes:
            app.call("stats", reset=True)
            t = time.time()
            self.do("loadStage", {"paths": paths, "segs": segs})
            app.wait(lambda: app.get("benchStage", "instanceCount") == paths * segs and app.get("benchStage", "pendingUpload") == 0, timeout=120)
            load_ms = (time.time() - t) * 1000
            during = app.call("stats", reset=True)["frameMs"]
            inst = app.get("benchStage", "instanceCount")
            m = self.sample()
            self.row(f"{paths:,} Pfade".replace(",", "."), m, f"{inst:,} Kanten, Laden {load_ms:.0f} ms, längstes Bild {during.get('max', 0):.1f} ms".replace(",", "."))
            self.shot(f"stage-{paths}")
            # A drag: all of them move every frame through the element texture, no geometry is touched.
            app.call("stats", reset=True)
            for i in range(60):
                self.do("stageMove", {"step": 1, "dx": 0.05, "dy": 0.0})
            m = self.sample(0.3)
            self.row("  alle verschieben", m, "60 setTransforms hintereinander")
            app.call("stats", reset=True)
            for i in range(200):
                self.do("stageReshape", i)
            s = app.call("stats", reset=True)["frameMs"]
            self.lines.append(f"| einzelne Elemente neu formen | - | {fmt(s.get('avg'), 2)} | {fmt(s.get('p99'), 2)} | - | - | - | 200 upsertElement |")
            print(self.lines[-1], flush=True)
            self.do("stageImage")
            self.do("stageSelect", {"n": 40, "x": 40, "y": 120, "w": 120, "h": 90})
            time.sleep(0.5)
            self.shot(f"stage-{paths}-auswahl")
            w, h = app.find("benchStage")["w"], app.find("benchStage")["h"]
            self.do("stageZoom", {"x": w * 0.3, "y": h * 0.5, "f": 6.0})
            time.sleep(0.3)
            self.shot(f"stage-{paths}-zoom")
            self.do("fitAll")
        self.do("continuous", False)

    # --- compute -----------------------------------------------------------------------------------------------
    def compute(self):
        app = self.app
        self.do("show", "compute")
        self.do("computeBench", 12)
        app.wait(lambda: app.get("benchCompute", "benchResult"), timeout=240)
        r = json.loads(app.get("benchCompute", "benchResult"))
        self.lines += ["", f"### Compute: {r['width']} x {r['height']} Pixel, Graustufen + Kontrast + Helligkeit", "", "| Weg | ms |", "|---|---:|",
                       f"| CPU, ein Kern | {r['cpu1Ms']:.1f} |", f"| CPU, {r['threads']} Threads | {r['cpuMs']:.1f} |",
                       f"| GPU Compute ({'ja' if r['gpu'] else 'Ersatz: ' + r['error']}) | {r['gpuComputeMs']:.1f} |",
                       f"| GPU: Bild hochladen, einmalig | {r['gpuUploadMs']:.1f} |", f"| GPU: alles zurücklesen, nur ohne Fenster nötig | {r['gpuReadbackMs']:.1f} |", "",
                       f"Größte Abweichung GPU gegen CPU in Graustufen (0..255): Grau {r['maxDiffGrey']}, Schwellwert {r['thresholdMaxDiff']}, Ordered {r['orderedMaxDiff']}, Kanten {r['edgesMaxDiff']}.",
                       f"Schwellwert CPU {r['thresholdCpuMs']:.1f} / GPU {r['thresholdGpuMs']:.1f} ms, Ordered CPU {r['orderedCpuMs']:.1f} / GPU {r['orderedGpuMs']:.1f} ms, Kanten CPU {r['edgesCpuMs']:.1f} / GPU {r['edgesGpuMs']:.1f} ms."]
        print("\n".join(self.lines[-12:]), flush=True)
        self.do("computeLoad", 12)
        app.wait(lambda: app.get("benchCompute", "backend") != "", timeout=30)
        time.sleep(2.0)
        backend = app.get("benchCompute", "backend")
        self.do("computeSet", {"mode": 0, "contrast": 35, "brightness": 10})
        time.sleep(0.5)
        self.shot("compute-grey")
        self.do("continuous", True)
        m = self.sample(2.0)
        self.do("continuous", False)
        self.header("Live-Vorschau im Fenster")
        self.row("12 MP, jedes Bild neu gerechnet", m, f"Weg {backend}")
        for mode, name in ((1, "schwellwert"), (2, "ordered"), (3, "kanten")):
            self.do("computeSet", {"mode": mode, "contrast": 35, "brightness": 10})
            time.sleep(0.5)
            self.shot(f"compute-{name}")


def run(exe, port, tag, env, counts, stage_sizes):
    e = dict(env)
    e["LUMACUT_BENCH"] = "1"
    e["PATH"] = QT_BIN + os.pathsep + os.environ["PATH"]
    e["QT_FORCE_STDERR_LOGGING"] = "1"
    app = App(exe=exe, port=port, env=e)
    try:
        app.wait(lambda: app.stats()["firstFrameMs"] > 0, timeout=60)
        app.call("gpuBench")
        time.sleep(0.5)
        s = app.stats()
        b = Bench(app, tag)
        b.lines += [f"## {tag}: {s.get('gpuName')} ({s.get('gpuType')}, {s.get('api')}), vsync {'an' if s.get('vsync') else 'aus'}, Compute {'ja' if s.get('compute') else 'nein'}, GPU-Zeitstempel {'ja' if s.get('timestamps') else 'nein'}"]
        print(b.lines[-1], flush=True)
        b.segments(counts)
        b.decimation()
        b.looks()
        b.reset_device()
        b.stage(stage_sizes)
        b.compute()
        assert app.proc.poll() is None, "Fenster ist abgestürzt"
        return b.lines
    finally:
        app.close()


def main():
    args = sys.argv[1:]
    port, only = 9601, None
    if "--port" in args:
        i = args.index("--port"); port = int(args[i + 1]); del args[i:i + 2]
    if "--only" in args:
        i = args.index("--only"); only = args[i + 1]; del args[i:i + 2]
    exe = args[0] if args else os.environ.get("LUMACUT_EXE") or str(OUT / "LumaCutStudio.exe")
    SHOTS.mkdir(parents=True, exist_ok=True)
    out = ["# GPU-Messung LumaCut Studio", "", time.strftime("%d.%m.%Y %H:%M")]
    if only != "sw":
        out += [""] + run(exe, port, "hw", {}, (100_000, 1_000_000, 5_000_000, 20_000_000), ((10_000, 16), (100_000, 16), (100_000, 64)))
    if only != "hw":
        # The software adapter has to work (CI has no GPU), not to be fast: only smaller loads.
        out += [""] + run(exe, port, "sw", {"QSG_RHI_PREFER_SOFTWARE_RENDERER": "1"}, (100_000, 1_000_000), ((10_000, 16),))
    (OUT / ("bench.md" if not only else f"bench-{only}.md")).write_text("\n".join(out) + "\n", encoding="utf-8")
    print("Geschrieben:", OUT, flush=True)


if __name__ == "__main__":
    main()
